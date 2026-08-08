"""Run the fixed corrected-proportional seeds-100..999 extension.

The 28,800 paired jobs are the only executable scope.  The committed corrected
n=100 compact exports are read-only inputs to a secondary 1,000-seed summary;
legacy v11 and sentinel outcomes are never estimator inputs.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import math
import multiprocessing as mp
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS_DIR = ROOT / "experiments"
for search_path in (ROOT, EXPERIMENTS_DIR):
    if str(search_path) in sys.path:
        sys.path.remove(str(search_path))
    sys.path.insert(0, str(search_path))

import run_corrected_proportional_n100 as corrected_n100  # noqa: E402
import run_rate_allocator_n100 as canonical  # noqa: E402
import run_rate_allocator_pilot as core  # noqa: E402
import sim  # noqa: E402


DRIVER_PATH = Path(__file__).resolve()
SIM_PATH = ROOT / "sim.py"
CANONICAL_DRIVER_PATH = Path(canonical.__file__).resolve()
CORE_DRIVER_PATH = Path(core.__file__).resolve()
CORRECTED_N100_DRIVER_PATH = Path(corrected_n100.__file__).resolve()
SPEC_PATH = (
    ROOT
    / "investigations"
    / "CORRECTED_PROPORTIONAL_N1000_EXTENSION_SPEC_2026_08_08.md"
)
EXPOSURE_PROVENANCE_PATH = ROOT / "investigations" / "maxmin_gate_2026_08_06.py"
OUTPUT_ROOT = (
    ROOT / "investigations" / "cp_n1000"
).resolve()
N100_ROOT = (
    ROOT
    / "investigations"
    / "corrected_proportional_n100"
    / "n100_2026-08-07_02"
).resolve()

BASELINE_COMMIT = "f2d8f88ec3cef01c250987df88245dc4361c245b"
EXPECTED_CANONICAL_PLAN_SHA256 = (
    "47099eedb41d1574cc49a6e08a2f7bb20b6c14077531b32b80222be9519291ac"
)
EXPECTED_ARM_SHA256 = (
    "467f87d72a89bf9bb15e80d824f43a5465f6731e3b890f1cea05e93a0f383b09"
)
EXPECTED_EXTENSION_PAIR_IDS_SHA256 = (
    "12f52040dbc480e3566dd9d25c4c89ae4d4cf40910bf5c30fc6834a54817268c"
)
EXPECTED_COMBINED_PAIR_IDS_SHA256 = (
    "3bd51d5ba6f303b4dcd0750f7a18d1e9c9a310962dfa339454cd6d9809f24717"
)
EXPECTED_BOOTSTRAP_SHA256 = {
    "extension_primary": "901e342e8d8849fcdd8bec11e7019b6b1a24d2ab73d62c61ec8eba8009f171d4",
    "extension_exposure_sensitivity": "92c451c7526085b32723402f91f2b06c0806e5345ebd6a74122db6267d1481ea",
    "combined_secondary": "983cc7176ab26dfcbaa22467b888439c67557da634f2bf3945721c64e42c3070",
}
EXPECTED_SOURCE_HASHES = {
    SIM_PATH: "96505cefe2e5aa761b80080d77145bfd384c688ce4a8ca5792f8f7ce17ef59bd",
    CANONICAL_DRIVER_PATH: "7d01a2e598c799b0c533fb650f33b8537f51fa3187f427fcf9ada108d56fd8b4",
    CORE_DRIVER_PATH: "777018e1a408eb5274d5ee87700fc66e4396fd5d39722f625f22e48840efc431",
    CORRECTED_N100_DRIVER_PATH: "7b65d37635a3d8315517f0076602cb4c663c1c0659ef1dbb3ee56e3053b10f9b",
    SPEC_PATH: "b3a74dcc5808d054f8025613b7a47f24867a33dbc894710aeced463b7788b41b",
    EXPOSURE_PROVENANCE_PATH: "2905e293712650b8c2ef8a259326e5502f102bf5773515712979aef2a8f7cb1b",
}
EXPECTED_N100_HASHES = {
    "COMPLETE.json": "ab9945a3d9826fc1a75af55657e65f246369bb322ed676972a379f9f33bf21ed",
    "completion_manifest.json": "6355cda3b07e025da2e88c8544a1a82760212510203e1b5f0ba08930c6691810",
    "pairs.csv": "d3acdacc328dfa567c816918b331ff8f6ef8bf27c36e226b0083aa4860e81f9b",
    "results_long.csv": "e599ea81f137abe0daee218ad465d86668e8a9ba38d40e7c7eb3a9f23461c7c8",
}
EXPECTED_N100_RUN_MANIFEST_SHA256 = (
    "7f13a2f10c4920ede8a917a23bb4906ad745b43df8b9bfb0e2306ed4de7428aa"
)

SAMPLE_IDS = tuple(range(100, 1000))
PREVIOUS_SAMPLE_IDS = tuple(range(100))
EXPOSED_SEED_CLUSTERS = frozenset({174, 199, 353, 657})
ALLOCATORS = (sim.RATE_ALLOCATOR_LINK_LOCAL, sim.RATE_ALLOCATOR_NETWORK_MAXMIN)
LEGACY_ALLOCATOR = sim.RATE_ALLOCATOR_LINK_LOCAL
MAXMIN_ALLOCATOR = sim.RATE_ALLOCATOR_NETWORK_MAXMIN
ARM_COUNT = 32
PAIR_COUNT = 28_800
SIMULATION_COUNT = 57_600
COMBINED_PAIR_COUNT = 32_000
PREFLIGHT_SEEDS = (100, 101)
PREFLIGHT_PAIR_COUNT = 64
BOOTSTRAP_REPLICATES = 20_000
BOOTSTRAP_SEED = 20_260_807
MAX_WORKERS = 8
CONSERVATIVE_PROJECTED_OUTPUT_BYTES = 450 * 1024 * 1024
MAX_SAFE_WINDOWS_PATH_CHARS = 248

PARTIAL_ROOT_NAMES = frozenset(
    {".run.lock", "run_manifest.json", "preflight_complete.json", "checkpoints", "timing_segments"}
)
FINAL_EXPORT_NAMES = frozenset(
    {
        "results_long.csv",
        "pairs.csv",
        "arm_analysis.csv",
        "combined_arm_analysis.csv",
        "analysis.json",
        "runtime.json",
        "gate.json",
    }
)
FINAL_ROOT_NAMES = PARTIAL_ROOT_NAMES | FINAL_EXPORT_NAMES | {
    "completion_manifest.json",
    "COMPLETE.json",
}
OUTPUT_NAME_RE = re.compile(r"n1000_extension_\d{4}-\d{2}-\d{2}_\d{2}")
_WORKER_HASHES: Dict[str, str] = {}


def _sha256_file(path: Path) -> str:
    return core._sha256_file(path)


def _digest(value: Any) -> str:
    return core._digest(value)


def _pair_id_digest(pair_ids: Sequence[str]) -> str:
    return _digest(list(pair_ids))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_hashes() -> Dict[str, str]:
    actual: Dict[str, str] = {}
    for path, expected in EXPECTED_SOURCE_HASHES.items():
        observed = _sha256_file(path)
        if observed != expected:
            raise RuntimeError(f"immutable source changed: {path}")
        actual[path.relative_to(ROOT).as_posix()] = observed
    actual[DRIVER_PATH.relative_to(ROOT).as_posix()] = _sha256_file(DRIVER_PATH)
    return dict(sorted(actual.items()))


def _run_git(*args: str, binary: bool = False) -> Any:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=not binary,
    ).stdout


def _status_paths() -> List[str]:
    raw = _run_git("status", "--porcelain=v1", "--untracked-files=all")
    paths: List[str] = []
    for line in raw.splitlines():
        if len(line) < 4 or " -> " in line:
            raise RuntimeError(f"unsupported git status entry: {line!r}")
        paths.append(line[3:].strip('"').replace("\\", "/"))
    return paths


def _git_state(*, allowed_output: Optional[Path]) -> Dict[str, Any]:
    head = _run_git("rev-parse", "HEAD").strip()
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", BASELINE_COMMIT, head],
        cwd=ROOT,
        capture_output=True,
    ).returncode == 0
    if not ancestor:
        raise RuntimeError("execution HEAD does not descend from the immutable baseline")
    upstream = _run_git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").strip()
    ahead_behind = _run_git("rev-list", "--left-right", "--count", "@{u}...HEAD").strip()
    if ahead_behind != "0\t0":
        raise RuntimeError("fresh scientific execution requires pushed upstream 0/0")
    paths = _status_paths()
    if allowed_output is None:
        if paths:
            raise RuntimeError(f"fresh scientific execution requires a clean tree: {paths}")
    else:
        prefix = allowed_output.relative_to(ROOT).as_posix().rstrip("/") + "/"
        unrelated = [path for path in paths if path != prefix[:-1] and not path.startswith(prefix)]
        if unrelated:
            raise RuntimeError(f"unrelated dirty paths during resume: {unrelated}")
    return {
        "baseline_commit": BASELINE_COMMIT,
        "baseline_is_ancestor": True,
        "execution_head": head,
        "upstream": upstream,
        "ahead": 0,
        "behind": 0,
        "unrelated_dirty_paths": [],
        "output_state_allowed": allowed_output is not None,
    }


def _canonical_arms() -> List[Tuple[int, Dict[str, Any]]]:
    source = canonical.build_plan()
    if source.get("plan_sha256") != EXPECTED_CANONICAL_PLAN_SHA256:
        raise RuntimeError("canonical n=100 plan seal changed")
    selected = [
        (index, copy.deepcopy(arm))
        for index, arm in enumerate(source["arms"])
        if arm.get("family") == "static_split"
        and arm.get("runner") == "proportional"
        and arm.get("policy") == "proportional"
        and arm.get("oracle_kind") == "proportional"
    ]
    if [index for index, _ in selected] != list(range(48, 80)):
        raise RuntimeError("canonical proportional arm indices changed")
    arms = [arm for _, arm in selected]
    if len(arms) != ARM_COUNT or _digest(arms) != EXPECTED_ARM_SHA256:
        raise RuntimeError("canonical proportional arm payload changed")
    return selected


def _materialize_pair(arm: Mapping[str, Any], arm_index: int, sample_id: int) -> Dict[str, Any]:
    config = json.loads(json.dumps(arm))
    config["sample_id"] = sample_id
    config["placement_seed"] = canonical.PLACEMENT_SEED_BASE + sample_id
    config["topology_seed"] = 1
    ordinal = arm_index * 1000 + sample_id
    execution_order = list(ALLOCATORS if ordinal % 2 == 0 else reversed(ALLOCATORS))
    return {
        "pair_id": f"a{arm_index + 1:03d}_{config['arm_id']}__s{sample_id:03d}",
        "arm_index": arm_index,
        "sample_index": sample_id,
        "sample_id": sample_id,
        "ordinal": ordinal,
        "execution_order": execution_order,
        "config": config,
        "config_sha256": _digest(config),
        "oracle_key": {
            "P": int(config["ring_size"]),
            "fabric": str(config["fabric"]),
            "k": int(config["k"]),
            "seed": sample_id,
        },
    }


def _expected_pair_ids(sample_ids: Iterable[int]) -> List[str]:
    return [
        f"a{index + 1:03d}_{arm['arm_id']}__s{seed:03d}"
        for index, arm in _canonical_arms()
        for seed in sample_ids
    ]


def build_plan() -> Dict[str, Any]:
    indexed_arms = _canonical_arms()
    pairs = [
        _materialize_pair(arm, arm_index, seed)
        for arm_index, arm in indexed_arms
        for seed in SAMPLE_IDS
    ]
    pair_ids = [pair["pair_id"] for pair in pairs]
    combined_ids = _expected_pair_ids(range(1000))
    first_counts = Counter(pair["execution_order"][0] for pair in pairs)
    preflight_ids = [
        pair["pair_id"] for pair in pairs if pair["sample_id"] in PREFLIGHT_SEEDS
    ]
    if (
        len(pairs) != PAIR_COUNT
        or len(set(pair_ids)) != PAIR_COUNT
        or _pair_id_digest(pair_ids) != EXPECTED_EXTENSION_PAIR_IDS_SHA256
        or _pair_id_digest(combined_ids) != EXPECTED_COMBINED_PAIR_IDS_SHA256
        or first_counts != Counter({LEGACY_ALLOCATOR: 14_400, MAXMIN_ALLOCATOR: 14_400})
        or len(preflight_ids) != PREFLIGHT_PAIR_COUNT
    ):
        raise RuntimeError("fixed n=1000 extension cardinality/digest changed")
    plan: Dict[str, Any] = {
        "schema": "corrected-proportional-n1000-extension-plan-v1",
        "sample_ids": list(SAMPLE_IDS),
        "allocators": list(ALLOCATORS),
        "arms": [arm for _, arm in indexed_arms],
        "canonical_arm_indices": [index for index, _ in indexed_arms],
        "pairs": pairs,
        "arm_count": ARM_COUNT,
        "pair_count": PAIR_COUNT,
        "simulation_count": SIMULATION_COUNT,
        "combined_pair_count": COMBINED_PAIR_COUNT,
        "arm_sha256": EXPECTED_ARM_SHA256,
        "pair_id_list_sha256": EXPECTED_EXTENSION_PAIR_IDS_SHA256,
        "combined_pair_id_list_sha256": EXPECTED_COMBINED_PAIR_IDS_SHA256,
        "allocator_first_pair_counts": dict(sorted(first_counts.items())),
        "preflight_pair_ids": preflight_ids,
        "primary_scope": "extension_seeds_100_through_999_validation_not_blind_holdout",
        "secondary_scope": "sealed_n100_plus_extension_read_only",
        "excluded_estimator_inputs": ["legacy_v11", "prior_maxmin_gate", "equal_policy"],
        "exposure_sensitivity_excluded_seed_clusters": sorted(EXPOSED_SEED_CLUSTERS),
        "no_other_execution_scope": True,
    }
    plan["plan_sha256"] = _digest(plan)
    return plan


def _verify_plan(plan: Mapping[str, Any]) -> str:
    recorded = str(plan.get("plan_sha256", ""))
    unsigned = copy.deepcopy(dict(plan))
    unsigned.pop("plan_sha256", None)
    if not recorded or _digest(unsigned) != recorded or dict(plan) != build_plan():
        raise RuntimeError("plan is not the fixed canonical extension")
    return recorded


def _read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _verify_n100_reference() -> Dict[str, Any]:
    for name, expected in EXPECTED_N100_HASHES.items():
        path = N100_ROOT / name
        if not path.is_file() or _sha256_file(path) != expected:
            raise RuntimeError(f"sealed n=100 compact reference changed: {path}")
    complete = json.loads((N100_ROOT / "COMPLETE.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (N100_ROOT / "completion_manifest.json").read_text(encoding="utf-8")
    )
    if (
        complete.get("schema") != "corrected-proportional-n100-complete-v1"
        or complete.get("completion_manifest_sha256")
        != EXPECTED_N100_HASHES["completion_manifest.json"]
        or manifest.get("pair_count") != 3_200
        or manifest.get("simulation_count") != 6_400
    ):
        raise RuntimeError("sealed n=100 completion linkage changed")
    artifacts = manifest.get("artifacts", {})
    for name in ("pairs.csv", "results_long.csv", "run_manifest.json"):
        path = N100_ROOT / name
        entry = artifacts.get(name, {})
        if (
            not path.is_file()
            or int(entry.get("bytes", -1)) != path.stat().st_size
            or entry.get("sha256") != _sha256_file(path)
        ):
            raise RuntimeError(f"n=100 signed compact artifact changed: {name}")
    if artifacts["run_manifest.json"]["sha256"] != EXPECTED_N100_RUN_MANIFEST_SHA256:
        raise RuntimeError("n=100 signed run manifest hash changed")
    old_run = json.loads((N100_ROOT / "run_manifest.json").read_text(encoding="utf-8"))
    old_plan = old_run.get("plan", {})
    old_pairs_spec = old_plan.get("pairs", [])
    canonical_plan = canonical.build_plan()
    canonical_pairs = [
        pair
        for pair in canonical_plan["pairs"]
        if pair["config"].get("oracle_kind") == "proportional"
        and pair["config"].get("family") == "static_split"
    ]
    if old_pairs_spec != canonical_pairs or len(old_pairs_spec) != 3_200:
        raise RuntimeError("n=100 signed pair specs differ from canonical configs")
    expected_ids = _expected_pair_ids(PREVIOUS_SAMPLE_IDS)
    if [pair["pair_id"] for pair in old_pairs_spec] != expected_ids:
        raise RuntimeError("n=100 signed pair order/bijection changed")
    spec_by_id = {pair["pair_id"]: pair for pair in old_pairs_spec}

    pair_rows = _read_csv(N100_ROOT / "pairs.csv")
    result_rows = _read_csv(N100_ROOT / "results_long.csv")
    if [row.get("pair_id") for row in pair_rows] != expected_ids or len(result_rows) != 6_400:
        raise RuntimeError("n=100 compact CSV cardinality/order changed")
    results_by_pair: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in result_rows:
        results_by_pair[row.get("pair_id", "")].append(row)
    normalized: List[Dict[str, Any]] = []
    for row in pair_rows:
        pair_id = row["pair_id"]
        spec = spec_by_id[pair_id]
        allocator_rows = results_by_pair.get(pair_id, [])
        indexed = {item.get("allocator"): item for item in allocator_rows}
        if len(allocator_rows) != 2 or set(indexed) != set(ALLOCATORS):
            raise RuntimeError(f"n=100 compact allocator bijection changed: {pair_id}")
        recomputed = _digest(spec["config"])
        if recomputed != spec["config_sha256"] or any(
            item.get("config_sha256") != recomputed for item in allocator_rows
        ):
            raise RuntimeError(f"n=100 canonical config digest mismatch: {pair_id}")
        legacy_time = float(indexed[LEGACY_ALLOCATOR]["completion_time_s"])
        maxmin_time = float(indexed[MAXMIN_ALLOCATOR]["completion_time_s"])
        if (
            float(row["link_local_time_s"]) != legacy_time
            or float(row["network_maxmin_time_s"]) != maxmin_time
            or int(row["sample_id"]) != int(spec["sample_id"])
            or row["arm_id"] != spec["config"]["arm_id"]
        ):
            raise RuntimeError(f"n=100 compact pair/result join changed: {pair_id}")
        normalized.append(
            {
                "pair_id": pair_id,
                "arm_id": row["arm_id"],
                "sample_id": int(row["sample_id"]),
                "fabric": row["fabric"],
                "ring_size": int(row["ring_size"]),
                "k": int(row["k"]),
                "link_local_time_s": legacy_time,
                "network_maxmin_time_s": maxmin_time,
                "network_over_link_local": maxmin_time / legacy_time,
                "log_network_over_link_local": math.log(maxmin_time / legacy_time),
                "network_minus_link_local_ticks": int(
                    indexed[MAXMIN_ALLOCATOR]["simulated_ticks"]
                )
                - int(indexed[LEGACY_ALLOCATOR]["simulated_ticks"]),
            }
        )
    return {
        "root": N100_ROOT.relative_to(ROOT).as_posix(),
        "hashes": dict(EXPECTED_N100_HASHES),
        "signed_run_manifest_sha256": EXPECTED_N100_RUN_MANIFEST_SHA256,
        "plan_sha256": old_plan.get("plan_sha256"),
        "pair_count": len(normalized),
        "simulation_count": len(result_rows),
        "pair_id_list_sha256": _pair_id_digest(expected_ids),
        "canonical_config_sha256_recomputed": True,
        "rows": normalized,
    }


def _reference_public(refs: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in refs.items() if key != "rows"}


def _immutable_snapshot(*, allowed_output: Optional[Path]) -> Dict[str, Any]:
    refs = _verify_n100_reference()
    sources = _source_hashes()
    return {
        "git": _git_state(allowed_output=allowed_output),
        "sources": sources,
        "source_sha256": sources,
        "n100_reference": _reference_public(refs),
        "n100_reference_sha256": dict(EXPECTED_N100_HASHES),
        "exposure_provenance_only": {
            "path": EXPOSURE_PROVENANCE_PATH.relative_to(ROOT).as_posix(),
            "sha256": EXPECTED_SOURCE_HASHES[EXPOSURE_PROVENANCE_PATH],
            "estimator_input": False,
            "excluded_seed_clusters": sorted(EXPOSED_SEED_CLUSTERS),
        },
    }


def _validate_output(raw: str, *, require_absent: bool) -> Path:
    output = Path(raw)
    if not output.is_absolute():
        raise RuntimeError("output path must be absolute")
    output = output.resolve()
    if output.parent != OUTPUT_ROOT or not OUTPUT_NAME_RE.fullmatch(output.name):
        raise RuntimeError(f"output must be a direct, named child of {OUTPUT_ROOT}")
    if require_absent and output.exists():
        raise RuntimeError("fresh output path already exists")
    if not require_absent and not output.is_dir():
        raise RuntimeError("resume output directory does not exist")
    return output


def _path_length_gate(output: Path) -> Dict[str, Any]:
    longest_pair_id = max(_expected_pair_ids(SAMPLE_IDS), key=len)
    final_path = output / "checkpoints" / f"{longest_pair_id}.json"
    staging_path = (
        output
        / "checkpoints"
        / ".staging"
        / f".{longest_pair_id}.json.tmp-12345678"
    )
    maximum = max(len(str(final_path)), len(str(staging_path)))
    if os.name == "nt" and maximum > MAX_SAFE_WINDOWS_PATH_CHARS:
        raise RuntimeError("campaign path exceeds conservative Windows safety limit")
    return {
        "passed": True,
        "longest_pair_id_chars": len(longest_pair_id),
        "max_final_path_chars": len(str(final_path)),
        "max_atomic_temp_path_chars": len(str(staging_path)),
        "windows_safety_limit_chars": MAX_SAFE_WINDOWS_PATH_CHARS,
    }


def _authorization(
    plan: Mapping[str, Any], output: Path, workers: int, immutable: Mapping[str, Any]
) -> str:
    return _digest(
        {
            "schema": "corrected-proportional-n1000-extension-authorization-v1",
            "plan_sha256": plan["plan_sha256"],
            "output": str(output),
            "workers": workers,
            "execution_head": immutable["git"]["execution_head"],
            "sources": immutable["sources"],
            "n100_reference": immutable["n100_reference"],
        }
    )


def _configure_core() -> None:
    core.DRIVER_PATH = DRIVER_PATH
    core.PILOT_ROOT = OUTPUT_ROOT
    core.SAMPLE_IDS = SAMPLE_IDS
    core._make_topology_and_ring = canonical._make_topology_and_ring
    core._finite_positive = corrected_n100._finite_timing_value
    core._conservation_gate = corrected_n100._conservation_gate


def _verify_worker_hashes() -> None:
    if not _WORKER_HASHES:
        raise RuntimeError("worker source authorization is unavailable")
    if _source_hashes() != _WORKER_HASHES:
        raise RuntimeError("worker source bytes changed")


def _worker_init(expected_hashes: Mapping[str, str]) -> None:
    global _WORKER_HASHES
    _WORKER_HASHES = dict(expected_hashes)
    _configure_core()
    _verify_worker_hashes()
    core._worker_init(
        _WORKER_HASHES[SIM_PATH.relative_to(ROOT).as_posix()],
        _WORKER_HASHES[DRIVER_PATH.relative_to(ROOT).as_posix()],
    )


def _run_pair_worker(pair: Mapping[str, Any]) -> Dict[str, Any]:
    _configure_core()
    _verify_worker_hashes()
    checkpoint = core._run_pair_worker(pair)
    _verify_worker_hashes()
    return checkpoint


def _finite_positive(value: Any, label: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise RuntimeError(f"{label} must be positive and finite")
    return parsed


def _finite_nonnegative(value: Any, label: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0:
        raise RuntimeError(f"{label} must be non-negative and finite")
    return parsed


def _valid_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_checkpoint(
    checkpoint: Mapping[str, Any], pair: Mapping[str, Any], plan_sha256: str
) -> None:
    if (
        checkpoint.get("schema") != "rate-allocator-pair-checkpoint-v1"
        or checkpoint.get("pair_id") != pair["pair_id"]
        or checkpoint.get("pair_spec") != pair
        or checkpoint.get("plan_sha256") != plan_sha256
        or checkpoint.get("pair_gate")
        != {"passed": True, "initial_digests_equal": True, "mutable_instances_distinct": True}
    ):
        raise RuntimeError(f"checkpoint identity/gate mismatch: {pair['pair_id']}")
    rows = checkpoint.get("rows", [])
    if len(rows) != 2 or {row.get("allocator") for row in rows} != set(ALLOCATORS):
        raise RuntimeError(f"checkpoint allocator bijection failed: {pair['pair_id']}")
    config = pair["config"]
    if (
        config.get("family") != "static_split"
        or config.get("runner") != "proportional"
        or config.get("policy") != "proportional"
        or config.get("congestion") is not None
    ):
        raise RuntimeError(f"checkpoint escaped proportional-only scope: {pair['pair_id']}")
    for row in rows:
        expected_position = pair["execution_order"].index(row["allocator"])
        conservation = row.get("conservation", {})
        expected_flows = int(config["ring_size"]) * int(config["k"])
        max_error = float(conservation.get("maximum_abs_error_bytes", math.inf))
        max_flow_error = float(
            conservation.get("maximum_per_flow_error_bytes", math.inf)
        )
        if (
            row.get("pair_id") != pair["pair_id"]
            or row.get("arm_id") != config["arm_id"]
            or int(row.get("sample_id", -1)) != int(pair["sample_id"])
            or row.get("family") != "static_split"
            or row.get("runner") != "proportional"
            or row.get("policy") != "proportional"
            or row.get("config_sha256") != pair["config_sha256"]
            or int(row.get("execution_position", -1)) != expected_position
            or not conservation.get("passed")
            or int(conservation.get("foreground_flow_count", -1))
            != expected_flows
            or int(conservation.get("checks", -1)) != int(config["ring_size"])
            or int(conservation.get("individual_remaining_values_checked", -1))
            != expected_flows
            or int(conservation.get("foreground_remaining_nonzero_count", -1)) != 0
            or float(conservation.get("remaining_foreground_bytes", math.inf)) != 0.0
            or float(conservation.get("foreground_remaining_min_bytes", math.inf)) != 0.0
            or float(conservation.get("foreground_remaining_max_bytes", math.inf)) != 0.0
            or int(conservation.get("non_bit_exact_flow_count", -1)) != 0
            or not 0.0 <= max_error <= 1e-6
            or not 0.0 <= max_flow_error <= 1e-6
            or row.get("adaptive_gate") is not None
            or row.get("background_instance_id") is not None
            or row.get("congestion_instance_id") is not None
        ):
            raise RuntimeError(f"checkpoint conservation/position failed: {pair['pair_id']}")
        completion = _finite_positive(row.get("completion_time_s"), "completion time")
        wall = _finite_positive(row.get("wall_time_s"), "wall time")
        cpu = _finite_nonnegative(row.get("cpu_time_s"), "CPU time")
        simulation_wall = _finite_positive(
            row.get("simulation_wall_time_s"), "simulation wall time"
        )
        simulation_cpu = _finite_nonnegative(
            row.get("simulation_cpu_time_s"), "simulation CPU time"
        )
        ticks = int(row.get("simulated_ticks", 0))
        if (
            row.get("completion_time_hex") != core._f64_hex(completion)
            or row.get("wall_time_hex") != core._f64_hex(wall)
            or row.get("cpu_time_hex") != core._f64_hex(cpu)
            or row.get("simulation_wall_time_hex") != core._f64_hex(simulation_wall)
            or row.get("simulation_cpu_time_hex") != core._f64_hex(simulation_cpu)
            or ticks <= 0
            or not math.isclose(
                completion,
                ticks * float(config["dt_s"]),
                rel_tol=2e-13,
                abs_tol=2e-15,
            )
            or simulation_wall > wall + 1e-9
        ):
            raise RuntimeError(f"checkpoint timing/float seal failed: {pair['pair_id']}")
    for field in (
        "config_sha256",
        "topology_sha256",
        "ring_sha256",
        "route_sha256",
        "process_initial_sha256",
    ):
        values = [row.get(field) for row in rows]
        if len(set(values)) != 1 or not _valid_digest(values[0]):
            raise RuntimeError(f"paired initial-state digest failed ({field}): {pair['pair_id']}")
    for field in ("topology_instance_id", "simulator_instance_id"):
        values = [row.get(field) for row in rows]
        if any(not isinstance(value, int) for value in values) or len(set(values)) != 2:
            raise RuntimeError(f"mutable-instance separation failed ({field}): {pair['pair_id']}")
    timing = checkpoint.get("parent_timing", {})
    if int(timing.get("segment_index", 0)) < 1:
        raise RuntimeError(f"checkpoint timing segment missing: {pair['pair_id']}")
    _finite_positive(timing.get("pool_elapsed_at_checkpoint_s"), "parent elapsed")


def _checkpoint_path(output: Path, pair_id: str) -> Path:
    return output / "checkpoints" / f"{pair_id}.json"


def _existing_checkpoints(
    output: Path, plan: Mapping[str, Any]
) -> Dict[str, Dict[str, Any]]:
    expected = {pair["pair_id"]: pair for pair in plan["pairs"]}
    found: Dict[str, Dict[str, Any]] = {}
    for path in sorted((output / "checkpoints").iterdir()):
        if path.name == ".staging" and path.is_dir():
            if any(path.iterdir()):
                raise RuntimeError("checkpoint staging is not empty")
            continue
        if not path.is_file() or path.suffix != ".json" or path.stem not in expected:
            raise RuntimeError(f"unexpected checkpoint artifact: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        _validate_checkpoint(value, expected[path.stem], plan["plan_sha256"])
        found[path.stem] = value
    return found


def _timing_path(output: Path, index: int) -> Path:
    return output / "timing_segments" / f"segment_{index:03d}.json"


def _ordered_timing_paths(timing_dir: Path) -> List[Path]:
    return sorted(
        timing_dir.glob("segment_*.json"),
        key=lambda path: int(path.stem.removeprefix("segment_")),
    )


def _load_timing(output: Path, checkpoints: Mapping[str, Any]) -> List[Dict[str, Any]]:
    timing_dir = output / "timing_segments"
    entries = list(timing_dir.iterdir())
    for path in entries:
        if path.name == ".staging" and path.is_dir() and not any(path.iterdir()):
            continue
        if not path.is_file() or not re.fullmatch(r"segment_\d{3,}\.json", path.name):
            raise RuntimeError(f"unauthorized timing artifact: {path}")
    covered: set[str] = set()
    segments: List[Dict[str, Any]] = []
    preflight_ids = set(_expected_pair_ids(PREFLIGHT_SEEDS))
    for expected_index, path in enumerate(_ordered_timing_paths(timing_dir), 1):
        if path != _timing_path(output, expected_index):
            raise RuntimeError("timing segment sequence has a gap")
        value = json.loads(path.read_text(encoding="utf-8"))
        pair_ids = value.get("pair_ids", [])
        phase = value.get("phase")
        recovered = value.get("recovered_after_interruption")
        pair_set = set(pair_ids) if isinstance(pair_ids, list) else set()
        if (
            value.get("schema") != "corrected-proportional-n1000-extension-timing-segment-v1"
            or value.get("segment_index") != expected_index
            or phase not in {"preflight_64", "remaining_28736", "recovered_after_interruption"}
            or not isinstance(recovered, bool)
            or ((phase == "recovered_after_interruption") != recovered)
            or not isinstance(pair_ids, list)
            or not pair_ids
            or len(pair_ids) != len(set(pair_ids))
            or any(pair_id not in checkpoints or pair_id in covered for pair_id in pair_ids)
            or int(value.get("pair_count", -1)) != len(pair_ids)
        ):
            raise RuntimeError(f"invalid timing segment: {path}")
        if (
            (phase == "preflight_64" and not pair_set <= preflight_ids)
            or (phase == "remaining_28736" and not pair_set.isdisjoint(preflight_ids))
            or (
                phase == "recovered_after_interruption"
                and not (pair_set <= preflight_ids or pair_set.isdisjoint(preflight_ids))
            )
        ):
            raise RuntimeError(f"timing phase mixes preflight/main pairs: {path}")
        expected_sim = sum(
            float(row["simulation_wall_time_s"])
            for pair_id in pair_ids
            for row in checkpoints[pair_id]["rows"]
        )
        expected_end = sum(
            float(row["wall_time_s"])
            for pair_id in pair_ids
            for row in checkpoints[pair_id]["rows"]
        )
        elapsed = _finite_positive(value.get("elapsed_pool_wall_s"), "segment elapsed")
        if (
            core._f64_hex(value.get("worker_simulation_wall_sum_s"))
            != core._f64_hex(expected_sim)
            or core._f64_hex(value.get("worker_end_to_end_wall_sum_s"))
            != core._f64_hex(expected_end)
            or any(
                int(checkpoints[pair_id]["parent_timing"]["segment_index"])
                != expected_index
                or float(checkpoints[pair_id]["parent_timing"]["pool_elapsed_at_checkpoint_s"])
                > elapsed
                for pair_id in pair_ids
            )
        ):
            raise RuntimeError(f"timing segment/checkpoint provenance mismatch: {path}")
        covered.update(pair_ids)
        segments.append(value)
    uncovered = sorted(set(checkpoints) - covered)
    if uncovered:
        index = len(segments) + 1
        if {
            int(checkpoints[pair_id]["parent_timing"]["segment_index"])
            for pair_id in uncovered
        } != {index}:
            raise RuntimeError("uncovered checkpoints span an invalid timing segment index")
        recovered = {
            "schema": "corrected-proportional-n1000-extension-timing-segment-v1",
            "segment_index": index,
            "phase": "recovered_after_interruption",
            "pair_ids": uncovered,
            "pair_count": len(uncovered),
            "elapsed_pool_wall_s": max(
                float(checkpoints[pair_id]["parent_timing"]["pool_elapsed_at_checkpoint_s"])
                for pair_id in uncovered
            ),
            "worker_simulation_wall_sum_s": sum(
                float(row["simulation_wall_time_s"])
                for pair_id in uncovered
                for row in checkpoints[pair_id]["rows"]
            ),
            "worker_end_to_end_wall_sum_s": sum(
                float(row["wall_time_s"])
                for pair_id in uncovered
                for row in checkpoints[pair_id]["rows"]
            ),
            "recovered_after_interruption": True,
        }
        core._atomic_json_once(_timing_path(output, index), recovered)
        segments.append(recovered)
    return segments


def _run_phase(
    pending: Sequence[Mapping[str, Any]],
    *,
    phase: str,
    output: Path,
    plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    checkpoints: Dict[str, Dict[str, Any]],
    segment_index: int,
) -> None:
    if not pending:
        return
    start = time.perf_counter()
    executor = ProcessPoolExecutor(
        max_workers=int(manifest["workers"]),
        mp_context=mp.get_context("spawn"),
        initializer=_worker_init,
        initargs=(manifest["immutable_before"]["sources"],),
    )
    try:
        futures = {executor.submit(_run_pair_worker, pair): pair for pair in pending}
        for completed, future in enumerate(as_completed(futures), 1):
            pair = futures[future]
            checkpoint = future.result()
            checkpoint["plan_sha256"] = plan["plan_sha256"]
            checkpoint["parent_timing"] = {
                "segment_index": segment_index,
                "pool_elapsed_at_checkpoint_s": time.perf_counter() - start,
            }
            _validate_checkpoint(checkpoint, pair, plan["plan_sha256"])
            core._atomic_json_once(_checkpoint_path(output, pair["pair_id"]), checkpoint)
            checkpoints[pair["pair_id"]] = checkpoint
            report_every = max(1, len(pending) // 20)
            if completed == len(pending) or completed % report_every == 0:
                elapsed = time.perf_counter() - start
                eta_min = (len(pending) - completed) / max(completed / elapsed, 1e-12) / 60
                print(f"[{phase}] {completed:,}/{len(pending):,}; ETA {eta_min:.2f} min", flush=True)
    except BaseException:
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)
    pair_ids = sorted(pair["pair_id"] for pair in pending)
    segment = {
        "schema": "corrected-proportional-n1000-extension-timing-segment-v1",
        "segment_index": segment_index,
        "phase": phase,
        "pair_ids": pair_ids,
        "pair_count": len(pair_ids),
        "elapsed_pool_wall_s": time.perf_counter() - start,
        "worker_simulation_wall_sum_s": sum(
            float(row["simulation_wall_time_s"])
            for pair_id in pair_ids
            for row in checkpoints[pair_id]["rows"]
        ),
        "worker_end_to_end_wall_sum_s": sum(
            float(row["wall_time_s"])
            for pair_id in pair_ids
            for row in checkpoints[pair_id]["rows"]
        ),
        "recovered_after_interruption": False,
    }
    core._atomic_json_once(_timing_path(output, segment_index), segment)


def _file_metadata(path: Path) -> Dict[str, Any]:
    return {"bytes": path.stat().st_size, "sha256": _sha256_file(path)}


def _held_lock_metadata(path: Path, run_lock: core.ExclusiveRunLock) -> Dict[str, Any]:
    try:
        expected_path = path.resolve(strict=True)
        declared_path = Path(run_lock.path).resolve(strict=True)
        handle = run_lock.handle
        handle_path = Path(handle.name).resolve(strict=True)
    except (AttributeError, OSError, TypeError) as exc:
        raise RuntimeError("held run-lock handle is unavailable") from exc
    if expected_path != declared_path or expected_path != handle_path or handle.closed:
        raise RuntimeError("held run-lock path/handle identity changed")
    handle.flush()
    path_before = path.stat()
    handle_before = os.fstat(handle.fileno())
    if (path_before.st_dev, path_before.st_ino) != (
        handle_before.st_dev,
        handle_before.st_ino,
    ):
        raise RuntimeError("held run-lock no longer identifies the path")
    original = handle.tell()
    digest = hashlib.sha256()
    size = 0
    try:
        handle.seek(0)
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    finally:
        handle.seek(original)
    path_after = path.stat()
    handle_after = os.fstat(handle.fileno())
    before_signature = (
        path_before.st_dev,
        path_before.st_ino,
        path_before.st_size,
        path_before.st_mtime_ns,
    )
    if (
        before_signature
        != (
            path_after.st_dev,
            path_after.st_ino,
            path_after.st_size,
            path_after.st_mtime_ns,
        )
        or before_signature
        != (
            handle_after.st_dev,
            handle_after.st_ino,
            handle_after.st_size,
            handle_after.st_mtime_ns,
        )
        or size != path_after.st_size
    ):
        raise RuntimeError("held run-lock changed during hashing")
    return {"bytes": size, "sha256": digest.hexdigest(), "hashed_via_held_handle": True}


def _verify_root_names(output: Path) -> None:
    names = {path.name for path in output.iterdir() if path.name != ".staging"}
    if not names.issubset(FINAL_ROOT_NAMES) or not {
        ".run.lock", "run_manifest.json", "checkpoints", "timing_segments"
    }.issubset(names):
        raise RuntimeError(f"unexpected/missing output-root artifacts: {sorted(names)}")
    if (output / ".staging").exists() and any((output / ".staging").iterdir()):
        raise RuntimeError("root staging is not empty")


def _verify_directory_inventory(output: Path, *, require_complete: bool) -> None:
    allowed_dirs = {"checkpoints", "timing_segments"}
    actual_dirs: set[str] = set()
    for path in output.rglob("*"):
        if not path.is_dir():
            continue
        relative = path.relative_to(output).as_posix()
        if path.name == ".staging" and not any(path.iterdir()):
            continue
        actual_dirs.add(relative)
    if actual_dirs != allowed_dirs:
        raise RuntimeError(f"campaign directory inventory is not exact: {sorted(actual_dirs)}")
    expected_checkpoint_names = {
        f"{pair_id}.json" for pair_id in _expected_pair_ids(SAMPLE_IDS)
    }
    checkpoint_names = {
        path.name
        for path in (output / "checkpoints").iterdir()
        if path.is_file()
    }
    if (
        not checkpoint_names.issubset(expected_checkpoint_names)
        or (require_complete and checkpoint_names != expected_checkpoint_names)
    ):
        raise RuntimeError("checkpoint filename inventory is not exact")
    timing_entries = [
        path
        for path in (output / "timing_segments").iterdir()
        if not (path.name == ".staging" and path.is_dir() and not any(path.iterdir()))
    ]
    if any(
        not path.is_file() or not re.fullmatch(r"segment_\d{3,}\.json", path.name)
        for path in timing_entries
    ):
        raise RuntimeError("timing filename inventory is not exact")
    if require_complete and not timing_entries:
        raise RuntimeError("complete campaign has no timing segments")


def _preflight_gate(
    plan: Mapping[str, Any], checkpoints: Mapping[str, Mapping[str, Any]]
) -> Dict[str, Any]:
    expected = list(plan["preflight_pair_ids"])
    if set(checkpoints) != set(expected) or len(checkpoints) != PREFLIGHT_PAIR_COUNT:
        raise RuntimeError("preflight checkpoint set changed")
    first = Counter(checkpoints[pair_id]["pair_spec"]["execution_order"][0] for pair_id in expected)
    seeds = Counter(int(checkpoints[pair_id]["pair_spec"]["sample_id"]) for pair_id in expected)
    arms = Counter(checkpoints[pair_id]["pair_spec"]["config"]["arm_id"] for pair_id in expected)
    if first != Counter({LEGACY_ALLOCATOR: 32, MAXMIN_ALLOCATOR: 32}) or seeds != Counter({100: 32, 101: 32}) or set(arms.values()) != {2}:
        raise RuntimeError("preflight balance/coverage changed")
    return {
        "passed": True,
        "integrity_only_no_effect_stopping": True,
        "ordered_pair_ids": expected,
        "pair_count": PREFLIGHT_PAIR_COUNT,
        "simulation_count": 128,
        "allocator_first_pair_counts": dict(sorted(first.items())),
        "seed_pair_counts": {str(key): value for key, value in sorted(seeds.items())},
        "arm_count": len(arms),
        "conservation_pass_count": 128,
    }


def _write_or_verify_preflight(
    output: Path,
    plan: Mapping[str, Any],
    checkpoints: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> Dict[str, Any]:
    subset = {pair_id: checkpoints[pair_id] for pair_id in plan["preflight_pair_ids"]}
    gate = _preflight_gate(plan, subset)
    checkpoint_signatures = {
        f"checkpoints/{pair_id}.json": _file_metadata(_checkpoint_path(output, pair_id))
        for pair_id in gate["ordered_pair_ids"]
    }
    timing_signatures: Dict[str, Dict[str, Any]] = {}
    covered: set[str] = set()
    expected = set(gate["ordered_pair_ids"])
    for path in sorted((output / "timing_segments").glob("segment_*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        ids = set(value.get("pair_ids", []))
        if ids and ids.issubset(expected):
            timing_signatures[path.relative_to(output).as_posix()] = _file_metadata(path)
            covered.update(ids)
    if covered != expected:
        raise RuntimeError("preflight timing signatures do not cover the 64 pairs")
    value = {
        "schema": "corrected-proportional-n1000-extension-preflight-v1",
        **gate,
        "plan_sha256": plan["plan_sha256"],
        "run_manifest_signature": _file_metadata(output / "run_manifest.json"),
        "checkpoint_signatures": checkpoint_signatures,
        "timing_segment_signatures": timing_signatures,
        "source_gate": {
            "passed": True,
            "driver_sha256": manifest["driver_sha256"],
            "source_sha256": manifest["immutable_before"]["sources"],
            "n100_reference_sha256": manifest["immutable_before"][
                "n100_reference_sha256"
            ],
        },
    }
    path = output / "preflight_complete.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != value:
            raise RuntimeError("preflight seal changed")
    else:
        core._atomic_json_once(path, value)
    seal_mtime = path.stat().st_mtime_ns
    if any(
        _checkpoint_path(output, pair_id).stat().st_mtime_ns > seal_mtime
        for pair_id in plan["preflight_pair_ids"]
    ) or any(
        _checkpoint_path(output, pair_id).stat().st_mtime_ns < seal_mtime
        for pair_id in set(checkpoints) - set(plan["preflight_pair_ids"])
    ):
        raise RuntimeError("preflight/main checkpoint write ordering changed")
    return value


def _paired_rows(checkpoints: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for pair_id in sorted(checkpoints):
        checkpoint = checkpoints[pair_id]
        indexed = {row["allocator"]: row for row in checkpoint["rows"]}
        pair = checkpoint["pair_spec"]
        config = pair["config"]
        legacy = indexed[LEGACY_ALLOCATOR]
        maxmin = indexed[MAXMIN_ALLOCATOR]
        legacy_time = float(legacy["completion_time_s"])
        maxmin_time = float(maxmin["completion_time_s"])
        ratio = maxmin_time / legacy_time
        rows.append(
            {
                "pair_id": pair_id,
                "arm_id": config["arm_id"],
                "arm_index": int(pair["arm_index"]),
                "sample_index": int(pair["sample_index"]),
                "sample_id": int(pair["sample_id"]),
                "fabric": config["fabric"],
                "ring_size": int(config["ring_size"]),
                "k": int(config["k"]),
                "link_local_time_s": legacy_time,
                "network_maxmin_time_s": maxmin_time,
                "network_over_link_local": ratio,
                "log_network_over_link_local": math.log(ratio),
                "network_minus_link_local_s": maxmin_time - legacy_time,
                "network_minus_link_local_ticks": int(maxmin["simulated_ticks"])
                - int(legacy["simulated_ticks"]),
            }
        )
    return rows


def _bootstrap_indexes(seed_count: int, expected_sha256: str) -> np.ndarray:
    rng = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED))
    indices = rng.integers(
        0, seed_count, size=(BOOTSTRAP_REPLICATES, seed_count), dtype=np.uint32
    ).astype("<u4", copy=False)
    index_sha256 = hashlib.sha256(indices.tobytes(order="C")).hexdigest()
    if index_sha256 != expected_sha256:
        raise RuntimeError("bootstrap index matrix digest changed")
    return indices


def _bootstrap_values(seed_log_values: Sequence[float], indices: np.ndarray) -> Dict[str, Any]:
    values = np.asarray(seed_log_values, dtype=np.float64)
    if values.shape != (indices.shape[1],) or not np.isfinite(values).all():
        raise RuntimeError("bootstrap cluster/value shape changed")
    replicates = np.empty(BOOTSTRAP_REPLICATES, dtype=np.float64)
    for start in range(0, BOOTSTRAP_REPLICATES, 250):
        stop = min(start + 250, BOOTSTRAP_REPLICATES)
        replicates[start:stop] = np.exp(values[indices[start:stop]].mean(axis=1))
    low, high = np.quantile(replicates, [0.025, 0.975], method="linear")
    return {
        "point_estimate": math.exp(float(values.mean())),
        "ci95_low": float(low),
        "ci95_high": float(high),
    }


def _tick_class(delta_ticks: int) -> str:
    if delta_ticks <= -2:
        return "maxmin_faster_by_2plus"
    if delta_ticks == 0:
        return "exact_tie"
    if delta_ticks in (-1, 1):
        return "one_tick_tie"
    return "maxmin_slower_by_2plus"


def _descriptive(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    ratios = np.asarray(
        [float(row["network_over_link_local"]) for row in rows], dtype=np.float64
    )
    delta_s = np.asarray(
        [
            float(
                row.get(
                    "network_minus_link_local_s",
                    float(row["network_maxmin_time_s"])
                    - float(row["link_local_time_s"]),
                )
            )
            for row in rows
        ],
        dtype=np.float64,
    )
    delta_ticks = np.asarray(
        [int(row["network_minus_link_local_ticks"]) for row in rows], dtype=np.int64
    )
    classes = Counter(_tick_class(int(value)) for value in delta_ticks)
    return {
        "pair_count": len(rows),
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
        "tick_counts": {
            name: int(classes.get(name, 0))
            for name in (
                "maxmin_faster_by_2plus",
                "exact_tie",
                "one_tick_tie",
                "maxmin_slower_by_2plus",
            )
        },
    }


def _domain_analysis(
    rows: Sequence[Mapping[str, Any]],
    seed_ids: Sequence[int],
    expected_index_sha256: str,
) -> Dict[str, Any]:
    by_seed: Dict[int, List[Mapping[str, Any]]] = defaultdict(list)
    by_arm: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_seed[int(row["sample_id"])].append(row)
        by_arm[str(row["arm_id"])].append(row)
    seeds = list(seed_ids)
    if (
        sorted(by_seed) != seeds
        or {len(group) for group in by_seed.values()} != {ARM_COUNT}
        or len(by_arm) != ARM_COUNT
        or {len(group) for group in by_arm.values()} != {len(seeds)}
    ):
        raise RuntimeError("analysis seed/arm bijection changed")
    indices = _bootstrap_indexes(len(seeds), expected_index_sha256)
    seed_logs = [
        sum(float(row["log_network_over_link_local"]) for row in by_seed[seed])
        / ARM_COUNT
        for seed in seeds
    ]
    global_bootstrap = _bootstrap_values(seed_logs, indices)
    total_log = sum(float(row["log_network_over_link_local"]) for row in rows)
    loo = []
    for seed in seeds:
        removed = sum(
            float(row["log_network_over_link_local"]) for row in by_seed[seed]
        )
        loo.append(math.exp((total_log - removed) / (len(rows) - ARM_COUNT)))
    point = global_bootstrap["point_estimate"]
    single_seed_dependence = (
        any(value >= 1.0 for value in loo)
        if point < 1.0
        else any(value <= 1.0 for value in loo)
        if point > 1.0
        else False
    )
    per_arm: Dict[str, Any] = {}
    for arm_id in sorted(by_arm):
        arm_rows = sorted(by_arm[arm_id], key=lambda item: int(item["sample_id"]))
        per_arm[arm_id] = {
            **_descriptive(arm_rows),
            **_bootstrap_values(
                [float(row["log_network_over_link_local"]) for row in arm_rows],
                indices,
            ),
            "descriptive_only": True,
            "multiplicity_adjusted": False,
        }
    del indices
    return {
        "estimand": "T_network_maxmin/T_link_local",
        "global": {
            **_descriptive(rows),
            **global_bootstrap,
            "cluster_count": len(seeds),
            "pairs_per_cluster": ARM_COUNT,
            "bootstrap_replicates": BOOTSTRAP_REPLICATES,
            "bootstrap_rng": f"PCG64({BOOTSTRAP_SEED})",
            "bootstrap_index_sha256": expected_index_sha256,
        },
        "per_arm": per_arm,
        "leave_one_seed_out": {
            "minimum": min(loo),
            "maximum": max(loo),
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
    return -1 if point < 1.0 else 1 if point > 1.0 else 0


def _arm_export(domain: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [
        {
            "arm_id": arm_id,
            "pair_count": values["pair_count"],
            "geometric_mean_ratio": values["geometric_mean_ratio"],
            "ci95_low": values["ci95_low"],
            "ci95_high": values["ci95_high"],
        }
        for arm_id, values in sorted(domain["per_arm"].items())
    ]


def _analysis(
    checkpoints: Mapping[str, Mapping[str, Any]], refs: Mapping[str, Any]
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    extension = _paired_rows(checkpoints)
    expected_extension_ids = _expected_pair_ids(SAMPLE_IDS)
    if [row["pair_id"] for row in extension] != expected_extension_ids:
        raise RuntimeError("extension analysis pair order/bijection changed")
    old = list(refs["rows"])
    by_id = {row["pair_id"]: row for row in [*old, *extension]}
    combined_ids = _expected_pair_ids(range(1000))
    if len(by_id) != COMBINED_PAIR_COUNT or [pair_id for pair_id in combined_ids if pair_id not in by_id]:
        raise RuntimeError("combined compact/extension bijection changed")
    combined = [by_id[pair_id] for pair_id in combined_ids]
    if _pair_id_digest([row["pair_id"] for row in combined]) != EXPECTED_COMBINED_PAIR_IDS_SHA256:
        raise RuntimeError("combined canonical arm-major pair order changed")
    sensitivity_seeds = [
        seed for seed in SAMPLE_IDS if seed not in EXPOSED_SEED_CLUSTERS
    ]
    sensitivity_rows = [
        row
        for row in extension
        if int(row["sample_id"]) not in EXPOSED_SEED_CLUSTERS
    ]
    primary = _domain_analysis(
        extension, list(SAMPLE_IDS), EXPECTED_BOOTSTRAP_SHA256["extension_primary"]
    )
    sensitivity = _domain_analysis(
        sensitivity_rows,
        sensitivity_seeds,
        EXPECTED_BOOTSTRAP_SHA256["extension_exposure_sensitivity"],
    )
    secondary = _domain_analysis(
        combined, list(range(1000)), EXPECTED_BOOTSTRAP_SHA256["combined_secondary"]
    )
    primary_global = primary["global"]
    sensitivity_global = sensitivity["global"]
    secondary_global = secondary["global"]
    overlap_pair_ids = sorted(
        {
            "a055_proportional_3tier_nb_p64_k8__s199",
            "a055_proportional_3tier_nb_p64_k8__s657",
            "a071_proportional_3tier_os4_p64_k8__s174",
            "a071_proportional_3tier_os4_p64_k8__s353",
            "a072_proportional_3tier_os4_p64_k16__s174",
            "a072_proportional_3tier_os4_p64_k16__s353",
        }
    )
    value = {
        "schema": "corrected-proportional-n1000-extension-analysis-v1",
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
            "excluded_seed_ids": sorted(EXPOSED_SEED_CLUSTERS),
            "excluded_seed_cluster_count": len(EXPOSED_SEED_CLUSTERS),
            "prior_sentinel_overlap_pair_ids": overlap_pair_ids,
            "prior_sentinel_overlap_pair_count": len(overlap_pair_ids),
            "interpretation": "conditional_on_fixed_32_arm_matrix_simulator_and_rate_model",
            "comparison_to_primary": {
                "primary_directional_label": _ci_direction(primary_global),
                "sensitivity_directional_label": _ci_direction(sensitivity_global),
                "point_estimate_delta": sensitivity_global["point_estimate"]
                - primary_global["point_estimate"],
                "point_estimate_ratio": sensitivity_global["point_estimate"]
                / primary_global["point_estimate"],
                "ci95_low_delta": sensitivity_global["ci95_low"]
                - primary_global["ci95_low"],
                "ci95_high_delta": sensitivity_global["ci95_high"]
                - primary_global["ci95_high"],
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
    return value, extension, _arm_export(primary), _arm_export(secondary)


def _flat_result_rows(checkpoints: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    flat: List[Dict[str, Any]] = []
    for pair_id in sorted(checkpoints):
        checkpoint = checkpoints[pair_id]
        pair = checkpoint["pair_spec"]
        config = pair["config"]
        for row in sorted(checkpoint["rows"], key=lambda item: item["execution_position"]):
            conservation = row["conservation"]
            flat.append(
                {
                    "pair_id": pair_id,
                    "arm_id": config["arm_id"],
                    "arm_index": pair["arm_index"],
                    "sample_index": pair["sample_index"],
                    "sample_id": pair["sample_id"],
                    "fabric": config["fabric"],
                    "ring_size": config["ring_size"],
                    "k": config["k"],
                    "allocator": row["allocator"],
                    "execution_position": row["execution_position"],
                    "completion_time_s": repr(row["completion_time_s"]),
                    "completion_time_hex": row["completion_time_hex"],
                    "simulated_ticks": row["simulated_ticks"],
                    "config_sha256": row["config_sha256"],
                    "topology_sha256": row["topology_sha256"],
                    "ring_sha256": row["ring_sha256"],
                    "route_sha256": row["route_sha256"],
                    "process_initial_sha256": row["process_initial_sha256"],
                    "conservation_max_error_B": repr(conservation["maximum_abs_error_bytes"]),
                    "conservation_remaining_B": repr(conservation["remaining_foreground_bytes"]),
                    "remaining_nonzero_count": conservation["foreground_remaining_nonzero_count"],
                    "campaign_use": "extension_primary_validation",
                }
            )
    return flat


def _csv_bytes(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(fields), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing to write empty CSV: {path}")
    core._atomic_write_once(path, _csv_bytes(rows, list(rows[0].keys())))


def _cleanup_staging(output: Path) -> None:
    for directory in (output / "checkpoints", output / "timing_segments", output):
        staging = directory / ".staging"
        if staging.exists():
            if any(staging.iterdir()):
                raise RuntimeError(f"non-empty atomic staging directory: {staging}")
            staging.rmdir()


def _inventory(
    output: Path, run_lock: core.ExclusiveRunLock, *, exclude: Sequence[str]
) -> Dict[str, Dict[str, Any]]:
    excluded = set(exclude)
    artifacts: Dict[str, Dict[str, Any]] = {}
    for path in sorted(output.rglob("*"), key=lambda item: item.relative_to(output).as_posix()):
        if not path.is_file():
            continue
        relative = path.relative_to(output).as_posix()
        if relative in excluded:
            continue
        artifacts[relative] = (
            _held_lock_metadata(path, run_lock)
            if relative == ".run.lock"
            else _file_metadata(path)
        )
    return artifacts


def _runtime(segments: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    pair_ids = [pair_id for segment in segments for pair_id in segment["pair_ids"]]
    if len(pair_ids) != PAIR_COUNT or len(set(pair_ids)) != PAIR_COUNT:
        raise RuntimeError("timing segments do not cover the full extension exactly once")
    total_wall = sum(float(segment["elapsed_pool_wall_s"]) for segment in segments)
    return {
        "schema": "corrected-proportional-n1000-extension-runtime-v1",
        "segment_count": len(segments),
        "pair_count": len(pair_ids),
        "total_wall_s": total_wall,
        "pool_wall_sum_s": total_wall,
        "worker_simulation_wall_sum_s": sum(
            float(segment["worker_simulation_wall_sum_s"]) for segment in segments
        ),
        "worker_end_to_end_wall_sum_s": sum(
            float(segment["worker_end_to_end_wall_sum_s"]) for segment in segments
        ),
        "recovered_segment_count": sum(bool(segment["recovered_after_interruption"]) for segment in segments),
        "timing_is_operational_not_scientific": True,
    }


def _immutable_after(manifest: Mapping[str, Any], output: Path) -> Dict[str, Any]:
    current = _immutable_snapshot(allowed_output=output)
    before = manifest["immutable_before"]
    for key in (
        "sources",
        "source_sha256",
        "n100_reference",
        "n100_reference_sha256",
        "exposure_provenance_only",
    ):
        if current[key] != before[key]:
            raise RuntimeError(f"immutable {key} changed during execution")
    if current["git"]["execution_head"] != before["git"]["execution_head"]:
        raise RuntimeError("execution HEAD changed during campaign")
    return copy.deepcopy(dict(before))


def _finalize(
    output: Path,
    plan: Mapping[str, Any],
    checkpoints: Mapping[str, Mapping[str, Any]],
    refs: Mapping[str, Any],
    manifest: Mapping[str, Any],
    segments: Sequence[Mapping[str, Any]],
    run_lock: core.ExclusiveRunLock,
) -> Dict[str, Any]:
    if len(checkpoints) != PAIR_COUNT:
        raise RuntimeError("finalization requires all 28,800 checkpoints")
    analysis, pairs, arm_rows, combined_arm_rows = _analysis(checkpoints, refs)
    _write_csv(output / "results_long.csv", _flat_result_rows(checkpoints))
    _write_csv(output / "pairs.csv", pairs)
    _write_csv(output / "arm_analysis.csv", arm_rows)
    _write_csv(output / "combined_arm_analysis.csv", combined_arm_rows)
    core._atomic_json_once(output / "analysis.json", analysis)
    runtime = _runtime(segments)
    core._atomic_json_once(output / "runtime.json", runtime)
    immutable_after = _immutable_after(manifest, output)
    gate = {
        "schema": "corrected-proportional-n1000-extension-gate-v1",
        "passed": True,
        "plan_sha256": plan["plan_sha256"],
        "pair_count": PAIR_COUNT,
        "row_count": SIMULATION_COUNT,
        "simulation_count": SIMULATION_COUNT,
        "primary_domain": "extension_only_seeds_100_999",
        "secondary_domain": "combined_seeds_0_999",
        "primary_scope": analysis["analysis_role"],
        "sensitivity_excluded_seed_clusters": sorted(EXPOSED_SEED_CLUSTERS),
        "secondary_is_not_primary": True,
        "fixed_sample_no_effect_based_stopping": True,
        "all_conservation_checks_passed": True,
        "n100_canonical_config_hashes_recomputed": True,
        "legacy_v11_or_sentinel_used_as_estimator_input": False,
        "paper_change_authorized": False,
        "decision": analysis["decision"]["status"],
        "next_status": "PENDING_INDEPENDENT_AUDIT_AND_RESEARCH_DECISION",
    }
    core._atomic_json_once(output / "gate.json", gate)
    _cleanup_staging(output)
    _verify_root_names(output)
    _verify_directory_inventory(output, require_complete=True)
    required_without_completion = (
        PARTIAL_ROOT_NAMES | FINAL_EXPORT_NAMES
    )
    names = {path.name for path in output.iterdir()}
    if names != required_without_completion:
        raise RuntimeError(f"pre-completion root inventory changed: {sorted(names)}")
    artifacts = _inventory(
        output, run_lock, exclude=("completion_manifest.json", "COMPLETE.json")
    )
    completion = {
        "schema": "corrected-proportional-n1000-extension-completion-v1",
        "status": "COMPLETE_PENDING_INDEPENDENT_AUDIT_AND_RESEARCH_DECISION",
        "plan_sha256": plan["plan_sha256"],
        "pair_count": PAIR_COUNT,
        "simulation_count": SIMULATION_COUNT,
        "combined_pair_count": COMBINED_PAIR_COUNT,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "analysis_sha256": _sha256_file(output / "analysis.json"),
        "gate": gate,
        "runtime": runtime,
        "immutable_after": immutable_after,
        "completion_manifest_excludes_itself_and_complete": True,
        "completion_manifest_self_signed": False,
        "complete_file_self_signed": False,
        "run_lock_hashed_via_held_handle": True,
    }
    core._atomic_json_once(output / "completion_manifest.json", completion)
    _cleanup_staging(output)
    complete = {
        "schema": "corrected-proportional-n1000-extension-complete-v1",
        "status": completion["status"],
        "plan_sha256": plan["plan_sha256"],
        "completion_manifest_sha256": _sha256_file(output / "completion_manifest.json"),
        "completion_manifest_bytes": (output / "completion_manifest.json").stat().st_size,
        "run_manifest_sha256": _sha256_file(output / "run_manifest.json"),
        "run_manifest_bytes": (output / "run_manifest.json").stat().st_size,
        "written_last": True,
    }
    core._atomic_json_once(output / "COMPLETE.json", complete)
    _cleanup_staging(output)
    if {path.name for path in output.iterdir()} != FINAL_ROOT_NAMES:
        raise RuntimeError("final root allowlist mismatch")
    return complete


def _validate_completion_manifest(
    output: Path,
    manifest: Mapping[str, Any],
    run_lock: core.ExclusiveRunLock,
) -> Dict[str, Any]:
    completion_path = output / "completion_manifest.json"
    if not completion_path.is_file():
        raise RuntimeError("completion manifest is missing")
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    inventory = _inventory(
        output, run_lock, exclude=("completion_manifest.json", "COMPLETE.json")
    )
    gate = json.loads((output / "gate.json").read_text(encoding="utf-8"))
    runtime = json.loads((output / "runtime.json").read_text(encoding="utf-8"))
    analysis = json.loads((output / "analysis.json").read_text(encoding="utf-8"))
    analysis_status = analysis.get("decision", {}).get("status")
    if (
        completion.get("schema")
        != "corrected-proportional-n1000-extension-completion-v1"
        or completion.get("status")
        != "COMPLETE_PENDING_INDEPENDENT_AUDIT_AND_RESEARCH_DECISION"
        or completion.get("plan_sha256") != manifest["plan_sha256"]
        or int(completion.get("pair_count", -1)) != PAIR_COUNT
        or int(completion.get("simulation_count", -1)) != SIMULATION_COUNT
        or int(completion.get("combined_pair_count", -1)) != COMBINED_PAIR_COUNT
        or completion.get("completion_manifest_self_signed") is not False
        or completion.get("complete_file_self_signed") is not False
        or completion.get("completion_manifest_excludes_itself_and_complete") is not True
        or completion.get("run_lock_hashed_via_held_handle") is not True
        or completion.get("artifacts") != inventory
        or int(completion.get("artifact_count", -1)) != len(inventory)
        or completion.get("analysis_sha256") != _sha256_file(output / "analysis.json")
        or completion.get("gate") != gate
        or completion.get("runtime") != runtime
        or completion.get("immutable_after") != manifest["immutable_before"]
        or gate.get("schema") != "corrected-proportional-n1000-extension-gate-v1"
        or gate.get("passed") is not True
        or gate.get("primary_domain") != "extension_only_seeds_100_999"
        or gate.get("secondary_domain") != "combined_seeds_0_999"
        or gate.get("decision") != analysis_status
        or int(gate.get("pair_count", -1)) != PAIR_COUNT
        or int(gate.get("row_count", -1)) != SIMULATION_COUNT
        or runtime.get("schema")
        != "corrected-proportional-n1000-extension-runtime-v1"
        or int(runtime.get("pair_count", -1)) != PAIR_COUNT
        or analysis.get("schema")
        != "corrected-proportional-n1000-extension-analysis-v1"
        or analysis.get("primary_domain") != "extension_only_seeds_100_999"
        or analysis.get("secondary_domain") != "combined_seeds_0_999"
        or analysis_status != "PENDING_INDEPENDENT_AUDIT_AND_RESEARCH_DECISION"
        or int(analysis.get("extension_primary", {}).get("global", {}).get("pair_count", -1))
        != PAIR_COUNT
        or int(analysis.get("combined_secondary", {}).get("global", {}).get("pair_count", -1))
        != COMBINED_PAIR_COUNT
        or int(
            analysis.get("sentinel_excluded_sensitivity", {})
            .get("global", {})
            .get("pair_count", -1)
        )
        != (PAIR_COUNT - len(EXPOSED_SEED_CLUSTERS) * ARM_COUNT)
    ):
        raise RuntimeError("completion manifest payload changed")
    return completion


def _verify_complete(
    output: Path, manifest: Mapping[str, Any], run_lock: core.ExclusiveRunLock
) -> Dict[str, Any]:
    _cleanup_staging(output)
    _verify_root_names(output)
    _verify_directory_inventory(output, require_complete=True)
    complete_path = output / "COMPLETE.json"
    completion_path = output / "completion_manifest.json"
    if not complete_path.is_file() or not completion_path.is_file():
        raise RuntimeError("complete verification requires both completion files")
    complete = json.loads(complete_path.read_text(encoding="utf-8"))
    completion = _validate_completion_manifest(output, manifest, run_lock)
    if (
        complete.get("schema") != "corrected-proportional-n1000-extension-complete-v1"
        or complete.get("status") != completion.get("status")
        or complete.get("plan_sha256") != manifest["plan_sha256"]
        or complete.get("completion_manifest_sha256") != _sha256_file(completion_path)
        or int(complete.get("completion_manifest_bytes", -1)) != completion_path.stat().st_size
        or complete.get("run_manifest_sha256") != _sha256_file(output / "run_manifest.json")
        or int(complete.get("run_manifest_bytes", -1))
        != (output / "run_manifest.json").stat().st_size
        or complete.get("written_last") is not True
        or completion.get("schema")
        != "corrected-proportional-n1000-extension-completion-v1"
        or completion.get("status")
        != "COMPLETE_PENDING_INDEPENDENT_AUDIT_AND_RESEARCH_DECISION"
        or int(completion.get("pair_count", -1)) != PAIR_COUNT
        or int(completion.get("simulation_count", -1)) != SIMULATION_COUNT
        or completion.get("plan_sha256") != manifest["plan_sha256"]
    ):
        raise RuntimeError("completion linkage changed")
    _immutable_after(manifest, output)
    return complete


def _resume_completion_only(
    output: Path, manifest: Mapping[str, Any], run_lock: core.ExclusiveRunLock
) -> Dict[str, Any]:
    completion_path = output / "completion_manifest.json"
    if not completion_path.is_file() or (output / "COMPLETE.json").exists():
        raise RuntimeError("not a completion-manifest-only crash state")
    _cleanup_staging(output)
    if {path.name for path in output.iterdir()} != FINAL_ROOT_NAMES - {"COMPLETE.json"}:
        raise RuntimeError("completion-manifest-only state has arbitrary root artifacts")
    _verify_directory_inventory(output, require_complete=True)
    completion = _validate_completion_manifest(output, manifest, run_lock)
    _immutable_after(manifest, output)
    complete = {
        "schema": "corrected-proportional-n1000-extension-complete-v1",
        "status": completion["status"],
        "plan_sha256": manifest["plan_sha256"],
        "completion_manifest_sha256": _sha256_file(completion_path),
        "completion_manifest_bytes": completion_path.stat().st_size,
        "run_manifest_sha256": _sha256_file(output / "run_manifest.json"),
        "run_manifest_bytes": (output / "run_manifest.json").stat().st_size,
        "written_last": True,
    }
    core._atomic_json_once(output / "COMPLETE.json", complete)
    _cleanup_staging(output)
    if {path.name for path in output.iterdir()} != FINAL_ROOT_NAMES:
        raise RuntimeError("completion-only resume final root inventory changed")
    _verify_directory_inventory(output, require_complete=True)
    return complete


def _new_manifest(
    plan: Mapping[str, Any],
    output: Path,
    workers: int,
    immutable: Mapping[str, Any],
    authorization: str,
) -> Dict[str, Any]:
    git_before = immutable["git"]
    value: Dict[str, Any] = {
        "schema": "corrected-proportional-n1000-extension-run-v1",
        "created_utc": _utc_now(),
        "output": str(output),
        "workers": workers,
        "plan": plan,
        "plan_sha256": plan["plan_sha256"],
        "authorization_sha256": authorization,
        "driver_sha256": immutable["sources"][
            DRIVER_PATH.relative_to(ROOT).as_posix()
        ],
        "baseline_ancestor": BASELINE_COMMIT,
        "git": {
            "head": git_before["execution_head"],
            "dirty": False,
            "upstream": git_before["upstream"],
            "ahead": 0,
            "behind": 0,
        },
        "immutable_before": immutable,
        "platform": platform.platform(),
        "python": sys.version,
        "multiprocessing_start_method": "spawn",
        "execution_phases": ["preflight_64", "remaining_28736"],
        "preflight_is_integrity_only": True,
        "fixed_sample_no_adaptive_stopping": True,
        "checkpoint_policy": "one atomic parent-written JSON per paired checkpoint",
        "output_contract": {
            "partial_root_names": sorted(PARTIAL_ROOT_NAMES),
            "final_root_names": sorted(FINAL_ROOT_NAMES),
            "checkpoints_create_once": True,
            "timing_segments_create_once": True,
            "completion_manifest_only_crash_state_is_resumable": True,
        },
    }
    value["manifest_payload_sha256"] = _digest(value)
    return value


def _verify_manifest(
    manifest: Mapping[str, Any], plan: Mapping[str, Any], output: Path
) -> None:
    unsigned = copy.deepcopy(dict(manifest))
    recorded = unsigned.pop("manifest_payload_sha256", None)
    immutable = manifest.get("immutable_before")
    if (
        manifest.get("schema") != "corrected-proportional-n1000-extension-run-v1"
        or not isinstance(immutable, Mapping)
        or not isinstance(recorded, str)
        or _digest(unsigned) != recorded
        or manifest.get("plan") != plan
        or manifest.get("plan_sha256") != plan["plan_sha256"]
        or Path(str(manifest.get("output", ""))).resolve() != output
        or manifest.get("baseline_ancestor") != BASELINE_COMMIT
        or manifest.get("checkpoint_policy")
        != "one atomic parent-written JSON per paired checkpoint"
        or manifest.get("driver_sha256")
        != immutable.get("sources", {}).get(
            DRIVER_PATH.relative_to(ROOT).as_posix()
        )
    ):
        raise RuntimeError("run manifest payload/provenance changed")
    workers = int(manifest.get("workers", 0))
    if not 1 <= workers <= MAX_WORKERS:
        raise RuntimeError("run manifest worker count is invalid")
    expected_authorization = _authorization(plan, output, workers, immutable)
    if manifest.get("authorization_sha256") != expected_authorization:
        raise RuntimeError("run manifest authorization changed")


def execute_or_resume(
    plan: Mapping[str, Any],
    output: Path,
    *,
    workers: Optional[int],
    resume: bool,
    confirmed_authorization: Optional[str] = None,
    preflight_only: bool = False,
) -> Dict[str, Any]:
    _verify_plan(plan)
    output = _validate_output(str(output), require_absent=not resume)
    _configure_core()
    if not resume:
        if workers is None or not 1 <= int(workers) <= MAX_WORKERS:
            raise RuntimeError(f"fresh execution requires 1..{MAX_WORKERS} workers")
        immutable = _immutable_snapshot(allowed_output=None)
        authorization = _authorization(plan, output, int(workers), immutable)
        if confirmed_authorization != authorization:
            raise RuntimeError("dry-run authorization changed before output creation")
        if shutil.disk_usage(ROOT).free < CONSERVATIVE_PROJECTED_OUTPUT_BYTES * 2:
            raise RuntimeError("insufficient free disk before output creation")
        _path_length_gate(output)
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        output.mkdir(exist_ok=False)
        (output / "checkpoints").mkdir()
        (output / "timing_segments").mkdir()

    with core.ExclusiveRunLock(output / ".run.lock") as run_lock:
        manifest_path = output / "run_manifest.json"
        if resume:
            if not manifest_path.is_file():
                raise RuntimeError("resume requires run_manifest.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                manifest.get("schema") != "corrected-proportional-n1000-extension-run-v1"
                or manifest.get("plan") != plan
                or Path(manifest.get("output", "")).resolve() != output
                or not 1 <= int(manifest.get("workers", 0)) <= MAX_WORKERS
            ):
                raise RuntimeError("resume manifest differs from fixed campaign")
            _verify_manifest(manifest, plan, output)
            _immutable_after(manifest, output)
            if (output / "COMPLETE.json").exists():
                return _verify_complete(output, manifest, run_lock)
            if (output / "completion_manifest.json").exists():
                return _resume_completion_only(output, manifest, run_lock)
        else:
            assert workers is not None and confirmed_authorization is not None
            manifest = _new_manifest(
                plan, output, int(workers), immutable, confirmed_authorization
            )
            _verify_manifest(manifest, plan, output)
            core._atomic_json_once(manifest_path, manifest)

        _verify_root_names(output)
        _verify_directory_inventory(output, require_complete=False)
        refs = _verify_n100_reference()
        checkpoints = _existing_checkpoints(output, plan)
        segments = _load_timing(output, checkpoints)
        preflight_ids = set(plan["preflight_pair_ids"])
        if set(checkpoints) - preflight_ids and not (output / "preflight_complete.json").is_file():
            raise RuntimeError("non-preflight checkpoints exist without preflight seal")
        preflight_pending = [
            pair for pair in plan["pairs"]
            if pair["pair_id"] in preflight_ids and pair["pair_id"] not in checkpoints
        ]
        _run_phase(
            preflight_pending,
            phase="preflight_64",
            output=output,
            plan=plan,
            manifest=manifest,
            checkpoints=checkpoints,
            segment_index=len(segments) + 1,
        )
        checkpoints = _existing_checkpoints(output, plan)
        segments = _load_timing(output, checkpoints)
        _write_or_verify_preflight(output, plan, checkpoints, manifest)
        if preflight_only:
            if set(checkpoints) - preflight_ids:
                raise RuntimeError("--preflight-only is invalid after main-phase work exists")
            preflight_segments = [
                segment
                for segment in segments
                if set(segment["pair_ids"]) <= preflight_ids
            ]
            if {
                pair_id
                for segment in preflight_segments
                for pair_id in segment["pair_ids"]
            } != preflight_ids:
                raise RuntimeError("preflight ETA lacks exact timing coverage")
            preflight_wall = sum(
                float(segment["elapsed_pool_wall_s"])
                for segment in preflight_segments
            )
            pairs_per_s = PREFLIGHT_PAIR_COUNT / preflight_wall
            return {
                "status": "PREFLIGHT_COMPLETE_READY_TO_RESUME",
                "pair_count": PREFLIGHT_PAIR_COUNT,
                "output": str(output),
                "preflight_pool_wall_s": preflight_wall,
                "observed_pairs_per_s": pairs_per_s,
                "projected_remaining_minutes": (
                    (PAIR_COUNT - PREFLIGHT_PAIR_COUNT) / pairs_per_s / 60.0
                ),
                "eta_role": "operational_projection_not_scientific_result",
            }
        pending = [pair for pair in plan["pairs"] if pair["pair_id"] not in checkpoints]
        _run_phase(
            pending,
            phase="remaining_28736",
            output=output,
            plan=plan,
            manifest=manifest,
            checkpoints=checkpoints,
            segment_index=len(segments) + 1,
        )
        checkpoints = _existing_checkpoints(output, plan)
        segments = _load_timing(output, checkpoints)
        return _finalize(output, plan, checkpoints, refs, manifest, segments, run_lock)


def dry_run(plan: Mapping[str, Any], output: Path, workers: int) -> Dict[str, Any]:
    _verify_plan(plan)
    output = _validate_output(str(output), require_absent=True)
    if not 1 <= workers <= MAX_WORKERS:
        raise RuntimeError(f"workers must be 1..{MAX_WORKERS}")
    immutable = _immutable_snapshot(allowed_output=None)
    disk_free = shutil.disk_usage(ROOT).free
    if disk_free < CONSERVATIVE_PROJECTED_OUTPUT_BYTES * 2:
        raise RuntimeError("insufficient free disk for conservative campaign projection")
    authorization = _authorization(plan, output, workers, immutable)
    path_gate = _path_length_gate(output)
    value = {
        "schema": "corrected-proportional-n1000-extension-dry-run-v1",
        "execution_writes_performed": False,
        "output": str(output),
        "workers": workers,
        "plan_sha256": plan["plan_sha256"],
        "arm_count": ARM_COUNT,
        "pair_count": PAIR_COUNT,
        "simulation_count": SIMULATION_COUNT,
        "preflight_pair_count": PREFLIGHT_PAIR_COUNT,
        "storage_gate": {
            "passed": True,
            "free_bytes": disk_free,
            "conservative_projected_output_bytes": CONSERVATIVE_PROJECTED_OUTPUT_BYTES,
            "required_headroom_multiplier": 2,
        },
        "path_length_gate": path_gate,
        "authorization_sha256": authorization,
        "immutable_before": immutable,
        "command": (
            f'python "{DRIVER_PATH}" --run --output "{output}" '
            f"--workers {workers} --confirm {authorization}"
        ),
    }
    print(json.dumps(value, indent=2, sort_keys=True))
    return value


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--resume", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--confirm")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    if args.dry_run and (args.workers is None or args.confirm or args.preflight_only):
        parser.error("--dry-run requires --workers and rejects --confirm/--preflight-only")
    if args.run and (args.workers is None or not args.confirm):
        parser.error("--run requires --workers and --confirm")
    if args.resume and (args.workers is not None or args.confirm):
        parser.error("--resume rejects --workers and --confirm")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    plan = build_plan()
    output = Path(args.output)
    if args.dry_run:
        dry_run(plan, output, args.workers)
    else:
        result = execute_or_resume(
            plan,
            output,
            workers=args.workers,
            resume=args.resume,
            confirmed_authorization=args.confirm,
            preflight_only=args.preflight_only,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
