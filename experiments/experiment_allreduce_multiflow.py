"""
Stage 3 – Step 3b: Multi-Flow Ring All-Reduce Under Congestion

Evaluates static multi-flow (k=1,2,4,8) on the full pipelined Ring All-Reduce
algorithm under targeted core/agg congestion.
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
    run_ring_allreduce,
    run_simple_ring_transfer,
)

# ─── Configuration ───────────────────────────────────────────
TOPO_K = 16
LINK_GBPS = 100.0
DT_S = 5e-5

SWEEP_K = [1, 2, 4, 8]
SWEEP_P = [8, 16]
SWEEP_M = [256 * 1024 * 1024]  # 256 MiB
M_LABEL = {256 * 1024 * 1024: "256 MiB"}
SWEEP_FRAC = [0.0, 0.3, 0.5]
PIPELINE_WINDOW = 4
NUM_RUNS = 3

# Congestion (same as Stage 2)
CONG_PARAMS = dict(
    congested_util_low=0.50, congested_util_high=0.95,
    normal_util_low=0.00, normal_util_high=0.05,
    p_on=0.01, p_off=0.005,
    target_layers=["agg_core", "edge_agg"],
)

TODAY = date.today().isoformat()
OUT_DIR = Path(f"{_RING_ROOT}/results/v3.0_allreduce_{TODAY}/multiflow")


def make_congestion(frac, seed):
    if frac <= 0.0:
        return None
    return CongestionModel(mode="onoff", seed=seed, affected_fraction=frac, **CONG_PARAMS)


def run_all() -> List[Dict[str, Any]]:
    rows = []
    combos = list(itertools.product(SWEEP_K, SWEEP_P, SWEEP_M, SWEEP_FRAC))
    total = len(combos) * NUM_RUNS
    count = 0

    for run_idx in range(NUM_RUNS):
        seed = int(time.time_ns()) % (2**31) + run_idx * 10000

        for k, P, M, frac in combos:
            count += 1
            topo = FatTree(k=TOPO_K, link_capacity_Gbps=LINK_GBPS, seed=seed)
            ring = build_worker_ring(topo.hosts, worker_count=P, start_index=0)
            cong = make_congestion(frac, seed + int(frac * 1000))

            print(f"[{count}/{total}] k={k} P={P} frac={frac:.0%} ...", end=" ")

            # Pipelined all-reduce
            ar = run_ring_allreduce(
                topo=topo, ring=ring, total_bytes_M=M,
                flows_per_neighbor=k, dt_s=DT_S,
                pipelined=True, pipeline_window=PIPELINE_WINDOW,
                alpha_s=0.0, congestion=cong,
            )

            # Also run simple transfer for comparison
            cong2 = make_congestion(frac, seed + int(frac * 1000))
            t_simple = run_simple_ring_transfer(
                topo=topo, ring=ring, bytes_per_neighbor=M,
                flows_per_neighbor=k, dt_s=DT_S, congestion=cong2,
            )

            row = {
                "run": run_idx + 1, "seed": seed,
                "flows_per_neighbor": k, "ring_size": P,
                "msg_bytes": M, "affected_fraction": frac,
                "allreduce_time_s": ar.total_time_s,
                "simple_transfer_time_s": t_simple,
                "mean_step_s": np.mean(ar.step_times_s),
                "std_step_s": np.std(ar.step_times_s),
                "max_step_s": max(ar.step_times_s),
                "p99_step_s": np.percentile(ar.step_times_s, 99),
                "total_steps": len(ar.step_times_s),
            }
            rows.append(row)
            print(f"AR={ar.total_time_s:.6f}s simple={t_simple:.6f}s steps={len(ar.step_times_s)}")

    return rows


def save_csv(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSV saved: {path}")


def plot_completion_vs_k(rows, path):
    """Allreduce completion time vs k, one subplot per congestion level."""
    fracs = sorted(set(r["affected_fraction"] for r in rows))
    p_vals = sorted(set(r["ring_size"] for r in rows))
    k_vals = sorted(set(r["flows_per_neighbor"] for r in rows))

    fig, axes = plt.subplots(1, len(fracs), figsize=(6 * len(fracs), 5), sharey=True)
    if len(fracs) == 1:
        axes = [axes]
    colors = plt.cm.tab10(np.linspace(0, 0.5, len(p_vals)))

    for ax, frac in zip(axes, fracs):
        for pi, P in enumerate(p_vals):
            means, stds = [], []
            for k in k_vals:
                times = [r["allreduce_time_s"] for r in rows
                         if r["affected_fraction"] == frac and r["ring_size"] == P
                         and r["flows_per_neighbor"] == k]
                means.append(np.mean(times))
                stds.append(np.std(times))
            ax.errorbar(k_vals, means, yerr=stds, marker="o", capsize=3,
                        label=f"P={P}", color=colors[pi])

        ax.set_title(f"Congestion: {frac:.0%}")
        ax.set_xlabel("Flows per Neighbor (k)")
        ax.set_xticks(k_vals)
        ax.legend()
        ax.grid(True, alpha=0.3)
    axes[0].set_ylabel("All-Reduce Completion Time (s)")

    fig.suptitle("Pipelined Ring All-Reduce: Multi-Flow Effect", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    print(f"Plot saved: {path}")


def plot_step_times(rows, path):
    """Per-step time statistics by congestion and k."""
    fracs = sorted(set(r["affected_fraction"] for r in rows))
    k_vals = sorted(set(r["flows_per_neighbor"] for r in rows))
    P_FIXED = 16

    fig, axes = plt.subplots(1, len(fracs), figsize=(6 * len(fracs), 5), sharey=True)
    if len(fracs) == 1:
        axes = [axes]

    for ax, frac in zip(axes, fracs):
        mean_steps = []
        p99_steps = []
        for k in k_vals:
            ms = [r["mean_step_s"] for r in rows
                  if r["affected_fraction"] == frac and r["ring_size"] == P_FIXED
                  and r["flows_per_neighbor"] == k]
            p99 = [r["p99_step_s"] for r in rows
                   if r["affected_fraction"] == frac and r["ring_size"] == P_FIXED
                   and r["flows_per_neighbor"] == k]
            mean_steps.append(np.mean(ms))
            p99_steps.append(np.mean(p99))

        x = np.arange(len(k_vals))
        ax.bar(x - 0.15, mean_steps, 0.3, label="Mean step", color="#2196F3")
        ax.bar(x + 0.15, p99_steps, 0.3, label="P99 step", color="#FF5722")
        ax.set_xticks(x)
        ax.set_xticklabels([str(k) for k in k_vals])
        ax.set_title(f"Congestion: {frac:.0%}")
        ax.set_xlabel("Flows per Neighbor (k)")
        ax.legend()
        ax.grid(axis="y", alpha=0.3)

    axes[0].set_ylabel("Per-Step Time (s)")
    fig.suptitle(f"All-Reduce Step Times (P={P_FIXED})", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    print(f"Plot saved: {path}")


def plot_allreduce_vs_simple(rows, path):
    """Compare allreduce speedup vs simple transfer speedup."""
    P_FIXED = 16
    k_vals = sorted(set(r["flows_per_neighbor"] for r in rows))
    fracs = sorted(set(r["affected_fraction"] for r in rows))
    fracs = [f for f in fracs if f > 0]  # skip 0%

    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(k_vals))
    width = 0.35
    colors_ar = plt.cm.Blues(np.linspace(0.4, 0.8, len(fracs)))
    colors_st = plt.cm.Oranges(np.linspace(0.4, 0.8, len(fracs)))

    for fi, frac in enumerate(fracs):
        ar_speedups, st_speedups = [], []
        for k in k_vals:
            ar_k1 = np.mean([r["allreduce_time_s"] for r in rows
                             if r["ring_size"] == P_FIXED and r["affected_fraction"] == frac
                             and r["flows_per_neighbor"] == 1])
            ar_k = np.mean([r["allreduce_time_s"] for r in rows
                            if r["ring_size"] == P_FIXED and r["affected_fraction"] == frac
                            and r["flows_per_neighbor"] == k])
            st_k1 = np.mean([r["simple_transfer_time_s"] for r in rows
                             if r["ring_size"] == P_FIXED and r["affected_fraction"] == frac
                             and r["flows_per_neighbor"] == 1])
            st_k = np.mean([r["simple_transfer_time_s"] for r in rows
                            if r["ring_size"] == P_FIXED and r["affected_fraction"] == frac
                            and r["flows_per_neighbor"] == k])
            ar_speedups.append(ar_k1 / ar_k if ar_k > 0 else 1)
            st_speedups.append(st_k1 / st_k if st_k > 0 else 1)

        offset = fi * 0.15
        ax.bar(x - width / 2 + offset, ar_speedups, width / len(fracs),
               label=f"AllReduce {frac:.0%}", color=colors_ar[fi])
        ax.bar(x + width / 2 + offset, st_speedups, width / len(fracs),
               label=f"Simple {frac:.0%}", color=colors_st[fi])

    ax.set_xticks(x)
    ax.set_xticklabels([f"k={k}" for k in k_vals])
    ax.set_ylabel("Speedup vs k=1")
    ax.set_title(f"Multi-Flow Speedup: All-Reduce vs Simple Transfer (P={P_FIXED})")
    ax.axhline(y=1.0, color="gray", linestyle="--", linewidth=0.8)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=200)
    print(f"Plot saved: {path}")


def print_summary(rows):
    print("\n" + "=" * 85)
    print("ALL-REDUCE MULTI-FLOW SUMMARY")
    print("=" * 85)

    grouped = defaultdict(list)
    for r in rows:
        grouped[(r["ring_size"], r["affected_fraction"], r["flows_per_neighbor"])].append(r)

    for P in sorted(set(r["ring_size"] for r in rows)):
        print(f"\n--- P={P} ---")
        k_vals = sorted(set(r["flows_per_neighbor"] for r in rows))
        print(f"{'Cong':>6}", end="")
        for k in k_vals:
            print(f"  {'k='+str(k):>10}", end="")
        print(f"  {'Speedup':>10}")
        print("-" * 85)

        for frac in sorted(set(r["affected_fraction"] for r in rows)):
            print(f"{frac:>6.0%}", end="")
            t_k1 = np.mean([r["allreduce_time_s"] for r in grouped[(P, frac, 1)]])
            for k in k_vals:
                t = np.mean([r["allreduce_time_s"] for r in grouped[(P, frac, k)]])
                print(f"  {t:>10.6f}", end="")
            t_kmax = np.mean([r["allreduce_time_s"] for r in grouped[(P, frac, max(k_vals))]])
            speedup = t_k1 / t_kmax if t_kmax > 0 else 0
            print(f"  {speedup:>9.2f}x")

    print("=" * 85)


def main():
    print(f"All-Reduce Multi-Flow Experiment")
    print(f"k={SWEEP_K}, P={SWEEP_P}, frac={SWEEP_FRAC}, pipeline_window={PIPELINE_WINDOW}")
    print(f"Output: {OUT_DIR}\n")

    rows = run_all()
    save_csv(rows, OUT_DIR / "results.csv")
    plot_completion_vs_k(rows, OUT_DIR / "allreduce_completion_vs_k.png")
    plot_step_times(rows, OUT_DIR / "allreduce_step_times.png")
    plot_allreduce_vs_simple(rows, OUT_DIR / "allreduce_vs_simple.png")
    print_summary(rows)


if __name__ == "__main__":
    main()
