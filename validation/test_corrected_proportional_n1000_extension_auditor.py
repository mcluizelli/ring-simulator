"""Fail-closed, simulation-free tests for the n=1000 extension auditor."""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
AUDITOR_PATH = (
    ROOT
    / "investigations"
    / "audit_corrected_proportional_n1000_extension_2026_08_08.py"
)
SPEC = importlib.util.spec_from_file_location("n1000_extension_auditor_under_test", AUDITOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load n=1000 extension auditor")
auditor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = auditor
SPEC.loader.exec_module(auditor)


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _valid_row(pair: dict[str, object], allocator: str, position: int) -> dict[str, object]:
    config = pair["config"]
    assert isinstance(config, dict)
    completion = 0.0054
    zero_hex = struct.pack(">d", 0.0).hex()
    common_digest = "1" * 64
    return {
        "adaptive_gate": None,
        "allocator": allocator,
        "arm_id": config["arm_id"],
        "background_instance_id": None,
        "completion_time_hex": struct.pack(">d", completion).hex(),
        "completion_time_s": completion,
        "config_sha256": pair["config_sha256"],
        "congestion_instance_id": None,
        "conservation": {
            "checks": int(config["ring_size"]),
            "foreground_flow_count": int(config["ring_size"]) * int(config["k"]),
            "foreground_remaining_max_bytes": 0.0,
            "foreground_remaining_min_bytes": 0.0,
            "foreground_remaining_nonzero_count": 0,
            "individual_remaining_values_checked": int(config["ring_size"])
            * int(config["k"]),
            "maximum_abs_error_bytes": 0.0,
            "maximum_abs_error_bytes_hex": zero_hex,
            "maximum_per_flow_error_bytes": 0.0,
            "maximum_per_flow_error_bytes_hex": zero_hex,
            "non_bit_exact_flow_count": 0,
            "passed": True,
            "remaining_foreground_bytes": 0.0,
        },
        "execution_position": position,
        "family": "static_split",
        "pair_id": pair["pair_id"],
        "policy": "proportional",
        "process_initial_sha256": common_digest,
        "ring_sha256": common_digest,
        "route_sha256": common_digest,
        "runner": "proportional",
        "sample_id": pair["sample_id"],
        "simulated_ticks": 108,
        "wall_time_s": 0.02,
        "cpu_time_s": 0.01,
        "simulation_wall_time_s": 0.015,
        "simulation_cpu_time_s": 0.008,
        "simulator_instance_id": 100 + position,
        "topology_instance_id": 200 + position,
        "topology_sha256": common_digest,
    }


def _valid_checkpoint(pair: dict[str, object]) -> dict[str, object]:
    order = pair["execution_order"]
    assert isinstance(order, list)
    rows = [_valid_row(pair, allocator, index) for index, allocator in enumerate(order)]
    return {
        "schema": "rate-allocator-pair-checkpoint-v1",
        "pair_id": pair["pair_id"],
        "pair_spec": pair,
        "pair_gate": {
            "initial_digests_equal": True,
            "mutable_instances_distinct": True,
            "passed": True,
        },
        "parent_timing": {"pool_elapsed_at_checkpoint_s": 1.0, "segment_index": 1},
        "plan_sha256": "a" * 64,
        "rows": rows,
    }


class CorrectedProportionalN1000ExtensionAuditorTests(unittest.TestCase):
    def test_auditor_never_imports_campaign_driver(self) -> None:
        tree = ast.parse(AUDITOR_PATH.read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        self.assertFalse(
            any("run_corrected_proportional_n1000_extension" in name for name in imported)
        )

    def test_auditor_has_no_filesystem_write_primitive(self) -> None:
        tree = ast.parse(AUDITOR_PATH.read_text(encoding="utf-8"))
        forbidden_attributes = {
            "write_text",
            "write_bytes",
            "unlink",
            "mkdir",
            "rename",
            "replace",
            "rmdir",
        }
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertTrue(forbidden_attributes.isdisjoint(called))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "open" or len(node.args) < 2:
                continue
            if isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                self.assertNotIn("w", node.args[1].value)
                self.assertNotIn("a", node.args[1].value)
                self.assertNotIn("+", node.args[1].value)

    def test_exact_arm_payload_and_order(self) -> None:
        arms = auditor._expected_arms()
        self.assertEqual(len(arms), 32)
        self.assertEqual(_digest(arms), auditor.EXPECTED_ARM_PAYLOAD_SHA256)
        self.assertEqual(arms[0]["arm_id"], "proportional_3tier_nb_p16_k2")
        self.assertEqual(arms[-1]["arm_id"], "proportional_2tier_p64_k16")
        self.assertEqual(
            {arm["fabric"] for arm in arms},
            {"3tier_nb", "3tier_os2", "3tier_os4", "2tier"},
        )

    def test_exact_extension_and_combined_id_digests(self) -> None:
        extension_ids = auditor._expected_pair_ids(auditor.EXTENSION_SEEDS)
        combined_ids = auditor._expected_pair_ids(auditor.COMBINED_SEEDS)
        self.assertEqual(len(extension_ids), 28_800)
        self.assertEqual(len(set(extension_ids)), 28_800)
        self.assertEqual(_digest(extension_ids), auditor.EXPECTED_EXTENSION_PAIR_ID_SHA256)
        self.assertEqual(len(combined_ids), 32_000)
        self.assertEqual(len(set(combined_ids)), 32_000)
        self.assertEqual(_digest(combined_ids), auditor.EXPECTED_COMBINED_PAIR_ID_SHA256)
        n100_ids = set(auditor._expected_pair_ids(tuple(range(100))))
        self.assertTrue(set(extension_ids).isdisjoint(n100_ids))

    def test_pair_ordinal_sample_index_and_balanced_order(self) -> None:
        pairs = auditor._expected_pairs()
        self.assertEqual(len(pairs), 28_800)
        first_counts = {allocator: 0 for allocator in auditor.ALLOCATORS}
        for pair in pairs:
            self.assertEqual(pair["sample_index"], pair["sample_id"])
            self.assertEqual(
                pair["ordinal"],
                pair["arm_index"] * 1_000 + pair["sample_id"],
            )
            self.assertEqual(pair["config_sha256"], _digest(pair["config"]))
            first_counts[pair["execution_order"][0]] += 1
        self.assertEqual(
            first_counts,
            {"link_local_equal_share": 14_400, "network_maxmin": 14_400},
        )
        self.assertEqual(pairs[0]["sample_id"], 100)
        self.assertEqual(pairs[-1]["sample_id"], 999)

    def test_preflight_is_all_32_arms_for_exactly_two_new_seeds(self) -> None:
        pair_ids = auditor._expected_preflight_ids()
        self.assertEqual(len(pair_ids), 64)
        self.assertEqual(len(set(pair_ids)), 64)
        self.assertEqual({int(pair_id.rsplit("__s", 1)[1]) for pair_id in pair_ids}, {100, 101})
        self.assertEqual({int(pair_id[1:4]) for pair_id in pair_ids}, set(range(49, 81)))

    def test_bootstrap_domains_have_independent_fixed_hashes(self) -> None:
        _, extension_hash = auditor._bootstrap_indexes(900)
        _, sensitivity_hash = auditor._bootstrap_indexes(896)
        _, combined_hash = auditor._bootstrap_indexes(1_000)
        self.assertEqual(extension_hash, auditor.EXPECTED_EXTENSION_BOOTSTRAP_SHA256)
        self.assertEqual(
            sensitivity_hash,
            auditor.EXPECTED_SENTINEL_EXCLUDED_BOOTSTRAP_SHA256,
        )
        self.assertEqual(combined_hash, auditor.EXPECTED_COMBINED_BOOTSTRAP_SHA256)
        self.assertNotEqual(extension_hash, combined_hash)

    def test_prior_sentinel_overlap_and_cluster_exclusion_are_exact(self) -> None:
        overlap = auditor._verify_prior_sentinel_overlap()
        self.assertEqual(overlap["pair_count"], 6)
        self.assertEqual(overlap["seed_cluster_count"], 4)
        self.assertEqual(set(overlap["seed_ids"]), {174, 199, 353, 657})
        self.assertEqual(
            set(overlap["pair_ids"]), auditor.EXPECTED_SENTINEL_OVERLAP_PAIR_IDS
        )
        retained = [
            seed
            for seed in auditor.EXTENSION_SEEDS
            if seed not in auditor.SENTINEL_OVERLAP_SEEDS
        ]
        self.assertEqual(len(retained), 896)
        self.assertTrue(set(retained).isdisjoint(auditor.SENTINEL_OVERLAP_SEEDS))

    def test_sensitivity_instability_and_counterexample_force_review(self) -> None:
        stable = {
            "point_estimate": 0.98,
            "ci95_low": 0.97,
            "ci95_high": 0.99,
            "tick_counts": {"maxmin_slower_by_2plus": 0},
        }
        self.assertEqual(
            auditor._analysis_review_reasons(
                stable,
                stable,
                stable,
                primary_single_seed_dependence=False,
            ),
            [],
        )
        sensitivity_crosses = {
            **stable,
            "point_estimate": 0.999,
            "ci95_low": 0.98,
            "ci95_high": 1.01,
        }
        reasons = auditor._analysis_review_reasons(
            stable,
            sensitivity_crosses,
            stable,
            primary_single_seed_dependence=False,
        )
        self.assertIn(
            "sentinel_excluded_sensitivity_ci_classification_differs", reasons
        )
        counterexample = copy.deepcopy(stable)
        counterexample["tick_counts"]["maxmin_slower_by_2plus"] = 1
        reasons = auditor._analysis_review_reasons(
            counterexample,
            stable,
            stable,
            primary_single_seed_dependence=False,
        )
        self.assertIn("extension_contains_maxmin_slower_by_2plus_pair", reasons)
        reasons = auditor._analysis_review_reasons(
            stable,
            stable,
            sensitivity_crosses,
            primary_single_seed_dependence=False,
        )
        self.assertIn("combined_secondary_ci_classification_differs", reasons)

    def test_checkpoint_validator_accepts_valid_pair_and_rejects_old_seed(self) -> None:
        pair = auditor._expected_pairs((100,))[0]
        checkpoint = _valid_checkpoint(pair)
        record = auditor._validate_checkpoint(checkpoint, pair, "a" * 64)
        self.assertEqual(record["sample_id"], 100)
        old_pair = copy.deepcopy(pair)
        old_pair["sample_id"] = 99
        old_pair["sample_index"] = 99
        old_pair["config"]["sample_id"] = 99
        old_pair["config_sha256"] = _digest(old_pair["config"])
        old_pair["pair_id"] = auditor._pair_id(
            old_pair["arm_index"], old_pair["config"]["arm_id"], 99
        )
        old_checkpoint = _valid_checkpoint(old_pair)
        with self.assertRaisesRegex(RuntimeError, "forbidden n=100 seed"):
            auditor._validate_checkpoint(old_checkpoint, old_pair, "a" * 64)

    def test_checkpoint_validator_rejects_conservation_and_pairing_tamper(self) -> None:
        pair = auditor._expected_pairs((100,))[0]
        checkpoint = _valid_checkpoint(pair)
        checkpoint["rows"][0]["conservation"]["remaining_foreground_bytes"] = 1.0
        with self.assertRaisesRegex(RuntimeError, "foreground bytes remain"):
            auditor._validate_checkpoint(checkpoint, pair, "a" * 64)
        checkpoint = _valid_checkpoint(pair)
        checkpoint["rows"][1]["topology_sha256"] = "2" * 64
        with self.assertRaisesRegex(RuntimeError, "paired topology_sha256 mismatch"):
            auditor._validate_checkpoint(checkpoint, pair, "a" * 64)

    def test_checkpoint_validator_rejects_truncated_coverage_and_bad_timing(self) -> None:
        pair = auditor._expected_pairs((100,))[0]
        checkpoint = _valid_checkpoint(pair)
        checkpoint["rows"][0]["conservation"]["checks"] -= 1
        with self.assertRaisesRegex(RuntimeError, "logical-edge/flow conservation coverage"):
            auditor._validate_checkpoint(checkpoint, pair, "a" * 64)
        checkpoint = _valid_checkpoint(pair)
        checkpoint["rows"][0]["simulation_wall_time_s"] = -0.1
        with self.assertRaisesRegex(RuntimeError, "simulation wall is not positive"):
            auditor._validate_checkpoint(checkpoint, pair, "a" * 64)
        checkpoint = _valid_checkpoint(pair)
        checkpoint["rows"][1]["topology_instance_id"] = checkpoint["rows"][0][
            "topology_instance_id"
        ]
        with self.assertRaisesRegex(RuntimeError, "topology_instance_id values are missing/reused"):
            auditor._validate_checkpoint(checkpoint, pair, "a" * 64)
        checkpoint = _valid_checkpoint(pair)
        checkpoint["rows"][0]["conservation"]["maximum_abs_error_bytes"] = -1e-9
        with self.assertRaisesRegex(RuntimeError, "is negative"):
            auditor._validate_checkpoint(checkpoint, pair, "a" * 64)

    def test_recovered_preflight_timing_is_signed_and_recomputed(self) -> None:
        names = [Path("segment_1000.json"), Path("segment_999.json")]
        self.assertEqual(
            [path.name for path in sorted(names, key=auditor._timing_segment_number)],
            ["segment_999.json", "segment_1000.json"],
        )
        pairs = auditor._expected_pairs(auditor.PREFLIGHT_SEEDS)
        records = [
            auditor._validate_checkpoint(_valid_checkpoint(pair), pair, "a" * 64)
            for pair in pairs
        ]
        pair_ids = [pair["pair_id"] for pair in pairs]
        segment = {
            "schema": auditor.TIMING_SCHEMA,
            "segment_index": 1,
            "phase": "recovered_after_interruption",
            "recovered_after_interruption": True,
            "pair_ids": pair_ids,
            "pair_count": len(pair_ids),
            "elapsed_pool_wall_s": 1.5,
            "worker_end_to_end_wall_sum_s": sum(
                row["wall_time_s"]
                for record in records
                for row in record["rows"].values()
            ),
            "worker_simulation_wall_sum_s": sum(
                row["simulation_wall_time_s"]
                for record in records
                for row in record["rows"].values()
            ),
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            timing = output / "timing_segments"
            timing.mkdir()
            path = timing / "segment_001.json"
            path.write_text(json.dumps(segment), encoding="utf-8")
            result = auditor._verify_timing(output, records)
            self.assertEqual(result["pair_count"], 64)
            segment["recovered_after_interruption"] = False
            path.write_text(json.dumps(segment), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "phase/recovery provenance"):
                auditor._verify_timing(output, records)

    def test_compact_n100_join_needs_no_raw_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            compact = Path(temporary) / "n100_compact"
            compact.mkdir()
            for name in auditor.EXPECTED_N100_SHA256:
                shutil.copy2(auditor.N100_ROOT / name, compact / name)
            with mock.patch.object(auditor, "N100_ROOT", compact):
                verified = auditor._verify_n100_reference()
            self.assertEqual(verified["pair_count"], 3_200)
            self.assertEqual(verified["row_count"], 6_400)
            self.assertFalse((compact / "checkpoints").exists())

    def test_compact_n100_hash_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            compact = Path(temporary) / "n100_compact"
            compact.mkdir()
            for name in auditor.EXPECTED_N100_SHA256:
                shutil.copy2(auditor.N100_ROOT / name, compact / name)
            target = compact / "pairs.csv"
            target.write_bytes(target.read_bytes() + b"\n")
            with mock.patch.object(auditor, "N100_ROOT", compact):
                with self.assertRaisesRegex(RuntimeError, "reference drift"):
                    auditor._verify_n100_reference()

    def test_root_inventory_contract_is_exact(self) -> None:
        self.assertEqual(
            auditor.EXPECTED_PARTIAL_ROOT_FILES,
            {".run.lock", "run_manifest.json", "preflight_complete.json"},
        )

    def test_output_path_must_be_direct_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            campaign_root = Path(temporary) / "campaign"
            direct = campaign_root / "n1000_extension_2026-08-08_01"
            nested = direct / "nested"
            bad_name = campaign_root / "run_01"
            nested.mkdir(parents=True)
            bad_name.mkdir()
            with mock.patch.object(auditor, "CAMPAIGN_ROOT", campaign_root.resolve()):
                self.assertEqual(auditor._validate_output_path(str(direct)), direct.resolve())
                with self.assertRaisesRegex(RuntimeError, "direct, canonically named child"):
                    auditor._validate_output_path(str(nested))
                with self.assertRaisesRegex(RuntimeError, "canonically named child"):
                    auditor._validate_output_path(str(bad_name))

    def test_analysis_tree_rejects_unreviewed_extra_claims(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "key set differs"):
            auditor._assert_tree(
                {"estimate": 0.9, "extra_claim": "unreviewed"},
                {"estimate": 0.9},
                "analysis",
            )

    def test_complete_directly_binds_run_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            run_manifest = output / "run_manifest.json"
            run_manifest.write_text('{"schema":"test"}\n', encoding="utf-8")
            digest = hashlib.sha256(run_manifest.read_bytes()).hexdigest()
            size = run_manifest.stat().st_size
            complete = {"run_manifest_sha256": digest, "run_manifest_bytes": size}
            artifacts = {
                "run_manifest.json": {"sha256": digest, "bytes": size}
            }
            auditor._verify_complete_run_manifest_binding(output, complete, artifacts)
            complete["run_manifest_sha256"] = "0" * 64
            with self.assertRaisesRegex(RuntimeError, "directly bind"):
                auditor._verify_complete_run_manifest_binding(
                    output, complete, artifacts
                )
        self.assertEqual(len(auditor.EXPECTED_FINAL_ROOT_FILES), 12)
        self.assertEqual(
            auditor.EXPECTED_FINAL_ROOT_FILES - auditor.EXPECTED_PARTIAL_ROOT_FILES,
            {
                "results_long.csv",
                "pairs.csv",
                "arm_analysis.csv",
                "combined_arm_analysis.csv",
                "analysis.json",
                "runtime.json",
                "gate.json",
                "completion_manifest.json",
                "COMPLETE.json",
            },
        )

    def test_self_test_is_explicitly_simulation_free(self) -> None:
        source = ast.parse(AUDITOR_PATH.read_text(encoding="utf-8"))
        function = next(
            node
            for node in source.body
            if isinstance(node, ast.FunctionDef) and node.name == "_self_test"
        )
        called_names = {
            node.func.id
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertFalse(
            {
                "run_simulation",
                "execute_or_resume",
                "_run_pair_worker",
                "subprocess",
            }
            & called_names
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
