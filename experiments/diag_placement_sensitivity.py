"""
DIAGNOSTIC (not a frozen vX.Y result set) - placement sensitivity.

Question
--------
v6.1 (Fig 1, congestion regimes) and v5.1 (Fig 5 + the 2.47x headline) build the
ring with build_worker_ring(hosts, P, start_index=0), i.e. hosts[0..P-1]. Because
FatTree lists hosts pod-major, that ring lies entirely inside pod 0: at P=64,
56/64 ring edges are intra-rack (m=1 path) and NONE of the ring's paths traverse
an agg-core link. The topology / k / split studies (v9-v12) instead place workers
uniformly at random, where most edges are cross-pod (m=64).

So: does the placement change the conclusions?

This script varies ONLY the ring construction, holding topology, congestion
model, parameters, message size, dt and seeds fixed.

  Part A - Fig 1 config: P=16, affected_fraction=0.3, all four regimes, k in {1,2,4,8}
  Part B - headline cell: P=64, affected_fraction=0.5, onoff, k in {1,2,4,8}

Speed-up is per-seed paired: T(k=1) / T(k) within the same placement+model+seed.

Usage:  python experiments/diag_placement_sensitivity.py [n_seeds] [workers]
Output: results/diag_placement_2026-07-21/{partA.csv, partB.csv}
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _BootPath
_RING_ROOT = _BootPath(__file__).resolve().parents[1]
if str(_RING_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_RING_ROOT))

import csv
import multiprocessing as mp
import os
import random

import numpy as np

from sim import FatTree, CongestionModel, build_worker_ring, run_simple_ring_transfer

TOPO_K = 16
LINK_GBPS = 100.0
DT_S = 5e-5
BYTES = 256 * 1024 * 1024          # 256 MiB - matches v6.1 and v5.1
SWEEP_K = [1, 2, 4, 8]
SEED_BASE = 9000                   # same base the random-placement studies use

# Exactly the v6.1 model definitions.
MODELS = {
    "onoff": dict(mode="onoff", target_layers=["agg_core", "edge_agg"],
                  congested_util_low=0.50, congested_util_high=0.95,
                  normal_util_low=0.0, normal_util_high=0.05, p_on=0.01, p_off=0.005),
    "iid": dict(mode="iid", target_layers=["agg_core", "edge_agg"],
                congested_util_low=0.50, congested_util_high=0.95,
                normal_util_low=0.0, normal_util_high=0.05),
    "hot_spot": dict(mode="hot_spot", target_layers=["agg_core", "edge_agg"],
                     congested_util_low=0.50, congested_util_high=0.95),
    "microburst": dict(mode="microburst", target_layers=["agg_core", "edge_agg"],
                       burst_prob=0.001, burst_ticks=2,
                       burst_util_low=0.80, burst_util_high=0.98,
                       normal_util_low=0.0, normal_util_high=0.05),
}

OUT_DIR = _BootPath(f"{_RING_ROOT}/results/diag_placement_2026-07-21")
_TOPO = None


def _init():
    global _TOPO
    _TOPO = FatTree(k=TOPO_K, link_capacity_Gbps=LINK_GBPS)


def make_ring(placement: str, P: int, seed: int):
    if placement == "contiguous":                       # what v6.1 / v5.1 do
        return build_worker_ring(_TOPO.hosts, worker_count=P, start_index=0)
    return random.Random(SEED_BASE + seed).sample(_TOPO.hosts, P)   # what v9-v12 do


def _work(task):
    placement, model, P, af, k, seed = task
    ring = make_ring(placement, P, seed)
    cong = CongestionModel(seed=seed, affected_fraction=af, **MODELS[model])
    t = run_simple_ring_transfer(topo=_TOPO, ring=ring, bytes_per_neighbor=BYTES,
                                 flows_per_neighbor=k, dt_s=DT_S, congestion=cong)
    return {"placement": placement, "model": model, "P": P, "af": af,
            "k": k, "seed": seed, "t": t}


def boot_ci(vals, n_boot=5000, seed=42):
    v = np.asarray([x for x in vals if x == x], float)
    if len(v) < 2:
        return (float(v[0]) if len(v) else float("nan"),) * 3
    rng = np.random.default_rng(seed)
    m = np.array([rng.choice(v, len(v), replace=True).mean() for _ in range(n_boot)])
    return float(v.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def run(tasks, nw, label):
    print(f"\n[{label}] {len(tasks):,} runs on {nw} workers", flush=True)
    rows = []
    with mp.Pool(nw, initializer=_init) as pool:
        for i, r in enumerate(pool.imap_unordered(_work, tasks, chunksize=8), 1):
            rows.append(r)
            if i % max(1, len(tasks) // 10) == 0:
                print(f"  [{label}] {i:,}/{len(tasks):,}", flush=True)
    return rows


def summarize(rows, group_models):
    T = {(r["placement"], r["model"], r["k"], r["seed"]): r["t"] for r in rows}
    seeds = sorted({r["seed"] for r in rows})
    out = []
    for placement in ("contiguous", "random"):
        for model in group_models:
            for k in SWEEP_K:
                sp = [T[(placement, model, 1, s)] / T[(placement, model, k, s)]
                      for s in seeds
                      if (placement, model, 1, s) in T and (placement, model, k, s) in T
                      and T[(placement, model, k, s)] > 0]
                if not sp:
                    continue
                m, lo, hi = boot_ci(sp)
                out.append({"placement": placement, "model": model, "k": k,
                            "n": len(sp), "speedup": m, "ci_low": lo, "ci_high": hi})
    return out


def report(summ, title, models):
    print(f"\n=== {title} ===")
    print(f"{'model':<12} {'k':>3} | {'contiguous (v6.1/v5.1 style)':>30} | {'random (v9-v12 style)':>26}")
    print("-" * 80)
    for model in models:
        for k in SWEEP_K:
            c = next((s for s in summ if s["placement"] == "contiguous" and s["model"] == model and s["k"] == k), None)
            r = next((s for s in summ if s["placement"] == "random" and s["model"] == model and s["k"] == k), None)
            if not c or not r:
                continue
            print(f"{model:<12} {k:>3} | {c['speedup']:>8.3f} [{c['ci_low']:.3f},{c['ci_high']:.3f}]"
                  f"      | {r['speedup']:>8.3f} [{r['ci_low']:.3f},{r['ci_high']:.3f}]")


def main():
    n = int(_sys.argv[1]) if len(_sys.argv) > 1 else 100
    nw = int(_sys.argv[2]) if len(_sys.argv) > 2 else max(1, (os.cpu_count() or 4) - 2)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Part A - the Fig 1 configuration
    tasksA = [(p, m, 16, 0.3, k, s)
              for p in ("contiguous", "random") for m in MODELS
              for k in SWEEP_K for s in range(n)]
    rowsA = run(tasksA, nw, "A P=16 af=0.3")
    summA = summarize(rowsA, list(MODELS))
    with open(OUT_DIR / "partA.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summA[0].keys())); w.writeheader(); w.writerows(summA)
    report(summA, "PART A - Fig 1 config (P=16, af=0.3)", list(MODELS))

    # Part B - the 2.47x headline cell
    tasksB = [(p, "onoff", 64, 0.5, k, s)
              for p in ("contiguous", "random") for k in SWEEP_K for s in range(n)]
    rowsB = run(tasksB, nw, "B P=64 af=0.5")
    summB = summarize(rowsB, ["onoff"])
    with open(OUT_DIR / "partB.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summB[0].keys())); w.writeheader(); w.writerows(summB)
    report(summB, "PART B - headline cell (P=64, af=0.5, onoff)", ["onoff"])

    print(f"\nCSVs in {OUT_DIR}/")


if __name__ == "__main__":
    main()
