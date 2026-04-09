"""
Stage 1 – Step 1.3: Congestion Validation

Validates that under congestion:
1. The bottleneck edge (B*) determines the completion time.
2. Higher congestion fraction leads to higher completion time (monotonic).
3. Per-logical-edge throughput spread widens under congestion.

Runs: P=16, M=256MiB, affected_fraction=[0.0, 0.1, 0.3, 0.5], 5 seeds each.
Outputs CSV + plots to results/ directory.
"""
from __future__ import annotations

import csv
import os
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import List, Dict, Any

import numpy as np
import matplotlib.pyplot as plt

from sim import (
    FatTree,
    CongestionModel,
    build_worker_ring,
    run_simple_ring_transfer,
)

# ─── Configuration ───────────────────────────────────────────
TOPO_K = 16
LINK_GBPS = 100.0

RING_SIZE = 16
MSG_BYTES = 256 * 1024 * 1024  # 256 MiB
FLOWS_PER_NEIGHBOR = 1
DT_S = 5e-5

AFFECTED_FRACTIONS = [0.0, 0.1, 0.3, 0.5]
NUM_RUNS = 5

# Congestion model parameters (same as experiments.py)
CONGESTED_UTIL_LOW = 0.30
CONGESTED_UTIL_HIGH = 0.85
NORMAL_UTIL_LOW = 0.00
NORMAL_UTIL_HIGH = 0.05
P_ON = 0.003
P_OFF = 0.012

# ─── Output paths ────────────────────────────────────────────
TODAY = date.today().isoformat()
OUT_DIR = Path(f"results/v1.0_validation_{TODAY}/congestion")


def make_congestion(affected_fraction: float, seed: int):
    if affected_fraction <= 0.0:
        return None
    return CongestionModel(
        mode="onoff",
        seed=seed,
        affected_fraction=affected_fraction,
        congested_util_low=CONGESTED_UTIL_LOW,
        congested_util_high=CONGESTED_UTIL_HIGH,
        normal_util_low=NORMAL_UTIL_LOW,
        normal_util_high=NORMAL_UTIL_HIGH,
        p_on=P_ON,
        p_off=P_OFF,
    )


def run_all_cases() -> List[Dict[str, Any]]:
    rows = []
    total = len(AFFECTED_FRACTIONS) * NUM_RUNS
    count = 0

    for frac in AFFECTED_FRACTIONS:
        for run_idx in range(NUM_RUNS):
            count += 1
            seed = int(time.time_ns()) % (2**31) + run_idx * 1000 + int(frac * 1000)
            topo = FatTree(k=TOPO_K, link_capacity_Gbps=LINK_GBPS, seed=seed)
            ring = build_worker_ring(topo.hosts, worker_count=RING_SIZE, start_index=0)
            cong = make_congestion(frac, seed)

            print(f"[{count}/{total}] frac={frac:.1f}, run={run_idx+1}/{NUM_RUNS} ...")

            metrics = run_simple_ring_transfer(
                topo=topo,
                ring=ring,
                bytes_per_neighbor=MSG_BYTES,
                flows_per_neighbor=FLOWS_PER_NEIGHBOR,
                dt_s=DT_S,
                congestion=cong,
                return_metrics=True,
            )

            sim_time = metrics["completion_time_s"]
            theo_time = metrics["theoretical_time_s"]  # no-congestion theoretical

            # Per-logical-edge simulated throughput
            edge_throughputs = list(metrics["per_logical_edge_sim_throughput_Bps"].values())
            min_edge_tp = min(edge_throughputs)
            max_edge_tp = max(edge_throughputs)
            mean_edge_tp = np.mean(edge_throughputs)

            # Slowdown factor vs no-congestion theoretical
            slowdown = sim_time / theo_time if theo_time > 0 else float("inf")

            row = {
                "affected_fraction": frac,
                "run": run_idx + 1,
                "seed": seed,
                "simulated_time_s": sim_time,
                "theoretical_time_no_cong_s": theo_time,
                "slowdown_factor": slowdown,
                "min_edge_throughput_Gbps": min_edge_tp * 8 / 1e9,
                "max_edge_throughput_Gbps": max_edge_tp * 8 / 1e9,
                "mean_edge_throughput_Gbps": mean_edge_tp * 8 / 1e9,
                "throughput_spread_Gbps": (max_edge_tp - min_edge_tp) * 8 / 1e9,
            }
            rows.append(row)

            # Store per-edge details for box plot
            row["_edge_throughputs_Gbps"] = [t * 8 / 1e9 for t in edge_throughputs]

            print(f"  sim={sim_time:.6f}s  slowdown={slowdown:.3f}x  "
                  f"B*={min_edge_tp*8/1e9:.2f} Gbps  spread={row['throughput_spread_Gbps']:.2f} Gbps")

    return rows


def save_csv(rows: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclude internal fields from CSV
    csv_keys = [k for k in rows[0].keys() if not k.startswith("_")]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSV saved: {path}")


def plot_per_edge_throughput(rows: List[Dict[str, Any]], path: Path) -> None:
    """Box plot of per-logical-edge throughput grouped by affected_fraction."""
    fig, ax = plt.subplots(figsize=(10, 6))

    # Collect all edge throughputs per fraction
    data_by_frac = defaultdict(list)
    for r in rows:
        data_by_frac[r["affected_fraction"]].extend(r["_edge_throughputs_Gbps"])

    fracs = sorted(data_by_frac.keys())
    box_data = [data_by_frac[f] for f in fracs]
    labels = [f"{f:.0%}" for f in fracs]

    bp = ax.boxplot(box_data, tick_labels=labels, patch_artist=True)
    colors = plt.cm.RdYlGn_r(np.linspace(0.1, 0.9, len(fracs)))
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)

    ax.set_xlabel("Congestion (% of links affected)", fontsize=12)
    ax.set_ylabel("Per-Logical-Edge Throughput (Gbps)", fontsize=12)
    ax.set_title(f"Edge Throughput Distribution Under Congestion\n(P={RING_SIZE}, M=256 MiB, {NUM_RUNS} runs)", fontsize=13)
    ax.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=200)
    print(f"Plot saved: {path}")


def plot_bottleneck_analysis(rows: List[Dict[str, Any]], path: Path) -> None:
    """Completion time vs affected_fraction with mean + error bars."""
    fig, ax = plt.subplots(figsize=(10, 6))

    grouped = defaultdict(list)
    for r in rows:
        grouped[r["affected_fraction"]].append(r["simulated_time_s"])

    fracs = sorted(grouped.keys())
    means = [np.mean(grouped[f]) for f in fracs]
    stds = [np.std(grouped[f]) for f in fracs]

    # Individual points
    for r in rows:
        ax.scatter(r["affected_fraction"], r["simulated_time_s"],
                   c="#1f77b4", alpha=0.4, s=30, zorder=2)

    # Mean + error bars
    ax.errorbar(fracs, means, yerr=stds, fmt="o-", color="red", markersize=8,
                capsize=5, linewidth=2, label="Mean ± Std", zorder=3)

    # No-congestion reference line
    baseline_mean = means[0] if fracs[0] == 0.0 else None
    if baseline_mean:
        ax.axhline(y=baseline_mean, color="green", linestyle="--", linewidth=1,
                   label=f"Baseline (no congestion): {baseline_mean:.4f}s")

    ax.set_xlabel("Congestion (fraction of links affected)", fontsize=12)
    ax.set_ylabel("Completion Time (s)", fontsize=12)
    ax.set_title(f"Completion Time vs Congestion Level\n(P={RING_SIZE}, M=256 MiB, {NUM_RUNS} runs)", fontsize=13)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=200)
    print(f"Plot saved: {path}")


def print_summary(rows: List[Dict[str, Any]]) -> None:
    print("\n" + "=" * 75)
    print("CONGESTION VALIDATION SUMMARY")
    print("=" * 75)
    print(f"{'Fraction':>10}  {'Mean Time (s)':>14}  {'Std':>8}  {'Mean Slowdown':>14}  {'Mean Spread (Gbps)':>18}")
    print("-" * 75)

    grouped = defaultdict(list)
    for r in rows:
        grouped[r["affected_fraction"]].append(r)

    prev_mean = None
    monotonic = True
    for frac in sorted(grouped.keys()):
        group = grouped[frac]
        mean_time = np.mean([r["simulated_time_s"] for r in group])
        std_time = np.std([r["simulated_time_s"] for r in group])
        mean_slowdown = np.mean([r["slowdown_factor"] for r in group])
        mean_spread = np.mean([r["throughput_spread_Gbps"] for r in group])

        if prev_mean is not None and mean_time < prev_mean:
            monotonic = False
        prev_mean = mean_time

        print(f"{frac:>10.1%}  {mean_time:>14.6f}  {std_time:>8.6f}  {mean_slowdown:>14.3f}x  {mean_spread:>18.2f}")

    print("-" * 75)
    print(f"Monotonicity check: {'PASS' if monotonic else 'FAIL'}")
    print("=" * 75)


def main() -> None:
    print(f"Congestion Validation — Fat-Tree k={TOPO_K}, {LINK_GBPS} Gbps")
    print(f"P={RING_SIZE}, M=256 MiB, fractions={AFFECTED_FRACTIONS}")
    print(f"Output: {OUT_DIR}\n")

    rows = run_all_cases()
    save_csv(rows, OUT_DIR / "results.csv")
    plot_per_edge_throughput(rows, OUT_DIR / "per_edge_throughput.png")
    plot_bottleneck_analysis(rows, OUT_DIR / "bottleneck_analysis.png")
    print_summary(rows)


if __name__ == "__main__":
    main()
