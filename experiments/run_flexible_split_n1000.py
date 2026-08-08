"""
R2 (2026-08-04) — PRODUCTION re-run of the C.3.8 flexible-split study at n=1000.

Identical methodology, constants and code path to run_flexible_split.py (v11.0);
the ONLY differences are the default seed count (1000), the equal-split baseline
(the n=1000 sweep v10.1) and the output version directory. v11.0 stays frozen.

Pairing is exact by construction: both this run and v10.1 build the ring for seed
s from random.Random(SEED_BASE + s), so T_equal and T_prop come from the same
placement. Motivation: the paper's "never loses in any of 4,000 paired
configurations" claim and the gap-closure figure are still on n=100; at n=1000
the same claim covers ~40,000 configurations.

Usage:  python experiments/run_flexible_split_n1000.py [n_seeds] [n_workers]
"""
from __future__ import annotations

# --- bootstrap ---
import sys as _sys
from pathlib import Path as _BootPath
_RING_ROOT = _BootPath(__file__).resolve().parents[1]
if str(_RING_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_RING_ROOT))
# -----------------

import csv
import multiprocessing as mp
import os
import random
from statistics import mean

import numpy as np

from sim import FatTree, run_ring_transfer_proportional

K_TOPO = 16
BYTES = 64 * 1024 * 1024
DT = 5e-5
SWEEP_K = [2, 4, 8, 16]          # k=1 is an identity (validated); k=32 equal comes from v10.1
P_LIST = [16, 64]
SEED_BASE = 9000                 # MUST match run_k_saturation_n1000.py for pairing
FABRICS = {
    "3tier_nb":  (3, 1.0),
    "3tier_os2": (3, 2.0),
    "3tier_os4": (3, 4.0),
    "2tier":     (2, 1.0),
}
EQUAL_DIR = _RING_ROOT / "results" / "v10.1_k_saturation_n1000"
OUT_DIR = _RING_ROOT / "results" / "v11.1_flexible_split_n1000"

_TOPOS = {}


def _init():
    global _TOPOS
    for name, (nt, osub) in FABRICS.items():
        _TOPOS[name] = FatTree(K_TOPO, n_tiers=nt, oversub=osub)


def _work(seed):
    rows = []
    for P in P_LIST:
        ring3 = random.Random(SEED_BASE + seed).sample(_TOPOS["3tier_nb"].hosts, P)
        ring2 = random.Random(SEED_BASE + seed).sample(_TOPOS["2tier"].hosts, P)
        for fname, topo in _TOPOS.items():
            ring = ring2 if fname == "2tier" else ring3
            for k in SWEEP_K:
                tp = run_ring_transfer_proportional(topo, ring, BYTES, k, dt_s=DT)
                rows.append({"fabric": fname, "P": P, "seed": seed, "k": k, "t_prop": tp})
    return rows


def boot_ci(vals, n_boot=5000, seed=42):
    v = np.asarray([x for x in vals if x == x], float)
    if len(v) < 2:
        return (float(v[0]) if len(v) else float("nan"),) * 3
    rng = np.random.default_rng(seed)
    m = np.array([rng.choice(v, len(v), replace=True).mean() for _ in range(n_boot)])
    return float(v.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
    n = int(_sys.argv[1]) if len(_sys.argv) > 1 else 1000
    nw = int(_sys.argv[2]) if len(_sys.argv) > 2 else min(20, os.cpu_count() or 4)
    if not (EQUAL_DIR / "results.csv").exists():
        _sys.exit(f"missing equal-split baseline {EQUAL_DIR}/results.csv "
                  f"(run run_k_saturation_n1000.py first)")

    print(f"R2 flexible split n={n}: {list(FABRICS)} x k{SWEEP_K} x P{P_LIST}, {nw} workers\n", flush=True)
    rows = []
    with mp.Pool(processes=nw, initializer=_init) as pool:
        for i, res in enumerate(pool.imap_unordered(_work, list(range(n))), 1):
            rows.extend(res)
            if i % max(1, n // 20) == 0 or i == n:
                print(f"  [{i}/{n}] seeds done", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda r: (r["fabric"], r["P"], r["seed"], r["k"]))
    with open(OUT_DIR / "results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    # join with the n=1000 equal-split baseline (identical placements by construction)
    EQ = {}
    for r in csv.DictReader(open(EQUAL_DIR / "results.csv")):
        EQ[(r["fabric"], int(r["P"]), int(r["seed"]), int(r["k"]))] = \
            (float(r["t_sim"]), float(r["opt_time"]))
    PR = {(r["fabric"], r["P"], r["seed"], r["k"]): r["t_prop"] for r in rows}
    seeds = sorted({r["seed"] for r in rows})

    summ, slower = [], 0
    for P in P_LIST:
        for fname in FABRICS:
            for k in SWEEP_K:
                ratios, gap_e, gap_p = [], [], []
                for s in seeds:
                    te, opt = EQ[(fname, P, s, k)]
                    tp = PR[(fname, P, s, k)]
                    ratios.append(te / tp)
                    if tp > te * 1.005:
                        slower += 1
                    if opt > 0:
                        gap_e.append(te / opt - 1)
                        gap_p.append(tp / opt - 1)
                m, lo, hi = boot_ci(ratios)
                summ.append({"fabric": fname, "P": P, "k": k, "n": len(ratios),
                             "prop_vs_equal_mean": m, "ci_low": lo, "ci_high": hi,
                             "prop_vs_equal_max": max(ratios),
                             "mean_gap_equal_pct": mean(gap_e) * 100,
                             "mean_gap_prop_pct": mean(gap_p) * 100})
    with open(OUT_DIR / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summ[0].keys()))
        w.writeheader(); w.writerows(summ)

    n_cfg = len(seeds) * len(P_LIST) * len(FABRICS) * len(SWEEP_K)
    print(f"\nGUARD prop never slower than equal (>+0.5%): {slower} violation(s) "
          f"of {n_cfg} paired configurations (want 0)")
    print("\n=== prop-vs-equal speed-up (paired, 95% CI) | gap-to-opt equal% -> prop% ===")
    for P in P_LIST:
        print(f"--- P={P} ---")
        for fname in FABRICS:
            cells = {c["k"]: c for c in summ if c["fabric"] == fname and c["P"] == P}
            line = f"{fname:<11} "
            for k in SWEEP_K:
                c = cells[k]
                line += (f"k{k}:{c['prop_vs_equal_mean']:.3f}[{c['ci_low']:.3f},{c['ci_high']:.3f}]"
                         f"({c['mean_gap_equal_pct']:.0f}%->{c['mean_gap_prop_pct']:.0f}%)  ")
            print(line)
    print("\n=== QP headline: T_prop(k=8) vs T_equal(k=32), paired ===")
    for P in P_LIST:
        for fname in FABRICS:
            r = [EQ[(fname, P, s, 32)][0] / PR[(fname, P, s, 8)] for s in seeds]
            m, lo, hi = boot_ci(r)
            verdict = "prop@k8 >= equal@k32" if lo >= 0.999 else (
                "equal@k32 wins" if hi < 1.0 else "statistical tie")
            print(f"  {fname:<11} P={P:<3} equal@k32/prop@k8 = {m:.3f} [{lo:.3f},{hi:.3f}]  -> {verdict}")

    # flagship (paper Fig. 3): prop@k=16 vs equal@k=32 on os4/P=64, paired
    fl = [EQ[("3tier_os4", 64, s, 32)][0] / PR[("3tier_os4", 64, s, 16)] for s in seeds]
    m, lo, hi = boot_ci(fl)
    print(f"\nFLAGSHIP os4/P=64  equal@k32 / prop@k16 = {m:.4f} [{lo:.4f},{hi:.4f}]  (n={len(fl)})")
    print(f"\nCSV + summary in {OUT_DIR}/")


if __name__ == "__main__":
    main()
