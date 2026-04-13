"""
Stage 3 – Step 3c: All-Reduce Under Realistic Background Traffic

Uses BackgroundTrafficGenerator (competing flows) instead of the
statistical CongestionModel. This models realistic cross-traffic
from other training jobs sharing the same Fat-Tree fabric.
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

from sim import (
    FatTree,
    BackgroundTrafficConfig,
    build_worker_ring,
    run_ring_allreduce,
)

# ─── Configuration ───────────────────────────────────────────
TOPO_K = 16
LINK_GBPS = 100.0
DT_S = 5e-5

RING_SIZE = 16
MSG_BYTES = 256 * 1024 * 1024  # 256 MiB
PIPELINE_WINDOW = 4

SWEEP_K = [1, 4]
SWEEP_ARRIVAL_RATES = [0, 200, 500, 1000]  # flows per second (0 = no background)
NUM_RUNS = 3

TODAY = date.today().isoformat()
OUT_DIR = Path(f"results/v3.0_allreduce_{TODAY}/background")


def make_bg_config(arrival_rate, seed):
    if arrival_rate <= 0:
        return None
    return BackgroundTrafficConfig(
        seed=seed,
        arrival_rate_fps=arrival_rate,
        size_dist="lognormal",
        mean_bytes=50 * 1024 * 1024,  # 50 MiB mean flow size
        sigma_logn=1.0,
        locality="mixed",
        p_local=0.5,
    )


def run_all() -> List[Dict[str, Any]]:
    rows = []
    combos = list(itertools.product(SWEEP_K, SWEEP_ARRIVAL_RATES))
    total = len(combos) * NUM_RUNS
    count = 0

    for run_idx in range(NUM_RUNS):
        seed = int(time.time_ns()) % (2**31) + run_idx * 10000
        topo = FatTree(k=TOPO_K, link_capacity_Gbps=LINK_GBPS, seed=seed)
        ring = build_worker_ring(topo.hosts, worker_count=RING_SIZE, start_index=0)

        for k, rate in combos:
            count += 1
            bg = make_bg_config(rate, seed + rate)

            print(f"[{count}/{total}] k={k} rate={rate} fps ...", end=" ", flush=True)

            ar = run_ring_allreduce(
                topo=topo, ring=ring, total_bytes_M=MSG_BYTES,
                flows_per_neighbor=k, dt_s=DT_S,
                pipelined=True, pipeline_window=PIPELINE_WINDOW,
                alpha_s=0.0, background_cfg=bg,
            )

            row = {
                "run": run_idx + 1, "seed": seed,
                "flows_per_neighbor": k,
                "arrival_rate_fps": rate,
                "allreduce_time_s": ar.total_time_s,
                "mean_step_s": np.mean(ar.step_times_s),
                "std_step_s": np.std(ar.step_times_s),
                "p99_step_s": np.percentile(ar.step_times_s, 99),
                "max_step_s": max(ar.step_times_s),
            }
            rows.append(row)
            print(f"AR={ar.total_time_s:.6f}s mean_step={row['mean_step_s']:.6f}s")

    return rows


def save_csv(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSV saved: {path}")


def plot_background_effect(rows, path):
    """Completion time vs arrival rate, k=1 vs k=4."""
    fig, ax = plt.subplots(figsize=(10, 6))

    colors = {1: "#1f77b4", 4: "#2ca02c"}
    markers = {1: "o", 4: "s"}

    for k in SWEEP_K:
        rates = sorted(set(r["arrival_rate_fps"] for r in rows))
        means, stds = [], []
        for rate in rates:
            times = [r["allreduce_time_s"] for r in rows
                     if r["flows_per_neighbor"] == k and r["arrival_rate_fps"] == rate]
            means.append(np.mean(times))
            stds.append(np.std(times))

        ax.errorbar(rates, means, yerr=stds, marker=markers[k], capsize=5,
                     linewidth=2, markersize=8, label=f"k={k}", color=colors[k])

    ax.set_xlabel("Background Traffic (flows/sec)")
    ax.set_ylabel("All-Reduce Completion Time (s)")
    ax.set_title(f"All-Reduce Under Background Traffic (P={RING_SIZE}, M=256 MiB)")
    ax.legend(fontsize=12)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=200)
    print(f"Plot saved: {path}")


def plot_step_time_cdf(rows, path):
    """CDF of per-step times for k=1 vs k=4 at highest traffic rate."""
    max_rate = max(SWEEP_ARRIVAL_RATES)
    if max_rate == 0:
        print("No background traffic runs — skipping CDF plot")
        return

    fig, ax = plt.subplots(figsize=(10, 6))
    colors = {1: "#1f77b4", 4: "#2ca02c"}

    for k in SWEEP_K:
        # Collect all per-step times at max rate
        all_step_times = []
        for r in rows:
            if r["flows_per_neighbor"] == k and r["arrival_rate_fps"] == max_rate:
                # We don't have individual step times in CSV, use mean/p99
                all_step_times.append(r["mean_step_s"])
                all_step_times.append(r["p99_step_s"])

        if all_step_times:
            sorted_t = np.sort(all_step_times)
            cdf = np.arange(1, len(sorted_t) + 1) / len(sorted_t)
            ax.plot(sorted_t, cdf, label=f"k={k}", color=colors[k], linewidth=2)

    ax.set_xlabel("Per-Step Time (s)")
    ax.set_ylabel("CDF")
    ax.set_title(f"Step Time Distribution at {max_rate} fps Background Traffic")
    ax.legend()
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=200)
    print(f"Plot saved: {path}")


def print_summary(rows):
    print("\n" + "=" * 80)
    print("BACKGROUND TRAFFIC SUMMARY")
    print("=" * 80)

    grouped = defaultdict(list)
    for r in rows:
        grouped[(r["arrival_rate_fps"], r["flows_per_neighbor"])].append(r)

    print(f"{'Rate':>8}  {'k=1 (s)':>10}  {'k=4 (s)':>10}  {'Speedup':>8}  {'k=1 P99':>10}  {'k=4 P99':>10}")
    print("-" * 80)

    for rate in sorted(set(r["arrival_rate_fps"] for r in rows)):
        t1 = np.mean([r["allreduce_time_s"] for r in grouped[(rate, 1)]])
        t4 = np.mean([r["allreduce_time_s"] for r in grouped[(rate, 4)]])
        p99_1 = np.mean([r["p99_step_s"] for r in grouped[(rate, 1)]])
        p99_4 = np.mean([r["p99_step_s"] for r in grouped[(rate, 4)]])
        speedup = t1 / t4 if t4 > 0 else 0
        print(f"{rate:>8}  {t1:>10.6f}  {t4:>10.6f}  {speedup:>7.2f}x  {p99_1:>10.6f}  {p99_4:>10.6f}")

    print("=" * 80)


def main():
    print(f"All-Reduce Background Traffic Experiment")
    print(f"P={RING_SIZE}, M=256 MiB, k={SWEEP_K}, rates={SWEEP_ARRIVAL_RATES}")
    print(f"Output: {OUT_DIR}\n")

    rows = run_all()
    save_csv(rows, OUT_DIR / "results.csv")
    plot_background_effect(rows, OUT_DIR / "background_effect.png")
    plot_step_time_cdf(rows, OUT_DIR / "step_time_cdf.png")
    print_summary(rows)


if __name__ == "__main__":
    main()
