"""
Headline cell at production n, with the CORRECTED worker placement.

Replaces the v5.1 cell behind the paper's "2.47x under targeted congestion":
static multi-flow, P=64, on/off congestion at affected_fraction=0.5, k in {1,2,4,8},
n=1000, per-seed paired against k=1.

v5.1 built the ring with build_worker_ring(hosts, P, start_index=0), which lands
entirely inside pod 0 (56/64 edges have a single path; no ring path crosses an
agg-core link). This run uses the project convention that v9-v12 already follow:
random.Random(SEED_BASE + run).sample(hosts, P). See tracker A.5.

Usage:  python experiments/run_headline_n1000.py [n=1000] [workers]
Output: results/v5.4_headline_n1000_placementfix/{results.csv, summary.csv}
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

from sim import FatTree, CongestionModel, run_simple_ring_transfer

TOPO_K = 16
LINK_GBPS = 100.0
DT_S = 5e-5
BYTES = 256 * 1024 * 1024          # 256 MiB per neighbour, as in v5.1
P = 64
AF = 0.5                            # heaviest congestion setting
SWEEP_K = [1, 2, 4, 8]
SEED_BASE = 9000
BASE_SEED = 0xBEEF                  # v5.1's static base seed, kept for continuity

CONG_PARAMS = dict(
    congested_util_low=0.50, congested_util_high=0.95,
    normal_util_low=0.00, normal_util_high=0.05,
    p_on=0.01, p_off=0.005,
    target_layers=["agg_core", "edge_agg"],
)

OUT_DIR = _BootPath(f"{_RING_ROOT}/results/v5.4_headline_n1000_placementfix")
_TOPO = None


def _init():
    global _TOPO
    _TOPO = FatTree(k=TOPO_K, link_capacity_Gbps=LINK_GBPS)


def _work(args):
    run_idx, k = args
    seed = BASE_SEED + run_idx * 10_000_001
    ring = random.Random(SEED_BASE + run_idx).sample(_TOPO.hosts, P)   # FIXED placement
    cong = CongestionModel(mode="onoff", seed=seed + int(AF * 1000),
                           affected_fraction=AF, **CONG_PARAMS)
    t = run_simple_ring_transfer(topo=_TOPO, ring=ring, bytes_per_neighbor=BYTES,
                                 flows_per_neighbor=k, dt_s=DT_S, congestion=cong)
    return {"run": run_idx, "k": k, "completion_time_s": t}


def boot_ci(vals, n_boot=5000, seed=42):
    v = np.asarray(vals, float)
    rng = np.random.default_rng(seed)
    m = np.array([rng.choice(v, len(v), replace=True).mean() for _ in range(n_boot)])
    return float(v.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
    n = int(_sys.argv[1]) if len(_sys.argv) > 1 else 1000
    nw = int(_sys.argv[2]) if len(_sys.argv) > 2 else max(1, (os.cpu_count() or 4) - 2)
    tasks = [(r, k) for r in range(n) for k in SWEEP_K]
    print(f"headline cell P={P} af={AF} k={SWEEP_K} n={n} on {nw} workers "
          f"({len(tasks):,} runs)", flush=True)

    rows = []
    with mp.Pool(nw, initializer=_init) as pool:
        for i, r in enumerate(pool.imap_unordered(_work, tasks, chunksize=8), 1):
            rows.append(r)
            if i % max(1, len(tasks) // 20) == 0:
                print(f"  [{i:,}/{len(tasks):,}]", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["run", "k", "completion_time_s"])
        w.writeheader(); w.writerows(rows)

    T = {(r["run"], r["k"]): r["completion_time_s"] for r in rows}
    runs = sorted({r["run"] for r in rows})
    summ = []
    for k in SWEEP_K:
        sp = [T[(r, 1)] / T[(r, k)] for r in runs if T.get((r, k))]
        m, lo, hi = boot_ci(sp)
        summ.append({"ring_size": P, "k": k, "affected_fraction": AF, "n_seeds": len(sp),
                     "speedup": m, "speedup_ci_low": lo, "speedup_ci_high": hi,
                     "total_qps": k * P})
        print(f"  k={k}: {m:.3f} [{lo:.3f},{hi:.3f}]", flush=True)
    with open(OUT_DIR / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summ[0].keys()))
        w.writeheader(); w.writerows(summ)

    head = next(s for s in summ if s["k"] == 8)
    print(f"\nHEADLINE (P={P}, k=8, af={AF}, n={len(runs)}): "
          f"{head['speedup']:.3f} CI[{head['speedup_ci_low']:.3f},{head['speedup_ci_high']:.3f}]")
    print("v5.1 (pod-local ring, n=1000) reported 2.468 CI[2.440,2.495]")
    print(f"CSVs in {OUT_DIR}/")


if __name__ == "__main__":
    main()
