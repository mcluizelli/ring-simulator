"""Simulation-free tests for the corrected proportional n=1000 extension."""
from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "experiments"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_corrected_proportional_n1000_extension as driver  # noqa: E402


class CorrectedProportionalN1000ExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = driver.build_plan()
        cls.by_id = {pair["pair_id"]: pair for pair in cls.plan["pairs"]}

    def _checkpoint(self, pair: dict, *, segment_index: int = 1) -> dict:
        rows = []
        digest = "a" * 64
        config = pair["config"]
        flow_count = int(config["ring_size"]) * int(config["k"])
        ticks = 100
        completion = ticks * float(config["dt_s"])
        for position, allocator in enumerate(pair["execution_order"]):
            rows.append(
                {
                    "pair_id": pair["pair_id"],
                    "arm_id": config["arm_id"],
                    "sample_id": pair["sample_id"],
                    "family": "static_split",
                    "runner": "proportional",
                    "policy": "proportional",
                    "allocator": allocator,
                    "execution_position": position,
                    "config_sha256": pair["config_sha256"],
                    "topology_sha256": digest,
                    "ring_sha256": digest,
                    "route_sha256": digest,
                    "process_initial_sha256": digest,
                    "topology_instance_id": 10 + position,
                    "simulator_instance_id": 20 + position,
                    "background_instance_id": None,
                    "congestion_instance_id": None,
                    "adaptive_gate": None,
                    "completion_time_s": completion,
                    "completion_time_hex": driver.core._f64_hex(completion),
                    "simulated_ticks": ticks,
                    "wall_time_s": 1.0 + position,
                    "wall_time_hex": driver.core._f64_hex(1.0 + position),
                    "cpu_time_s": 0.0,
                    "cpu_time_hex": driver.core._f64_hex(0.0),
                    "simulation_wall_time_s": 0.5 + position,
                    "simulation_wall_time_hex": driver.core._f64_hex(0.5 + position),
                    "simulation_cpu_time_s": 0.0,
                    "simulation_cpu_time_hex": driver.core._f64_hex(0.0),
                    "conservation": {
                        "passed": True,
                        "checks": int(config["ring_size"]),
                        "foreground_flow_count": flow_count,
                        "individual_remaining_values_checked": flow_count,
                        "foreground_remaining_nonzero_count": 0,
                        "remaining_foreground_bytes": 0.0,
                        "foreground_remaining_min_bytes": 0.0,
                        "foreground_remaining_max_bytes": 0.0,
                        "non_bit_exact_flow_count": 0,
                        "maximum_abs_error_bytes": 0.0,
                        "maximum_per_flow_error_bytes": 0.0,
                    },
                }
            )
        return {
            "schema": "rate-allocator-pair-checkpoint-v1",
            "pair_id": pair["pair_id"],
            "pair_spec": pair,
            "rows": rows,
            "pair_gate": {
                "passed": True,
                "initial_digests_equal": True,
                "mutable_instances_distinct": True,
            },
            "plan_sha256": self.plan["plan_sha256"],
            "parent_timing": {
                "segment_index": segment_index,
                "pool_elapsed_at_checkpoint_s": 0.75,
            },
        }

    def _direct_synthetic_analysis(self) -> dict:
        extension_ids = [f"ext-{index:05d}" for index in range(28_800)]
        old_ids = [f"old-{index:04d}" for index in range(3_200)]
        extension = [
            {"pair_id": pair_id, "sample_id": 100}
            for pair_id in extension_ids
        ]
        old = [{"pair_id": pair_id, "sample_id": 0} for pair_id in old_ids]

        def domain(pair_count: int) -> dict:
            return {
                "estimand": "T_network_maxmin/T_link_local",
                "global": {
                    "pair_count": pair_count,
                    "point_estimate": 1.0,
                    "ci95_low": 0.9,
                    "ci95_high": 1.1,
                },
                "per_arm": {
                    "arm": {
                        "pair_count": pair_count,
                        "geometric_mean_ratio": 1.0,
                        "ci95_low": 0.9,
                        "ci95_high": 1.1,
                    }
                },
                "leave_one_seed_out": {
                    "minimum": 1.0,
                    "maximum": 1.0,
                    "single_seed_dependence": False,
                },
            }

        def expected_ids(seeds: object) -> list[str]:
            return extension_ids if len(list(seeds)) == 900 else [*old_ids, *extension_ids]

        with (
            mock.patch.object(driver, "_paired_rows", return_value=extension),
            mock.patch.object(driver, "_expected_pair_ids", side_effect=expected_ids),
            mock.patch.object(
                driver,
                "_pair_id_digest",
                return_value=driver.EXPECTED_COMBINED_PAIR_IDS_SHA256,
            ),
            mock.patch.object(
                driver,
                "_domain_analysis",
                side_effect=[domain(28_800), domain(28_672), domain(32_000)],
            ),
        ):
            analysis, _, _, _ = driver._analysis({}, {"rows": old})
        return analysis

    def test_exact_plan_domain_order_and_digests(self) -> None:
        plan = self.plan
        self.assertEqual((plan["arm_count"], plan["pair_count"]), (32, 28_800))
        self.assertEqual(plan["simulation_count"], 57_600)
        self.assertEqual(plan["canonical_arm_indices"], list(range(48, 80)))
        self.assertEqual(plan["sample_ids"], list(range(100, 1000)))
        self.assertEqual(plan["arm_sha256"], driver.EXPECTED_ARM_SHA256)
        self.assertEqual(
            plan["pair_id_list_sha256"], driver.EXPECTED_EXTENSION_PAIR_IDS_SHA256
        )
        self.assertEqual(
            plan["combined_pair_id_list_sha256"],
            driver.EXPECTED_COMBINED_PAIR_IDS_SHA256,
        )
        self.assertEqual(
            plan["allocator_first_pair_counts"],
            {driver.LEGACY_ALLOCATOR: 14_400, driver.MAXMIN_ALLOCATOR: 14_400},
        )
        first, last = plan["pairs"][0], plan["pairs"][-1]
        self.assertEqual(first["pair_id"], "a049_proportional_3tier_nb_p16_k2__s100")
        self.assertEqual(last["pair_id"], "a080_proportional_2tier_p64_k16__s999")
        self.assertEqual(first["sample_index"], first["sample_id"])
        self.assertEqual(first["ordinal"], first["arm_index"] * 1000 + 100)
        self.assertEqual(first["oracle_key"]["seed"], 100)

    def test_scope_contains_only_proportional_static_pairs(self) -> None:
        for pair in self.plan["pairs"]:
            config = pair["config"]
            self.assertEqual(
                (config["family"], config["runner"], config["policy"]),
                ("static_split", "proportional", "proportional"),
            )
            self.assertGreaterEqual(pair["sample_id"], 100)
            self.assertNotIn("controller", config)
            self.assertNotIn("background", config)
            self.assertNotIn("congestion", config)

    def test_preflight_is_all_arms_at_seeds_100_and_101(self) -> None:
        ids = self.plan["preflight_pair_ids"]
        self.assertEqual(len(ids), 64)
        pairs = {pair_id: {"pair_spec": self.by_id[pair_id]} for pair_id in ids}
        gate = driver._preflight_gate(self.plan, pairs)
        self.assertEqual(gate["seed_pair_counts"], {"100": 32, "101": 32})
        self.assertTrue(gate["integrity_only_no_effect_stopping"])
        with self.assertRaises(RuntimeError):
            driver._preflight_gate(self.plan, dict(list(pairs.items())[:-1]))

    def test_actual_preflight_seal_leaves_no_staging_and_rejects_residue(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            checkpoints_dir = output / "checkpoints"
            timing_dir = output / "timing_segments"
            checkpoints_dir.mkdir()
            timing_dir.mkdir()
            (output / ".run.lock").write_bytes(b"0")
            (output / "run_manifest.json").write_text("{}\n", encoding="utf-8")
            pair_ids = list(self.plan["preflight_pair_ids"])
            checkpoints = {}
            for pair_id in pair_ids:
                (checkpoints_dir / f"{pair_id}.json").write_text(
                    "{}\n", encoding="utf-8"
                )
                checkpoints[pair_id] = {"pair_spec": self.by_id[pair_id]}
            (timing_dir / "segment_001.json").write_text(
                json.dumps({"pair_ids": pair_ids}), encoding="utf-8"
            )
            manifest = {
                "driver_sha256": "d" * 64,
                "immutable_before": {
                    "sources": {},
                    "n100_reference_sha256": {},
                },
            }
            driver._seal_preflight_boundary(
                output,
                self.plan,
                checkpoints,
                manifest,
                require_exact_root=True,
            )
            self.assertTrue((output / "preflight_complete.json").is_file())
            self.assertFalse(
                any(
                    path.is_dir() and path.name == ".staging"
                    for path in output.rglob("*")
                )
            )
            self.assertEqual(
                {path.name for path in output.iterdir()},
                driver.PARTIAL_ROOT_NAMES,
            )

            residue = checkpoints_dir / ".staging"
            residue.mkdir()
            (residue / "orphan.tmp").write_bytes(b"x")
            with self.assertRaises(RuntimeError):
                driver._seal_preflight_boundary(
                    output,
                    self.plan,
                    checkpoints,
                    manifest,
                    require_exact_root=True,
                )

    def test_bootstrap_index_contracts(self) -> None:
        for count, key in (
            (900, "extension_primary"),
            (896, "extension_exposure_sensitivity"),
            (1000, "combined_secondary"),
        ):
            indexes = driver._bootstrap_indexes(
                count, driver.EXPECTED_BOOTSTRAP_SHA256[key]
            )
            self.assertEqual(indexes.shape, (20_000, count))
            del indexes

    def test_sealed_n100_compact_join_recomputes_configs(self) -> None:
        refs = driver._verify_n100_reference()
        self.assertEqual(refs["pair_count"], 3_200)
        self.assertEqual(refs["simulation_count"], 6_400)
        self.assertTrue(refs["canonical_config_sha256_recomputed"])
        self.assertEqual(refs["rows"][0]["sample_id"], 0)
        self.assertEqual(refs["rows"][-1]["sample_id"], 99)

    def test_combined_order_is_arm_major_not_old_then_extension(self) -> None:
        combined = driver._expected_pair_ids(range(1000))
        old_then_extension = [
            *driver._expected_pair_ids(range(100)),
            *driver._expected_pair_ids(range(100, 1000)),
        ]
        self.assertNotEqual(combined, old_then_extension)
        self.assertEqual(combined[99][-6:], "__s099")
        self.assertEqual(combined[100][-6:], "__s100")
        self.assertEqual(driver._pair_id_digest(combined), driver.EXPECTED_COMBINED_PAIR_IDS_SHA256)

    def test_analysis_root_schema_uses_canonical_combined_key(self) -> None:
        analysis = self._direct_synthetic_analysis()
        self.assertEqual(
            set(analysis),
            {
                "schema",
                "primary_domain",
                "secondary_domain",
                "analysis_role",
                "n100_reuse_is_secondary_only",
                "extension_primary",
                "sentinel_excluded_sensitivity",
                "combined_secondary",
                "decision",
                "scope_limits",
            },
        )
        self.assertNotIn("secondary_combined", analysis)

    def test_checkpoint_gate_rejects_conservation_and_timing_tamper(self) -> None:
        pair = self.plan["pairs"][0]
        checkpoint = self._checkpoint(pair)
        driver._validate_checkpoint(checkpoint, pair, self.plan["plan_sha256"])
        bad = json.loads(json.dumps(checkpoint))
        bad["rows"][0]["conservation"]["individual_remaining_values_checked"] -= 1
        with self.assertRaises(RuntimeError):
            driver._validate_checkpoint(bad, pair, self.plan["plan_sha256"])
        bad = json.loads(json.dumps(checkpoint))
        bad["rows"][0]["completion_time_hex"] = "0" * 16
        with self.assertRaises(RuntimeError):
            driver._validate_checkpoint(bad, pair, self.plan["plan_sha256"])

    def test_timing_regular_and_recovery_are_recomputed(self) -> None:
        pair = self.plan["pairs"][0]
        checkpoint = self._checkpoint(pair)
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            (output / "timing_segments").mkdir()
            segment = {
                "schema": "corrected-proportional-n1000-extension-timing-segment-v1",
                "segment_index": 1,
                "phase": "preflight_64",
                "pair_ids": [pair["pair_id"]],
                "pair_count": 1,
                "elapsed_pool_wall_s": 1.0,
                "worker_simulation_wall_sum_s": 2.0,
                "worker_end_to_end_wall_sum_s": 3.0,
                "recovered_after_interruption": False,
            }
            (output / "timing_segments" / "segment_001.json").write_text(
                json.dumps(segment), encoding="utf-8"
            )
            loaded = driver._load_timing(output, {pair["pair_id"]: checkpoint})
            self.assertEqual(len(loaded), 1)
            segment["worker_end_to_end_wall_sum_s"] = 4.0
            (output / "timing_segments" / "segment_001.json").write_text(
                json.dumps(segment), encoding="utf-8"
            )
            with self.assertRaises(RuntimeError):
                driver._load_timing(output, {pair["pair_id"]: checkpoint})

        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            (output / "timing_segments").mkdir()
            loaded = driver._load_timing(output, {pair["pair_id"]: checkpoint})
            self.assertEqual(loaded[0]["phase"], "recovered_after_interruption")
            self.assertEqual(loaded[0]["worker_end_to_end_wall_sum_s"], 3.0)

    def test_timing_inventory_rejects_unknown_and_supports_index_1000(self) -> None:
        self.assertEqual(driver._timing_path(Path("x"), 1000).name, "segment_1000.json")
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            timing = output / "timing_segments"
            timing.mkdir()
            for name in ("segment_1000.json", "segment_101.json", "segment_999.json"):
                (timing / name).write_text("{}", encoding="utf-8")
            self.assertEqual(
                [path.name for path in driver._ordered_timing_paths(timing)],
                ["segment_101.json", "segment_999.json", "segment_1000.json"],
            )
            for path in list(timing.iterdir()):
                path.unlink()
            (timing / "notes.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                driver._load_timing(output, {})

    def test_exact_directory_inventory_rejects_nested_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            (output / "checkpoints").mkdir()
            (output / "timing_segments").mkdir()
            (output / "checkpoints" / "extra").mkdir()
            with self.assertRaises(RuntimeError):
                driver._verify_directory_inventory(output, require_complete=False)

    def test_manifest_payload_and_authorization_are_tamper_evident(self) -> None:
        output = driver.OUTPUT_ROOT / "n1000_extension_2026-08-08_01"
        sources = {
            driver.DRIVER_PATH.relative_to(driver.ROOT).as_posix(): "b" * 64
        }
        immutable = {
            "git": {
                "execution_head": "1" * 40,
                "upstream": "origin/test",
            },
            "sources": sources,
            "n100_reference": {},
        }
        authorization = driver._authorization(self.plan, output, 4, immutable)
        manifest = driver._new_manifest(
            self.plan, output, 4, immutable, authorization
        )
        driver._verify_manifest(manifest, self.plan, output)
        bad = json.loads(json.dumps(manifest))
        bad["workers"] = 5
        with self.assertRaises(RuntimeError):
            driver._verify_manifest(bad, self.plan, output)

    def test_completion_manifest_validation_rejects_tampered_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            analysis = self._direct_synthetic_analysis()
            gate = {
                "schema": "corrected-proportional-n1000-extension-gate-v1",
                "passed": True,
                "primary_domain": "extension_only_seeds_100_999",
                "secondary_domain": "combined_seeds_0_999",
                "decision": "PENDING_INDEPENDENT_AUDIT_AND_RESEARCH_DECISION",
                "pair_count": 28_800,
                "row_count": 57_600,
            }
            runtime = {
                "schema": "corrected-proportional-n1000-extension-runtime-v1",
                "pair_count": 28_800,
            }
            for name, value in (
                ("analysis.json", analysis),
                ("gate.json", gate),
                ("runtime.json", runtime),
            ):
                (output / name).write_text(json.dumps(value), encoding="utf-8")
            manifest = {"plan_sha256": "c" * 64, "immutable_before": {"x": 1}}
            completion = {
                "schema": "corrected-proportional-n1000-extension-completion-v1",
                "status": "COMPLETE_PENDING_INDEPENDENT_AUDIT_AND_RESEARCH_DECISION",
                "plan_sha256": "c" * 64,
                "pair_count": 28_800,
                "simulation_count": 57_600,
                "combined_pair_count": 32_000,
                "completion_manifest_self_signed": False,
                "complete_file_self_signed": False,
                "completion_manifest_excludes_itself_and_complete": True,
                "run_lock_hashed_via_held_handle": True,
                "artifacts": {},
                "artifact_count": 0,
                "analysis_sha256": driver._sha256_file(output / "analysis.json"),
                "gate": gate,
                "runtime": runtime,
                "immutable_after": {"x": 1},
            }
            completion_path = output / "completion_manifest.json"
            completion_path.write_text(json.dumps(completion), encoding="utf-8")
            with mock.patch.object(driver, "_inventory", return_value={}):
                driver._validate_completion_manifest(output, manifest, object())
                completion["status"] = "READY"
                completion_path.write_text(json.dumps(completion), encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    driver._validate_completion_manifest(output, manifest, object())

    def test_completion_only_crash_removes_empty_atomic_staging(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            for name in driver.FINAL_ROOT_NAMES - {"COMPLETE.json"}:
                path = output / name
                if name in {"checkpoints", "timing_segments"}:
                    path.mkdir()
                elif name == ".run.lock":
                    path.write_bytes(b"0")
                else:
                    path.write_text("{}", encoding="utf-8")
            (output / ".staging").mkdir()
            manifest = {"plan_sha256": "c" * 64}
            completion = {
                "status": "COMPLETE_PENDING_INDEPENDENT_AUDIT_AND_RESEARCH_DECISION"
            }
            with (
                mock.patch.object(
                    driver, "_validate_completion_manifest", return_value=completion
                ),
                mock.patch.object(driver, "_immutable_after", return_value={}),
                mock.patch.object(driver, "_verify_directory_inventory"),
            ):
                result = driver._resume_completion_only(output, manifest, object())
            self.assertEqual(result["status"], completion["status"])
            self.assertTrue((output / "COMPLETE.json").is_file())
            self.assertFalse((output / ".staging").exists())

    def test_complete_marker_status_and_plan_are_tamper_evident(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            (output / "checkpoints").mkdir()
            (output / "timing_segments").mkdir()
            (output / "completion_manifest.json").write_text("{}", encoding="utf-8")
            (output / "run_manifest.json").write_text("{}", encoding="utf-8")
            completion = {
                "schema": "corrected-proportional-n1000-extension-completion-v1",
                "status": "COMPLETE_PENDING_INDEPENDENT_AUDIT_AND_RESEARCH_DECISION",
                "plan_sha256": "c" * 64,
                "pair_count": 28_800,
                "simulation_count": 57_600,
            }
            manifest = {"plan_sha256": "c" * 64}

            def write_marker(status: str, plan_sha256: str) -> None:
                marker = {
                    "schema": "corrected-proportional-n1000-extension-complete-v1",
                    "status": status,
                    "plan_sha256": plan_sha256,
                    "completion_manifest_sha256": driver._sha256_file(
                        output / "completion_manifest.json"
                    ),
                    "completion_manifest_bytes": (
                        output / "completion_manifest.json"
                    ).stat().st_size,
                    "run_manifest_sha256": driver._sha256_file(
                        output / "run_manifest.json"
                    ),
                    "run_manifest_bytes": (output / "run_manifest.json").stat().st_size,
                    "written_last": True,
                }
                (output / "COMPLETE.json").write_text(json.dumps(marker), encoding="utf-8")

            patches = (
                mock.patch.object(driver, "_verify_root_names"),
                mock.patch.object(driver, "_verify_directory_inventory"),
                mock.patch.object(
                    driver, "_validate_completion_manifest", return_value=completion
                ),
                mock.patch.object(driver, "_immutable_after", return_value={}),
            )
            with patches[0], patches[1], patches[2], patches[3]:
                write_marker(completion["status"], manifest["plan_sha256"])
                driver._verify_complete(output, manifest, object())
                write_marker("MISLEADING", manifest["plan_sha256"])
                with self.assertRaises(RuntimeError):
                    driver._verify_complete(output, manifest, object())
                write_marker(completion["status"], "d" * 64)
                with self.assertRaises(RuntimeError):
                    driver._verify_complete(output, manifest, object())

    def test_staging_cleanup_rejects_nonempty_crash_residue(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            (output / "checkpoints" / ".staging").mkdir(parents=True)
            (output / "timing_segments").mkdir()
            (output / "checkpoints" / ".staging" / "orphan.tmp").write_bytes(b"x")
            with self.assertRaises(RuntimeError):
                driver._cleanup_staging(output)

    def test_held_lock_hash_uses_exact_live_handle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / ".run.lock"
            with driver.core.ExclusiveRunLock(path) as lock:
                metadata = driver._held_lock_metadata(path, lock)
                self.assertTrue(metadata["hashed_via_held_handle"])
                other = Path(raw) / "other.lock"
                other.write_bytes(b"0")
                original = lock.path
                lock.path = other
                with self.assertRaises(RuntimeError):
                    driver._held_lock_metadata(path, lock)
                lock.path = original
            closed = path.open("rb")
            closed.close()
            fake = SimpleNamespace(path=path, handle=closed)
            with self.assertRaises(RuntimeError):
                driver._held_lock_metadata(path, fake)

    def test_dry_run_does_not_create_absent_parent_or_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            campaign_root = Path(raw) / "cp_n1000"
            output = campaign_root / "n1000_extension_2026-08-08_01"
            immutable = {
                "git": {"execution_head": "1" * 40},
                "sources": {},
                "n100_reference": {},
            }
            with (
                mock.patch.object(driver, "OUTPUT_ROOT", campaign_root.resolve()),
                mock.patch.object(driver, "_immutable_snapshot", return_value=immutable),
                mock.patch.object(
                    driver.shutil,
                    "disk_usage",
                    return_value=SimpleNamespace(free=10**12),
                ),
                mock.patch("builtins.print"),
            ):
                result = driver.dry_run(self.plan, output, 4)
            self.assertFalse(campaign_root.exists())
            self.assertFalse(output.exists())
            self.assertFalse(result["execution_writes_performed"])

    def test_source_has_no_duplicate_dict_literal_keys(self) -> None:
        tree = ast.parse(driver.DRIVER_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                literal_keys = [
                    key.value
                    for key in node.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                ]
                self.assertEqual(len(literal_keys), len(set(literal_keys)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
