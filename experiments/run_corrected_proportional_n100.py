"""Corrected proportional-only paired n=100 revalidation.

This sidecar filters the sealed canonical n=100 plan to its 32 proportional
arms, runs both rate allocators through the existing paired production worker,
and writes only below ``investigations/corrected_proportional_n100``.  The old
proportional outcomes are diagnostics, never an oracle.  This module has no
n=1000 execution mode.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import multiprocessing as mp
import numbers
import os
import platform
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS_DIR = ROOT / "experiments"
for path in (ROOT, EXPERIMENTS_DIR):
    if str(path) in sys.path:
        sys.path.remove(str(path))
    sys.path.insert(0, str(path))

import run_rate_allocator_n100 as canonical  # noqa: E402
import run_rate_allocator_pilot as core  # noqa: E402
import sim  # noqa: E402


DRIVER_PATH = Path(__file__).resolve()
CANONICAL_DRIVER_PATH = Path(canonical.__file__).resolve()
CORE_DRIVER_PATH = Path(core.__file__).resolve()
SIM_PATH = ROOT / "sim.py"
SPEC_PATH = ROOT / "investigations" / "CORRECTED_PROPORTIONAL_N100_SPEC_2026_08_07.md"
OUTPUT_ROOT = (ROOT / "investigations" / "corrected_proportional_n100").resolve()
HISTORICAL_ROOT = (
    ROOT / "investigations" / "rate_allocator_n100" / "n100_2026-08-06_03"
).resolve()
AUDIT_V2_ROOT = (
    ROOT
    / "investigations"
    / "proportional_mechanism_audit_v2"
    / "audit_v2_2026-08-07_01"
).resolve()
AUDIT_V1_ROOT = (
    ROOT
    / "investigations"
    / "proportional_mechanism_audit"
    / "audit_2026-08-07_01"
).resolve()
HISTORICAL_COMPLETE_PATH = HISTORICAL_ROOT / "COMPLETE.json"
AUDIT_V2_COMPLETE_PATH = AUDIT_V2_ROOT / "COMPLETE.json"
AUDIT_V1_COMPLETE_PATH = AUDIT_V1_ROOT / "COMPLETE.json"
AUDIT_V2_EQUIVALENCE_PATH = AUDIT_V2_ROOT / "production_equivalence.json"

SAMPLE_IDS = tuple(range(100))
ALLOCATORS = (sim.RATE_ALLOCATOR_LINK_LOCAL, sim.RATE_ALLOCATOR_NETWORK_MAXMIN)
LEGACY_ALLOCATOR = sim.RATE_ALLOCATOR_LINK_LOCAL
MAXMIN_ALLOCATOR = sim.RATE_ALLOCATOR_NETWORK_MAXMIN
PAIR_COUNT = 3_200
SIMULATION_COUNT = 6_400
ARM_COUNT = 32
PREFLIGHT_ANCHOR_PAIR_ID = "a079_proportional_2tier_p64_k8__s066"
EXPECTED_PAIR_ID_SHA256 = (
    "72c14abfa494a0896b79aa75abf5d8071e6697f14e2e323963a869a62bda31da"
)
EXPECTED_CANONICAL_PLAN_SHA256 = (
    "47099eedb41d1574cc49a6e08a2f7bb20b6c14077531b32b80222be9519291ac"
)
EXPECTED_FROZEN_ROOT_SHA256 = (
    "09a1418e965b9c2d597721ff0d3b1e8db937a19ce667accfa2cf1f469664c24e"
)
EXPECTED_SOURCE_HASHES = {
    SIM_PATH: "96505cefe2e5aa761b80080d77145bfd384c688ce4a8ca5792f8f7ce17ef59bd",
    CANONICAL_DRIVER_PATH: "7d01a2e598c799b0c533fb650f33b8537f51fa3187f427fcf9ada108d56fd8b4",
    CORE_DRIVER_PATH: "777018e1a408eb5274d5ee87700fc66e4396fd5d39722f625f22e48840efc431",
    SPEC_PATH: "0bfb2286b52f0dc5266c8e80a08e7d2de8e7508565e5f07b25caee8e4a508090",
}
EXPECTED_REFERENCE_HASHES = {
    AUDIT_V2_COMPLETE_PATH: "046f980e20312b2ff988ec3fd1a1185cd2df9c261acf4da61168a658661cccd9",
    AUDIT_V1_COMPLETE_PATH: "a6e4c00a80c6bfb179af68f9308e2e91e2fab8aaed6ceda10a09cbe9494419ad",
    HISTORICAL_COMPLETE_PATH: "c4caaf8bb203eff3b815236c3bc848d8d483b521571c3ab71a47a32f135eadfa",
}
BOOTSTRAP_REPLICATES = 20_000
BOOTSTRAP_SEED = 20_260_807
PRIOR_FINAL_ROOT_FILES = frozenset(
    {
        ".run.lock",
        "run_manifest.json",
        "preflight_complete.json",
        "results_long.csv",
        "pairs.csv",
        "historical_deltas.csv",
        "equal_comparison.csv",
        "leave_one_seed_out.csv",
        "arm_analysis.csv",
        "strata_analysis.csv",
        "analysis.json",
        "REPORT.md",
        "runtime.json",
        "gate.json",
        "v2_overlap.json",
    }
)
FINAL_ROOT_FILES = PRIOR_FINAL_ROOT_FILES | {
    "completion_manifest.json",
    "COMPLETE.json",
}
REQUIRED_EARLY_ROOT_FILES = frozenset(
    {".run.lock", "run_manifest.json", "preflight_complete.json"}
)

_BASE_CONSERVATION_GATE = core._conservation_gate
_WORKER_EXPECTED_HASHES: Dict[str, str] = {}


def _sha256_file(path: Path) -> str:
    return core._sha256_file(path)


def _locked_run_lock_artifact(
    path: Path, run_lock: core.ExclusiveRunLock
) -> Dict[str, Any]:
    """Hash the held run lock without reopening its locked byte on Windows."""
    try:
        expected_path = path.resolve(strict=True)
        declared_path = Path(run_lock.path).resolve(strict=True)
        handle = run_lock.handle
        handle_path = Path(handle.name).resolve(strict=True)
    except (AttributeError, OSError, TypeError) as exc:
        raise RuntimeError("run-lock handle is unavailable or invalid") from exc
    if expected_path != declared_path or expected_path != handle_path:
        raise RuntimeError("run-lock handle path differs from the expected artifact")
    if handle.closed:
        raise RuntimeError("run-lock handle is closed during artifact hashing")

    handle.flush()
    path_before = path.stat()
    handle_before = os.fstat(handle.fileno())
    if (path_before.st_dev, path_before.st_ino) != (
        handle_before.st_dev,
        handle_before.st_ino,
    ):
        raise RuntimeError("run-lock handle does not identify the expected artifact")

    original_offset = handle.tell()
    digest = hashlib.sha256()
    byte_count = 0
    try:
        handle.seek(0)
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            byte_count += len(block)
    finally:
        handle.seek(original_offset)

    path_after = path.stat()
    handle_after = os.fstat(handle.fileno())
    before_signature = (
        path_before.st_dev,
        path_before.st_ino,
        path_before.st_size,
        path_before.st_mtime_ns,
    )
    if before_signature != (
        path_after.st_dev,
        path_after.st_ino,
        path_after.st_size,
        path_after.st_mtime_ns,
    ) or before_signature != (
        handle_after.st_dev,
        handle_after.st_ino,
        handle_after.st_size,
        handle_after.st_mtime_ns,
    ):
        raise RuntimeError("run-lock artifact changed while it was being hashed")
    if byte_count != path_after.st_size:
        raise RuntimeError("run-lock artifact size changed while it was being hashed")
    return {"bytes": byte_count, "sha256": digest.hexdigest()}


def _artifact_metadata(
    path: Path, run_lock: core.ExclusiveRunLock
) -> Dict[str, Any]:
    if path.resolve(strict=True) == Path(run_lock.path).resolve(strict=True):
        return _locked_run_lock_artifact(path, run_lock)
    return {"bytes": path.stat().st_size, "sha256": _sha256_file(path)}


def _digest(value: Any) -> str:
    return core._digest(value)


def _pair_id_digest(pair_ids: Sequence[str]) -> str:
    return _digest(list(pair_ids))


def _canonical_filtered_payload() -> Dict[str, Any]:
    source = canonical.build_plan()
    if source.get("plan_sha256") != EXPECTED_CANONICAL_PLAN_SHA256:
        raise RuntimeError("canonical n=100 plan seal changed")
    pairs = [
        copy.deepcopy(pair)
        for pair in source["pairs"]
        if pair["config"].get("oracle_kind") == "proportional"
        and pair["config"].get("family") == "static_split"
        and pair["config"].get("runner") == "proportional"
        and pair["config"].get("policy") == "proportional"
    ]
    selected_arm_ids = {pair["config"]["arm_id"] for pair in pairs}
    arms = [
        copy.deepcopy(arm)
        for arm in source["arms"]
        if arm["arm_id"] in selected_arm_ids
    ]
    pair_ids = [pair["pair_id"] for pair in pairs]
    first_counts = Counter(pair["execution_order"][0] for pair in pairs)
    payload: Dict[str, Any] = {
        "schema": "corrected-proportional-n100-plan-v1",
        "source_plan_sha256": source["plan_sha256"],
        "sample_ids": list(SAMPLE_IDS),
        "allocators": list(ALLOCATORS),
        "arms": arms,
        "pairs": pairs,
        "arm_count": len(arms),
        "pair_count": len(pairs),
        "simulation_count": 2 * len(pairs),
        "pair_id_list_sha256": _pair_id_digest(pair_ids),
        "allocator_first_pair_counts": dict(sorted(first_counts.items())),
        "preflight_pair_ids": [
            pair["pair_id"]
            for pair in pairs
            if int(pair["sample_id"]) == 0 or pair["pair_id"] == PREFLIGHT_ANCHOR_PAIR_ID
        ],
        "historical_outcomes_are_diagnostic_only": True,
        "no_n1000_execution_path": True,
    }
    return payload


def build_plan() -> Dict[str, Any]:
    plan = _canonical_filtered_payload()
    pair_ids = [pair["pair_id"] for pair in plan["pairs"]]
    if (
        len(plan["arms"]) != ARM_COUNT
        or len(plan["pairs"]) != PAIR_COUNT
        or plan["simulation_count"] != SIMULATION_COUNT
        or len(set(pair_ids)) != PAIR_COUNT
        or plan["pair_id_list_sha256"] != EXPECTED_PAIR_ID_SHA256
    ):
        raise RuntimeError("corrected proportional matrix cardinality/digest changed")
    if sorted({int(pair_id[1:4]) for pair_id in pair_ids}) != list(range(49, 81)):
        raise RuntimeError("corrected proportional canonical arm identifiers changed")
    if plan["allocator_first_pair_counts"] != {
        LEGACY_ALLOCATOR: 1_600,
        MAXMIN_ALLOCATOR: 1_600,
    }:
        raise RuntimeError("full corrected proportional allocator order is unbalanced")
    if len(plan["preflight_pair_ids"]) != 33 or len(set(plan["preflight_pair_ids"])) != 33:
        raise RuntimeError("preflight is not the fixed 33-pair set")
    plan["plan_sha256"] = _digest(plan)
    return plan


def _verify_plan_integrity(plan: Mapping[str, Any]) -> str:
    recorded = str(plan.get("plan_sha256", ""))
    unsigned = copy.deepcopy(dict(plan))
    unsigned.pop("plan_sha256", None)
    if not recorded or _digest(unsigned) != recorded:
        raise RuntimeError("plan digest mismatch")
    canonical_plan = build_plan()
    if dict(plan) != canonical_plan:
        raise RuntimeError("plan is not the canonical filtered proportional matrix")
    return recorded


def _preflight_pairs(plan: Mapping[str, Any]) -> List[Dict[str, Any]]:
    _verify_plan_integrity(plan)
    expected = set(plan["preflight_pair_ids"])
    selected = [pair for pair in plan["pairs"] if pair["pair_id"] in expected]
    if len(selected) != 33 or {pair["pair_id"] for pair in selected} != expected:
        raise RuntimeError("preflight selection changed")
    return selected


def _verify_bundle_inventory(root: Path, complete_path: Path) -> Dict[str, Any]:
    complete = json.loads(complete_path.read_text(encoding="utf-8"))
    signed_names: set[str] = set()
    if "artifacts" in complete:
        for name, expected in complete["artifacts"].items():
            signed_names.add(name)
            path = root / name
            if (
                not path.is_file()
                or path.stat().st_size != int(expected["bytes"])
                or _sha256_file(path) != expected["sha256"]
            ):
                raise RuntimeError(f"sealed reference artifact changed: {path}")
    else:
        manifest = root / "completion_manifest.json"
        if _sha256_file(manifest) != complete.get("completion_manifest_sha256"):
            raise RuntimeError(f"sealed completion manifest changed: {manifest}")
        completion = json.loads(manifest.read_text(encoding="utf-8"))
        run_manifest = root / "run_manifest.json"
        if _sha256_file(run_manifest) != complete.get("run_manifest_sha256"):
            raise RuntimeError(f"sealed run manifest changed: {run_manifest}")
        signed: Dict[str, Mapping[str, Any]] = {}
        for group in ("exports", "checkpoints", "timing_segments"):
            signed.update(completion.get(group, {}))
        run_entry = completion.get("run_manifest")
        if isinstance(run_entry, Mapping):
            signed["run_manifest.json"] = run_entry
        for name, expected in signed.items():
            path = root / name
            if (
                not path.is_file()
                or path.stat().st_size != int(expected["bytes"])
                or _sha256_file(path) != expected["sha256"]
            ):
                raise RuntimeError(f"sealed historical artifact changed: {path}")
        signed_names.update(signed)
        signed_names.update({"completion_manifest.json", ".run.lock"})
    signed_names.add("COMPLETE.json")
    actual_names = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    if actual_names != signed_names:
        raise RuntimeError(
            f"sealed bundle inventory changed: {root}; "
            f"extra={sorted(actual_names - signed_names)} "
            f"missing={sorted(signed_names - actual_names)}"
        )
    return complete


def _tree_snapshot(root: Path) -> Dict[str, Any]:
    if not root.is_dir():
        raise RuntimeError(f"protected tree is missing: {root}")
    files: List[Dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"protected tree contains a symlink: {path}")
        if path.is_file():
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
    return {
        "root": root.relative_to(ROOT).as_posix(),
        "file_count": len(files),
        "total_bytes": sum(item["bytes"] for item in files),
        "root_sha256": _digest(files),
    }


def _verify_immutable_inputs(expected: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    source_hashes = {
        path.relative_to(ROOT).as_posix(): _sha256_file(path)
        for path in EXPECTED_SOURCE_HASHES
    }
    for path, wanted in EXPECTED_SOURCE_HASHES.items():
        if source_hashes[path.relative_to(ROOT).as_posix()] != wanted:
            raise RuntimeError(f"immutable source changed: {path}")
    reference_hashes = {
        path.relative_to(ROOT).as_posix(): _sha256_file(path)
        for path in EXPECTED_REFERENCE_HASHES
    }
    for path, wanted in EXPECTED_REFERENCE_HASHES.items():
        if reference_hashes[path.relative_to(ROOT).as_posix()] != wanted:
            raise RuntimeError(f"immutable sealed reference changed: {path}")
    audit_complete = _verify_bundle_inventory(AUDIT_V2_ROOT, AUDIT_V2_COMPLETE_PATH)
    audit_v1_complete = _verify_bundle_inventory(AUDIT_V1_ROOT, AUDIT_V1_COMPLETE_PATH)
    historical_complete = _verify_bundle_inventory(HISTORICAL_ROOT, HISTORICAL_COMPLETE_PATH)
    if audit_complete.get("status") != "PASS_READY_FOR_PROPORTIONAL_N100_REVALIDATION":
        raise RuntimeError("Audit v2 is not sealed PASS")
    if historical_complete.get("plan_sha256") != EXPECTED_CANONICAL_PLAN_SHA256:
        raise RuntimeError("historical n=100 plan seal changed")
    if not str(audit_v1_complete.get("status", "")).startswith("STOP_BEFORE_N1000"):
        raise RuntimeError("Audit v1 sealed status changed")
    frozen = core.audit_frozen_csvs()
    if frozen.get("root_sha256") != EXPECTED_FROZEN_ROOT_SHA256:
        raise RuntimeError("frozen-results root changed")
    snapshot = {
        "source_sha256": source_hashes,
        "reference_sha256": reference_hashes,
        "protected_trees": {
            "historical_n100": _tree_snapshot(HISTORICAL_ROOT),
            "audit_v1": _tree_snapshot(AUDIT_V1_ROOT),
            "audit_v2": _tree_snapshot(AUDIT_V2_ROOT),
        },
        "frozen": frozen,
        "results_tree": core.snapshot_results_tree(),
    }
    if expected is not None and snapshot != dict(expected):
        raise RuntimeError("immutable input snapshot changed since authorization")
    return snapshot


def _authorization_sha256(
    plan: Mapping[str, Any],
    *,
    output: Path,
    workers: int,
    driver_hash: Optional[str] = None,
    immutable: Optional[Mapping[str, Any]] = None,
) -> str:
    _verify_plan_integrity(plan)
    return _digest(
        {
            "plan_sha256": plan["plan_sha256"],
            "output": str(output.resolve()),
            "workers": int(workers),
            "driver_sha256": driver_hash or _sha256_file(DRIVER_PATH),
            "immutable_inputs": dict(immutable or _verify_immutable_inputs()),
        }
    )


def _validate_output_path(raw: str, *, require_absent: bool) -> Path:
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    resolved = candidate.resolve()
    if resolved == OUTPUT_ROOT or OUTPUT_ROOT not in resolved.parents:
        raise RuntimeError(f"output must be a new child of {OUTPUT_ROOT}; got {resolved}")
    forbidden_roots = (
        (ROOT / "results").resolve(),
        HISTORICAL_ROOT,
        AUDIT_V2_ROOT,
    )
    if any(resolved == root or root in resolved.parents for root in forbidden_roots):
        raise RuntimeError(f"output overlaps forbidden immutable tree: {resolved}")
    if require_absent and resolved.exists():
        raise FileExistsError(f"refusing existing output {resolved}; use --resume")
    return resolved


def _finite_timing_value(value: Any, label: str) -> float:
    numeric = float(value)
    if "cpu time" in label.lower():
        if not math.isfinite(numeric) or numeric < 0.0:
            raise RuntimeError(f"{label} must be finite and non-negative")
        return numeric
    if not math.isfinite(numeric) or numeric <= 0.0:
        raise RuntimeError(f"{label} must be finite and positive")
    return numeric


def _conservation_gate(
    config: Mapping[str, Any], result: Any, engine: core.PilotAuditedSimulator
) -> Dict[str, Any]:
    if str(config.get("runner")) != "proportional":
        return canonical._conservation_gate(config, result, engine)
    delivered = result.get("per_edge_delivered_bytes")
    if not isinstance(delivered, Mapping) or len(delivered) != int(config["ring_size"]):
        raise RuntimeError("proportional delivered-byte vector has wrong edge count")
    target = float(config["bytes_per_neighbor"])
    for edge, raw_value in delivered.items():
        value = float(raw_value)
        if not math.isfinite(value) or abs(value - target) > 1e-6:
            raise RuntimeError(
                f"proportional edge {edge!r} delivered invalid bytes {raw_value!r}"
            )
    verdict = dict(_BASE_CONSERVATION_GATE(config, result, engine))
    flows = core._foreground_flows(engine, "proportional")
    expected_flows = int(config["ring_size"]) * int(config["k"])
    if len(flows) != expected_flows:
        raise RuntimeError(
            f"proportional foreground flow count {len(flows)} != {expected_flows}"
        )
    remaining = [float(flow.remaining_bytes) for flow in flows]
    if any(not math.isfinite(value) for value in remaining):
        raise RuntimeError("proportional foreground remaining bytes are non-finite")
    nonzero_count = sum(value != 0.0 for value in remaining)
    if nonzero_count:
        raise RuntimeError(
            f"proportional has {nonzero_count} individual foreground flows remaining"
        )
    if int(verdict.get("checks", -1)) != int(config["ring_size"]):
        raise RuntimeError("proportional logical-edge conservation count changed")
    if int(verdict.get("foreground_flow_count", -1)) != expected_flows:
        raise RuntimeError("proportional conservation recorded wrong flow count")
    if float(verdict.get("maximum_abs_error_bytes", math.inf)) > 1e-6:
        raise RuntimeError("proportional conservation exceeds 1e-6 byte")
    base_remaining = float(verdict.get("remaining_foreground_bytes", math.nan))
    if not math.isfinite(base_remaining) or base_remaining != 0.0:
        raise RuntimeError("base proportional aggregate remaining bytes are not exactly zero")
    for key, value in verdict.items():
        if isinstance(value, float) and not math.isfinite(value):
            raise RuntimeError(f"non-finite conservation value: {key}")
    verdict.update(
        {
            "remaining_foreground_bytes": base_remaining,
            "foreground_remaining_nonzero_count": nonzero_count,
            "foreground_remaining_min_bytes": min(remaining),
            "foreground_remaining_max_bytes": max(remaining),
            "individual_remaining_values_checked": len(remaining),
        }
    )
    return verdict


def _configure_core() -> None:
    core.DRIVER_PATH = DRIVER_PATH
    core.PILOT_ROOT = OUTPUT_ROOT
    core.SAMPLE_IDS = SAMPLE_IDS
    core._make_topology_and_ring = canonical._make_topology_and_ring
    core._finite_positive = _finite_timing_value
    core._conservation_gate = _conservation_gate


def _verify_worker_sources() -> None:
    if not _WORKER_EXPECTED_HASHES:
        raise RuntimeError("worker source authorization is unavailable")
    paths = {
        "sim_sha256": SIM_PATH,
        "driver_sha256": DRIVER_PATH,
        "canonical_driver_sha256": CANONICAL_DRIVER_PATH,
        "core_driver_sha256": CORE_DRIVER_PATH,
        "spec_sha256": SPEC_PATH,
        "audit_v2_complete_sha256": AUDIT_V2_COMPLETE_PATH,
        "audit_v1_complete_sha256": AUDIT_V1_COMPLETE_PATH,
        "historical_complete_sha256": HISTORICAL_COMPLETE_PATH,
    }
    for key, path in paths.items():
        if _sha256_file(path) != _WORKER_EXPECTED_HASHES.get(key):
            raise RuntimeError(f"immutable source changed inside worker: {path}")


def _worker_init(expected_hashes: Mapping[str, str]) -> None:
    global _WORKER_EXPECTED_HASHES
    _WORKER_EXPECTED_HASHES = dict(expected_hashes)
    _configure_core()
    _verify_worker_sources()
    core._worker_init(
        _WORKER_EXPECTED_HASHES["sim_sha256"],
        _WORKER_EXPECTED_HASHES["driver_sha256"],
    )


def _run_pair_worker(pair: Mapping[str, Any]) -> Dict[str, Any]:
    _configure_core()
    _verify_worker_sources()
    checkpoint = _delegate_pair_worker(pair)
    _verify_worker_sources()
    return checkpoint


def _delegate_pair_worker(
    pair: Mapping[str, Any], delegate: Optional[Any] = None
) -> Dict[str, Any]:
    return (delegate or core._run_pair_worker)(pair)


def _odd_order_bridge_gate(plan: Mapping[str, Any]) -> Dict[str, Any]:
    pair = next(
        item
        for item in plan["pairs"]
        if item["execution_order"][0] == MAXMIN_ALLOCATOR
    )
    received: List[Mapping[str, Any]] = []

    def capture(item: Mapping[str, Any]) -> Dict[str, Any]:
        received.append(item)
        return {"execution_order": list(item["execution_order"])}

    result = _delegate_pair_worker(pair, capture)
    if (
        received != [pair]
        or received[0] is not pair
        or result["execution_order"] != [MAXMIN_ALLOCATOR, LEGACY_ALLOCATOR]
    ):
        raise RuntimeError("no-simulation reverse-order worker bridge failed")
    return {
        "passed": True,
        "pair_id": pair["pair_id"],
        "sample_id": int(pair["sample_id"]),
        "execution_order": list(pair["execution_order"]),
        "same_pair_object_delegated": True,
        "simulations_run": 0,
    }


def _cluster_bootstrap(values_by_seed: Mapping[int, Sequence[float]]) -> Dict[str, Any]:
    seed_ids = sorted(int(seed) for seed in values_by_seed)
    if not seed_ids or seed_ids != list(range(len(seed_ids))):
        raise RuntimeError("bootstrap seed clusters must be dense and zero based")
    widths = {len(values_by_seed[seed]) for seed in seed_ids}
    if len(widths) != 1 or not widths or next(iter(widths)) < 1:
        raise RuntimeError("bootstrap seed clusters have inconsistent/empty widths")
    matrix = np.asarray([values_by_seed[seed] for seed in seed_ids], dtype=np.float64)
    if not np.isfinite(matrix).all():
        raise RuntimeError("bootstrap log-ratio input is non-finite")
    rng = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED))
    indices = rng.integers(
        0,
        len(seed_ids),
        size=(BOOTSTRAP_REPLICATES, len(seed_ids)),
        dtype=np.uint32,
    ).astype("<u4", copy=False)
    cluster_means = matrix.mean(axis=1)
    replicates = np.exp(cluster_means[indices].mean(axis=1))
    low, high = np.quantile(replicates, [0.025, 0.975], method="linear")
    return {
        "point_estimate": float(math.exp(float(matrix.mean()))),
        "ci95_low": float(low),
        "ci95_high": float(high),
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "rng": "PCG64(20260807)",
        "quantiles": [0.025, 0.975],
        "quantile_method": "linear",
        "bootstrap_index_shape": list(indices.shape),
        "bootstrap_index_dtype": indices.dtype.str,
        "bootstrap_index_sha256": hashlib.sha256(indices.tobytes(order="C")).hexdigest(),
    }


def _tick_class(delta_ticks: int) -> str:
    delta = int(delta_ticks)
    if delta <= -2:
        return "maxmin_faster_by_2plus"
    if delta == 0:
        return "exact_tie"
    if delta in (-1, 1):
        return "one_tick_tie"
    return "maxmin_slower_by_2plus"


def _historical_artifact_entry(
    completion: Mapping[str, Any], relative: str
) -> Mapping[str, Any]:
    for group in ("checkpoints", "exports", "timing_segments"):
        entry = completion.get(group, {}).get(relative)
        if isinstance(entry, Mapping):
            return entry
    raise RuntimeError(f"historical completion manifest does not sign {relative}")


def _read_signed_historical_checkpoint(
    pair: Mapping[str, Any], completion: Mapping[str, Any], plan_hash: str
) -> Dict[str, Any]:
    relative = f"checkpoints/{pair['pair_id']}.json"
    path = HISTORICAL_ROOT / relative
    expected = _historical_artifact_entry(completion, relative)
    if (
        not path.is_file()
        or path.stat().st_size != int(expected["bytes"])
        or _sha256_file(path) != expected["sha256"]
    ):
        raise RuntimeError(f"historical checkpoint seal changed: {pair['pair_id']}")
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    core._validate_checkpoint(checkpoint, pair, plan_hash)
    return checkpoint


def _reference_indexes() -> Dict[str, Any]:
    """Load only the 3,200 proportional and 3,200 matched static-equal pairs."""
    _configure_core()
    source_plan = canonical.build_plan()
    if source_plan["plan_sha256"] != EXPECTED_CANONICAL_PLAN_SHA256:
        raise RuntimeError("canonical source plan changed while loading references")
    completion_path = HISTORICAL_ROOT / "completion_manifest.json"
    complete = json.loads(HISTORICAL_COMPLETE_PATH.read_text(encoding="utf-8"))
    if _sha256_file(completion_path) != complete["completion_manifest_sha256"]:
        raise RuntimeError("historical completion manifest changed")
    completion = json.loads(completion_path.read_text(encoding="utf-8"))

    proportional_pairs = {
        pair["pair_id"]: pair
        for pair in source_plan["pairs"]
        if pair["config"].get("family") == "static_split"
        and pair["config"].get("runner") == "proportional"
        and pair["config"].get("policy") == "proportional"
    }
    equal_pairs: Dict[Tuple[str, int, int, int], Mapping[str, Any]] = {}
    for pair in source_plan["pairs"]:
        config = pair["config"]
        if not (
            config.get("family") == "static_split"
            and config.get("runner") == "simple"
            and config.get("policy") == "equal"
            and int(config.get("k", 0)) in (2, 4, 8, 16)
        ):
            continue
        key = (
            str(config["fabric"]),
            int(config["ring_size"]),
            int(config["k"]),
            int(pair["sample_id"]),
        )
        if key in equal_pairs:
            raise RuntimeError(f"duplicate equal-policy reference key: {key}")
        equal_pairs[key] = pair
    if len(proportional_pairs) != PAIR_COUNT or len(equal_pairs) != PAIR_COUNT:
        raise RuntimeError("historical proportional/equal reference cardinality changed")

    historical_pairs: Dict[str, Dict[str, Any]] = {}
    historical_rows: Dict[Tuple[str, str], Mapping[str, Any]] = {}
    equal_rows: Dict[Tuple[str, int, int, int, str], Dict[str, Any]] = {}
    equal_allocator_identical_pairs = 0
    for pair_id, pair in proportional_pairs.items():
        checkpoint = _read_signed_historical_checkpoint(
            pair, completion, source_plan["plan_sha256"]
        )
        historical_pairs[pair_id] = checkpoint
        for row in checkpoint["rows"]:
            historical_rows[(pair_id, row["allocator"])] = row
    for cell, pair in equal_pairs.items():
        checkpoint = _read_signed_historical_checkpoint(
            pair, completion, source_plan["plan_sha256"]
        )
        equal_by_allocator = {row["allocator"]: row for row in checkpoint["rows"]}
        if (
            equal_by_allocator[LEGACY_ALLOCATOR]["completion_time_hex"]
            != equal_by_allocator[MAXMIN_ALLOCATOR]["completion_time_hex"]
            or int(equal_by_allocator[LEGACY_ALLOCATOR]["simulated_ticks"])
            != int(equal_by_allocator[MAXMIN_ALLOCATOR]["simulated_ticks"])
        ):
            raise RuntimeError(
                f"observed static-equal allocator identity changed: {pair['pair_id']}"
            )
        equal_allocator_identical_pairs += 1
        for row in checkpoint["rows"]:
            equal_rows[(*cell, row["allocator"])] = {
                "pair_id": pair["pair_id"],
                "row": row,
            }
    if len(historical_rows) != SIMULATION_COUNT or len(equal_rows) != SIMULATION_COUNT:
        raise RuntimeError("historical/equal allocator-row join is not bijective")
    return {
        "source_plan_sha256": source_plan["plan_sha256"],
        "historical_pairs": historical_pairs,
        "historical_rows": historical_rows,
        "equal_rows": equal_rows,
        "historical_pair_count": len(historical_pairs),
        "historical_row_count": len(historical_rows),
        "equal_pair_count": len(equal_pairs),
        "equal_row_count": len(equal_rows),
        "equal_allocator_identical_pair_count": equal_allocator_identical_pairs,
    }


def _require_digest_match(
    current: Mapping[str, Any], reference: Mapping[str, Any], fields: Iterable[str], label: str
) -> None:
    for field in fields:
        if current.get(field) != reference.get(field):
            raise RuntimeError(f"{label} structural digest mismatch: {field}")


def _attach_reference_diagnostics(
    checkpoint: Dict[str, Any], refs: Mapping[str, Any]
) -> None:
    pair = checkpoint["pair_spec"]
    pair_id = pair["pair_id"]
    config = pair["config"]
    historical_checkpoint = refs["historical_pairs"].get(pair_id)
    if historical_checkpoint is None or historical_checkpoint["pair_spec"] != pair:
        raise RuntimeError(f"missing/mismatched historical proportional pair: {pair_id}")
    for row in checkpoint["rows"]:
        allocator = row["allocator"]
        try:
            historical = refs["historical_rows"][(pair_id, allocator)]
            equal_ref = refs["equal_rows"][(
                str(config["fabric"]),
                int(config["ring_size"]),
                int(config["k"]),
                int(pair["sample_id"]),
                allocator,
            )]
        except KeyError as exc:
            raise RuntimeError(f"missing historical/equal reference row: {pair_id} {allocator}") from exc
        equal = equal_ref["row"]
        _require_digest_match(
            row,
            historical,
            (
                "config_sha256",
                "topology_sha256",
                "ring_sha256",
                "route_sha256",
                "process_initial_sha256",
            ),
            "historical proportional",
        )
        _require_digest_match(
            row,
            equal,
            (
                "topology_sha256",
                "ring_sha256",
                "route_sha256",
                "process_initial_sha256",
            ),
            "matched equal policy",
        )
        new_time = float(row["completion_time_s"])
        old_time = float(historical["completion_time_s"])
        equal_time = float(equal["completion_time_s"])
        new_ticks = int(row["simulated_ticks"])
        old_ticks = int(historical["simulated_ticks"])
        equal_ticks = int(equal["simulated_ticks"])
        row["reference_diagnostics"] = {
            "schema": "corrected-proportional-reference-diagnostics-v1",
            "historical_proportional": {
                "pair_id": pair_id,
                "allocator": allocator,
                "corrected_completion_time_s": new_time,
                "corrected_completion_time_hex": row["completion_time_hex"],
                "corrected_simulated_ticks": new_ticks,
                "completion_time_s": old_time,
                "completion_time_hex": historical["completion_time_hex"],
                "simulated_ticks": old_ticks,
                "corrected_minus_historical_s": new_time - old_time,
                "corrected_minus_historical_ticks": new_ticks - old_ticks,
                "corrected_over_historical": new_time / old_time,
                "relative_delta": new_time / old_time - 1.0,
                "completion_binary64_equal": (
                    row["completion_time_hex"] == historical["completion_time_hex"]
                ),
            },
            "matched_equal_policy": {
                "pair_id": equal_ref["pair_id"],
                "allocator": allocator,
                "completion_time_s": equal_time,
                "completion_time_hex": equal["completion_time_hex"],
                "simulated_ticks": equal_ticks,
                "corrected_completion_time_s": new_time,
                "corrected_completion_time_hex": row["completion_time_hex"],
                "corrected_simulated_ticks": new_ticks,
                "equal_over_corrected_proportional": equal_time / new_time,
                "corrected_proportional_minus_equal_s": new_time - equal_time,
                "corrected_proportional_minus_equal_ticks": new_ticks - equal_ticks,
                "claim_review_trigger": new_ticks - equal_ticks >= 2,
            },
        }


def _validate_checkpoint(
    checkpoint: Dict[str, Any],
    pair: Mapping[str, Any],
    plan_hash: str,
    refs: Mapping[str, Any],
) -> None:
    _configure_core()
    core._validate_checkpoint(checkpoint, pair, plan_hash)
    for row in checkpoint["rows"]:
        conservation = row.get("conservation", {})
        expected_flows = int(pair["config"]["ring_size"]) * int(pair["config"]["k"])
        expected_checks = int(pair["config"]["ring_size"])
        required_numeric = (
            "remaining_foreground_bytes",
            "maximum_abs_error_bytes",
            "maximum_per_flow_error_bytes",
            "foreground_remaining_min_bytes",
            "foreground_remaining_max_bytes",
        )
        if any(
            isinstance(conservation.get(key), bool)
            or not isinstance(conservation.get(key), numbers.Real)
            or not math.isfinite(float(conservation[key]))
            for key in required_numeric
        ):
            raise RuntimeError(f"non-finite persisted conservation value: {pair['pair_id']}")
        if (
            conservation.get("maximum_abs_error_bytes_hex")
            != core._f64_hex(conservation["maximum_abs_error_bytes"])
            or conservation.get("maximum_per_flow_error_bytes_hex")
            != core._f64_hex(conservation["maximum_per_flow_error_bytes"])
        ):
            raise RuntimeError(f"persisted conservation numeric/hex mismatch: {pair['pair_id']}")
        maximum_error = float(conservation.get("maximum_abs_error_bytes", math.nan))
        if (
            conservation.get("passed") is not True
            or int(conservation.get("foreground_flow_count", -1)) != expected_flows
            or int(conservation.get("checks", -1)) != expected_checks
            or int(conservation.get("foreground_remaining_nonzero_count", -1)) != 0
            or int(conservation.get("individual_remaining_values_checked", -1)) != expected_flows
            or float(conservation.get("foreground_remaining_min_bytes", math.nan)) != 0.0
            or float(conservation.get("foreground_remaining_max_bytes", math.nan)) != 0.0
            or float(conservation.get("remaining_foreground_bytes", math.nan)) != 0.0
            or not math.isfinite(maximum_error)
            or maximum_error > 1e-6
        ):
            raise RuntimeError(f"strengthened conservation gate failed: {pair['pair_id']}")
        diagnostics = row.get("reference_diagnostics")
        if not isinstance(diagnostics, Mapping):
            raise RuntimeError(f"reference diagnostics missing: {pair['pair_id']}")
    probe = copy.deepcopy(checkpoint)
    for row in probe["rows"]:
        row.pop("reference_diagnostics", None)
    _attach_reference_diagnostics(probe, refs)
    recorded = {
        row["allocator"]: row["reference_diagnostics"] for row in checkpoint["rows"]
    }
    recomputed = {
        row["allocator"]: row["reference_diagnostics"] for row in probe["rows"]
    }
    if recorded != recomputed:
        raise RuntimeError(f"reference diagnostics mismatch: {pair['pair_id']}")


def _existing_checkpoints(
    output: Path, plan: Mapping[str, Any], refs: Mapping[str, Any]
) -> Dict[str, Dict[str, Any]]:
    checkpoint_dir = output / "checkpoints"
    expected = {pair["pair_id"]: pair for pair in plan["pairs"]}
    found: Dict[str, Dict[str, Any]] = {}
    for path in sorted(checkpoint_dir.iterdir()):
        if path.name == ".staging" and path.is_dir():
            if any(not child.is_file() or ".tmp-" not in child.name for child in path.iterdir()):
                raise RuntimeError("checkpoint staging contains unknown artifact")
            continue
        if not path.is_file() or path.suffix != ".json":
            raise RuntimeError(f"unexpected checkpoint artifact: {path.name}")
        pair_id = path.stem
        if pair_id not in expected or pair_id in found:
            raise RuntimeError(f"unknown/duplicate checkpoint: {pair_id}")
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
        _validate_checkpoint(checkpoint, expected[pair_id], plan["plan_sha256"], refs)
        found[pair_id] = checkpoint
    return found


def _audit_v2_expected_rows() -> Dict[Tuple[str, str], Mapping[str, Any]]:
    bundle = json.loads(AUDIT_V2_EQUIVALENCE_PATH.read_text(encoding="utf-8"))
    expected: Dict[Tuple[str, str], Mapping[str, Any]] = {}
    for item in bundle.get("pairs", []):
        pair_id = item["pair_id"]
        fresh = item["fresh_pair_worker"]
        if fresh.get("pair_id") != pair_id:
            raise RuntimeError("Audit v2 pair bridge is inconsistent")
        for row in fresh["rows"]:
            key = (pair_id, row["allocator"])
            if key in expected:
                raise RuntimeError(f"duplicate Audit v2 row: {key}")
            expected[key] = row
    if len(expected) != 60:
        raise RuntimeError("Audit v2 expected-row cardinality changed")
    return expected


def _audit_v2_overlap_gate(
    checkpoints: Mapping[str, Mapping[str, Any]], *, require_all: bool = False
) -> Dict[str, Any]:
    expected_rows = _audit_v2_expected_rows()
    expected_pair_ids = {pair_id for pair_id, _ in expected_rows}
    overlap_ids = set(checkpoints).intersection(expected_pair_ids)
    if require_all and overlap_ids != expected_pair_ids:
        raise RuntimeError("complete campaign lacks the full 30-pair Audit v2 overlap")
    expected_preflight_overlap = {
        "a069_proportional_3tier_os4_p64_k2__s000",
        "a072_proportional_3tier_os4_p64_k16__s000",
        "a079_proportional_2tier_p64_k8__s000",
        PREFLIGHT_ANCHOR_PAIR_ID,
    }
    if not require_all and overlap_ids != expected_preflight_overlap:
        raise RuntimeError("preflight Audit v2 overlap is not the fixed four-pair set")
    checked: List[Tuple[str, str]] = []
    conservation_fields = (
        "passed",
        "foreground_flow_count",
        "checks",
        "remaining_foreground_bytes",
        "maximum_abs_error_bytes",
        "maximum_abs_error_bytes_hex",
        "non_bit_exact_flow_count",
        "maximum_per_flow_error_bytes",
        "maximum_per_flow_error_bytes_hex",
    )
    digest_fields = (
        "config_sha256",
        "topology_sha256",
        "ring_sha256",
        "route_sha256",
        "process_initial_sha256",
    )
    for pair_id in sorted(overlap_ids):
        rows = {row["allocator"]: row for row in checkpoints[pair_id]["rows"]}
        if set(rows) != set(ALLOCATORS):
            raise RuntimeError(f"Audit v2 overlap pair is incomplete: {pair_id}")
        for allocator in ALLOCATORS:
            current = rows[allocator]
            expected = expected_rows[(pair_id, allocator)]
            if (
                current.get("completion_time_hex") != expected.get("completion_time_hex")
                or int(current.get("simulated_ticks", -1))
                != int(expected.get("simulated_ticks", -2))
            ):
                raise RuntimeError(f"Audit v2 completion mismatch: {pair_id} {allocator}")
            _require_digest_match(current, expected, digest_fields, "Audit v2")
            for field in conservation_fields:
                if current.get("conservation", {}).get(field) != expected.get(
                    "conservation", {}
                ).get(field):
                    raise RuntimeError(
                        f"Audit v2 conservation mismatch: {pair_id} {allocator} {field}"
                    )
            for numeric_field, hex_field in (
                ("maximum_abs_error_bytes", "maximum_abs_error_bytes_hex"),
                ("maximum_per_flow_error_bytes", "maximum_per_flow_error_bytes_hex"),
            ):
                numeric = current["conservation"].get(numeric_field)
                if (
                    isinstance(numeric, bool)
                    or not isinstance(numeric, numbers.Real)
                    or not math.isfinite(float(numeric))
                    or current["conservation"].get(hex_field) != core._f64_hex(numeric)
                ):
                    raise RuntimeError(
                        f"Audit v2 conservation numeric/hex invalid: {pair_id} {allocator}"
                    )
            checked.append((pair_id, allocator))
    anchors: List[str] = []
    anchor_contract = {
        (
            "a072_proportional_3tier_os4_p64_k16__s033",
            LEGACY_ALLOCATOR,
        ): ("3f79ce075f6fd214", 126, "6.30ms"),
        (PREFLIGHT_ANCHOR_PAIR_ID, MAXMIN_ALLOCATOR): (
            "3f7930be0ded2882",
            123,
            "6.15ms",
        ),
    }
    for key, (hex_value, ticks, label) in anchor_contract.items():
        if key not in expected_rows or key[0] not in overlap_ids:
            continue
        row = next(
            item for item in checkpoints[key[0]]["rows"] if item["allocator"] == key[1]
        )
        if row["completion_time_hex"] != hex_value or int(row["simulated_ticks"]) != ticks:
            raise RuntimeError(f"named Audit v2 anchor changed: {key}")
        anchors.append(f"{key[0]}:{key[1]}:{label}")
    return {
        "passed": True,
        "pair_count": len(overlap_ids),
        "row_count": len(checked),
        "pair_ids": sorted(overlap_ids),
        "named_anchors_checked": anchors,
        "require_all": require_all,
    }


def _preflight_gate(
    plan: Mapping[str, Any],
    checkpoints: Mapping[str, Mapping[str, Any]],
    refs: Mapping[str, Any],
) -> Dict[str, Any]:
    ordered_ids = list(plan["preflight_pair_ids"])
    if set(checkpoints) != set(ordered_ids) or len(checkpoints) != 33:
        raise RuntimeError("preflight gate requires exactly the fixed 33 checkpoints")
    expected_pairs = {pair["pair_id"]: pair for pair in _preflight_pairs(plan)}
    for pair_id in ordered_ids:
        _validate_checkpoint(
            dict(checkpoints[pair_id]),
            expected_pairs[pair_id],
            plan["plan_sha256"],
            refs,
        )
    row_count = sum(len(checkpoint["rows"]) for checkpoint in checkpoints.values())
    conservation_rows = sum(
        row["conservation"].get("passed") is True
        and row["conservation"].get("foreground_remaining_nonzero_count") == 0
        for checkpoint in checkpoints.values()
        for row in checkpoint["rows"]
    )
    reference_rows = sum(
        isinstance(row.get("reference_diagnostics"), Mapping)
        for checkpoint in checkpoints.values()
        for row in checkpoint["rows"]
    )
    if row_count != 66 or conservation_rows != 66 or reference_rows != 66:
        raise RuntimeError("preflight row/conservation/reference coverage is incomplete")
    v2 = _audit_v2_overlap_gate(checkpoints, require_all=False)
    odd_bridge = _odd_order_bridge_gate(plan)
    return {
        "passed": True,
        "status": "PASS_PREFLIGHT_33_READY_FOR_REMAINING_3167",
        "ordered_pair_ids": ordered_ids,
        "pair_count": 33,
        "row_count": 66,
        "first_allocator_counts": {LEGACY_ALLOCATOR: 33, MAXMIN_ALLOCATOR: 0},
        "conservation_gate": {"passed": True, "row_count": conservation_rows},
        "historical_join_gate": {"passed": True, "row_count": reference_rows},
        "odd_order_bridge_gate": odd_bridge,
        "audit_v2_overlap_gate": v2,
    }


def _global_gate(
    plan: Mapping[str, Any],
    checkpoints: Mapping[str, Mapping[str, Any]],
    refs: Mapping[str, Any],
) -> Dict[str, Any]:
    expected = {pair["pair_id"]: pair for pair in plan["pairs"]}
    if set(checkpoints) != set(expected) or len(checkpoints) != PAIR_COUNT:
        raise RuntimeError("global gate does not have the exact 3,200 checkpoints")
    arm_rows: Counter[str] = Counter()
    seed_rows: Counter[int] = Counter()
    allocator_rows: Counter[str] = Counter()
    first_counts: Counter[str] = Counter()
    conservation_rows = 0
    reference_rows = 0
    for pair_id, pair in expected.items():
        checkpoint = dict(checkpoints[pair_id])
        _validate_checkpoint(checkpoint, pair, plan["plan_sha256"], refs)
        first_counts[pair["execution_order"][0]] += 1
        for row in checkpoint["rows"]:
            if (
                row.get("family") != "static_split"
                or row.get("runner") != "proportional"
                or row.get("policy") != "proportional"
            ):
                raise RuntimeError(f"unplanned campaign row: {pair_id}")
            arm_rows[row["arm_id"]] += 1
            seed_rows[int(row["sample_id"])] += 1
            allocator_rows[row["allocator"]] += 1
            conservation_rows += row["conservation"].get("passed") is True
            reference_rows += isinstance(row.get("reference_diagnostics"), Mapping)
    if set(arm_rows.values()) != {200} or len(arm_rows) != ARM_COUNT:
        raise RuntimeError("global per-arm row cardinality changed")
    if seed_rows != Counter({seed: 64 for seed in SAMPLE_IDS}):
        raise RuntimeError("global per-seed row cardinality changed")
    if allocator_rows != Counter({allocator: 3_200 for allocator in ALLOCATORS}):
        raise RuntimeError("global allocator row cardinality changed")
    if first_counts != Counter({allocator: 1_600 for allocator in ALLOCATORS}):
        raise RuntimeError("global allocator-first balance changed")
    if conservation_rows != SIMULATION_COUNT or reference_rows != SIMULATION_COUNT:
        raise RuntimeError("global conservation/reference coverage is incomplete")
    if refs.get("equal_allocator_identical_pair_count") != PAIR_COUNT:
        raise RuntimeError("matched static-equal allocator identity was not verified")
    return {
        "passed": True,
        "pair_count": PAIR_COUNT,
        "row_count": SIMULATION_COUNT,
        "arm_count": ARM_COUNT,
        "per_arm_rows": 200,
        "per_seed_rows": 64,
        "allocator_rows": dict(sorted(allocator_rows.items())),
        "allocator_first_pair_counts": dict(sorted(first_counts.items())),
        "conservation_rows": conservation_rows,
        "historical_join_rows": reference_rows,
        "matched_equal_pair_count": refs["equal_pair_count"],
        "matched_equal_allocator_identical_pairs": refs[
            "equal_allocator_identical_pair_count"
        ],
        "audit_v2_overlap_gate": _audit_v2_overlap_gate(
            checkpoints, require_all=True
        ),
    }


def _worker_hashes_from_manifest(manifest: Mapping[str, Any]) -> Dict[str, str]:
    immutable = manifest["immutable_before"]
    source = immutable["source_sha256"]
    references = immutable["reference_sha256"]
    return {
        "sim_sha256": source[SIM_PATH.relative_to(ROOT).as_posix()],
        "driver_sha256": manifest["driver_sha256"],
        "canonical_driver_sha256": source[
            CANONICAL_DRIVER_PATH.relative_to(ROOT).as_posix()
        ],
        "core_driver_sha256": source[CORE_DRIVER_PATH.relative_to(ROOT).as_posix()],
        "spec_sha256": source[SPEC_PATH.relative_to(ROOT).as_posix()],
        "audit_v1_complete_sha256": references[
            AUDIT_V1_COMPLETE_PATH.relative_to(ROOT).as_posix()
        ],
        "audit_v2_complete_sha256": references[
            AUDIT_V2_COMPLETE_PATH.relative_to(ROOT).as_posix()
        ],
        "historical_complete_sha256": references[
            HISTORICAL_COMPLETE_PATH.relative_to(ROOT).as_posix()
        ],
    }


def _verify_runtime_authorization(manifest: Mapping[str, Any]) -> None:
    if _sha256_file(DRIVER_PATH) != manifest.get("driver_sha256"):
        raise RuntimeError("corrected n=100 driver changed after authorization")
    immutable = _verify_immutable_inputs(manifest.get("immutable_before"))
    expected_auth = _authorization_sha256(
        manifest["plan"],
        output=Path(manifest["output"]),
        workers=int(manifest["workers"]),
        driver_hash=manifest["driver_sha256"],
        immutable=immutable,
    )
    if manifest.get("authorization_sha256") != expected_auth:
        raise RuntimeError("run authorization is inconsistent")
    unsigned_manifest = dict(manifest)
    recorded_manifest_hash = unsigned_manifest.pop("manifest_payload_sha256", None)
    if recorded_manifest_hash != _digest(unsigned_manifest):
        raise RuntimeError("run manifest payload hash is inconsistent")


def _new_manifest(
    plan: Mapping[str, Any],
    output: Path,
    workers: int,
    immutable: Mapping[str, Any],
    driver_hash: str,
) -> Dict[str, Any]:
    authorization = _authorization_sha256(
        plan,
        output=output,
        workers=workers,
        driver_hash=driver_hash,
        immutable=immutable,
    )
    manifest = {
        "schema": "corrected-proportional-n100-run-v1",
        "created_local": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "output": str(output),
        "workers": int(workers),
        "python": sys.version,
        "platform": platform.platform(),
        "multiprocessing_start_method": "spawn",
        "plan_sha256": plan["plan_sha256"],
        "plan": plan,
        "driver_sha256": driver_hash,
        "immutable_before": dict(immutable),
        "authorization_sha256": authorization,
        "git": core._git_state(),
        "checkpoint_policy": "one atomic parent-written JSON per paired checkpoint",
        "execution_phases": ["preflight_33", "remaining_3167"],
        "historical_outcomes_are_diagnostic_only": True,
        "n1000_execution_path": False,
    }
    manifest["manifest_payload_sha256"] = _digest(manifest)
    return manifest


def _timing_path(output: Path, index: int) -> Path:
    return output / "timing_segments" / f"segment_{index:03d}.json"


def _load_timing_segments(
    output: Path, checkpoints: Mapping[str, Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    segments: List[Dict[str, Any]] = []
    covered: set[str] = set()
    timing_paths = list((output / "timing_segments").iterdir())

    def timing_sort_key(path: Path) -> Tuple[int, str]:
        if path.is_file() and path.suffix == ".json" and path.stem.startswith("segment_"):
            try:
                return (int(path.stem.split("_", 1)[1]), path.name)
            except ValueError:
                pass
        return (sys.maxsize, path.name)

    for path in sorted(timing_paths, key=timing_sort_key):
        if path.name == ".staging" and path.is_dir():
            if any(not child.is_file() or ".tmp-" not in child.name for child in path.iterdir()):
                raise RuntimeError("timing staging contains unknown artifact")
            continue
        if not path.is_file() or path.suffix != ".json":
            raise RuntimeError(f"unexpected timing artifact: {path.name}")
        segment = json.loads(path.read_text(encoding="utf-8"))
        index = len(segments) + 1
        if (
            segment.get("schema") != "corrected-proportional-n100-timing-segment-v1"
            or path.name != f"segment_{index:03d}.json"
            or int(segment.get("segment_index", -1)) != index
        ):
            raise RuntimeError(f"invalid/non-sequential timing segment: {path.name}")
        phase = segment.get("phase")
        recovered = segment.get("recovered_after_interruption")
        if phase not in (
            "preflight_33",
            "remaining_3167",
            "recovered_after_interruption",
        ) or not isinstance(recovered, bool):
            raise RuntimeError(f"invalid timing phase/recovery provenance: {path.name}")
        if (phase == "recovered_after_interruption") != recovered:
            raise RuntimeError(f"inconsistent timing recovery provenance: {path.name}")
        pair_ids = list(segment.get("pair_ids", []))
        if (
            not pair_ids
            or len(pair_ids) != len(set(pair_ids))
            or covered.intersection(pair_ids)
            or any(pair_id not in checkpoints for pair_id in pair_ids)
        ):
            raise RuntimeError(f"invalid timing pair coverage: {path.name}")
        preflight_ids = set(build_plan()["preflight_pair_ids"])
        pair_set = set(pair_ids)
        if phase == "preflight_33" and not pair_set.issubset(preflight_ids):
            raise RuntimeError(f"preflight timing segment contains main pairs: {path.name}")
        if phase == "remaining_3167" and pair_set.intersection(preflight_ids):
            raise RuntimeError(f"main timing segment contains preflight pairs: {path.name}")
        if phase == "recovered_after_interruption" and not (
            pair_set.issubset(preflight_ids) or pair_set.isdisjoint(preflight_ids)
        ):
            raise RuntimeError(f"recovered timing segment mixes phases: {path.name}")
        elapsed = _finite_timing_value(segment["elapsed_pool_wall_s"], "pool wall")
        for pair_id in pair_ids:
            timing = checkpoints[pair_id]["parent_timing"]
            if (
                int(timing["segment_index"]) != index
                or float(timing["pool_elapsed_at_checkpoint_s"]) > elapsed
            ):
                raise RuntimeError(f"checkpoint timing mismatch: {pair_id}")
        expected_sim = sum(
            float(row["simulation_wall_time_s"])
            for pair_id in pair_ids
            for row in checkpoints[pair_id]["rows"]
        )
        expected_total = sum(
            float(row["wall_time_s"])
            for pair_id in pair_ids
            for row in checkpoints[pair_id]["rows"]
        )
        if (
            core._f64_hex(segment["worker_simulation_wall_sum_s"])
            != core._f64_hex(expected_sim)
            or core._f64_hex(segment["worker_end_to_end_wall_sum_s"])
            != core._f64_hex(expected_total)
        ):
            raise RuntimeError(f"timing worker sum mismatch: {path.name}")
        covered.update(pair_ids)
        segments.append(segment)
    return segments


def _recover_timing_segments(
    output: Path,
    checkpoints: Mapping[str, Mapping[str, Any]],
    existing: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    covered = {pair_id for segment in existing for pair_id in segment["pair_ids"]}
    groups: Dict[int, List[str]] = defaultdict(list)
    for pair_id, checkpoint in checkpoints.items():
        if pair_id not in covered:
            groups[int(checkpoint["parent_timing"]["segment_index"])].append(pair_id)
    next_index = len(existing) + 1
    for index in sorted(groups):
        if index != next_index:
            raise RuntimeError(f"cannot recover timing segment {index}; expected {next_index}")
        pair_ids = sorted(groups[index])
        segment = {
            "schema": "corrected-proportional-n100-timing-segment-v1",
            "segment_index": index,
            "phase": "recovered_after_interruption",
            "pair_ids": pair_ids,
            "elapsed_pool_wall_s": max(
                float(checkpoints[pair_id]["parent_timing"]["pool_elapsed_at_checkpoint_s"])
                for pair_id in pair_ids
            ),
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
            "recovered_after_interruption": True,
        }
        core._atomic_json_once(_timing_path(output, index), segment)
        next_index += 1
    return _load_timing_segments(output, checkpoints)


def _run_pending_phase(
    pending: Sequence[Mapping[str, Any]],
    *,
    phase: str,
    output: Path,
    plan: Mapping[str, Any],
    refs: Mapping[str, Any],
    manifest: Mapping[str, Any],
    checkpoints: Dict[str, Dict[str, Any]],
    segment_index: int,
) -> None:
    if not pending:
        return
    workers = int(manifest["workers"])
    pool_start = time.perf_counter()
    context = mp.get_context("spawn")
    executor = ProcessPoolExecutor(
        max_workers=workers,
        mp_context=context,
        initializer=_worker_init,
        initargs=(_worker_hashes_from_manifest(manifest),),
    )
    completed_in_phase = 0
    try:
        futures = {executor.submit(_run_pair_worker, pair): pair for pair in pending}
        for future in as_completed(futures):
            pair = futures[future]
            checkpoint = future.result()
            checkpoint["plan_sha256"] = plan["plan_sha256"]
            checkpoint["parent_timing"] = {
                "segment_index": segment_index,
                "pool_elapsed_at_checkpoint_s": time.perf_counter() - pool_start,
            }
            _attach_reference_diagnostics(checkpoint, refs)
            _validate_checkpoint(checkpoint, pair, plan["plan_sha256"], refs)
            core._atomic_json_once(
                core._checkpoint_path(output, pair["pair_id"]), checkpoint
            )
            checkpoints[pair["pair_id"]] = checkpoint
            completed_in_phase += 1
            report_every = max(1, len(pending) // 20)
            if completed_in_phase == len(pending) or completed_in_phase % report_every == 0:
                elapsed = time.perf_counter() - pool_start
                rate = completed_in_phase / max(elapsed, 1e-12)
                eta = (len(pending) - completed_in_phase) / max(rate, 1e-12) / 60.0
                print(
                    f"[{phase}] {completed_in_phase:,}/{len(pending):,} pairs; ETA {eta:.2f} min",
                    flush=True,
                )
    except BaseException:
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)
    elapsed = time.perf_counter() - pool_start
    pair_ids = sorted(pair["pair_id"] for pair in pending)
    segment = {
        "schema": "corrected-proportional-n100-timing-segment-v1",
        "segment_index": segment_index,
        "phase": phase,
        "pair_ids": pair_ids,
        "elapsed_pool_wall_s": elapsed,
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


def _preflight_checkpoint_signatures(
    output: Path, ordered_pair_ids: Sequence[str]
) -> Dict[str, Dict[str, Any]]:
    return {
        f"checkpoints/{pair_id}.json": {
            "bytes": core._checkpoint_path(output, pair_id).stat().st_size,
            "sha256": _sha256_file(core._checkpoint_path(output, pair_id)),
        }
        for pair_id in ordered_pair_ids
    }


def _preflight_timing_signatures(
    output: Path, ordered_pair_ids: Sequence[str]
) -> Dict[str, Dict[str, Any]]:
    preflight_ids = set(ordered_pair_ids)
    signed: Dict[str, Dict[str, Any]] = {}
    for path in sorted((output / "timing_segments").glob("segment_*.json")):
        segment = json.loads(path.read_text(encoding="utf-8"))
        pair_ids = set(segment.get("pair_ids", []))
        if pair_ids and pair_ids.issubset(preflight_ids):
            relative = path.relative_to(output).as_posix()
            signed[relative] = {
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
    if not signed:
        raise RuntimeError("preflight timing provenance is unsigned/missing")
    covered = {
        pair_id
        for relative in signed
        for pair_id in json.loads((output / relative).read_text(encoding="utf-8"))[
            "pair_ids"
        ]
    }
    if covered != preflight_ids:
        raise RuntimeError("preflight timing signatures do not cover all 33 pairs")
    return signed


def _write_preflight_seal(
    output: Path,
    plan: Mapping[str, Any],
    checkpoints: Mapping[str, Mapping[str, Any]],
    refs: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> Dict[str, Any]:
    gate = _preflight_gate(plan, checkpoints, refs)
    immutable_after = _verify_immutable_inputs(manifest["immutable_before"])
    seal = {
        "schema": "corrected-proportional-n100-preflight-v1",
        **gate,
        "plan_sha256": plan["plan_sha256"],
        "checkpoint_signatures": _preflight_checkpoint_signatures(
            output, gate["ordered_pair_ids"]
        ),
        "timing_segment_signatures": _preflight_timing_signatures(
            output, gate["ordered_pair_ids"]
        ),
        "run_manifest_signature": {
            "bytes": (output / "run_manifest.json").stat().st_size,
            "sha256": _sha256_file(output / "run_manifest.json"),
        },
        "source_gate": {
            "passed": True,
            "immutable_snapshot_sha256": _digest(immutable_after),
            "driver_sha256": manifest["driver_sha256"],
        },
    }
    core._atomic_json_once(output / "preflight_complete.json", seal)
    return seal


def _verify_preflight_seal(
    output: Path,
    plan: Mapping[str, Any],
    checkpoints: Mapping[str, Mapping[str, Any]],
    refs: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> Dict[str, Any]:
    _verify_root_artifact_set(output, mode="partial")
    path = output / "preflight_complete.json"
    if not path.is_file():
        raise RuntimeError("remaining execution requires preflight_complete.json")
    recorded = json.loads(path.read_text(encoding="utf-8"))
    gate = _preflight_gate(
        plan,
        {pair_id: checkpoints[pair_id] for pair_id in plan["preflight_pair_ids"]},
        refs,
    )
    if any(recorded.get(key) != value for key, value in gate.items()):
        raise RuntimeError("preflight seal gate payload changed")
    if recorded.get("plan_sha256") != plan["plan_sha256"]:
        raise RuntimeError("preflight seal plan changed")
    signatures = _preflight_checkpoint_signatures(output, plan["preflight_pair_ids"])
    if recorded.get("checkpoint_signatures") != signatures:
        raise RuntimeError("preflight checkpoint signatures changed")
    timing_signatures = _preflight_timing_signatures(
        output, plan["preflight_pair_ids"]
    )
    if recorded.get("timing_segment_signatures") != timing_signatures:
        raise RuntimeError("preflight timing signatures changed")
    expected_run_manifest_signature = {
        "bytes": (output / "run_manifest.json").stat().st_size,
        "sha256": _sha256_file(output / "run_manifest.json"),
    }
    if recorded.get("run_manifest_signature") != expected_run_manifest_signature:
        raise RuntimeError("preflight run-manifest signature changed")
    expected_source_gate = {
        "passed": True,
        "immutable_snapshot_sha256": _digest(manifest["immutable_before"]),
        "driver_sha256": manifest["driver_sha256"],
    }
    if recorded.get("source_gate") != expected_source_gate:
        raise RuntimeError("preflight source gate payload changed")
    _verify_runtime_authorization(manifest)
    seal_mtime = path.stat().st_mtime_ns
    if any(
        core._checkpoint_path(output, pair_id).stat().st_mtime_ns > seal_mtime
        for pair_id in plan["preflight_pair_ids"]
    ):
        raise RuntimeError("preflight seal predates a preflight checkpoint")
    if any(
        core._checkpoint_path(output, pair_id).stat().st_mtime_ns < seal_mtime
        for pair_id in set(checkpoints) - set(plan["preflight_pair_ids"])
    ):
        raise RuntimeError("a remaining checkpoint predates the preflight seal")
    return recorded


def execute_or_resume(
    plan: Mapping[str, Any],
    output: Path,
    *,
    workers: Optional[int],
    resume: bool,
    confirmed_authorization: Optional[str] = None,
) -> Dict[str, Any]:
    _verify_plan_integrity(plan)
    _configure_core()
    validated_output = _validate_output_path(str(output), require_absent=not resume)
    if validated_output != output.resolve():
        raise RuntimeError("execution output path differs after containment validation")
    if resume:
        if not output.is_dir():
            raise RuntimeError(f"resume directory does not exist: {output}")
    else:
        if workers is None or not 1 <= int(workers) <= 8:
            raise RuntimeError("fresh execution requires 1..8 workers")
        immutable = _verify_immutable_inputs()
        driver_hash = _sha256_file(DRIVER_PATH)
        if confirmed_authorization != _authorization_sha256(
            plan,
            output=output,
            workers=int(workers),
            driver_hash=driver_hash,
            immutable=immutable,
        ):
            raise RuntimeError("execution authorization changed before output creation")
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        output.mkdir(parents=False, exist_ok=False)
        (output / "checkpoints").mkdir(exist_ok=False)
        (output / "timing_segments").mkdir(exist_ok=False)

    with core.ExclusiveRunLock(output / ".run.lock") as run_lock:
        manifest_path = output / "run_manifest.json"
        if resume:
            if not manifest_path.is_file():
                raise RuntimeError("resume requires run_manifest.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                manifest.get("schema") != "corrected-proportional-n100-run-v1"
                or manifest.get("plan") != plan
                or manifest.get("plan_sha256") != plan["plan_sha256"]
                or Path(manifest.get("output", "")).resolve() != output
            ):
                raise RuntimeError("resume manifest differs from fixed campaign")
            workers = int(manifest["workers"])
            if not 1 <= workers <= 8:
                raise RuntimeError("resume worker count is outside 1..8")
            _verify_runtime_authorization(manifest)
            if (output / "COMPLETE.json").exists():
                return _verify_complete(output, manifest, run_lock)
        else:
            assert workers is not None
            immutable = _verify_immutable_inputs()
            driver_hash = _sha256_file(DRIVER_PATH)
            manifest = _new_manifest(plan, output, int(workers), immutable, driver_hash)
            if manifest["authorization_sha256"] != confirmed_authorization:
                raise RuntimeError("execution sources changed while creating manifest")
            core._atomic_json_once(manifest_path, manifest)

        refs = _reference_indexes()
        checkpoints = _existing_checkpoints(output, plan, refs)
        preflight_ids = set(plan["preflight_pair_ids"])
        extra_ids = set(checkpoints) - preflight_ids
        preflight_path = output / "preflight_complete.json"
        if extra_ids and not preflight_path.is_file():
            raise RuntimeError("non-preflight checkpoints exist without a preflight seal")
        if preflight_path.is_file():
            if not preflight_ids.issubset(checkpoints):
                raise RuntimeError("preflight seal exists without all 33 checkpoints")
            _verify_preflight_seal(output, plan, checkpoints, refs, manifest)
        segments = _load_timing_segments(output, checkpoints)
        segments = _recover_timing_segments(output, checkpoints, segments)

        pending_preflight = [
            pair for pair in _preflight_pairs(plan) if pair["pair_id"] not in checkpoints
        ]
        if pending_preflight:
            _run_pending_phase(
                pending_preflight,
                phase="preflight_33",
                output=output,
                plan=plan,
                refs=refs,
                manifest=manifest,
                checkpoints=checkpoints,
                segment_index=len(segments) + 1,
            )
            checkpoints = _existing_checkpoints(output, plan, refs)
            segments = _load_timing_segments(output, checkpoints)
        preflight_checkpoints = {
            pair_id: checkpoints[pair_id] for pair_id in plan["preflight_pair_ids"]
        }
        if not preflight_path.is_file():
            _write_preflight_seal(
                output, plan, preflight_checkpoints, refs, manifest
            )
            _verify_preflight_seal(output, plan, checkpoints, refs, manifest)

        pending = [pair for pair in plan["pairs"] if pair["pair_id"] not in checkpoints]
        if pending:
            _run_pending_phase(
                pending,
                phase="remaining_3167",
                output=output,
                plan=plan,
                refs=refs,
                manifest=manifest,
                checkpoints=checkpoints,
                segment_index=len(segments) + 1,
            )
        checkpoints = _existing_checkpoints(output, plan, refs)
        segments = _load_timing_segments(output, checkpoints)
        return _finalize(
            output, plan, checkpoints, refs, manifest, segments, run_lock
        )


def _paired_analysis_rows(
    checkpoints: Mapping[str, Mapping[str, Any]], refs: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for pair_id in sorted(checkpoints):
        checkpoint = checkpoints[pair_id]
        if pair_id in seen:
            raise RuntimeError(f"duplicate analysis pair: {pair_id}")
        seen.add(pair_id)
        indexed = {row["allocator"]: row for row in checkpoint["rows"]}
        if set(indexed) != set(ALLOCATORS) or len(checkpoint["rows"]) != 2:
            raise RuntimeError(f"analysis pair lacks both allocators: {pair_id}")
        legacy = indexed[LEGACY_ALLOCATOR]
        maxmin = indexed[MAXMIN_ALLOCATOR]
        legacy_diag = legacy["reference_diagnostics"]
        maxmin_diag = maxmin["reference_diagnostics"]
        old_legacy = legacy_diag["historical_proportional"]
        old_maxmin = maxmin_diag["historical_proportional"]
        equal_legacy = legacy_diag["matched_equal_policy"]
        equal_maxmin = maxmin_diag["matched_equal_policy"]
        legacy_time = float(legacy["completion_time_s"])
        maxmin_time = float(maxmin["completion_time_s"])
        ratio = maxmin_time / legacy_time
        delta_ticks = int(maxmin["simulated_ticks"]) - int(legacy["simulated_ticks"])
        historical_delta_ticks = int(old_maxmin["simulated_ticks"]) - int(
            old_legacy["simulated_ticks"]
        )
        material_reversal = (
            historical_delta_ticks <= -2 and delta_ticks >= 2
        ) or (historical_delta_ticks >= 2 and delta_ticks <= -2)
        config = checkpoint["pair_spec"]["config"]
        rows.append(
            {
                "pair_id": pair_id,
                "arm_id": config["arm_id"],
                "sample_id": int(checkpoint["pair_spec"]["sample_id"]),
                "fabric": config["fabric"],
                "ring_size": int(config["ring_size"]),
                "k": int(config["k"]),
                "link_local_time_s": legacy_time,
                "network_maxmin_time_s": maxmin_time,
                "network_over_link_local": ratio,
                "log_network_over_link_local": math.log(ratio),
                "network_minus_link_local_s": maxmin_time - legacy_time,
                "network_minus_link_local_ms": 1_000.0
                * (maxmin_time - legacy_time),
                "network_minus_link_local_ticks": delta_ticks,
                "tick_class": _tick_class(delta_ticks),
                "historical_network_minus_link_local_ticks": historical_delta_ticks,
                "historical_tick_class": _tick_class(historical_delta_ticks),
                "material_historical_ordering_reversal": material_reversal,
                "equal_over_corrected_link_local": equal_legacy[
                    "equal_over_corrected_proportional"
                ],
                "equal_over_corrected_network_maxmin": equal_maxmin[
                    "equal_over_corrected_proportional"
                ],
                "link_local_prop_minus_equal_ticks": equal_legacy[
                    "corrected_proportional_minus_equal_ticks"
                ],
                "network_maxmin_prop_minus_equal_ticks": equal_maxmin[
                    "corrected_proportional_minus_equal_ticks"
                ],
                "equal_claim_review_trigger": bool(
                    equal_legacy["claim_review_trigger"]
                    or equal_maxmin["claim_review_trigger"]
                ),
            }
        )
    if refs.get("equal_allocator_identical_pair_count") != PAIR_COUNT:
        raise RuntimeError("analysis lacks verified matched-equal identity")
    return rows


def _descriptive_summary(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    if not rows:
        raise RuntimeError("cannot summarize an empty paired stratum")
    ratios = [float(row["network_over_link_local"]) for row in rows]
    deltas_ms = [float(row["network_minus_link_local_ms"]) for row in rows]
    deltas_ticks = [int(row["network_minus_link_local_ticks"]) for row in rows]
    classes = Counter(str(row["tick_class"]) for row in rows)
    return {
        "pair_count": len(rows),
        "geometric_mean_ratio": math.exp(statistics.fmean(math.log(x) for x in ratios)),
        "median_ratio": statistics.median(ratios),
        "minimum_ratio": min(ratios),
        "maximum_ratio": max(ratios),
        "signed_delta_ms_mean": statistics.fmean(deltas_ms),
        "signed_delta_ms_median": statistics.median(deltas_ms),
        "signed_delta_ms_min": min(deltas_ms),
        "signed_delta_ms_max": max(deltas_ms),
        "absolute_delta_ms_mean": statistics.fmean(abs(x) for x in deltas_ms),
        "absolute_delta_ms_max": max(abs(x) for x in deltas_ms),
        "signed_delta_ticks_mean": statistics.fmean(deltas_ticks),
        "signed_delta_ticks_median": statistics.median(deltas_ticks),
        "signed_delta_ticks_min": min(deltas_ticks),
        "signed_delta_ticks_max": max(deltas_ticks),
        "absolute_delta_ticks_mean": statistics.fmean(abs(x) for x in deltas_ticks),
        "absolute_delta_ticks_median": statistics.median(abs(x) for x in deltas_ticks),
        "absolute_delta_ticks_max": max(abs(x) for x in deltas_ticks),
        "tick_class_counts": {
            name: classes.get(name, 0)
            for name in (
                "maxmin_faster_by_2plus",
                "exact_tie",
                "one_tick_tie",
                "maxmin_slower_by_2plus",
            )
        },
    }


def _stopping_status(
    *,
    global_ci_low: float,
    global_ci_high: float,
    claim_trigger: bool,
    material_reversal: bool,
    single_seed_dependence: bool,
    integrity_ok: bool = True,
) -> str:
    if not integrity_ok:
        return "STOP_AND_FIX_N100_INTEGRITY_FAILURE"
    if (
        global_ci_low <= 1.0 <= global_ci_high
        or claim_trigger
        or material_reversal
        or single_seed_dependence
    ):
        return "REVIEW_CORRECTED_N100_EFFECTS_BEFORE_SCALING"
    if global_ci_high < 1.0:
        return "READY_TO_DECIDE_PROPORTIONAL_N1000_SCOPE"
    return "REVIEW_CORRECTED_N100_EFFECTS_BEFORE_SCALING"


def _analyze(
    checkpoints: Mapping[str, Mapping[str, Any]], refs: Mapping[str, Any]
) -> Dict[str, Any]:
    pairs = _paired_analysis_rows(checkpoints, refs)
    if len(pairs) != PAIR_COUNT:
        raise RuntimeError("analysis requires exactly 3,200 paired rows")
    values_by_seed: Dict[int, List[float]] = {seed: [] for seed in SAMPLE_IDS}
    for row in pairs:
        values_by_seed[int(row["sample_id"])].append(
            float(row["log_network_over_link_local"])
        )
    if {len(values) for values in values_by_seed.values()} != {ARM_COUNT}:
        raise RuntimeError("global bootstrap clusters do not preserve all 32 arms")
    global_bootstrap = _cluster_bootstrap(values_by_seed)
    global_summary = _descriptive_summary(pairs)
    global_summary["bootstrap"] = global_bootstrap

    by_arm: List[Dict[str, Any]] = []
    for arm_id in sorted({str(row["arm_id"]) for row in pairs}):
        selected = [row for row in pairs if row["arm_id"] == arm_id]
        by_seed = {
            int(row["sample_id"]): [float(row["log_network_over_link_local"])]
            for row in selected
        }
        if len(by_seed) != 100:
            raise RuntimeError(f"arm bootstrap is not 100 paired seeds: {arm_id}")
        exemplar = selected[0]
        by_arm.append(
            {
                "arm_id": arm_id,
                "fabric": exemplar["fabric"],
                "ring_size": exemplar["ring_size"],
                "k": exemplar["k"],
                "descriptive": _descriptive_summary(selected),
                "bootstrap": _cluster_bootstrap(by_seed),
                "multiplicity_note": "descriptive_per_arm_interval_no_adjusted_significance_claim",
            }
        )

    strata: List[Dict[str, Any]] = []
    for dimension in ("fabric", "ring_size", "k"):
        for value in sorted({row[dimension] for row in pairs}, key=str):
            selected = [row for row in pairs if row[dimension] == value]
            strata.append(
                {
                    "dimension": dimension,
                    "value": value,
                    "descriptive": _descriptive_summary(selected),
                }
            )

    full_point = float(global_bootstrap["point_estimate"])
    leave_one_seed_out: List[Dict[str, Any]] = []
    for omitted in SAMPLE_IDS:
        retained = [
            float(row["log_network_over_link_local"])
            for row in pairs
            if int(row["sample_id"]) != omitted
        ]
        estimate = math.exp(statistics.fmean(retained))
        crosses = (full_point < 1.0 and estimate >= 1.0) or (
            full_point > 1.0 and estimate <= 1.0
        )
        leave_one_seed_out.append(
            {
                "omitted_seed": omitted,
                "geometric_mean_ratio": estimate,
                "crosses_one_relative_to_full": crosses,
            }
        )
    single_seed_dependence = any(
        row["crosses_one_relative_to_full"] for row in leave_one_seed_out
    )

    corrected_rows = [
        row
        for checkpoint in checkpoints.values()
        for row in checkpoint["rows"]
    ]
    historical_diags = [
        row["reference_diagnostics"]["historical_proportional"]
        for row in corrected_rows
    ]
    changed_rows = sum(not diag["completion_binary64_equal"] for diag in historical_diags)
    material_reversals = sum(
        bool(row["material_historical_ordering_reversal"]) for row in pairs
    )
    ordering_changes_outside_one_tick = sum(
        row["historical_tick_class"] != row["tick_class"]
        and abs(int(row["historical_network_minus_link_local_ticks"])) >= 2
        and abs(int(row["network_minus_link_local_ticks"])) >= 2
        for row in pairs
    )
    historical_summary = {
        "allocator_row_count": len(historical_diags),
        "changed_allocator_rows": changed_rows,
        "unchanged_allocator_rows": len(historical_diags) - changed_rows,
        "maximum_absolute_completion_delta_s": max(
            abs(float(diag["corrected_minus_historical_s"]))
            for diag in historical_diags
        ),
        "maximum_absolute_tick_delta": max(
            abs(int(diag["corrected_minus_historical_ticks"]))
            for diag in historical_diags
        ),
        "maximum_absolute_relative_delta": max(
            abs(float(diag["relative_delta"])) for diag in historical_diags
        ),
        "material_pair_ordering_reversals": material_reversals,
        "ordering_class_changes_outside_one_tick": ordering_changes_outside_one_tick,
        "interpretation": "correction_impact_diagnostic_not_treatment_effect",
    }
    historical_summary["by_allocator"] = {}
    for allocator in ALLOCATORS:
        selected_diags = [
            row["reference_diagnostics"]["historical_proportional"]
            for row in corrected_rows
            if row["allocator"] == allocator
        ]
        historical_summary["by_allocator"][allocator] = {
            "row_count": len(selected_diags),
            "changed_rows": sum(
                not diag["completion_binary64_equal"] for diag in selected_diags
            ),
            "maximum_absolute_completion_delta_s": max(
                abs(float(diag["corrected_minus_historical_s"]))
                for diag in selected_diags
            ),
            "maximum_absolute_tick_delta": max(
                abs(int(diag["corrected_minus_historical_ticks"]))
                for diag in selected_diags
            ),
            "maximum_absolute_relative_delta": max(
                abs(float(diag["relative_delta"])) for diag in selected_diags
            ),
        }

    equal_trigger_pairs = sum(bool(row["equal_claim_review_trigger"]) for row in pairs)
    equal_summary = {
        "matched_pair_count": refs["equal_pair_count"],
        "matched_allocator_row_count": refs["equal_row_count"],
        "observed_allocator_identical_pair_count": refs[
            "equal_allocator_identical_pair_count"
        ],
        "link_local_equal_over_corrected_proportional_geomean": math.exp(
            statistics.fmean(
                math.log(float(row["equal_over_corrected_link_local"])) for row in pairs
            )
        ),
        "network_maxmin_equal_over_corrected_proportional_geomean": math.exp(
            statistics.fmean(
                math.log(float(row["equal_over_corrected_network_maxmin"]))
                for row in pairs
            )
        ),
        "claim_review_trigger_pair_count": equal_trigger_pairs,
        "allocator_identity_was_verified_not_assumed": True,
        "no_cross_allocator_ratio_identity_assumed": True,
    }
    status = _stopping_status(
        global_ci_low=float(global_bootstrap["ci95_low"]),
        global_ci_high=float(global_bootstrap["ci95_high"]),
        claim_trigger=equal_trigger_pairs > 0,
        material_reversal=material_reversals > 0,
        single_seed_dependence=single_seed_dependence,
    )
    return {
        "schema": "corrected-proportional-n100-analysis-v1",
        "status": status,
        "estimand": "R=T_network_maxmin/T_link_local; R<1 means network max-min faster",
        "paired_row_count": len(pairs),
        "allocator_rows_not_treated_as_independent": True,
        "global": global_summary,
        "by_arm": by_arm,
        "strata": strata,
        "leave_one_seed_out": {
            "definition": "crossing one after omitting one complete seed cluster",
            "single_seed_dependence": single_seed_dependence,
            "minimum_geometric_mean_ratio": min(
                row["geometric_mean_ratio"] for row in leave_one_seed_out
            ),
            "maximum_geometric_mean_ratio": max(
                row["geometric_mean_ratio"] for row in leave_one_seed_out
            ),
            "rows": leave_one_seed_out,
        },
        "historical_correction": historical_summary,
        "equal_policy_comparator": equal_summary,
        "review_triggers": {
            "ci_contains_one_inclusive": float(global_bootstrap["ci95_low"])
            <= 1.0
            <= float(global_bootstrap["ci95_high"]),
            "same_allocator_equal_policy_claim_trigger": equal_trigger_pairs > 0,
            "material_historical_ordering_reversal": material_reversals > 0,
            "single_seed_dependence": single_seed_dependence,
        },
        "scope_limits": [
            "static proportional matrix only",
            "no controller, congestion, background, TCP, or population-wide claim",
            "completion does not authorize n1000",
        ],
    }


def _flat_result_rows(
    checkpoints: Mapping[str, Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    flat: List[Dict[str, Any]] = []
    for pair_id in sorted(checkpoints):
        config = checkpoints[pair_id]["pair_spec"]["config"]
        for row in sorted(checkpoints[pair_id]["rows"], key=lambda item: item["allocator"]):
            exported = core._flat_row(row)
            historical = row["reference_diagnostics"]["historical_proportional"]
            equal = row["reference_diagnostics"]["matched_equal_policy"]
            exported.update(
                {
                    "fabric": config["fabric"],
                    "ring_size": config["ring_size"],
                    "k": config["k"],
                    "campaign_use": "corrected_proportional_paired_n100_revalidation",
                    "remaining_nonzero_count": row["conservation"][
                        "foreground_remaining_nonzero_count"
                    ],
                    "remaining_min_B": repr(
                        row["conservation"]["foreground_remaining_min_bytes"]
                    ),
                    "remaining_max_B": repr(
                        row["conservation"]["foreground_remaining_max_bytes"]
                    ),
                    "historical_completion_time_s": repr(historical["completion_time_s"]),
                    "historical_completion_time_hex": historical["completion_time_hex"],
                    "historical_simulated_ticks": historical["simulated_ticks"],
                    "corrected_minus_historical_s": repr(
                        historical["corrected_minus_historical_s"]
                    ),
                    "corrected_minus_historical_ticks": historical[
                        "corrected_minus_historical_ticks"
                    ],
                    "corrected_historical_relative_delta": repr(
                        historical["relative_delta"]
                    ),
                    "historical_binary64_equal": historical[
                        "completion_binary64_equal"
                    ],
                    "equal_pair_id": equal["pair_id"],
                    "equal_completion_time_s": repr(equal["completion_time_s"]),
                    "equal_completion_time_hex": equal["completion_time_hex"],
                    "equal_simulated_ticks": equal["simulated_ticks"],
                    "equal_over_corrected_proportional": repr(
                        equal["equal_over_corrected_proportional"]
                    ),
                    "corrected_proportional_minus_equal_ticks": equal[
                        "corrected_proportional_minus_equal_ticks"
                    ],
                    "equal_claim_review_trigger": equal["claim_review_trigger"],
                }
            )
            flat.append(exported)
    return flat


def _historical_delta_rows(
    checkpoints: Mapping[str, Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for pair_id in sorted(checkpoints):
        for row in sorted(checkpoints[pair_id]["rows"], key=lambda item: item["allocator"]):
            diag = row["reference_diagnostics"]["historical_proportional"]
            rows.append(
                {
                    "pair_id": pair_id,
                    "arm_id": row["arm_id"],
                    "sample_id": row["sample_id"],
                    "allocator": row["allocator"],
                    "corrected_completion_time_s": repr(diag["corrected_completion_time_s"]),
                    "corrected_completion_time_hex": diag["corrected_completion_time_hex"],
                    "corrected_simulated_ticks": diag["corrected_simulated_ticks"],
                    "historical_completion_time_s": repr(diag["completion_time_s"]),
                    "historical_completion_time_hex": diag["completion_time_hex"],
                    "historical_simulated_ticks": diag["simulated_ticks"],
                    "corrected_minus_historical_s": repr(diag["corrected_minus_historical_s"]),
                    "corrected_minus_historical_ticks": diag["corrected_minus_historical_ticks"],
                    "relative_delta": repr(diag["relative_delta"]),
                    "completion_binary64_equal": diag["completion_binary64_equal"],
                }
            )
    return rows


def _equal_comparison_rows(
    checkpoints: Mapping[str, Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for pair_id in sorted(checkpoints):
        for row in sorted(checkpoints[pair_id]["rows"], key=lambda item: item["allocator"]):
            diag = row["reference_diagnostics"]["matched_equal_policy"]
            rows.append(
                {
                    "pair_id": pair_id,
                    "arm_id": row["arm_id"],
                    "sample_id": row["sample_id"],
                    "allocator": row["allocator"],
                    "equal_pair_id": diag["pair_id"],
                    "corrected_proportional_time_s": repr(diag["corrected_completion_time_s"]),
                    "corrected_proportional_time_hex": diag["corrected_completion_time_hex"],
                    "corrected_proportional_ticks": diag["corrected_simulated_ticks"],
                    "equal_time_s": repr(diag["completion_time_s"]),
                    "equal_time_hex": diag["completion_time_hex"],
                    "equal_ticks": diag["simulated_ticks"],
                    "equal_over_corrected_proportional": repr(
                        diag["equal_over_corrected_proportional"]
                    ),
                    "corrected_proportional_minus_equal_s": repr(
                        diag["corrected_proportional_minus_equal_s"]
                    ),
                    "corrected_proportional_minus_equal_ticks": diag[
                        "corrected_proportional_minus_equal_ticks"
                    ],
                    "claim_review_trigger": diag["claim_review_trigger"],
                }
            )
    return rows


def _runtime_summary(
    checkpoints: Mapping[str, Mapping[str, Any]],
    workers: int,
    timing_segments: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    rows = [row for checkpoint in checkpoints.values() for row in checkpoint["rows"]]
    covered = {
        pair_id for segment in timing_segments for pair_id in segment["pair_ids"]
    }
    if covered != set(checkpoints):
        raise RuntimeError("timing segments do not cover every checkpoint")
    elapsed = sum(float(segment["elapsed_pool_wall_s"]) for segment in timing_segments)
    return {
        "schema": "corrected-proportional-n100-runtime-v1",
        "workers": int(workers),
        "timing_segment_count": len(timing_segments),
        "elapsed_pool_wall_sum_s": elapsed,
        "elapsed_pool_wall_sum_min": elapsed / 60.0,
        "worker_simulation_wall_sum_s": sum(
            float(row["simulation_wall_time_s"]) for row in rows
        ),
        "worker_end_to_end_wall_sum_s": sum(float(row["wall_time_s"]) for row in rows),
        "completed_pairs_per_pool_second": len(checkpoints) / elapsed,
        "historical_linear_estimate_min": 2.19,
        "predeclared_operational_allowance_min": [3.5, 5.0],
        "n1000_eta_reported": False,
    }


def _analysis_markdown(analysis: Mapping[str, Any]) -> str:
    global_summary = analysis["global"]
    bootstrap = global_summary["bootstrap"]
    triggers = analysis["review_triggers"]
    return "\n".join(
        [
            "# Corrected proportional n=100 revalidation",
            "",
            f"Status: `{analysis['status']}`",
            "",
            "## Primary paired result",
            "",
            f"- Pairs: {analysis['paired_row_count']}",
            f"- Geometric mean R=T_network/T_link: {bootstrap['point_estimate']:.9g}",
            f"- Cluster-bootstrap 95% CI: [{bootstrap['ci95_low']:.9g}, {bootstrap['ci95_high']:.9g}]",
            f"- Exact bootstrap-index SHA-256: `{bootstrap['bootstrap_index_sha256']}`",
            "",
            "## Diagnostics",
            "",
            f"- Corrected historical rows changed: {analysis['historical_correction']['changed_allocator_rows']} / 6400",
            f"- Material allocator-order reversals: {analysis['historical_correction']['material_pair_ordering_reversals']}",
            f"- Same-allocator equal-policy claim triggers: {analysis['equal_policy_comparator']['claim_review_trigger_pair_count']}",
            f"- Single-seed dependence: {triggers['single_seed_dependence']}",
            "",
            "All intervals use paired seed clusters. The 6,400 allocator rows were not treated as independent observations.",
            "No n=1000 execution is authorized by this report.",
            "",
        ]
    )


def _arm_export_rows(analysis: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in analysis["by_arm"]:
        desc = item["descriptive"]
        boot = item["bootstrap"]
        rows.append(
            {
                "arm_id": item["arm_id"],
                "fabric": item["fabric"],
                "ring_size": item["ring_size"],
                "k": item["k"],
                "pair_count": desc["pair_count"],
                "geometric_mean_ratio": repr(desc["geometric_mean_ratio"]),
                "median_ratio": repr(desc["median_ratio"]),
                "minimum_ratio": repr(desc["minimum_ratio"]),
                "maximum_ratio": repr(desc["maximum_ratio"]),
                "ci95_low": repr(boot["ci95_low"]),
                "ci95_high": repr(boot["ci95_high"]),
                "bootstrap_index_sha256": boot["bootstrap_index_sha256"],
                "faster_2plus": desc["tick_class_counts"]["maxmin_faster_by_2plus"],
                "exact_tie": desc["tick_class_counts"]["exact_tie"],
                "one_tick_tie": desc["tick_class_counts"]["one_tick_tie"],
                "slower_2plus": desc["tick_class_counts"]["maxmin_slower_by_2plus"],
            }
        )
    return rows


def _strata_export_rows(analysis: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in analysis["strata"]:
        desc = item["descriptive"]
        rows.append(
            {
                "dimension": item["dimension"],
                "value": item["value"],
                "pair_count": desc["pair_count"],
                "geometric_mean_ratio": repr(desc["geometric_mean_ratio"]),
                "median_ratio": repr(desc["median_ratio"]),
                "minimum_ratio": repr(desc["minimum_ratio"]),
                "maximum_ratio": repr(desc["maximum_ratio"]),
                "signed_delta_ms_mean": repr(desc["signed_delta_ms_mean"]),
                "absolute_delta_ms_mean": repr(desc["absolute_delta_ms_mean"]),
                "faster_2plus": desc["tick_class_counts"]["maxmin_faster_by_2plus"],
                "exact_tie": desc["tick_class_counts"]["exact_tie"],
                "one_tick_tie": desc["tick_class_counts"]["one_tick_tie"],
                "slower_2plus": desc["tick_class_counts"]["maxmin_slower_by_2plus"],
            }
        )
    return rows


def _cleanup_empty_staging(output: Path) -> None:
    staging_dirs = sorted(
        (path for path in output.rglob(".staging") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in staging_dirs:
        if any(path.iterdir()):
            raise RuntimeError(f"non-empty staging directory remains: {path}")
        path.rmdir()


def _artifact_inventory(
    output: Path, run_lock: core.ExclusiveRunLock
) -> Dict[str, Dict[str, Any]]:
    if any(path.is_dir() and path.name == ".staging" for path in output.rglob("*")):
        raise RuntimeError("staging directory remains before artifact inventory")
    artifacts: Dict[str, Dict[str, Any]] = {}
    for path in sorted(output.rglob("*")):
        if path.is_file():
            relative = path.relative_to(output).as_posix()
            if relative in ("completion_manifest.json", "COMPLETE.json"):
                continue
            artifacts[relative] = _artifact_metadata(path, run_lock)
    return artifacts


def _root_file_names(output: Path) -> set[str]:
    return {path.name for path in output.iterdir() if path.is_file()}


def _verify_root_artifact_set(output: Path, *, mode: str) -> None:
    actual = _root_file_names(output)
    if mode == "partial":
        if not REQUIRED_EARLY_ROOT_FILES.issubset(actual):
            raise RuntimeError(
                f"partial output lacks required root artifacts: "
                f"{sorted(REQUIRED_EARLY_ROOT_FILES - actual)}"
            )
        partial_allowed = PRIOR_FINAL_ROOT_FILES | {"completion_manifest.json"}
        if not actual.issubset(partial_allowed):
            raise RuntimeError(
                f"partial output contains unknown root artifacts: "
                f"{sorted(actual - partial_allowed)}"
            )
        allowed_root_directories = {"checkpoints", "timing_segments", ".staging"}
        actual_root_directories = {
            path.name for path in output.iterdir() if path.is_dir()
        }
        if not actual_root_directories.issubset(allowed_root_directories):
            raise RuntimeError(
                f"partial output contains unknown root directories: "
                f"{sorted(actual_root_directories - allowed_root_directories)}"
            )
        return
    expected = PRIOR_FINAL_ROOT_FILES if mode == "prior_final" else FINAL_ROOT_FILES
    if mode not in ("prior_final", "final"):
        raise RuntimeError(f"unknown root artifact-set mode: {mode}")
    accepted_sets = [set(expected)]
    if mode == "prior_final":
        accepted_sets.append(set(expected) | {"completion_manifest.json"})
    if actual not in accepted_sets:
        raise RuntimeError(
            f"{mode} root artifact inventory changed: "
            f"extra={sorted(actual - expected)} missing={sorted(expected - actual)}"
        )


def _verify_exact_directory_inventory(output: Path) -> None:
    actual = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_dir()
    }
    expected = {"checkpoints", "timing_segments"}
    if actual != expected:
        raise RuntimeError(
            f"output directory inventory changed: extra={sorted(actual - expected)} "
            f"missing={sorted(expected - actual)}"
        )


def _finalize(
    output: Path,
    plan: Mapping[str, Any],
    checkpoints: Mapping[str, Mapping[str, Any]],
    refs: Mapping[str, Any],
    manifest: Mapping[str, Any],
    timing_segments: Sequence[Mapping[str, Any]],
    run_lock: core.ExclusiveRunLock,
) -> Dict[str, Any]:
    _verify_preflight_seal(output, plan, checkpoints, refs, manifest)
    gate = _global_gate(plan, checkpoints, refs)
    analysis = _analyze(checkpoints, refs)
    runtime = _runtime_summary(checkpoints, int(manifest["workers"]), timing_segments)
    paired_rows = _paired_analysis_rows(checkpoints, refs)
    core._atomic_write_once(
        output / "results_long.csv", core._csv_bytes(_flat_result_rows(checkpoints))
    )
    core._atomic_write_once(output / "pairs.csv", core._csv_bytes(paired_rows))
    core._atomic_write_once(
        output / "historical_deltas.csv",
        core._csv_bytes(_historical_delta_rows(checkpoints)),
    )
    core._atomic_write_once(
        output / "equal_comparison.csv",
        core._csv_bytes(_equal_comparison_rows(checkpoints)),
    )
    core._atomic_write_once(
        output / "leave_one_seed_out.csv",
        core._csv_bytes(analysis["leave_one_seed_out"]["rows"]),
    )
    core._atomic_write_once(
        output / "arm_analysis.csv", core._csv_bytes(_arm_export_rows(analysis))
    )
    core._atomic_write_once(
        output / "strata_analysis.csv", core._csv_bytes(_strata_export_rows(analysis))
    )
    core._atomic_json_once(output / "analysis.json", analysis)
    core._atomic_write_once(
        output / "REPORT.md", _analysis_markdown(analysis).encode("utf-8")
    )
    core._atomic_json_once(output / "runtime.json", runtime)
    core._atomic_json_once(output / "gate.json", gate)
    core._atomic_json_once(
        output / "v2_overlap.json", gate["audit_v2_overlap_gate"]
    )
    immutable_after = _verify_immutable_inputs(manifest["immutable_before"])
    if _sha256_file(DRIVER_PATH) != manifest["driver_sha256"]:
        raise RuntimeError("driver changed before final sealing")
    _cleanup_empty_staging(output)
    _verify_exact_directory_inventory(output)
    _verify_root_artifact_set(output, mode="prior_final")
    artifacts = _artifact_inventory(output, run_lock)
    expected_checkpoint_names = {
        f"checkpoints/{pair_id}.json" for pair_id in checkpoints
    }
    if {
        name for name in artifacts if name.startswith("checkpoints/")
    } != expected_checkpoint_names:
        raise RuntimeError("final checkpoint artifact inventory changed")
    expected_timing_names = {
        f"timing_segments/segment_{index:03d}.json"
        for index in range(1, len(timing_segments) + 1)
    }
    if {
        name for name in artifacts if name.startswith("timing_segments/")
    } != expected_timing_names:
        raise RuntimeError("final timing artifact inventory changed")
    completion = {
        "schema": "corrected-proportional-n100-completion-v1",
        "plan_sha256": plan["plan_sha256"],
        "status": analysis["status"],
        "pair_count": PAIR_COUNT,
        "simulation_count": SIMULATION_COUNT,
        "gate": gate,
        "analysis_sha256": artifacts["analysis.json"]["sha256"],
        "runtime": runtime,
        "immutable_after": immutable_after,
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "completion_manifest_self_signed": False,
        "complete_file_self_signed": False,
        "n1000_started": False,
    }
    core._atomic_json_once(output / "completion_manifest.json", completion)
    _cleanup_empty_staging(output)
    complete = {
        "schema": "corrected-proportional-n100-complete-v1",
        "plan_sha256": plan["plan_sha256"],
        "status": analysis["status"],
        "completion_manifest_sha256": _sha256_file(
            output / "completion_manifest.json"
        ),
        "completion_manifest_bytes": (output / "completion_manifest.json").stat().st_size,
        "written_last": True,
        "n1000_started": False,
    }
    core._atomic_json_once(output / "COMPLETE.json", complete)
    _cleanup_empty_staging(output)
    _verify_exact_directory_inventory(output)
    _verify_root_artifact_set(output, mode="final")
    return _verify_complete(output, manifest, run_lock)


def _verify_complete(
    output: Path,
    manifest: Mapping[str, Any],
    run_lock: core.ExclusiveRunLock,
) -> Dict[str, Any]:
    complete_path = output / "COMPLETE.json"
    completion_path = output / "completion_manifest.json"
    if not complete_path.is_file() or not completion_path.is_file():
        raise RuntimeError("completed campaign lacks sealing manifests")
    complete = json.loads(complete_path.read_text(encoding="utf-8"))
    if (
        complete.get("schema") != "corrected-proportional-n100-complete-v1"
        or complete.get("plan_sha256") != manifest["plan_sha256"]
        or complete.get("written_last") is not True
        or complete.get("n1000_started") is not False
        or completion_path.stat().st_size != int(complete["completion_manifest_bytes"])
        or _sha256_file(completion_path) != complete["completion_manifest_sha256"]
    ):
        raise RuntimeError("COMPLETE seal is invalid")
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    if (
        completion.get("schema") != "corrected-proportional-n100-completion-v1"
        or completion.get("plan_sha256") != manifest["plan_sha256"]
        or completion.get("pair_count") != PAIR_COUNT
        or completion.get("simulation_count") != SIMULATION_COUNT
        or completion.get("gate", {}).get("passed") is not True
        or completion.get("n1000_started") is not False
        or completion.get("status") != complete.get("status")
    ):
        raise RuntimeError("completion manifest contract is invalid")
    artifacts = completion.get("artifacts", {})
    if len(artifacts) != int(completion.get("artifact_count", -1)):
        raise RuntimeError("completion artifact count is inconsistent")
    for relative, expected in artifacts.items():
        path = output / relative
        if not path.is_file():
            raise RuntimeError(f"completed artifact changed: {relative}")
        actual = _artifact_metadata(path, run_lock)
        if (
            actual["bytes"] != int(expected["bytes"])
            or actual["sha256"] != expected["sha256"]
        ):
            raise RuntimeError(f"completed artifact changed: {relative}")
    actual_files = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file()
    }
    expected_files = set(artifacts) | {"completion_manifest.json", "COMPLETE.json"}
    if actual_files != expected_files:
        raise RuntimeError(
            f"completed file inventory changed: extra={sorted(actual_files - expected_files)} "
            f"missing={sorted(expected_files - actual_files)}"
        )
    if any(path.is_dir() and path.name == ".staging" for path in output.rglob("*")):
        raise RuntimeError("completed output retains a staging directory")
    _verify_exact_directory_inventory(output)
    _verify_root_artifact_set(output, mode="final")
    if complete_path.stat().st_mtime_ns < completion_path.stat().st_mtime_ns:
        raise RuntimeError("COMPLETE.json was not written after completion_manifest.json")
    _verify_runtime_authorization(manifest)
    if completion.get("immutable_after") != manifest.get("immutable_before"):
        raise RuntimeError("completion immutable snapshot differs from authorization")
    return completion


def dry_run(plan: Mapping[str, Any], output: Path) -> None:
    immutable = _verify_immutable_inputs()
    refs = _reference_indexes()
    driver_hash = _sha256_file(DRIVER_PATH)
    authorization = _authorization_sha256(
        plan,
        output=output,
        workers=8,
        driver_hash=driver_hash,
        immutable=immutable,
    )
    print("CORRECTED PROPORTIONAL N=100 DRY-RUN (NO OUTPUT, NO SIMULATIONS)")
    print(f"output={output}")
    print(f"plan_sha256={plan['plan_sha256']}")
    print(f"authorization_sha256={authorization}")
    print(f"driver_sha256={driver_hash}")
    print(
        f"matrix={ARM_COUNT} arms x 100 seeds x 2 allocators = "
        f"{PAIR_COUNT} pairs / {SIMULATION_COUNT} simulations"
    )
    print(
        f"preflight=33 pairs; historical={refs['historical_pair_count']}/"
        f"{refs['historical_row_count']}; equal={refs['equal_pair_count']}/"
        f"{refs['equal_row_count']}"
    )
    print(f"immutable_snapshot_sha256={_digest(immutable)}")
    command = subprocess.list2cmdline(
        [
            sys.executable,
            str(DRIVER_PATH),
            "--execute",
            "--output",
            str(output),
            "--confirm-plan-sha256",
            authorization,
            "--workers",
            "8",
        ]
    )
    print("AUTHORIZED_EXECUTION_TEMPLATE")
    print(command)
    print("STOP: dry-run completed; no n=1000 mode exists")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--resume", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--confirm-plan-sha256")
    parser.add_argument("--workers", type=int)
    args = parser.parse_args(argv)
    if args.dry_run:
        if args.confirm_plan_sha256 is not None or args.workers is not None:
            parser.error("--dry-run accepts neither confirmation nor workers")
    elif args.execute:
        if args.confirm_plan_sha256 is None or args.workers is None:
            parser.error("--execute requires --confirm-plan-sha256 and --workers")
    elif args.resume:
        if args.confirm_plan_sha256 is not None or args.workers is not None:
            parser.error("--resume reads authorization and workers from its manifest")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    plan = build_plan()
    if args.dry_run:
        output = _validate_output_path(args.output, require_absent=True)
        dry_run(plan, output)
        return 0
    try:
        if args.execute:
            output = _validate_output_path(args.output, require_absent=True)
            completion = execute_or_resume(
                plan,
                output,
                workers=int(args.workers),
                resume=False,
                confirmed_authorization=args.confirm_plan_sha256,
            )
        else:
            output = _validate_output_path(args.output, require_absent=False)
            completion = execute_or_resume(
                plan,
                output,
                workers=None,
                resume=True,
                confirmed_authorization=None,
            )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "STOP_AND_FIX_N100_INTEGRITY_FAILURE",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise
    print(
        json.dumps(
            {
                "schema": completion["schema"],
                "status": completion["status"],
                "pair_count": completion["pair_count"],
                "simulation_count": completion["simulation_count"],
                "artifact_count": completion["artifact_count"],
                "analysis_sha256": completion["analysis_sha256"],
                "completion_manifest_sha256": _sha256_file(
                    output / "completion_manifest.json"
                ),
                "n1000_started": completion["n1000_started"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    print("STOPPED: corrected proportional n=100 complete; n=1000 was not started")
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
