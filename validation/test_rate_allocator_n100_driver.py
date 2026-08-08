"""Structural and provenance tests for the fixed paired n=100 campaign."""
from __future__ import annotations

import json
import math
import multiprocessing as mp
import sys
import unittest
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
EXPERIMENTS_DIR = ROOT / "experiments"
if str(EXPERIMENTS_DIR) in sys.path:
    sys.path.remove(str(EXPERIMENTS_DIR))
sys.path.insert(0, str(EXPERIMENTS_DIR))

import run_placement_policies_n1000 as placement_source  # noqa: E402
import run_rate_allocator_n100 as driver  # noqa: E402
import sim  # noqa: E402


class RateAllocatorN100DriverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = driver.build_plan()

    def test_exact_campaign_cardinality(self) -> None:
        self.assertEqual(self.plan["arm_count"], 134)
        self.assertEqual(self.plan["pair_count"], 13_400)
        self.assertEqual(self.plan["simulation_count"], 26_800)
        self.assertEqual(self.plan["arm_family_counts"], driver.EXPECTED_ARM_COUNTS)
        self.assertEqual(self.plan["family_pair_counts"], driver.EXPECTED_FAMILY_PAIRS)

    def test_scientific_matrix_is_80_16_24_8_6(self) -> None:
        by_family = {}
        for arm in self.plan["arms"]:
            by_family.setdefault(arm["family"], []).append(arm)
        self.assertEqual({k: len(v) for k, v in by_family.items()}, driver.EXPECTED_ARM_COUNTS)
        self.assertEqual(
            sum(a["oracle_kind"] == "equal" for a in by_family["static_split"]), 48
        )
        self.assertEqual(
            sum(a["oracle_kind"] == "proportional" for a in by_family["static_split"]),
            32,
        )

    def test_runner_and_allocator_order_counts(self) -> None:
        runner_rows = {
            runner: 2 * sum(p["config"]["runner"] == runner for p in self.plan["pairs"])
            for runner in driver.EXPECTED_RUNNER_ROWS
        }
        self.assertEqual(runner_rows, driver.EXPECTED_RUNNER_ROWS)
        first = {
            allocator: sum(p["execution_order"][0] == allocator for p in self.plan["pairs"])
            for allocator in driver.ALLOCATORS
        }
        self.assertEqual(first, {allocator: 6_700 for allocator in driver.ALLOCATORS})

    def test_every_legacy_pair_has_a_frozen_oracle(self) -> None:
        indexes = driver._oracle_indexes()
        counts = {}
        for pair in self.plan["pairs"]:
            kind = pair["config"]["oracle_kind"]
            key = pair["oracle_key"]
            if kind == "placement":
                packed = (key["policy"], int(key["seed"]), int(key["k"]))
                row = indexes[kind].get(packed)
            else:
                row = driver.core._oracle_row(pair, indexes)
            self.assertIsNotNone(row, pair["pair_id"])
            counts[kind] = counts.get(kind, 0) + 1
        self.assertEqual(
            counts,
            {
                "equal": 4_800,
                "proportional": 3_200,
                "congestion": 1_600,
                "controller": 2_400,
                "background": 800,
                "placement": 600,
            },
        )

    def test_controller_zero_load_is_replayed_without_congestion_object(self) -> None:
        selected = [
            p
            for p in self.plan["pairs"]
            if p["config"]["family"] == "controller"
            and p["config"]["affected_fraction"] == 0.0
        ]
        self.assertEqual(len(selected), 600)
        self.assertTrue(all(p["config"]["congestion"] is None for p in selected))
        sample = next(p for p in selected if p["sample_id"] == 17)
        self.assertEqual(
            sample["config"]["topology_seed"],
            driver.CONTROLLER_SEED_BASE + 17 * driver.SEED_STRIDE,
        )

    def test_controller_is_frozen_not_recalibrated(self) -> None:
        controller = [a for a in self.plan["arms"] if a["family"] == "controller"]
        self.assertEqual(len(controller), 24)
        self.assertTrue(
            all(
                a["controller_evaluation"]
                == "frozen_for_allocator_isolation_no_recalibration"
                for a in controller
            )
        )
        configs = {json.dumps(a["controller"], sort_keys=True) for a in controller}
        self.assertEqual(len(configs), 1)

    def test_placement_rings_match_the_source_driver(self) -> None:
        placement_source._init()
        for policy in placement_source.POLICIES:
            for seed in (0, 17, 99):
                pair = next(
                    p
                    for p in self.plan["pairs"]
                    if p["config"].get("placement_policy") == policy
                    and p["config"]["k"] == 1
                    and p["sample_id"] == seed
                )
                _, actual = driver._make_topology_and_ring(pair["config"])
                expected = placement_source.make_ring(policy, seed)
                self.assertEqual(actual, expected, f"{policy} seed={seed}")

    def test_background_seed_derivation_matches_source(self) -> None:
        for pair in self.plan["pairs"]:
            config = pair["config"]
            if config["family"] != "background":
                continue
            rate = int(config["arrival_rate_fps"])
            expected = (
                None
                if rate == 0
                else driver.BACKGROUND_SEED_BASE
                + pair["sample_id"] * driver.SEED_STRIDE
                + rate
            )
            self.assertEqual(config["background_seed"], expected)

    def test_output_is_investigation_only(self) -> None:
        allowed = driver._validate_output_path(
            "investigations/rate_allocator_n100/structural-test-does-not-exist",
            require_absent=True,
        )
        self.assertIn(driver.OUTPUT_ROOT, allowed.parents)
        with self.assertRaises(RuntimeError):
            driver._validate_output_path("results/forbidden-n100", require_absent=True)

    def test_authorization_binds_wrapper_core_and_sim(self) -> None:
        base = driver._authorization_sha256(self.plan)
        changed_driver = driver._authorization_sha256(self.plan, driver_hash="0" * 64)
        changed_core = driver._authorization_sha256(self.plan, core_hash="0" * 64)
        changed_sim = driver._authorization_sha256(self.plan, sim_hash="0" * 64)
        self.assertEqual(len({base, changed_driver, changed_core, changed_sim}), 4)

    def test_windows_zero_cpu_tick_is_timing_only(self) -> None:
        self.assertEqual(driver._finite_timing_value(0.0, "CPU time"), 0.0)
        self.assertEqual(driver._finite_timing_value(0.0, "simulation CPU time"), 0.0)
        with self.assertRaises(RuntimeError):
            driver._finite_timing_value(-1e-9, "CPU time")
        with self.assertRaises(RuntimeError):
            driver._finite_timing_value(0.0, "completion time")

    def test_simple_conservation_allows_128_target_ulps_but_rejects_256(self) -> None:
        target = float(256 * 1024 * 1024)
        target_ulp = math.ulp(target)
        config = {
            "runner": "simple",
            "ring_size": 1,
            "bytes_per_neighbor": target,
        }

        def flow(error_ulps: int, *, remaining: float = 0.0) -> SimpleNamespace:
            return SimpleNamespace(
                five_tuple=SimpleNamespace(src="a", dst="b"),
                sent_bytes=target + error_ulps * target_ulp,
                remaining_bytes=remaining,
            )

        with patch.object(driver.core, "_foreground_flows", return_value=[flow(128)]):
            verdict = driver._conservation_gate(config, object(), object())
        self.assertEqual(verdict["roundoff_tolerance_target_ulps"], 128)
        self.assertEqual(verdict["maximum_abs_error_bytes"], 128 * target_ulp)

        with patch.object(driver.core, "_foreground_flows", return_value=[flow(256)]):
            with self.assertRaisesRegex(RuntimeError, "exceeds n=100 audit tolerance"):
                driver._conservation_gate(config, object(), object())

        with patch.object(
            driver.core, "_foreground_flows", return_value=[flow(0, remaining=target_ulp)]
        ):
            with self.assertRaisesRegex(RuntimeError, "foreground bytes remaining"):
                driver._conservation_gate(config, object(), object())

    def test_adaptive_gate_uses_the_authorized_ring_size(self) -> None:
        old_edges = driver._WORKER_EXPECTED_ADAPTIVE_EDGES
        old_k_max = driver._WORKER_EXPECTED_ADAPTIVE_K_MAX
        try:
            driver._WORKER_EXPECTED_ADAPTIVE_EDGES = 16
            driver._WORKER_EXPECTED_ADAPTIVE_K_MAX = 4
            result = {
                "final_k_per_edge": {f"edge-{i}": 1 for i in range(16)},
                "k_history": [],
                "completion_time_s": 1.0,
            }
            self.assertEqual(driver._adaptive_gate(result)["edge_count"], 16)
            result["final_k_per_edge"]["edge-16"] = 1
            with self.assertRaises(RuntimeError):
                driver._adaptive_gate(result)
        finally:
            driver._WORKER_EXPECTED_ADAPTIVE_EDGES = old_edges
            driver._WORKER_EXPECTED_ADAPTIVE_K_MAX = old_k_max

    def test_no_n1000_execution_path(self) -> None:
        self.assertTrue(self.plan["no_n1000_execution_path"])
        parser_text = Path(driver.__file__).read_text(encoding="utf-8")
        self.assertNotIn("--execute-n1000", parser_text)
        self.assertNotIn("--n1000", parser_text)
        self.assertEqual(driver.SAMPLE_IDS, tuple(range(100)))

    def test_frozen_snapshot_is_still_exact(self) -> None:
        snapshot = driver.core.audit_frozen_csvs()
        self.assertEqual(snapshot["count"], 63)
        self.assertEqual(snapshot["total_bytes"], 21_210_573)
        self.assertEqual(
            snapshot["root_sha256"],
            "09a1418e965b9c2d597721ff0d3b1e8db937a19ce667accfa2cf1f469664c24e",
        )

    def test_spawned_paired_worker_uses_the_authorized_sources(self) -> None:
        pair = next(
            p
            for p in self.plan["pairs"]
            if p["config"]["arm_id"] == "controller_p16_af00_adaptive"
            and p["sample_id"] == 0
        )
        sim_hash = driver.core._sha256_file(driver.SIM_PATH)
        driver_hash = driver.core._sha256_file(driver.DRIVER_PATH)
        core_hash = driver.core._sha256_file(driver.CORE_DRIVER_PATH)
        with ProcessPoolExecutor(
            max_workers=1,
            mp_context=mp.get_context("spawn"),
            initializer=driver._worker_init,
            initargs=(sim_hash, driver_hash, core_hash),
        ) as pool:
            checkpoint = pool.submit(driver._run_pair_worker, pair).result(timeout=30)
        driver._attach_oracle_verdict(checkpoint, driver._oracle_indexes())
        self.assertEqual(
            next(
                row["oracle_verdict"]["status"]
                for row in checkpoint["rows"]
                if row["allocator"] == driver.LEGACY_ALLOCATOR
            ),
            "exact_binary64_match",
        )


if __name__ == "__main__":
    unittest.main()
