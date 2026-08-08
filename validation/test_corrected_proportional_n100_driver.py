"""Fail-closed contract tests for corrected proportional n=100 revalidation.

These tests intentionally use only the fixed plan, sealed read-only references,
and tiny synthetic fixtures.  They never execute the 3,200-pair campaign and
never write under results/ or either sealed audit/campaign directory.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import math
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = ROOT / "experiments"
for path in (ROOT, EXPERIMENTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

try:
    import run_corrected_proportional_n100 as driver  # noqa: E402
except ModuleNotFoundError as exc:  # Fail closed, but keep discovery readable.
    driver = None
    DRIVER_IMPORT_ERROR = exc
else:
    DRIVER_IMPORT_ERROR = None


EXPECTED_PAIR_ID_SHA256 = (
    "72c14abfa494a0896b79aa75abf5d8071e6697f14e2e323963a869a62bda31da"
)
EXPECTED_FROZEN_ROOT_SHA256 = (
    "09a1418e965b9c2d597721ff0d3b1e8db937a19ce667accfa2cf1f469664c24e"
)
EXPECTED_AUDIT_V2_COMPLETE_SHA256 = (
    "046f980e20312b2ff988ec3fd1a1185cd2df9c261acf4da61168a658661cccd9"
)
EXPECTED_HISTORICAL_COMPLETE_SHA256 = (
    "c4caaf8bb203eff3b815236c3bc848d8d483b521571c3ab71a47a32f135eadfa"
)
EXPECTED_FROZEN_SPEC_SHA256 = (
    "0bfb2286b52f0dc5266c8e80a08e7d2de8e7508565e5f07b25caee8e4a508090"
)
EXPECTED_BOOTSTRAP_INDEX_SHA256_100 = (
    "97a42157ab7dd18246ac02f284afb9da83a406f01b467cae35efaab2ad7a654f"
)
EXPECTED_BOOTSTRAP_INDEX_SHA256_3 = (
    "b9e7b91ba1e901388f00793756b81a7c09852548470ee5408101ede70b8d3a27"
)
AUDIT_V2_EQUIVALENCE = (
    ROOT
    / "investigations"
    / "proportional_mechanism_audit_v2"
    / "audit_v2_2026-08-07_01"
    / "production_equivalence.json"
)
FROZEN_SPEC = (
    ROOT / "investigations" / "CORRECTED_PROPORTIONAL_N100_SPEC_2026_08_07.md"
)


def _json_digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _option_literals(module: object) -> set[str]:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    options: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if not isinstance(function, ast.Attribute) or function.attr != "add_argument":
            continue
        for argument in node.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                if argument.value.startswith("-"):
                    options.add(argument.value)
    return options


def _called_attribute_names(function: object) -> set[str]:
    tree = ast.parse(inspect.getsource(function))
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


class CorrectedProportionalN100DriverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if driver is None:
            raise AssertionError(
                "corrected proportional n=100 driver is missing"
            ) from DRIVER_IMPORT_ERROR
        cls.plan = driver.build_plan()

    def test_frozen_spec_bytes_are_unchanged(self) -> None:
        self.assertEqual(
            hashlib.sha256(FROZEN_SPEC.read_bytes()).hexdigest(),
            EXPECTED_FROZEN_SPEC_SHA256,
        )

    def test_exact_filtered_plan_cardinality_ids_and_digest(self) -> None:
        arms = self.plan["arms"]
        pairs = self.plan["pairs"]
        pair_ids = [pair["pair_id"] for pair in pairs]
        arm_numbers = sorted({int(pair_id[1:4]) for pair_id in pair_ids})

        self.assertEqual(len(arms), 32)
        self.assertEqual(len(pairs), 3_200)
        self.assertEqual(self.plan["simulation_count"], 6_400)
        self.assertEqual(len(set(pair_ids)), 3_200)
        self.assertEqual(_json_digest(pair_ids), EXPECTED_PAIR_ID_SHA256)
        self.assertEqual(arm_numbers, list(range(49, 81)))

        self.assertEqual(
            {int(pair["sample_id"]) for pair in pairs}, set(range(100))
        )
        self.assertEqual(
            {
                (
                    pair["config"]["fabric"],
                    int(pair["config"]["ring_size"]),
                    int(pair["config"]["k"]),
                )
                for pair in pairs
            },
            {
                (fabric, ring_size, k)
                for fabric in ("2tier", "3tier_nb", "3tier_os2", "3tier_os4")
                for ring_size in (16, 64)
                for k in (2, 4, 8, 16)
            },
        )
        self.assertTrue(
            all(
                pair["config"]["family"] == "static_split"
                and pair["config"]["runner"] == "proportional"
                and pair["config"]["policy"] == "proportional"
                and pair["config"]["oracle_kind"] == "proportional"
                for pair in pairs
            )
        )

        per_arm: dict[str, int] = {}
        per_seed: dict[int, int] = {}
        first_allocator: dict[str, int] = {}
        for pair in pairs:
            per_arm[pair["config"]["arm_id"]] = (
                per_arm.get(pair["config"]["arm_id"], 0) + 1
            )
            per_seed[int(pair["sample_id"])] = per_seed.get(int(pair["sample_id"]), 0) + 1
            first = pair["execution_order"][0]
            first_allocator[first] = first_allocator.get(first, 0) + 1
        self.assertEqual(set(per_arm.values()), {100})
        self.assertEqual(set(per_seed.values()), {32})
        self.assertEqual(
            first_allocator,
            {
                "link_local_equal_share": 1_600,
                "network_maxmin": 1_600,
            },
        )

    def test_plan_hash_and_canonical_filter_fail_closed_on_tamper(self) -> None:
        self.assertEqual(driver._verify_plan_integrity(self.plan), self.plan["plan_sha256"])
        changed = copy.deepcopy(self.plan)
        changed["pairs"][0]["config"]["k"] = 99
        with self.assertRaises(RuntimeError):
            driver._verify_plan_integrity(changed)

        rehashed = copy.deepcopy(changed)
        rehashed.pop("plan_sha256", None)
        changed["plan_sha256"] = _json_digest(rehashed)
        with self.assertRaises(RuntimeError):
            driver._verify_plan_integrity(changed)

    def test_preflight_is_exactly_32_seed_zero_pairs_plus_named_anchor(self) -> None:
        selected = list(driver._preflight_pairs(self.plan))
        selected_ids = [pair["pair_id"] for pair in selected]
        expected_ids = {
            pair["pair_id"]
            for pair in self.plan["pairs"]
            if int(pair["sample_id"]) == 0
        }
        expected_ids.add("a079_proportional_2tier_p64_k8__s066")

        self.assertEqual(len(selected), 33)
        self.assertEqual(len(set(selected_ids)), 33)
        self.assertEqual(set(selected_ids), expected_ids)
        self.assertEqual(sum(pair["sample_id"] == 0 for pair in selected), 32)
        self.assertEqual(
            sum(pair["pair_id"] == "a079_proportional_2tier_p64_k8__s066" for pair in selected),
            1,
        )
        # This is an intentional property of the fixed preflight, not a balance
        # gate: seed 0 and seed 66 are both even, hence legacy runs first in all
        # 33 pairs.  Balance is required only for the complete 3,200-pair plan.
        self.assertEqual(
            {pair["execution_order"][0] for pair in selected},
            {"link_local_equal_share"},
        )

    def test_no_n1000_mode_or_sample_is_reachable(self) -> None:
        self.assertTrue(self.plan["no_n1000_execution_path"])
        self.assertEqual(tuple(driver.SAMPLE_IDS), tuple(range(100)))
        self.assertEqual(max(pair["sample_id"] for pair in self.plan["pairs"]), 99)
        self.assertFalse(
            any("n1000" in option.lower() for option in _option_literals(driver))
        )

    def test_output_path_is_contained_in_new_sidecar_tree(self) -> None:
        candidate = "investigations/corrected_proportional_n100/unit-test-does-not-exist"
        allowed = driver._validate_output_path(candidate, require_absent=True)
        self.assertIn(driver.OUTPUT_ROOT, allowed.parents)
        for forbidden in (
            "results/forbidden-corrected-n100",
            "investigations/rate_allocator_n100/n100_2026-08-06_03",
            "investigations/proportional_mechanism_audit_v2/audit_v2_2026-08-07_01",
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises((RuntimeError, FileExistsError)):
                    driver._validate_output_path(forbidden, require_absent=False)

    def test_root_artifact_allowlist_rejects_extra_and_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            (output / "checkpoints").mkdir()
            (output / "timing_segments").mkdir()
            for name in driver.REQUIRED_EARLY_ROOT_FILES:
                (output / name).write_bytes(b"fixture")
            driver._verify_root_artifact_set(output, mode="partial")

            extra = output / "notes.txt"
            extra.write_text("must not be silently signed", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                driver._verify_root_artifact_set(output, mode="partial")
            extra.unlink()

            for name in driver.PRIOR_FINAL_ROOT_FILES:
                path = output / name
                if not path.exists():
                    path.write_bytes(b"fixture")
            driver._verify_root_artifact_set(output, mode="prior_final")
            missing = output / "analysis.json"
            missing.unlink()
            with self.assertRaises(RuntimeError):
                driver._verify_root_artifact_set(output, mode="prior_final")
            missing.write_bytes(b"fixture")

            # Real crash window: completion manifest was atomically written,
            # but COMPLETE.json was not.  Resume must accept this exact state;
            # atomic_write_once will later require byte-identical completion.
            (output / "completion_manifest.json").write_bytes(b"fixture")
            driver._verify_root_artifact_set(output, mode="partial")
            driver._verify_root_artifact_set(output, mode="prior_final")
            (output / "COMPLETE.json").write_bytes(b"fixture")
            with self.assertRaises(RuntimeError):
                driver._verify_root_artifact_set(output, mode="partial")
            driver._verify_root_artifact_set(output, mode="final")
            (output / "failed.log").write_bytes(b"fixture")
            with self.assertRaises(RuntimeError):
                driver._verify_root_artifact_set(output, mode="final")

    def test_held_run_lock_is_signed_and_verified_without_reopening(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            (output / "checkpoints").mkdir()
            (output / "timing_segments").mkdir()
            for name in driver.PRIOR_FINAL_ROOT_FILES - {".run.lock"}:
                (output / name).write_bytes(f"fixture:{name}".encode("utf-8"))

            lock_path = output / ".run.lock"
            manifest = {"plan_sha256": "fixture-plan", "immutable_before": {}}
            path_sha256 = driver._sha256_file

            with driver.core.ExclusiveRunLock(lock_path) as run_lock:
                def reject_second_lock_handle(path: Path) -> str:
                    if path.resolve(strict=True) == lock_path.resolve(strict=True):
                        raise AssertionError("locked artifact was reopened")
                    return path_sha256(path)

                with mock.patch.object(
                    driver, "_sha256_file", side_effect=reject_second_lock_handle
                ):
                    artifacts = driver._artifact_inventory(output, run_lock)
                    self.assertEqual(
                        artifacts[".run.lock"],
                        {
                            "bytes": 1,
                            "sha256": hashlib.sha256(b"0").hexdigest(),
                        },
                    )
                    with self.assertRaises(RuntimeError):
                        driver._locked_run_lock_artifact(
                            output / "analysis.json", run_lock
                        )

                    completion = {
                        "schema": "corrected-proportional-n100-completion-v1",
                        "plan_sha256": manifest["plan_sha256"],
                        "status": "GO",
                        "pair_count": driver.PAIR_COUNT,
                        "simulation_count": driver.SIMULATION_COUNT,
                        "gate": {"passed": True},
                        "analysis_sha256": artifacts["analysis.json"]["sha256"],
                        "runtime": {},
                        "immutable_after": manifest["immutable_before"],
                        "artifacts": artifacts,
                        "artifact_count": len(artifacts),
                        "completion_manifest_self_signed": False,
                        "complete_file_self_signed": False,
                        "n1000_started": False,
                    }
                    driver.core._atomic_json_once(
                        output / "completion_manifest.json", completion
                    )
                    completion_path = output / "completion_manifest.json"
                    complete = {
                        "schema": "corrected-proportional-n100-complete-v1",
                        "plan_sha256": manifest["plan_sha256"],
                        "status": completion["status"],
                        "completion_manifest_sha256": path_sha256(completion_path),
                        "completion_manifest_bytes": completion_path.stat().st_size,
                        "written_last": True,
                        "n1000_started": False,
                    }
                    driver.core._atomic_json_once(output / "COMPLETE.json", complete)
                    driver._cleanup_empty_staging(output)
                    with mock.patch.object(driver, "_verify_runtime_authorization"):
                        verified = driver._verify_complete(
                            output, manifest, run_lock
                        )
                    self.assertEqual(
                        verified["artifacts"][".run.lock"],
                        artifacts[".run.lock"],
                    )

    def test_worker_delegates_to_core_without_historical_oracle_calls(self) -> None:
        forbidden_calls = {
            "_oracle_indexes",
            "_oracle_row",
            "_attach_oracle_verdict",
            "_existing_checkpoints",
            "execute_or_resume",
        }
        source_calls = _called_attribute_names(driver._run_pair_worker)
        self.assertTrue(forbidden_calls.isdisjoint(source_calls))

        pair = next(
            pair
            for pair in self.plan["pairs"]
            if pair["execution_order"][0] == "network_maxmin"
        )
        self.assertEqual(
            pair["execution_order"],
            ["network_maxmin", "link_local_equal_share"],
        )
        sentinel = {"pair_id": pair["pair_id"], "rows": []}
        with ExitStack() as stack:
            delegated = stack.enter_context(
                mock.patch.object(driver.core, "_run_pair_worker", return_value=sentinel)
            )
            for name in (
                "_oracle_indexes",
                "_oracle_row",
                "_attach_oracle_verdict",
                "_existing_checkpoints",
                "execute_or_resume",
            ):
                if hasattr(driver.core, name):
                    stack.enter_context(
                        mock.patch.object(
                            driver.core,
                            name,
                            side_effect=AssertionError(f"forbidden core call: {name}"),
                        )
                    )
            canonical = getattr(driver, "canonical", None) or getattr(driver, "n100", None)
            if canonical is not None:
                for name in ("_oracle_indexes", "_attach_oracle_verdict", "execute_or_resume"):
                    if hasattr(canonical, name):
                        stack.enter_context(
                            mock.patch.object(
                                canonical,
                                name,
                                side_effect=AssertionError(f"forbidden canonical call: {name}"),
                            )
                        )
            if hasattr(driver, "_verify_worker_sources"):
                stack.enter_context(
                    mock.patch.object(driver, "_verify_worker_sources", return_value=None)
                )
            actual = driver._run_pair_worker(pair)
        self.assertIs(actual, sentinel)
        delegated.assert_called_once_with(pair)

    def test_source_seals_pass_and_reject_sim_drift(self) -> None:
        snapshot = driver._verify_immutable_inputs()
        serialized = json.dumps(snapshot, sort_keys=True)
        self.assertIn(EXPECTED_FROZEN_ROOT_SHA256, serialized)
        self.assertIn(EXPECTED_AUDIT_V2_COMPLETE_SHA256, serialized)
        self.assertIn(EXPECTED_HISTORICAL_COMPLETE_SHA256, serialized)
        self.assertIn(EXPECTED_FROZEN_SPEC_SHA256, serialized)

        original = driver._sha256_file

        def drift(path: Path) -> str:
            if Path(path).resolve() == Path(driver.SIM_PATH).resolve():
                return "0" * 64
            return original(path)

        with mock.patch.object(driver, "_sha256_file", side_effect=drift):
            with self.assertRaises(RuntimeError):
                driver._verify_immutable_inputs()

    def test_proportional_conservation_checks_each_live_remaining_value(self) -> None:
        target = float(64 * 1024 * 1024)
        config = {
            "runner": "proportional",
            "ring_size": 2,
            "k": 2,
            "bytes_per_neighbor": target,
        }
        result = {
            "per_edge_delivered_bytes": {"e0": target, "e1": target},
        }

        def flow(fid: int, remaining: float) -> SimpleNamespace:
            return SimpleNamespace(
                fid=fid,
                remaining_bytes=remaining,
                sent_bytes=target / 2,
                five_tuple=SimpleNamespace(dport=20000),
            )

        good_engine = SimpleNamespace(
            flows={fid: flow(fid, 0.0) for fid in range(4)}
        )
        verdict = driver._conservation_gate(config, result, good_engine)
        self.assertEqual(verdict["foreground_flow_count"], 4)
        self.assertEqual(verdict["checks"], 2)
        self.assertEqual(verdict["foreground_remaining_nonzero_count"], 0)
        self.assertEqual(verdict["foreground_remaining_min_bytes"], 0.0)
        self.assertEqual(verdict["foreground_remaining_max_bytes"], 0.0)

        short_engine = SimpleNamespace(
            flows={fid: flow(fid, 0.0) for fid in range(3)}
        )
        with self.assertRaises(RuntimeError):
            driver._conservation_gate(config, result, short_engine)

        bad_delivered = {
            "per_edge_delivered_bytes": {"e0": target, "e1": float("nan")}
        }
        with self.assertRaises(RuntimeError):
            driver._conservation_gate(config, bad_delivered, good_engine)

        # Both cases defeat an aggregate sum(max(0, remaining)) check: a
        # negative value clips to zero, while NaN can be hidden by max(0, NaN).
        for bad_remaining in (-1.0, float("nan"), float("inf")):
            with self.subTest(bad_remaining=bad_remaining):
                bad_engine = SimpleNamespace(
                    flows={
                        0: flow(0, bad_remaining),
                        1: flow(1, 0.0),
                        2: flow(2, 0.0),
                        3: flow(3, 0.0),
                    }
                )
                with self.assertRaises(RuntimeError):
                    driver._conservation_gate(config, result, bad_engine)

    def test_seed457_68_ulp_roundoff_passes_but_129_ulps_fails(self) -> None:
        target = float(64 * 1024 * 1024)
        ulp = math.ulp(target)
        seed457_value = float.fromhex("0x1.0000000000044p+26")
        self.assertEqual(seed457_value - target, 68 * ulp)
        config = {
            "runner": "proportional",
            "ring_size": 2,
            "k": 2,
            "bytes_per_neighbor": target,
        }

        def flow(fid: int) -> SimpleNamespace:
            return SimpleNamespace(
                fid=fid,
                remaining_bytes=0.0,
                sent_bytes=target / 2,
                five_tuple=SimpleNamespace(dport=20000),
            )

        engine = SimpleNamespace(flows={fid: flow(fid) for fid in range(4)})
        report = driver._conservation_gate(
            config,
            {"per_edge_delivered_bytes": {"edge0": target, "edge23": seed457_value}},
            engine,
        )
        self.assertEqual(report["maximum_abs_error_bytes"], 68 * ulp)
        self.assertEqual(report["roundoff_tolerance_B"], 128 * ulp)
        self.assertEqual(report["remaining_foreground_bytes"], 0.0)

        with self.assertRaises(RuntimeError):
            driver._conservation_gate(
                config,
                {
                    "per_edge_delivered_bytes": {
                        "edge0": target,
                        "edge23": target + 129 * ulp,
                    }
                },
                engine,
            )

    def test_audit_v2_overlap_gate_accepts_sealed_rows_and_rejects_delta(self) -> None:
        bundle = json.loads(AUDIT_V2_EQUIVALENCE.read_text(encoding="utf-8"))
        checkpoints = {
            item["pair_id"]: copy.deepcopy(item["fresh_pair_worker"])
            for item in bundle["pairs"]
        }
        verdict = driver._audit_v2_overlap_gate(checkpoints, require_all=True)
        self.assertEqual(verdict["pair_count"], 30)
        self.assertEqual(verdict["row_count"], 60)

        changed = copy.deepcopy(checkpoints)
        target = changed["a079_proportional_2tier_p64_k8__s066"]
        target["rows"][0]["completion_time_hex"] = "0000000000000000"
        with self.assertRaises(RuntimeError):
            driver._audit_v2_overlap_gate(changed, require_all=True)

        numeric_tamper = copy.deepcopy(checkpoints)
        numeric_tamper["a079_proportional_2tier_p64_k8__s066"]["rows"][0][
            "conservation"
        ]["maximum_abs_error_bytes"] = float("nan")
        with self.assertRaises(RuntimeError):
            driver._audit_v2_overlap_gate(numeric_tamper, require_all=True)

    def test_preflight_v2_overlap_is_exactly_four_pairs_and_one_named_anchor(self) -> None:
        bundle = json.loads(AUDIT_V2_EQUIVALENCE.read_text(encoding="utf-8"))
        all_v2 = {
            item["pair_id"]: copy.deepcopy(item["fresh_pair_worker"])
            for item in bundle["pairs"]
        }
        preflight_ids = {pair["pair_id"] for pair in driver._preflight_pairs(self.plan)}
        overlap = {
            pair_id: checkpoint
            for pair_id, checkpoint in all_v2.items()
            if pair_id in preflight_ids
        }
        self.assertEqual(
            set(overlap),
            {
                "a069_proportional_3tier_os4_p64_k2__s000",
                "a072_proportional_3tier_os4_p64_k16__s000",
                "a079_proportional_2tier_p64_k8__s000",
                "a079_proportional_2tier_p64_k8__s066",
            },
        )
        verdict = driver._audit_v2_overlap_gate(overlap, require_all=False)
        self.assertEqual(verdict["pair_count"], 4)
        self.assertEqual(verdict["row_count"], 8)
        serialized = json.dumps(verdict, sort_keys=True)
        self.assertIn("a079_proportional_2tier_p64_k8__s066", serialized)
        self.assertNotIn("a072_proportional_3tier_os4_p64_k16__s033", serialized)

    def test_existing_checkpoint_loader_is_custom_and_recomputes_references(self) -> None:
        called = _called_attribute_names(driver._existing_checkpoints)
        self.assertNotIn("_existing_checkpoints", called)
        source = (
            inspect.getsource(driver._existing_checkpoints)
            + inspect.getsource(driver._validate_checkpoint)
        )
        self.assertIn("_attach_reference_diagnostics", source)
        self.assertNotIn("_attach_oracle_verdict", source)
        self.assertNotIn("_oracle", source)

    def test_cluster_bootstrap_contract_is_deterministic_and_seed_clustered(self) -> None:
        values_by_seed = {
            0: [math.log(2.0), math.log(8.0)],
            1: [math.log(4.0), math.log(16.0)],
            2: [math.log(1.0), math.log(1.0)],
        }
        first = driver._cluster_bootstrap(values_by_seed)
        second = driver._cluster_bootstrap(values_by_seed)
        self.assertEqual(first, second)
        self.assertEqual(first["rng"], "PCG64(20260807)")
        self.assertEqual(first["bootstrap_replicates"], 20_000)
        self.assertEqual(first["bootstrap_index_shape"], [20_000, 3])
        self.assertEqual(first["bootstrap_index_dtype"], "<u4")
        self.assertEqual(
            first["bootstrap_index_sha256"], EXPECTED_BOOTSTRAP_INDEX_SHA256_3
        )

        expected = math.exp(
            sum(value for values in values_by_seed.values() for value in values) / 6
        )
        self.assertTrue(
            math.isclose(
                first["point_estimate"], expected, rel_tol=1e-12, abs_tol=1e-12
            )
        )
        self.assertEqual(first["ci95_low"], 1.0)
        self.assertTrue(
            math.isclose(first["ci95_high"], 8.0, rel_tol=0.0, abs_tol=math.ulp(8.0))
        )

        global_shape = driver._cluster_bootstrap(
            {seed: [float(seed + 1)] for seed in range(100)}
        )
        self.assertEqual(
            global_shape["bootstrap_index_sha256"],
            EXPECTED_BOOTSTRAP_INDEX_SHA256_100,
        )
        self.assertEqual(global_shape["bootstrap_index_shape"], [20_000, 100])
        self.assertEqual(global_shape["bootstrap_index_dtype"], "<u4")

    def test_tick_classes_are_mutually_exclusive_at_all_boundaries(self) -> None:
        expected = {
            -3: "maxmin_faster_by_2plus",
            -2: "maxmin_faster_by_2plus",
            -1: "one_tick_tie",
            0: "exact_tie",
            1: "one_tick_tie",
            2: "maxmin_slower_by_2plus",
            3: "maxmin_slower_by_2plus",
        }
        self.assertEqual(
            {delta: driver._tick_class(delta) for delta in expected}, expected
        )

    def test_stopping_status_mapping_is_fail_closed(self) -> None:
        base = {
            "global_ci_low": 0.90,
            "global_ci_high": 0.99,
            "claim_trigger": False,
            "material_reversal": False,
            "single_seed_dependence": False,
        }
        self.assertEqual(
            driver._stopping_status(**base),
            "READY_TO_DECIDE_PROPORTIONAL_N1000_SCOPE",
        )
        for change in (
            {"global_ci_high": 1.0},
            {"claim_trigger": True},
            {"material_reversal": True},
            {"single_seed_dependence": True},
        ):
            args = {**base, **change}
            self.assertEqual(
                driver._stopping_status(**args),
                "REVIEW_CORRECTED_N100_EFFECTS_BEFORE_SCALING",
            )
        self.assertEqual(
            driver._stopping_status(**base, integrity_ok=False),
            "STOP_AND_FIX_N100_INTEGRITY_FAILURE",
        )


if __name__ == "__main__":
    unittest.main()
