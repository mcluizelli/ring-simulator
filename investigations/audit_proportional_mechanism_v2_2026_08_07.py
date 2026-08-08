"""Post-fix audit of the prospective proportional byte redistributor.

Audit v2 reuses the sealed v1 matrix, but never treats the historical v1
outcomes as an oracle for the corrected mechanism.  It has no full-n100 or
n1000 execution path and writes only to its dedicated investigation tree.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import multiprocessing as mp
import os
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
EXPERIMENTS = ROOT / "experiments"
if str(EXPERIMENTS) not in sys.path:
    sys.path.insert(0, str(EXPERIMENTS))
INVESTIGATIONS = ROOT / "investigations"
if str(INVESTIGATIONS) not in sys.path:
    sys.path.insert(0, str(INVESTIGATIONS))

import audit_proportional_mechanism_2026_08_07 as v1  # noqa: E402
import run_rate_allocator_n100 as n100  # noqa: E402
import sim  # noqa: E402


SCRIPT_PATH = Path(__file__).resolve()
SPEC_PATH = INVESTIGATIONS / "PROPORTIONAL_MECHANISM_AUDIT_V2_SPEC_2026_08_07.md"
OUTPUT_ROOT = (INVESTIGATIONS / "proportional_mechanism_audit_v2").resolve()
V1_SCRIPT_PATH = INVESTIGATIONS / "audit_proportional_mechanism_2026_08_07.py"
V1_SPEC_PATH = INVESTIGATIONS / "PROPORTIONAL_MECHANISM_AUDIT_SPEC_2026_08_07.md"
FIX_CONTRACT_PATH = INVESTIGATIONS / "PROPORTIONAL_EXACT_CURRENT_FIX_CONTRACT_2026_08_07.md"
V1_ROOT = (
    INVESTIGATIONS
    / "proportional_mechanism_audit"
    / "audit_2026-08-07_01"
).resolve()
SEALED_ROOT = (
    INVESTIGATIONS / "rate_allocator_n100" / "n100_2026-08-06_03"
).resolve()

EXPECTED_SOURCE_HASHES = {
    ROOT / "sim.py": "96505cefe2e5aa761b80080d77145bfd384c688ce4a8ca5792f8f7ce17ef59bd",
    ROOT / "experiments" / "run_rate_allocator_n100.py": "7d01a2e598c799b0c533fb650f33b8537f51fa3187f427fcf9ada108d56fd8b4",
    ROOT / "experiments" / "run_rate_allocator_pilot.py": "777018e1a408eb5274d5ee87700fc66e4396fd5d39722f625f22e48840efc431",
}
EXPECTED_REFERENCE_HASHES = {
    FIX_CONTRACT_PATH: "b324de9f5c2f74443334901231df366759097299e84505c39b31e5fa6ce7d6c5",
    V1_SCRIPT_PATH: "7cde3d0892b93b653f76200c40493604141a60dca611da4c368a52668f62a727",
    V1_SPEC_PATH: "076a29c0441a24d331747e3442a129feda1eb718fe77f03c8f45395d40077f05",
    V1_ROOT / "COMPLETE.json": "a6e4c00a80c6bfb179af68f9308e2e91e2fab8aaed6ceda10a09cbe9494419ad",
}
EXPECTED_SEALED_HASHES = dict(v1.EXPECTED_SEALED_HASHES)
EXPECTED_FROZEN_ROOT = v1.EXPECTED_FROZEN_ROOT
EXPECTED_V1_PLAN_SHA256 = "701a1de1782bda0713b28accef415ba4f621d10ba770eb67b446e2641eb7d636"
EXPECTED_N100_PLAN_SHA256 = "47099eedb41d1574cc49a6e08a2f7bb20b6c14077531b32b80222be9519291ac"

ARM_IDS = tuple(v1.ARM_IDS)
SAMPLE_IDS = tuple(v1.SAMPLE_IDS)
WINDOWS_S = tuple(v1.WINDOWS_S)
EXPECTED_WINDOW_TICKS = dict(v1.EXPECTED_WINDOW_TICKS)
ALLOCATORS = tuple(v1.ALLOCATORS)
PRODUCTION_WINDOW_S = v1.PRODUCTION_WINDOW_S
CONSERVATION_TOLERANCE_B = v1.CONSERVATION_TOLERANCE_B
SHADOW_WEIGHT_TOLERANCE = v1.SHADOW_WEIGHT_TOLERANCE
MAX_STEPS = v1.MAX_STEPS
REQUIRED_DEFECT_COVERAGE = (
    (
        "proportional_3tier_os4_p64_k16",
        33,
        sim.RATE_ALLOCATOR_LINK_LOCAL,
    ),
    (
        "proportional_2tier_p64_k8",
        66,
        sim.RATE_ALLOCATOR_NETWORK_MAXMIN,
    ),
)

_WORKER_SCRIPT_HASH = ""
_WORKER_SPEC_HASH = ""


def _sha256_file(path: Path) -> str:
    return v1._sha256_file(path)


def _digest(value: Any) -> str:
    return v1._digest(value)


def _f64_hex(value: Any) -> str:
    return v1._f64_hex(value)


def _hexify_floats(value: Any) -> Any:
    return v1._hexify_floats(value)


def _read_json(path: Path) -> Dict[str, Any]:
    return v1._read_json(path)


def _atomic_write_text(path: Path, text: str) -> None:
    v1._atomic_write_text(path, text)


def _write_json(path: Path, value: Any) -> None:
    v1._write_json(path, value)


def _assert_shared_constants() -> None:
    expected = (
        tuple(v1.ARM_IDS),
        tuple(v1.SAMPLE_IDS),
        tuple(v1.WINDOWS_S),
        tuple(v1.ALLOCATORS),
        v1.PRODUCTION_WINDOW_S,
        v1.CONSERVATION_TOLERANCE_B,
        v1.SHADOW_WEIGHT_TOLERANCE,
    )
    actual = (
        ARM_IDS,
        SAMPLE_IDS,
        WINDOWS_S,
        ALLOCATORS,
        PRODUCTION_WINDOW_S,
        CONSERVATION_TOLERANCE_B,
        SHADOW_WEIGHT_TOLERANCE,
    )
    if _hexify_floats(actual) != _hexify_floats(expected):
        raise RuntimeError("v2 constants drifted from the sealed v1 matrix")


def _v1_bundle_inventory() -> Dict[str, Any]:
    complete = _read_json(V1_ROOT / "COMPLETE.json")
    if complete.get("schema") != "proportional-mechanism-audit-complete-v1":
        raise RuntimeError("unexpected v1 completion schema")
    if complete.get("status") != "STOP_BEFORE_N1000_AND_REVIEW":
        raise RuntimeError("unexpected v1 decision")
    if complete.get("plan_sha256") != EXPECTED_V1_PLAN_SHA256:
        raise RuntimeError("unexpected v1 plan seal")
    artifacts = complete.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise RuntimeError("v1 completion seal has no artifacts")
    expected_names = set(artifacts) | {"COMPLETE.json"}
    actual_files = {
        path.relative_to(V1_ROOT).as_posix()
        for path in V1_ROOT.rglob("*")
        if path.is_file()
    }
    if actual_files != expected_names:
        raise RuntimeError(
            f"v1 artifact inventory changed: {sorted(actual_files ^ expected_names)}"
        )
    inventory = []
    for name, expected in sorted(artifacts.items()):
        path = V1_ROOT / name
        actual_hash = _sha256_file(path)
        actual_bytes = path.stat().st_size
        if actual_hash != expected["sha256"] or actual_bytes != int(expected["bytes"]):
            raise RuntimeError(f"v1 artifact integrity mismatch: {name}")
        inventory.append(
            {"relative_path": name, "bytes": actual_bytes, "sha256": actual_hash}
        )
    complete_path = V1_ROOT / "COMPLETE.json"
    inventory.append(
        {
            "relative_path": "COMPLETE.json",
            "bytes": complete_path.stat().st_size,
            "sha256": _sha256_file(complete_path),
        }
    )
    inventory.sort(key=lambda row: row["relative_path"])
    return {
        "status": complete["status"],
        "plan_sha256": complete["plan_sha256"],
        "file_count": len(inventory),
        "root_sha256": _digest(inventory),
        "files": inventory,
    }


def build_plan() -> Dict[str, Any]:
    _assert_shared_constants()
    v1_manifest = _read_json(V1_ROOT / "run_manifest.json")
    source_plan = v1_manifest.get("plan")
    if not isinstance(source_plan, dict):
        raise RuntimeError("v1 run manifest lacks its plan")
    if source_plan.get("plan_sha256") != EXPECTED_V1_PLAN_SHA256:
        raise RuntimeError("v1 run manifest plan hash changed")
    unsigned_v1_plan = dict(source_plan)
    unsigned_v1_plan.pop("plan_sha256", None)
    if _digest(unsigned_v1_plan) != EXPECTED_V1_PLAN_SHA256:
        raise RuntimeError("v1 embedded plan no longer self-verifies")

    current = n100.build_plan()
    if current.get("plan_sha256") != EXPECTED_N100_PLAN_SHA256:
        raise RuntimeError("current n=100 plan changed")
    current_pairs = {
        pair["pair_id"]: pair for pair in current["pairs"]
    }
    selected_pairs = copy.deepcopy(source_plan["selected_pairs"])
    jobs = copy.deepcopy(source_plan["jobs"])
    if len(selected_pairs) != 30 or len(jobs) != 90:
        raise RuntimeError("v1 matrix cardinality changed")
    for pair in selected_pairs:
        current_pair = current_pairs.get(pair["pair_id"])
        if current_pair is None:
            raise RuntimeError(f"current plan lacks {pair['pair_id']}")
        if _hexify_floats(current_pair) != _hexify_floats(pair):
            raise RuntimeError(f"current pair specification drifted: {pair['pair_id']}")
    expected_case_ids = {job["case_id"] for job in jobs}
    if len(expected_case_ids) != 90:
        raise RuntimeError("v2 case IDs are not unique")
    for job in jobs:
        if job["pair"]["pair_id"] != job["source_pair_id"]:
            raise RuntimeError(f"job/pair mismatch: {job['case_id']}")
        expected_ticks = EXPECTED_WINDOW_TICKS[float(job["window_s"])]
        if int(job["window_ticks"]) != expected_ticks:
            raise RuntimeError(f"window tick drift: {job['case_id']}")

    plan: Dict[str, Any] = {
        "schema": "proportional-mechanism-audit-plan-v2",
        "purpose": "post_fix_static_core_diagnostic_not_a_paper_estimator",
        "source_v1_plan_sha256": source_plan["plan_sha256"],
        "source_n100_plan_sha256": current["plan_sha256"],
        "arm_ids": list(ARM_IDS),
        "sample_ids": list(SAMPLE_IDS),
        "windows_s": list(WINDOWS_S),
        "window_ticks": [EXPECTED_WINDOW_TICKS[w] for w in WINDOWS_S],
        "allocators": list(ALLOCATORS),
        "source_pair_count": len(selected_pairs),
        "window_job_count": len(jobs),
        "traced_simulation_count": len(jobs) * len(ALLOCATORS),
        "production_window_trace_count": len(selected_pairs) * len(ALLOCATORS),
        "fresh_pair_worker_count": len(selected_pairs),
        "historical_delta_row_count": len(selected_pairs) * len(ALLOCATORS),
        "selected_pairs": selected_pairs,
        "jobs": jobs,
        "hard_gate": {
            "conservation_tolerance_B": CONSERVATION_TOLERANCE_B,
            "snapshot_shadow_weight_tolerance": SHADOW_WEIGHT_TOLERANCE,
            "one_ms_sidecar_production_binary64_equivalence": True,
            "one_ms_fresh_worker_bridge_equivalence": True,
            "strict_v1_historical_bijection": True,
        },
        "sensitivity_gate": copy.deepcopy(source_plan["sensitivity_gate"]),
        "no_full_n100_execution_path": True,
        "no_n1000_execution_path": True,
        "mutates_v1": False,
        "mutates_frozen_results": False,
    }
    plan["plan_sha256"] = _digest(plan)
    return plan


def _verify_plan_integrity(plan: Mapping[str, Any]) -> str:
    claimed = plan.get("plan_sha256")
    if not isinstance(claimed, str):
        raise RuntimeError("v2 plan lacks its digest")
    unsigned = copy.deepcopy(dict(plan))
    unsigned.pop("plan_sha256", None)
    actual = _digest(unsigned)
    if actual != claimed:
        raise RuntimeError(f"v2 plan digest mismatch: {actual} != {claimed}")
    return actual


def _verify_canonical_plan(plan: Mapping[str, Any]) -> None:
    canonical = build_plan()
    if _hexify_floats(plan) != _hexify_floats(canonical):
        raise RuntimeError("v2 plan is self-consistent but not the canonical frozen matrix")


def authorization_sha256(plan: Mapping[str, Any]) -> str:
    verified_plan_sha256 = _verify_plan_integrity(plan)
    _verify_canonical_plan(plan)
    return _digest(
        {
            "plan_sha256": verified_plan_sha256,
            "audit_script_sha256": _sha256_file(SCRIPT_PATH),
            "spec_sha256": _sha256_file(SPEC_PATH),
            "source_sha256": {
                path.relative_to(ROOT).as_posix(): expected
                for path, expected in EXPECTED_SOURCE_HASHES.items()
            },
            "reference_sha256": {
                path.relative_to(ROOT).as_posix(): expected
                for path, expected in EXPECTED_REFERENCE_HASHES.items()
            },
            "v1_root_sha256": _v1_bundle_inventory()["root_sha256"],
        }
    )


def verify_immutable_inputs(plan: Mapping[str, Any]) -> Dict[str, Any]:
    _verify_plan_integrity(plan)
    _verify_canonical_plan(plan)
    for path, expected in {
        **EXPECTED_SOURCE_HASHES,
        **EXPECTED_REFERENCE_HASHES,
        **EXPECTED_SEALED_HASHES,
    }.items():
        actual = _sha256_file(path)
        if actual != expected:
            raise RuntimeError(
                f"immutable input changed: {path.relative_to(ROOT)} {actual} != {expected}"
            )
    v1_bundle = _v1_bundle_inventory()
    frozen = n100.core.audit_frozen_csvs()
    if frozen["root_sha256"] != EXPECTED_FROZEN_ROOT or frozen["mismatches"] != 0:
        raise RuntimeError(f"frozen-result integrity failed: {frozen}")
    sealed_inventory = v1._validate_selected_checkpoint_inventory(
        plan["selected_pairs"]
    )
    if sealed_inventory["plan_sha256"] != plan["source_n100_plan_sha256"]:
        raise RuntimeError("selected sealed checkpoints use a different plan")
    return {
        "audit_sources": {
            "audit_script_sha256": _sha256_file(SCRIPT_PATH),
            "spec_sha256": _sha256_file(SPEC_PATH),
        },
        "source_sha256": {
            path.relative_to(ROOT).as_posix(): _sha256_file(path)
            for path in EXPECTED_SOURCE_HASHES
        },
        "reference_sha256": {
            path.relative_to(ROOT).as_posix(): _sha256_file(path)
            for path in EXPECTED_REFERENCE_HASHES
        },
        "v1_bundle": v1_bundle,
        "frozen_results": frozen,
        "sealed_inventory": sealed_inventory,
    }


def _validate_output_path(raw: str, *, require_absent: bool) -> Path:
    resolved = Path(raw)
    if not resolved.is_absolute():
        resolved = ROOT / resolved
    resolved = resolved.resolve()
    if resolved == OUTPUT_ROOT or OUTPUT_ROOT not in resolved.parents:
        raise RuntimeError(f"output must be a child of {OUTPUT_ROOT}")
    forbidden = ((ROOT / "results").resolve(), V1_ROOT, SEALED_ROOT)
    for root in forbidden:
        if resolved == root or root in resolved.parents or resolved in root.parents:
            raise RuntimeError(f"output overlaps forbidden tree: {root}")
    if require_absent and resolved.exists():
        raise FileExistsError(f"refusing existing output {resolved}")
    return resolved


def _flat_artifact_names(output: Path) -> set[str]:
    directories = [path for path in output.rglob("*") if path.is_dir()]
    if directories:
        relative = sorted(path.relative_to(output).as_posix() for path in directories)
        raise RuntimeError(f"unexpected v2 artifact directories: {relative}")
    files = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file()
    }
    if any("/" in name for name in files):
        raise RuntimeError("nested v2 artifacts are forbidden")
    return files


def _edge_rows(mapping: Mapping[Any, Any]) -> List[Tuple[str, Any]]:
    return sorted((repr(key), value) for key, value in mapping.items())


def _boundary_state(engine: sim.FlowLevelSimulator) -> Dict[str, Any]:
    congestion_state = None
    if engine.congestion is not None:
        congestion_state = copy.deepcopy(vars(engine.congestion))
    return {
        "time_s": float(engine.time_s),
        "flows": [
            {
                "fid": int(fid),
                "five_tuple": {
                    "src": repr(flow.five_tuple.src),
                    "dst": repr(flow.five_tuple.dst),
                    "sport": int(flow.five_tuple.sport),
                    "dport": int(flow.five_tuple.dport),
                    "proto": int(flow.five_tuple.proto),
                },
                "path": [repr(node) for node in flow.path],
                "remaining_bytes": float(flow.remaining_bytes),
                "sent_bytes": float(flow.sent_bytes),
                "last_rate_Bps": float(flow.last_rate_Bps),
            }
            for fid, flow in engine.flows.items()
        ],
        "edge_bytes_sent": _edge_rows(engine.edge_bytes_sent),
        "maxmin_active_key": engine._maxmin_active_key,
        "maxmin_flow_edges": _edge_rows(engine._maxmin_flow_edges),
        "maxmin_link_users": _edge_rows(engine._maxmin_link_users),
        "next_fid": int(engine._next_fid),
        "dt_s": float(engine.dt_s),
        "rate_allocator": engine.rate_allocator,
        "topology_sha256": n100.core._topology_digest(engine.topo),
        "congestion": congestion_state,
    }


def _boundary_state_sha256(engine: sim.FlowLevelSimulator) -> str:
    return _digest(_hexify_floats(_boundary_state(engine)))


def _normalized_weights(rates: Sequence[float]) -> Tuple[List[float], float]:
    finite = [float(rate) for rate in rates]
    total = sum(finite)
    if total <= 0.0:
        return [0.0 for _ in finite], total
    return [rate / total for rate in finite], total


def _production_candidate_fids(
    engine: sim.FlowLevelSimulator,
    live_ring_fids: set[int],
    ring_fid_set: set[int],
) -> List[int]:
    return [
        fid
        for fid, flow in engine.flows.items()
        if fid in live_ring_fids
        or (fid not in ring_fid_set and flow.remaining_bytes > 0.0)
    ]


def _expected_candidate_fids(
    engine: sim.FlowLevelSimulator,
    groups: Sequence[Sequence[int]],
    ring_fid_set: set[int],
) -> List[int]:
    """Derive expected membership independently from group liveness."""
    expected_members: set[int] = set()
    for fids in groups:
        remaining = sum(
            max(0.0, float(engine.flows[fid].remaining_bytes)) for fid in fids
        )
        if remaining > 0.0:
            expected_members.update(fids)
    expected_members.update(
        fid
        for fid, flow in engine.flows.items()
        if fid not in ring_fid_set and flow.remaining_bytes > 0.0
    )
    return [fid for fid in engine.flows if fid in expected_members]


def _run_trace(
    pair: Mapping[str, Any], config: Mapping[str, Any], allocator: str
) -> Dict[str, Any]:
    if config["family"] != "static_split" or config["runner"] != "proportional":
        raise RuntimeError("v2 accepts static proportional cells only")
    if config.get("congestion") is not None or config.get("background") is not None:
        raise RuntimeError("v2 static audit does not authorize dynamic traffic")

    topo, ring = n100._make_topology_and_ring(config)
    topology_sha = n100.core._topology_digest(topo)
    ring_sha = n100.core._ring_digest(ring)
    route_sha = n100.core._route_digest(config, topo, ring)
    engine = sim.FlowLevelSimulator(
        topo,
        dt_s=float(config["dt_s"]),
        rate_allocator=allocator,
    )
    k = int(config["k"])
    target = float(config["bytes_per_neighbor"])
    ring_fids = sim.add_ring_neighbor_flows(
        engine, ring, target, flows_per_neighbor=k
    )
    ring_fid_set = set(ring_fids)
    pathless = sum(not engine._flow_edges(engine.flows[fid]) for fid in ring_fids)
    if pathless:
        raise RuntimeError("v2 encountered a pathless controlled QP")
    groups = [
        ring_fids[index : index + k]
        for index in range(0, len(ring_fids), k)
    ]
    if len(groups) != int(config["ring_size"]):
        raise RuntimeError("logical-edge grouping changed")
    window_ticks = max(
        1,
        int(
            round(
                float(config["redistribution_window_s"])
                / float(config["dt_s"])
            )
        ),
    )

    final_zero_step: Dict[int, int | None] = {fid: None for fid in ring_fids}
    candidate_history: List[List[int]] = []
    metrics: Dict[str, Any] = {
        "snapshot_boundary_count": 0,
        "snapshot_call_count": 0,
        "redistribution_live_group_count": 0,
        "idle_qp_boundary_observation_count": 0,
        "reactivation_count": 0,
        "reactivated_bytes_B": 0.0,
        "maximum_idle_assignment_fraction": 0.0,
        "candidate_set_mismatch_count": 0,
        "snapshot_key_mismatch_count": 0,
        "snapshot_state_mutation_count": 0,
        "snapshot_oracle_rate_binary64_mismatch_count": 0,
        "snapshot_oracle_weight_mismatch_count": 0,
        "maximum_snapshot_oracle_weight_abs_difference": 0.0,
        "counterfactual_retained_weight_mismatch_count": 0,
        "maximum_counterfactual_retained_weight_difference": 0.0,
        "negative_snapshot_rate_count": 0,
        "nonfinite_snapshot_rate_count": 0,
        "negative_shadow_rate_count": 0,
        "nonfinite_shadow_rate_count": 0,
        "zero_rate_live_group_count": 0,
        "pathless_controlled_qp_count": pathless,
        "maximum_inflight_conservation_error_B": 0.0,
        "maximum_redistribution_sum_error_B": 0.0,
        "minimum_remaining_bytes_B": 0.0,
    }

    steps = 0
    while steps < MAX_STEPS:
        if all(engine.flows[fid].remaining_bytes <= 0.0 for fid in ring_fids):
            break

        active_before = {
            fid for fid in ring_fids if engine.flows[fid].remaining_bytes > 0.0
        }
        engine.step()
        steps += 1
        for fid in active_before:
            if engine.flows[fid].remaining_bytes <= 0.0:
                final_zero_step[fid] = steps
        metrics["minimum_remaining_bytes_B"] = min(
            metrics["minimum_remaining_bytes_B"],
            min(float(engine.flows[fid].remaining_bytes) for fid in ring_fids),
        )

        if k <= 1 or not (steps == 1 or steps % window_ticks == 0):
            continue

        live_groups: List[Tuple[List[int], List[sim.Flow], float]] = []
        for fids in groups:
            flows = [engine.flows[fid] for fid in fids]
            remaining = sum(max(0.0, float(flow.remaining_bytes)) for flow in flows)
            sent = sum(float(flow.sent_bytes) for flow in flows)
            metrics["maximum_inflight_conservation_error_B"] = max(
                metrics["maximum_inflight_conservation_error_B"],
                abs(sent + remaining - target),
            )
            if remaining > 0.0:
                live_groups.append((fids, flows, remaining))
        if not live_groups:
            continue

        live_ring_fids = {
            fid for fids, _, _ in live_groups for fid in fids
        }
        candidate_fids = _production_candidate_fids(
            engine, live_ring_fids, ring_fid_set
        )
        expected_candidate_fids = _expected_candidate_fids(
            engine, groups, ring_fid_set
        )
        if (
            candidate_fids != expected_candidate_fids
            or len(candidate_fids) != len(set(candidate_fids))
        ):
            metrics["candidate_set_mismatch_count"] += 1
        candidate_history.append(list(candidate_fids))
        metrics["snapshot_boundary_count"] += 1

        state_before = _boundary_state_sha256(engine)
        used_rates = engine.snapshot_flow_rates(candidate_fids)
        metrics["snapshot_call_count"] += 1
        state_after_used = _boundary_state_sha256(engine)
        shadow_rates = v1._prospective_rates(engine, candidate_fids)
        state_after_shadow = _boundary_state_sha256(engine)
        if state_before != state_after_used:
            metrics["snapshot_state_mutation_count"] += 1
        if state_after_used != state_after_shadow:
            metrics["snapshot_state_mutation_count"] += 1
        if list(used_rates) != candidate_fids or list(shadow_rates) != candidate_fids:
            metrics["snapshot_key_mismatch_count"] += 1

        for fids, flows, remaining in live_groups:
            metrics["redistribution_live_group_count"] += 1
            used = [float(used_rates[fid]) for fid in fids]
            shadow = [float(shadow_rates[fid]) for fid in fids]
            retained = [float(flow.last_rate_Bps) for flow in flows]
            metrics["negative_snapshot_rate_count"] += sum(rate < 0.0 for rate in used)
            metrics["nonfinite_snapshot_rate_count"] += sum(
                not math.isfinite(rate) for rate in used
            )
            metrics["negative_shadow_rate_count"] += sum(rate < 0.0 for rate in shadow)
            metrics["nonfinite_shadow_rate_count"] += sum(
                not math.isfinite(rate) for rate in shadow
            )
            if any(rate < 0.0 or not math.isfinite(rate) for rate in used + shadow):
                continue

            used_weights, used_sum = _normalized_weights(used)
            shadow_weights, shadow_sum = _normalized_weights(shadow)
            retained_weights, _ = v1._normalized_weights(retained)
            metrics["snapshot_oracle_rate_binary64_mismatch_count"] += sum(
                _f64_hex(actual) != _f64_hex(expected)
                for actual, expected in zip(used, shadow)
            )
            for used_weight, shadow_weight, retained_weight in zip(
                used_weights, shadow_weights, retained_weights
            ):
                shadow_difference = abs(used_weight - shadow_weight)
                metrics["maximum_snapshot_oracle_weight_abs_difference"] = max(
                    metrics["maximum_snapshot_oracle_weight_abs_difference"],
                    shadow_difference,
                )
                if shadow_difference > SHADOW_WEIGHT_TOLERANCE:
                    metrics["snapshot_oracle_weight_mismatch_count"] += 1
                retained_difference = abs(used_weight - retained_weight)
                metrics["maximum_counterfactual_retained_weight_difference"] = max(
                    metrics["maximum_counterfactual_retained_weight_difference"],
                    retained_difference,
                )
                if retained_difference > SHADOW_WEIGHT_TOLERANCE:
                    metrics["counterfactual_retained_weight_mismatch_count"] += 1

            if used_sum <= 0.0:
                metrics["zero_rate_live_group_count"] += 1
                continue
            if shadow_sum <= 0.0:
                metrics["snapshot_oracle_weight_mismatch_count"] += len(fids)

            before = [float(flow.remaining_bytes) for flow in flows]
            after = [remaining * weight for weight in used_weights]
            idle_bytes = 0.0
            for fid, flow, old_remaining, new_remaining in zip(
                fids, flows, before, after
            ):
                if old_remaining <= 0.0:
                    metrics["idle_qp_boundary_observation_count"] += 1
                    if new_remaining > 0.0:
                        metrics["reactivation_count"] += 1
                        idle_bytes += new_remaining
                flow.remaining_bytes = new_remaining
                if new_remaining > 0.0 and old_remaining <= 0.0:
                    final_zero_step[fid] = None
                elif new_remaining <= 0.0 and old_remaining > 0.0:
                    final_zero_step[fid] = steps
            metrics["reactivated_bytes_B"] += idle_bytes
            metrics["maximum_idle_assignment_fraction"] = max(
                metrics["maximum_idle_assignment_fraction"],
                idle_bytes / remaining,
            )
            metrics["maximum_redistribution_sum_error_B"] = max(
                metrics["maximum_redistribution_sum_error_B"],
                abs(sum(float(flow.remaining_bytes) for flow in flows) - remaining),
            )
    else:
        raise RuntimeError("v2 traced proportional transfer exceeded max_steps")

    delivered = [
        sum(float(engine.flows[fid].sent_bytes) for fid in fids) for fids in groups
    ]
    final_remaining = [
        sum(max(0.0, float(engine.flows[fid].remaining_bytes)) for fid in fids)
        for fids in groups
    ]
    final_errors = [abs(value - target) for value in delivered]
    final_finish_spreads = []
    for fids in groups:
        ticks = [final_zero_step[fid] for fid in fids]
        if any(tick is None for tick in ticks):
            raise RuntimeError("a controlled QP has no final completion tick")
        final_finish_spreads.append(max(ticks) - min(ticks))
    metrics.update(
        {
            "candidate_sequence_sha256": _digest(candidate_history),
            "final_conservation_max_error_B": max(final_errors, default=0.0),
            "final_remaining_max_B": max(final_remaining, default=0.0),
            "maximum_final_qp_finish_spread_ticks": max(
                final_finish_spreads, default=0
            ),
        }
    )
    return {
        "audit_version": 2,
        "rate_source": "snapshot_flow_rates",
        "case_id": None,
        "source_pair_id": pair["pair_id"],
        "arm_id": config["arm_id"],
        "sample_id": int(config["sample_id"]),
        "allocator": allocator,
        "window_s": float(config["redistribution_window_s"]),
        "window_ticks": window_ticks,
        "completion_time_s": float(engine.time_s),
        "completion_time_hex": _f64_hex(engine.time_s),
        "simulated_ticks": steps,
        "config_sha256": n100.core._digest(config),
        "topology_sha256": topology_sha,
        "ring_sha256": ring_sha,
        "route_sha256": route_sha,
        "delivered_bytes_hex": [_f64_hex(value) for value in delivered],
        "delivered_vector_sha256": _digest([_f64_hex(value) for value in delivered]),
        "metrics": metrics,
    }


def _run_corrected_production(
    config: Mapping[str, Any], allocator: str
) -> Dict[str, Any]:
    return v1._run_direct_production(config, allocator)


def _verify_worker_sources() -> None:
    for path, expected in {
        **EXPECTED_SOURCE_HASHES,
        **EXPECTED_REFERENCE_HASHES,
    }.items():
        if _sha256_file(path) != expected:
            raise RuntimeError(f"immutable source changed inside worker: {path}")
    if _sha256_file(SCRIPT_PATH) != _WORKER_SCRIPT_HASH:
        raise RuntimeError("v2 audit script changed inside worker")
    if _sha256_file(SPEC_PATH) != _WORKER_SPEC_HASH:
        raise RuntimeError("v2 audit specification changed inside worker")


def _worker_init(script_hash: str, spec_hash: str) -> None:
    global _WORKER_SCRIPT_HASH, _WORKER_SPEC_HASH
    _WORKER_SCRIPT_HASH = script_hash
    _WORKER_SPEC_HASH = spec_hash
    n100._worker_init(
        EXPECTED_SOURCE_HASHES[ROOT / "sim.py"],
        EXPECTED_SOURCE_HASHES[ROOT / "experiments" / "run_rate_allocator_n100.py"],
        EXPECTED_SOURCE_HASHES[ROOT / "experiments" / "run_rate_allocator_pilot.py"],
    )
    _verify_worker_sources()


def _run_job(job: Mapping[str, Any]) -> Dict[str, Any]:
    _verify_worker_sources()
    traces = []
    production = []
    for allocator in job["pair"]["execution_order"]:
        trace = _run_trace(job["pair"], job["config"], allocator)
        trace["case_id"] = job["case_id"]
        traces.append(trace)
        if float(job["window_s"]) == PRODUCTION_WINDOW_S:
            direct = _run_corrected_production(job["config"], allocator)
            direct["allocator"] = allocator
            production.append(direct)
    fresh_pair = None
    if float(job["window_s"]) == PRODUCTION_WINDOW_S:
        fresh_pair = n100._run_pair_worker(job["pair"])
    _verify_worker_sources()
    return {
        "case_id": job["case_id"],
        "source_pair_id": job["source_pair_id"],
        "pair_spec": copy.deepcopy(job["pair"]),
        "window_s": float(job["window_s"]),
        "traces": traces,
        "direct_production": production,
        "fresh_pair_worker": fresh_pair,
    }


def _validate_one_ms_equivalence(result: Mapping[str, Any]) -> Dict[str, Any]:
    if float(result["window_s"]) != PRODUCTION_WINDOW_S:
        raise RuntimeError("1 ms equivalence called outside the production window")
    if len(result["traces"]) != len(ALLOCATORS):
        raise RuntimeError("sidecar row cardinality changed")
    if len(result["direct_production"]) != len(ALLOCATORS):
        raise RuntimeError("direct-production row cardinality changed")
    trace_by_allocator = {row["allocator"]: row for row in result["traces"]}
    direct_by_allocator = {
        row["allocator"]: row for row in result["direct_production"]
    }
    if set(trace_by_allocator) != set(ALLOCATORS):
        raise RuntimeError("sidecar lacks an allocator")
    if set(direct_by_allocator) != set(ALLOCATORS):
        raise RuntimeError("direct production lacks an allocator")

    fresh = result["fresh_pair_worker"]
    if fresh is None or fresh.get("pair_id") != result["source_pair_id"]:
        raise RuntimeError("fresh paired-worker replay is missing")
    if _hexify_floats(fresh.get("pair_spec")) != _hexify_floats(
        result["pair_spec"]
    ):
        raise RuntimeError(f"fresh pair specification changed: {result['source_pair_id']}")
    expected_pair_gate = {
        "passed": True,
        "initial_digests_equal": True,
        "mutable_instances_distinct": True,
    }
    if fresh.get("pair_gate") != expected_pair_gate:
        raise RuntimeError(f"fresh pair gate changed: {result['source_pair_id']}")
    if len(fresh.get("rows", [])) != len(ALLOCATORS):
        raise RuntimeError("fresh paired-worker row cardinality changed")
    fresh_rows = {row["allocator"]: row for row in fresh["rows"]}
    if set(fresh_rows) != set(ALLOCATORS):
        raise RuntimeError("fresh paired worker lacks an allocator")

    projections = []
    for allocator in ALLOCATORS:
        trace = trace_by_allocator[allocator]
        direct = direct_by_allocator[allocator]
        worker = fresh_rows[allocator]
        if trace["completion_time_hex"] != direct["completion_time_hex"]:
            raise RuntimeError(
                f"sidecar/direct completion mismatch: {result['case_id']} {allocator}"
            )
        if trace["delivered_bytes_hex"] != direct["delivered_bytes_hex"]:
            raise RuntimeError(
                f"sidecar/direct delivery mismatch: {result['case_id']} {allocator}"
            )
        if worker["completion_time_hex"] != trace["completion_time_hex"]:
            raise RuntimeError(
                f"worker/sidecar completion mismatch: {result['case_id']} {allocator}"
            )
        if int(worker["simulated_ticks"]) != int(trace["simulated_ticks"]):
            raise RuntimeError(
                f"worker/sidecar tick mismatch: {result['case_id']} {allocator}"
            )
        for field in (
            "config_sha256",
            "topology_sha256",
            "ring_sha256",
            "route_sha256",
        ):
            if worker[field] != trace[field]:
                raise RuntimeError(
                    f"worker/sidecar {field} mismatch: {result['case_id']} {allocator}"
                )
        conservation = worker.get("conservation", {})
        if not conservation.get("passed"):
            raise RuntimeError(
                f"fresh worker conservation failed: {result['case_id']} {allocator}"
            )
        remaining_foreground = float(
            conservation.get("remaining_foreground_bytes", math.inf)
        )
        maximum_conservation_error = float(
            conservation.get("maximum_abs_error_bytes", math.inf)
        )
        if not math.isfinite(remaining_foreground) or not math.isfinite(
            maximum_conservation_error
        ):
            raise RuntimeError(
                f"fresh worker non-finite conservation: {result['case_id']} {allocator}"
            )
        if remaining_foreground != 0.0:
            raise RuntimeError(
                f"fresh worker retained bytes: {result['case_id']} {allocator}"
            )
        if maximum_conservation_error > CONSERVATION_TOLERANCE_B:
            raise RuntimeError(
                f"fresh worker conservation tolerance: {result['case_id']} {allocator}"
            )
        if _f64_hex(maximum_conservation_error) != _f64_hex(
            trace["metrics"]["final_conservation_max_error_B"]
        ):
            raise RuntimeError(
                f"worker/sidecar conservation mismatch: {result['case_id']} {allocator}"
            )
        projections.append(
            {
                "pair_id": result["source_pair_id"],
                "case_id": result["case_id"],
                "allocator": allocator,
                "completion_time_hex": trace["completion_time_hex"],
                "simulated_ticks": int(trace["simulated_ticks"]),
                "delivered_bytes_hex": trace["delivered_bytes_hex"],
                "delivered_vector_sha256": trace["delivered_vector_sha256"],
                "config_sha256": trace["config_sha256"],
                "topology_sha256": trace["topology_sha256"],
                "ring_sha256": trace["ring_sha256"],
                "route_sha256": trace["route_sha256"],
                "worker_conservation": conservation,
                "sidecar_direct_exact": True,
                "worker_bridge_exact": True,
            }
        )
    return {
        "pair_id": result["source_pair_id"],
        "case_id": result["case_id"],
        "sidecar_direct_exact_rows": 2,
        "worker_bridge_exact_rows": 2,
        "projections": projections,
        "direct_production": result["direct_production"],
        "fresh_pair_worker": fresh,
    }


def _hard_gate(traces: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    failures: List[str] = []
    expected_keys = {
        (arm_id, sample_id, allocator, window_s)
        for arm_id in ARM_IDS
        for sample_id in SAMPLE_IDS
        for allocator in ALLOCATORS
        for window_s in WINDOWS_S
    }
    actual_keys = {
        (
            row["arm_id"],
            int(row["sample_id"]),
            row["allocator"],
            float(row["window_s"]),
        )
        for row in traces
    }
    if len(traces) != 180 or actual_keys != expected_keys:
        failures.append(
            f"trace matrix mismatch: rows={len(traces)} unique_keys={len(actual_keys)}"
        )

    for arm_id in ARM_IDS:
        for sample_id in SAMPLE_IDS:
            cell = [
                row
                for row in traces
                if row["arm_id"] == arm_id and int(row["sample_id"]) == sample_id
            ]
            if len(cell) != 6:
                continue
            for field in ("topology_sha256", "ring_sha256", "route_sha256"):
                if len({row[field] for row in cell}) != 1:
                    failures.append(
                        f"{field} changed across windows/allocators: {arm_id} seed={sample_id}"
                    )
            for window_s in WINDOWS_S:
                paired = [row for row in cell if float(row["window_s"]) == window_s]
                if len(paired) != 2:
                    failures.append(
                        f"allocator pair missing: {arm_id} seed={sample_id} window={window_s}"
                    )
                elif len({row["config_sha256"] for row in paired}) != 1:
                    failures.append(
                        f"config differs between allocators: {arm_id} seed={sample_id} window={window_s}"
                    )
            if len({row["config_sha256"] for row in cell}) != 3:
                failures.append(
                    f"window configs are not three distinct snapshots: {arm_id} seed={sample_id}"
                )

    counter_keys = (
        "candidate_set_mismatch_count",
        "snapshot_key_mismatch_count",
        "snapshot_state_mutation_count",
        "snapshot_oracle_rate_binary64_mismatch_count",
        "snapshot_oracle_weight_mismatch_count",
        "negative_snapshot_rate_count",
        "nonfinite_snapshot_rate_count",
        "negative_shadow_rate_count",
        "nonfinite_shadow_rate_count",
        "pathless_controlled_qp_count",
    )
    totals = {key: 0 for key in counter_keys}
    totals.update(
        {
            "snapshot_boundary_count": 0,
            "snapshot_call_count": 0,
            "zero_rate_live_group_count": 0,
            "reactivation_count": 0,
            "counterfactual_retained_weight_mismatch_count": 0,
        }
    )
    maxima = {
        "final_conservation_max_error_B": 0.0,
        "maximum_inflight_conservation_error_B": 0.0,
        "maximum_redistribution_sum_error_B": 0.0,
        "maximum_snapshot_oracle_weight_abs_difference": 0.0,
        "maximum_counterfactual_retained_weight_difference": 0.0,
    }
    for row in traces:
        metrics = row["metrics"]
        if row.get("audit_version") != 2 or row.get("rate_source") != "snapshot_flow_rates":
            failures.append(
                f"rate source violation: {row['case_id']} {row['allocator']}"
            )
        for key in totals:
            totals[key] += int(metrics[key])
        for key in maxima:
            maxima[key] = max(maxima[key], float(metrics[key]))
        if int(metrics["snapshot_call_count"]) != int(
            metrics["snapshot_boundary_count"]
        ):
            failures.append(
                f"snapshot call cardinality: {row['case_id']} {row['allocator']}"
            )
        if int(metrics["snapshot_call_count"]) < 1:
            failures.append(
                f"snapshot coverage absent: {row['case_id']} {row['allocator']}"
            )
        finite_metric_keys = (
            "final_conservation_max_error_B",
            "maximum_inflight_conservation_error_B",
            "maximum_redistribution_sum_error_B",
            "final_remaining_max_B",
            "minimum_remaining_bytes_B",
            "maximum_snapshot_oracle_weight_abs_difference",
            "maximum_counterfactual_retained_weight_difference",
        )
        nonfinite_metrics = [
            key for key in finite_metric_keys if not math.isfinite(float(metrics[key]))
        ]
        if not math.isfinite(float(row["completion_time_s"])):
            nonfinite_metrics.append("completion_time_s")
        if nonfinite_metrics:
            failures.append(
                f"non-finite metrics {nonfinite_metrics}: {row['case_id']} {row['allocator']}"
            )
        if (
            math.isfinite(float(metrics["final_conservation_max_error_B"]))
            and float(metrics["final_conservation_max_error_B"])
            > CONSERVATION_TOLERANCE_B
        ):
            failures.append(
                f"final conservation: {row['case_id']} {row['allocator']}"
            )
        if (
            math.isfinite(float(metrics["maximum_inflight_conservation_error_B"]))
            and
            float(metrics["maximum_inflight_conservation_error_B"])
            > CONSERVATION_TOLERANCE_B
        ):
            failures.append(
                f"inflight conservation: {row['case_id']} {row['allocator']}"
            )
        if (
            math.isfinite(float(metrics["maximum_redistribution_sum_error_B"]))
            and
            float(metrics["maximum_redistribution_sum_error_B"])
            > CONSERVATION_TOLERANCE_B
        ):
            failures.append(
                f"redistribution conservation: {row['case_id']} {row['allocator']}"
            )
        if (
            math.isfinite(float(metrics["final_remaining_max_B"]))
            and float(metrics["final_remaining_max_B"]) > 0.0
        ):
            failures.append(f"remaining bytes: {row['case_id']} {row['allocator']}")
        if (
            math.isfinite(float(metrics["minimum_remaining_bytes_B"]))
            and float(metrics["minimum_remaining_bytes_B"]) < 0.0
        ):
            failures.append(
                f"negative remaining bytes: {row['case_id']} {row['allocator']}"
            )
    trace_index = {
        (
            row["arm_id"],
            int(row["sample_id"]),
            row["allocator"],
            float(row["window_s"]),
        ): row
        for row in traces
    }
    for arm_id, sample_id, allocator in REQUIRED_DEFECT_COVERAGE:
        row = trace_index.get((arm_id, sample_id, allocator, PRODUCTION_WINDOW_S))
        if row is None:
            failures.append(
                f"required defect-coverage row missing: {arm_id} seed={sample_id} {allocator}"
            )
            continue
        metrics = row["metrics"]
        for key in (
            "idle_qp_boundary_observation_count",
            "reactivation_count",
            "counterfactual_retained_weight_mismatch_count",
        ):
            if int(metrics[key]) < 1:
                failures.append(
                    f"required defect coverage absent ({key}): {arm_id} seed={sample_id} {allocator}"
                )
    for key in counter_keys:
        if totals[key] != 0:
            failures.append(f"{key}={totals[key]}")
    return {
        "passed": not failures,
        "failures": failures,
        "totals": totals,
        "maxima": maxima,
        "tolerances": {
            "conservation_B": CONSERVATION_TOLERANCE_B,
            "snapshot_shadow_weight": SHADOW_WEIGHT_TOLERANCE,
        },
    }


def _historical_comparison(
    traces: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    raw_v1 = json.loads((V1_ROOT / "results.json").read_text(encoding="utf-8"))
    if not isinstance(raw_v1, list):
        raise RuntimeError("v1 results.json is not a row list")
    v1_index: Dict[Tuple[str, int, str, float], Mapping[str, Any]] = {}
    for row in raw_v1:
        key = (
            row["arm_id"],
            int(row["sample_id"]),
            row["allocator"],
            float(row["window_s"]),
        )
        if key in v1_index:
            raise RuntimeError(f"duplicate v1 historical key: {key}")
        v1_index[key] = row
    corrected = [
        row for row in traces if float(row["window_s"]) == PRODUCTION_WINDOW_S
    ]
    corrected_index: Dict[Tuple[str, int, str, float], Mapping[str, Any]] = {}
    for row in corrected:
        key = (
            row["arm_id"],
            int(row["sample_id"]),
            row["allocator"],
            float(row["window_s"]),
        )
        if key in corrected_index:
            raise RuntimeError(f"duplicate corrected historical key: {key}")
        corrected_index[key] = row
    expected_keys = {
        (arm_id, sample_id, allocator, PRODUCTION_WINDOW_S)
        for arm_id in ARM_IDS
        for sample_id in SAMPLE_IDS
        for allocator in ALLOCATORS
    }
    if set(corrected_index) != expected_keys:
        raise RuntimeError("corrected 1 ms historical join is not bijective")
    if not expected_keys.issubset(v1_index):
        raise RuntimeError("v1 lacks a required 1 ms historical row")

    directions: Dict[Tuple[str, int], Tuple[str, str]] = {}
    for arm_id in ARM_IDS:
        for sample_id in SAMPLE_IDS:
            legacy_key = (arm_id, sample_id, ALLOCATORS[0], PRODUCTION_WINDOW_S)
            maxmin_key = (arm_id, sample_id, ALLOCATORS[1], PRODUCTION_WINDOW_S)
            v1_direction = v1._effect_direction(
                int(v1_index[legacy_key]["simulated_ticks"]),
                int(v1_index[maxmin_key]["simulated_ticks"]),
            )
            corrected_direction = v1._effect_direction(
                int(corrected_index[legacy_key]["simulated_ticks"]),
                int(corrected_index[maxmin_key]["simulated_ticks"]),
            )
            directions[(arm_id, sample_id)] = (v1_direction, corrected_direction)

    rows = []
    structural_fields = (
        "config_sha256",
        "topology_sha256",
        "ring_sha256",
        "route_sha256",
    )
    for key in sorted(
        expected_keys,
        key=lambda value: (
            ARM_IDS.index(value[0]),
            value[1],
            ALLOCATORS.index(value[2]),
        ),
    ):
        old = v1_index[key]
        new = corrected_index[key]
        invariant_matches = {
            field: old[field] == new[field] for field in structural_fields
        }
        if not all(invariant_matches.values()):
            raise RuntimeError(f"historical structural mismatch: {key}")
        delta_s = float(new["completion_time_s"]) - float(old["completion_time_s"])
        delta_ticks = int(new["simulated_ticks"]) - int(old["simulated_ticks"])
        v1_direction, corrected_direction = directions[(key[0], key[1])]
        rows.append(
            {
                "arm_id": key[0],
                "sample_id": key[1],
                "allocator": key[2],
                "window_s": key[3],
                "v1_completion_time_s": float(old["completion_time_s"]),
                "v1_completion_time_hex": old["completion_time_hex"],
                "corrected_completion_time_s": float(new["completion_time_s"]),
                "corrected_completion_time_hex": new["completion_time_hex"],
                "delta_s": delta_s,
                "delta_ticks": delta_ticks,
                "relative_delta": delta_s / float(old["completion_time_s"]),
                "binary64_changed": old["completion_time_hex"]
                != new["completion_time_hex"],
                "v1_stale_shadow_mismatch_count": int(
                    old["metrics"]["stale_shadow_mismatch_count"]
                ),
                "v1_maximum_stale_shadow_weight_abs_difference": float(
                    old["metrics"]["maximum_stale_shadow_weight_abs_difference"]
                ),
                "corrected_counterfactual_retained_weight_mismatch_count": int(
                    new["metrics"]["counterfactual_retained_weight_mismatch_count"]
                ),
                "invariant_digests_match": True,
                "v1_allocator_direction": v1_direction,
                "corrected_allocator_direction": corrected_direction,
                "ordering_changed_outside_one_tick_tie": (
                    v1_direction != "one_tick_tie"
                    and corrected_direction != "one_tick_tie"
                    and v1_direction != corrected_direction
                ),
            }
        )
    if len(rows) != 60:
        raise RuntimeError(f"historical join returned {len(rows)} rows")
    return {
        "schema": "proportional-mechanism-audit-v2-historical-comparison-v1",
        "row_count": len(rows),
        "changed_binary64_rows": sum(row["binary64_changed"] for row in rows),
        "maximum_abs_relative_delta": max(
            (abs(float(row["relative_delta"])) for row in rows), default=0.0
        ),
        "ordering_changes_outside_one_tick_tie": sum(
            old != "one_tick_tie"
            and new != "one_tick_tie"
            and old != new
            for old, new in directions.values()
        ),
        "rows": rows,
    }


def _flatten_trace(row: Mapping[str, Any]) -> Dict[str, Any]:
    flat = {
        key: row[key]
        for key in (
            "audit_version",
            "rate_source",
            "case_id",
            "source_pair_id",
            "arm_id",
            "sample_id",
            "allocator",
            "window_s",
            "window_ticks",
            "completion_time_s",
            "completion_time_hex",
            "simulated_ticks",
            "config_sha256",
            "topology_sha256",
            "ring_sha256",
            "route_sha256",
            "delivered_vector_sha256",
        )
    }
    flat.update(row["metrics"])
    return flat


def _write_csv_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing to write empty CSV: {path.name}")
    fields = list(rows[0])
    if any(list(row) != fields for row in rows):
        raise RuntimeError(f"CSV rows have inconsistent fields: {path.name}")
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def _report_markdown(summary: Mapping[str, Any]) -> str:
    hard = summary["hard_gate"]
    sensitivity = summary["sensitivity_gate"]
    historical = summary["historical_comparison"]
    lines = [
        "# Corrected proportional mechanism audit v2",
        "",
        f"- Hard mechanism gate: **{'PASS' if hard['passed'] else 'FAIL'}**",
        f"- Window-sensitivity gate: **{'PASS' if sensitivity['passed'] else 'FAIL'}**",
        f"- Decision: **{summary['decision']['status']}**",
        f"- Traced simulations: {summary['trace_count']}",
        f"- Exact 1 ms sidecar/direct rows: {summary['equivalence']['sidecar_direct_exact_rows']}",
        f"- Exact 1 ms worker-bridge rows: {summary['equivalence']['worker_bridge_exact_rows']}",
        "",
        "## Mechanism observations",
        "",
        f"- Snapshot boundaries/calls: {hard['totals']['snapshot_boundary_count']}/{hard['totals']['snapshot_call_count']}",
        f"- Snapshot/shadow weight mismatches: {hard['totals']['snapshot_oracle_weight_mismatch_count']}",
        f"- Snapshot state mutations: {hard['totals']['snapshot_state_mutation_count']}",
        f"- Idle-QP reactivations: {hard['totals']['reactivation_count']}",
        f"- Corrected/retained counterfactual weight mismatches: {hard['totals']['counterfactual_retained_weight_mismatch_count']}",
        f"- Maximum corrected/retained weight difference: {hard['maxima']['maximum_counterfactual_retained_weight_difference']:.12g}",
        f"- Maximum final conservation error: {hard['maxima']['final_conservation_max_error_B']:.12g} B",
        "",
        "## Historical v1 comparison at 1 ms",
        "",
        f"- Bijective rows: {historical['row_count']}",
        f"- Completion rows changed in binary64: {historical['changed_binary64_rows']}",
        f"- Maximum absolute relative completion delta: {100*historical['maximum_abs_relative_delta']:.6g}%",
        f"- Allocator-order changes outside one-tick ties: {historical['ordering_changes_outside_one_tick_tie']}",
        "",
        "## Window sensitivity",
        "",
        f"- Maximum cell/allocator/window median absolute delta: {100*sensitivity['maximum_cell_allocator_median_abs_relative_delta']:.6g}%",
        f"- Maximum individual absolute delta: {100*sensitivity['maximum_individual_abs_relative_delta']:.6g}%",
        f"- Ordering reversals outside a one-tick tie: {len(sensitivity['ordering_reversals_outside_one_tick_tie'])}",
        "",
        "## Scope",
        "",
        "This audit covers only the corrected static proportional core. A pass",
        "authorizes review before a full proportional n=100 revalidation; it does",
        "not authorize n=1000, controller calibration, or dynamic-congestion claims.",
        "No frozen result, paper, commit, or push is produced by this run.",
        "",
    ]
    if hard["failures"]:
        lines.extend(["## Hard-gate failures", ""])
        lines.extend(f"- {failure}" for failure in hard["failures"])
        lines.append("")
    return "\n".join(lines)


def execute(
    plan: Mapping[str, Any], output: Path, authorization: str, workers: int
) -> Dict[str, Any]:
    _verify_plan_integrity(plan)
    output = _validate_output_path(str(output), require_absent=True)
    expected_authorization = authorization_sha256(plan)
    if authorization != expected_authorization:
        raise RuntimeError(
            f"authorization mismatch: supplied {authorization}, expected {expected_authorization}"
        )
    before = verify_immutable_inputs(plan)
    if authorization != authorization_sha256(plan):
        raise RuntimeError("v2 sources changed while sealing authorization")
    script_hash = before["audit_sources"]["audit_script_sha256"]
    spec_hash = before["audit_sources"]["spec_sha256"]
    output.mkdir(parents=True, exist_ok=False)
    completed: List[Dict[str, Any]] = []
    executor: ProcessPoolExecutor | None = None
    try:
        manifest = {
            "schema": "proportional-mechanism-audit-run-v2",
            "authorization_sha256": authorization,
            "audit_script_sha256": script_hash,
            "spec_sha256": spec_hash,
            "plan": plan,
            "immutable_before": before,
            "output": str(output),
            "workers": workers,
            "multiprocessing_start_method": "spawn",
        }
        _write_json(output / "run_manifest.json", manifest)

        executor = ProcessPoolExecutor(
            max_workers=workers,
            mp_context=mp.get_context("spawn"),
            initializer=_worker_init,
            initargs=(script_hash, spec_hash),
        )
        try:
            futures = {
                executor.submit(_run_job, job): job["case_id"]
                for job in plan["jobs"]
            }
            for future in as_completed(futures):
                completed.append(future.result())
        except BaseException:
            executor.shutdown(wait=False, cancel_futures=True)
            executor = None
            raise
        else:
            executor.shutdown(wait=True)
            executor = None

        completed.sort(key=lambda item: item["case_id"])
        traces = [row for result in completed for row in result["traces"]]
        traces.sort(
            key=lambda row: (
                ARM_IDS.index(row["arm_id"]),
                int(row["sample_id"]),
                float(row["window_s"]),
                ALLOCATORS.index(row["allocator"]),
            )
        )
        if len(traces) != 180:
            raise RuntimeError(f"v2 returned {len(traces)} traces, expected 180")

        replay_evidence = []
        equivalence = {
            "sidecar_direct_exact_rows": 0,
            "worker_bridge_exact_rows": 0,
            "pair_count": 0,
        }
        for result in completed:
            if float(result["window_s"]) != PRODUCTION_WINDOW_S:
                continue
            evidence = _validate_one_ms_equivalence(result)
            replay_evidence.append(evidence)
            equivalence["sidecar_direct_exact_rows"] += evidence[
                "sidecar_direct_exact_rows"
            ]
            equivalence["worker_bridge_exact_rows"] += evidence[
                "worker_bridge_exact_rows"
            ]
            equivalence["pair_count"] += 1
        if equivalence != {
            "sidecar_direct_exact_rows": 60,
            "worker_bridge_exact_rows": 60,
            "pair_count": 30,
        }:
            raise RuntimeError(f"1 ms equivalence cardinality changed: {equivalence}")

        hard = _hard_gate(traces)
        _assert_shared_constants()
        sensitivity = v1._sensitivity_gate(traces)
        historical = _historical_comparison(traces)
        after = verify_immutable_inputs(plan)
        if _hexify_floats(before) != _hexify_floats(after):
            raise RuntimeError("immutable input snapshot changed during v2")
        decision = {
            "status": (
                "PASS_READY_FOR_PROPORTIONAL_N100_REVALIDATION"
                if hard["passed"] and sensitivity["passed"]
                else "STOP_BEFORE_PROPORTIONAL_N100_AND_REVIEW"
            ),
            "full_n100_not_run": True,
            "n1000_not_authorized": True,
            "controller_and_dynamic_congestion_out_of_scope": True,
        }
        historical_summary = {
            key: value for key, value in historical.items() if key != "rows"
        }
        summary = {
            "schema": "proportional-mechanism-audit-summary-v2",
            "trace_count": len(traces),
            "equivalence": equivalence,
            "hard_gate": hard,
            "sensitivity_gate": sensitivity,
            "historical_comparison": historical_summary,
            "decision": decision,
            "immutable_after": after,
        }

        _write_csv_rows(output / "results.csv", [_flatten_trace(row) for row in traces])
        _write_json(output / "results.json", traces)
        _write_json(
            output / "production_equivalence.json",
            {
                "schema": "proportional-mechanism-audit-v2-production-equivalence-v1",
                "equivalence": equivalence,
                "pairs": replay_evidence,
            },
        )
        _write_csv_rows(output / "v1_historical_deltas.csv", historical["rows"])
        _write_json(output / "v1_historical_deltas.json", historical)
        _write_json(output / "summary.json", summary)
        _atomic_write_text(output / "REPORT.md", _report_markdown(summary))

        final_immutable = verify_immutable_inputs(plan)
        if _hexify_floats(before) != _hexify_floats(final_immutable):
            raise RuntimeError("immutable input snapshot changed before v2 seal")
        expected_artifacts = {
            "REPORT.md",
            "production_equivalence.json",
            "results.csv",
            "results.json",
            "run_manifest.json",
            "summary.json",
            "v1_historical_deltas.csv",
            "v1_historical_deltas.json",
        }
        actual_artifacts = _flat_artifact_names(output)
        if actual_artifacts != expected_artifacts:
            raise RuntimeError(
                f"unsigned or missing v2 artifact: {sorted(actual_artifacts ^ expected_artifacts)}"
            )
        artifacts = {
            name: {
                "sha256": _sha256_file(output / name),
                "bytes": (output / name).stat().st_size,
            }
            for name in sorted(expected_artifacts)
        }
        complete = {
            "schema": "proportional-mechanism-audit-complete-v2",
            "status": decision["status"],
            "authorization_sha256": authorization,
            "plan_sha256": plan["plan_sha256"],
            "immutable_final_sha256": _digest(_hexify_floats(final_immutable)),
            "artifacts": artifacts,
        }
        _write_json(output / "COMPLETE.json", complete)
        return summary
    except BaseException as exc:
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        try:
            _write_json(
                output / "FAILED.json",
                {
                    "status": "failed",
                    "completed_jobs": len(completed),
                    "error_type": type(exc).__name__,
                    "error": repr(exc),
                },
            )
        except Exception:
            pass
        raise


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--authorization")
    parser.add_argument("--output")
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    plan = build_plan()
    immutable = verify_immutable_inputs(plan)
    authorization = authorization_sha256(plan)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "authorization_sha256": authorization,
                    "plan_sha256": plan["plan_sha256"],
                    "trace_count": plan["traced_simulation_count"],
                    "window_job_count": plan["window_job_count"],
                    "immutable_inputs": immutable,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if not args.authorization or not args.output:
        raise SystemExit("--execute requires --authorization and --output")
    if args.workers < 1 or args.workers > 8:
        raise SystemExit("--workers must be between 1 and 8")
    output = _validate_output_path(args.output, require_absent=True)
    summary = execute(plan, output, args.authorization, args.workers)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
