"""
Stage 2 – Step 2.1: Static Multi-Flow Experiments

Sweeps flows_per_neighbor (k) × ring_size × affected_fraction to show
that static multi-flow improves ring throughput under congestion.
"""
from __future__ import annotations

import csv
import itertools
import time
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
    CongestionModel,
    build_worker_ring,
    run_simple_ring_transfer,
)

# ─── Configuration ───────────────────────────────────────────
TOPO_K = 16
LINK_GBPS = 100.0
DT_S = 5e-5
BYTES_PER_NEIGHBOR = 256 * 1024 * 1024  # 256 MiB

SWEEP_K_VALUES = [1, 2, 4, 8]
SWEEP_RING_SIZES = [4, 8, 16, 32]
SWEEP_AFFECTED_FRACTIONS = [0.0, 0.1, 0.3, 0.5]
NUM_RUNS = 3

# Congestion model parameters — heavier, realistic core/agg congestion
# Congestion only on agg<->core and edge<->agg links (where ECMP provides
# alternative paths). Host<->edge links are unaffected since they are
# single-path and congestion there cannot be bypassed by multi-flow.
CONGESTED_UTIL_LOW = 0.50
CONGESTED_UTIL_HIGH = 0.95
NORMAL_UTIL_LOW = 0.00
NORMAL_UTIL_HIGH = 0.05
P_ON = 0.01
P_OFF = 0.005
TARGET_LAYERS = ["agg_core", "edge_agg"]

# ─── Output ──────────────────────────────────────────────────
TODAY = date.today().isoformat()
OUT_DIR = Path(f"{_RING_ROOT}/results/v2.0_multiflow_{TODAY}/static")


def make_congestion(affected_fraction: float, seed: int):
    if affected_fraction <= 0.0:
        return None
    return CongestionModel(
        mode="onoff", seed=seed, affected_fraction=affected_fraction,
        congested_util_low=CONGESTED_UTIL_LOW, congested_util_high=CONGESTED_UTIL_HIGH,
        normal_util_low=NORMAL_UTIL_LOW, normal_util_high=NORMAL_UTIL_HIGH,
        p_on=P_ON, p_off=P_OFF,
        target_layers=TARGET_LAYERS,
    )


def run_all_cases() -> List[Dict[str, Any]]:
    rows = []
    combos = list(itertools.product(SWEEP_K_VALUES, SWEEP_RING_SIZES, SWEEP_AFFECTED_FRACTIONS))
    total = len(combos) * NUM_RUNS
    count = 0

    for run_idx in range(NUM_RUNS):
        seed = int(time.time_ns()) % (2**31) + run_idx * 10000
        topo = FatTree(k=TOPO_K, link_capacity_Gbps=LINK_GBPS, seed=seed)

        for k_val, ring_size, frac in combos:
            count += 1
            ring = build_worker_ring(topo.hosts, worker_count=ring_size, start_index=0)
            cong = make_congestion(frac, seed + int(frac * 1000))

            print(f"[{count}/{total}] run={run_idx+1} k={k_val} P={ring_size} frac={frac:.1f} ...", end=" ")

            t = run_simple_ring_transfer(
                topo=topo, ring=ring, bytes_per_neighbor=BYTES_PER_NEIGHBOR,
                flows_per_neighbor=k_val, dt_s=DT_S, congestion=cong,
            )

            rows.append({
                "run": run_idx + 1,
                "seed": seed,
                "flows_per_neighbor": k_val,
                "ring_size": ring_size,
                "affected_fraction": frac,
                "completion_time_s": t,
            })
            print(f"t={t:.6f}s")

    return rows


def save_csv(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSV saved: {path}")


def plot_completion_vs_k(rows, path):
    """2x2 grid: one subplot per congestion level, lines per ring size."""
    fracs = sorted(set(r["affected_fraction"] for r in rows))
    ring_sizes = sorted(set(r["ring_size"] for r in rows))
    k_vals = sorted(set(r["flows_per_neighbor"] for r in rows))

    fig, axes = plt.subplots(2, 2, figsize=(14, 10), sharex=True)
    axes = axes.flatten()

    colors = plt.cm.tab10(np.linspace(0, 0.8, len(ring_sizes)))

    for ax_idx, frac in enumerate(fracs):
        ax = axes[ax_idx]
        for rs_idx, rs in enumerate(ring_sizes):
            means = []
            stds = []
            for k in k_vals:
                times = [r["completion_time_s"] for r in rows
                         if r["affected_fraction"] == frac and r["ring_size"] == rs
                         and r["flows_per_neighbor"] == k]
                means.append(np.mean(times))
                stds.append(np.std(times))

            ax.errorbar(k_vals, means, yerr=stds, marker="o", capsize=3,
                        label=f"P={rs}", color=colors[rs_idx])

        ax.set_title(f"Congestion: {frac:.0%}")
        ax.set_ylabel("Completion Time (s)")
        ax.set_xlabel("Flows per Neighbor (k)")
        ax.set_xticks(k_vals)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    fig.suptitle("Static Multi-Flow: Completion Time vs k", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    print(f"Plot saved: {path}")


def plot_heatmap(rows, path):
    """Speedup heatmap for P=16: k vs congestion level."""
    RS = 16
    k_vals = sorted(set(r["flows_per_neighbor"] for r in rows))
    fracs = sorted(set(r["affected_fraction"] for r in rows))

    # Compute mean times
    mean_times = {}
    for k in k_vals:
        for frac in fracs:
            times = [r["completion_time_s"] for r in rows
                     if r["ring_size"] == RS and r["flows_per_neighbor"] == k
                     and r["affected_fraction"] == frac]
            mean_times[(k, frac)] = np.mean(times) if times else float("nan")

    # Compute speedup vs k=1
    speedup = np.zeros((len(fracs), len(k_vals)))
    for fi, frac in enumerate(fracs):
        base = mean_times.get((1, frac), 1.0)
        for ki, k in enumerate(k_vals):
            speedup[fi, ki] = base / mean_times.get((k, frac), base)

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(speedup, aspect="auto", cmap="YlOrRd", origin="lower")
    ax.set_xticks(range(len(k_vals)))
    ax.set_xticklabels([str(k) for k in k_vals])
    ax.set_yticks(range(len(fracs)))
    ax.set_yticklabels([f"{f:.0%}" for f in fracs])
    ax.set_xlabel("Flows per Neighbor (k)")
    ax.set_ylabel("Congestion (affected fraction)")
    ax.set_title(f"Speedup vs k=1 Baseline (P={RS})")

    # Annotate cells
    for fi in range(len(fracs)):
        for ki in range(len(k_vals)):
            ax.text(ki, fi, f"{speedup[fi, ki]:.2f}x",
                    ha="center", va="center", fontsize=10, fontweight="bold")

    plt.colorbar(im, ax=ax, label="Speedup (x)")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    print(f"Plot saved: {path}")


def plot_speedup_bars(rows, path):
    """Grouped bars at congestion=0.3: ring_size × k."""
    FRAC = 0.3
    ring_sizes = sorted(set(r["ring_size"] for r in rows))
    k_vals = sorted(set(r["flows_per_neighbor"] for r in rows))

    x = np.arange(len(ring_sizes))
    width = 0.18
    colors = plt.cm.viridis(np.linspace(0.2, 0.9, len(k_vals)))

    fig, ax = plt.subplots(figsize=(12, 6))
    for ki, k in enumerate(k_vals):
        means = []
        for rs in ring_sizes:
            times = [r["completion_time_s"] for r in rows
                     if r["ring_size"] == rs and r["flows_per_neighbor"] == k
                     and r["affected_fraction"] == FRAC]
            means.append(np.mean(times))
        offset = (ki - len(k_vals) / 2 + 0.5) * width
        ax.bar(x + offset, means, width, label=f"k={k}", color=colors[ki])

    ax.set_xticks(x)
    ax.set_xticklabels([str(rs) for rs in ring_sizes])
    ax.set_xlabel("Ring Size (P)")
    ax.set_ylabel("Completion Time (s)")
    ax.set_title(f"Multi-Flow Effect at {FRAC:.0%} Congestion")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=200)
    print(f"Plot saved: {path}")


def print_summary(rows):
    print("\n" + "=" * 80)
    print("STATIC MULTI-FLOW SUMMARY (mean over runs)")
    print("=" * 80)

    grouped = defaultdict(list)
    for r in rows:
        grouped[(r["affected_fraction"], r["ring_size"], r["flows_per_neighbor"])].append(r["completion_time_s"])

    print(f"{'Cong':>6}  {'P':>4}  ", end="")
    k_vals = sorted(set(r["flows_per_neighbor"] for r in rows))
    for k in k_vals:
        print(f"{'k='+str(k):>12}", end="")
    print(f"  {'Speedup k1->8':>14}")
    print("-" * 80)

    for frac in sorted(set(r["affected_fraction"] for r in rows)):
        for rs in sorted(set(r["ring_size"] for r in rows)):
            print(f"{frac:>6.0%}  {rs:>4}  ", end="")
            t_k1 = np.mean(grouped[(frac, rs, 1)])
            for k in k_vals:
                t = np.mean(grouped[(frac, rs, k)])
                print(f"{t:>12.6f}", end="")
            t_k8 = np.mean(grouped[(frac, rs, max(k_vals))])
            speedup = t_k1 / t_k8 if t_k8 > 0 else 0
            print(f"  {speedup:>13.2f}x")


def main():
    print(f"Static Multi-Flow Experiment — k={SWEEP_K_VALUES}")
    print(f"P={SWEEP_RING_SIZES}, frac={SWEEP_AFFECTED_FRACTIONS}, {NUM_RUNS} runs")
    print(f"Output: {OUT_DIR}\n")

    rows = run_all_cases()
    save_csv(rows, OUT_DIR / "results.csv")
    plot_completion_vs_k(rows, OUT_DIR / "completion_vs_k.png")
    plot_heatmap(rows, OUT_DIR / "heatmap_k_vs_congestion.png")
    plot_speedup_bars(rows, OUT_DIR / "speedup_bars.png")
    print_summary(rows)


if __name__ == "__main__":
    main()
