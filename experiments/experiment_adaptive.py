"""
Stage 2 – Step 2.3: Adaptive vs Static vs Baseline Comparison

Three-way comparison of ring transfer approaches under congestion:
1. Baseline: k=1 (single flow per neighbor)
2. Static: k=4 (fixed multi-flow)
3. Adaptive: starts k=1, grows dynamically based on throughput
"""
from __future__ import annotations

import csv
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
    AdaptiveConfig,
    build_worker_ring,
    run_simple_ring_transfer,
    run_adaptive_ring_transfer,
)

# ─── Configuration ───────────────────────────────────────────
TOPO_K = 16
LINK_GBPS = 100.0
DT_S = 5e-5
BYTES_PER_NEIGHBOR = 256 * 1024 * 1024  # 256 MiB

SWEEP_RING_SIZES = [8, 16]
SWEEP_AFFECTED_FRACTIONS = [0.0, 0.1, 0.3, 0.5]
STATIC_K = 4
NUM_RUNS = 3

ADAPTIVE_CFG = AdaptiveConfig(
    measurement_window_s=0.001,
    threshold=0.2,
    k_max=4,
    cooldown_ticks=200,
)

# Congestion model parameters — realistic core/agg congestion
CONGESTED_UTIL_LOW = 0.50
CONGESTED_UTIL_HIGH = 0.95
NORMAL_UTIL_LOW = 0.00
NORMAL_UTIL_HIGH = 0.05
P_ON = 0.01
P_OFF = 0.005
TARGET_LAYERS = ["agg_core", "edge_agg"]

# ─── Output ──────────────────────────────────────────────────
TODAY = date.today().isoformat()
OUT_DIR = Path(f"{_RING_ROOT}/results/v2.0_multiflow_{TODAY}/adaptive")


def make_congestion(affected_fraction, seed):
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
    total = len(SWEEP_RING_SIZES) * len(SWEEP_AFFECTED_FRACTIONS) * NUM_RUNS * 3
    count = 0

    # Store one representative adaptive result for convergence plot
    convergence_data = None

    for run_idx in range(NUM_RUNS):
        seed = int(time.time_ns()) % (2**31) + run_idx * 10000

        for ring_size in SWEEP_RING_SIZES:
            topo = FatTree(k=TOPO_K, link_capacity_Gbps=LINK_GBPS, seed=seed)
            ring = build_worker_ring(topo.hosts, worker_count=ring_size, start_index=0)

            for frac in SWEEP_AFFECTED_FRACTIONS:
                cong_seed = seed + int(frac * 1000)

                # --- Baseline (k=1) ---
                count += 1
                print(f"[{count}/{total}] baseline P={ring_size} frac={frac:.1f} ...", end=" ")
                cong = make_congestion(frac, cong_seed)
                t_base = run_simple_ring_transfer(
                    topo=topo, ring=ring, bytes_per_neighbor=BYTES_PER_NEIGHBOR,
                    flows_per_neighbor=1, dt_s=DT_S, congestion=cong,
                )
                rows.append({
                    "run": run_idx + 1, "ring_size": ring_size,
                    "affected_fraction": frac, "method": "baseline",
                    "completion_time_s": t_base, "final_k_mean": 1.0, "final_k_max": 1,
                })
                print(f"t={t_base:.6f}s")

                # --- Static (k=STATIC_K) ---
                count += 1
                print(f"[{count}/{total}] static(k={STATIC_K}) P={ring_size} frac={frac:.1f} ...", end=" ")
                cong = make_congestion(frac, cong_seed)
                t_static = run_simple_ring_transfer(
                    topo=topo, ring=ring, bytes_per_neighbor=BYTES_PER_NEIGHBOR,
                    flows_per_neighbor=STATIC_K, dt_s=DT_S, congestion=cong,
                )
                rows.append({
                    "run": run_idx + 1, "ring_size": ring_size,
                    "affected_fraction": frac, "method": f"static(k={STATIC_K})",
                    "completion_time_s": t_static,
                    "final_k_mean": float(STATIC_K), "final_k_max": STATIC_K,
                })
                print(f"t={t_static:.6f}s")

                # --- Adaptive ---
                count += 1
                print(f"[{count}/{total}] adaptive P={ring_size} frac={frac:.1f} ...", end=" ")
                cong = make_congestion(frac, cong_seed)
                result = run_adaptive_ring_transfer(
                    topo=topo, ring=ring, bytes_per_neighbor=BYTES_PER_NEIGHBOR,
                    adaptive_cfg=ADAPTIVE_CFG, dt_s=DT_S, congestion=cong,
                )
                k_values = list(result["final_k_per_edge"].values())
                rows.append({
                    "run": run_idx + 1, "ring_size": ring_size,
                    "affected_fraction": frac, "method": "adaptive",
                    "completion_time_s": result["completion_time_s"],
                    "final_k_mean": np.mean(k_values),
                    "final_k_max": max(k_values),
                })
                print(f"t={result['completion_time_s']:.6f}s k_avg={np.mean(k_values):.1f} k_max={max(k_values)}")

                # Save convergence data for P=16, frac=0.3, first run
                if (ring_size == 16 and frac == 0.3 and run_idx == 0
                        and result["k_history"]):
                    convergence_data = result

    return rows, convergence_data


def save_csv(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSV saved: {path}")


def plot_comparison(rows, path):
    """Grouped bars: baseline/static/adaptive per congestion level, fixed P=16."""
    RS = 16
    fracs = sorted(set(r["affected_fraction"] for r in rows))
    methods = ["baseline", f"static(k={STATIC_K})", "adaptive"]
    colors = {"baseline": "#1f77b4", f"static(k={STATIC_K})": "#ff7f0e", "adaptive": "#2ca02c"}

    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(fracs))
    width = 0.25

    for mi, method in enumerate(methods):
        means = []
        stds = []
        for frac in fracs:
            times = [r["completion_time_s"] for r in rows
                     if r["ring_size"] == RS and r["affected_fraction"] == frac
                     and r["method"] == method]
            means.append(np.mean(times))
            stds.append(np.std(times))
        offset = (mi - 1) * width
        ax.bar(x + offset, means, width, yerr=stds, capsize=4,
               label=method, color=colors[method], alpha=0.85)

    ax.set_xticks(x)
    ax.set_xticklabels([f"{f:.0%}" for f in fracs])
    ax.set_xlabel("Congestion (fraction of links affected)")
    ax.set_ylabel("Completion Time (s)")
    ax.set_title(f"Baseline vs Static(k={STATIC_K}) vs Adaptive (P={RS}, M=256 MiB)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=200)
    print(f"Plot saved: {path}")


def plot_convergence(convergence_data, path):
    """k over time for each logical edge (representative run)."""
    if convergence_data is None:
        print("No convergence data — skipping convergence plot")
        return

    k_history = convergence_data["k_history"]
    P = convergence_data["ring_size"]

    fig, ax = plt.subplots(figsize=(12, 6))

    # Build k trajectory per edge
    edge_k = defaultdict(list)  # edge_index -> [(time, k)]
    for t_s, edge_idx, new_k in k_history:
        edge_k[edge_idx].append((t_s, new_k))

    colors = plt.cm.tab20(np.linspace(0, 1, P))
    for edge_idx in range(P):
        trajectory = edge_k.get(edge_idx, [])
        if not trajectory:
            # Edge stayed at k=1
            ax.plot([0, convergence_data["completion_time_s"]], [1, 1],
                    color=colors[edge_idx], alpha=0.3, linewidth=1)
        else:
            # Build step function
            times = [0] + [t for t, k in trajectory] + [convergence_data["completion_time_s"]]
            ks = [1] + [k for t, k in trajectory] + [trajectory[-1][1]]
            ax.step(times, ks, where="post", color=colors[edge_idx],
                    linewidth=1.5, alpha=0.7, label=f"Edge {edge_idx}")

    ax.set_xlabel("Simulation Time (s)")
    ax.set_ylabel("Flows per Edge (k)")
    ax.set_title("Adaptive Controller Convergence (P=16, Congestion=30%)")
    if P <= 20:
        ax.legend(fontsize=7, ncol=2, loc="upper left")
    ax.grid(True, alpha=0.3)
    ax.set_ylim(0.5, ADAPTIVE_CFG.k_max + 0.5)

    fig.tight_layout()
    fig.savefig(path, dpi=200)
    print(f"Plot saved: {path}")


def plot_k_distribution(rows, path):
    """Box plot of final k per edge by congestion level (adaptive only)."""
    adaptive_rows = [r for r in rows if r["method"] == "adaptive"]
    fracs = sorted(set(r["affected_fraction"] for r in adaptive_rows))

    fig, ax = plt.subplots(figsize=(10, 6))

    data_by_frac = defaultdict(list)
    for r in adaptive_rows:
        data_by_frac[r["affected_fraction"]].append(r["final_k_mean"])

    box_data = [data_by_frac[f] for f in fracs]
    labels = [f"{f:.0%}" for f in fracs]

    bp = ax.boxplot(box_data, tick_labels=labels, patch_artist=True)
    colors = plt.cm.RdYlGn_r(np.linspace(0.1, 0.9, len(fracs)))
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)

    ax.set_xlabel("Congestion (fraction of links affected)")
    ax.set_ylabel("Mean Final k per Edge")
    ax.set_title("Adaptive Controller: Flow Allocation by Congestion Level")
    ax.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=200)
    print(f"Plot saved: {path}")


def print_summary(rows):
    print("\n" + "=" * 85)
    print("ADAPTIVE vs STATIC vs BASELINE SUMMARY")
    print("=" * 85)

    grouped = defaultdict(list)
    for r in rows:
        grouped[(r["ring_size"], r["affected_fraction"], r["method"])].append(r)

    for rs in sorted(set(r["ring_size"] for r in rows)):
        print(f"\n--- Ring Size P={rs} ---")
        print(f"{'Cong':>6}  {'Baseline (s)':>14}  {f'Static k={STATIC_K} (s)':>14}  {'Adaptive (s)':>14}  {'Speedup':>8}")
        for frac in sorted(set(r["affected_fraction"] for r in rows)):
            base = np.mean([r["completion_time_s"] for r in grouped[(rs, frac, "baseline")]])
            static = np.mean([r["completion_time_s"] for r in grouped[(rs, frac, f"static(k={STATIC_K})")]])
            adapt = np.mean([r["completion_time_s"] for r in grouped[(rs, frac, "adaptive")]])
            speedup = base / adapt if adapt > 0 else 0
            print(f"{frac:>6.0%}  {base:>14.6f}  {static:>14.6f}  {adapt:>14.6f}  {speedup:>7.2f}x")

    print("=" * 85)


def main():
    print(f"Adaptive vs Static vs Baseline Comparison")
    print(f"P={SWEEP_RING_SIZES}, frac={SWEEP_AFFECTED_FRACTIONS}")
    print(f"Static k={STATIC_K}, Adaptive cfg: threshold={ADAPTIVE_CFG.threshold}, k_max={ADAPTIVE_CFG.k_max}")
    print(f"Output: {OUT_DIR}\n")

    rows, convergence_data = run_all_cases()
    save_csv(rows, OUT_DIR / "results.csv")
    plot_comparison(rows, OUT_DIR / "comparison.png")
    plot_convergence(convergence_data, OUT_DIR / "convergence.png")
    plot_k_distribution(rows, OUT_DIR / "k_distribution.png")
    print_summary(rows)


if __name__ == "__main__":
    main()
