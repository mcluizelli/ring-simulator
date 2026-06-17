"""
Stage 3 – Step 3a: Validate Ring All-Reduce Against Theoretical Model

Verifies:
    T_allreduce = 2(P-1) * (chunk_bytes / B*)
where chunk_bytes = M / P, B* = bottleneck bandwidth, and alpha=0 (flow-level sim).

Runs non-pipelined allreduce with no congestion.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import List, Dict, Any

import numpy as np
import matplotlib.pyplot as plt

# --- bootstrap: make the simulator core (../sim.py) importable from this subfolder ---
import sys as _sys
from pathlib import Path as _BootPath
_RING_ROOT = _BootPath(__file__).resolve().parents[1]
if str(_RING_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_RING_ROOT))
# ------------------------------------------------------------------------------------
from sim import (
    FatTree,
    build_worker_ring,
    run_ring_allreduce,
    compute_ring_theoretical_time,
)

# ─── Configuration ───────────────────────────────────────────
TOPO_K = 16
LINK_GBPS = 100.0
DT_S = 5e-5

RING_SIZES = [4, 8, 16]
MSG_SIZES = [64 * 1024 * 1024, 256 * 1024 * 1024]
MSG_LABELS = {64 * 1024 * 1024: "64 MiB", 256 * 1024 * 1024: "256 MiB"}
FLOWS_PER_NEIGHBOR = 1
SEEDS = [1, 42]

TODAY = date.today().isoformat()
OUT_DIR = Path(f"{_RING_ROOT}/results/v3.0_allreduce_{TODAY}/validation")


def run_all() -> List[Dict[str, Any]]:
    rows = []
    total = len(SEEDS) * len(RING_SIZES) * len(MSG_SIZES)
    count = 0

    for seed in SEEDS:
        topo = FatTree(k=TOPO_K, link_capacity_Gbps=LINK_GBPS, seed=seed)

        for P in RING_SIZES:
            ring = build_worker_ring(topo.hosts, worker_count=P, start_index=0)

            # Get B* from theoretical analysis (no congestion)
            theory = compute_ring_theoretical_time(
                topo, ring, bytes_per_neighbor=1.0,  # dummy
                flows_per_neighbor=FLOWS_PER_NEIGHBOR,
            )
            B_star = theory["bottleneck_bandwidth_Bps"]

            for M in MSG_SIZES:
                count += 1
                print(f"[{count}/{total}] seed={seed} P={P} M={MSG_LABELS[M]} ...", end=" ")

                # Theoretical: T = 2(P-1) * (M/P) / B*
                chunk = M / P
                steps = 2 * (P - 1)
                theo_time = steps * (chunk / B_star) if B_star > 0 else float("inf")

                # Simulated (non-pipelined, no congestion)
                result = run_ring_allreduce(
                    topo=topo, ring=ring, total_bytes_M=M,
                    flows_per_neighbor=FLOWS_PER_NEIGHBOR,
                    dt_s=DT_S, pipelined=False, alpha_s=0.0,
                )
                sim_time = result.total_time_s
                ratio = sim_time / theo_time if theo_time > 0 else float("inf")

                row = {
                    "seed": seed, "ring_size": P,
                    "msg_bytes": M, "msg_label": MSG_LABELS[M],
                    "total_steps": steps, "chunk_bytes": chunk,
                    "B_star_Gbps": B_star * 8 / 1e9,
                    "theoretical_time_s": theo_time,
                    "simulated_time_s": sim_time,
                    "ratio": ratio,
                    "mean_step_s": np.mean(result.step_times_s),
                    "std_step_s": np.std(result.step_times_s),
                }
                rows.append(row)
                print(f"sim={sim_time:.6f} theo={theo_time:.6f} ratio={ratio:.4f}")

    return rows


def save_csv(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSV saved: {path}")


def plot_validation(rows, path):
    fig, ax = plt.subplots(figsize=(8, 8))

    colors = {"64 MiB": "#1f77b4", "256 MiB": "#ff7f0e"}
    size_scale = {4: 50, 8: 90, 16: 140}

    for r in rows:
        ax.scatter(r["theoretical_time_s"], r["simulated_time_s"],
                   c=colors[r["msg_label"]], s=size_scale.get(r["ring_size"], 80),
                   alpha=0.7, edgecolors="black", linewidths=0.5)

    all_t = [r["theoretical_time_s"] for r in rows] + [r["simulated_time_s"] for r in rows]
    lo, hi = min(all_t) * 0.9, max(all_t) * 1.1
    ax.plot([lo, hi], [lo, hi], "k--", linewidth=1, label="y = x")

    for label, color in colors.items():
        ax.scatter([], [], c=color, s=80, label=f"M = {label}", edgecolors="black")
    for P, sz in sorted(size_scale.items()):
        ax.scatter([], [], c="gray", s=sz, label=f"P = {P}", edgecolors="black")

    ratios = [r["ratio"] for r in rows]
    ax.text(0.05, 0.95, f"Mean ratio: {np.mean(ratios):.4f} +/- {np.std(ratios):.4f}",
            transform=ax.transAxes, fontsize=10, va="top",
            bbox=dict(boxstyle="round", facecolor="lightyellow", alpha=0.8))

    ax.set_xlabel("Theoretical Time (s)")
    ax.set_ylabel("Simulated Time (s)")
    ax.set_title("All-Reduce Validation: Simulated vs Theoretical")
    ax.legend(loc="lower right", fontsize=9)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    print(f"Plot saved: {path}")


def print_summary(rows):
    print("\n" + "=" * 75)
    print("ALL-REDUCE VALIDATION SUMMARY")
    print("=" * 75)
    print(f"{'P':>4}  {'M':>8}  {'Steps':>6}  {'Sim (s)':>10}  {'Theo (s)':>10}  {'Ratio':>8}")
    print("-" * 75)

    grouped = defaultdict(list)
    for r in rows:
        grouped[(r["ring_size"], r["msg_label"])].append(r)

    for (P, ml), group in sorted(grouped.items()):
        sim_m = np.mean([r["simulated_time_s"] for r in group])
        theo_m = np.mean([r["theoretical_time_s"] for r in group])
        ratio_m = np.mean([r["ratio"] for r in group])
        steps = group[0]["total_steps"]
        print(f"{P:>4}  {ml:>8}  {steps:>6}  {sim_m:>10.6f}  {theo_m:>10.6f}  {ratio_m:>8.4f}")

    ratios = [r["ratio"] for r in rows]
    print("-" * 75)
    print(f"Overall mean ratio: {np.mean(ratios):.4f} +/- {np.std(ratios):.4f}")
    print("=" * 75)


def main():
    print(f"All-Reduce Validation - Fat-Tree k={TOPO_K}, {LINK_GBPS} Gbps")
    print(f"Non-pipelined, no congestion, alpha=0\n")

    rows = run_all()
    save_csv(rows, OUT_DIR / "results.csv")
    plot_validation(rows, OUT_DIR / "allreduce_theoretical_vs_simulated.png")
    print_summary(rows)


if __name__ == "__main__":
    main()
