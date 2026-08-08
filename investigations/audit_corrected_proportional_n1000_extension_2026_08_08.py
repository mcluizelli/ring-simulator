"""Independent read-only audit for the corrected proportional n=1000 extension.

The production audit deliberately does not import the campaign driver.  It
reconstructs the 32-arm, seeds-100..999 matrix independently, validates every
paired checkpoint and signed artifact, joins only the sealed compact n=100
exports, and recomputes the extension-primary and combined-secondary
statistics from first principles.  ``--self-test`` performs no simulations and
writes no files.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import re
import statistics
import struct
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
INVESTIGATIONS = ROOT / "investigations"
EXPERIMENTS = ROOT / "experiments"
SCRIPT_PATH = Path(__file__).resolve()
DRIVER_PATH = EXPERIMENTS / "run_corrected_proportional_n1000_extension.py"
SPEC_PATH = INVESTIGATIONS / "CORRECTED_PROPORTIONAL_N1000_EXTENSION_SPEC_2026_08_08.md"
SIM_PATH = ROOT / "sim.py"
CANONICAL_PATH = EXPERIMENTS / "run_rate_allocator_n100.py"
CORE_PATH = EXPERIMENTS / "run_rate_allocator_pilot.py"
N100_DRIVER_PATH = EXPERIMENTS / "run_corrected_proportional_n100.py"
CAMPAIGN_ROOT = (INVESTIGATIONS / "cp_n1000").resolve()
OUTPUT_NAME_RE = re.compile(r"n1000_extension_\d{4}-\d{2}-\d{2}_\d{2}")
N100_ROOT = (
    INVESTIGATIONS
    / "corrected_proportional_n100"
    / "n100_2026-08-07_02"
).resolve()

ALLOCATORS = ("link_local_equal_share", "network_maxmin")
EXTENSION_SEEDS = tuple(range(100, 1_000))
COMBINED_SEEDS = tuple(range(1_000))
ARM_INDICES = tuple(range(48, 80))
ARM_COUNT = 32
EXTENSION_PAIR_COUNT = 28_800
EXTENSION_ROW_COUNT = 57_600
COMBINED_PAIR_COUNT = 32_000
N100_PAIR_COUNT = 3_200
N100_ROW_COUNT = 6_400
PREFLIGHT_SEEDS = (100, 101)
PREFLIGHT_PAIR_COUNT = 64
COMPACT_N100_CONSERVATION_TOLERANCE_B = 1e-6
PROPORTIONAL_CONSERVATION_ULPS = 128
BOOTSTRAP_REPLICATES = 20_000
BOOTSTRAP_SEED = 20_260_807
APPROVED_BASELINE_COMMIT = "f2d8f88ec3cef01c250987df88245dc4361c245b"

EXPECTED_ARM_PAYLOAD_SHA256 = (
    "467f87d72a89bf9bb15e80d824f43a5465f6731e3b890f1cea05e93a0f383b09"
)
EXPECTED_EXTENSION_PAIR_ID_SHA256 = (
    "12f52040dbc480e3566dd9d25c4c89ae4d4cf40910bf5c30fc6834a54817268c"
)
EXPECTED_COMBINED_PAIR_ID_SHA256 = (
    "3bd51d5ba6f303b4dcd0750f7a18d1e9c9a310962dfa339454cd6d9809f24717"
)
EXPECTED_EXTENSION_BOOTSTRAP_SHA256 = (
    "901e342e8d8849fcdd8bec11e7019b6b1a24d2ab73d62c61ec8eba8009f171d4"
)
EXPECTED_COMBINED_BOOTSTRAP_SHA256 = (
    "983cc7176ab26dfcbaa22467b888439c67557da634f2bf3945721c64e42c3070"
)
SENTINEL_OVERLAP_SEEDS = frozenset({174, 199, 353, 657})
EXPECTED_SENTINEL_OVERLAP_PAIR_IDS = frozenset(
    {
        "a055_proportional_3tier_nb_p64_k8__s199",
        "a055_proportional_3tier_nb_p64_k8__s657",
        "a071_proportional_3tier_os4_p64_k8__s174",
        "a071_proportional_3tier_os4_p64_k8__s353",
        "a072_proportional_3tier_os4_p64_k16__s174",
        "a072_proportional_3tier_os4_p64_k16__s353",
    }
)
EXPECTED_SENTINEL_EXCLUDED_BOOTSTRAP_SHA256 = (
    "92c451c7526085b32723402f91f2b06c0806e5345ebd6a74122db6267d1481ea"
)

# Rebind exactly once after the driver and specification are final.  Production
# and self-test both fail closed while either marker remains unresolved.
EXPECTED_DRIVER_SHA256 = (
    "3f9e67a8524c01bb09b0f8e0538b911052ca84f59fe7952a1dd28109625ea190"
)
EXPECTED_SPEC_SHA256 = (
    "8f70b5d0963de93539ad663d1e195ac52ea0cc568d5dcf0bbcb6740fae7bdc42"
)
EXPECTED_SOURCE_SHA256 = {
    SIM_PATH: "96505cefe2e5aa761b80080d77145bfd384c688ce4a8ca5792f8f7ce17ef59bd",
    CANONICAL_PATH: "7d01a2e598c799b0c533fb650f33b8537f51fa3187f427fcf9ada108d56fd8b4",
    CORE_PATH: "9613d3a753ea8e5c720bc2a5ac43110fd363aba13181790100fda936501408d0",
    N100_DRIVER_PATH: "670d98ab17960fb2061de04eecca993cf35fe568a98b164a8dc3ce780e695196",
    INVESTIGATIONS / "maxmin_gate_2026_08_06.py": (
        "2905e293712650b8c2ef8a259326e5502f102bf5773515712979aef2a8f7cb1b"
    ),
}
EXPECTED_N100_SHA256 = {
    "COMPLETE.json": "ab9945a3d9826fc1a75af55657e65f246369bb322ed676972a379f9f33bf21ed",
    "completion_manifest.json": "6355cda3b07e025da2e88c8544a1a82760212510203e1b5f0ba08930c6691810",
    "pairs.csv": "d3acdacc328dfa567c816918b331ff8f6ef8bf27c36e226b0083aa4860e81f9b",
    "results_long.csv": "e599ea81f137abe0daee218ad465d86668e8a9ba38d40e7c7eb3a9f23461c7c8",
}

PLAN_SCHEMA = "corrected-proportional-n1000-extension-plan-v1"
RUN_SCHEMA = "corrected-proportional-n1000-extension-run-v1"
TIMING_SCHEMA = "corrected-proportional-n1000-extension-timing-segment-v1"
PREFLIGHT_SCHEMA = "corrected-proportional-n1000-extension-preflight-v1"
ANALYSIS_SCHEMA = "corrected-proportional-n1000-extension-analysis-v1"
RUNTIME_SCHEMA = "corrected-proportional-n1000-extension-runtime-v1"
GATE_SCHEMA = "corrected-proportional-n1000-extension-gate-v1"
COMPLETION_SCHEMA = "corrected-proportional-n1000-extension-completion-v1"
COMPLETE_SCHEMA = "corrected-proportional-n1000-extension-complete-v1"

EXPECTED_PARTIAL_ROOT_FILES = frozenset(
    {".run.lock", "run_manifest.json", "preflight_complete.json"}
)
EXPECTED_FINAL_ROOT_FILES = EXPECTED_PARTIAL_ROOT_FILES | {
    "results_long.csv",
    "pairs.csv",
    "arm_analysis.csv",
    "combined_arm_analysis.csv",
    "analysis.json",
    "runtime.json",
    "gate.json",
    "completion_manifest.json",
    "COMPLETE.json",
}


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _read_json(path: Path) -> Any:
    _require(path.is_file(), f"missing JSON artifact: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"invalid JSON artifact: {path}") from exc


def _read_csv(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    _require(path.is_file(), f"missing CSV artifact: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        _require(reader.fieldnames is not None, f"CSV has no header: {path}")
        return list(reader.fieldnames), [dict(row) for row in reader]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _valid_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _valid_git_oid(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def _f64_hex(value: Any) -> str:
    return struct.pack(">d", float(value)).hex()


def _finite(value: Any, label: str, *, positive: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{label} is not numeric") from exc
    _require(math.isfinite(result), f"{label} is not finite")
    if positive:
        _require(result > 0.0, f"{label} is not positive")
    return result


def _expected_arms() -> List[Dict[str, Any]]:
    arms: List[Dict[str, Any]] = []
    fabrics = (
        ("3tier_nb", 3, 1.0),
        ("3tier_os2", 3, 2.0),
        ("3tier_os4", 3, 4.0),
        ("2tier", 2, 1.0),
    )
    for fabric, n_tiers, oversub in fabrics:
        for ring_size in (16, 64):
            for split_count in (2, 4, 8, 16):
                arms.append(
                    {
                        "arm_id": (
                            f"proportional_{fabric}_p{ring_size}_k{split_count}"
                        ),
                        "bytes_per_neighbor": 67_108_864,
                        "dt_s": 0.00005,
                        "fabric": fabric,
                        "family": "static_split",
                        "k": split_count,
                        "link_Gbps": 100.0,
                        "n_tiers": n_tiers,
                        "oracle_kind": "proportional",
                        "oversub": oversub,
                        "placement": "uniform_without_replacement",
                        "policy": "proportional",
                        "redistribution_window_s": 0.001,
                        "ring_size": ring_size,
                        "runner": "proportional",
                        "topology_k": 16,
                    }
                )
    _require(len(arms) == ARM_COUNT, "independent arm construction drift")
    _require(
        _json_digest(arms) == EXPECTED_ARM_PAYLOAD_SHA256,
        "independent arm payload digest drift",
    )
    return arms


def _pair_id(arm_index: int, arm_id: str, sample_id: int) -> str:
    return f"a{arm_index + 1:03d}_{arm_id}__s{sample_id:03d}"


def _expected_pairs(seeds: Sequence[int] = EXTENSION_SEEDS) -> List[Dict[str, Any]]:
    pairs: List[Dict[str, Any]] = []
    for offset, arm in enumerate(_expected_arms()):
        arm_index = 48 + offset
        for sample_id in seeds:
            config = {
                **arm,
                "sample_id": int(sample_id),
                "placement_seed": 9_000 + int(sample_id),
                "topology_seed": 1,
            }
            ordinal = arm_index * 1_000 + int(sample_id)
            order = ALLOCATORS if ordinal % 2 == 0 else tuple(reversed(ALLOCATORS))
            pairs.append(
                {
                    "arm_index": arm_index,
                    "config": config,
                    "config_sha256": _json_digest(config),
                    "execution_order": list(order),
                    "oracle_key": {
                        "P": int(arm["ring_size"]),
                        "fabric": str(arm["fabric"]),
                        "k": int(arm["k"]),
                        "seed": int(sample_id),
                    },
                    "ordinal": ordinal,
                    "pair_id": _pair_id(arm_index, str(arm["arm_id"]), int(sample_id)),
                    "sample_id": int(sample_id),
                    "sample_index": int(sample_id),
                }
            )
    return pairs


def _expected_pair_ids(seeds: Sequence[int]) -> List[str]:
    return [pair["pair_id"] for pair in _expected_pairs(seeds)]


def _expected_preflight_ids() -> List[str]:
    return _expected_pair_ids(PREFLIGHT_SEEDS)


def _bootstrap_indexes(seed_count: int) -> Tuple[np.ndarray, str]:
    generator = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED))
    indexes = generator.integers(
        0,
        seed_count,
        size=(BOOTSTRAP_REPLICATES, seed_count),
        dtype=np.uint32,
    )
    little_endian = np.ascontiguousarray(indexes.astype("<u4", copy=False))
    return indexes, hashlib.sha256(little_endian.tobytes(order="C")).hexdigest()


def _tick_class(delta_ticks: int) -> str:
    if delta_ticks <= -2:
        return "maxmin_faster_by_2plus"
    if delta_ticks == 0:
        return "exact_tie"
    if delta_ticks in (-1, 1):
        return "one_tick_tie"
    if delta_ticks >= 2:
        return "maxmin_slower_by_2plus"
    raise AssertionError("unreachable tick class")


def _verify_source_seals() -> Dict[str, str]:
    _require(
        _valid_digest(EXPECTED_DRIVER_SHA256),
        "auditor driver hash has not been rebound to the final driver",
    )
    _require(
        _valid_digest(EXPECTED_SPEC_SHA256),
        "auditor specification hash has not been rebound to the final specification",
    )
    expected = {
        **EXPECTED_SOURCE_SHA256,
        DRIVER_PATH: EXPECTED_DRIVER_SHA256,
        SPEC_PATH: EXPECTED_SPEC_SHA256,
    }
    actual: Dict[str, str] = {}
    for path, expected_hash in expected.items():
        _require(path.is_file(), f"sealed source is missing: {path.relative_to(ROOT)}")
        digest = _sha256_file(path)
        _require(digest == expected_hash, f"sealed source drift: {path.relative_to(ROOT)}")
        actual[path.relative_to(ROOT).as_posix()] = digest
    return actual


def _driver_contract_from_ast() -> Dict[str, Any]:
    """Inspect literal safety contracts without importing driver code."""
    _require(DRIVER_PATH.is_file(), "campaign driver is missing")
    tree = ast.parse(DRIVER_PATH.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assignments: Dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                assignments[target.id] = node.value
    return {
        "imports_auditor": any("audit_corrected_proportional_n1000_extension" in name for name in imports),
        "has_main_guard": any(
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
            for node in tree.body
        ),
        "assignment_names": sorted(assignments),
    }


def _verify_prior_sentinel_overlap() -> Dict[str, Any]:
    """Recover the prior gate's static proportional sentinel domain from AST."""
    path = INVESTIGATIONS / "maxmin_gate_2026_08_06.py"
    _require(
        _sha256_file(path) == EXPECTED_SOURCE_SHA256[path],
        "prior max-min gate source drift",
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "run_dynamic_gate"
        ),
        None,
    )
    _require(function is not None, "prior max-min gate entry point is missing")
    sentinel_cells: Any = None
    for node in ast.walk(function):
        if not isinstance(node, ast.For) or not isinstance(node.target, ast.Tuple):
            continue
        names = [
            element.id if isinstance(element, ast.Name) else None
            for element in node.target.elts
        ]
        if names == ["cell", "fabric", "oversub", "seeds"]:
            try:
                sentinel_cells = ast.literal_eval(node.iter)
            except Exception as exc:
                raise RuntimeError("prior sentinel cell literals are not recoverable") from exc
            break
    _require(
        sentinel_cells
        == (
            ("N0", "3tier_nb", 1.0, [0, 199, 657]),
            ("O0", "3tier_os4", 4.0, [0, 353, 174]),
        ),
        "prior static sentinel seed domain changed",
    )
    overlap_ids = {
        _pair_id(54, "proportional_3tier_nb_p64_k8", seed)
        for seed in (199, 657)
    }
    overlap_ids.update(
        _pair_id(arm_index, arm_id, seed)
        for arm_index, arm_id in (
            (70, "proportional_3tier_os4_p64_k8"),
            (71, "proportional_3tier_os4_p64_k16"),
        )
        for seed in (174, 353)
    )
    _require(
        overlap_ids == EXPECTED_SENTINEL_OVERLAP_PAIR_IDS,
        "independent prior-sentinel overlap derivation drift",
    )
    _require(
        {int(pair_id.rsplit("__s", 1)[1]) for pair_id in overlap_ids}
        == SENTINEL_OVERLAP_SEEDS,
        "prior-sentinel overlap seed clusters drift",
    )
    return {
        "pair_ids": sorted(overlap_ids),
        "pair_count": len(overlap_ids),
        "seed_ids": sorted(SENTINEL_OVERLAP_SEEDS),
        "seed_cluster_count": len(SENTINEL_OVERLAP_SEEDS),
    }


def _verify_plan(manifest: Mapping[str, Any]) -> Tuple[List[Dict[str, Any]], str]:
    _require(
        set(manifest)
        == {
            "schema",
            "created_utc",
            "output",
            "workers",
            "plan",
            "plan_sha256",
            "authorization_sha256",
            "driver_sha256",
            "baseline_ancestor",
            "git",
            "immutable_before",
            "platform",
            "python",
            "multiprocessing_start_method",
            "execution_phases",
            "preflight_is_integrity_only",
            "fixed_sample_no_adaptive_stopping",
            "checkpoint_policy",
            "output_contract",
            "manifest_payload_sha256",
        },
        "run-manifest key set differs from the frozen contract",
    )
    _require(manifest.get("schema") == RUN_SCHEMA, "run-manifest schema mismatch")
    _require(manifest.get("driver_sha256") == EXPECTED_DRIVER_SHA256, "manifest driver seal mismatch")
    plan = manifest.get("plan")
    _require(isinstance(plan, dict), "manifest plan is missing")
    _require(
        set(plan)
        == {
            "schema",
            "sample_ids",
            "allocators",
            "arms",
            "canonical_arm_indices",
            "pairs",
            "arm_count",
            "pair_count",
            "simulation_count",
            "combined_pair_count",
            "arm_sha256",
            "pair_id_list_sha256",
            "combined_pair_id_list_sha256",
            "allocator_first_pair_counts",
            "preflight_pair_ids",
            "primary_scope",
            "secondary_scope",
            "excluded_estimator_inputs",
            "exposure_sensitivity_excluded_seed_clusters",
            "no_other_execution_scope",
            "plan_sha256",
        },
        "plan key set differs from the frozen contract",
    )
    _require(plan.get("schema") == PLAN_SCHEMA, "plan schema mismatch")
    recorded_plan_hash = str(plan.get("plan_sha256", ""))
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    _require(
        _valid_digest(recorded_plan_hash) and _json_digest(unsigned) == recorded_plan_hash,
        "plan payload digest mismatch",
    )
    _require(manifest.get("plan_sha256") == recorded_plan_hash, "manifest/plan hash mismatch")
    unsigned_manifest = dict(manifest)
    recorded_manifest_hash = unsigned_manifest.pop("manifest_payload_sha256", None)
    _require(
        _valid_digest(recorded_manifest_hash)
        and _json_digest(unsigned_manifest) == recorded_manifest_hash,
        "run-manifest payload digest mismatch",
    )

    expected = _expected_pairs()
    expected_ids = [pair["pair_id"] for pair in expected]
    _require(len(expected_ids) == EXTENSION_PAIR_COUNT, "independent extension cardinality drift")
    _require(
        _json_digest(expected_ids) == EXPECTED_EXTENSION_PAIR_ID_SHA256,
        "independent extension pair-ID digest drift",
    )
    _require(plan.get("arms") == _expected_arms(), "plan arms differ from independent matrix")
    _require(plan.get("pairs") == expected, "plan pairs differ from independent matrix")
    _require(plan.get("sample_ids") == list(EXTENSION_SEEDS), "plan seed domain is not 100..999")
    _require(plan.get("allocators") == list(ALLOCATORS), "plan allocator set/order mismatch")
    _require(
        int(plan.get("arm_count", -1)) == ARM_COUNT
        and int(plan.get("pair_count", -1)) == EXTENSION_PAIR_COUNT
        and int(plan.get("simulation_count", -1)) == EXTENSION_ROW_COUNT,
        "plan cardinality mismatch",
    )
    _require(
        plan.get("pair_id_list_sha256") == EXPECTED_EXTENSION_PAIR_ID_SHA256,
        "plan pair-ID seal mismatch",
    )
    _require(
        plan.get("combined_pair_id_list_sha256") == EXPECTED_COMBINED_PAIR_ID_SHA256,
        "plan combined pair-ID seal mismatch",
    )
    _require(
        plan.get("arm_sha256") == EXPECTED_ARM_PAYLOAD_SHA256
        and plan.get("canonical_arm_indices") == list(ARM_INDICES)
        and int(plan.get("combined_pair_count", -1)) == COMBINED_PAIR_COUNT,
        "plan arm/combined metadata mismatch",
    )
    _require(
        plan.get("primary_scope")
        == "extension_seeds_100_through_999_validation_not_blind_holdout"
        and plan.get("secondary_scope")
        == "sealed_n100_plus_extension_read_only"
        and plan.get("excluded_estimator_inputs")
        == ["legacy_v11", "prior_maxmin_gate", "equal_policy"]
        and plan.get("exposure_sensitivity_excluded_seed_clusters")
        == sorted(SENTINEL_OVERLAP_SEEDS)
        and plan.get("no_other_execution_scope") is True,
        "plan estimator/scope boundary mismatch",
    )
    first = Counter(pair["execution_order"][0] for pair in expected)
    _require(
        dict(first) == {ALLOCATORS[0]: 14_400, ALLOCATORS[1]: 14_400},
        "independent allocator-first order is unbalanced",
    )
    _require(
        plan.get("allocator_first_pair_counts") == dict(sorted(first.items())),
        "recorded allocator-first counts mismatch",
    )
    _require(
        plan.get("preflight_pair_ids") == _expected_preflight_ids(),
        "preflight is not seeds 100 and 101 across all arms",
    )
    _require(
        all(int(pair["sample_id"]) >= 100 for pair in plan["pairs"]),
        "plan attempts to simulate a seed from the sealed n=100 domain",
    )
    return expected, recorded_plan_hash


def _verify_manifest_provenance(manifest: Mapping[str, Any], output: Path) -> Dict[str, Any]:
    _require(Path(str(manifest.get("output", ""))).resolve() == output, "manifest output path mismatch")
    _require(
        1 <= int(manifest.get("workers", 0)) <= 8,
        "manifest worker count is outside the authorized 1..8 range",
    )
    _require(manifest.get("multiprocessing_start_method") == "spawn", "start method is not spawn")
    _require(
        manifest.get("checkpoint_policy") == "one atomic parent-written JSON per paired checkpoint",
        "checkpoint atomicity policy mismatch",
    )
    immutable = manifest.get("immutable_before")
    _require(isinstance(immutable, dict), "manifest immutable-before snapshot is missing")
    expected_authorization = _json_digest(
        {
            "schema": "corrected-proportional-n1000-extension-authorization-v1",
            "plan_sha256": manifest.get("plan_sha256"),
            "output": str(output),
            "workers": int(manifest.get("workers", 0)),
            "execution_head": immutable.get("git", {}).get("execution_head"),
            "sources": immutable.get("sources"),
            "n100_reference": immutable.get("n100_reference"),
        }
    )
    _require(
        manifest.get("authorization_sha256") == expected_authorization,
        "run-manifest execution authorization mismatch",
    )
    expected_partial_names = sorted(
        EXPECTED_PARTIAL_ROOT_FILES | {"checkpoints", "timing_segments"}
    )
    expected_final_names = sorted(
        EXPECTED_FINAL_ROOT_FILES | {"checkpoints", "timing_segments"}
    )
    _require(
        manifest.get("execution_phases") == ["preflight_64", "remaining_28736"]
        and manifest.get("preflight_is_integrity_only") is True
        and manifest.get("fixed_sample_no_adaptive_stopping") is True
        and manifest.get("output_contract")
        == {
            "partial_root_names": expected_partial_names,
            "final_root_names": expected_final_names,
            "checkpoints_create_once": True,
            "timing_segments_create_once": True,
            "completion_manifest_only_crash_state_is_resumable": True,
        },
        "run-manifest phase/output contract mismatch",
    )
    git = immutable.get("git")
    _require(isinstance(git, dict), "manifest git provenance is missing")
    _require(
        git.get("baseline_is_ancestor") is True
        and int(git.get("ahead", -1)) == 0
        and int(git.get("behind", -1)) == 0
        and git.get("unrelated_dirty_paths") == []
        and git.get("output_state_allowed") is False,
        "fresh campaign execution was not clean/pushed at upstream 0/0",
    )
    head = git.get("execution_head")
    _require(_valid_git_oid(head), "campaign git HEAD is invalid")
    baseline = str(
        git.get("baseline_commit", "")
    )
    _require(
        baseline == APPROVED_BASELINE_COMMIT,
        "manifest does not bind the approved f2d8f88 baseline ancestry",
    )
    ancestry = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "merge-base",
            "--is-ancestor",
            APPROVED_BASELINE_COMMIT,
            str(head),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    _require(
        ancestry.returncode == 0,
        "recorded clean execution HEAD does not descend from the approved baseline",
    )
    source_map = immutable.get("sources")
    _require(isinstance(source_map, dict), "manifest source seal map is missing")
    _require(
        immutable.get("source_sha256") == source_map,
        "manifest source-hash alias differs from the source seal map",
    )
    actual_sources = _verify_source_seals()
    for relative, digest in actual_sources.items():
        _require(source_map.get(relative) == digest, f"manifest source seal mismatch: {relative}")
    n100_reference = immutable.get("n100_reference")
    _require(isinstance(n100_reference, dict), "manifest n=100 reference seals are missing")
    n100_map = n100_reference.get("hashes")
    _require(isinstance(n100_map, dict), "manifest n=100 raw-hash map is missing")
    _require(
        immutable.get("n100_reference_sha256") == n100_map,
        "manifest n=100 raw-hash alias differs from the compact reference",
    )
    for name, digest in EXPECTED_N100_SHA256.items():
        _require(
            n100_map.get(name) == digest,
            f"manifest n=100 seal mismatch: {name}",
        )
    exposure = immutable.get("exposure_provenance_only")
    _require(
        exposure
        == {
            "path": "investigations/maxmin_gate_2026_08_06.py",
            "sha256": EXPECTED_SOURCE_SHA256[
                INVESTIGATIONS / "maxmin_gate_2026_08_06.py"
            ],
            "estimator_input": False,
            "excluded_seed_clusters": sorted(SENTINEL_OVERLAP_SEEDS),
        },
        "manifest exposure-provenance boundary mismatch",
    )
    _require(
        manifest.get("baseline_ancestor") == APPROVED_BASELINE_COMMIT
        and manifest.get("git")
        == {
            "head": head,
            "dirty": False,
            "upstream": git.get("upstream"),
            "ahead": 0,
            "behind": 0,
        },
        "run-manifest top-level git/baseline summary mismatch",
    )
    return {"git_head": head, "baseline_commit": baseline, "source_count": len(actual_sources)}


def _verify_n100_reference() -> Dict[str, Any]:
    for name, expected_hash in EXPECTED_N100_SHA256.items():
        path = N100_ROOT / name
        _require(path.is_file(), f"sealed n=100 compact reference is missing: {name}")
        _require(_sha256_file(path) == expected_hash, f"sealed n=100 reference drift: {name}")

    complete = _read_json(N100_ROOT / "COMPLETE.json")
    completion = _read_json(N100_ROOT / "completion_manifest.json")
    _require(
        complete.get("completion_manifest_sha256")
        == EXPECTED_N100_SHA256["completion_manifest.json"],
        "n=100 COMPLETE/completion linkage mismatch",
    )
    _require(
        complete.get("completion_manifest_bytes")
        == (N100_ROOT / "completion_manifest.json").stat().st_size,
        "n=100 COMPLETE byte-count linkage mismatch",
    )
    artifacts = completion.get("artifacts")
    _require(isinstance(artifacts, dict), "n=100 completion artifact map is missing")
    for name in ("pairs.csv", "results_long.csv"):
        signature = artifacts.get(name)
        _require(
            isinstance(signature, dict)
            and signature.get("sha256") == EXPECTED_N100_SHA256[name]
            and int(signature.get("bytes", -1)) == (N100_ROOT / name).stat().st_size,
            f"n=100 completion signature mismatch: {name}",
        )

    pair_header, pair_rows = _read_csv(N100_ROOT / "pairs.csv")
    result_header, result_rows = _read_csv(N100_ROOT / "results_long.csv")
    required_pair = {
        "pair_id", "arm_id", "sample_id", "fabric", "ring_size", "k",
        "link_local_time_s", "network_maxmin_time_s",
        "network_over_link_local", "network_minus_link_local_ticks",
    }
    required_result = {
        "pair_id", "arm_id", "sample_id", "allocator", "execution_position",
        "completion_time_s", "completion_time_hex", "simulated_ticks",
        "config_sha256", "topology_sha256", "ring_sha256", "route_sha256",
        "conservation_max_error_B", "conservation_remaining_B",
        "remaining_nonzero_count",
    }
    _require(required_pair <= set(pair_header), "n=100 pairs.csv schema is incomplete")
    _require(required_result <= set(result_header), "n=100 results_long.csv schema is incomplete")
    _require(len(pair_rows) == N100_PAIR_COUNT, "n=100 pair-row count mismatch")
    _require(len(result_rows) == N100_ROW_COUNT, "n=100 allocator-row count mismatch")

    expected_pairs = _expected_pairs(tuple(range(100)))
    expected_ids = [pair["pair_id"] for pair in expected_pairs]
    _require([row["pair_id"] for row in pair_rows] == expected_ids, "n=100 pair order/IDs mismatch")
    _require(len(set(expected_ids)) == N100_PAIR_COUNT, "n=100 pair IDs are not unique")
    expected_by_id = {pair["pair_id"]: pair for pair in expected_pairs}
    pair_map: Dict[str, Dict[str, Any]] = {}
    for row in pair_rows:
        pair_id = row["pair_id"]
        expected = expected_by_id[pair_id]
        sample_id = int(row["sample_id"])
        _require(0 <= sample_id < 100, f"n=100 seed outside 0..99: {pair_id}")
        _require(
            row["arm_id"] == expected["config"]["arm_id"]
            and row["fabric"] == expected["config"]["fabric"]
            and int(row["ring_size"]) == expected["config"]["ring_size"]
            and int(row["k"]) == expected["config"]["k"],
            f"n=100 pair metadata mismatch: {pair_id}",
        )
        local_time = _finite(row["link_local_time_s"], f"{pair_id}:n100 local", positive=True)
        maxmin_time = _finite(row["network_maxmin_time_s"], f"{pair_id}:n100 maxmin", positive=True)
        ratio = _finite(row["network_over_link_local"], f"{pair_id}:n100 ratio", positive=True)
        _require(
            math.isclose(ratio, maxmin_time / local_time, rel_tol=2e-15, abs_tol=0.0),
            f"n=100 pair ratio mismatch: {pair_id}",
        )
        pair_map[pair_id] = {
            "pair_id": pair_id,
            "arm_id": row["arm_id"],
            "fabric": row["fabric"],
            "P": int(row["ring_size"]),
            "k": int(row["k"]),
            "sample_id": sample_id,
            "local_time": local_time,
            "maxmin_time": maxmin_time,
            "ratio": maxmin_time / local_time,
            "delta_ticks": int(row["network_minus_link_local_ticks"]),
        }

    result_map: Dict[Tuple[str, str], Dict[str, str]] = {}
    for row in result_rows:
        key = (row["pair_id"], row["allocator"])
        _require(row["pair_id"] in pair_map, f"orphan n=100 allocator row: {row['pair_id']}")
        _require(row["allocator"] in ALLOCATORS, f"unknown n=100 allocator: {row['allocator']}")
        _require(key not in result_map, f"duplicate n=100 allocator row: {key}")
        result_map[key] = row
        expected = expected_by_id[row["pair_id"]]
        _require(int(row["sample_id"]) == expected["sample_id"], f"n=100 result seed mismatch: {key}")
        _require(int(row["execution_position"]) == expected["execution_order"].index(row["allocator"]), f"n=100 order mismatch: {key}")
        _require(row["config_sha256"] == expected["config_sha256"], f"n=100 config seal mismatch: {key}")
        time_value = _finite(row["completion_time_s"], f"{key}:completion", positive=True)
        _require(row["completion_time_hex"] == _f64_hex(time_value), f"n=100 float seal mismatch: {key}")
        _require(_finite(row["conservation_max_error_B"], f"{key}:conservation") <= COMPACT_N100_CONSERVATION_TOLERANCE_B, f"n=100 conservation error: {key}")
        _require(abs(_finite(row["conservation_remaining_B"], f"{key}:remaining")) <= COMPACT_N100_CONSERVATION_TOLERANCE_B, f"n=100 remaining bytes: {key}")
        _require(int(row["remaining_nonzero_count"]) == 0, f"n=100 nonzero remaining flows: {key}")
    _require(len(result_map) == N100_ROW_COUNT, "n=100 allocator-row bijection mismatch")
    for pair_id, record in pair_map.items():
        local = result_map[(pair_id, ALLOCATORS[0])]
        maxmin = result_map[(pair_id, ALLOCATORS[1])]
        _require(float(local["completion_time_s"]) == record["local_time"], f"n=100 pair/result local mismatch: {pair_id}")
        _require(float(maxmin["completion_time_s"]) == record["maxmin_time"], f"n=100 pair/result maxmin mismatch: {pair_id}")
        _require(int(maxmin["simulated_ticks"]) - int(local["simulated_ticks"]) == record["delta_ticks"], f"n=100 pair/result tick mismatch: {pair_id}")
        for digest_field in ("topology_sha256", "ring_sha256", "route_sha256"):
            _require(local[digest_field] == maxmin[digest_field] and _valid_digest(local[digest_field]), f"n=100 paired {digest_field} mismatch: {pair_id}")

    return {
        "records": [pair_map[pair_id] for pair_id in expected_ids],
        "pair_count": len(pair_map),
        "row_count": len(result_map),
        "complete_sha256": EXPECTED_N100_SHA256["COMPLETE.json"],
        "completion_manifest_sha256": EXPECTED_N100_SHA256["completion_manifest.json"],
    }


def _checkpoint_row_map(checkpoint: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    rows = checkpoint.get("rows")
    _require(isinstance(rows, list) and len(rows) == 2, "checkpoint does not contain two allocator rows")
    mapped = {str(row.get("allocator")): row for row in rows if isinstance(row, dict)}
    _require(set(mapped) == set(ALLOCATORS), "checkpoint allocator pair is incomplete/duplicated")
    return mapped


def _validate_conservation(
    row: Mapping[str, Any], label: str, config: Mapping[str, Any]
) -> None:
    conservation = row.get("conservation")
    _require(isinstance(conservation, dict), f"{label}: conservation payload missing")
    _require(conservation.get("passed") is True, f"{label}: conservation gate failed")
    max_error = _finite(conservation.get("maximum_abs_error_bytes"), f"{label}: maximum error")
    max_flow_error = _finite(conservation.get("maximum_per_flow_error_bytes"), f"{label}: per-flow error")
    remaining = _finite(conservation.get("remaining_foreground_bytes"), f"{label}: remaining")
    target = _finite(
        config.get("bytes_per_neighbor"),
        f"{label}: proportional byte target",
        positive=True,
    )
    expected_tolerance = max(
        COMPACT_N100_CONSERVATION_TOLERANCE_B,
        PROPORTIONAL_CONSERVATION_ULPS * math.ulp(target),
    )
    recorded_tolerance = _finite(
        conservation.get("roundoff_tolerance_B"),
        f"{label}: proportional roundoff tolerance",
        positive=True,
    )
    _require(
        _f64_hex(recorded_tolerance) == _f64_hex(expected_tolerance)
        and conservation.get("roundoff_tolerance_B_hex")
        == _f64_hex(expected_tolerance)
        and conservation.get("roundoff_tolerance_ulps")
        == PROPORTIONAL_CONSERVATION_ULPS,
        f"{label}: proportional roundoff-tolerance fields mismatch",
    )
    _require(
        0.0 <= max_error <= expected_tolerance,
        f"{label}: conservation error exceeds extension roundoff tolerance/is negative",
    )
    _require(
        0.0 <= max_flow_error <= expected_tolerance,
        f"{label}: per-flow error exceeds extension roundoff tolerance/is negative",
    )
    _require(remaining == 0.0, f"{label}: foreground bytes remain exactly")
    _require(int(conservation.get("foreground_remaining_nonzero_count", -1)) == 0, f"{label}: nonzero foreground flows remain")
    expected_checks = int(config["ring_size"])
    expected_flows = expected_checks * int(config["k"])
    _require(
        int(conservation.get("checks", -1)) == expected_checks
        and int(conservation.get("foreground_flow_count", -1)) == expected_flows
        and int(conservation.get("individual_remaining_values_checked", -1))
        == expected_flows,
        f"{label}: logical-edge/flow conservation coverage mismatch",
    )
    _require(
        float(conservation.get("foreground_remaining_min_bytes", math.nan)) == 0.0
        and float(conservation.get("foreground_remaining_max_bytes", math.nan)) == 0.0
        and remaining == 0.0,
        f"{label}: remaining-byte extrema are not exactly zero",
    )
    _require(
        int(conservation.get("non_bit_exact_flow_count", -1)) == 0,
        f"{label}: a foreground flow failed bit-exact conservation",
    )
    if "maximum_abs_error_bytes_hex" in conservation:
        _require(conservation["maximum_abs_error_bytes_hex"] == _f64_hex(max_error), f"{label}: maximum error float seal mismatch")
    if "maximum_per_flow_error_bytes_hex" in conservation:
        _require(conservation["maximum_per_flow_error_bytes_hex"] == _f64_hex(max_flow_error), f"{label}: per-flow error float seal mismatch")


def _validate_checkpoint(checkpoint: Mapping[str, Any], expected: Mapping[str, Any], plan_sha256: str) -> Dict[str, Any]:
    pair_id = str(expected["pair_id"])
    _require(checkpoint.get("schema") == "rate-allocator-pair-checkpoint-v1", f"{pair_id}: checkpoint schema mismatch")
    _require(checkpoint.get("pair_id") == pair_id, f"{pair_id}: checkpoint identity mismatch")
    _require(checkpoint.get("plan_sha256") == plan_sha256, f"{pair_id}: checkpoint plan seal mismatch")
    _require(checkpoint.get("pair_spec") == expected, f"{pair_id}: checkpoint pair spec mismatch")
    pair_gate = checkpoint.get("pair_gate")
    _require(
        isinstance(pair_gate, dict)
        and pair_gate.get("passed") is True
        and pair_gate.get("initial_digests_equal") is True
        and pair_gate.get("mutable_instances_distinct") is True,
        f"{pair_id}: paired execution gate failed",
    )
    parent_timing = checkpoint.get("parent_timing")
    _require(isinstance(parent_timing, dict) and int(parent_timing.get("segment_index", 0)) >= 1, f"{pair_id}: parent timing provenance missing")
    _finite(
        parent_timing.get("pool_elapsed_at_checkpoint_s"),
        f"{pair_id}: parent elapsed",
        positive=True,
    )

    rows = _checkpoint_row_map(checkpoint)
    for allocator, row in rows.items():
        label = f"{pair_id}:{allocator}"
        _require(row.get("pair_id") == pair_id, f"{label}: row pair identity mismatch")
        _require(row.get("arm_id") == expected["config"]["arm_id"], f"{label}: arm mismatch")
        _require(int(row.get("sample_id", -1)) == int(expected["sample_id"]), f"{label}: seed mismatch")
        _require(int(row.get("sample_id", -1)) >= 100, f"{label}: forbidden n=100 seed was simulated")
        _require(row.get("config_sha256") == expected["config_sha256"], f"{label}: config seal mismatch")
        _require(int(row.get("execution_position", -1)) == expected["execution_order"].index(allocator), f"{label}: execution order mismatch")
        completion = _finite(row.get("completion_time_s"), f"{label}: completion", positive=True)
        _require(row.get("completion_time_hex") == _f64_hex(completion), f"{label}: completion float seal mismatch")
        ticks = int(row.get("simulated_ticks", 0))
        _require(ticks > 0, f"{label}: simulated tick count is invalid")
        dt_s = float(expected["config"]["dt_s"])
        _require(math.isclose(completion, ticks * dt_s, rel_tol=2e-13, abs_tol=2e-15), f"{label}: completion/tick consistency mismatch")
        _validate_conservation(row, label, expected["config"])
        wall_time = _finite(row.get("wall_time_s"), f"{label}: worker wall", positive=True)
        simulation_wall = _finite(
            row.get("simulation_wall_time_s"),
            f"{label}: simulation wall",
            positive=True,
        )
        cpu_time = _finite(row.get("cpu_time_s"), f"{label}: worker CPU")
        simulation_cpu = _finite(
            row.get("simulation_cpu_time_s"), f"{label}: simulation CPU"
        )
        _require(
            cpu_time >= 0.0
            and simulation_cpu >= 0.0
            and simulation_wall <= wall_time + 1e-9,
            f"{label}: worker/simulation timing is inconsistent",
        )
        for value, hex_field in (
            (wall_time, "wall_time_hex"),
            (cpu_time, "cpu_time_hex"),
            (simulation_wall, "simulation_wall_time_hex"),
            (simulation_cpu, "simulation_cpu_time_hex"),
        ):
            if hex_field in row:
                _require(
                    row[hex_field] == _f64_hex(value),
                    f"{label}: {hex_field} float seal mismatch",
                )
        _require(row.get("family") == "static_split" and row.get("runner") == "proportional" and row.get("policy") == "proportional", f"{label}: policy identity mismatch")
        _require(row.get("adaptive_gate") is None, f"{label}: unexpected adaptive controller payload")
        _require(row.get("background_instance_id") is None and row.get("congestion_instance_id") is None, f"{label}: unexpected non-static workload state")
        for digest_field in ("process_initial_sha256", "topology_sha256", "ring_sha256", "route_sha256"):
            _require(_valid_digest(row.get(digest_field)), f"{label}: invalid {digest_field}")
    for digest_field in ("process_initial_sha256", "topology_sha256", "ring_sha256", "route_sha256"):
        _require(rows[ALLOCATORS[0]][digest_field] == rows[ALLOCATORS[1]][digest_field], f"{pair_id}: paired {digest_field} mismatch")
    for instance_field in ("simulator_instance_id", "topology_instance_id"):
        left = rows[ALLOCATORS[0]].get(instance_field)
        right = rows[ALLOCATORS[1]].get(instance_field)
        _require(
            left is not None and right is not None and left != right,
            f"{pair_id}: paired {instance_field} values are missing/reused",
        )

    local = rows[ALLOCATORS[0]]
    maxmin = rows[ALLOCATORS[1]]
    local_time = float(local["completion_time_s"])
    maxmin_time = float(maxmin["completion_time_s"])
    return {
        "pair_id": pair_id,
        "arm_id": expected["config"]["arm_id"],
        "fabric": expected["config"]["fabric"],
        "P": int(expected["config"]["ring_size"]),
        "k": int(expected["config"]["k"]),
        "sample_id": int(expected["sample_id"]),
        "local_time": local_time,
        "maxmin_time": maxmin_time,
        "ratio": maxmin_time / local_time,
        "delta_s": maxmin_time - local_time,
        "delta_ticks": int(maxmin["simulated_ticks"]) - int(local["simulated_ticks"]),
        "rows": rows,
        "segment_index": int(parent_timing["segment_index"]),
        "pool_elapsed_at_checkpoint_s": float(
            parent_timing["pool_elapsed_at_checkpoint_s"]
        ),
    }


def _load_checkpoints(output: Path, expected_pairs: Sequence[Mapping[str, Any]], plan_sha256: str) -> Tuple[Dict[str, Mapping[str, Any]], List[Dict[str, Any]]]:
    checkpoint_dir = output / "checkpoints"
    _require(checkpoint_dir.is_dir(), "checkpoint directory is missing")
    expected_files = {f"{pair['pair_id']}.json" for pair in expected_pairs}
    actual_entries = list(checkpoint_dir.iterdir())
    _require(all(path.is_file() for path in actual_entries), "checkpoint directory contains a non-file")
    _require({path.name for path in actual_entries} == expected_files, "checkpoint file inventory is not exact")
    checkpoints: Dict[str, Mapping[str, Any]] = {}
    records: List[Dict[str, Any]] = []
    for pair in expected_pairs:
        pair_id = str(pair["pair_id"])
        checkpoint = _read_json(checkpoint_dir / f"{pair_id}.json")
        _require(isinstance(checkpoint, dict), f"{pair_id}: checkpoint is not an object")
        checkpoints[pair_id] = checkpoint
        records.append(_validate_checkpoint(checkpoint, pair, plan_sha256))
    _require(len(records) == EXTENSION_PAIR_COUNT, "validated checkpoint count mismatch")
    return checkpoints, records


def _verify_preflight(output: Path, checkpoints: Mapping[str, Mapping[str, Any]], manifest: Mapping[str, Any]) -> Dict[str, Any]:
    seal_path = output / "preflight_complete.json"
    seal = _read_json(seal_path)
    _require(isinstance(seal, dict) and seal.get("schema") == PREFLIGHT_SCHEMA, "preflight schema mismatch")
    _require(
        set(seal)
        == {
            "schema",
            "passed",
            "integrity_only_no_effect_stopping",
            "ordered_pair_ids",
            "pair_count",
            "simulation_count",
            "allocator_first_pair_counts",
            "seed_pair_counts",
            "arm_count",
            "conservation_pass_count",
            "plan_sha256",
            "run_manifest_signature",
            "checkpoint_signatures",
            "timing_segment_signatures",
            "source_gate",
        },
        "preflight key set differs from the frozen contract",
    )
    expected_ids = _expected_preflight_ids()
    _require(len(expected_ids) == PREFLIGHT_PAIR_COUNT, "independent preflight cardinality drift")
    recorded_ids = seal.get("ordered_pair_ids", seal.get("pair_ids"))
    _require(recorded_ids == expected_ids, "preflight pair order/domain mismatch")
    _require(int(seal.get("pair_count", -1)) == PREFLIGHT_PAIR_COUNT, "preflight pair count mismatch")
    _require(int(seal.get("simulation_count", -1)) == 2 * PREFLIGHT_PAIR_COUNT, "preflight simulation count mismatch")
    _require(seal.get("passed") is True, "preflight gate did not pass")
    _require(seal.get("plan_sha256") == manifest.get("plan_sha256"), "preflight plan seal mismatch")
    signatures = seal.get("checkpoint_signatures")
    _require(isinstance(signatures, dict) and len(signatures) == PREFLIGHT_PAIR_COUNT, "preflight checkpoint signatures are incomplete")
    for pair_id in expected_ids:
        relative = f"checkpoints/{pair_id}.json"
        signature = signatures.get(relative)
        path = output / relative
        _require(isinstance(signature, dict), f"missing preflight checkpoint signature: {pair_id}")
        _require(int(signature.get("bytes", -1)) == path.stat().st_size and signature.get("sha256") == _sha256_file(path), f"preflight checkpoint signature drift: {pair_id}")
        _require(checkpoints[pair_id]["pair_spec"]["sample_id"] in PREFLIGHT_SEEDS, f"preflight includes wrong seed: {pair_id}")
    timing_signatures = seal.get("timing_segment_signatures")
    _require(
        isinstance(timing_signatures, dict) and timing_signatures,
        "preflight timing signatures are missing",
    )
    timing_covered: set[str] = set()
    for relative, signature in timing_signatures.items():
        path = output / relative
        _require(
            Path(relative).parent.as_posix() == "timing_segments"
            and path.is_file()
            and isinstance(signature, dict)
            and int(signature.get("bytes", -1)) == path.stat().st_size
            and signature.get("sha256") == _sha256_file(path),
            f"preflight timing signature drift: {relative}",
        )
        segment = _read_json(path)
        pair_ids = segment.get("pair_ids")
        _require(
            isinstance(pair_ids, list)
            and set(pair_ids) <= set(expected_ids),
            f"preflight timing signature contains a main/unknown pair: {relative}",
        )
        timing_covered.update(pair_ids)
        _require(
            path.stat().st_mtime_ns <= seal_path.stat().st_mtime_ns,
            f"preflight seal predates signed timing segment: {relative}",
        )
    _require(
        timing_covered == set(expected_ids),
        "preflight timing signatures do not cover the fixed 64 pairs",
    )
    manifest_signature = seal.get("run_manifest_signature")
    manifest_path = output / "run_manifest.json"
    _require(isinstance(manifest_signature, dict) and int(manifest_signature.get("bytes", -1)) == manifest_path.stat().st_size and manifest_signature.get("sha256") == _sha256_file(manifest_path), "preflight run-manifest signature mismatch")
    _require(
        seal.get("source_gate")
        == {
            "passed": True,
            "driver_sha256": manifest["driver_sha256"],
            "source_sha256": manifest["immutable_before"]["sources"],
            "n100_reference_sha256": manifest["immutable_before"][
                "n100_reference_sha256"
            ],
        },
        "preflight source/reference gate mismatch",
    )
    _require(
        seal.get("allocator_first_pair_counts")
        == {ALLOCATORS[0]: 32, ALLOCATORS[1]: 32}
        and seal.get("seed_pair_counts") == {"100": 32, "101": 32}
        and int(seal.get("arm_count", -1)) == ARM_COUNT
        and int(seal.get("conservation_pass_count", -1))
        == 2 * PREFLIGHT_PAIR_COUNT
        and seal.get("integrity_only_no_effect_stopping") is True,
        "preflight balance/conservation/scope gate mismatch",
    )
    seal_mtime = seal_path.stat().st_mtime_ns
    _require(all((output / f"checkpoints/{pair_id}.json").stat().st_mtime_ns <= seal_mtime for pair_id in expected_ids), "preflight seal predates a preflight checkpoint")
    _require(all((output / f"checkpoints/{pair_id}.json").stat().st_mtime_ns >= seal_mtime for pair_id in set(checkpoints) - set(expected_ids)), "a main-phase checkpoint predates the preflight seal")
    return {"pair_count": PREFLIGHT_PAIR_COUNT, "seed_ids": list(PREFLIGHT_SEEDS), "passed": True}


def _timing_segment_number(path: Path) -> int:
    match = re.fullmatch(r"segment_([0-9]+)\.json", path.name)
    _require(match is not None, f"unauthorized timing filename: {path.name}")
    return int(match.group(1))


def _verify_timing(output: Path, records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    timing_dir = output / "timing_segments"
    _require(timing_dir.is_dir(), "timing-segment directory is missing")
    paths = sorted(timing_dir.glob("segment_*.json"), key=_timing_segment_number)
    _require(paths and len(paths) == len(list(timing_dir.iterdir())), "timing directory contains an unauthorized artifact")
    expected_ids = {str(record["pair_id"]) for record in records}
    record_by_id = {str(record["pair_id"]): record for record in records}
    preflight_ids = set(_expected_preflight_ids())
    covered: set[str] = set()
    preflight_covered: set[str] = set()
    segment_by_pair: Dict[str, int] = {}
    elapsed_total = 0.0
    worker_simulation_total = 0.0
    worker_end_to_end_total = 0.0
    recovered_segment_count = 0
    for expected_index, path in enumerate(paths, start=1):
        _require(
            path.name == f"segment_{expected_index:03d}.json",
            "timing segment filenames are non-sequential",
        )
        segment = _read_json(path)
        _require(
            isinstance(segment, dict)
            and set(segment)
            == {
                "schema",
                "segment_index",
                "phase",
                "pair_ids",
                "pair_count",
                "elapsed_pool_wall_s",
                "worker_simulation_wall_sum_s",
                "worker_end_to_end_wall_sum_s",
                "recovered_after_interruption",
            },
            f"timing segment key set differs from the frozen contract: {path.name}",
        )
        _require(segment.get("schema") == TIMING_SCHEMA and int(segment.get("segment_index", -1)) == expected_index, f"timing segment schema/index mismatch: {path.name}")
        phase = segment.get("phase")
        recovered = segment.get("recovered_after_interruption")
        _require(
            phase in (
                "preflight_64",
                "remaining_28736",
                "recovered_after_interruption",
            )
            and isinstance(recovered, bool)
            and ((phase == "recovered_after_interruption") == recovered),
            f"invalid timing phase/recovery provenance: {path.name}",
        )
        pair_ids = segment.get("pair_ids")
        _require(isinstance(pair_ids, list) and pair_ids, f"empty timing segment: {path.name}")
        _require(
            int(segment.get("pair_count", -1)) == len(pair_ids),
            f"timing segment pair count mismatch: {path.name}",
        )
        _require(len(pair_ids) == len(set(pair_ids)), f"duplicate pair inside timing segment: {path.name}")
        _require(not (set(pair_ids) & covered), f"pair appears in multiple timing segments: {path.name}")
        _require(set(pair_ids) <= expected_ids, f"unknown pair in timing segment: {path.name}")
        pair_set = set(pair_ids)
        if phase == "preflight_64":
            _require(
                pair_set <= preflight_ids,
                f"preflight timing segment contains a main-phase pair: {path.name}",
            )
            preflight_covered.update(pair_ids)
        elif phase == "remaining_28736":
            _require(
                pair_set.isdisjoint(preflight_ids),
                f"main timing segment contains a preflight pair: {path.name}",
            )
        else:
            _require(
                pair_set <= preflight_ids or pair_set.isdisjoint(preflight_ids),
                f"recovered timing segment mixes preflight and main pairs: {path.name}",
            )
            if pair_set <= preflight_ids:
                preflight_covered.update(pair_ids)
        covered.update(pair_ids)
        for pair_id in pair_ids:
            segment_by_pair[pair_id] = expected_index
        elapsed = _finite(
            segment.get("elapsed_pool_wall_s"),
            f"{path.name}:elapsed",
            positive=True,
        )
        elapsed_total += elapsed
        expected_total = sum(
            float(row["wall_time_s"])
            for pair_id in pair_ids
            for row in record_by_id[pair_id]["rows"].values()
        )
        expected_simulation = sum(
            float(row["simulation_wall_time_s"])
            for pair_id in pair_ids
            for row in record_by_id[pair_id]["rows"].values()
        )
        recorded_total = _finite(
            segment.get("worker_end_to_end_wall_sum_s"),
            f"{path.name}:worker wall",
            positive=True,
        )
        worker_end_to_end_total += recorded_total
        recorded_simulation = _finite(
            segment.get("worker_simulation_wall_sum_s"),
            f"{path.name}:simulation wall",
            positive=True,
        )
        worker_simulation_total += recorded_simulation
        recovered_segment_count += int(recovered)
        _require(
            _f64_hex(recorded_total) == _f64_hex(expected_total)
            and _f64_hex(recorded_simulation) == _f64_hex(expected_simulation),
            f"timing worker sums do not match checkpoints: {path.name}",
        )
        for pair_id in pair_ids:
            parent_elapsed = float(record_by_id[pair_id]["pool_elapsed_at_checkpoint_s"])
            _require(
                parent_elapsed <= elapsed,
                f"checkpoint parent time exceeds segment elapsed time: {pair_id}",
            )
    _require(covered == expected_ids, "timing segments do not cover the checkpoint inventory exactly")
    _require(preflight_covered == preflight_ids, "timing preflight coverage mismatch")
    for record in records:
        _require(record["segment_index"] == segment_by_pair[record["pair_id"]], f"checkpoint/timing segment mismatch: {record['pair_id']}")
    return {
        "segment_count": len(paths),
        "pair_count": len(covered),
        "elapsed_pool_wall_sum_s": elapsed_total,
        "worker_simulation_wall_sum_s": worker_simulation_total,
        "worker_end_to_end_wall_sum_s": worker_end_to_end_total,
        "recovered_segment_count": recovered_segment_count,
    }


def _verify_completion_bundle(output: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    completion_path = output / "completion_manifest.json"
    complete_path = output / "COMPLETE.json"
    completion = _read_json(completion_path)
    complete = _read_json(complete_path)
    _require(
        isinstance(completion, dict)
        and set(completion)
        == {
            "schema",
            "status",
            "plan_sha256",
            "pair_count",
            "simulation_count",
            "combined_pair_count",
            "artifact_count",
            "artifacts",
            "analysis_sha256",
            "gate",
            "runtime",
            "immutable_after",
            "completion_manifest_excludes_itself_and_complete",
            "completion_manifest_self_signed",
            "complete_file_self_signed",
            "run_lock_hashed_via_held_handle",
        },
        "completion-manifest key set differs from the frozen contract",
    )
    _require(
        isinstance(complete, dict)
        and set(complete)
        == {
            "schema",
            "status",
            "plan_sha256",
            "completion_manifest_sha256",
            "completion_manifest_bytes",
            "run_manifest_sha256",
            "run_manifest_bytes",
            "written_last",
        },
        "COMPLETE key set differs from the frozen contract",
    )
    _require(completion.get("schema") == COMPLETION_SCHEMA, "completion-manifest schema mismatch")
    _require(complete.get("schema") == COMPLETE_SCHEMA, "COMPLETE schema mismatch")
    _require(complete.get("completion_manifest_sha256") == _sha256_file(completion_path), "COMPLETE does not bind the completion manifest")
    _require(int(complete.get("completion_manifest_bytes", -1)) == completion_path.stat().st_size, "COMPLETE completion byte count mismatch")
    _require(complete.get("written_last") is True, "COMPLETE does not assert last-write ordering")
    _require(complete.get("plan_sha256") == completion.get("plan_sha256"), "completion plan seal mismatch")
    _require(complete.get("status") == completion.get("status"), "completion status mismatch")
    _require(int(completion.get("pair_count", -1)) == EXTENSION_PAIR_COUNT and int(completion.get("simulation_count", -1)) == EXTENSION_ROW_COUNT, "completion cardinality mismatch")
    artifacts = completion.get("artifacts")
    _require(isinstance(artifacts, dict) and artifacts, "completion artifact seal is missing")
    _verify_complete_run_manifest_binding(output, complete, artifacts)
    _require("completion_manifest.json" not in artifacts and "COMPLETE.json" not in artifacts, "completion files self-hash")
    for relative, signature in artifacts.items():
        path_token = Path(relative)
        _require(isinstance(relative, str) and relative and not path_token.is_absolute() and ".." not in path_token.parts, f"unsafe completion artifact path: {relative}")
        _require(isinstance(signature, dict), f"malformed completion signature: {relative}")
        _require(
            set(signature)
            == (
                {"bytes", "sha256", "hashed_via_held_handle"}
                if relative == ".run.lock"
                else {"bytes", "sha256"}
            ),
            f"completion signature key set mismatch: {relative}",
        )
        path = output / relative
        _require(path.is_file(), f"signed completion artifact is missing: {relative}")
        _require(int(signature.get("bytes", -1)) == path.stat().st_size and signature.get("sha256") == _sha256_file(path), f"signed artifact drift: {relative}")
    actual_files = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
    expected_files = set(artifacts) | {"completion_manifest.json", "COMPLETE.json"}
    _require(actual_files == expected_files, "campaign file inventory is not exact")
    _require({name for name in actual_files if "/" not in name} == EXPECTED_FINAL_ROOT_FILES, "campaign root-file inventory is not exact")
    checkpoint_files = {name for name in artifacts if name.startswith("checkpoints/")}
    _require(len(checkpoint_files) == EXTENSION_PAIR_COUNT, "signed checkpoint count mismatch")
    timing_files = {name for name in artifacts if name.startswith("timing_segments/")}
    _require(timing_files and all(Path(name).name.startswith("segment_") and name.endswith(".json") for name in timing_files), "signed timing inventory mismatch")
    actual_dirs = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_dir()}
    _require(actual_dirs == {"checkpoints", "timing_segments"}, "campaign directory inventory is not exact")
    latest_signed = max((output / relative).stat().st_mtime_ns for relative in artifacts)
    _require(completion_path.stat().st_mtime_ns >= latest_signed and complete_path.stat().st_mtime_ns >= completion_path.stat().st_mtime_ns, "completion files were not written last")
    _require(int(completion.get("artifact_count", -1)) == len(artifacts), "completion artifact count mismatch")
    _require(
        completion.get("completion_manifest_excludes_itself_and_complete") is True
        and completion.get("completion_manifest_self_signed") is False
        and completion.get("complete_file_self_signed") is False
        and completion.get("run_lock_hashed_via_held_handle") is True
        and artifacts.get(".run.lock", {}).get("hashed_via_held_handle") is True,
        "completion self-exclusion/held-lock signing flags mismatch",
    )
    _require(
        completion.get("status")
        == "COMPLETE_PENDING_INDEPENDENT_AUDIT_AND_RESEARCH_DECISION"
        and int(completion.get("combined_pair_count", -1))
        == COMBINED_PAIR_COUNT,
        "completion status/combined cardinality mismatch",
    )
    _require(
        completion.get("gate") == _read_json(output / "gate.json")
        and completion.get("runtime") == _read_json(output / "runtime.json"),
        "completion embedded gate/runtime differs from signed exports",
    )
    _require(
        completion.get("analysis_sha256")
        == artifacts.get("analysis.json", {}).get("sha256"),
        "completion analysis signature mismatch",
    )
    return completion, complete


def _verify_complete_run_manifest_binding(
    output: Path,
    complete: Mapping[str, Any],
    artifacts: Mapping[str, Any],
) -> None:
    run_manifest_path = output / "run_manifest.json"
    _require(run_manifest_path.is_file(), "run manifest is missing at completion")
    run_hash = _sha256_file(run_manifest_path)
    run_bytes = run_manifest_path.stat().st_size
    _require(
        complete.get("run_manifest_sha256") == run_hash
        and int(complete.get("run_manifest_bytes", -1)) == run_bytes,
        "COMPLETE does not directly bind the run manifest",
    )
    signature = artifacts.get("run_manifest.json")
    _require(
        isinstance(signature, dict)
        and signature.get("sha256") == run_hash
        and int(signature.get("bytes", -1)) == run_bytes,
        "completion manifest run-manifest signature mismatch",
    )


def _verify_immutable_after(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> None:
    _require(
        isinstance(after, dict) and dict(after) == dict(before),
        "completion immutable-after snapshot differs from the authorized before snapshot",
    )


def _verify_csv_exports(output: Path, records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    pair_header, pair_rows = _read_csv(output / "pairs.csv")
    result_header, result_rows = _read_csv(output / "results_long.csv")
    required_pair = {"pair_id", "arm_id", "sample_id", "fabric", "ring_size", "k", "link_local_time_s", "network_maxmin_time_s", "network_over_link_local", "network_minus_link_local_ticks"}
    required_result = {"pair_id", "arm_id", "sample_id", "allocator", "execution_position", "completion_time_s", "completion_time_hex", "simulated_ticks", "config_sha256", "topology_sha256", "ring_sha256", "route_sha256", "conservation_max_error_B", "conservation_remaining_B", "remaining_nonzero_count"}
    _require(required_pair <= set(pair_header), "extension pairs.csv schema is incomplete")
    _require(required_result <= set(result_header), "extension results_long.csv schema is incomplete")
    _require(len(pair_rows) == EXTENSION_PAIR_COUNT, "extension pairs.csv row count mismatch")
    _require(len(result_rows) == EXTENSION_ROW_COUNT, "extension results_long.csv row count mismatch")
    record_map = {str(record["pair_id"]): record for record in records}
    _require([row["pair_id"] for row in pair_rows] == [record["pair_id"] for record in records], "extension pairs.csv order/ID mismatch")
    for row in pair_rows:
        record = record_map[row["pair_id"]]
        _require(int(row["sample_id"]) == record["sample_id"] >= 100, f"extension pair seed mismatch: {row['pair_id']}")
        _require(row["arm_id"] == record["arm_id"] and row["fabric"] == record["fabric"] and int(row["ring_size"]) == record["P"] and int(row["k"]) == record["k"], f"extension pair metadata mismatch: {row['pair_id']}")
        _require(float(row["link_local_time_s"]) == record["local_time"] and float(row["network_maxmin_time_s"]) == record["maxmin_time"], f"extension pair time mismatch: {row['pair_id']}")
        _require(math.isclose(float(row["network_over_link_local"]), record["ratio"], rel_tol=2e-15, abs_tol=0.0), f"extension pair ratio mismatch: {row['pair_id']}")
        _require(int(row["network_minus_link_local_ticks"]) == record["delta_ticks"], f"extension pair tick mismatch: {row['pair_id']}")
    seen: set[Tuple[str, str]] = set()
    for row in result_rows:
        key = (row["pair_id"], row["allocator"])
        _require(row["pair_id"] in record_map and row["allocator"] in ALLOCATORS and key not in seen, f"extension allocator-row bijection failure: {key}")
        seen.add(key)
        source = record_map[row["pair_id"]]["rows"][row["allocator"]]
        _require(int(row["sample_id"]) == int(source["sample_id"]) >= 100, f"extension result seed mismatch: {key}")
        _require(int(row["execution_position"]) == int(source["execution_position"]), f"extension result order mismatch: {key}")
        _require(float(row["completion_time_s"]) == float(source["completion_time_s"]) and row["completion_time_hex"] == source["completion_time_hex"], f"extension result completion mismatch: {key}")
        _require(int(row["simulated_ticks"]) == int(source["simulated_ticks"]), f"extension result ticks mismatch: {key}")
        for digest_field in ("config_sha256", "topology_sha256", "ring_sha256", "route_sha256"):
            _require(row[digest_field] == source[digest_field], f"extension result {digest_field} mismatch: {key}")
        conservation = source["conservation"]
        _require(float(row["conservation_max_error_B"]) == float(conservation["maximum_abs_error_bytes"]), f"extension CSV conservation mismatch: {key}")
        _require(float(row["conservation_remaining_B"]) == float(conservation["remaining_foreground_bytes"]), f"extension CSV remaining mismatch: {key}")
        _require(int(row["remaining_nonzero_count"]) == int(conservation["foreground_remaining_nonzero_count"]), f"extension CSV nonzero-count mismatch: {key}")
    _require(len(seen) == EXTENSION_ROW_COUNT, "extension allocator-row count is not bijective")
    return {"pair_rows": len(pair_rows), "allocator_rows": len(result_rows)}


def _descriptive(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    _require(bool(records), "cannot summarize an empty record set")
    ratios = np.asarray([float(record["ratio"]) for record in records], dtype=np.float64)
    delta_s = np.asarray([float(record.get("delta_s", record["maxmin_time"] - record["local_time"])) for record in records], dtype=np.float64)
    delta_ticks = np.asarray([int(record["delta_ticks"]) for record in records], dtype=np.int64)
    classes = Counter(_tick_class(int(value)) for value in delta_ticks)
    return {
        "pair_count": len(records),
        "geometric_mean_ratio": math.exp(float(np.log(ratios).mean())),
        "median_ratio": float(np.median(ratios)),
        "minimum_ratio": float(ratios.min()),
        "maximum_ratio": float(ratios.max()),
        "mean_signed_delta_ms": float(delta_s.mean() * 1e3),
        "median_signed_delta_ms": float(np.median(delta_s) * 1e3),
        "mean_absolute_delta_ms": float(np.abs(delta_s).mean() * 1e3),
        "maximum_absolute_delta_ms": float(np.abs(delta_s).max() * 1e3),
        "minimum_delta_ticks": int(delta_ticks.min()),
        "maximum_delta_ticks": int(delta_ticks.max()),
        "tick_counts": {name: int(classes.get(name, 0)) for name in ("maxmin_faster_by_2plus", "exact_tie", "one_tick_tie", "maxmin_slower_by_2plus")},
    }


def _bootstrap_summary(seed_log_values: Sequence[float], indexes: np.ndarray) -> Dict[str, Any]:
    values = np.asarray(seed_log_values, dtype=np.float64)
    _require(values.shape == (indexes.shape[1],), "bootstrap cluster/value shape mismatch")
    ratios = np.empty(indexes.shape[0], dtype=np.float64)
    for start in range(0, indexes.shape[0], 250):
        stop = min(start + 250, indexes.shape[0])
        ratios[start:stop] = np.exp(values[indexes[start:stop]].mean(axis=1))
    return {
        "point_estimate": math.exp(float(values.mean())),
        "ci95_low": float(np.quantile(ratios, 0.025, method="linear")),
        "ci95_high": float(np.quantile(ratios, 0.975, method="linear")),
    }


def _domain_analysis(
    records: Sequence[Mapping[str, Any]],
    seeds: Sequence[int],
    expected_index_sha256: str,
) -> Dict[str, Any]:
    """Independently reproduce one preregistered seed-cluster domain."""
    by_seed: Dict[int, List[Mapping[str, Any]]] = defaultdict(list)
    by_arm: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        by_seed[int(record["sample_id"])].append(record)
        by_arm[str(record["arm_id"])].append(record)
    ordered_seeds = list(seeds)
    _require(
        sorted(by_seed) == ordered_seeds
        and {len(group) for group in by_seed.values()} == {ARM_COUNT}
        and len(by_arm) == ARM_COUNT
        and {len(group) for group in by_arm.values()} == {len(ordered_seeds)},
        "analysis seed/arm bijection mismatch",
    )
    indexes, observed_hash = _bootstrap_indexes(len(ordered_seeds))
    _require(
        observed_hash == expected_index_sha256,
        "analysis bootstrap-index digest mismatch",
    )
    seed_logs = [
        sum(math.log(float(record["ratio"])) for record in by_seed[seed])
        / ARM_COUNT
        for seed in ordered_seeds
    ]
    global_bootstrap = _bootstrap_summary(seed_logs, indexes)
    total_log = sum(math.log(float(record["ratio"])) for record in records)
    leave_one_out: List[float] = []
    for seed in ordered_seeds:
        removed = sum(
            math.log(float(record["ratio"])) for record in by_seed[seed]
        )
        leave_one_out.append(
            math.exp((total_log - removed) / (len(records) - ARM_COUNT))
        )
    point = float(global_bootstrap["point_estimate"])
    single_seed_dependence = (
        any(value >= 1.0 for value in leave_one_out)
        if point < 1.0
        else any(value <= 1.0 for value in leave_one_out)
        if point > 1.0
        else False
    )
    per_arm: Dict[str, Any] = {}
    for arm_id in sorted(by_arm):
        arm_records = sorted(
            by_arm[arm_id], key=lambda record: int(record["sample_id"])
        )
        per_arm[arm_id] = {
            **_descriptive(arm_records),
            **_bootstrap_summary(
                [math.log(float(record["ratio"])) for record in arm_records],
                indexes,
            ),
            "descriptive_only": True,
            "multiplicity_adjusted": False,
        }
    del indexes
    return {
        "estimand": "T_network_maxmin/T_link_local",
        "global": {
            **_descriptive(records),
            **global_bootstrap,
            "cluster_count": len(ordered_seeds),
            "pairs_per_cluster": ARM_COUNT,
            "bootstrap_replicates": BOOTSTRAP_REPLICATES,
            "bootstrap_rng": f"PCG64({BOOTSTRAP_SEED})",
            "bootstrap_index_sha256": expected_index_sha256,
        },
        "per_arm": per_arm,
        "leave_one_seed_out": {
            "minimum": min(leave_one_out),
            "maximum": max(leave_one_out),
            "single_seed_dependence": single_seed_dependence,
        },
    }


def _ci_direction(summary: Mapping[str, Any]) -> str:
    if float(summary["ci95_high"]) < 1.0:
        return "network_maxmin_faster"
    if float(summary["ci95_low"]) > 1.0:
        return "link_local_equal_share_faster"
    return "global_interval_includes_one"


def _point_direction(summary: Mapping[str, Any]) -> int:
    point = float(summary["point_estimate"])
    if point < 1.0:
        return -1
    if point > 1.0:
        return 1
    return 0


def _analysis_review_reasons(
    primary: Mapping[str, Any],
    sensitivity: Mapping[str, Any],
    secondary: Mapping[str, Any],
    *,
    primary_single_seed_dependence: bool,
) -> List[str]:
    reasons: List[str] = []
    if _ci_direction(primary) == "global_interval_includes_one":
        reasons.append("extension_primary_ci_contains_one")
    if primary_single_seed_dependence:
        reasons.append("extension_primary_single_seed_dependence")
    if int(primary["tick_counts"]["maxmin_slower_by_2plus"]) > 0:
        reasons.append("extension_contains_maxmin_slower_by_2plus_pair")
    if _point_direction(primary) != _point_direction(secondary):
        reasons.append("combined_secondary_direction_disagrees")
    if _ci_direction(primary) != _ci_direction(secondary):
        reasons.append("combined_secondary_ci_classification_differs")
    if _point_direction(primary) != _point_direction(sensitivity):
        reasons.append("sentinel_excluded_sensitivity_direction_disagrees")
    if _ci_direction(primary) != _ci_direction(sensitivity):
        reasons.append("sentinel_excluded_sensitivity_ci_classification_differs")
    return reasons


def _export_bootstrap_summary(
    records: Sequence[Mapping[str, Any]],
    seeds: Sequence[int],
    expected_hash: str,
) -> Dict[str, Any]:
    by_seed: Dict[int, List[float]] = defaultdict(list)
    seed_set = set(seeds)
    for record in records:
        seed = int(record["sample_id"])
        if seed in seed_set:
            by_seed[seed].append(math.log(float(record["ratio"])))
    _require(set(by_seed) == seed_set, "bootstrap seed-cluster inventory mismatch")
    _require(set(map(len, by_seed.values())) == {ARM_COUNT}, "bootstrap seed clusters are not size 32")
    indexes, observed_hash = _bootstrap_indexes(len(seeds))
    _require(observed_hash == expected_hash, "bootstrap-index digest mismatch")
    seed_log_means = [statistics.fmean(by_seed[seed]) for seed in seeds]
    bootstrap = _bootstrap_summary(seed_log_means, indexes)
    del indexes
    return {
        "seed_cluster_count": len(seeds),
        "arm_count_per_cluster": ARM_COUNT,
        "pair_count": len(seeds) * ARM_COUNT,
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_index_dtype": "little_endian_uint32",
        "bootstrap_index_shape": [BOOTSTRAP_REPLICATES, len(seeds)],
        "bootstrap_index_sha256": observed_hash,
        "geometric_mean_network_over_link_local": bootstrap["point_estimate"],
        "cluster_bootstrap_ci95_low": bootstrap["ci95_low"],
        "cluster_bootstrap_ci95_high": bootstrap["ci95_high"],
        "directional_label": _ci_direction(bootstrap),
        "inference_domain": "placement_seed_clusters_conditional_on_fixed_32_arm_topology_model_matrix",
        "not_population_or_model_uncertainty": True,
    }


def _export_arm_summaries(
    records: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["arm_id"])].append(record)
    _require(len(grouped) == ARM_COUNT, "arm-summary arm inventory mismatch")
    summaries: List[Dict[str, Any]] = []
    for arm_id in sorted(grouped):
        group = grouped[arm_id]
        first = group[0]
        logs = [math.log(float(record["ratio"])) for record in group]
        deltas = [int(record["delta_ticks"]) for record in group]
        summaries.append(
            {
                "arm_id": arm_id,
                "fabric": first["fabric"],
                "ring_size": int(first["P"]),
                "k": int(first["k"]),
                "seed_count": len(group),
                "geometric_mean_network_over_link_local": math.exp(
                    sum(logs) / len(logs)
                ),
                "network_faster_count": sum(delta < 0 for delta in deltas),
                "exact_tick_tie_count": sum(delta == 0 for delta in deltas),
                "link_local_faster_count": sum(delta > 0 for delta in deltas),
                "descriptive_only": True,
            }
        )
    return summaries


def _normalized_global_for_review(
    export: Mapping[str, Any], records: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    return {
        "point_estimate": float(
            export["geometric_mean_network_over_link_local"]
        ),
        "ci95_low": float(export["cluster_bootstrap_ci95_low"]),
        "ci95_high": float(export["cluster_bootstrap_ci95_high"]),
        "tick_counts": _descriptive(records)["tick_counts"],
    }


def _leave_one_seed_out_review(
    records: Sequence[Mapping[str, Any]], seeds: Sequence[int]
) -> Dict[str, Any]:
    by_seed: Dict[int, List[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        by_seed[int(record["sample_id"])].append(record)
    _require(set(by_seed) == set(seeds), "leave-one-seed inventory mismatch")
    total_log = sum(math.log(float(record["ratio"])) for record in records)
    values = []
    for seed in seeds:
        removed = sum(math.log(float(record["ratio"])) for record in by_seed[seed])
        values.append(math.exp((total_log - removed) / (len(records) - ARM_COUNT)))
    point = math.exp(total_log / len(records))
    dependence = (
        any(value >= 1.0 for value in values)
        if point < 1.0
        else any(value <= 1.0 for value in values)
        if point > 1.0
        else False
    )
    return {
        "minimum": min(values),
        "maximum": max(values),
        "single_seed_dependence": dependence,
    }


def _scientific_analysis(
    extension_records: Sequence[Mapping[str, Any]],
    n100_records: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    _require(len(extension_records) == EXTENSION_PAIR_COUNT, "extension estimator input count mismatch")
    _require(len(n100_records) == N100_PAIR_COUNT, "n=100 join input count mismatch")
    extension_ids = [str(record["pair_id"]) for record in extension_records]
    n100_ids = [str(record["pair_id"]) for record in n100_records]
    combined_ids = _expected_pair_ids(COMBINED_SEEDS)
    _require(_json_digest(extension_ids) == EXPECTED_EXTENSION_PAIR_ID_SHA256, "extension estimator pair-ID digest mismatch")
    _require(set(extension_ids).isdisjoint(n100_ids), "extension and n=100 pair domains overlap")
    combined_map = {str(record["pair_id"]): record for record in (*n100_records, *extension_records)}
    _require(len(combined_map) == COMBINED_PAIR_COUNT, "combined pair join is not bijective")
    _require(_json_digest(combined_ids) == EXPECTED_COMBINED_PAIR_ID_SHA256, "combined independent pair-ID digest drift")
    combined_records = [combined_map[pair_id] for pair_id in combined_ids]

    sentinel_overlap = _verify_prior_sentinel_overlap()
    retained_seeds = tuple(
        seed for seed in EXTENSION_SEEDS if seed not in SENTINEL_OVERLAP_SEEDS
    )
    sensitivity_records = [
        record
        for record in extension_records
        if int(record["sample_id"]) not in SENTINEL_OVERLAP_SEEDS
    ]
    _require(
        len(retained_seeds) == 896
        and len(sensitivity_records) == 28_672
        and {int(record["sample_id"]) for record in sensitivity_records}
        == set(retained_seeds),
        "sentinel-excluded sensitivity does not remove four whole clusters",
    )
    _require(
        EXPECTED_SENTINEL_OVERLAP_PAIR_IDS <= set(extension_ids),
        "the independently derived prior-sentinel overlap is not present in the extension",
    )
    primary = _domain_analysis(
        extension_records,
        EXTENSION_SEEDS,
        EXPECTED_EXTENSION_BOOTSTRAP_SHA256,
    )
    sensitivity = _domain_analysis(
        sensitivity_records,
        retained_seeds,
        EXPECTED_SENTINEL_EXCLUDED_BOOTSTRAP_SHA256,
    )
    secondary = _domain_analysis(
        combined_records,
        COMBINED_SEEDS,
        EXPECTED_COMBINED_BOOTSTRAP_SHA256,
    )
    primary_global = primary["global"]
    sensitivity_global = sensitivity["global"]
    secondary_global = secondary["global"]

    export = {
        "schema": ANALYSIS_SCHEMA,
        "primary_domain": "extension_only_seeds_100_999",
        "secondary_domain": "combined_seeds_0_999",
        "analysis_role": "fixed_matrix_validation_descriptive_not_confirmatory_holdout",
        "n100_reuse_is_secondary_only": True,
        "extension_primary": {
            **primary,
            "interpretation": "conditional_on_fixed_32_arm_matrix_simulator_and_rate_model",
        },
        "sentinel_excluded_sensitivity": {
            **sensitivity,
            "role": "predeclared_sensitivity_not_primary_or_holdout",
            "excluded_seed_ids": sorted(SENTINEL_OVERLAP_SEEDS),
            "excluded_seed_cluster_count": len(SENTINEL_OVERLAP_SEEDS),
            "prior_sentinel_overlap_pair_ids": sentinel_overlap["pair_ids"],
            "prior_sentinel_overlap_pair_count": sentinel_overlap["pair_count"],
            "interpretation": "conditional_on_fixed_32_arm_matrix_simulator_and_rate_model",
            "comparison_to_primary": {
                "primary_directional_label": _ci_direction(primary_global),
                "sensitivity_directional_label": _ci_direction(sensitivity_global),
                "point_estimate_delta": float(sensitivity_global["point_estimate"])
                - float(primary_global["point_estimate"]),
                "point_estimate_ratio": float(sensitivity_global["point_estimate"])
                / float(primary_global["point_estimate"]),
                "ci95_low_delta": float(sensitivity_global["ci95_low"])
                - float(primary_global["ci95_low"]),
                "ci95_high_delta": float(sensitivity_global["ci95_high"])
                - float(primary_global["ci95_high"]),
            },
        },
        "combined_secondary": {
            **secondary,
            "role": "secondary_descriptive",
            "interpretation": "conditional_on_fixed_32_arm_matrix_simulator_and_rate_model",
        },
        "decision": {
            "fixed_sample_no_adaptive_stopping": True,
            "automatic_paper_claim_change": False,
            "independent_audit_verdict_in_driver": False,
            "status": "PENDING_INDEPENDENT_AUDIT_AND_RESEARCH_DECISION",
        },
        "scope_limits": [
            "static proportional matrix only",
            "seeds 0..99 were used for the prior go/no-go and are excluded from the primary estimator",
            "six prior sentinel pairs touch four extension seed clusters; a predeclared sensitivity removes all four clusters",
            "the extension is validation/descriptive, not an untouched confirmatory holdout",
            "combined 0..999 analysis is secondary",
            "bootstrap intervals are conditional on the fixed 32-arm matrix, simulator, and rate model",
            "no equal-policy, controller, congestion, background, TCP, or population-wide claim",
            "no v11.1 row enters either estimator",
            "proportional-vs-equal paper ratios require a separate equal-invariance argument",
        ],
    }

    review_reasons = _analysis_review_reasons(
        primary_global,
        sensitivity_global,
        secondary_global,
        primary_single_seed_dependence=bool(
            primary["leave_one_seed_out"]["single_seed_dependence"]
        ),
    )
    return {
        "export": export,
        "audit_review": {
            "status": (
                "READY_FOR_EXPLICIT_RESEARCH_DECISION"
                if not review_reasons
                else "REVIEW_EFFECT_STABILITY_OR_COUNTEREXAMPLES"
            ),
            "review_reasons": review_reasons,
            "extension_primary_tick_counts": primary_global["tick_counts"],
            "extension_primary_leave_one_seed_out": primary["leave_one_seed_out"],
            "prior_sentinel_overlap_pair_ids": sentinel_overlap["pair_ids"],
            "prior_sentinel_overlap_pair_count": sentinel_overlap["pair_count"],
            "comparison_to_primary": {
                "primary_directional_label": _ci_direction(primary_global),
                "sensitivity_directional_label": _ci_direction(sensitivity_global),
                "point_estimate_delta": float(sensitivity_global["point_estimate"])
                - float(primary_global["point_estimate"]),
                "point_estimate_ratio": float(sensitivity_global["point_estimate"])
                / float(primary_global["point_estimate"]),
                "ci95_low_delta": float(sensitivity_global["ci95_low"])
                - float(primary_global["ci95_low"]),
                "ci95_high_delta": float(sensitivity_global["ci95_high"])
                - float(primary_global["ci95_high"]),
            },
            "combined_comparison_to_primary": {
                "primary_directional_label": _ci_direction(primary_global),
                "combined_directional_label": _ci_direction(secondary_global),
                "point_estimate_delta": float(secondary_global["point_estimate"])
                - float(primary_global["point_estimate"]),
                "point_estimate_ratio": float(secondary_global["point_estimate"])
                / float(primary_global["point_estimate"]),
                "ci95_low_delta": float(secondary_global["ci95_low"])
                - float(primary_global["ci95_low"]),
                "ci95_high_delta": float(secondary_global["ci95_high"])
                - float(primary_global["ci95_high"]),
            },
            "interpretive_boundary": [
                "fixed proportional matrix validation, not a blind confirmatory holdout",
                "primary uses only seeds 100..999; combined 0..999 is secondary",
                "sensitivity removes all four prior-sentinel seed clusters",
                "intervals condition on the fixed 32-arm simulator/rate-model matrix",
                "legacy v11 and prior sentinel outcomes are not estimator inputs",
                "equal-policy/controller/congestion/background claims are out of scope",
            ],
        },
    }


def _assert_tree(actual: Any, expected: Any, path: str) -> None:
    if isinstance(expected, dict):
        _require(isinstance(actual, dict), f"{path}: expected object")
        _require(
            set(actual) == set(expected),
            f"{path}: object key set differs from the independent export",
        )
        for key, value in expected.items():
            _assert_tree(actual[key], value, f"{path}.{key}")
        return
    if isinstance(expected, list):
        _require(isinstance(actual, list) and len(actual) == len(expected), f"{path}: list mismatch")
        for index, (left, right) in enumerate(zip(actual, expected)):
            _assert_tree(left, right, f"{path}[{index}]")
        return
    if isinstance(expected, float):
        _require(
            isinstance(actual, (int, float))
            and _f64_hex(float(actual)) == _f64_hex(expected),
            f"{path}: binary64 numeric mismatch",
        )
        return
    _require(actual == expected, f"{path}: value mismatch")


def _verify_csv_rows_exact(
    path: Path, expected_rows: Sequence[Mapping[str, Any]]
) -> None:
    header, rows = _read_csv(path)
    _require(bool(expected_rows), f"independent CSV expectation is empty: {path.name}")
    _require(
        header == list(expected_rows[0].keys()) and len(rows) == len(expected_rows),
        f"{path.name} schema/cardinality mismatch",
    )
    for row_index, (actual, expected) in enumerate(zip(rows, expected_rows)):
        for field, value in expected.items():
            token = actual[field]
            if isinstance(value, bool):
                matches = token == str(value)
            elif isinstance(value, int):
                try:
                    matches = int(token) == value
                except ValueError:
                    matches = False
            elif isinstance(value, float):
                try:
                    matches = _f64_hex(float(token)) == _f64_hex(value)
                except ValueError:
                    matches = False
            else:
                matches = token == str(value)
            _require(matches, f"{path.name}[{row_index}].{field}: value mismatch")


def _verify_analysis_exports(
    output: Path,
    independent: Mapping[str, Any],
    plan_sha256: str,
    timing: Mapping[str, Any],
) -> Dict[str, Any]:
    recorded = _read_json(output / "analysis.json")
    _require(isinstance(recorded, dict), "analysis.json is not an object")
    _assert_tree(recorded, independent, "analysis")
    gate = _read_json(output / "gate.json")
    expected_gate = {
        "schema": GATE_SCHEMA,
        "passed": True,
        "plan_sha256": plan_sha256,
        "pair_count": EXTENSION_PAIR_COUNT,
        "row_count": EXTENSION_ROW_COUNT,
        "simulation_count": EXTENSION_ROW_COUNT,
        "primary_domain": "extension_only_seeds_100_999",
        "secondary_domain": "combined_seeds_0_999",
        "primary_scope": independent["analysis_role"],
        "sensitivity_excluded_seed_clusters": sorted(SENTINEL_OVERLAP_SEEDS),
        "secondary_is_not_primary": True,
        "fixed_sample_no_effect_based_stopping": True,
        "all_conservation_checks_passed": True,
        "n100_canonical_config_hashes_recomputed": True,
        "legacy_v11_or_sentinel_used_as_estimator_input": False,
        "paper_change_authorized": False,
        "decision": independent["decision"]["status"],
        "next_status": "PENDING_INDEPENDENT_AUDIT_AND_RESEARCH_DECISION",
    }
    _assert_tree(gate, expected_gate, "gate")
    runtime = _read_json(output / "runtime.json")
    expected_runtime = {
        "schema": RUNTIME_SCHEMA,
        "segment_count": int(timing["segment_count"]),
        "pair_count": EXTENSION_PAIR_COUNT,
        "total_wall_s": float(timing["elapsed_pool_wall_sum_s"]),
        "pool_wall_sum_s": float(timing["elapsed_pool_wall_sum_s"]),
        "worker_simulation_wall_sum_s": float(
            timing["worker_simulation_wall_sum_s"]
        ),
        "worker_end_to_end_wall_sum_s": float(
            timing["worker_end_to_end_wall_sum_s"]
        ),
        "recovered_segment_count": int(timing["recovered_segment_count"]),
        "timing_is_operational_not_scientific": True,
    }
    _assert_tree(runtime, expected_runtime, "runtime")
    _require(
        float(runtime["total_wall_s"]) > 0.0
        and float(runtime["pool_wall_sum_s"]) > 0.0
        and float(runtime["worker_simulation_wall_sum_s"]) > 0.0
        and float(runtime["worker_end_to_end_wall_sum_s"]) > 0.0
        and _f64_hex(runtime["total_wall_s"])
        == _f64_hex(expected_runtime["total_wall_s"])
        and _f64_hex(runtime["pool_wall_sum_s"])
        == _f64_hex(expected_runtime["pool_wall_sum_s"])
        and _f64_hex(runtime["worker_simulation_wall_sum_s"])
        == _f64_hex(expected_runtime["worker_simulation_wall_sum_s"])
        and _f64_hex(runtime["worker_end_to_end_wall_sum_s"])
        == _f64_hex(expected_runtime["worker_end_to_end_wall_sum_s"]),
        "runtime totals are not positive/binary64-identical to timing segments",
    )
    extension_arm_rows = [
        {
            "arm_id": arm_id,
            "pair_count": values["pair_count"],
            "geometric_mean_ratio": values["geometric_mean_ratio"],
            "ci95_low": values["ci95_low"],
            "ci95_high": values["ci95_high"],
        }
        for arm_id, values in sorted(
            independent["extension_primary"]["per_arm"].items()
        )
    ]
    combined_arm_rows = [
        {
            "arm_id": arm_id,
            "pair_count": values["pair_count"],
            "geometric_mean_ratio": values["geometric_mean_ratio"],
            "ci95_low": values["ci95_low"],
            "ci95_high": values["ci95_high"],
        }
        for arm_id, values in sorted(
            independent["combined_secondary"]["per_arm"].items()
        )
    ]
    _verify_csv_rows_exact(
        output / "arm_analysis.csv",
        extension_arm_rows,
    )
    _verify_csv_rows_exact(
        output / "combined_arm_analysis.csv",
        combined_arm_rows,
    )
    return {
        "analysis_schema": recorded.get("schema"),
        "completion_status": independent["decision"]["status"],
    }


def _validate_output_path(raw: str) -> Path:
    output = Path(raw).expanduser().resolve()
    _require(
        output.parent == CAMPAIGN_ROOT and OUTPUT_NAME_RE.fullmatch(output.name),
        f"output must be a direct, canonically named child of {CAMPAIGN_ROOT}",
    )
    _require(output.is_dir(), f"campaign output directory does not exist: {output}")
    return output


def _self_test() -> Dict[str, Any]:
    sources = _verify_source_seals()
    contract = _driver_contract_from_ast()
    _require(contract["has_main_guard"], "driver has no main guard")
    _require(not contract["imports_auditor"], "driver imports the independent auditor")
    arms = _expected_arms()
    extension_ids = _expected_pair_ids(EXTENSION_SEEDS)
    combined_ids = _expected_pair_ids(COMBINED_SEEDS)
    _require(len(extension_ids) == EXTENSION_PAIR_COUNT and len(set(extension_ids)) == EXTENSION_PAIR_COUNT, "extension self-test cardinality mismatch")
    _require(_json_digest(extension_ids) == EXPECTED_EXTENSION_PAIR_ID_SHA256, "extension self-test pair-ID digest mismatch")
    _require(len(combined_ids) == COMBINED_PAIR_COUNT and _json_digest(combined_ids) == EXPECTED_COMBINED_PAIR_ID_SHA256, "combined self-test pair-ID digest mismatch")
    first = Counter(pair["execution_order"][0] for pair in _expected_pairs())
    _require(first == Counter({ALLOCATORS[0]: 14_400, ALLOCATORS[1]: 14_400}), "self-test allocator order imbalance")
    _, extension_bootstrap = _bootstrap_indexes(len(EXTENSION_SEEDS))
    _require(extension_bootstrap == EXPECTED_EXTENSION_BOOTSTRAP_SHA256, "extension self-test bootstrap digest mismatch")
    sentinel_overlap = _verify_prior_sentinel_overlap()
    _, sensitivity_bootstrap = _bootstrap_indexes(
        len(EXTENSION_SEEDS) - len(SENTINEL_OVERLAP_SEEDS)
    )
    _require(
        sensitivity_bootstrap == EXPECTED_SENTINEL_EXCLUDED_BOOTSTRAP_SHA256,
        "sentinel-excluded self-test bootstrap digest mismatch",
    )
    _, combined_bootstrap = _bootstrap_indexes(len(COMBINED_SEEDS))
    _require(combined_bootstrap == EXPECTED_COMBINED_BOOTSTRAP_SHA256, "combined self-test bootstrap digest mismatch")
    n100 = _verify_n100_reference()
    return {
        "status": "PASS_SELF_TEST_NO_SIMULATION",
        "source_count": len(sources),
        "arm_count": len(arms),
        "extension_pair_count": len(extension_ids),
        "combined_pair_count": len(combined_ids),
        "preflight_pair_count": len(_expected_preflight_ids()),
        "allocator_first_pair_counts": dict(sorted(first.items())),
        "extension_pair_id_sha256": _json_digest(extension_ids),
        "combined_pair_id_sha256": _json_digest(combined_ids),
        "extension_bootstrap_sha256": extension_bootstrap,
        "sentinel_excluded_bootstrap_sha256": sensitivity_bootstrap,
        "prior_sentinel_overlap_pair_count": sentinel_overlap["pair_count"],
        "prior_sentinel_overlap_seed_ids": sentinel_overlap["seed_ids"],
        "combined_bootstrap_sha256": combined_bootstrap,
        "n100_pair_count": n100["pair_count"],
        "n100_row_count": n100["row_count"],
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Independent audit of corrected proportional n=1000 extension")
    parser.add_argument("--output", help="completed campaign output directory")
    parser.add_argument("--self-test", action="store_true", help="validate deterministic contracts without simulation")
    arguments = parser.parse_args(argv)
    if not arguments.self_test and not arguments.output:
        parser.error("--output is required unless --self-test is selected")
    return arguments


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    try:
        if arguments.self_test:
            report = _self_test()
        else:
            output = _validate_output_path(arguments.output)
            sources = _verify_source_seals()
            completion, complete = _verify_completion_bundle(output)
            manifest = _read_json(output / "run_manifest.json")
            _require(isinstance(manifest, dict), "run manifest is not an object")
            expected_pairs, plan_sha256 = _verify_plan(manifest)
            provenance = _verify_manifest_provenance(manifest, output)
            _require(completion.get("plan_sha256") == plan_sha256, "completion/run plan seal mismatch")
            checkpoints, extension_records = _load_checkpoints(output, expected_pairs, plan_sha256)
            preflight = _verify_preflight(output, checkpoints, manifest)
            timing = _verify_timing(output, extension_records)
            csv_exports = _verify_csv_exports(output, extension_records)
            n100 = _verify_n100_reference()
            independent = _scientific_analysis(extension_records, n100["records"])
            exports = _verify_analysis_exports(
                output,
                independent["export"],
                plan_sha256,
                timing,
            )
            _require(
                complete.get("status")
                == "COMPLETE_PENDING_INDEPENDENT_AUDIT_AND_RESEARCH_DECISION",
                "COMPLETE status mismatch",
            )
            _verify_immutable_after(
                manifest["immutable_before"], completion.get("immutable_after", {})
            )
            report = {
                "status": "PASS_INDEPENDENT_CORRECTED_PROPORTIONAL_N1000_EXTENSION_AUDIT",
                "decision": independent["audit_review"]["status"],
                "output": str(output),
                "inventory": {"extension_pair_count": len(extension_records), "extension_row_count": EXTENSION_ROW_COUNT, "combined_pair_count": COMBINED_PAIR_COUNT},
                "primary": independent["export"]["extension_primary"]["global"],
                "sentinel_excluded_sensitivity": independent["export"]["sentinel_excluded_sensitivity"]["global"],
                "secondary": independent["export"]["combined_secondary"]["global"],
                "audit_review": independent["audit_review"],
                "preflight": preflight,
                "timing": timing,
                "csv_exports": csv_exports,
                "n100_reference": {key: value for key, value in n100.items() if key != "records"},
                "provenance": provenance,
                "analysis_exports": exports,
                "source_seal_count": len(sources),
            }
    except Exception as exc:
        failure = {
            "status": "FAIL_INDEPENDENT_CORRECTED_PROPORTIONAL_N1000_EXTENSION_AUDIT",
            "decision": "STOP_AND_FIX_N1000_EXTENSION_INTEGRITY_FAILURE",
            "error": str(exc),
        }
        print(json.dumps(failure, indent=2, sort_keys=True, ensure_ascii=False))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
