"""
The last mixed-n block in the controller dataset: the P=16 static curves.

v5.7_controller_n1000 made every P=64 series n=1000; the P=16 static rows were still
the n=100 rows carried from v5.3. They are not plotted or quoted today, but leaving an
n=100 block inside a file whose every other row is n=1000 is exactly the trap the
2026-08-04 audit was created to remove.

Identical to run_static_af_n1000.py in every constant, congestion parameter, seed
derivation and placement rule; only P and the af list differ (P=16 needs all four af
values, since none of them exists at n=1000).

Usage:  python experiments/run_static_af_p16_n1000.py [n=1000] [workers]
Output: results/v5.8_static_af_p16_n1000/{results.csv, summary.csv}
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
BYTES = 256 * 1024 * 1024
P = 16
AF_LIST = [0.0, 0.1, 0.3, 0.5]
SWEEP_K = [1, 2, 4, 8]
SEED_BASE = 9000
BASE_SEED = 0xBEEF

CONG_PARAMS = dict(
    congested_util_low=0.50, congested_util_high=0.95,
    normal_util_low=0.00, normal_util_high=0.05,
    p_on=0.01, p_off=0.005,
    target_layers=["agg_core", "edge_agg"],
)

OUT_DIR = _RING_ROOT / "results" / "v5.8_static_af_p16_n1000"
_TOPO = None


def _init():
    global _TOPO
    _TOPO = FatTree(k=TOPO_K, link_capacity_Gbps=LINK_GBPS)


def _work(args):
    run_idx, k, af = args
    seed = BASE_SEED + run_idx * 10_000_001
    ring = random.Random(SEED_BASE + run_idx).sample(_TOPO.hosts, P)
    cong = CongestionModel(mode="onoff", seed=seed + int(af * 1000),
                           affected_fraction=af, **CONG_PARAMS)
    t = run_simple_ring_transfer(topo=_TOPO, ring=ring, bytes_per_neighbor=BYTES,
                                 flows_per_neighbor=k, dt_s=DT_S, congestion=cong)
    return {"run": run_idx, "k": k, "affected_fraction": af, "completion_time_s": t}


def boot_ci(vals, n_boot=5000, seed=42):
    v = np.asarray(vals, float)
    rng = np.random.default_rng(seed)
    m = np.array([rng.choice(v, len(v), replace=True).mean() for _ in range(n_boot)])
    return float(v.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
    n = int(_sys.argv[1]) if len(_sys.argv) > 1 else 1000
    nw = int(_sys.argv[2]) if len(_sys.argv) > 2 else max(1, (os.cpu_count() or 4) - 4)
    tasks = [(r, k, af) for af in AF_LIST for r in range(n) for k in SWEEP_K]
    print(f"static af-sweep P={P} af={AF_LIST} k={SWEEP_K} n={n} on {nw} workers "
          f"({len(tasks):,} runs)", flush=True)

    rows = []
    with mp.Pool(nw, initializer=_init) as pool:
        for i, r in enumerate(pool.imap_unordered(_work, tasks, chunksize=8), 1):
            rows.append(r)
            if i % max(1, len(tasks) // 20) == 0:
                print(f"  [{i:,}/{len(tasks):,}]", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda r: (r["affected_fraction"], r["run"], r["k"]))
    with open(OUT_DIR / "results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["run", "k", "affected_fraction", "completion_time_s"])
        w.writeheader(); w.writerows(rows)

    T = {(r["affected_fraction"], r["run"], r["k"]): r["completion_time_s"] for r in rows}
    summ = []
    for af in AF_LIST:
        runs = sorted({r["run"] for r in rows if r["affected_fraction"] == af})
        for k in SWEEP_K:
            sp = [T[(af, r, 1)] / T[(af, r, k)] for r in runs if T.get((af, r, k))]
            m, lo, hi = boot_ci(sp)
            summ.append({"ring_size": P, "k": k, "affected_fraction": af, "n_seeds": len(sp),
                         "speedup": m, "speedup_ci_low": lo, "speedup_ci_high": hi,
                         "total_qps": k * P})
            print(f"  af={af} k={k}: {m:.3f} [{lo:.3f},{hi:.3f}]  (n={len(sp)})", flush=True)
    with open(OUT_DIR / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summ[0].keys()))
        w.writeheader(); w.writerows(summ)
    print(f"\nCSVs in {OUT_DIR}/")


if __name__ == "__main__":
    main()
