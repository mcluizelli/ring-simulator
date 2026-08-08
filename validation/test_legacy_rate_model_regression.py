"""Byte-exact regression fixtures for the frozen legacy rate model.

The expected records are hard-coded from the frozen v10.1, v11.1, and v5.5
CSVs.  The tests reconstruct each case from a fresh topology (and, for C10, a
fresh stateful congestion model) rather than reading those CSVs at test time.
Floating-point fields are compared by their IEEE-754 binary64 representation.
"""

from __future__ import annotations

import random
import struct
import sys
import unittest
from pathlib import Path


RING_ROOT = Path(__file__).resolve().parents[1]
if str(RING_ROOT) not in sys.path:
    sys.path.insert(0, str(RING_ROOT))

from sim import (  # noqa: E402
    CongestionModel,
    FatTree,
    RATE_ALLOCATOR_LINK_LOCAL,
    compute_ring_theoretical_time,
    run_ring_transfer_proportional,
    run_simple_ring_transfer,
)


MIB = 1024 * 1024
DT_S = 5e-5
PLACEMENT_SEED = 9000


def binary64_hex(value: float) -> str:
    """Return the exact IEEE-754 binary64 payload of ``value``."""
    return struct.pack(">d", float(value)).hex()


class LegacyRateModelRegressionTest(unittest.TestCase):
    def assert_binary64(self, actual: float, expected_hex: str) -> None:
        self.assertEqual(binary64_hex(actual), expected_hex)

    def test_n0_equal_snapshot(self) -> None:
        """Reproduce the frozen v10.1 3tier_nb/P64/seed0/k8 record."""
        def reproduce(rate_allocator=None):
            topo = FatTree(16)
            ring = random.Random(PLACEMENT_SEED).sample(topo.hosts, 64)
            mode = {} if rate_allocator is None else {"rate_allocator": rate_allocator}

            completion = run_simple_ring_transfer(
                topo=topo,
                ring=ring,
                bytes_per_neighbor=64 * MIB,
                flows_per_neighbor=8,
                dt_s=DT_S,
                congestion=None,
                **mode,
            )
            theory = compute_ring_theoretical_time(
                topo=topo,
                ring=ring,
                bytes_per_neighbor=64 * MIB,
                flows_per_neighbor=8,
                **mode,
            )
            top_links = set(topo.get_edges_by_layer()["agg_core"])
            contention = theory["edge_contention"]
            return {
                "fabric": "3tier_nb",
                "P": len(ring),
                "seed": 0,
                "k": 8,
                "t_sim": completion,
                "opt_time": theory["theoretical_time_s"],
                "equal_split_gap": completion / theory["theoretical_time_s"] - 1.0,
                "Bstar_Bps": theory["bottleneck_bandwidth_Bps"],
                "top_used": sum(
                    1 for edge in top_links if contention.get(edge, 0) > 0
                ),
                "max_top_contention": max(
                    (contention.get(edge, 0) for edge in top_links), default=0
                ),
            }

        for invocation, allocator in (
            ("default", None),
            ("explicit", RATE_ALLOCATOR_LINK_LOCAL),
        ):
            with self.subTest(invocation=invocation):
                actual = reproduce(allocator)
                self.assertEqual(
                    {key: actual[key] for key in ("fabric", "P", "seed", "k")},
                    {"fabric": "3tier_nb", "P": 64, "seed": 0, "k": 8},
                )
                self.assert_binary64(actual["t_sim"], "3f761e4f765fd8a8")
                self.assert_binary64(actual["opt_time"], "3f75fd7fe1796495")
                self.assert_binary64(actual["equal_split_gap"], "3f77df7ffffffc00")
                self.assert_binary64(actual["Bstar_Bps"], "42074876e8000000")
                self.assertEqual(actual["top_used"], 748)
                self.assertEqual(actual["max_top_contention"], 4)

    def test_o0_proportional_snapshot(self) -> None:
        """Reproduce the frozen v11.1 3tier_os4/P64/seed0/k8 record."""
        def reproduce(rate_allocator=None):
            topo = FatTree(16, oversub=4.0)
            ring = random.Random(PLACEMENT_SEED).sample(topo.hosts, 64)
            mode = {} if rate_allocator is None else {"rate_allocator": rate_allocator}
            completion = run_ring_transfer_proportional(
                topo=topo,
                ring=ring,
                bytes_per_neighbor=64 * MIB,
                flows_per_neighbor=8,
                dt_s=DT_S,
                congestion=None,
                **mode,
            )
            return {
                "fabric": "3tier_os4",
                "P": len(ring),
                "seed": 0,
                "k": 8,
                "t_prop": completion,
            }

        for invocation, allocator in (
            ("default", None),
            ("explicit", RATE_ALLOCATOR_LINK_LOCAL),
        ):
            with self.subTest(invocation=invocation):
                actual = reproduce(allocator)
                self.assertEqual(
                    {key: actual[key] for key in ("fabric", "P", "seed", "k")},
                    {"fabric": "3tier_os4", "P": 64, "seed": 0, "k": 8},
                )
                self.assert_binary64(actual["t_prop"], "3f7e4f765fd8ad98")

    def test_c10_congested_baseline_snapshot(self) -> None:
        """Reproduce the frozen v5.5 baseline record for one-based run 1.

        The campaign driver uses zero-based ``run_idx=0`` to construct this
        case, while its durable CSV records the public run label as ``run=1``.
        """
        run_idx = 0
        affected_fraction = 0.1
        topology_seed = 0xCAFE
        congestion_seed = (
            topology_seed
            + run_idx * 10_000_001
            + int(affected_fraction * 1000)
        )

        def reproduce(rate_allocator=None):
            topo = FatTree(16, seed=topology_seed)
            ring = random.Random(PLACEMENT_SEED).sample(topo.hosts, 64)
            congestion = CongestionModel(
                mode="onoff",
                seed=congestion_seed,
                affected_fraction=affected_fraction,
                congested_util_low=0.50,
                congested_util_high=0.95,
                normal_util_low=0.00,
                normal_util_high=0.05,
                p_on=0.01,
                p_off=0.005,
                target_layers=["agg_core", "edge_agg"],
            )
            mode = {} if rate_allocator is None else {"rate_allocator": rate_allocator}
            completion = run_simple_ring_transfer(
                topo=topo,
                ring=ring,
                bytes_per_neighbor=256 * MIB,
                flows_per_neighbor=1,
                dt_s=DT_S,
                congestion=congestion,
                **mode,
            )
            return {
                "run": run_idx + 1,
                # The CSV preserves the topology/run seed; the congestion process
                # uses the deterministic affected-fraction offset above.
                "seed": topology_seed,
                "ring_size": len(ring),
                "affected_fraction": affected_fraction,
                "method": "baseline",
                "completion_time_s": completion,
                "final_k_mean": 1.0,
                "final_k_max": 1,
            }

        self.assertEqual(congestion_seed, 52066)
        for invocation, allocator in (
            ("default", None),
            ("explicit", RATE_ALLOCATOR_LINK_LOCAL),
        ):
            with self.subTest(invocation=invocation):
                actual = reproduce(allocator)
                self.assertEqual(actual["run"], 1)
                self.assertEqual(actual["seed"], 51966)
                self.assertEqual(actual["ring_size"], 64)
                self.assert_binary64(
                    actual["affected_fraction"], "3fb999999999999a"
                )
                self.assertEqual(actual["method"], "baseline")
                self.assert_binary64(
                    actual["completion_time_s"], "3faebedfa43fe677"
                )
                self.assert_binary64(actual["final_k_mean"], "3ff0000000000000")
                self.assertEqual(actual["final_k_max"], 1)


if __name__ == "__main__":
    unittest.main()
