"""
D.6 — Multi-flow benefit across congestion models.

Runs the simple ring transfer at P=16 for k in {1,2,4,8} under each of the five
congestion models (onoff / iid / hot_spot / incast / microburst), with FIXED
seeds and per-seed-paired speedup + bootstrap 95% CI (same methodology as v5.1).

Goal: show WHERE multi-flow helps (hot_spot), where it is NEUTRAL (incast — the
single-path access-link limit), and where it is high-variance / can hurt.

Usage:
    python experiments/experiment_congestion_models.py [n_seeds]   # default 100; use a small
                                                        # number for a quick pilot
"""
from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Any

import numpy as np
import matplotlib.pyplot as plt

# --- bootstrap: make the simulator core (../sim.py) importable from this subfolder ---
import sys as _sys
from pathlib import Path as _BootPath
_RING_ROOT = _BootPath(__file__).resolve().parents[1]
if str(_RING_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_RING_ROOT))
# ------------------------------------------------------------------------------------
from sim import FatTree, CongestionModel, build_worker_ring, run_simple_ring_transfer

# ─── Configuration ───────────────────────────────────────────
TOPO_K = 16
LINK_GBPS = 100.0
DT_S = 5e-5
BYTES_PER_NEIGHBOR = 256 * 1024 * 1024   # 256 MiB (matches the static experiment)
RING_SIZE = 16                            # smallest size where multi-flow matters
SWEEP_K = [1, 2, 4, 8]
AFFECTED_FRACTION = 0.3
DEFAULT_SEEDS = 100

# Per-model congestion parameters. Each model targets the layer that makes its
# point: bypassable layers (agg_core/edge_agg) for the regimes multi-flow should
# help, and the single-path host_edge for incast (the topological limit).
MODELS: Dict[str, dict] = {
    "onoff": dict(
        mode="onoff", target_layers=["agg_core", "edge_agg"],
        congested_util_low=0.50, congested_util_high=0.95,
        normal_util_low=0.0, normal_util_high=0.05, p_on=0.01, p_off=0.005,
    ),
    "iid": dict(
        mode="iid", target_layers=["agg_core", "edge_agg"],
        congested_util_low=0.50, congested_util_high=0.95,
        normal_util_low=0.0, normal_util_high=0.05,
    ),
    "hot_spot": dict(
        mode="hot_spot", target_layers=["agg_core", "edge_agg"],
        congested_util_low=0.50, congested_util_high=0.95,
    ),
    "incast": dict(
        mode="incast", target_layers=["host_edge"],
        incast_util_low=0.85, incast_util_high=0.98,
    ),
    "microburst": dict(
        mode="microburst", target_layers=["agg_core", "edge_agg"],
        burst_prob=0.001, burst_ticks=2, burst_util_low=0.80, burst_util_high=0.98,
        normal_util_low=0.0, normal_util_high=0.05,
    ),
}

TODAY = date.today().isoformat()
OUT_DIR = Path(f"{_RING_ROOT}/results/v6.1_congestion_models_{TODAY}")


def make_congestion(model: str, seed: int) -> CongestionModel:
    return CongestionModel(seed=seed, affected_fraction=AFFECTED_FRACTION, **MODELS[model])


def run_sweep(n_seeds: int) -> List[Dict[str, Any]]:
    # Topology is deterministic for a given k (the seed only drives congestion),
    # so build it once.
    topo = FatTree(k=TOPO_K, link_capacity_Gbps=LINK_GBPS)
    ring = build_worker_ring(topo.hosts, worker_count=RING_SIZE, start_index=0)

    rows: List[Dict[str, Any]] = []
    total = len(MODELS) * n_seeds * len(SWEEP_K)
    count = 0
    for model in MODELS:
        for seed in range(n_seeds):
            # Same congestion seed for every k at this (model, seed) so the k=1 and
            # k>1 runs see the SAME congestion realization -> valid per-seed pairing.
            cong_seed = 1000 + seed
            for k in SWEEP_K:
                count += 1
                cong = make_congestion(model, cong_seed)
                t = run_simple_ring_transfer(
                    topo=topo, ring=ring, bytes_per_neighbor=BYTES_PER_NEIGHBOR,
                    flows_per_neighbor=k, dt_s=DT_S, congestion=cong,
                )
                rows.append({"model": model, "seed": seed, "k": k, "completion_time_s": t})
            if (seed + 1) % max(1, n_seeds // 10) == 0:
                print(f"  [{count}/{total}] {model} seed {seed+1}/{n_seeds}")
    return rows


# ─── Analysis: per-seed-paired speedup + bootstrap 95% CI ─────
def _bootstrap_ci(values, n_boot=2000, ci=0.95, seed=42):
    v = np.asarray(values, dtype=float)
    v = v[~np.isnan(v)]
    if len(v) == 0:
        return float("nan"), float("nan"), float("nan")
    if len(v) == 1:
        return float(v[0]), float(v[0]), float(v[0])
    rng = np.random.default_rng(seed)
    means = np.array([rng.choice(v, size=len(v), replace=True).mean() for _ in range(n_boot)])
    lo = float(np.percentile(means, (1 - ci) / 2 * 100))
    hi = float(np.percentile(means, (1 + ci) / 2 * 100))
    return float(v.mean()), lo, hi


def analyze(rows) -> List[Dict[str, Any]]:
    # index time by (model, seed, k)
    T: Dict = {}
    for r in rows:
        T[(r["model"], r["seed"], r["k"])] = r["completion_time_s"]
    seeds = sorted(set(r["seed"] for r in rows))

    summary = []
    for model in MODELS:
        for k in SWEEP_K:
            # per-seed speedup = T(k=1, seed) / T(k, seed)
            sp = []
            for s in seeds:
                t1 = T.get((model, s, 1))
                tk = T.get((model, s, k))
                if t1 and tk and tk > 0:
                    sp.append(t1 / tk)
            mean_sp, lo, hi = _bootstrap_ci(sp)
            summary.append({
                "model": model, "k": k, "n_seeds": len(sp),
                "speedup_mean": mean_sp, "speedup_ci_low": lo, "speedup_ci_high": hi,
                "speedup_min": min(sp) if sp else float("nan"),
                "speedup_max": max(sp) if sp else float("nan"),
            })
    return summary


def save_csv(rows, path, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"CSV saved: {path}")


def plot_speedup(summary, path):
    fig, ax = plt.subplots(figsize=(10, 6))
    colors = plt.cm.tab10(np.linspace(0, 0.9, len(MODELS)))
    for mi, model in enumerate(MODELS):
        ks = [s["k"] for s in summary if s["model"] == model]
        mean = [s["speedup_mean"] for s in summary if s["model"] == model]
        lo = [s["speedup_ci_low"] for s in summary if s["model"] == model]
        hi = [s["speedup_ci_high"] for s in summary if s["model"] == model]
        ax.plot(ks, mean, marker="o", color=colors[mi], label=model)
        ax.fill_between(ks, lo, hi, color=colors[mi], alpha=0.15)
    ax.axhline(1.0, color="grey", ls="--", lw=1)
    ax.set_xlabel("Flows per neighbor (k)")
    ax.set_ylabel("Speedup vs k=1 (per-seed paired, 95% CI band)")
    n_seeds = max((s["n_seeds"] for s in summary), default=0)
    ax.set_title(f"Multi-flow benefit by congestion model (P={RING_SIZE}, n={n_seeds} seeds)")
    ax.set_xticks(SWEEP_K)
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    print(f"Plot saved: {path}")


def print_summary(summary):
    print("\n" + "=" * 72)
    print(f"{'model':<11} {'k':>2} {'n':>4} {'speedup':>9} {'95% CI':>16} {'min..max':>14}")
    print("-" * 72)
    for s in summary:
        print(f"{s['model']:<11} {s['k']:>2} {s['n_seeds']:>4} "
              f"{s['speedup_mean']:>8.2f}x [{s['speedup_ci_low']:.2f},{s['speedup_ci_high']:.2f}]"
              f"   {s['speedup_min']:.2f}..{s['speedup_max']:.2f}")


def main():
    n_seeds = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SEEDS
    print(f"D.6 congestion-models sweep: {list(MODELS)} × k={SWEEP_K} × {n_seeds} seeds "
          f"(P={RING_SIZE}, M={BYTES_PER_NEIGHBOR // (1024*1024)} MiB)\n")
    rows = run_sweep(n_seeds)
    save_csv(rows, OUT_DIR / "results.csv",
             ["model", "seed", "k", "completion_time_s"])
    summary = analyze(rows)
    save_csv(summary, OUT_DIR / "summary.csv",
             ["model", "k", "n_seeds", "speedup_mean", "speedup_ci_low",
              "speedup_ci_high", "speedup_min", "speedup_max"])
    plot_speedup(summary, OUT_DIR / "speedup_by_model.png")
    print_summary(summary)


if __name__ == "__main__":
    main()
