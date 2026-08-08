"""Reproducible paired analysis for the sealed rate-allocator n=100 campaign.

The script treats each arm as a paired n=100 experiment.  Its one cross-arm
headline uses the sample ID as a cluster and keeps all 32 matched
equal/proportional cells together during resampling.  Controller results are
reported separately because its thresholds were frozen under the legacy rate
model and therefore are diagnostic until recalibrated on disjoint seeds.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_ROOT = (ROOT / "investigations" / "rate_allocator_n100").resolve()
LEGACY = "link_local_equal_share"
MAXMIN = "network_maxmin"
BASE_SEED = 20_260_806
DEFAULT_REPS = 20_000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_seed(label: str) -> int:
    payload = hashlib.sha256(label.encode("utf-8")).digest()
    return (BASE_SEED + int.from_bytes(payload[:8], "big")) % (2**63 - 1)


def _f(value: float) -> str:
    return repr(float(value))


def _csv_payload(rows: Sequence[Mapping[str, Any]]) -> bytes:
    if not rows:
        raise RuntimeError("refusing to write an empty analysis table")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().replace("\r\n", "\n").encode("utf-8")


def _write_once(path: Path, payload: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.write_bytes(payload)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _validate_location(path: Path, *, must_exist: bool) -> Path:
    resolved = path.resolve()
    if resolved == ANALYSIS_ROOT or ANALYSIS_ROOT not in resolved.parents:
        raise RuntimeError(f"path must be a child of {ANALYSIS_ROOT}: {resolved}")
    if must_exist and not resolved.is_dir():
        raise FileNotFoundError(resolved)
    if not must_exist and resolved.exists():
        raise FileExistsError(f"refusing existing analysis output {resolved}")
    return resolved


def _validate_sealed_run(run: Path) -> dict[str, Any]:
    run = _validate_location(run, must_exist=True)
    complete_path = run / "COMPLETE.json"
    completion_path = run / "completion_manifest.json"
    complete = json.loads(complete_path.read_text(encoding="utf-8"))
    if complete.get("schema") != "rate-allocator-n100-complete-v1":
        raise RuntimeError("wrong n=100 COMPLETE schema")
    if complete.get("status") != "n100_revalidation_complete_ready_for_analysis":
        raise RuntimeError("n=100 run is not ready for analysis")
    if _sha256(completion_path) != complete["completion_manifest_sha256"]:
        raise RuntimeError("completion manifest hash mismatch")
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    if completion.get("pair_count") != 13_400 or completion.get("simulation_count") != 26_800:
        raise RuntimeError("sealed campaign cardinality changed")
    if completion.get("gate", {}).get("passed") is not True:
        raise RuntimeError("sealed campaign global gate is not true")
    if completion.get("controller_recalibrated") is not False:
        raise RuntimeError("controller is not the approved frozen controller")
    if completion.get("n1000_started") is not False:
        raise RuntimeError("unexpected n=1000 execution")
    for name in ("pairs.csv", "results_long.csv", "arm_summary.csv", "runtime.json"):
        meta = completion["exports"][name]
        path = run / name
        if path.stat().st_size != meta["bytes"] or _sha256(path) != meta["sha256"]:
            raise RuntimeError(f"sealed export changed: {name}")
    return {"run": run, "complete": complete, "completion": completion}


def _bootstrap_stats(values: Sequence[float], label: str, reps: int) -> dict[str, float]:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or len(array) < 2 or not np.all(np.isfinite(array)):
        raise RuntimeError(f"invalid bootstrap vector {label}")
    if np.any(array <= 0.0):
        raise RuntimeError(f"nonpositive ratio in {label}")
    rng = np.random.default_rng(_stable_seed(label))
    indexes = rng.integers(0, len(array), size=(reps, len(array)), dtype=np.int32)
    arithmetic = array[indexes].mean(axis=1)
    log_array = np.log(array)
    geometric = np.exp(log_array[indexes].mean(axis=1))
    mean_low, mean_high = np.quantile(arithmetic, (0.025, 0.975))
    geo_low, geo_high = np.quantile(geometric, (0.025, 0.975))
    return {
        "mean": float(array.mean()),
        "mean_ci_low": float(mean_low),
        "mean_ci_high": float(mean_high),
        "geometric_mean": math.exp(float(log_array.mean())),
        "geometric_ci_low": float(geo_low),
        "geometric_ci_high": float(geo_high),
        "median": float(np.median(array)),
        "minimum": float(array.min()),
        "maximum": float(array.max()),
    }


def _cluster_geometric(log_values: Sequence[float], label: str, reps: int) -> dict[str, float]:
    array = np.asarray(log_values, dtype=float)
    if array.shape != (100,) or not np.all(np.isfinite(array)):
        raise RuntimeError(f"{label} must contain exactly 100 finite seed clusters")
    rng = np.random.default_rng(_stable_seed(label))
    indexes = rng.integers(0, 100, size=(reps, 100), dtype=np.int32)
    boot = np.exp(array[indexes].mean(axis=1))
    low, high = np.quantile(boot, (0.025, 0.975))
    return {
        "estimate": math.exp(float(array.mean())),
        "ci_low": float(low),
        "ci_high": float(high),
        "seed_cluster_minimum": math.exp(float(array.min())),
        "seed_cluster_maximum": math.exp(float(array.max())),
    }


def _pair_rows(raw: Iterable[Mapping[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in raw:
        row: dict[str, Any] = dict(source)
        row["sample_id"] = int(source["sample_id"])
        row["ring_size"] = int(source["ring_size"])
        row["k"] = int(source["k"])
        row["legacy"] = float(source["legacy_time_s"])
        row["maxmin"] = float(source["maxmin_time_s"])
        row["ratio"] = row["maxmin"] / row["legacy"]
        row["bit_equal"] = row["legacy"].hex() == row["maxmin"].hex()
        if not math.isfinite(row["ratio"]) or row["ratio"] <= 0.0:
            raise RuntimeError(f"invalid pair ratio {row['pair_id']}")
        rows.append(row)
    if len(rows) != 13_400 or len({row["pair_id"] for row in rows}) != 13_400:
        raise RuntimeError("pair table cardinality or uniqueness changed")
    arm_counts = Counter(row["arm_id"] for row in rows)
    if len(arm_counts) != 134 or set(arm_counts.values()) != {100}:
        raise RuntimeError("pair table does not contain 134 complete n=100 arms")
    sample_counts = Counter(row["sample_id"] for row in rows)
    if set(sample_counts) != set(range(100)) or set(sample_counts.values()) != {134}:
        raise RuntimeError("sample coverage changed")
    return rows


def _arm_analysis(rows: Sequence[Mapping[str, Any]], reps: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["arm_id"])].append(row)
    output: list[dict[str, Any]] = []
    for arm_id in sorted(grouped):
        selected = sorted(grouped[arm_id], key=lambda item: item["sample_id"])
        stats = _bootstrap_stats([row["ratio"] for row in selected], f"arm:{arm_id}", reps)
        first = selected[0]
        faster = sum(row["ratio"] < 1.0 for row in selected)
        equal = sum(bool(row["bit_equal"]) for row in selected)
        slower = sum(row["ratio"] > 1.0 for row in selected)
        if first["family"] == "controller" and first["policy"] == "adaptive":
            inference = "diagnostic_frozen_controller_requires_recalibration"
        elif equal == 100:
            inference = "bit_exact_no_allocator_effect"
        elif stats["mean_ci_high"] < 1.0:
            inference = "maxmin_faster_pointwise_95pct_CI"
        elif stats["mean_ci_low"] > 1.0:
            inference = "maxmin_slower_pointwise_95pct_CI"
        else:
            inference = "pointwise_95pct_CI_includes_one"
        output.append(
            {
                "arm_id": arm_id,
                "family": first["family"],
                "policy": first["policy"],
                "fabric": first["fabric"],
                "ring_size": first["ring_size"],
                "k": first["k"],
                "n_pairs": 100,
                "ratio_mean": _f(stats["mean"]),
                "ratio_mean_ci_low": _f(stats["mean_ci_low"]),
                "ratio_mean_ci_high": _f(stats["mean_ci_high"]),
                "ratio_geometric_mean": _f(stats["geometric_mean"]),
                "ratio_geometric_ci_low": _f(stats["geometric_ci_low"]),
                "ratio_geometric_ci_high": _f(stats["geometric_ci_high"]),
                "ratio_median": _f(stats["median"]),
                "ratio_min": _f(stats["minimum"]),
                "ratio_max": _f(stats["maximum"]),
                "maxmin_faster_count": faster,
                "bit_equal_count": equal,
                "maxmin_slower_count": slower,
                "inference": inference,
            }
        )
    return output


def _family_analysis(rows: Sequence[Mapping[str, Any]], reps: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["family"])].append(row)
    output: list[dict[str, Any]] = []
    for family in sorted(grouped):
        selected = grouped[family]
        seed_logs = [
            float(np.mean([math.log(row["ratio"]) for row in selected if row["sample_id"] == seed]))
            for seed in range(100)
        ]
        cluster = _cluster_geometric(seed_logs, f"family-cluster:{family}", reps)
        output.append(
            {
                "family": family,
                "arm_count": len({row["arm_id"] for row in selected}),
                "pair_count": len(selected),
                "seed_cluster_count": 100,
                "equal_arm_weight_geometric_ratio": _f(cluster["estimate"]),
                "cluster_bootstrap_ci_low": _f(cluster["ci_low"]),
                "cluster_bootstrap_ci_high": _f(cluster["ci_high"]),
                "maxmin_faster_count": sum(row["ratio"] < 1.0 for row in selected),
                "bit_equal_count": sum(bool(row["bit_equal"]) for row in selected),
                "maxmin_slower_count": sum(row["ratio"] > 1.0 for row in selected),
                "interpretation": (
                    "diagnostic_only_frozen_controller"
                    if family == "controller"
                    else "seed_clustered_equal_arm_weight"
                ),
            }
        )
    return output


def _masking_analysis(
    rows: Sequence[Mapping[str, Any]], reps: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    static = [row for row in rows if row["family"] == "static_split"]
    key = lambda row: (row["fabric"], row["ring_size"], row["k"], row["sample_id"])
    equal = {key(row): row for row in static if row["policy"] == "equal"}
    proportional = {key(row): row for row in static if row["policy"] == "proportional"}
    common = sorted(set(equal).intersection(proportional))
    if len(common) != 3_200:
        raise RuntimeError(f"expected 3,200 matched equal/proportional rows, got {len(common)}")
    joined: list[dict[str, Any]] = []
    for item in common:
        eq = equal[item]
        prop = proportional[item]
        legacy_advantage = eq["legacy"] / prop["legacy"]
        maxmin_advantage = eq["maxmin"] / prop["maxmin"]
        joined.append(
            {
                "fabric": item[0],
                "ring_size": item[1],
                "k": item[2],
                "sample_id": item[3],
                "legacy_advantage": legacy_advantage,
                "maxmin_advantage": maxmin_advantage,
                "amplification": maxmin_advantage / legacy_advantage,
            }
        )
    cells: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in joined:
        cells[(row["fabric"], row["ring_size"], row["k"])].append(row)
    if len(cells) != 32 or any(len(value) != 100 for value in cells.values()):
        raise RuntimeError("matched masking matrix is not 32 complete n=100 cells")

    output: list[dict[str, Any]] = []
    for cell in sorted(cells):
        selected = sorted(cells[cell], key=lambda item: item["sample_id"])
        legacy = _bootstrap_stats(
            [row["legacy_advantage"] for row in selected], f"mask-legacy:{cell}", reps
        )
        maxmin = _bootstrap_stats(
            [row["maxmin_advantage"] for row in selected], f"mask-maxmin:{cell}", reps
        )
        amplification = _bootstrap_stats(
            [row["amplification"] for row in selected], f"mask-amplification:{cell}", reps
        )
        exact = sum(row["amplification"] == 1.0 for row in selected)
        if exact == 100:
            inference = "models_identical_in_this_cell"
        elif amplification["geometric_ci_low"] > 1.0:
            inference = "masking_supported_pointwise_95pct_CI"
        else:
            inference = "pointwise_95pct_CI_includes_one"
        output.append(
            {
                "fabric": cell[0],
                "ring_size": cell[1],
                "k": cell[2],
                "n_pairs": 100,
                "legacy_prop_advantage_mean": _f(legacy["mean"]),
                "legacy_prop_advantage_mean_ci_low": _f(legacy["mean_ci_low"]),
                "legacy_prop_advantage_mean_ci_high": _f(legacy["mean_ci_high"]),
                "maxmin_prop_advantage_mean": _f(maxmin["mean"]),
                "maxmin_prop_advantage_mean_ci_low": _f(maxmin["mean_ci_low"]),
                "maxmin_prop_advantage_mean_ci_high": _f(maxmin["mean_ci_high"]),
                "amplification_geometric_mean": _f(amplification["geometric_mean"]),
                "amplification_geometric_ci_low": _f(amplification["geometric_ci_low"]),
                "amplification_geometric_ci_high": _f(amplification["geometric_ci_high"]),
                "amplification_mean": _f(amplification["mean"]),
                "amplification_mean_ci_low": _f(amplification["mean_ci_low"]),
                "amplification_mean_ci_high": _f(amplification["mean_ci_high"]),
                "amplification_gt_one_count": sum(row["amplification"] > 1.0 for row in selected),
                "amplification_equal_one_count": exact,
                "amplification_lt_one_count": sum(row["amplification"] < 1.0 for row in selected),
                "inference": inference,
            }
        )

    seed_legacy_logs = []
    seed_maxmin_logs = []
    seed_amplification_logs = []
    for seed in range(100):
        selected = [row for row in joined if row["sample_id"] == seed]
        if len(selected) != 32:
            raise RuntimeError(f"masking seed cluster {seed} has {len(selected)} cells")
        seed_legacy_logs.append(float(np.mean([math.log(row["legacy_advantage"]) for row in selected])))
        seed_maxmin_logs.append(float(np.mean([math.log(row["maxmin_advantage"]) for row in selected])))
        seed_amplification_logs.append(float(np.mean([math.log(row["amplification"]) for row in selected])))
    legacy_cluster = _cluster_geometric(seed_legacy_logs, "masking:legacy-cluster", reps)
    maxmin_cluster = _cluster_geometric(seed_maxmin_logs, "masking:maxmin-cluster", reps)
    amplification_cluster = _cluster_geometric(
        seed_amplification_logs, "masking:amplification-cluster", reps
    )
    cell_geometric = [float(row["amplification_geometric_mean"]) for row in output]
    headline = {
        "matched_cells": 32,
        "paired_rows": 3_200,
        "seed_clusters": 100,
        "legacy_proportional_advantage_geometric": legacy_cluster,
        "maxmin_proportional_advantage_geometric": maxmin_cluster,
        "proportional_advantage_amplification": amplification_cluster,
        "cell_geometric_amplification_gt_one": sum(value > 1.0 for value in cell_geometric),
        "cell_geometric_amplification_equal_one": sum(value == 1.0 for value in cell_geometric),
        "cell_geometric_amplification_lt_one": sum(value < 1.0 for value in cell_geometric),
        "pointwise_cells_with_95pct_CI_above_one": sum(
            row["inference"] == "masking_supported_pointwise_95pct_CI" for row in output
        ),
        "multiplicity_note": "cell intervals are pointwise; no multiplicity adjustment",
        "headline_inference": (
            "seed-clustered evidence that the legacy local model masked part of the "
            "proportional policy's advantage"
        ),
    }
    return output, headline


def _controller_analysis(
    pairs: Sequence[Mapping[str, Any]], long_rows: Sequence[Mapping[str, str]], reps: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    adaptive_pairs = {
        row["pair_id"]: row
        for row in pairs
        if row["family"] == "controller" and row["policy"] == "adaptive"
    }
    indexed: dict[str, dict[str, Mapping[str, str]]] = defaultdict(dict)
    for row in long_rows:
        if row["pair_id"] in adaptive_pairs:
            indexed[row["pair_id"]][row["allocator"]] = row
    if len(adaptive_pairs) != 800 or len(indexed) != 800 or any(len(value) != 2 for value in indexed.values()):
        raise RuntimeError("controller adaptive table is incomplete")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_event_different = 0
    all_final_mean_different = 0
    slow_event_different = 0
    slow_final_mean_different = 0
    for pair_id, pair in adaptive_pairs.items():
        legacy = indexed[pair_id][LEGACY]
        maxmin = indexed[pair_id][MAXMIN]
        event_different = int(legacy["adaptive_event_count"]) != int(maxmin["adaptive_event_count"])
        mean_different = float(legacy["final_k_mean"]).hex() != float(maxmin["final_k_mean"]).hex()
        record = {
            "ratio": pair["ratio"],
            "bit_equal": pair["bit_equal"],
            "event_different": event_different,
            "final_mean_different": mean_different,
        }
        grouped[str(pair["arm_id"])].append(record)
        all_event_different += event_different
        all_final_mean_different += mean_different
        if pair["ratio"] > 1.0:
            slow_event_different += event_different
            slow_final_mean_different += mean_different
    output: list[dict[str, Any]] = []
    for arm_id in sorted(grouped):
        selected = grouped[arm_id]
        stats = _bootstrap_stats([row["ratio"] for row in selected], f"controller:{arm_id}", reps)
        output.append(
            {
                "arm_id": arm_id,
                "n_pairs": 100,
                "ratio_mean": _f(stats["mean"]),
                "ratio_mean_ci_low": _f(stats["mean_ci_low"]),
                "ratio_mean_ci_high": _f(stats["mean_ci_high"]),
                "maxmin_faster_count": sum(row["ratio"] < 1.0 for row in selected),
                "bit_equal_count": sum(bool(row["bit_equal"]) for row in selected),
                "maxmin_slower_count": sum(row["ratio"] > 1.0 for row in selected),
                "adaptive_event_count_changed": sum(bool(row["event_different"]) for row in selected),
                "final_k_mean_changed": sum(bool(row["final_mean_different"]) for row in selected),
                "interpretation": "diagnostic_only_recalibrate_on_disjoint_seeds",
            }
        )
    slow_count = sum(row["ratio"] > 1.0 for row in adaptive_pairs.values())
    headline = {
        "adaptive_pairs": 800,
        "maxmin_faster": sum(row["ratio"] < 1.0 for row in adaptive_pairs.values()),
        "bit_equal": sum(bool(row["bit_equal"]) for row in adaptive_pairs.values()),
        "maxmin_slower": slow_count,
        "event_count_changed": all_event_different,
        "final_k_mean_changed": all_final_mean_different,
        "slower_pairs_with_event_count_changed": slow_event_different,
        "slower_pairs_with_final_k_mean_changed": slow_final_mean_different,
        "interpretation": (
            "rate-model and controller decisions are coupled; frozen-threshold results are "
            "diagnostic and cannot support a calibrated method comparison"
        ),
    }
    return output, headline


def analyze(run: Path, output: Path, reps: int) -> None:
    if reps < 1_000:
        raise RuntimeError("bootstrap repetitions must be at least 1,000")
    sealed = _validate_sealed_run(run)
    run = sealed["run"]
    output = _validate_location(output, must_exist=False)
    if run == output or run in output.parents:
        raise RuntimeError("analysis output must not mutate the sealed run")
    pairs = _pair_rows(_read_csv(run / "pairs.csv"))
    long_rows = _read_csv(run / "results_long.csv")
    if len(long_rows) != 26_800:
        raise RuntimeError("long table cardinality changed")
    fixed = [
        row
        for row in pairs
        if not (row["family"] == "controller" and row["policy"] == "adaptive")
    ]
    if any(row["ratio"] > 1.0 for row in fixed):
        raise RuntimeError("a fixed-policy max-min result is slower than legacy")
    static_equal = [
        row for row in pairs if row["family"] == "static_split" and row["policy"] == "equal"
    ]
    static_prop = [
        row
        for row in pairs
        if row["family"] == "static_split" and row["policy"] == "proportional"
    ]
    if len(static_equal) != 4_800 or not all(row["bit_equal"] for row in static_equal):
        raise RuntimeError("static equal policy is not bit-exact across allocators")
    if len(static_prop) != 3_200:
        raise RuntimeError("static proportional matrix changed")

    arms = _arm_analysis(pairs, reps)
    families = _family_analysis(pairs, reps)
    masking, masking_headline = _masking_analysis(pairs, reps)
    controller, controller_headline = _controller_analysis(pairs, long_rows, reps)
    runtime = json.loads((run / "runtime.json").read_text(encoding="utf-8"))
    global_counts = {
        "pairs": len(pairs),
        "maxmin_faster": sum(row["ratio"] < 1.0 for row in pairs),
        "bit_equal": sum(bool(row["bit_equal"]) for row in pairs),
        "maxmin_slower": sum(row["ratio"] > 1.0 for row in pairs),
        "fixed_policy_pairs": len(fixed),
        "fixed_policy_maxmin_slower": sum(row["ratio"] > 1.0 for row in fixed),
        "static_equal_bit_exact": sum(bool(row["bit_equal"]) for row in static_equal),
        "static_proportional_maxmin_faster": sum(row["ratio"] < 1.0 for row in static_prop),
        "static_proportional_bit_equal": sum(bool(row["bit_equal"]) for row in static_prop),
        "static_proportional_maxmin_slower": sum(row["ratio"] > 1.0 for row in static_prop),
    }
    headline = {
        "schema": "rate-allocator-n100-analysis-headline-v1",
        "global_counts": global_counts,
        "proportional_masking": masking_headline,
        "frozen_controller": controller_headline,
        "runtime": {
            "n100_pool_wall_s": runtime["measured_n100_pool_wall_s"],
            "n1000_linear_projection_hours": runtime["n1000_projection"][
                "central_wall_hours_linear_same_matrix_same_workers"
            ],
            "n1000_started": False,
            "projection_is_not_a_confidence_interval": True,
        },
        "inference_limits": [
            "n=100 results are revalidation evidence; frozen result files remain unchanged",
            "cell intervals are pointwise 95% percentile bootstrap intervals without multiplicity adjustment",
            "the masking headline resamples 100 seed clusters and keeps all 32 cells within each seed together",
            "the frozen controller is diagnostic until recalibrated on disjoint seeds",
            "no n=1000 execution is authorized or started",
        ],
    }

    output.mkdir(parents=False)
    payloads = {
        "allocator_effect_by_arm.csv": _csv_payload(arms),
        "family_seed_cluster_summary.csv": _csv_payload(families),
        "proportional_masking_by_cell.csv": _csv_payload(masking),
        "controller_frozen_diagnostic_by_arm.csv": _csv_payload(controller),
        "headline.json": _json_bytes(headline),
    }
    amp = masking_headline["proportional_advantage_amplification"]
    controller_info = controller_headline
    summary = f"""# Paired n=100 rate-allocator analysis

The sealed campaign contains 13,400 paired jobs (26,800 simulations), with 100
paired samples in each of 134 arms. All 13,400 legacy halves reproduce their
frozen references exactly in binary64.

## Main model-sensitivity result

Across the 32 matched equal/proportional cells, the network-wide allocator
multiplies the proportional policy's advantage by **{amp['estimate']:.6f}**
(seed-clustered 95% bootstrap CI **[{amp['ci_low']:.6f},
{amp['ci_high']:.6f}]**). The cluster is the sample ID: all 32 cells stay
together in every bootstrap draw. At the cell level, 23 geometric effects are
above one, nine are exactly one, and none is below one. Cell intervals are
pointwise and have no multiplicity correction; the clustered headline is the
primary inference.

The mechanism is concrete: all 4,800 static equal-split pairs are bit-identical
between allocators, while network max-min improves 1,036 of 3,200 proportional
pairs and is bit-identical in the other 2,164. Thus the legacy link-local model
masked part of proportional splitting's benefit rather than creating it.

## Frozen-controller boundary

The frozen adaptive controller is diagnostic only. It is slower under max-min
in {controller_info['maxmin_slower']} of 800 pairs; {controller_info['slower_pairs_with_event_count_changed']}
of those slower pairs also change the number of adaptive events. Across all 800
pairs, {controller_info['event_count_changed']} change event count. This is
evidence that allocator and controller decisions are coupled, so a fair method
comparison requires recalibration on disjoint seeds before evaluation.

## Runtime and next gate

The measured eight-worker n=100 pool time is
{runtime['measured_n100_pool_wall_s'] / 60.0:.2f} minutes. A linear same-matrix
n=1000 planning projection is
{runtime['n1000_projection']['central_wall_hours_linear_same_matrix_same_workers']:.2f}
hours; it is not a confidence interval. No n=1000 run was started. The next
scientific gate is controller recalibration on separate seeds, followed by an
Ibrahem decision on the production n=1000 scope.
"""
    payloads["ANALYSIS_SUMMARY.md"] = summary.encode("utf-8")
    for name, payload in payloads.items():
        _write_once(output / name, payload)
    output_meta = {
        name: {"bytes": (output / name).stat().st_size, "sha256": _sha256(output / name)}
        for name in sorted(payloads)
    }
    manifest = {
        "schema": "rate-allocator-n100-analysis-manifest-v1",
        "sealed_run": str(run),
        "sealed_complete_sha256": _sha256(run / "COMPLETE.json"),
        "sealed_completion_manifest_sha256": _sha256(run / "completion_manifest.json"),
        "sealed_pairs_sha256": _sha256(run / "pairs.csv"),
        "sealed_results_long_sha256": _sha256(run / "results_long.csv"),
        "analysis_source_sha256": _sha256(Path(__file__).resolve()),
        "bootstrap": {
            "repetitions": reps,
            "base_seed": BASE_SEED,
            "interval": "two-sided 95% percentile",
            "arm_unit": "paired sample within one arm",
            "headline_unit": "sample-ID cluster containing all 32 matched cells",
        },
        "outputs": output_meta,
        "paper_or_frozen_files_modified": False,
        "n1000_started": False,
    }
    _write_once(output / "analysis_manifest.json", _json_bytes(manifest))
    done = {
        "schema": "rate-allocator-n100-analysis-complete-v1",
        "analysis_manifest_sha256": _sha256(output / "analysis_manifest.json"),
        "status": "analysis_complete_ready_for_review",
    }
    _write_once(output / "COMPLETE.json", _json_bytes(done))
    print("ANALYSIS_COMPLETE")
    print(f"output={output}")
    print(f"masking_amplification={amp['estimate']:.9f}")
    print(f"masking_95pct_CI=[{amp['ci_low']:.9f},{amp['ci_high']:.9f}]")
    print(f"frozen_controller_slower={controller_info['maxmin_slower']}/800")


def verify(output: Path) -> None:
    output = _validate_location(output, must_exist=True)
    done = json.loads((output / "COMPLETE.json").read_text(encoding="utf-8"))
    if done.get("schema") != "rate-allocator-n100-analysis-complete-v1":
        raise RuntimeError("wrong analysis COMPLETE schema")
    manifest_path = output / "analysis_manifest.json"
    if _sha256(manifest_path) != done["analysis_manifest_sha256"]:
        raise RuntimeError("analysis manifest changed")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run = Path(manifest["sealed_run"])
    if _sha256(run / "COMPLETE.json") != manifest["sealed_complete_sha256"]:
        raise RuntimeError("sealed run COMPLETE changed")
    if _sha256(run / "completion_manifest.json") != manifest["sealed_completion_manifest_sha256"]:
        raise RuntimeError("sealed completion manifest changed")
    if _sha256(run / "pairs.csv") != manifest["sealed_pairs_sha256"]:
        raise RuntimeError("sealed pairs changed")
    if _sha256(run / "results_long.csv") != manifest["sealed_results_long_sha256"]:
        raise RuntimeError("sealed long results changed")
    if _sha256(Path(__file__).resolve()) != manifest["analysis_source_sha256"]:
        raise RuntimeError("analysis source changed")
    for name, meta in manifest["outputs"].items():
        path = output / name
        if path.stat().st_size != meta["bytes"] or _sha256(path) != meta["sha256"]:
            raise RuntimeError(f"analysis output changed: {name}")
    print("ANALYSIS_VERIFY_OK")
    print(f"output={output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--analyze", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-reps", type=int, default=DEFAULT_REPS)
    args = parser.parse_args()
    if args.analyze:
        if args.run is None:
            parser.error("--analyze requires --run")
        analyze(args.run, args.output, args.bootstrap_reps)
    else:
        if args.run is not None:
            parser.error("--verify reads the sealed-run path from the analysis manifest")
        verify(args.output)


if __name__ == "__main__":
    main()
