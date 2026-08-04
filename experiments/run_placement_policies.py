"""
Worker-placement policy sweep (answers Jose's meeting comment M1).

The paper never states how the P workers are chosen. This measures how much the
policy matters, on the fabric where multi-flow has the most room (3-tier oversub
4:1) and at the headline setting (P=64, on/off congestion at af=0.5).

Policies
--------
  compact_pod : hosts[0..P-1]. At r=16 a pod holds exactly 64 hosts, so a P=64
                ring fills one pod. This is what the placement bug did (A.5):
                most ring edges are intra-rack (single path).
  random      : uniform draw over all hosts, the project convention (SEED_BASE=9000).
  spread      : 4 hosts from each of the 16 pods, interleaved round-robin so that
                consecutive ring members always sit in different pods -> every ring
                edge is cross-pod and sees the full (r/2)^2 = 64-path fan-out.

Reported per policy: the k=1 baseline time (absolute cost of the placement) and the
k=8 speed-up (how much room multi-flow has). The two move in OPPOSITE directions,
which is the point.

Usage:  python experiments/run_placement_policies.py [n=100] [workers]
Output: results/placement_policies_2026-07-28/{results.csv, summary.csv}
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
from collections import defaultdict

import numpy as np

from sim import FatTree, CongestionModel, run_simple_ring_transfer

TOPO_K = 16
LINK_GBPS = 100.0
DT = 5e-5
BYTES = 256 * 1024 * 1024
P = 64
AF = 0.5
SWEEP_K = [1, 8]
SEED_BASE = 9000
POLICIES = ["compact_pod", "random", "spread"]

CONG = dict(congested_util_low=0.50, congested_util_high=0.95,
            normal_util_low=0.00, normal_util_high=0.05,
            p_on=0.01, p_off=0.005, target_layers=["agg_core", "edge_agg"])

OUT = _BootPath(f"{_RING_ROOT}/results/placement_policies_2026-07-28")
_NB = _OS4 = None


def _init():
    global _NB, _OS4
    _NB = FatTree(TOPO_K, n_tiers=3, oversub=1.0)     # host list / placement reference
    _OS4 = FatTree(TOPO_K, n_tiers=3, oversub=4.0)    # the fabric under test


def make_ring(policy: str, seed: int):
    hosts = _NB.hosts
    if policy == "compact_pod":
        return hosts[:P]                               # one pod exactly, at r=16
    if policy == "random":
        return random.Random(SEED_BASE + seed).sample(hosts, P)
    if policy == "spread":
        by_pod = defaultdict(list)
        for h in hosts:
            by_pod[h.split("_")[0]].append(h)
        rng = random.Random(SEED_BASE + seed)
        pods = sorted(by_pod)
        per = P // len(pods)                           # 4 per pod for P=64, 16 pods
        picked = {p: rng.sample(by_pod[p], per) for p in pods}
        ring = []
        for i in range(per):                           # round-robin -> neighbours differ in pod
            for p in pods:
                ring.append(picked[p][i])
        return ring
    raise ValueError(policy)


def _work(args):
    policy, seed, k = args
    ring = make_ring(policy, seed)
    cong = CongestionModel(mode="onoff", seed=SEED_BASE + seed,
                           affected_fraction=AF, **CONG)
    t = run_simple_ring_transfer(topo=_OS4, ring=ring, bytes_per_neighbor=BYTES,
                                 flows_per_neighbor=k, dt_s=DT, congestion=cong)
    return {"policy": policy, "seed": seed, "k": k, "t": t}


def boot(v, nb=5000, s=42):
    v = np.asarray(v, float)
    rng = np.random.default_rng(s)
    m = np.array([rng.choice(v, len(v), replace=True).mean() for _ in range(nb)])
    return float(v.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def path_profile(policy):
    """How many equal-cost paths does each ring edge see, under this policy?"""
    _init()
    ring = make_ring(policy, 0)
    counts = [len(_NB.equal_cost_paths_hosts(ring[i], ring[(i + 1) % P])) for i in range(P)]
    from collections import Counter
    return dict(Counter(counts))


def main():
    n = int(_sys.argv[1]) if len(_sys.argv) > 1 else 100
    nw = int(_sys.argv[2]) if len(_sys.argv) > 2 else max(1, (os.cpu_count() or 4) - 2)
    tasks = [(p, s, k) for p in POLICIES for s in range(n) for k in SWEEP_K]
    print(f"placement policies {POLICIES} x k{SWEEP_K} x n={n} ({len(tasks):,} runs)", flush=True)

    rows = []
    with mp.Pool(nw, initializer=_init) as pool:
        for i, r in enumerate(pool.imap_unordered(_work, tasks, chunksize=8), 1):
            rows.append(r)
            if i % max(1, len(tasks) // 10) == 0:
                print(f"  [{i:,}/{len(tasks):,}]", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["policy", "seed", "k", "t"]); w.writeheader(); w.writerows(rows)

    T = {(r["policy"], r["seed"], r["k"]): r["t"] for r in rows}
    seeds = sorted({r["seed"] for r in rows})
    summ = []
    print(f"\n{'policy':<13} {'baseline k=1 (ms)':>18} {'speed-up k=8':>22} {'edge path-counts':>26}")
    print("-" * 84)
    for p in POLICIES:
        base = [T[(p, s, 1)] for s in seeds]
        sp = [T[(p, s, 1)] / T[(p, s, 8)] for s in seeds]
        mb, lb, hb = boot(base); ms, ls, hs = boot(sp)
        prof = path_profile(p)
        summ.append({"policy": p, "n": len(seeds), "baseline_s": mb,
                     "speedup_k8": ms, "ci_low": ls, "ci_high": hs,
                     "edge_path_counts": str(prof)})
        print(f"{p:<13} {mb*1000:>18.1f} {ms:>10.3f} [{ls:.3f},{hs:.3f}] {str(prof):>26}")
    with open(OUT / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summ[0].keys())); w.writeheader(); w.writerows(summ)
    print(f"\nCSVs in {OUT}/")


if __name__ == "__main__":
    main()
