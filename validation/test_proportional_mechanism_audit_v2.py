"""Structural and behavioral tests for corrected proportional Audit v2."""
from __future__ import annotations

import copy
import json
import multiprocessing as mp
import sys
import tempfile
import unittest
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
INVESTIGATIONS = ROOT / "investigations"
for path in (ROOT, INVESTIGATIONS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import audit_proportional_mechanism_v2_2026_08_07 as audit  # noqa: E402


class CorrectedProportionalAuditV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = audit.build_plan()

    def _job(self, arm_id: str, sample_id: int, window_s: float):
        return next(
            job
            for job in self.plan["jobs"]
            if job["config"]["arm_id"] == arm_id
            and int(job["config"]["sample_id"]) == sample_id
            and float(job["window_s"]) == window_s
        )

    def test_plan_matrix_is_exact_and_unique(self) -> None:
        self.assertEqual(self.plan["source_pair_count"], 30)
        self.assertEqual(self.plan["window_job_count"], 90)
        self.assertEqual(self.plan["traced_simulation_count"], 180)
        self.assertEqual(self.plan["production_window_trace_count"], 60)
        self.assertEqual(self.plan["historical_delta_row_count"], 60)
        self.assertEqual(len({job["case_id"] for job in self.plan["jobs"]}), 90)
        self.assertEqual(self.plan["arm_ids"], list(audit.ARM_IDS))
        self.assertEqual(self.plan["sample_ids"], list(audit.SAMPLE_IDS))
        self.assertEqual(self.plan["window_ticks"], [10, 20, 40])
        self.assertTrue(self.plan["no_full_n100_execution_path"])
        self.assertTrue(self.plan["no_n1000_execution_path"])

    def test_v1_bundle_is_complete_and_byte_exact(self) -> None:
        first = audit._v1_bundle_inventory()
        second = audit._v1_bundle_inventory()
        self.assertEqual(first, second)
        self.assertEqual(first["file_count"], 6)
        self.assertEqual(first["status"], "STOP_BEFORE_N1000_AND_REVIEW")
        self.assertEqual(first["plan_sha256"], audit.EXPECTED_V1_PLAN_SHA256)

    def test_authorization_rejects_source_drift(self) -> None:
        original = audit._sha256_file

        def drift(path: Path) -> str:
            if path == audit.ROOT / "sim.py":
                return "0" * 64
            return original(path)

        with mock.patch.object(audit, "_sha256_file", side_effect=drift):
            with self.assertRaisesRegex(RuntimeError, "immutable input changed"):
                audit.verify_immutable_inputs(self.plan)

    def test_authorization_rejects_mutated_plan_content(self) -> None:
        mutated = copy.deepcopy(self.plan)
        mutated["jobs"][0]["config"]["bytes_per_neighbor"] += 1
        with self.assertRaisesRegex(RuntimeError, "plan digest mismatch"):
            audit.authorization_sha256(mutated)
        with self.assertRaisesRegex(RuntimeError, "plan digest mismatch"):
            audit.verify_immutable_inputs(mutated)
        unsigned = copy.deepcopy(mutated)
        unsigned.pop("plan_sha256")
        mutated["plan_sha256"] = audit._digest(unsigned)
        with self.assertRaisesRegex(RuntimeError, "not the canonical frozen matrix"):
            audit.authorization_sha256(mutated)

    def test_output_is_fresh_v2_sidecar_only(self) -> None:
        allowed = audit._validate_output_path(
            "investigations/proportional_mechanism_audit_v2/does-not-exist",
            require_absent=True,
        )
        self.assertIn(audit.OUTPUT_ROOT, allowed.parents)
        for forbidden in (
            "results/forbidden-v2",
            "investigations/proportional_mechanism_audit/audit_2026-08-07_01",
            "investigations/rate_allocator_n100/n100_2026-08-06_03",
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(RuntimeError):
                    audit._validate_output_path(forbidden, require_absent=False)
        with self.assertRaisesRegex(RuntimeError, "output must be a child"):
            audit.execute(
                self.plan,
                audit.ROOT / "results" / "execute-must-reject",
                "not-an-authorization",
                1,
            )

    def test_recursive_artifact_scan_rejects_nested_unsigned_file(self) -> None:
        with tempfile.TemporaryDirectory(dir=audit.INVESTIGATIONS) as raw:
            root = Path(raw)
            nested = root / "nested"
            nested.mkdir()
            (nested / "unsigned.txt").write_text("unsigned", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "artifact directories"):
                audit._flat_artifact_names(root)

    def test_candidate_oracle_covers_completed_idle_and_external_flows(self) -> None:
        engine = SimpleNamespace(
            flows={
                1: SimpleNamespace(remaining_bytes=0.0),
                2: SimpleNamespace(remaining_bytes=0.0),
                3: SimpleNamespace(remaining_bytes=5.0),
                4: SimpleNamespace(remaining_bytes=0.0),
                5: SimpleNamespace(remaining_bytes=7.0),
                6: SimpleNamespace(remaining_bytes=0.0),
            }
        )
        groups = ((1, 2), (3, 4))
        ring_fids = {1, 2, 3, 4}
        live_ring_fids = {3, 4}
        production = audit._production_candidate_fids(
            engine, live_ring_fids, ring_fids
        )
        expected = audit._expected_candidate_fids(engine, groups, ring_fids)
        self.assertEqual(production, [3, 4, 5])
        self.assertEqual(production, expected)

    def test_affected_trace_matches_corrected_direct_for_both_allocators(self) -> None:
        job = self._job(
            "proportional_3tier_os4_p64_k16", 33, audit.PRODUCTION_WINDOW_S
        )
        for allocator in audit.ALLOCATORS:
            with self.subTest(allocator=allocator):
                trace = audit._run_trace(job["pair"], job["config"], allocator)
                direct = audit._run_corrected_production(job["config"], allocator)
                self.assertEqual(
                    trace["completion_time_hex"], direct["completion_time_hex"]
                )
                self.assertEqual(
                    trace["delivered_bytes_hex"], direct["delivered_bytes_hex"]
                )
                self.assertEqual(
                    trace["metrics"]["snapshot_oracle_weight_mismatch_count"], 0
                )
                self.assertEqual(
                    trace["metrics"]["snapshot_state_mutation_count"], 0
                )

    def test_zero_rate_group_retains_its_split(self) -> None:
        job = self._job(
            "proportional_3tier_os4_p64_k2", 0, audit.PRODUCTION_WINDOW_S
        )
        original_snapshot = audit.sim.FlowLevelSimulator.snapshot_flow_rates
        original_shadow = audit.v1._prospective_rates
        actual_calls = 0
        shadow_calls = 0

        def snapshot_once_zero(engine, fids):
            nonlocal actual_calls
            actual_calls += 1
            if actual_calls == 1:
                return {fid: 0.0 for fid in fids}
            return original_snapshot(engine, fids)

        def shadow_once_zero(engine, fids):
            nonlocal shadow_calls
            shadow_calls += 1
            if shadow_calls == 1:
                return {fid: 0.0 for fid in fids}
            return original_shadow(engine, fids)

        with mock.patch.object(
            audit.sim.FlowLevelSimulator,
            "snapshot_flow_rates",
            new=snapshot_once_zero,
        ), mock.patch.object(audit.v1, "_prospective_rates", new=shadow_once_zero):
            trace = audit._run_trace(
                job["pair"], job["config"], audit.ALLOCATORS[0]
            )
        self.assertGreater(trace["metrics"]["zero_rate_live_group_count"], 0)
        self.assertEqual(
            trace["metrics"]["snapshot_oracle_weight_mismatch_count"], 0
        )

    def test_historical_retained_difference_is_diagnostic_only(self) -> None:
        job = self._job(
            "proportional_3tier_os4_p64_k16", 33, audit.PRODUCTION_WINDOW_S
        )
        trace = audit._run_trace(job["pair"], job["config"], audit.ALLOCATORS[0])
        trace["case_id"] = job["case_id"]
        trace["metrics"]["counterfactual_retained_weight_mismatch_count"] = 123
        verdict = audit._hard_gate([trace])
        self.assertFalse(verdict["passed"])  # one row is intentionally not the matrix
        self.assertFalse(
            any(
                "counterfactual_retained_weight_mismatch_count" in failure
                for failure in verdict["failures"]
            )
        )
        trace["metrics"]["reactivation_count"] = 0
        verdict = audit._hard_gate([trace])
        self.assertTrue(
            any(
                "required defect coverage absent (reactivation_count)" in failure
                for failure in verdict["failures"]
            )
        )

    def test_hard_gate_rejects_snapshot_shadow_mismatch(self) -> None:
        job = self._job(
            "proportional_3tier_os4_p64_k2", 0, audit.PRODUCTION_WINDOW_S
        )
        trace = audit._run_trace(job["pair"], job["config"], audit.ALLOCATORS[0])
        trace["case_id"] = job["case_id"]
        trace["metrics"]["snapshot_oracle_weight_mismatch_count"] = 1
        verdict = audit._hard_gate([trace])
        self.assertFalse(verdict["passed"])
        self.assertIn("snapshot_oracle_weight_mismatch_count=1", verdict["failures"])
        trace["metrics"]["snapshot_oracle_weight_mismatch_count"] = 0
        trace["metrics"]["snapshot_call_count"] = 0
        trace["metrics"]["snapshot_boundary_count"] = 0
        trace["metrics"]["final_conservation_max_error_B"] = float("nan")
        verdict = audit._hard_gate([trace])
        self.assertTrue(
            any("snapshot coverage absent" in failure for failure in verdict["failures"])
        )
        self.assertTrue(
            any("non-finite metrics" in failure for failure in verdict["failures"])
        )

    def test_v1_historical_join_allows_outcome_delta_but_is_bijective(self) -> None:
        old_rows = json.loads(
            (audit.V1_ROOT / "results.json").read_text(encoding="utf-8")
        )
        corrected = []
        for old in old_rows:
            if float(old["window_s"]) != audit.PRODUCTION_WINDOW_S:
                continue
            row = copy.deepcopy(old)
            row["metrics"]["counterfactual_retained_weight_mismatch_count"] = 0
            corrected.append(row)
        corrected[0]["completion_time_s"] += 5e-5
        corrected[0]["completion_time_hex"] = audit._f64_hex(
            corrected[0]["completion_time_s"]
        )
        corrected[0]["simulated_ticks"] += 1
        comparison = audit._historical_comparison(corrected)
        self.assertEqual(comparison["row_count"], 60)
        self.assertEqual(comparison["changed_binary64_rows"], 1)
        with self.assertRaisesRegex(RuntimeError, "not bijective"):
            audit._historical_comparison(corrected[:-1])

    def test_sensitivity_gate_keeps_neighboring_windows_separate(self) -> None:
        traces = []
        for arm_id in audit.ARM_IDS:
            for sample_id in audit.SAMPLE_IDS:
                for allocator in audit.ALLOCATORS:
                    for window_s in audit.WINDOWS_S:
                        time_s = 1.0
                        if arm_id == audit.ARM_IDS[0] and window_s == 0.5e-3:
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
        verdict = audit.v1._sensitivity_gate(traces)
        self.assertFalse(verdict["passed"])
        self.assertAlmostEqual(
            verdict["maximum_cell_allocator_median_abs_relative_delta"], 0.015
        )

    def test_spawned_affected_job_replays_both_allocators(self) -> None:
        job = self._job(
            "proportional_3tier_os4_p64_k16", 33, audit.PRODUCTION_WINDOW_S
        )
        with ProcessPoolExecutor(
            max_workers=1,
            mp_context=mp.get_context("spawn"),
            initializer=audit._worker_init,
            initargs=(
                audit._sha256_file(audit.SCRIPT_PATH),
                audit._sha256_file(audit.SPEC_PATH),
            ),
        ) as pool:
            result = pool.submit(audit._run_job, job).result(timeout=60)
        evidence = audit._validate_one_ms_equivalence(result)
        self.assertEqual(evidence["sidecar_direct_exact_rows"], 2)
        self.assertEqual(evidence["worker_bridge_exact_rows"], 2)
        self.assertEqual(
            {row["allocator"] for row in result["traces"]}, set(audit.ALLOCATORS)
        )
        mutated = copy.deepcopy(result)
        mutated["fresh_pair_worker"]["pair_spec"]["sample_id"] = -1
        with self.assertRaisesRegex(RuntimeError, "pair specification changed"):
            audit._validate_one_ms_equivalence(mutated)
        duplicate = copy.deepcopy(result)
        duplicate["fresh_pair_worker"]["rows"].append(
            copy.deepcopy(duplicate["fresh_pair_worker"]["rows"][0])
        )
        with self.assertRaisesRegex(RuntimeError, "row cardinality changed"):
            audit._validate_one_ms_equivalence(duplicate)


if __name__ == "__main__":
    unittest.main()
