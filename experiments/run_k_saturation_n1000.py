"""
R1 (2026-08-04) — PRODUCTION re-run of the C.3.7 k-saturation sweep at n=1000.

Identical methodology, constants and code path to run_k_saturation.py (v10.0);
the ONLY differences are the default seed count (1000) and the output version
directory. v10.0 stays frozen and untouched.

Because the ring for seed s is built from random.Random(SEED_BASE + s) inside the
worker, seeds 0..99 of this run reproduce v10.0 exactly -- verify_v101.py checks
that bit-for-bit before any number from here is used.

Motivation: Tables I/II and the k* rule (now headlined in the abstract) are the
last core results still on n=100.

Usage:  python experiments/run_k_saturation_n1000.py [n_seeds] [n_workers]
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

from sim import FatTree, compute_ring_theoretical_time, run_simple_ring_transfer

K_TOPO = 16
BYTES = 64 * 1024 * 1024
DT = 5e-5
SWEEP_K = [1, 2, 4, 8, 16, 32]
P_LIST = [16, 64]
SEED_BASE = 9000          # identical to v10.0 -> seeds 0..99 must reproduce it
FABRICS = {
    "3tier_nb":  (3, 1.0),
    "3tier_os2": (3, 2.0),
    "3tier_os4": (3, 4.0),
    "2tier":     (2, 1.0),
}
OUT_DIR = _RING_ROOT / "results" / "v10.1_k_saturation_n1000"

_TOPOS = {}
_TOP_LINKS = {}


def _init():
    global _TOPOS, _TOP_LINKS
    for name, (nt, osub) in FABRICS.items():
        t = FatTree(K_TOPO, n_tiers=nt, oversub=osub)
        _TOPOS[name] = t
        layers = t.get_edges_by_layer()
        top = layers["agg_core"] if nt == 3 else layers["leaf_spine"]
        _TOP_LINKS[name] = set(top)


def _work(seed):
    rows = []
    for P in P_LIST:
        ring3 = random.Random(SEED_BASE + seed).sample(_TOPOS["3tier_nb"].hosts, P)
        ring2 = random.Random(SEED_BASE + seed).sample(_TOPOS["2tier"].hosts, P)
        for fname, topo in _TOPOS.items():
            ring = ring2 if fname == "2tier" else ring3
            toplinks = _TOP_LINKS[fname]
            for k in SWEEP_K:
                t = run_simple_ring_transfer(topo=topo, ring=ring, bytes_per_neighbor=BYTES,
                                             flows_per_neighbor=k, dt_s=DT, congestion=None)
                th = compute_ring_theoretical_time(topo, ring, BYTES, flows_per_neighbor=k)
                cont = th["edge_contention"]
                used = sum(1 for e in toplinks if cont.get(e, 0) > 0)
                maxc = max((cont.get(e, 0) for e in toplinks), default=0)
                opt = th["theoretical_time_s"]
                gap = (t / opt - 1.0) if opt else float("nan")
                rows.append({"fabric": fname, "P": P, "seed": seed, "k": k,
                             "t_sim": t, "opt_time": opt, "equal_split_gap": gap,
                             "Bstar_Bps": th["bottleneck_bandwidth_Bps"],
                             "top_used": used, "max_top_contention": maxc})
    return rows


def boot_ci(vals, n_boot=5000, ci=0.95, seed=42):
    v = np.asarray([x for x in vals if x == x], float)
    if len(v) < 2:
        return (float(v[0]) if len(v) else float("nan"),) * 3
    rng = np.random.default_rng(seed)
    m = np.array([rng.choice(v, len(v), replace=True).mean() for _ in range(n_boot)])
    return float(v.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
    n = int(_sys.argv[1]) if len(_sys.argv) > 1 else 1000
    nw = int(_sys.argv[2]) if len(_sys.argv) > 2 else min(20, os.cpu_count() or 4)
    seeds = list(range(n))
    print(f"R1 k-saturation n={n}: {list(FABRICS)} x k{SWEEP_K} x P{P_LIST}, {nw} workers\n", flush=True)

    rows = []
    with mp.Pool(processes=nw, initializer=_init) as pool:
        for i, res in enumerate(pool.imap_unordered(_work, seeds), 1):
            rows.extend(res)
            if i % max(1, n // 20) == 0 or i == n:
                print(f"  [{i}/{n}] seeds done", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda r: (r["fabric"], r["P"], r["seed"], r["k"]))
    with open(OUT_DIR / "results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    T = {(r["fabric"], r["P"], r["seed"], r["k"]): r for r in rows}
    seeds_set = sorted(set(r["seed"] for r in rows))
    beats = sum(1 for r in rows if r["opt_time"] and r["t_sim"] < 0.99 * r["opt_time"])
    k1gap = max((abs(r["equal_split_gap"]) for r in rows
                 if r["k"] == 1 and r["equal_split_gap"] == r["equal_split_gap"]), default=0.0)

    summ = []
    for P in P_LIST:
        for fname in FABRICS:
            for k in SWEEP_K:
                sp = []
                for s in seeds_set:
                    a = T.get((fname, P, s, 1)); b = T.get((fname, P, s, k))
                    if a and b and b["t_sim"] > 0:
                        sp.append(a["t_sim"] / b["t_sim"])
                m, lo, hi = boot_ci(sp)
                cells = [T[(fname, P, s, k)] for s in seeds_set if (fname, P, s, k) in T]
                summ.append({
                    "fabric": fname, "P": P, "k": k, "n": len(sp),
                    "speedup_mean": m, "ci_low": lo, "ci_high": hi,
                    "speedup_min": min(sp) if sp else float("nan"),
                    "speedup_max": max(sp) if sp else float("nan"),
                    "mean_max_top_contention": mean(c["max_top_contention"] for c in cells),
                    "mean_top_used": mean(c["top_used"] for c in cells),
                    "mean_equal_split_gap": mean(c["equal_split_gap"] for c in cells),
                    "mean_opt_speedup": mean(
                        T[(fname, P, s, 1)]["t_sim"] / T[(fname, P, s, k)]["opt_time"]
                        for s in seeds_set
                        if (fname, P, s, k) in T and T[(fname, P, s, k)]["opt_time"] > 0),
                })
    with open(OUT_DIR / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summ[0].keys()))
        w.writeheader(); w.writerows(summ)

    print(f"\nGUARD sim never beats optimal-split bound: {beats} violation(s) (want 0)")
    print(f"GUARD k=1 equal==optimal: max gap {k1gap*100:.2f}% (want <1%)")
    for P in P_LIST:
        print(f"\n=== P={P} : speed-up vs k (per-seed paired, 95% CI) ===")
        for fname in FABRICS:
            cells = {s["k"]: s for s in summ if s["fabric"] == fname and s["P"] == P}
            line = f"{fname:<11} "
            for k in SWEEP_K:
                c = cells[k]
                line += f"k{k}:{c['speedup_mean']:.2f}[{c['ci_low']:.2f},{c['ci_high']:.2f}] "
            print(line)
    print(f"\nCSV + summary in {OUT_DIR}/")


if __name__ == "__main__":
    main()
