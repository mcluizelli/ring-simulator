"""Structural and behavioral tests for the bounded proportional sidecar audit."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
INVESTIGATIONS = ROOT / "investigations"
if str(INVESTIGATIONS) not in sys.path:
    sys.path.insert(0, str(INVESTIGATIONS))

import audit_proportional_mechanism_2026_08_07 as audit  # noqa: E402
import sim  # noqa: E402


class ProportionalMechanismAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = audit.build_plan()

    def test_fixed_matrix_is_exactly_180_traces(self) -> None:
        self.assertEqual(self.plan["source_pair_count"], 30)
        self.assertEqual(self.plan["window_job_count"], 90)
        self.assertEqual(self.plan["traced_simulation_count"], 180)
        self.assertEqual(self.plan["arm_ids"], list(audit.ARM_IDS))
        self.assertEqual(self.plan["sample_ids"], list(audit.SAMPLE_IDS))
        self.assertEqual(self.plan["window_ticks"], [10, 20, 40])
        self.assertEqual(len({job["case_id"] for job in self.plan["jobs"]}), 90)

    def test_selected_arm_indices_and_pair_ids_are_sealed(self) -> None:
        for pair in self.plan["selected_pairs"]:
            arm_id = pair["config"]["arm_id"]
            self.assertEqual(pair["arm_index"], audit.EXPECTED_ARM_INDICES[arm_id])
            self.assertRegex(pair["pair_id"], r"^a(069|072|079)_proportional_")

    def test_window_jobs_change_only_the_window(self) -> None:
        for job in self.plan["jobs"]:
            base = job["pair"]["config"]
            materialized = job["config"]
            changed = {key for key in base if base[key] != materialized[key]}
            expected = (
                set()
                if job["window_s"] == audit.PRODUCTION_WINDOW_S
                else {"redistribution_window_s"}
            )
            self.assertEqual(changed, expected)
            self.assertEqual(
                job["window_ticks"], audit.EXPECTED_WINDOW_TICKS[job["window_s"]]
            )

    def test_normalized_weights_match_production_semantics(self) -> None:
        weights, total = audit._normalized_weights([2.0, -1.0, 6.0])
        self.assertEqual(total, 8.0)
        self.assertEqual(weights, [0.25, 0.0, 0.75])
        weights, total = audit._normalized_weights([float("inf"), 4.0])
        self.assertEqual(total, 4.0)
        self.assertEqual(weights, [0.0, 1.0])
        weights, total = audit._normalized_weights([0.0, -3.0])
        self.assertEqual(total, 0.0)
        self.assertEqual(weights, [0.0, 0.0])

    def test_prospective_rates_equal_measured_rates_when_all_qps_are_active(self) -> None:
        pair = next(
            pair
            for pair in self.plan["selected_pairs"]
            if pair["config"]["arm_id"] == "proportional_3tier_os4_p64_k2"
            and pair["sample_id"] == 0
        )
        config = pair["config"]
        for allocator in audit.ALLOCATORS:
            topo, ring = audit.n100._make_topology_and_ring(config)
            engine = sim.FlowLevelSimulator(
                topo, dt_s=float(config["dt_s"]), rate_allocator=allocator
            )
            fids = sim.add_ring_neighbor_flows(
                engine,
                ring,
                float(config["bytes_per_neighbor"]),
                flows_per_neighbor=int(config["k"]),
            )
            engine.step()
            prospective = audit._prospective_rates(engine, fids)
            self.assertEqual(
                [audit._f64_hex(prospective[fid]) for fid in fids],
                [audit._f64_hex(engine.flows[fid].last_rate_Bps) for fid in fids],
            )

    def test_single_trace_is_binary64_exact_to_production(self) -> None:
        job = next(
            job
            for job in self.plan["jobs"]
            if job["config"]["arm_id"] == "proportional_3tier_os4_p64_k2"
            and job["config"]["sample_id"] == 0
            and job["window_s"] == audit.PRODUCTION_WINDOW_S
        )
        allocator = sim.RATE_ALLOCATOR_LINK_LOCAL
        trace = audit._run_trace(job["pair"], job["config"], allocator)
        production = audit._run_direct_production(job["config"], allocator)
        self.assertEqual(trace["completion_time_hex"], production["completion_time_hex"])
        self.assertEqual(trace["delivered_bytes_hex"], production["delivered_bytes_hex"])
        self.assertLessEqual(
            trace["metrics"]["final_conservation_max_error_B"],
            audit.CONSERVATION_TOLERANCE_B,
        )

    def test_historical_v1_rejects_current_source_drift(self) -> None:
        historical = audit.EXPECTED_SOURCE_HASHES[ROOT / "sim.py"]
        current = audit._sha256_file(ROOT / "sim.py")
        self.assertEqual(
            historical,
            "40edbacc28e61bb25769278382506c32611cf7fd9e14777480b6fd3d664fab69",
        )
        self.assertNotEqual(current, historical)
        with self.assertRaisesRegex(RuntimeError, "source changed inside worker"):
            audit._verify_worker_sources()

    def test_sensitivity_medians_are_separate_for_each_window(self) -> None:
        traces = []
        for arm_id in audit.ARM_IDS:
            for sample_id in audit.SAMPLE_IDS:
                for allocator in audit.ALLOCATORS:
                    for window_s in audit.WINDOWS_S:
                        time_s = 1.0
                        if (
                            arm_id == audit.ARM_IDS[0]
                            and window_s == 0.5e-3
                        ):
                            time_s = 1.015
                        traces.append(
                            {
                                "arm_id": arm_id,
                                "sample_id": sample_id,
                                "allocator": allocator,
                                "window_s": window_s,
                                "completion_time_s": time_s,
                                "simulated_ticks": round(time_s / 5e-5),
                            }
                        )
        verdict = audit._sensitivity_gate(traces)
        self.assertFalse(verdict["passed"])
        self.assertAlmostEqual(
            verdict["maximum_cell_allocator_median_abs_relative_delta"],
            0.015,
        )

    def test_hard_gate_rejects_a_stale_shadow_mismatch(self) -> None:
        job = self.plan["jobs"][0]
        trace = audit._run_trace(
            job["pair"], job["config"], sim.RATE_ALLOCATOR_LINK_LOCAL
        )
        trace["case_id"] = job["case_id"]
        mutated = copy.deepcopy(trace)
        mutated["metrics"]["stale_shadow_mismatch_count"] = 1
        verdict = audit._hard_gate([mutated])
        self.assertFalse(verdict["passed"])
        self.assertIn("stale_shadow_mismatch_count=1", verdict["failures"])

    def test_output_is_sidecar_only_and_no_n1000_mode_exists(self) -> None:
        allowed = audit._validate_output_path(
            "investigations/proportional_mechanism_audit/structural-test-does-not-exist",
            require_absent=True,
        )
        self.assertIn(audit.OUTPUT_ROOT, allowed.parents)
        with self.assertRaises(RuntimeError):
            audit._validate_output_path("results/forbidden-audit", require_absent=True)
        source = Path(audit.__file__).read_text(encoding="utf-8")
        self.assertNotIn("--n1000", source)
        self.assertTrue(self.plan["no_n1000_execution_path"])


if __name__ == "__main__":
    unittest.main()
