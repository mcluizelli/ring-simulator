"""Read-only structural gates for the fixed n=5 allocator pilot driver."""

from __future__ import annotations

import contextlib
import io
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from experiments import run_rate_allocator_pilot as pilot
import sim


class RateAllocatorPilotDriverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = pilot.build_plan()

    def test_fixed_matrix_cardinality_and_balance(self) -> None:
        self.assertEqual(len(self.plan["arms"]), 18)
        self.assertEqual(len(self.plan["pairs"]), 90)
        self.assertEqual(self.plan["simulation_count"], 180)
        self.assertEqual(self.plan["family_pair_counts"], pilot.EXPECTED_FAMILY_PAIRS)
        first = {
            allocator: sum(
                pair["execution_order"][0] == allocator
                for pair in self.plan["pairs"]
            )
            for allocator in pilot.ALLOCATORS
        }
        self.assertEqual(first, {pilot.ALLOCATORS[0]: 45, pilot.ALLOCATORS[1]: 45})

    def test_derived_seeds_and_oracle_cardinality(self) -> None:
        exact = 0
        diagnostic = 0
        for pair in self.plan["pairs"]:
            config = pair["config"]
            sample = pair["sample_id"]
            self.assertEqual(config["placement_seed"], 9000 + sample)
            if config["family"] == "controller":
                topo_seed = 0xCAFE + sample * 10_000_001
                self.assertEqual(config["topology_seed"], topo_seed)
                self.assertEqual(
                    config["congestion"]["seed"],
                    topo_seed + int(config["affected_fraction"] * 1000),
                )
            if config["family"] == "background":
                rate = config["arrival_rate_fps"]
                expected = (
                    None
                    if rate == 0
                    else 0xBEEF + sample * 10_000_001 + rate
                )
                self.assertEqual(config["background_seed"], expected)
            if config["oracle_kind"] == "new_diagnostic":
                diagnostic += 1
            else:
                exact += 1
        self.assertEqual((exact, diagnostic), (85, 5))

    def test_all_85_oracle_keys_resolve(self) -> None:
        indexes = pilot._oracle_indexes()
        resolved = 0
        for pair in self.plan["pairs"]:
            row = pilot._oracle_row(pair, indexes)
            if pair["config"]["oracle_kind"] == "new_diagnostic":
                self.assertIsNone(row)
            else:
                self.assertIsNotNone(row)
                resolved += 1
        self.assertEqual(resolved, 85)

    def test_authorization_binds_plan_and_both_sources(self) -> None:
        baseline = pilot._authorization_sha256(
            self.plan, sim_hash="a" * 64, driver_hash="b" * 64
        )
        self.assertNotEqual(
            baseline,
            pilot._authorization_sha256(
                self.plan, sim_hash="c" * 64, driver_hash="b" * 64
            ),
        )
        self.assertNotEqual(
            baseline,
            pilot._authorization_sha256(
                self.plan, sim_hash="a" * 64, driver_hash="d" * 64
            ),
        )

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "must_not_exist"
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                pilot.dry_run(self.plan, output)
            self.assertFalse(output.exists())
            text = capture.getvalue()
            self.assertIn("CANONICAL_PLAN_JSON_BEGIN", text)
            self.assertIn("CANONICAL_PLAN_JSON_END", text)
            self.assertIn("NO FILES, NO SIMULATIONS", text)

    def test_adaptive_overdelivery_gate_is_local_ulp_scale(self) -> None:
        target = float(256 * 1024 * 1024)
        config = {
            "runner": "adaptive",
            "bytes_per_neighbor": target,
            "ring_size": 1,
        }

        def engine_with(sent: float) -> SimpleNamespace:
            flow = sim.Flow(
                fid=1,
                five_tuple=sim.Flow5Tuple(
                    src="h0_0_0", dst="h0_0_1", sport=10000, dport=20000
                ),
                path=["h0_0_0", "e0_0", "h0_0_1"],
                remaining_bytes=0.0,
                sent_bytes=sent,
            )
            return SimpleNamespace(flows={1: flow})

        accepted = target + 24 * math.ulp(target)
        report = pilot._conservation_gate(config, {}, engine_with(accepted))
        self.assertTrue(report["passed"])

        rejected = target + 128 * math.ulp(target)
        with self.assertRaises(RuntimeError):
            pilot._conservation_gate(config, {}, engine_with(rejected))

    def test_simple_conservation_gate_is_local_ulp_scale(self) -> None:
        target = float(256 * 1024 * 1024)
        config = {
            "runner": "simple",
            "bytes_per_neighbor": target,
            "ring_size": 1,
        }

        def engine_with(sent: float) -> SimpleNamespace:
            flow = sim.Flow(
                fid=1,
                five_tuple=sim.Flow5Tuple(
                    src="h0_0_0", dst="h0_0_1", sport=10000, dport=20000
                ),
                path=["h0_0_0", "e0_0", "h0_0_1"],
                remaining_bytes=0.0,
                sent_bytes=sent,
            )
            return SimpleNamespace(flows={1: flow})

        accepted = target - 25 * math.ulp(target)
        report = pilot._conservation_gate(config, 0.031, engine_with(accepted))
        self.assertTrue(report["passed"])

        rejected = target - 128 * math.ulp(target)
        with self.assertRaises(RuntimeError):
            pilot._conservation_gate(config, 0.031, engine_with(rejected))

    def test_allreduce_per_flow_gate_is_local_ulp_scale(self) -> None:
        requested = float(16 * 1024 * 1024)
        self.assertTrue(
            pilot._within_local_ulps(
                requested - 6 * math.ulp(requested), requested, ulps=64
            )
        )
        self.assertFalse(
            pilot._within_local_ulps(
                requested - 128 * math.ulp(requested), requested, ulps=64
            )
        )


if __name__ == "__main__":
    unittest.main()
