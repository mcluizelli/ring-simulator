"""
A.4 flagship re-run — os4 / P=64, equal vs proportional at n=1000 (production n).

Self-contained + self-paired: for each seed it runs BOTH arms on the SAME ring
placement —
  equal  = run_simple_ring_transfer         (== run_k_saturation.py, v10.0)
  prop   = run_ring_transfer_proportional   (== run_flexible_split_k32.py, v12.0)
so the +10.7% hero (equal@k=32 vs prop@k=16) gets a PAIRED bootstrap CI at n=1000.

Placement replicates the frozen runs exactly: random.Random(SEED_BASE+seed).sample(
FatTree(16,n_tiers=3,oversub=1.0).hosts, 64) -> the transfer runs on the oversub=4.0
fabric. Hence seeds 0..99 reproduce v10.0 (t_sim) and v12.0 (t_prop) bit-for-bit,
which the companion checker uses as a guard before we trust the n=1000 CI.

Usage:  python experiments/run_flagship_n1000.py [n=1000] [workers]
Output: results/v12.1_flagship_n1000_os4p64/{results.csv, flagship_ci.csv}
"""
from __future__ import annotations

# --- bootstrap: make ../sim.py importable ---
import sys as _sys
from pathlib import Path as _BootPath
_RING_ROOT = _BootPath(__file__).resolve().parents[1]
if str(_RING_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_RING_ROOT))
# --------------------------------------------

import csv
import multiprocessing as mp
import os
import random

import numpy as np

from sim import FatTree, run_simple_ring_transfer, run_ring_transfer_proportional

K_TOPO = 16
BYTES = 64 * 1024 * 1024          # 64 MiB / neighbour, == v10.0 / v12.0
DT = 5e-5
SWEEP_K = [1, 2, 4, 8, 16, 32]    # full sweep: k1 baseline for the Fig 3 curves; hero uses equal@32 / prop@16,8
P = 64
SEED_BASE = 9000                  # MUST match v10.0 / v12.0 for pairing
OUT_DIR = _BootPath("results/v12.1_flagship_n1000_os4p64")

_NB = None   # placement host set (oversub=1.0, == the frozen runs)
_OS4 = None  # transfer fabric (oversub=4.0)


def _init():
    global _NB, _OS4
    _NB = FatTree(K_TOPO, n_tiers=3, oversub=1.0)
    _OS4 = FatTree(K_TOPO, n_tiers=3, oversub=4.0)


def _work(seed):
    ring = random.Random(SEED_BASE + seed).sample(_NB.hosts, P)
    out = []
    for k in SWEEP_K:
        te = run_simple_ring_transfer(topo=_OS4, ring=ring, bytes_per_neighbor=BYTES,
                                      flows_per_neighbor=k, dt_s=DT, congestion=None)
        tp = run_ring_transfer_proportional(_OS4, ring, BYTES, k, dt_s=DT)
        out.append({"seed": seed, "k": k, "t_equal": te, "t_prop": tp})
    return out


def boot_ci(vals, n_boot=5000, seed=42):
    v = np.asarray([x for x in vals if x == x], float)
    if len(v) < 2:
        return (float(v[0]) if len(v) else float("nan"),) * 3
    rng = np.random.default_rng(seed)
    m = np.array([rng.choice(v, len(v), replace=True).mean() for _ in range(n_boot)])
    return float(v.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
    n = int(_sys.argv[1]) if len(_sys.argv) > 1 else 1000
    nw = int(_sys.argv[2]) if len(_sys.argv) > 2 else max(1, (os.cpu_count() or 4) - 2)
    print(f"A.4 flagship os4/P{P} equal+prop, k{SWEEP_K}, n={n}, {nw} workers", flush=True)

    rows = []
    with mp.Pool(nw, initializer=_init) as pool:
        for i, res in enumerate(pool.imap_unordered(_work, range(n)), 1):
            rows.extend(res)
            if i % max(1, n // 20) == 0 or i == n:
                print(f"  [{i}/{n}] seeds done", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["seed", "k", "t_equal", "t_prop"])
        w.writeheader(); w.writerows(rows)

    E = {(r["seed"], r["k"]): r["t_equal"] for r in rows}
    Pr = {(r["seed"], r["k"]): r["t_prop"] for r in rows}
    seeds = sorted({r["seed"] for r in rows})

    r16 = [E[(s, 32)] / Pr[(s, 16)] for s in seeds]     # hero: equal@32 vs prop@16
    r8 = [E[(s, 32)] / Pr[(s, 8)] for s in seeds]       # 'quarter': equal@32 vs prop@8
    m16, lo16, hi16 = boot_ci(r16)
    m8, lo8, hi8 = boot_ci(r8)
    rom16 = float(np.mean([E[(s, 32)] for s in seeds]) / np.mean([Pr[(s, 16)] for s in seeds]))
    rom8 = float(np.mean([E[(s, 32)] for s in seeds]) / np.mean([Pr[(s, 8)] for s in seeds]))

    ci_rows = [
        {"fabric": "3tier_os4", "P": P, "n": len(seeds), "metric": "equal@32 / prop@16",
         "mean_of_ratios": m16, "ci_low": lo16, "ci_high": hi16, "ratio_of_means": rom16},
        {"fabric": "3tier_os4", "P": P, "n": len(seeds), "metric": "equal@32 / prop@8",
         "mean_of_ratios": m8, "ci_low": lo8, "ci_high": hi8, "ratio_of_means": rom8},
    ]
    with open(OUT_DIR / "flagship_ci.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ci_rows[0].keys()))
        w.writeheader(); w.writerows(ci_rows)

    print(f"\nHERO equal@32 / prop@16 : mean-of-ratios={m16:.4f} CI[{lo16:.4f},{hi16:.4f}]"
          f"  ratio-of-means={rom16:.4f} (+{(rom16 - 1) * 100:.1f}%)")
    print(f"     equal@32 / prop@8  : mean-of-ratios={m8:.4f} CI[{lo8:.4f},{hi8:.4f}]"
          f"  ratio-of-means={rom8:.4f}")
    print(f"CSV + flagship_ci.csv in {OUT_DIR}/")


if __name__ == "__main__":
    main()
