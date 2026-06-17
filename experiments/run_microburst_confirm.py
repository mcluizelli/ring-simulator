"""
v7 — Microburst confirmation run (parallel, n-seed, paired, bootstrap CIs).

Confirms (or refutes) the three claims from docs/research/microburst_investigation.md
to publishable rigor:

  Claim 2  duration is NOT the limiter: at matched aggregate congestion the
           adaptive controller reacts to 0.1ms bursts >= as well as to 1ms/5ms.
  Claim 3  the cooldown is the lever: at pure 0.1ms bursts, shortening the
           controller cooldown 10ms->1ms recovers most of the multi-flow gain.
  Claim 4  efficiency: adaptive reaches >= best static-k speedup at lower QP cost.

Method: per-seed-paired ratios (same congestion realization for every run-type of
a seed) + bootstrap 95% CIs, and WITHIN-SEED paired differences for the key tests
(these cancel the congestion-realization noise that made n=6 point estimates
useless). Burst frequency is calibrated per duration so all durations share the
SAME mean utilization (~0.30) on the affected edges — the only thing that differs
is the burst timescale.

Usage:  python experiments/run_microburst_confirm.py [n_seeds] [n_workers] [target_util]
"""
from __future__ import annotations

import csv
import multiprocessing as mp
import os
import sys
from pathlib import Path
from statistics import mean, pstdev

import numpy as np

# --- bootstrap: make the simulator core (../sim.py) importable from this subfolder ---
import sys as _sys
from pathlib import Path as _BootPath
_RING_ROOT = _BootPath(__file__).resolve().parents[1]
if str(_RING_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_RING_ROOT))
# ------------------------------------------------------------------------------------
from sim import (
    AdaptiveConfig, CongestionModel, FatTree, build_worker_ring,
    run_adaptive_ring_transfer, run_simple_ring_transfer,
)

# ── Fixed experiment parameters (match D.6) ──────────────────
TOPO_K, LINK, DT, BYTES, RING, AFF = 16, 100.0, 5e-5, 256 * 1024 * 1024, 16, 0.3
DURATIONS = [2, 20, 100]            # 0.1ms (sub-ms), 1ms (=window), 5ms (>>window)
SEED_BASE = 7000

# Controller variants (window=1ms unless noted; threshold .2 unless noted)
CTRLS = {
    "adaptDef":  AdaptiveConfig(),                                                   # cd 10ms
    "adaptCD5":  AdaptiveConfig(cooldown_ticks=100),                                 # cd 5ms
    "adaptCD2":  AdaptiveConfig(cooldown_ticks=40),                                  # cd 2ms
    "adaptCD1":  AdaptiveConfig(cooldown_ticks=20),                                  # cd 1ms
    "adaptAggr": AdaptiveConfig(measurement_window_s=0.0005, threshold=0.1, cooldown_ticks=20),
}

# Run-types: (label, duration_ticks, kind, payload)
SPECS = []
for bt in DURATIONS:
    SPECS.append((f"dur{bt}_k1", bt, "static", 1))
    SPECS.append((f"dur{bt}_k8", bt, "static", 8))
    SPECS.append((f"dur{bt}_adaptDef", bt, "adaptive", "adaptDef"))
# extra static ladder + cooldown sweep only at the sub-ms duration (bt=2)
SPECS.append(("dur2_k2", 2, "static", 2))
SPECS.append(("dur2_k4", 2, "static", 4))
for name in ["adaptCD5", "adaptCD2", "adaptCD1", "adaptAggr"]:
    SPECS.append((f"dur2_{name}", 2, "adaptive", name))

OUT_DIR = Path(f"{_RING_ROOT}/results/v7.0_microburst_confirm_2026-06-17")

# ── Worker globals ───────────────────────────────────────────
_TOPO = _RING = _LAYERS = _POOL = _ALL = None
_BP = {}   # duration_ticks -> calibrated burst_prob


def _make_topo():
    topo = FatTree(k=TOPO_K, link_capacity_Gbps=LINK)
    ring = build_worker_ring(topo.hosts, worker_count=RING, start_index=0)
    layers = topo.get_edges_by_layer()
    allE = [e for L in layers.values() for e in L]
    pool = layers["agg_core"] + layers["edge_agg"]
    return topo, ring, allE, pool


def cong(seed, bt, bp):
    return CongestionModel(
        mode="microburst", seed=SEED_BASE + seed, affected_fraction=AFF,
        target_layers=["agg_core", "edge_agg"],
        burst_prob=bp, burst_ticks=bt,
        burst_util_low=0.80, burst_util_high=0.98,
        normal_util_low=0.0, normal_util_high=0.05,
    )


def _init(burst_probs):
    global _TOPO, _RING, _LAYERS, _POOL, _ALL, _BP
    _TOPO, _RING, _ALL, _POOL = _make_topo()
    _BP = burst_probs


def _work(seed):
    rows = []
    for label, bt, kind, payload in SPECS:
        c = cong(seed, bt, _BP[bt])
        if kind == "static":
            t = run_simple_ring_transfer(topo=_TOPO, ring=_RING, bytes_per_neighbor=BYTES,
                                         flows_per_neighbor=payload, dt_s=DT, congestion=c)
            mk = float(payload)
        else:
            ad = run_adaptive_ring_transfer(topo=_TOPO, ring=_RING, bytes_per_neighbor=BYTES,
                                            adaptive_cfg=CTRLS[payload], dt_s=DT, congestion=c)
            t = ad["completion_time_s"]
            mk = mean(ad["final_k_per_edge"].values())
        rows.append({"seed": seed, "run_type": label, "duration_ticks": bt,
                     "completion_s": t, "mean_k": mk})
    return rows


# ── Calibration (main process) ───────────────────────────────
# Each affected edge runs the SAME independent microburst process, so the
# per-edge mean utilization is iid across edges and independent of how many
# edges are affected. We therefore calibrate burst_prob on a small synthetic
# edge set (fast) rather than the ~1000 topology edges (which made calibration
# the bottleneck). 30 edges x 4000 ticks = 120k samples -> a stable mean.
_CAL_EDGES = [(f"cu{i}", f"cv{i}") for i in range(30)]


def realized_util(bt, bp, ticks=4000):
    cm = CongestionModel(
        mode="microburst", seed=12345, affected_fraction=1.0,
        burst_prob=bp, burst_ticks=bt,
        burst_util_low=0.80, burst_util_high=0.98,
        normal_util_low=0.0, normal_util_high=0.05,
    )
    cm.attach(_CAL_EDGES, target_edges=_CAL_EDGES)
    per_edge = {e: 0.0 for e in cm._affected}
    for _ in range(ticks):
        cm.update_tick()
        for e in cm._affected:
            per_edge[e] += cm._util.get(e, 0.0)
    edge_means = [v / ticks for v in per_edge.values()]
    return mean(edge_means), pstdev(edge_means)


def calibrate(bt, target):
    lo, hi = 1e-4, 0.95
    for _ in range(34):
        mid = (lo + hi) / 2
        u, _ = realized_util(bt, mid, ticks=2000)
        if u < target:
            lo = mid
        else:
            hi = mid
    bp = (lo + hi) / 2
    um, us = realized_util(bt, bp, ticks=8000)
    return bp, um, us


# ── Analysis ─────────────────────────────────────────────────
def boot_ci(vals, n_boot=5000, ci=0.95, seed=42):
    v = np.asarray([x for x in vals if x == x], float)
    if len(v) < 2:
        return (float(v[0]) if len(v) else float("nan"),) * 3
    rng = np.random.default_rng(seed)
    m = np.array([rng.choice(v, len(v), replace=True).mean() for _ in range(n_boot)])
    return float(v.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    nw = int(sys.argv[2]) if len(sys.argv) > 2 else min(10, os.cpu_count() or 4)
    target = float(sys.argv[3]) if len(sys.argv) > 3 else 0.30
    seeds = list(range(n))

    global OUT_DIR
    OUT_DIR = Path(f"{_RING_ROOT}/results/v7.0_microburst_confirm_2026-06-17/util{int(round(target*100)):02d}")

    print(f"v7 microburst confirmation: n={n} seeds, {nw} workers, target_util={target}\n")
    print("Calibrating burst_prob per duration (matched per-edge aggregate util)...")
    burst_probs = {}
    for bt in DURATIONS:
        bp, um, us = calibrate(bt, target)
        burst_probs[bt] = bp
        print(f"  dur={bt:>3} ({bt*DT*1000:.2f}ms): burst_prob={bp:.4f}  achieved_util={um:.3f}+/-{us:.3f}")

    print(f"\nRunning {len(SPECS)} run-types x {n} seeds = {len(SPECS)*n} sims...")
    rows = []
    with mp.Pool(processes=nw, initializer=_init, initargs=(burst_probs,)) as pool_:
        for i, res in enumerate(pool_.imap_unordered(_work, seeds), 1):
            rows.extend(res)
            if i % max(1, n // 20) == 0 or i == n:
                print(f"  [{i}/{n}] seeds done", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["seed", "run_type", "duration_ticks", "completion_s", "mean_k"])
        w.writeheader(); w.writerows(rows)

    # index
    T, K = {}, {}
    for r in rows:
        T[(r["seed"], r["run_type"])] = r["completion_s"]
        K[(r["seed"], r["run_type"])] = r["mean_k"]

    def dur_of(rt): return int(rt.split("_")[0][3:])
    def speedups(rt):
        out = []
        for s in seeds:
            base = T.get((s, f"dur{dur_of(rt)}_k1")); tk = T.get((s, rt))
            if base and tk and tk > 0:
                out.append(base / tk)
        return out

    print("\n" + "=" * 78)
    print("PER-CONDITION SPEEDUP (per-seed paired vs k=1 same duration, bootstrap 95% CI)")
    print(f"{'run_type':>16} {'speedup':>9} {'95% CI':>16} {'mean_k':>7}")
    print("-" * 78)
    summ = []
    for label, bt, kind, payload in SPECS:
        sp = speedups(label)
        m, lo, hi = boot_ci(sp)
        mk = mean([K[(s, label)] for s in seeds if (s, label) in K])
        summ.append({"run_type": label, "speedup_mean": m, "ci_low": lo, "ci_high": hi, "mean_k": mk})
        print(f"{label:>16} {m:>8.3f}x [{lo:.3f},{hi:.3f}] {mk:>7.2f}")
    with open(OUT_DIR / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["run_type", "speedup_mean", "ci_low", "ci_high", "mean_k"])
        w.writeheader(); w.writerows(summ)

    # ── Paired-difference tests (the decisive ones) ──
    def paired_diff(rt_a, rt_b):
        d = []
        for s in seeds:
            a, b = T.get((s, rt_a)), T.get((s, rt_b))
            ba, bb = T.get((s, f"dur{dur_of(rt_a)}_k1")), T.get((s, f"dur{dur_of(rt_b)}_k1"))
            if a and b and ba and bb and a > 0 and b > 0:
                d.append(ba / a - bb / b)   # speedup(a) - speedup(b), paired by seed
        return boot_ci(d)

    print("\n" + "=" * 78)
    print("DECISIVE PAIRED-DIFFERENCE TESTS (mean d_speedup, 95% CI; sign is what matters)")
    print("-" * 78)
    tests = [
        ("Claim2 controller: 0.1ms - 1ms (adaptDef)", "dur2_adaptDef", "dur20_adaptDef"),
        ("Claim2 controller: 0.1ms - 5ms (adaptDef)", "dur2_adaptDef", "dur100_adaptDef"),
        ("Claim2 static k8: 0.1ms - 1ms", "dur2_k8", "dur20_k8"),
        ("Claim3 cooldown: cd1ms - cd10ms (sub-ms)", "dur2_adaptCD1", "dur2_adaptDef"),
        ("Claim3 cooldown: aggr - cd10ms (sub-ms)", "dur2_adaptAggr", "dur2_adaptDef"),
        ("Claim4 adaptCD1 - static k8 (sub-ms)", "dur2_adaptCD1", "dur2_k8"),
    ]
    for name, a, b in tests:
        m, lo, hi = paired_diff(a, b)
        verdict = ("A>B" if lo > 0 else ("A<B" if hi < 0 else "indistinguishable (CI spans 0)"))
        print(f"  {name:<44} d={m:+.3f} [{lo:+.3f},{hi:+.3f}]  -> {verdict}")

    # QP efficiency note
    mk_cd1 = mean([K[(s, "dur2_adaptCD1")] for s in seeds if (s, "dur2_adaptCD1") in K])
    print(f"\nQP cost: adaptCD1 mean_k={mk_cd1:.2f} vs static k=8 -> "
          f"{8/mk_cd1:.1f}x fewer flows if speedups match.")
    print(f"\nCSV + summary in {OUT_DIR}/")


if __name__ == "__main__":
    main()
