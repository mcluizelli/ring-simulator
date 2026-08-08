"""
Background-traffic sensitivity, re-run to production standards (2026-08-04).

Replaces results/v3.0_allreduce_2026-04-13/background/, which is the source of the
paper's sentence "changes ring completion time by under 1% up to 500 flows/s and by
about 2% at 1000 flows/s". That run has THREE defects, all verified in
experiment_allreduce_background.py:
  1. NUM_RUNS = 3            -- three seeds, in a paper whose every other number is n=1000;
  2. build_worker_ring(..., start_index=0)  -- the pod-local ring of tracker A.5, so no
     ring edge ever crossed pods and background traffic had far less room to interfere;
  3. seed = int(time.time_ns())             -- wall-clock seeds, so it is not reproducible.

This run keeps the experiment identical in every physical parameter (P=16, 256 MiB,
pipelined AllReduce with window 4, lognormal 50 MiB flows, mixed locality p_local=0.5,
rates {0,200,500,1000} fps, k in {1,4}) and fixes only those three things: random
placement per seed from SEED_BASE, deterministic seed derivation, and n from the CLI.

Per-seed PAIRED against the same seed's 0-fps run, bootstrap 95% CI (5000, rng 42).

Usage:  python experiments/run_background_n1000.py [n=1000] [workers]
Output: results/v13.0_background_n1000/{results.csv, summary.csv}
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

from sim import FatTree, BackgroundTrafficConfig, run_ring_allreduce

TOPO_K = 16
LINK_GBPS = 100.0
DT_S = 5e-5
RING_SIZE = 16
MSG_BYTES = 256 * 1024 * 1024
PIPELINE_WINDOW = 4
SWEEP_K = [1, 4]
RATES = [0, 200, 500, 1000]
SEED_BASE = 9000                 # project-wide placement base
BASE_SEED = 0xBEEF               # same derivation as the v5.4/v5.6 production runs

OUT_DIR = _RING_ROOT / "results" / "v13.0_background_n1000"
_TOPO = None


def _init():
    global _TOPO
    _TOPO = FatTree(k=TOPO_K, link_capacity_Gbps=LINK_GBPS)


def _bg(rate, seed):
    if rate <= 0:
        return None
    return BackgroundTrafficConfig(
        seed=seed, arrival_rate_fps=rate, size_dist="lognormal",
        mean_bytes=50 * 1024 * 1024, sigma_logn=1.0,
        locality="mixed", p_local=0.5,
    )


def _work(args):
    run_idx, k, rate = args
    seed = BASE_SEED + run_idx * 10_000_001
    ring = random.Random(SEED_BASE + run_idx).sample(_TOPO.hosts, RING_SIZE)   # FIXED
    ar = run_ring_allreduce(topo=_TOPO, ring=ring, total_bytes_M=MSG_BYTES,
                            flows_per_neighbor=k, dt_s=DT_S, pipelined=True,
                            pipeline_window=PIPELINE_WINDOW, alpha_s=0.0,
                            background_cfg=_bg(rate, seed + rate))
    st = np.asarray(ar.step_times_s, float)
    return {"run": run_idx, "k": k, "arrival_rate_fps": rate,
            "allreduce_time_s": ar.total_time_s,
            "mean_step_s": float(st.mean()), "p99_step_s": float(np.percentile(st, 99)),
            "max_step_s": float(st.max())}


def boot_ci(vals, n_boot=5000, seed=42):
    v = np.asarray(vals, float)
    if len(v) < 2:
        return (float(v[0]) if len(v) else float("nan"),) * 3
    rng = np.random.default_rng(seed)
    m = np.array([rng.choice(v, len(v), replace=True).mean() for _ in range(n_boot)])
    return float(v.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
    n = int(_sys.argv[1]) if len(_sys.argv) > 1 else 1000
    nw = int(_sys.argv[2]) if len(_sys.argv) > 2 else max(1, (os.cpu_count() or 4) - 4)
    tasks = [(r, k, rate) for r in range(n) for k in SWEEP_K for rate in RATES]
    print(f"background sweep P={RING_SIZE} k={SWEEP_K} rates={RATES} n={n} "
          f"on {nw} workers ({len(tasks):,} runs)", flush=True)

    rows = []
    with mp.Pool(nw, initializer=_init) as pool:
        for i, r in enumerate(pool.imap_unordered(_work, tasks, chunksize=4), 1):
            rows.append(r)
            if i % max(1, len(tasks) // 20) == 0:
                print(f"  [{i:,}/{len(tasks):,}]", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda r: (r["k"], r["arrival_rate_fps"], r["run"]))
    with open(OUT_DIR / "results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    T = {(r["k"], r["arrival_rate_fps"], r["run"]): r for r in rows}
    runs = sorted({r["run"] for r in rows})
    summ = []
    print("\n=== paired change in AllReduce completion time vs the same seed at 0 fps ===")
    for k in SWEEP_K:
        for rate in RATES:
            if rate == 0:
                continue
            d = [(T[(k, rate, r)]["allreduce_time_s"] / T[(k, 0, r)]["allreduce_time_s"] - 1) * 100
                 for r in runs if (k, rate, r) in T and (k, 0, r) in T]
            m, lo, hi = boot_ci(d)
            p99 = [(T[(k, rate, r)]["p99_step_s"] / T[(k, 0, r)]["p99_step_s"] - 1) * 100
                   for r in runs if (k, rate, r) in T and (k, 0, r) in T]
            pm, plo, phi = boot_ci(p99)
            summ.append({"ring_size": RING_SIZE, "k": k, "arrival_rate_fps": rate,
                         "n_seeds": len(d), "pct_change_mean": m,
                         "pct_change_ci_low": lo, "pct_change_ci_high": hi,
                         "pct_change_max": max(d) if d else float("nan"),
                         "p99_pct_change_mean": pm,
                         "p99_ci_low": plo, "p99_ci_high": phi})
            print(f"  k={k} {rate:>4} fps: {m:+6.2f}% [{lo:+.2f},{hi:+.2f}]  "
                  f"max {max(d):+6.2f}%  | p99 step {pm:+6.2f}% [{plo:+.2f},{phi:+.2f}]  (n={len(d)})")
    with open(OUT_DIR / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summ[0].keys()))
        w.writeheader(); w.writerows(summ)
    print(f"\nCSVs in {OUT_DIR}/")


if __name__ == "__main__":
    main()
