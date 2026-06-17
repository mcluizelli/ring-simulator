"""
INVESTIGATION part 2: is the controller's weak microburst reaction caused by the
sub-ms DURATION (the 'cannot react in time' claim) or by controller TUNING
(cooldown 10 ms, threshold 20%) — which would be fixable?

Two decisive tests, both at MATCHED aggregate congestion (mean_util ~ 0.30 on the
affected edges, calibrated per duration so the only thing that differs is the
burst timescale):

  Test 1 — vary DURATION at matched aggregate, DEFAULT controller:
    burst_ticks in {2 (100us, sub-ms), 20 (1ms = window), 100 (5ms >> window)}.
    If the controller reacts (mean_k, adaptive speedup) about EQUALLY across
    durations, then duration is NOT the bottleneck -> 'cannot react to sub-ms'
    is a false positive.

  Test 2 — at the sub-ms duration (burst_ticks=2), DEFAULT vs TUNED controller
    (shorter cooldown + lower threshold). If tuning recovers most of static k8's
    gain, the weak reaction was a tuning artifact, not a hard temporal limit.

Usage:  python investigations/investigate_microburst_duration.py [n_seeds]
"""
from __future__ import annotations

import sys
from statistics import mean

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

TOPO_K, LINK, DT, BYTES, RING, AFF = 16, 100.0, 5e-5, 256 * 1024 * 1024, 16, 0.3
TARGET_UTIL = 0.30

topo = FatTree(k=TOPO_K, link_capacity_Gbps=LINK)
ring = build_worker_ring(topo.hosts, worker_count=RING, start_index=0)
_layers = topo.get_edges_by_layer()
_all = [e for L in _layers.values() for e in L]
_pool = _layers["agg_core"] + _layers["edge_agg"]


def cong(burst_prob, seed, burst_ticks):
    return CongestionModel(
        mode="microburst", seed=seed, affected_fraction=AFF,
        target_layers=["agg_core", "edge_agg"],
        burst_prob=burst_prob, burst_ticks=burst_ticks,
        burst_util_low=0.80, burst_util_high=0.98,
        normal_util_low=0.0, normal_util_high=0.05,
    )


def util_of(burst_prob, burst_ticks, seeds, ticks=600):
    vals = []
    for s in seeds:
        cm = cong(burst_prob, s, burst_ticks)
        cm.attach(_all, target_edges=_pool)
        acc = 0.0
        for _ in range(ticks):
            cm.update_tick()
            acc += mean(cm._util.get(e, 0.0) for e in cm._affected)
        vals.append(acc / ticks)
    return mean(vals)


def calibrate_prob(burst_ticks, seeds):
    """Bisection search for burst_prob that yields mean_util ~ TARGET_UTIL."""
    lo, hi = 1e-4, 0.95
    for _ in range(22):
        mid = (lo + hi) / 2
        u = util_of(mid, burst_ticks, seeds[:4])
        if u < TARGET_UTIL:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def eval_config(burst_prob, burst_ticks, seeds, adcfg):
    sp_static, mk, sp_adapt = [], [], []
    for s in seeds:
        t1 = run_simple_ring_transfer(topo=topo, ring=ring, bytes_per_neighbor=BYTES,
                                      flows_per_neighbor=1, dt_s=DT, congestion=cong(burst_prob, s, burst_ticks))
        t8 = run_simple_ring_transfer(topo=topo, ring=ring, bytes_per_neighbor=BYTES,
                                      flows_per_neighbor=8, dt_s=DT, congestion=cong(burst_prob, s, burst_ticks))
        ad = run_adaptive_ring_transfer(topo=topo, ring=ring, bytes_per_neighbor=BYTES,
                                        adaptive_cfg=adcfg, dt_s=DT, congestion=cong(burst_prob, s, burst_ticks))
        sp_static.append(t1 / t8)
        mk.append(mean(ad["final_k_per_edge"].values()))
        sp_adapt.append(t1 / ad["completion_time_s"])
    return mean(sp_static), mean(mk), mean(sp_adapt)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    seeds = list(range(2000, 2000 + n))
    default = AdaptiveConfig()  # window 1ms, threshold 0.2, k_max 8, cooldown 200 (10ms)

    print(f"Matched-aggregate microburst study — target mean_util~{TARGET_UTIL}, "
          f"P={RING}, n={n}\n")

    print("TEST 1 — vary burst DURATION at matched aggregate, DEFAULT controller")
    print(f"{'burst_ticks':>11} {'~dur':>7} {'burst_prob':>10} {'mean_util':>9} "
          f"{'static k8':>10} {'adapt meanK':>12} {'adapt spd':>10}")
    print("-" * 75)
    durations = [2, 20, 100]  # 100us (sub-ms), 1ms (=window), 5ms (>>window)
    for bt in durations:
        bp = calibrate_prob(bt, seeds)
        u = util_of(bp, bt, seeds)
        s_sp, a_mk, a_sp = eval_config(bp, bt, seeds, default)
        dur_ms = bt * DT * 1000
        print(f"{bt:>11} {dur_ms:>6.2f}m {bp:>10.4f} {u:>9.3f} "
              f"{s_sp:>9.2f}x {a_mk:>12.2f} {a_sp:>9.2f}x")

    print("\nTEST 2 — at sub-ms duration (burst_ticks=2), DEFAULT vs TUNED controller")
    bt = 2
    bp = calibrate_prob(bt, seeds)
    u = util_of(bp, bt, seeds)
    print(f"  (burst_prob={bp:.4f}, mean_util={u:.3f}, burst dur=0.10ms << 1ms window)")
    print(f"{'controller':>30} {'window':>7} {'thresh':>7} {'cooldown':>9} "
          f"{'adapt meanK':>12} {'adapt spd':>10}")
    print("-" * 80)
    variants = [
        ("default (1ms, .2, 10ms)", AdaptiveConfig()),
        ("lower threshold (.1)", AdaptiveConfig(threshold=0.1)),
        ("short cooldown (1ms)", AdaptiveConfig(cooldown_ticks=20)),
        ("tuned (.5ms win,.1,1ms cd)", AdaptiveConfig(measurement_window_s=0.0005, threshold=0.1, cooldown_ticks=20)),
    ]
    s_sp, _, _ = eval_config(bp, bt, seeds, default)
    for label, cfg in variants:
        _, a_mk, a_sp = eval_config(bp, bt, seeds, cfg)
        print(f"{label:>30} {cfg.measurement_window_s*1000:>6.2f}m {cfg.threshold:>7.2f} "
              f"{cfg.cooldown_ticks*DT*1000:>7.1f}m {a_mk:>12.2f} {a_sp:>9.2f}x")
    print(f"\n  static k=8 reference at this config: {s_sp:.2f}x")
    print("\n  If TUNED adapt spd approaches static k=8 at the SUB-MS duration, the weak")
    print("  default reaction was a TUNING artifact (cooldown/threshold), not a hard")
    print("  'sub-ms is too fast to react' limit -> the original claim is a false positive.")


if __name__ == "__main__":
    main()
