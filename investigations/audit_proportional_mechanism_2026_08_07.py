"""Bounded mechanism audit for the online proportional byte redistributor.

The audit is deliberately a sidecar.  It reproduces the production loop, adds
observations, and compares the 1 ms trajectory to both a fresh production replay
and the sealed paired n=100 campaign.  It never edits the simulator or frozen
results and has no n=1000 execution path.
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
import struct
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))
EXPERIMENTS = ROOT / "experiments"
if str(EXPERIMENTS) in sys.path:
    sys.path.remove(str(EXPERIMENTS))
sys.path.insert(0, str(EXPERIMENTS))

import run_rate_allocator_n100 as n100  # noqa: E402
import sim  # noqa: E402


SCRIPT_PATH = Path(__file__).resolve()
SPEC_PATH = ROOT / "investigations" / "PROPORTIONAL_MECHANISM_AUDIT_SPEC_2026_08_07.md"
OUTPUT_ROOT = (ROOT / "investigations" / "proportional_mechanism_audit").resolve()
SEALED_ROOT = (
    ROOT / "investigations" / "rate_allocator_n100" / "n100_2026-08-06_03"
).resolve()

EXPECTED_SOURCE_HASHES = {
    ROOT / "sim.py": "40edbacc28e61bb25769278382506c32611cf7fd9e14777480b6fd3d664fab69",
    ROOT / "experiments" / "run_rate_allocator_n100.py": "7d01a2e598c799b0c533fb650f33b8537f51fa3187f427fcf9ada108d56fd8b4",
    ROOT / "experiments" / "run_rate_allocator_pilot.py": "777018e1a408eb5274d5ee87700fc66e4396fd5d39722f625f22e48840efc431",
}
EXPECTED_SEALED_HASHES = {
    SEALED_ROOT / "pairs.csv": "1f414755c340daa84b9b0df83c60e36991129111bca2bce1dc4165e5f6541764",
    SEALED_ROOT / "results_long.csv": "70c75d05ff4e593266f809e8daf6f6ece058c8ff925b309200fe01669c74c8dd",
    SEALED_ROOT / "COMPLETE.json": "c4caaf8bb203eff3b815236c3bc848d8d483b521571c3ab71a47a32f135eadfa",
}
EXPECTED_FROZEN_ROOT = "09a1418e965b9c2d597721ff0d3b1e8db937a19ce667accfa2cf1f469664c24e"

ARM_IDS = (
    "proportional_3tier_os4_p64_k2",
    "proportional_3tier_os4_p64_k16",
    "proportional_2tier_p64_k8",
)
EXPECTED_ARM_INDICES = {
    "proportional_3tier_os4_p64_k2": 68,
    "proportional_3tier_os4_p64_k16": 71,
    "proportional_2tier_p64_k8": 78,
}
SAMPLE_IDS = (0, 11, 22, 33, 44, 55, 66, 77, 88, 99)
WINDOWS_S = (0.5e-3, 1.0e-3, 2.0e-3)
EXPECTED_WINDOW_TICKS = {0.5e-3: 10, 1.0e-3: 20, 2.0e-3: 40}
ALLOCATORS = (
    sim.RATE_ALLOCATOR_LINK_LOCAL,
    sim.RATE_ALLOCATOR_NETWORK_MAXMIN,
)
PRODUCTION_WINDOW_S = 1.0e-3
CONSERVATION_TOLERANCE_B = 1.0e-6
SHADOW_WEIGHT_TOLERANCE = 1.0e-12
MAX_STEPS = 12_000_000

SCIENTIFIC_ROW_FIELDS = (
    "adaptive_gate",
    "allocator",
    "arm_id",
    "completion_time_hex",
    "completion_time_s",
    "config_sha256",
    "conservation",
    "execution_position",
    "family",
    "oracle_actual",
    "pair_id",
    "policy",
    "process_initial_sha256",
    "ring_sha256",
    "route_sha256",
    "runner",
    "sample_id",
    "scalar_metrics",
    "simulated_ticks",
    "topology_sha256",
)

_WORKER_AUDIT_HASH = ""
_WORKER_SPEC_HASH = ""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _f64_hex(value: Any) -> str:
    return struct.pack(">d", float(value)).hex()


def _hexify_floats(value: Any) -> Any:
    if isinstance(value, float):
        return {"__binary64__": _f64_hex(value)}
    if isinstance(value, dict):
        return {str(k): _hexify_floats(v) for k, v in sorted(value.items(), key=lambda x: str(x[0]))}
    if isinstance(value, (list, tuple)):
        return [_hexify_floats(v) for v in value]
    return value


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object in {path}")
    return value


def _atomic_write_text(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _write_json(path: Path, value: Any) -> None:
    _atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_plan() -> Dict[str, Any]:
    base = n100.build_plan()
    pair_index = {
        (pair["config"]["arm_id"], int(pair["sample_id"])): pair
        for pair in base["pairs"]
    }
    selected_pairs: List[Dict[str, Any]] = []
    for arm_id in ARM_IDS:
        for sample_id in SAMPLE_IDS:
            pair = copy.deepcopy(pair_index[(arm_id, sample_id)])
            expected_index = EXPECTED_ARM_INDICES[arm_id]
            if int(pair["arm_index"]) != expected_index:
                raise RuntimeError(
                    f"arm index changed for {arm_id}: {pair['arm_index']} != {expected_index}"
                )
            selected_pairs.append(pair)

    jobs: List[Dict[str, Any]] = []
    for pair in selected_pairs:
        for window_s in WINDOWS_S:
            config = copy.deepcopy(pair["config"])
            original = copy.deepcopy(config)
            config["redistribution_window_s"] = window_s
            changed = {
                key
                for key in set(original) | set(config)
                if _hexify_floats(original.get(key)) != _hexify_floats(config.get(key))
            }
            expected_changes = set() if window_s == PRODUCTION_WINDOW_S else {"redistribution_window_s"}
            if changed != expected_changes:
                raise RuntimeError(
                    f"window materialization changed unexpected fields: {sorted(changed)}"
                )
            ticks = max(1, int(round(window_s / float(config["dt_s"]))))
            if ticks != EXPECTED_WINDOW_TICKS[window_s]:
                raise RuntimeError(f"window {window_s} materialized as {ticks} ticks")
            jobs.append(
                {
                    "case_id": f"{pair['pair_id']}__w{int(round(window_s * 1e6)):04d}us",
                    "source_pair_id": pair["pair_id"],
                    "pair": pair,
                    "config": config,
                    "config_sha256": n100.core._digest(config),
                    "window_s": window_s,
                    "window_ticks": ticks,
                }
            )

    if len(selected_pairs) != 30 or len(jobs) != 90:
        raise RuntimeError("fixed audit must contain 30 source pairs and 90 window jobs")
    if len({job["case_id"] for job in jobs}) != 90:
        raise RuntimeError("audit case IDs are not unique")
    first_allocator = {
        allocator: sum(pair["execution_order"][0] == allocator for pair in selected_pairs)
        for allocator in ALLOCATORS
    }
    if first_allocator != {allocator: 15 for allocator in ALLOCATORS}:
        raise RuntimeError(f"selected allocator order is not balanced: {first_allocator}")
    plan: Dict[str, Any] = {
        "schema": "proportional-mechanism-audit-plan-v1",
        "purpose": "diagnostic_only_not_a_paper_estimator",
        "source_n100_plan_sha256": base["plan_sha256"],
        "arm_ids": list(ARM_IDS),
        "sample_ids": list(SAMPLE_IDS),
        "windows_s": list(WINDOWS_S),
        "window_ticks": [EXPECTED_WINDOW_TICKS[w] for w in WINDOWS_S],
        "allocators": list(ALLOCATORS),
        "source_pair_count": len(selected_pairs),
        "window_job_count": len(jobs),
        "traced_simulation_count": len(jobs) * len(ALLOCATORS),
        "production_equivalence_simulation_count": len(selected_pairs) * len(ALLOCATORS),
        "sealed_replay_simulation_count": len(selected_pairs) * len(ALLOCATORS),
        "selected_pairs": selected_pairs,
        "jobs": jobs,
        "hard_gate": {
            "conservation_tolerance_B": CONSERVATION_TOLERANCE_B,
            "shadow_weight_tolerance": SHADOW_WEIGHT_TOLERANCE,
            "one_ms_binary64_equivalence": True,
            "one_ms_sealed_scientific_equivalence": True,
        },
        "sensitivity_gate": {
            "ordering_tie_ticks": 1,
            "maximum_cell_allocator_median_abs_relative_delta": 0.01,
            "maximum_individual_abs_relative_delta": 0.05,
        },
        "no_n1000_execution_path": True,
        "mutates_simulator": False,
        "mutates_frozen_results": False,
    }
    plan["plan_sha256"] = _digest(plan)
    return plan


def authorization_sha256(plan: Mapping[str, Any]) -> str:
    return _digest(
        {
            "plan_sha256": plan["plan_sha256"],
            "audit_script_sha256": _sha256_file(SCRIPT_PATH),
            "spec_sha256": _sha256_file(SPEC_PATH),
            "source_sha256": {
                path.relative_to(ROOT).as_posix(): expected
                for path, expected in EXPECTED_SOURCE_HASHES.items()
            },
            "sealed_sha256": {
                path.relative_to(ROOT).as_posix(): expected
                for path, expected in EXPECTED_SEALED_HASHES.items()
            },
        }
    )


def _validate_selected_checkpoint_inventory(
    selected_pairs: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    complete = _read_json(SEALED_ROOT / "COMPLETE.json")
    completion_manifest_path = SEALED_ROOT / "completion_manifest.json"
    run_manifest_path = SEALED_ROOT / "run_manifest.json"
    if _sha256_file(completion_manifest_path) != complete["completion_manifest_sha256"]:
        raise RuntimeError("sealed completion manifest hash mismatch")
    if _sha256_file(run_manifest_path) != complete["run_manifest_sha256"]:
        raise RuntimeError("sealed run manifest hash mismatch")
    completion_manifest = _read_json(completion_manifest_path)
    selected: Dict[str, Any] = {}
    for pair in selected_pairs:
        relative = f"checkpoints/{pair['pair_id']}.json"
        try:
            expected = completion_manifest["checkpoints"][relative]
        except KeyError as exc:
            raise RuntimeError(f"sealed checkpoint is missing: {relative}") from exc
        path = SEALED_ROOT / relative
        actual_hash = _sha256_file(path)
        actual_bytes = path.stat().st_size
        if actual_hash != expected["sha256"] or actual_bytes != int(expected["bytes"]):
            raise RuntimeError(f"sealed checkpoint integrity mismatch: {relative}")
        checkpoint = _read_json(path)
        if _hexify_floats(checkpoint["pair_spec"]) != _hexify_floats(pair):
            raise RuntimeError(f"sealed pair specification mismatch: {pair['pair_id']}")
        if checkpoint.get("plan_sha256") != complete.get("plan_sha256"):
            raise RuntimeError(f"sealed checkpoint plan mismatch: {pair['pair_id']}")
        selected[pair["pair_id"]] = {
            "relative_path": relative,
            "sha256": actual_hash,
            "bytes": actual_bytes,
        }
    if len(selected) != 30:
        raise RuntimeError("selected checkpoint inventory is not exactly 30")
    return {
        "complete_status": complete.get("status"),
        "plan_sha256": complete.get("plan_sha256"),
        "completion_manifest_sha256": complete["completion_manifest_sha256"],
        "run_manifest_sha256": complete["run_manifest_sha256"],
        "selected_checkpoints": selected,
    }


def verify_immutable_inputs(plan: Mapping[str, Any]) -> Dict[str, Any]:
    for path, expected in {**EXPECTED_SOURCE_HASHES, **EXPECTED_SEALED_HASHES}.items():
        actual = _sha256_file(path)
        if actual != expected:
            raise RuntimeError(
                f"immutable input changed: {path.relative_to(ROOT)} {actual} != {expected}"
            )
    frozen = n100.core.audit_frozen_csvs()
    if frozen["root_sha256"] != EXPECTED_FROZEN_ROOT or frozen["mismatches"] != 0:
        raise RuntimeError(f"frozen-result integrity failed: {frozen}")
    inventory = _validate_selected_checkpoint_inventory(plan["selected_pairs"])
    if inventory["plan_sha256"] != plan["source_n100_plan_sha256"]:
        raise RuntimeError("current n=100 plan differs from the sealed plan")
    return {
        "audit_sources": {
            "audit_script_sha256": _sha256_file(SCRIPT_PATH),
            "spec_sha256": _sha256_file(SPEC_PATH),
        },
        "source_sha256": {
            path.relative_to(ROOT).as_posix(): _sha256_file(path)
            for path in EXPECTED_SOURCE_HASHES
        },
        "sealed_sha256": {
            path.relative_to(ROOT).as_posix(): _sha256_file(path)
            for path in EXPECTED_SEALED_HASHES
        },
        "frozen_results": frozen,
        "sealed_inventory": inventory,
    }


def _validate_output_path(raw: str, *, require_absent: bool) -> Path:
    resolved = Path(raw)
    if not resolved.is_absolute():
        resolved = ROOT / resolved
    resolved = resolved.resolve()
    if resolved == OUTPUT_ROOT or OUTPUT_ROOT not in resolved.parents:
        raise RuntimeError(f"output must be a child of {OUTPUT_ROOT}")
    results_root = (ROOT / "results").resolve()
    if resolved == results_root or results_root in resolved.parents:
        raise RuntimeError("audit output is forbidden inside results/")
    if require_absent and resolved.exists():
        raise FileExistsError(f"refusing existing output {resolved}")
    return resolved


def _flow_edges(engine: sim.FlowLevelSimulator, fid: int) -> Tuple[sim.Edge, ...]:
    return tuple(engine._flow_edges(engine.flows[fid]))


def _prospective_rates(
    engine: sim.FlowLevelSimulator, candidate_fids: Sequence[int]
) -> Dict[int, float]:
    """Compute current rates for the declared candidate active set, read-only."""
    ordered = list(candidate_fids)
    if engine.rate_allocator == sim.RATE_ALLOCATOR_LINK_LOCAL:
        link_users: Dict[sim.Edge, List[int]] = {}
        flow_edges: Dict[int, Tuple[sim.Edge, ...]] = {}
        for fid in ordered:
            edges = _flow_edges(engine, fid)
            flow_edges[fid] = edges
            for edge in edges:
                link_users.setdefault(edge, []).append(fid)
        link_share: Dict[sim.Edge, float] = {}
        for edge, fids in link_users.items():
            nominal = engine.topo.edge_of.get(edge, 0.0)
            capacity = nominal
            if engine.congestion is not None:
                capacity = engine.congestion.residual_capacity(edge, nominal)
            link_share[edge] = capacity / max(1, len(fids)) if capacity > 0 else 0.0
        return {
            fid: (
                float("inf")
                if not flow_edges[fid]
                else min(link_share.get(edge, 0.0) for edge in flow_edges[fid])
            )
            for fid in ordered
        }

    flow_edges = {fid: _flow_edges(engine, fid) for fid in ordered}
    link_users: Dict[sim.Edge, List[int]] = {}
    for fid in ordered:
        for edge in flow_edges[fid]:
            link_users.setdefault(edge, []).append(fid)
    capacities: Dict[sim.Edge, float] = {}
    for edge in link_users:
        nominal = engine.topo.edge_of.get(edge, 0.0)
        capacity = nominal
        if engine.congestion is not None:
            capacity = engine.congestion.residual_capacity(edge, nominal)
        capacities[edge] = capacity
    return sim._allocate_network_maxmin(flow_edges, link_users, capacities)


def _normalized_weights(rates: Sequence[float]) -> Tuple[List[float], float]:
    clamped = [max(0.0, float(rate)) for rate in rates]
    finite_sum = sum(rate for rate in clamped if math.isfinite(rate))
    if finite_sum <= 0.0:
        return [0.0 for _ in clamped], finite_sum
    return [
        rate / finite_sum if math.isfinite(rate) else 0.0 for rate in clamped
    ], finite_sum


def _run_trace(
    pair: Mapping[str, Any], config: Mapping[str, Any], allocator: str
) -> Dict[str, Any]:
    if config["family"] != "static_split" or config["runner"] != "proportional":
        raise RuntimeError("mechanism audit accepts static proportional cells only")
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

    last_measured_step: Dict[int, int | None] = {fid: None for fid in ring_fids}
    final_zero_step: Dict[int, int | None] = {fid: None for fid in ring_fids}
    pending_reactivation: Dict[int, Dict[str, float]] = {}
    metrics: Dict[str, Any] = {
        "redistribution_boundary_count": 0,
        "redistribution_live_group_count": 0,
        "idle_qp_boundary_observation_count": 0,
        "reactivation_count": 0,
        "stale_reactivation_count": 0,
        "stale_positive_weight_count": 0,
        "positive_weight_without_measurement_count": 0,
        "raw_negative_rate_count": 0,
        "raw_nonfinite_rate_count": 0,
        "zero_rate_live_group_count": 0,
        "nonfinite_used_weight_count": 0,
        "stale_shadow_mismatch_count": 0,
        "max_used_rate_age_ticks": 0,
        "reactivated_bytes_B": 0.0,
        "maximum_idle_assignment_fraction": 0.0,
        "maximum_shadow_weight_abs_difference": 0.0,
        "maximum_stale_shadow_weight_abs_difference": 0.0,
        "maximum_reactivation_next_rate_relative_error": 0.0,
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
        for fid in active_before:
            last_measured_step[fid] = steps + 1
        engine.step()
        steps += 1

        for fid in active_before:
            if engine.flows[fid].remaining_bytes <= 0.0:
                final_zero_step[fid] = steps

        if pending_reactivation:
            for fid, pending in list(pending_reactivation.items()):
                if fid not in active_before:
                    raise RuntimeError("reactivated QP was not active in the next tick")
                next_rate = float(engine.flows[fid].last_rate_Bps)
                used_rate = float(pending["used_rate"])
                scale = max(abs(next_rate), abs(used_rate), 1.0)
                relative_error = abs(next_rate - used_rate) / scale
                metrics["maximum_reactivation_next_rate_relative_error"] = max(
                    metrics["maximum_reactivation_next_rate_relative_error"],
                    relative_error,
                )
                del pending_reactivation[fid]

        metrics["minimum_remaining_bytes_B"] = min(
            metrics["minimum_remaining_bytes_B"],
            min(float(engine.flows[fid].remaining_bytes) for fid in ring_fids),
        )

        if k <= 1 or not (steps == 1 or steps % window_ticks == 0):
            continue

        metrics["redistribution_boundary_count"] += 1
        live_groups: List[Tuple[List[int], float]] = []
        for fids in groups:
            remaining = sum(
                max(0.0, float(engine.flows[fid].remaining_bytes)) for fid in fids
            )
            sent = sum(float(engine.flows[fid].sent_bytes) for fid in fids)
            metrics["maximum_inflight_conservation_error_B"] = max(
                metrics["maximum_inflight_conservation_error_B"],
                abs(sent + remaining - target),
            )
            if remaining > 0.0:
                live_groups.append((fids, remaining))
        candidate_fids = [fid for fids, _ in live_groups for fid in fids]
        prospective = _prospective_rates(engine, candidate_fids)

        for fids, remaining in live_groups:
            metrics["redistribution_live_group_count"] += 1
            flows = [engine.flows[fid] for fid in fids]
            raw_rates = [float(flow.last_rate_Bps) for flow in flows]
            metrics["raw_negative_rate_count"] += sum(rate < 0.0 for rate in raw_rates)
            metrics["raw_nonfinite_rate_count"] += sum(
                not math.isfinite(rate) for rate in raw_rates
            )
            used_weights, rate_sum = _normalized_weights(raw_rates)
            shadow_weights, shadow_sum = _normalized_weights(
                [float(prospective[fid]) for fid in fids]
            )
            if rate_sum <= 0.0:
                metrics["zero_rate_live_group_count"] += 1
                continue
            if shadow_sum <= 0.0:
                raise RuntimeError("prospective current rates sum to zero on a live edge")

            before = [float(flow.remaining_bytes) for flow in flows]
            after = [remaining * weight for weight in used_weights]
            idle_bytes = 0.0
            for fid, flow, old_remaining, new_remaining, weight, shadow_weight, raw_rate in zip(
                fids,
                flows,
                before,
                after,
                used_weights,
                shadow_weights,
                raw_rates,
            ):
                if not math.isfinite(weight):
                    metrics["nonfinite_used_weight_count"] += 1
                measured = last_measured_step[fid]
                if weight > 0.0 and measured is None:
                    metrics["positive_weight_without_measurement_count"] += 1
                    age = steps + 1
                else:
                    age = 0 if measured is None else steps - measured
                if weight > 0.0:
                    metrics["max_used_rate_age_ticks"] = max(
                        metrics["max_used_rate_age_ticks"], age
                    )
                    if age > 0:
                        metrics["stale_positive_weight_count"] += 1
                difference = abs(weight - shadow_weight)
                metrics["maximum_shadow_weight_abs_difference"] = max(
                    metrics["maximum_shadow_weight_abs_difference"], difference
                )
                if age > 0:
                    metrics["maximum_stale_shadow_weight_abs_difference"] = max(
                        metrics["maximum_stale_shadow_weight_abs_difference"],
                        difference,
                    )
                    if difference > SHADOW_WEIGHT_TOLERANCE:
                        metrics["stale_shadow_mismatch_count"] += 1

                if old_remaining <= 0.0:
                    metrics["idle_qp_boundary_observation_count"] += 1
                    if new_remaining > 0.0:
                        metrics["reactivation_count"] += 1
                        if age > 0:
                            metrics["stale_reactivation_count"] += 1
                        idle_bytes += new_remaining
                        pending_reactivation[fid] = {
                            "used_rate": raw_rate,
                            "shadow_rate": float(prospective[fid]),
                            "rate_age_ticks": float(age),
                        }
                flow.remaining_bytes = new_remaining
                if new_remaining > 0.0 and old_remaining <= 0.0:
                    final_zero_step[fid] = None
                elif new_remaining <= 0.0 and old_remaining > 0.0:
                    final_zero_step[fid] = steps

            metrics["reactivated_bytes_B"] += idle_bytes
            metrics["maximum_idle_assignment_fraction"] = max(
                metrics["maximum_idle_assignment_fraction"], idle_bytes / remaining
            )
            metrics["maximum_redistribution_sum_error_B"] = max(
                metrics["maximum_redistribution_sum_error_B"],
                abs(sum(float(flow.remaining_bytes) for flow in flows) - remaining),
            )

    else:
        raise RuntimeError("traced proportional transfer exceeded max_steps")

    if pending_reactivation:
        raise RuntimeError("completion left an unobserved reactivation")
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
            raise RuntimeError("a QP has no final completion tick")
        final_finish_spreads.append(max(ticks) - min(ticks))
    metrics.update(
        {
            "final_conservation_max_error_B": max(final_errors, default=0.0),
            "final_remaining_max_B": max(final_remaining, default=0.0),
            "maximum_final_qp_finish_spread_ticks": max(
                final_finish_spreads, default=0
            ),
        }
    )
    return {
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


def _run_direct_production(
    config: Mapping[str, Any], allocator: str
) -> Dict[str, Any]:
    topo, ring = n100._make_topology_and_ring(config)
    result = sim.run_ring_transfer_proportional(
        topo=topo,
        ring=ring,
        bytes_per_neighbor=float(config["bytes_per_neighbor"]),
        flows_per_neighbor=int(config["k"]),
        dt_s=float(config["dt_s"]),
        window_s=float(config["redistribution_window_s"]),
        return_metrics=True,
        rate_allocator=allocator,
    )
    delivered = [float(result["per_edge_delivered_bytes"][index]) for index in range(int(config["ring_size"]))]
    return {
        "completion_time_s": float(result["completion_time_s"]),
        "completion_time_hex": _f64_hex(result["completion_time_s"]),
        "delivered_bytes_hex": [_f64_hex(value) for value in delivered],
        "delivered_vector_sha256": _digest([_f64_hex(value) for value in delivered]),
    }


def _verify_worker_sources() -> None:
    for path, expected in EXPECTED_SOURCE_HASHES.items():
        if _sha256_file(path) != expected:
            raise RuntimeError(f"source changed inside worker: {path}")
    if _sha256_file(SCRIPT_PATH) != _WORKER_AUDIT_HASH:
        raise RuntimeError("audit script changed inside worker")
    if _sha256_file(SPEC_PATH) != _WORKER_SPEC_HASH:
        raise RuntimeError("audit specification changed inside worker")


def _worker_init(audit_hash: str, spec_hash: str) -> None:
    global _WORKER_AUDIT_HASH, _WORKER_SPEC_HASH
    _WORKER_AUDIT_HASH = audit_hash
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
            direct = _run_direct_production(job["config"], allocator)
            direct["allocator"] = allocator
            production.append(direct)
    sealed_replay = None
    if float(job["window_s"]) == PRODUCTION_WINDOW_S:
        sealed_replay = n100._run_pair_worker(job["pair"])
    _verify_worker_sources()
    return {
        "case_id": job["case_id"],
        "source_pair_id": job["source_pair_id"],
        "window_s": float(job["window_s"]),
        "traces": traces,
        "direct_production": production,
        "sealed_replay": sealed_replay,
    }


def _scientific_projection(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {field: _hexify_floats(row[field]) for field in SCIENTIFIC_ROW_FIELDS}


def _validate_one_ms_equivalence(
    result: Mapping[str, Any], sealed_inventory: Mapping[str, Any]
) -> Dict[str, Any]:
    if float(result["window_s"]) != PRODUCTION_WINDOW_S:
        raise RuntimeError("production equivalence called outside 1 ms")
    trace_by_allocator = {row["allocator"]: row for row in result["traces"]}
    production_by_allocator = {
        row["allocator"]: row for row in result["direct_production"]
    }
    if set(trace_by_allocator) != set(ALLOCATORS) or set(production_by_allocator) != set(ALLOCATORS):
        raise RuntimeError("1 ms equivalence lacks an allocator")
    for allocator in ALLOCATORS:
        trace = trace_by_allocator[allocator]
        production = production_by_allocator[allocator]
        if trace["completion_time_hex"] != production["completion_time_hex"]:
            raise RuntimeError(
                f"sidecar/production completion mismatch: {result['case_id']} {allocator}"
            )
        if trace["delivered_bytes_hex"] != production["delivered_bytes_hex"]:
            raise RuntimeError(
                f"sidecar/production delivery mismatch: {result['case_id']} {allocator}"
            )

    fresh = result["sealed_replay"]
    pair_id = result["source_pair_id"]
    if fresh is None or fresh["pair_id"] != pair_id:
        raise RuntimeError(f"fresh sealed replay is missing for {pair_id}")
    sealed_path = SEALED_ROOT / sealed_inventory["selected_checkpoints"][pair_id]["relative_path"]
    sealed = _read_json(sealed_path)
    if _hexify_floats(fresh["pair_spec"]) != _hexify_floats(sealed["pair_spec"]):
        raise RuntimeError(f"fresh/sealed pair specification mismatch: {pair_id}")
    if fresh["pair_gate"] != sealed["pair_gate"]:
        raise RuntimeError(f"fresh/sealed pair gate mismatch: {pair_id}")
    fresh_rows = {row["allocator"]: row for row in fresh["rows"]}
    sealed_rows = {row["allocator"]: row for row in sealed["rows"]}
    if set(fresh_rows) != set(ALLOCATORS) or set(sealed_rows) != set(ALLOCATORS):
        raise RuntimeError(f"fresh/sealed allocator set mismatch: {pair_id}")
    for allocator in ALLOCATORS:
        if _scientific_projection(fresh_rows[allocator]) != _scientific_projection(
            sealed_rows[allocator]
        ):
            raise RuntimeError(f"fresh/sealed scientific mismatch: {pair_id} {allocator}")
    return {
        "sidecar_production_exact_rows": 2,
        "fresh_sealed_exact_rows": 2,
        "pair_id": pair_id,
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
            trace["arm_id"],
            int(trace["sample_id"]),
            trace["allocator"],
            float(trace["window_s"]),
        )
        for trace in traces
    }
    if len(traces) != 180 or actual_keys != expected_keys:
        failures.append(
            f"trace matrix mismatch: rows={len(traces)} unique_keys={len(actual_keys)}"
        )
    for arm_id in ARM_IDS:
        for sample_id in SAMPLE_IDS:
            cell = [
                trace
                for trace in traces
                if trace["arm_id"] == arm_id
                and int(trace["sample_id"]) == sample_id
            ]
            if len(cell) != 6:
                continue
            for field in ("topology_sha256", "ring_sha256", "route_sha256"):
                if len({trace[field] for trace in cell}) != 1:
                    failures.append(
                        f"{field} changed across windows/allocators: {arm_id} seed={sample_id}"
                    )
            for window_s in WINDOWS_S:
                window_rows = [
                    trace for trace in cell if float(trace["window_s"]) == window_s
                ]
                if len(window_rows) != 2:
                    failures.append(
                        f"allocator pair missing: {arm_id} seed={sample_id} window={window_s}"
                    )
                    continue
                if len({trace["config_sha256"] for trace in window_rows}) != 1:
                    failures.append(
                        f"config differs between allocators: {arm_id} seed={sample_id} window={window_s}"
                    )
            if len({trace["config_sha256"] for trace in cell}) != 3:
                failures.append(
                    f"window configs are not three distinct snapshots: {arm_id} seed={sample_id}"
                )
    maxima = {
        "final_conservation_max_error_B": 0.0,
        "maximum_inflight_conservation_error_B": 0.0,
        "maximum_redistribution_sum_error_B": 0.0,
        "maximum_shadow_weight_abs_difference": 0.0,
        "maximum_stale_shadow_weight_abs_difference": 0.0,
        "maximum_used_rate_age_ticks": 0,
    }
    totals = {
        "reactivation_count": 0,
        "stale_reactivation_count": 0,
        "stale_positive_weight_count": 0,
        "stale_shadow_mismatch_count": 0,
        "zero_rate_live_group_count": 0,
        "raw_negative_rate_count": 0,
        "raw_nonfinite_rate_count": 0,
        "positive_weight_without_measurement_count": 0,
        "nonfinite_used_weight_count": 0,
    }
    for trace in traces:
        metrics = trace["metrics"]
        for key in totals:
            totals[key] += int(metrics[key])
        maxima["final_conservation_max_error_B"] = max(
            maxima["final_conservation_max_error_B"],
            float(metrics["final_conservation_max_error_B"]),
        )
        maxima["maximum_inflight_conservation_error_B"] = max(
            maxima["maximum_inflight_conservation_error_B"],
            float(metrics["maximum_inflight_conservation_error_B"]),
        )
        maxima["maximum_redistribution_sum_error_B"] = max(
            maxima["maximum_redistribution_sum_error_B"],
            float(metrics["maximum_redistribution_sum_error_B"]),
        )
        maxima["maximum_shadow_weight_abs_difference"] = max(
            maxima["maximum_shadow_weight_abs_difference"],
            float(metrics["maximum_shadow_weight_abs_difference"]),
        )
        maxima["maximum_stale_shadow_weight_abs_difference"] = max(
            maxima["maximum_stale_shadow_weight_abs_difference"],
            float(metrics["maximum_stale_shadow_weight_abs_difference"]),
        )
        maxima["maximum_used_rate_age_ticks"] = max(
            maxima["maximum_used_rate_age_ticks"],
            int(metrics["max_used_rate_age_ticks"]),
        )
        if float(metrics["final_conservation_max_error_B"]) > CONSERVATION_TOLERANCE_B:
            failures.append(f"final conservation: {trace['case_id']} {trace['allocator']}")
        if float(metrics["maximum_inflight_conservation_error_B"]) > CONSERVATION_TOLERANCE_B:
            failures.append(f"inflight conservation: {trace['case_id']} {trace['allocator']}")
        if float(metrics["maximum_redistribution_sum_error_B"]) > CONSERVATION_TOLERANCE_B:
            failures.append(f"redistribution conservation: {trace['case_id']} {trace['allocator']}")
        if float(metrics["final_remaining_max_B"]) > 0.0:
            failures.append(f"remaining bytes: {trace['case_id']} {trace['allocator']}")
        if float(metrics["minimum_remaining_bytes_B"]) < 0.0:
            failures.append(f"negative remaining bytes: {trace['case_id']} {trace['allocator']}")
    for key in (
        "zero_rate_live_group_count",
        "raw_negative_rate_count",
        "raw_nonfinite_rate_count",
        "positive_weight_without_measurement_count",
        "nonfinite_used_weight_count",
        "stale_shadow_mismatch_count",
    ):
        if totals[key] != 0:
            failures.append(f"{key}={totals[key]}")
    return {
        "passed": not failures,
        "failures": failures,
        "totals": totals,
        "maxima": maxima,
        "tolerances": {
            "conservation_B": CONSERVATION_TOLERANCE_B,
            "stale_shadow_weight": SHADOW_WEIGHT_TOLERANCE,
        },
    }


def _effect_direction(legacy_ticks: int, maxmin_ticks: int) -> str:
    if abs(legacy_ticks - maxmin_ticks) <= 1:
        return "one_tick_tie"
    if maxmin_ticks < legacy_ticks:
        return "network_maxmin_faster"
    return "network_maxmin_slower"


def _sensitivity_gate(traces: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    index = {
        (
            row["arm_id"],
            int(row["sample_id"]),
            row["allocator"],
            float(row["window_s"]),
        ): row
        for row in traces
    }
    individual: List[Dict[str, Any]] = []
    grouped: Dict[Tuple[str, str, float], List[float]] = {}
    maximum_abs_relative = 0.0
    for arm_id in ARM_IDS:
        for sample_id in SAMPLE_IDS:
            for allocator in ALLOCATORS:
                baseline = index[(arm_id, sample_id, allocator, PRODUCTION_WINDOW_S)]
                for window_s in (0.5e-3, 2.0e-3):
                    row = index[(arm_id, sample_id, allocator, window_s)]
                    relative = (
                        float(row["completion_time_s"])
                        / float(baseline["completion_time_s"])
                        - 1.0
                    )
                    delta_ticks = int(row["simulated_ticks"]) - int(
                        baseline["simulated_ticks"]
                    )
                    maximum_abs_relative = max(maximum_abs_relative, abs(relative))
                    grouped.setdefault((arm_id, allocator, window_s), []).append(
                        abs(relative)
                    )
                    individual.append(
                        {
                            "arm_id": arm_id,
                            "sample_id": sample_id,
                            "allocator": allocator,
                            "window_s": window_s,
                            "relative_to_1ms": relative,
                            "delta_ticks": delta_ticks,
                        }
                    )
    cell_allocator_window = []
    maximum_median = 0.0
    for (arm_id, allocator, window_s), values in sorted(grouped.items()):
        median = statistics.median(values)
        maximum_median = max(maximum_median, median)
        cell_allocator_window.append(
            {
                "arm_id": arm_id,
                "allocator": allocator,
                "window_s": window_s,
                "median_abs_relative_delta": median,
                "maximum_abs_relative_delta": max(values),
            }
        )

    reversals = []
    directions = []
    for arm_id in ARM_IDS:
        for sample_id in SAMPLE_IDS:
            by_window: Dict[float, str] = {}
            for window_s in WINDOWS_S:
                legacy = index[(arm_id, sample_id, ALLOCATORS[0], window_s)]
                maxmin = index[(arm_id, sample_id, ALLOCATORS[1], window_s)]
                by_window[window_s] = _effect_direction(
                    int(legacy["simulated_ticks"]), int(maxmin["simulated_ticks"])
                )
            reference = by_window[PRODUCTION_WINDOW_S]
            directions.append(
                {"arm_id": arm_id, "sample_id": sample_id, "directions": by_window}
            )
            for window_s in (0.5e-3, 2.0e-3):
                other = by_window[window_s]
                if (
                    reference != "one_tick_tie"
                    and other != "one_tick_tie"
                    and reference != other
                ):
                    reversals.append(
                        {
                            "arm_id": arm_id,
                            "sample_id": sample_id,
                            "reference": reference,
                            "window_s": window_s,
                            "other": other,
                        }
                    )
    passed = (
        not reversals
        and maximum_median <= 0.01
        and maximum_abs_relative <= 0.05
    )
    return {
        "passed": passed,
        "maximum_cell_allocator_median_abs_relative_delta": maximum_median,
        "maximum_individual_abs_relative_delta": maximum_abs_relative,
        "ordering_reversals_outside_one_tick_tie": reversals,
        "cell_allocator_window_summary": cell_allocator_window,
        "individual_comparisons": individual,
        "directions": directions,
    }


def _flatten_trace(row: Mapping[str, Any]) -> Dict[str, Any]:
    flat = {
        key: row[key]
        for key in (
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


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    flattened = [_flatten_trace(row) for row in rows]
    fields = list(flattened[0])
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(flattened)
    os.replace(temporary, path)


def _report_markdown(summary: Mapping[str, Any]) -> str:
    hard = summary["hard_gate"]
    sensitivity = summary["sensitivity_gate"]
    decision = summary["decision"]
    lines = [
        "# Proportional mechanism audit",
        "",
        f"- Hard mechanism gate: **{'PASS' if hard['passed'] else 'FAIL'}**",
        f"- Window-sensitivity gate: **{'PASS' if sensitivity['passed'] else 'FAIL'}**",
        f"- Decision: **{decision['status']}**",
        f"- Traced simulations: {summary['trace_count']}",
        f"- Exact 1 ms sidecar/production rows: {summary['equivalence']['sidecar_production_exact_rows']}",
        f"- Exact fresh/sealed scientific rows: {summary['equivalence']['fresh_sealed_exact_rows']}",
        "",
        "## Mechanism observations",
        "",
        f"- QP reactivations: {hard['totals']['reactivation_count']}",
        f"- Reactivations using a rate older than the just-finished tick: {hard['totals']['stale_reactivation_count']}",
        f"- Positive stale weights: {hard['totals']['stale_positive_weight_count']}",
        f"- Stale weights differing from prospective current weights: {hard['totals']['stale_shadow_mismatch_count']}",
        f"- Maximum used-rate age: {hard['maxima']['maximum_used_rate_age_ticks']} ticks",
        f"- Maximum stale/current normalized-weight difference: {hard['maxima']['maximum_stale_shadow_weight_abs_difference']:.12g}",
        f"- Maximum final conservation error: {hard['maxima']['final_conservation_max_error_B']:.12g} B",
        "",
        "## Window sensitivity",
        "",
        f"- Maximum cell/allocator/window median absolute delta: {100*sensitivity['maximum_cell_allocator_median_abs_relative_delta']:.6g}%",
        f"- Maximum individual absolute delta: {100*sensitivity['maximum_individual_abs_relative_delta']:.6g}%",
        f"- Ordering reversals outside a one-tick tie: {len(sensitivity['ordering_reversals_outside_one_tick_tie'])}",
        "",
        "## Scope",
        "",
        "This gate covers the static proportional core only. It does not validate",
        "controller calibration or stale-rate behavior under time-varying congestion.",
        "No `sim.py`, frozen result, paper, commit, or push was produced by this run.",
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
    expected_authorization = authorization_sha256(plan)
    if authorization != expected_authorization:
        raise RuntimeError(
            f"authorization mismatch: supplied {authorization}, expected {expected_authorization}"
        )
    before = verify_immutable_inputs(plan)
    if authorization != authorization_sha256(plan):
        raise RuntimeError("audit sources changed while sealing authorization")
    audit_hash = before["audit_sources"]["audit_script_sha256"]
    spec_hash = before["audit_sources"]["spec_sha256"]
    output.mkdir(parents=True, exist_ok=False)
    completed: List[Dict[str, Any]] = []
    executor: ProcessPoolExecutor | None = None
    try:
        manifest = {
            "schema": "proportional-mechanism-audit-run-v1",
            "authorization_sha256": authorization,
            "audit_script_sha256": audit_hash,
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
            initargs=(audit_hash, spec_hash),
        )
        try:
            futures = {
                executor.submit(_run_job, job): job["case_id"] for job in plan["jobs"]
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
            raise RuntimeError(f"audit returned {len(traces)} traces, expected 180")

        equivalence = {
            "sidecar_production_exact_rows": 0,
            "fresh_sealed_exact_rows": 0,
            "pair_count": 0,
        }
        sealed_inventory = before["sealed_inventory"]
        for result in completed:
            if float(result["window_s"]) != PRODUCTION_WINDOW_S:
                continue
            verdict = _validate_one_ms_equivalence(result, sealed_inventory)
            equivalence["sidecar_production_exact_rows"] += verdict[
                "sidecar_production_exact_rows"
            ]
            equivalence["fresh_sealed_exact_rows"] += verdict[
                "fresh_sealed_exact_rows"
            ]
            equivalence["pair_count"] += 1
        if equivalence != {
            "sidecar_production_exact_rows": 60,
            "fresh_sealed_exact_rows": 60,
            "pair_count": 30,
        }:
            raise RuntimeError(f"1 ms equivalence cardinality changed: {equivalence}")

        hard = _hard_gate(traces)
        sensitivity = _sensitivity_gate(traces)
        after = verify_immutable_inputs(plan)
        if _hexify_floats(before) != _hexify_floats(after):
            raise RuntimeError("immutable input snapshot changed during audit")
        decision = {
            "status": (
                "LOCK_1MS_FOR_STATIC_CORE_N1000"
                if hard["passed"] and sensitivity["passed"]
                else "STOP_BEFORE_N1000_AND_REVIEW"
            ),
            "controller_and_dynamic_congestion_remain_out_of_scope": True,
        }
        summary = {
            "schema": "proportional-mechanism-audit-summary-v1",
            "trace_count": len(traces),
            "equivalence": equivalence,
            "hard_gate": hard,
            "sensitivity_gate": sensitivity,
            "decision": decision,
            "immutable_after": after,
        }
        _write_csv(output / "results.csv", traces)
        _write_json(output / "results.json", traces)
        _write_json(output / "summary.json", summary)
        _atomic_write_text(output / "REPORT.md", _report_markdown(summary))

        final_seal = verify_immutable_inputs(plan)
        if _hexify_floats(before) != _hexify_floats(final_seal):
            raise RuntimeError("immutable input snapshot changed before completion seal")
        artifacts = {}
        for path in sorted(output.iterdir(), key=lambda item: item.name):
            if path.is_file() and path.name != "COMPLETE.json":
                artifacts[path.name] = {
                    "sha256": _sha256_file(path),
                    "bytes": path.stat().st_size,
                }
        complete = {
            "schema": "proportional-mechanism-audit-complete-v1",
            "status": decision["status"],
            "authorization_sha256": authorization,
            "plan_sha256": plan["plan_sha256"],
            "immutable_final_sha256": _digest(_hexify_floats(final_seal)),
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
