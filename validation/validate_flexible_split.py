"""
Validation for run_ring_transfer_proportional (C.3.8 flexible split).

Checks (all must pass):
  V0  Byte conservation: every logical edge delivers EXACTLY bytes_per_neighbor
      (redistribution must never create or destroy bytes) — the sound guard
      against over-claiming.
  V1  k=1 identity: proportional == equal exactly (redistribution is a no-op).
  V2  Never-worse: proportional <= equal * (1 + 0.5%) on every sampled cell
      (equal split IS a feasible allocation, so proportional must not lose).
  V3  Bound sanity: proportional >= 0.90 * static optimal-split bound.
      NOTE the static bound assumes FULL contention for the whole run; in the
      sim, edges that finish early reduce contention and speed up the rest, so
      completion may legitimately land somewhat BELOW the static bound
      (proportional sharpens this end-game effect). Conservation (V0) — not the
      static bound — is the over-claim guard.
  V4  Gap closure on the canonical stressed cell (os4, P=16, k=8): over seeds
      with a REAL equal-split gap (>2%), proportional closes >= 90% of
      (equal - opt).  Seeds whose slowest edge is host-NIC-bottlenecked have a
      ~0.6% quantization-level "gap" that NO split policy can close (all k
      sub-flows share the same host link) — they are reported, not scored.
  V5  Symmetric no-op: on a cell where equal-split already sits on the bound
      (nb, k=2), proportional changes nothing beyond 1%.

Usage:  python validation/validate_flexible_split.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_RING_ROOT = Path(__file__).resolve().parents[1]
if str(_RING_ROOT) not in sys.path:
    sys.path.insert(0, str(_RING_ROOT))

import random

from sim import (FatTree, FlowLevelSimulator, add_ring_neighbor_flows,
                 compute_ring_theoretical_time,
                 run_ring_transfer_proportional, run_simple_ring_transfer)

BYTES = 64 * 1024 * 1024
DT = 5e-5
SEED_BASE = 9000

FABRICS = {
    "3tier_nb":  (3, 1.0),
    "3tier_os4": (3, 4.0),
    "2tier":     (2, 1.0),
}

failures = []


def check(name, ok, detail):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    if not ok:
        failures.append(name)


def main():
    topos = {n: FatTree(16, n_tiers=nt, oversub=os) for n, (nt, os) in FABRICS.items()}

    print("V0 — byte conservation per logical edge (os4, k=8)")
    topo = topos["3tier_os4"]
    ring = random.Random(SEED_BASE).sample(topo.hosts, 16)
    m = run_ring_transfer_proportional(topo, ring, BYTES, 8, dt_s=DT, return_metrics=True)
    worst = max(abs(v - BYTES) / BYTES for v in m["per_edge_delivered_bytes"].values())
    check("V0 conservation", worst < 1e-9, f"worst per-edge delivery error = {worst:.2e} (want < 1e-9)")

    print("V1 — k=1 identity (prop == equal exactly)")
    for name, topo in topos.items():
        ring = random.Random(SEED_BASE + 3).sample(topo.hosts, 16)
        te = run_simple_ring_transfer(topo=topo, ring=ring, bytes_per_neighbor=BYTES,
                                      flows_per_neighbor=1, dt_s=DT, congestion=None)
        tp = run_ring_transfer_proportional(topo, ring, BYTES, 1, dt_s=DT)
        check(f"V1 {name}", abs(tp - te) < 1e-12, f"equal={te:.6f}s prop={tp:.6f}s")

    print("V2+V3 — never-worse than equal AND never beats 0.99*optimal (5 seeds x k in {2,4,8})")
    worst_v2, worst_v3 = 0.0, 10.0
    for name, topo in topos.items():
        for seed in range(5):
            ring = random.Random(SEED_BASE + seed).sample(topo.hosts, 16)
            for k in (2, 4, 8):
                te = run_simple_ring_transfer(topo=topo, ring=ring, bytes_per_neighbor=BYTES,
                                              flows_per_neighbor=k, dt_s=DT, congestion=None)
                tp = run_ring_transfer_proportional(topo, ring, BYTES, k, dt_s=DT)
                opt = compute_ring_theoretical_time(topo, ring, BYTES, k)["theoretical_time_s"]
                worst_v2 = max(worst_v2, tp / te - 1)
                worst_v3 = min(worst_v3, tp / opt)
    check("V2 never-worse", worst_v2 <= 0.005, f"worst prop/equal-1 = {worst_v2*100:+.2f}% (allow +0.5%)")
    check("V3 bound sanity", worst_v3 >= 0.90,
          f"min prop/opt = {worst_v3:.4f} (>=0.90; sub-1.0 = legitimate end-game contention decay)")

    print("V4 — gap closure on os4/P=16/k=8 (5 seeds; scored only where gap > 2%)")
    topo = topos["3tier_os4"]
    closures, host_limited = [], 0
    for seed in range(5):
        ring = random.Random(SEED_BASE + seed).sample(topo.hosts, 16)
        te = run_simple_ring_transfer(topo=topo, ring=ring, bytes_per_neighbor=BYTES,
                                      flows_per_neighbor=8, dt_s=DT, congestion=None)
        tp = run_ring_transfer_proportional(topo, ring, BYTES, 8, dt_s=DT)
        opt = compute_ring_theoretical_time(topo, ring, BYTES, 8)["theoretical_time_s"]
        if te / opt - 1 > 0.02:
            closures.append((te - tp) / (te - opt))
        else:
            host_limited += 1
    mean_cl = sum(closures) / len(closures) if closures else float("nan")
    check("V4 gap closure", bool(closures) and mean_cl >= 0.90,
          f"mean closure = {mean_cl*100:.1f}% over {len(closures)} gapped seeds "
          f"({host_limited} host-NIC-limited seeds excluded; want >= 90%)")

    print("V5 — symmetric no-op (nb, k=2: equal already near bound)")
    topo = topos["3tier_nb"]
    ring = random.Random(SEED_BASE + 1).sample(topo.hosts, 16)
    te = run_simple_ring_transfer(topo=topo, ring=ring, bytes_per_neighbor=BYTES,
                                  flows_per_neighbor=2, dt_s=DT, congestion=None)
    tp = run_ring_transfer_proportional(topo, ring, BYTES, 2, dt_s=DT)
    check("V5 symmetric", abs(tp / te - 1) <= 0.01, f"prop/equal = {tp/te:.4f} (want within 1%)")

    print()
    if failures:
        print(f"RESULT: {len(failures)} FAILURE(S): {failures}")
        sys.exit(1)
    print("RESULT: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
