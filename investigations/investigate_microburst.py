"""
INVESTIGATION (D.6 follow-up): is the microburst "controller cannot react in
time" claim a false positive?

The D.6 static result (microburst -> ~1.02x) was taken as evidence that the
adaptive controller's 1 ms window cannot react to sub-millisecond bursts. But:
  1. the static experiment has NO controller, so it cannot show a controller
     limitation at all; and
  2. what triggers the controller is the WINDOW-AVERAGE throughput dropping
     below (1 - threshold) * nominal. A burst's effect on that average is
     (frequency x duration x intensity) = the FRACTION of the window that is
     congested — not whether one burst is shorter than the window.

Hypothesis: microburst -> ~1.0x because the default params are too SPARSE
(burst_prob=0.001 -> ~0.2% of ticks congested), i.e. there is almost no
aggregate congestion to bypass — NOT because the controller is too slow.

Discriminating test: hold burst DURATION fixed at 2 ticks (=100 us, well below
the 1 ms / 20-tick window) and sweep FREQUENCY (burst_prob). For each level:
  - realized mean utilization on affected edges (aggregate congestion)
  - static speedup  T(k=1)/T(k=8)            -> does multi-flow help at all?
  - adaptive mean final k                     -> does the controller add flows?
  - adaptive speedup T(k=1,static)/T(adaptive)-> does reacting recover the time?

If denser SUB-MS bursts make static multi-flow help AND the controller add
flows, then "cannot react to sub-ms" is refuted: the variable is aggregate load,
not individual burst duration.

Usage:  python investigations/investigate_microburst.py [n_seeds]
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

TOPO_K = 16
LINK = 100.0
DT = 5e-5
BYTES = 256 * 1024 * 1024
RING = 16
AFF = 0.3
BURST_TICKS = 2          # FIXED sub-ms duration (100 us) << 1 ms controller window

topo = FatTree(k=TOPO_K, link_capacity_Gbps=LINK)
ring = build_worker_ring(topo.hosts, worker_count=RING, start_index=0)
_layers = topo.get_edges_by_layer()
_all_edges = [e for L in _layers.values() for e in L]
_pool = _layers["agg_core"] + _layers["edge_agg"]


def cong(burst_prob: float, seed: int, burst_ticks: int = BURST_TICKS) -> CongestionModel:
    return CongestionModel(
        mode="microburst", seed=seed, affected_fraction=AFF,
        target_layers=["agg_core", "edge_agg"],
        burst_prob=burst_prob, burst_ticks=burst_ticks,
        burst_util_low=0.80, burst_util_high=0.98,
        normal_util_low=0.0, normal_util_high=0.05,
    )


def realized_util(burst_prob: float, seed: int, ticks: int, burst_ticks: int = BURST_TICKS) -> float:
    """Mean utilization on affected edges over `ticks` (proxy for aggregate load)."""
    cm = cong(burst_prob, seed, burst_ticks)
    cm.attach(_all_edges, target_edges=_pool)
    acc = 0.0
    for _ in range(ticks):
        cm.update_tick()
        acc += mean(cm._util.get(e, 0.0) for e in cm._affected)
    return acc / ticks


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    seeds = list(range(1000, 1000 + n))
    probs = [0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2]
    adcfg = AdaptiveConfig()  # default: 1 ms window, threshold 0.2, k_max 8, cooldown 10 ms

    print(f"microburst investigation — burst_ticks={BURST_TICKS} (100 us, sub-ms) FIXED, "
          f"sweep frequency; P={RING}, n={n} seeds, k_max={adcfg.k_max}\n")
    print(f"{'burst_prob':>10} {'mean_util':>9} {'static k8':>10} {'adapt meanK':>12} "
          f"{'adapt spd':>10} {'verdict':>26}")
    print("-" * 82)

    for bp in probs:
        util = mean(realized_util(bp, s, 600) for s in seeds)
        sp_static, mk, sp_adapt = [], [], []
        for s in seeds:
            t1 = run_simple_ring_transfer(topo=topo, ring=ring, bytes_per_neighbor=BYTES,
                                          flows_per_neighbor=1, dt_s=DT, congestion=cong(bp, s))
            t8 = run_simple_ring_transfer(topo=topo, ring=ring, bytes_per_neighbor=BYTES,
                                          flows_per_neighbor=8, dt_s=DT, congestion=cong(bp, s))
            ad = run_adaptive_ring_transfer(topo=topo, ring=ring, bytes_per_neighbor=BYTES,
                                            adaptive_cfg=adcfg, dt_s=DT, congestion=cong(bp, s))
            sp_static.append(t1 / t8)
            mk.append(mean(ad["final_k_per_edge"].values()))
            sp_adapt.append(t1 / ad["completion_time_s"])
        s_sp, a_mk, a_sp = mean(sp_static), mean(mk), mean(sp_adapt)
        # verdict: did the controller react, and did it recover most of static's gain?
        if s_sp < 1.05:
            v = "no congestion to bypass"
        elif a_mk > 1.3 and a_sp > 1.0 + 0.5 * (s_sp - 1.0):
            v = "CONTROLLER REACTS"
        elif a_mk <= 1.15:
            v = "controller does NOT react"
        else:
            v = "partial reaction"
        print(f"{bp:>10.3f} {util:>9.3f} {s_sp:>9.2f}x {a_mk:>12.2f} {a_sp:>9.2f}x {v:>26}")

    print("\nReading the table:")
    print("  - If 'static k8' rises with burst_prob while duration stays 100us, multi-flow")
    print("    DOES help under sub-ms bursts -> the limit is aggregate load, not duration.")
    print("  - If 'adapt meanK' rises above 1 (controller adds flows) and 'adapt spd'")
    print("    tracks 'static k8', the controller CAN react to sub-ms bursts -> the")
    print("    'cannot react in time' claim is a FALSE POSITIVE (a sparsity artifact).")


if __name__ == "__main__":
    main()
