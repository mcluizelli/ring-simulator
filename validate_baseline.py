"""
Stage 1 – Step 1.2: Baseline Validation (No Congestion)

Validates the ring simulator against the theoretical bottleneck model:
    T_simple = bytes_per_neighbor / B*
where B* is the minimum per-logical-edge throughput.

Runs: P=[4,8,16,32], M=[64MiB,256MiB], 3 seeds, no congestion.
Outputs CSV + scatter plot to results/ directory.
"""
from __future__ import annotations

import csv
import os
import sys
from datetime import date
from pathlib import Path
from typing import List, Dict, Any

import numpy as np
import matplotlib.pyplot as plt

from sim import (
    FatTree,
    build_worker_ring,
    run_simple_ring_transfer,
    compute_ring_theoretical_time,
)

# ─── Configuration ───────────────────────────────────────────
TOPO_K = 16
LINK_GBPS = 100.0

RING_SIZES = [4, 8, 16, 32]
MSG_SIZES_BYTES = [64 * 1024 * 1024, 256 * 1024 * 1024]  # 64 MiB, 256 MiB
MSG_LABELS = {64 * 1024 * 1024: "64 MiB", 256 * 1024 * 1024: "256 MiB"}
FLOWS_PER_NEIGHBOR = 1
SEEDS = [1, 42, 123]
DT_S = 5e-5

# ─── Output paths ────────────────────────────────────────────
TODAY = date.today().isoformat()
OUT_DIR = Path(f"results/v1.0_validation_{TODAY}/baseline")


def run_all_cases() -> List[Dict[str, Any]]:
    rows = []
    total = len(SEEDS) * len(RING_SIZES) * len(MSG_SIZES_BYTES)
    count = 0

    for seed in SEEDS:
        topo = FatTree(k=TOPO_K, link_capacity_Gbps=LINK_GBPS, seed=seed)

        for P in RING_SIZES:
            ring = build_worker_ring(topo.hosts, worker_count=P, start_index=0)

            for M in MSG_SIZES_BYTES:
                count += 1
                print(f"[{count}/{total}] seed={seed}, P={P}, M={MSG_LABELS[M]} ...")

                metrics = run_simple_ring_transfer(
                    topo=topo,
                    ring=ring,
                    bytes_per_neighbor=M,
                    flows_per_neighbor=FLOWS_PER_NEIGHBOR,
                    dt_s=DT_S,
                    congestion=None,
                    background_cfg=None,
                    return_metrics=True,
                )

                sim_time = metrics["completion_time_s"]
                theo_time = metrics["theoretical_time_s"]
                ratio = sim_time / theo_time if theo_time > 0 else float("inf")
                bottleneck = metrics["bottleneck_bandwidth_Bps"]

                row = {
                    "seed": seed,
                    "ring_size": P,
                    "msg_bytes": M,
                    "msg_label": MSG_LABELS[M],
                    "simulated_time_s": sim_time,
                    "theoretical_time_s": theo_time,
                    "ratio_sim_over_theo": ratio,
                    "bottleneck_Bps": bottleneck,
                    "bottleneck_Gbps": bottleneck * 8 / 1e9,
                    "flows_per_neighbor": FLOWS_PER_NEIGHBOR,
                }
                rows.append(row)
                print(f"  sim={sim_time:.6f}s  theo={theo_time:.6f}s  ratio={ratio:.4f}  B*={bottleneck*8/1e9:.2f} Gbps")

    return rows


def save_csv(rows: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSV saved: {path}")


def plot_validation(rows: List[Dict[str, Any]], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 8))

    # Color by message size, marker size by ring size
    colors = {"64 MiB": "#1f77b4", "256 MiB": "#ff7f0e"}
    size_scale = {4: 40, 8: 70, 16: 110, 32: 160}

    for row in rows:
        ax.scatter(
            row["theoretical_time_s"],
            row["simulated_time_s"],
            c=colors[row["msg_label"]],
            s=size_scale.get(row["ring_size"], 80),
            alpha=0.7,
            edgecolors="black",
            linewidths=0.5,
        )

    # y=x reference line
    all_times = [r["theoretical_time_s"] for r in rows] + [r["simulated_time_s"] for r in rows]
    lo, hi = min(all_times) * 0.9, max(all_times) * 1.1
    ax.plot([lo, hi], [lo, hi], "k--", linewidth=1, label="y = x (perfect match)")

    # Legend for colors
    for label, color in colors.items():
        ax.scatter([], [], c=color, s=80, label=f"M = {label}", edgecolors="black", linewidths=0.5)
    # Legend for sizes
    for P, sz in sorted(size_scale.items()):
        ax.scatter([], [], c="gray", s=sz, label=f"P = {P}", edgecolors="black", linewidths=0.5)

    # Annotate mean ratio
    ratios = [r["ratio_sim_over_theo"] for r in rows]
    mean_ratio = np.mean(ratios)
    std_ratio = np.std(ratios)
    ax.text(
        0.05, 0.95,
        f"Mean ratio (sim/theo): {mean_ratio:.4f} ± {std_ratio:.4f}",
        transform=ax.transAxes, fontsize=10, verticalalignment="top",
        bbox=dict(boxstyle="round", facecolor="lightyellow", alpha=0.8),
    )

    ax.set_xlabel("Theoretical Time (s)", fontsize=12)
    ax.set_ylabel("Simulated Time (s)", fontsize=12)
    ax.set_title("Baseline Validation: Simulated vs Theoretical Completion Time", fontsize=13)
    ax.legend(loc="lower right", fontsize=9)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=200)
    print(f"Plot saved: {path}")


def print_summary(rows: List[Dict[str, Any]]) -> None:
    print("\n" + "=" * 70)
    print("SUMMARY TABLE")
    print("=" * 70)
    print(f"{'P':>4}  {'M':>8}  {'Sim (s)':>10}  {'Theo (s)':>10}  {'Ratio':>8}  {'B* (Gbps)':>10}")
    print("-" * 70)

    # Average over seeds
    from collections import defaultdict
    grouped = defaultdict(list)
    for r in rows:
        grouped[(r["ring_size"], r["msg_label"])].append(r)

    for (P, mlabel), group in sorted(grouped.items()):
        sim_mean = np.mean([r["simulated_time_s"] for r in group])
        theo_mean = np.mean([r["theoretical_time_s"] for r in group])
        ratio_mean = np.mean([r["ratio_sim_over_theo"] for r in group])
        bw_mean = np.mean([r["bottleneck_Gbps"] for r in group])
        print(f"{P:>4}  {mlabel:>8}  {sim_mean:>10.6f}  {theo_mean:>10.6f}  {ratio_mean:>8.4f}  {bw_mean:>10.2f}")

    ratios = [r["ratio_sim_over_theo"] for r in rows]
    print("-" * 70)
    print(f"Overall mean ratio: {np.mean(ratios):.4f} ± {np.std(ratios):.4f}")
    print("=" * 70)


def main() -> None:
    print(f"Baseline Validation — Fat-Tree k={TOPO_K}, {LINK_GBPS} Gbps")
    print(f"Output: {OUT_DIR}\n")

    rows = run_all_cases()
    save_csv(rows, OUT_DIR / "results.csv")
    plot_validation(rows, OUT_DIR / "theoretical_vs_simulated.png")
    print_summary(rows)


if __name__ == "__main__":
    main()
