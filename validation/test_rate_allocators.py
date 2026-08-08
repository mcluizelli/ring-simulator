"""Correctness gates for the selectable flow-rate allocators."""

from __future__ import annotations

import copy
import math
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


RING_ROOT = Path(__file__).resolve().parents[1]
if str(RING_ROOT) not in sys.path:
    sys.path.insert(0, str(RING_ROOT))

import sim as sim_module  # noqa: E402

from sim import (  # noqa: E402
    AdaptiveConfig,
    CongestionModel,
    FatTree,
    Flow5Tuple,
    FlowLevelSimulator,
    RATE_ALLOCATOR_LINK_LOCAL,
    RATE_ALLOCATOR_NETWORK_MAXMIN,
    allocate_flow_rates,
    compute_ring_theoretical_time,
    run_adaptive_ring_transfer,
    run_ring_allreduce,
    run_ring_transfer_proportional,
    run_simple_ring_transfer,
)


Edge = tuple[str, str]
MIB = 1024 * 1024


def assert_maxmin_guards(
    case: unittest.TestCase,
    paths: dict[int, list[Edge]],
    capacities: dict[Edge, float],
    rates: dict[int, float],
) -> None:
    """Check capacity feasibility and a max-min bottleneck certificate."""
    users: dict[Edge, list[int]] = {}
    for fid, edges in paths.items():
        for edge in edges:
            users.setdefault(edge, []).append(fid)

    loads = {
        edge: sum(rates[fid] for fid in fids)
        for edge, fids in users.items()
    }
    for edge, load in loads.items():
        tolerance = 1e-8 * max(abs(capacities[edge]), abs(load))
        case.assertLessEqual(load, capacities[edge] + tolerance)

    for fid, edges in paths.items():
        if not edges:
            case.assertTrue(math.isinf(rates[fid]))
            continue
        certificate = any(
            math.isclose(
                loads[edge],
                capacities[edge],
                rel_tol=1e-8,
                abs_tol=0.0,
            )
            and all(
                rates[other]
                <= rates[fid] + 1e-8 * max(abs(rates[fid]), abs(rates[other]))
                for other in users[edge]
            )
            for edge in edges
        )
        case.assertTrue(certificate, f"flow {fid} lacks a bottleneck certificate")


class RateAllocatorUnitTest(unittest.TestCase):
    def test_unrelated_large_capacity_does_not_merge_small_bottlenecks(self) -> None:
        paths = {
            1: [("a", "b")],
            2: [("c", "d")],
            3: [("e", "f")],
        }
        capacities = {
            ("a", "b"): 1e-6,
            ("c", "d"): 0.5,
            ("e", "f"): 1e12,
        }
        rates = allocate_flow_rates(
            paths,
            capacities,
            RATE_ALLOCATOR_NETWORK_MAXMIN,
        )
        self.assertEqual(rates, {1: 1e-6, 2: 0.5, 3: 1e12})
        assert_maxmin_guards(self, paths, capacities, rates)

    def test_tiny_capacities_preserve_scale_and_distinct_bottlenecks(self) -> None:
        independent = allocate_flow_rates(
            {1: [("a", "b")], 2: [("c", "d")]},
            {("a", "b"): 0.0, ("c", "d"): 5e-13},
            RATE_ALLOCATOR_NETWORK_MAXMIN,
        )
        self.assertEqual(independent, {1: 0.0, 2: 5e-13})

        factor = 1e-15
        shared = ("s", "a")
        paths = {
            1: [shared, ("a", "x")],
            2: [shared, ("a", "y")],
        }
        capacities = {
            shared: 100.0 * factor,
            ("a", "x"): 20.0 * factor,
            ("a", "y"): 100.0 * factor,
        }
        rates = allocate_flow_rates(
            paths,
            capacities,
            RATE_ALLOCATOR_NETWORK_MAXMIN,
        )
        self.assertTrue(math.isclose(rates[1], 20.0 * factor, rel_tol=1e-15))
        self.assertTrue(math.isclose(rates[2], 80.0 * factor, rel_tol=1e-15))
        assert_maxmin_guards(self, paths, capacities, rates)

    def test_models_coincide_at_a_single_shared_bottleneck(self) -> None:
        edge = ("a", "b")
        paths = {1: [edge], 2: [edge], 3: [edge]}
        capacities = {edge: 90.0}
        legacy = allocate_flow_rates(
            paths, capacities, RATE_ALLOCATOR_LINK_LOCAL
        )
        maxmin = allocate_flow_rates(
            paths, capacities, RATE_ALLOCATOR_NETWORK_MAXMIN
        )
        self.assertEqual(legacy, {1: 30.0, 2: 30.0, 3: 30.0})
        self.assertEqual(maxmin, legacy)

    def test_canonical_stranded_capacity_counterexample(self) -> None:
        shared = ("s", "a")
        paths = {
            1: [shared, ("a", "x")],
            2: [shared, ("a", "y")],
        }
        capacities = {shared: 100.0, ("a", "x"): 20.0, ("a", "y"): 100.0}

        legacy = allocate_flow_rates(
            paths, capacities, RATE_ALLOCATOR_LINK_LOCAL
        )
        maxmin = allocate_flow_rates(
            paths, capacities, RATE_ALLOCATOR_NETWORK_MAXMIN
        )

        self.assertEqual(legacy, {1: 20.0, 2: 50.0})
        self.assertEqual(maxmin, {1: 20.0, 2: 80.0})
        assert_maxmin_guards(self, paths, capacities, maxmin)

    def test_random_lower_bound_feasibility_and_certificates(self) -> None:
        rng = random.Random(20260806)
        for sample in range(1000):
            n_links = rng.randint(1, 8)
            n_flows = rng.randint(1, 12)
            links = [(f"u{i}", f"v{i}") for i in range(n_links)]
            capacities = {edge: rng.uniform(0.01, 100.0) for edge in links}
            paths = {
                fid: rng.sample(links, rng.randint(1, min(4, n_links)))
                for fid in range(n_flows)
            }
            legacy = allocate_flow_rates(
                paths, capacities, RATE_ALLOCATOR_LINK_LOCAL
            )
            maxmin = allocate_flow_rates(
                paths, capacities, RATE_ALLOCATOR_NETWORK_MAXMIN
            )
            for fid in paths:
                tolerance = 1e-8 * max(1.0, maxmin[fid])
                self.assertLessEqual(
                    legacy[fid], maxmin[fid] + tolerance, f"sample={sample}"
                )
            assert_maxmin_guards(self, paths, capacities, maxmin)

    def test_zero_capacity_pathless_flow_and_directed_edges(self) -> None:
        forward = ("a", "b")
        reverse = ("b", "a")
        blocked = ("x", "y")
        paths = {1: [forward], 2: [reverse], 3: [blocked], 4: []}
        capacities = {forward: 10.0, reverse: 30.0, blocked: 0.0}

        rates = allocate_flow_rates(
            paths, capacities, RATE_ALLOCATOR_NETWORK_MAXMIN
        )

        self.assertEqual(rates[1], 10.0)
        self.assertEqual(rates[2], 30.0)
        self.assertEqual(rates[3], 0.0)
        self.assertTrue(math.isinf(rates[4]))
        assert_maxmin_guards(self, paths, capacities, rates)

    def test_flow_order_id_invariance_and_capacity_scaling(self) -> None:
        paths = {
            7: [("a", "b"), ("b", "c")],
            2: [("a", "b"), ("b", "d")],
            9: [("b", "d")],
        }
        capacities = {("a", "b"): 90.0, ("b", "c"): 15.0, ("b", "d"): 80.0}
        expected = allocate_flow_rates(
            paths, capacities, RATE_ALLOCATOR_NETWORK_MAXMIN
        )
        reversed_paths = dict(reversed(list(paths.items())))
        reordered = allocate_flow_rates(
            reversed_paths, dict(reversed(list(capacities.items()))),
            RATE_ALLOCATOR_NETWORK_MAXMIN,
        )
        self.assertEqual(expected, reordered)

        remap = {7: 101, 2: 55, 9: 3}
        remapped_paths = {remap[fid]: edges for fid, edges in paths.items()}
        remapped = allocate_flow_rates(
            remapped_paths, capacities, RATE_ALLOCATOR_NETWORK_MAXMIN
        )
        self.assertEqual(
            expected,
            {fid: remapped[remap[fid]] for fid in paths},
        )

        factor = 3.5
        scaled = allocate_flow_rates(
            paths,
            {edge: factor * cap for edge, cap in capacities.items()},
            RATE_ALLOCATOR_NETWORK_MAXMIN,
        )
        for fid in paths:
            self.assertAlmostEqual(scaled[fid], factor * expected[fid], places=12)

    def test_invalid_inputs_fail_before_congestion_attachment(self) -> None:
        topo = FatTree(4)
        congestion = CongestionModel(affected_fraction=0.1)
        with self.assertRaisesRegex(ValueError, "Unknown rate_allocator"):
            FlowLevelSimulator(
                topo,
                congestion=congestion,
                rate_allocator="not-a-rate-model",
            )
        self.assertIsNone(congestion._affected)

        duplicate = {1: [("a", "b"), ("a", "b")]}
        with self.assertRaisesRegex(ValueError, "same directed edge twice"):
            allocate_flow_rates(
                duplicate,
                {("a", "b"): 1.0},
                RATE_ALLOCATOR_NETWORK_MAXMIN,
            )

        for bad_capacity in (-1.0, float("nan"), float("inf")):
            with self.subTest(capacity=bad_capacity):
                with self.assertRaisesRegex(ValueError, "finite and non-negative"):
                    allocate_flow_rates(
                        {1: [("a", "b")]},
                        {("a", "b"): bad_capacity},
                        RATE_ALLOCATOR_NETWORK_MAXMIN,
                    )

    def test_mode_aware_static_reference(self) -> None:
        class StaticTopology:
            edge_of = {
                ("u", "v"): 100.0,
                ("v", "x"): 20.0,
                ("v", "y"): 100.0,
                ("p", "q"): 100.0,
                ("r", "t"): 100.0,
            }

            def ecmp_pick_path(self, five_tuple):
                if five_tuple.src == "left":
                    return ["u", "v", "x"] if five_tuple.sport % 100 == 0 else ["u", "v", "y"]
                return ["p", "q"] if five_tuple.sport % 100 == 0 else ["r", "t"]

        topo = StaticTopology()
        ring = ["left", "right"]
        legacy = compute_ring_theoretical_time(
            topo,
            ring,
            bytes_per_neighbor=700.0,
            flows_per_neighbor=2,
            rate_allocator=RATE_ALLOCATOR_LINK_LOCAL,
        )
        maxmin = compute_ring_theoretical_time(
            topo,
            ring,
            bytes_per_neighbor=700.0,
            flows_per_neighbor=2,
            rate_allocator=RATE_ALLOCATOR_NETWORK_MAXMIN,
        )

        self.assertEqual(legacy["bottleneck_bandwidth_Bps"], 70.0)
        self.assertEqual(maxmin["bottleneck_bandwidth_Bps"], 100.0)
        self.assertEqual(legacy["theoretical_time_s"], 10.0)
        self.assertEqual(maxmin["theoretical_time_s"], 7.0)


class RateAllocatorRunnerTest(unittest.TestCase):
    @staticmethod
    def topology_and_ring():
        topo = FatTree(4)
        ring = random.Random(1234).sample(topo.hosts, 4)
        return topo, ring

    def test_every_runner_propagates_invalid_mode(self) -> None:
        calls = []

        topo, ring = self.topology_and_ring()
        calls.append(
            lambda: run_simple_ring_transfer(
                topo, ring, MIB, 1, rate_allocator="invalid"
            )
        )
        topo, ring = self.topology_and_ring()
        calls.append(
            lambda: run_ring_transfer_proportional(
                topo, ring, MIB, 2, rate_allocator="invalid"
            )
        )
        topo, ring = self.topology_and_ring()
        calls.append(
            lambda: run_adaptive_ring_transfer(
                topo,
                ring,
                MIB,
                AdaptiveConfig(k_max=2),
                rate_allocator="invalid",
            )
        )
        topo, ring = self.topology_and_ring()
        calls.append(
            lambda: run_ring_allreduce(
                topo, ring, 4 * MIB, rate_allocator="invalid"
            )
        )

        for call in calls:
            with self.subTest(runner=call):
                with self.assertRaisesRegex(ValueError, "Unknown rate_allocator"):
                    call()

    def test_network_maxmin_runner_smoke_and_conservation(self) -> None:
        topo, ring = self.topology_and_ring()
        simple = run_simple_ring_transfer(
            topo,
            ring,
            4 * MIB,
            2,
            rate_allocator=RATE_ALLOCATOR_NETWORK_MAXMIN,
        )
        self.assertGreater(simple, 0.0)

        topo, ring = self.topology_and_ring()
        proportional = run_ring_transfer_proportional(
            topo,
            ring,
            4 * MIB,
            2,
            return_metrics=True,
            rate_allocator=RATE_ALLOCATOR_NETWORK_MAXMIN,
        )
        self.assertGreater(proportional["completion_time_s"], 0.0)
        for delivered in proportional["per_edge_delivered_bytes"].values():
            self.assertAlmostEqual(delivered, 4 * MIB, delta=1e-6)

        topo, ring = self.topology_and_ring()
        adaptive = run_adaptive_ring_transfer(
            topo,
            ring,
            4 * MIB,
            AdaptiveConfig(k_max=2),
            rate_allocator=RATE_ALLOCATOR_NETWORK_MAXMIN,
        )
        self.assertGreater(adaptive["completion_time_s"], 0.0)
        self.assertEqual(len(adaptive["final_k_per_edge"]), len(ring))

        topo, ring = self.topology_and_ring()
        allreduce = run_ring_allreduce(
            topo,
            ring,
            4 * MIB,
            flows_per_neighbor=2,
            rate_allocator=RATE_ALLOCATOR_NETWORK_MAXMIN,
        )
        self.assertGreater(allreduce.total_time_s, 0.0)
        self.assertEqual(len(allreduce.step_times_s), 2 * (len(ring) - 1))

    def test_snapshot_rates_include_idle_candidate_and_are_read_only(self) -> None:
        class FixedTopology:
            edge_of = {
                ("s", "a"): 100.0,
                ("a", "x"): 20.0,
                ("a", "y"): 100.0,
            }

            def ecmp_pick_path(self, five_tuple):
                if five_tuple.sport == 1:
                    return ["s", "a", "x"]
                return ["s", "a", "y"]

        engine = FlowLevelSimulator(
            FixedTopology(),
            dt_s=1.0,
            rate_allocator=RATE_ALLOCATOR_NETWORK_MAXMIN,
        )
        idle = engine.add_flow(Flow5Tuple("left", "right", 1, 9), 20.0)
        active = engine.add_flow(Flow5Tuple("left", "right", 2, 9), 160.0)
        engine.flows[idle].remaining_bytes = 0.0
        engine.flows[idle].sent_bytes = 20.0
        engine.flows[idle].last_rate_Bps = 7.0
        engine.flows[active].last_rate_Bps = 8.0
        before = {
            "time_s": engine.time_s,
            "flows": {
                fid: (
                    flow.remaining_bytes,
                    flow.sent_bytes,
                    flow.last_rate_Bps,
                )
                for fid, flow in engine.flows.items()
            },
            "cache_key": engine._maxmin_active_key,
            "cache_paths": copy.deepcopy(engine._maxmin_flow_edges),
            "cache_users": copy.deepcopy(engine._maxmin_link_users),
            "edge_bytes_sent": copy.deepcopy(engine.edge_bytes_sent),
        }

        together = engine.snapshot_flow_rates([idle, active])
        active_only = engine.snapshot_flow_rates([active])

        self.assertEqual(together, {idle: 20.0, active: 80.0})
        self.assertEqual(active_only, {active: 100.0})
        after = {
            "time_s": engine.time_s,
            "flows": {
                fid: (
                    flow.remaining_bytes,
                    flow.sent_bytes,
                    flow.last_rate_Bps,
                )
                for fid, flow in engine.flows.items()
            },
            "cache_key": engine._maxmin_active_key,
            "cache_paths": copy.deepcopy(engine._maxmin_flow_edges),
            "cache_users": copy.deepcopy(engine._maxmin_link_users),
            "edge_bytes_sent": copy.deepcopy(engine.edge_bytes_sent),
        }
        self.assertEqual(after, before)

    def test_snapshot_rates_follow_current_capacity_while_qp_is_idle(self) -> None:
        left_edge = ("left", "sink")
        right_edge = ("right", "sink")

        class FixedTopology:
            edge_of = {left_edge: 100.0, right_edge: 100.0}

            def ecmp_pick_path(self, five_tuple):
                if five_tuple.sport == 1:
                    return list(left_edge)
                return list(right_edge)

        class MutableResidual:
            target_layers = None

            def __init__(self):
                self.capacity = {left_edge: 10.0, right_edge: 90.0}

            def attach(self, all_edges, target_edges=None):
                self.attached = tuple(all_edges)

            def update_tick(self):
                raise AssertionError("snapshot must not advance congestion")

            def residual_capacity(self, edge, nominal):
                return self.capacity.get(edge, nominal)

        congestion = MutableResidual()
        engine = FlowLevelSimulator(
            FixedTopology(),
            congestion=congestion,
            rate_allocator=RATE_ALLOCATOR_LINK_LOCAL,
        )
        idle = engine.add_flow(Flow5Tuple("a", "b", 1, 9), 1.0)
        active = engine.add_flow(Flow5Tuple("a", "b", 2, 9), 1.0)
        engine.flows[idle].remaining_bytes = 0.0

        first = engine.snapshot_flow_rates([idle, active])
        congestion.capacity = {left_edge: 90.0, right_edge: 10.0}
        second = engine.snapshot_flow_rates([idle, active])

        self.assertEqual(first, {idle: 10.0, active: 90.0})
        self.assertEqual(second, {idle: 90.0, active: 10.0})
        self.assertEqual(engine.time_s, 0.0)
        self.assertEqual(engine.flows[idle].remaining_bytes, 0.0)

    def test_snapshot_rates_reject_duplicate_and_unknown_ids_before_sampling(self) -> None:
        class FixedTopology:
            edge_of = {("a", "b"): 10.0}

            def ecmp_pick_path(self, five_tuple):
                return ["a", "b"]

        class CountingResidual:
            target_layers = None

            def __init__(self):
                self.samples = 0

            def attach(self, all_edges, target_edges=None):
                pass

            def residual_capacity(self, edge, nominal):
                self.samples += 1
                return nominal

        congestion = CountingResidual()
        engine = FlowLevelSimulator(FixedTopology(), congestion=congestion)
        fid = engine.add_flow(Flow5Tuple("a", "b", 1, 9), 1.0)
        with self.assertRaisesRegex(ValueError, "unique flow IDs"):
            engine.snapshot_flow_rates([fid, fid])
        with self.assertRaisesRegex(ValueError, "unknown flow IDs"):
            engine.snapshot_flow_rates([fid, 999])
        self.assertEqual(congestion.samples, 0)

    def test_proportional_runner_uses_prospective_snapshot_rates(self) -> None:
        capacities = {
            ("u10000", "v10000"): 5.0,
            ("u10001", "v10001"): 5.0,
            ("u10100", "v10100"): 5.0,
            ("u10101", "v10101"): 1.0,
        }

        class FixedTopology:
            edge_of = capacities

            def ecmp_pick_path(self, five_tuple):
                return [f"u{five_tuple.sport}", f"v{five_tuple.sport}"]

        class CapturingSimulator(FlowLevelSimulator):
            registry = []

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.snapshot_calls = []
                self.__class__.registry.append(self)

            def snapshot_flow_rates(self, flow_ids):
                ordered = tuple(flow_ids)
                self.snapshot_calls.append(ordered)
                return {
                    fid: (0.0 if self.flows[fid].five_tuple.sport == 10100 else 1.0)
                    for fid in ordered
                }

        ring = ["left", "right"]
        with patch.object(sim_module, "FlowLevelSimulator", CapturingSimulator):
            result = run_ring_transfer_proportional(
                FixedTopology(),
                ring,
                10.0,
                2,
                dt_s=1.0,
                window_s=10.0,
                return_metrics=True,
                rate_allocator=RATE_ALLOCATOR_LINK_LOCAL,
            )

        self.assertEqual(result["completion_time_s"], 5.0)
        self.assertEqual(len(CapturingSimulator.registry), 1)
        engine = CapturingSimulator.registry[0]
        self.assertEqual(engine.snapshot_calls, [(3, 4)])
        self.assertEqual(engine.flows[3].remaining_bytes, 0.0)
        self.assertEqual(engine.flows[4].remaining_bytes, 0.0)
        self.assertEqual(result["per_edge_delivered_bytes"], {0: 10.0, 1: 10.0})

    def test_proportional_runner_retains_split_on_zero_rate_snapshot(self) -> None:
        class FixedTopology:
            edge_of = {
                ("left", "right"): 10.0,
                ("right", "left"): 10.0,
            }

            def ecmp_pick_path(self, five_tuple):
                return [five_tuple.src, five_tuple.dst]

        class ZeroOnceSimulator(FlowLevelSimulator):
            registry = []

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.zero_snapshot_before = None
                self.retention_checked = False
                self.__class__.registry.append(self)

            def snapshot_flow_rates(self, flow_ids):
                if self.zero_snapshot_before is None:
                    self.zero_snapshot_before = {
                        fid: self.flows[fid].remaining_bytes for fid in flow_ids
                    }
                    return {fid: 0.0 for fid in flow_ids}
                return super().snapshot_flow_rates(flow_ids)

            def step(self):
                if (
                    self.zero_snapshot_before is not None
                    and not self.retention_checked
                ):
                    current = {
                        fid: self.flows[fid].remaining_bytes
                        for fid in self.zero_snapshot_before
                    }
                    if current != self.zero_snapshot_before:
                        raise AssertionError("zero-rate snapshot changed the split")
                    self.retention_checked = True
                return super().step()

        with patch.object(sim_module, "FlowLevelSimulator", ZeroOnceSimulator):
            result = run_ring_transfer_proportional(
                FixedTopology(),
                ["left", "right"],
                10.0,
                2,
                dt_s=0.1,
                window_s=0.1,
                max_steps=1000,
                return_metrics=True,
                rate_allocator=RATE_ALLOCATOR_LINK_LOCAL,
            )
        self.assertGreater(result["completion_time_s"], 0.0)
        self.assertEqual(len(ZeroOnceSimulator.registry), 1)
        self.assertTrue(ZeroOnceSimulator.registry[0].retention_checked)
        self.assertEqual(result["per_edge_delivered_bytes"], {0: 10.0, 1: 10.0})

    def test_proportional_snapshot_keeps_external_active_flow(self) -> None:
        class CapturingExternalSimulator(FlowLevelSimulator):
            registry = []

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.snapshot_calls = []
                self.external_fid = self.add_flow(
                    Flow5Tuple(self.topo.hosts[0], self.topo.hosts[-1], 9000, 9999),
                    10**15,
                )
                self.__class__.registry.append(self)

            def snapshot_flow_rates(self, flow_ids):
                self.snapshot_calls.append(tuple(flow_ids))
                return super().snapshot_flow_rates(flow_ids)

        topo, ring = self.topology_and_ring()
        with patch.object(
            sim_module, "FlowLevelSimulator", CapturingExternalSimulator
        ):
            result = run_ring_transfer_proportional(
                topo,
                ring,
                64 * MIB,
                2,
                return_metrics=True,
                rate_allocator=RATE_ALLOCATOR_NETWORK_MAXMIN,
            )
        self.assertGreater(result["completion_time_s"], 0.0)
        engine = CapturingExternalSimulator.registry[0]
        self.assertGreater(len(engine.snapshot_calls), 0)
        self.assertIn(engine.external_fid, engine.snapshot_calls[0])
        self.assertEqual(len(engine.snapshot_calls[0]), 1 + len(ring) * 2)

    def test_proportional_runner_fails_closed_on_pathless_qp_for_all_k(self) -> None:
        class PathlessTopology:
            edge_of = {}

            def ecmp_pick_path(self, five_tuple):
                return [five_tuple.src]

        for flows_per_neighbor in (1, 2):
            with self.subTest(flows_per_neighbor=flows_per_neighbor):
                with self.assertRaisesRegex(RuntimeError, "non-empty path"):
                    run_ring_transfer_proportional(
                        PathlessTopology(),
                        ["left", "right"],
                        10.0,
                        flows_per_neighbor,
                        dt_s=1.0,
                        rate_allocator=RATE_ALLOCATOR_LINK_LOCAL,
                    )

    def test_maxmin_cache_invalidates_after_flow_completion(self) -> None:
        class FixedTopology:
            edge_of = {
                ("s", "a"): 100.0,
                ("a", "x"): 20.0,
                ("a", "y"): 100.0,
            }

            def ecmp_pick_path(self, five_tuple):
                if five_tuple.sport == 1:
                    return ["s", "a", "x"]
                return ["s", "a", "y"]

        engine = FlowLevelSimulator(
            FixedTopology(),
            dt_s=1.0,
            rate_allocator=RATE_ALLOCATOR_NETWORK_MAXMIN,
        )
        first = engine.add_flow(Flow5Tuple("left", "right", 1, 9), 20.0)
        second = engine.add_flow(Flow5Tuple("left", "right", 2, 9), 160.0)

        engine.step()
        self.assertEqual(engine.flows[first].last_rate_Bps, 20.0)
        self.assertEqual(engine.flows[second].last_rate_Bps, 80.0)
        self.assertEqual(engine.flows[first].remaining_bytes, 0.0)

        engine.step()
        self.assertEqual(engine.flows[second].last_rate_Bps, 100.0)
        self.assertEqual(engine.flows[second].remaining_bytes, 0.0)

    def test_maxmin_recomputes_capacity_with_unchanged_active_set(self) -> None:
        class OneLinkTopology:
            edge_of = {("a", "b"): 100.0}

            def ecmp_pick_path(self, five_tuple):
                return ["a", "b"]

        class ChangingCapacity:
            def __init__(self):
                self.tick = 0

            def attach(self, all_edges, target_edges=None):
                self.edges = tuple(all_edges)

            def update_tick(self):
                self.tick += 1

            def residual_capacity(self, edge, nominal):
                return nominal if self.tick == 1 else 40.0

        engine = FlowLevelSimulator(
            OneLinkTopology(),
            dt_s=1.0,
            congestion=ChangingCapacity(),
            rate_allocator=RATE_ALLOCATOR_NETWORK_MAXMIN,
        )
        first = engine.add_flow(Flow5Tuple("a", "b", 1, 9), 1000.0)
        second = engine.add_flow(Flow5Tuple("a", "b", 2, 9), 1000.0)

        engine.step()
        self.assertEqual(engine.flows[first].last_rate_Bps, 50.0)
        self.assertEqual(engine.flows[second].last_rate_Bps, 50.0)

        engine.step()
        self.assertEqual(engine.flows[first].last_rate_Bps, 20.0)
        self.assertEqual(engine.flows[second].last_rate_Bps, 20.0)

    def test_maxmin_cache_invalidates_after_flow_arrival(self) -> None:
        class OneLinkTopology:
            edge_of = {("a", "b"): 100.0}

            def ecmp_pick_path(self, five_tuple):
                return ["a", "b"]

        engine = FlowLevelSimulator(
            OneLinkTopology(),
            dt_s=1.0,
            rate_allocator=RATE_ALLOCATOR_NETWORK_MAXMIN,
        )
        first = engine.add_flow(Flow5Tuple("a", "b", 1, 9), 1000.0)
        engine.step()
        self.assertEqual(engine.flows[first].last_rate_Bps, 100.0)

        second = engine.add_flow(Flow5Tuple("a", "b", 2, 9), 1000.0)
        engine.step()
        self.assertEqual(engine.flows[first].last_rate_Bps, 50.0)
        self.assertEqual(engine.flows[second].last_rate_Bps, 50.0)


if __name__ == "__main__":
    unittest.main()
