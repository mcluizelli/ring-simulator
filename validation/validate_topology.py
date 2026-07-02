"""
Validate the extended FatTree topologies (task C.3.0-val) — a false-positive guard
for the C.3.3 / C.3.4 experiments. Checks, per fabric:
  - structural counts (hosts, switches, ECMP path diversity);
  - the realised oversubscription ratio (agg/leaf down:up BW) == requested;
  - path diversity is PRESERVED under Option-B oversubscription (capacity-only);
  - bisection bandwidth == full / oversub;
  - sim vs theory < 1% on a no-congestion ring transfer (the engine behaves);
  - backward compatibility: FatTree(k) defaults == classic non-blocking 3-tier.

See docs/research/plan_C3_fattree_topology.md.
"""
from __future__ import annotations

# --- bootstrap: make the simulator core (../sim.py) importable from this subfolder ---
import sys as _sys
from pathlib import Path as _BootPath
_RING_ROOT = _BootPath(__file__).resolve().parents[1]
if str(_RING_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_RING_ROOT))
# ------------------------------------------------------------------------------------

from sim import (FatTree, build_worker_ring, run_simple_ring_transfer,
                 compute_ring_theoretical_time)

GBPS = 1e9 / 8.0  # bytes/s per Gbps


def agg_down_up_ratio(t: FatTree, sw: str) -> float:
    """down:up BW ratio at a switch: sum(downlink caps) / sum(uplink caps).
    'down' = links from a lower-tier node into sw; 'up' = links from sw to a
    higher-tier node. Tiers by name prefix: h < e < a < c."""
    rank = {"h": 0, "e": 1, "a": 2, "c": 3}
    down = up = 0.0
    for (u, v), cap in t.edge_of.items():
        if u == sw and rank[v[0]] > rank[sw[0]]:
            up += cap
        if v == sw and rank[u[0]] < rank[sw[0]]:
            down += cap
    return down / up if up else float("inf")


def bisection_Bps(t: FatTree) -> float:
    """Aggregate capacity of the top-tier cut (sum of one direction of the
    switch<->core / leaf<->spine links) = the fabric's bisection proxy."""
    top = "c"
    mid = "a" if t.n_tiers == 3 else "e"
    return sum(cap for (u, v), cap in t.edge_of.items() if u[0] == mid and v[0] == top)


def npaths(t, a, b):
    return len(t.equal_cost_paths_hosts(a, b))


def main() -> int:
    k = 16
    ok = True

    def check(cond, label):
        nonlocal ok
        ok &= cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")

    print("=== backward compatibility (defaults == classic non-blocking 3-tier) ===")
    base = FatTree(k)
    check(base.edge_of == FatTree(k, n_tiers=3, oversub=1.0).edge_of, "defaults == explicit 3-tier oversub=1")
    check(len(base.hosts) == k * (k // 2) ** 2, f"hosts == k(k/2)^2 = {k*(k//2)**2}")
    check(len(base.core) == (k // 2) ** 2, f"cores == (k/2)^2 = {(k//2)**2}")
    check(npaths(base, base.hosts[0], base.hosts[-1]) == (k // 2) ** 2,
          f"cross-pod ECMP paths == (k/2)^2 = {(k//2)**2}")

    print("\n=== 3-tier oversubscription (Option B: capacity, paths preserved) ===")
    nb = bisection_Bps(base)
    for os in (1, 2, 4):
        t = FatTree(k, oversub=os)
        ratio = agg_down_up_ratio(t, "a0_0")
        paths = npaths(t, t.hosts[0], t.hosts[-1])
        bis = bisection_Bps(t)
        check(abs(ratio - os) < 1e-6, f"oversub={os}: agg down:up ratio == {os}  (got {ratio:.2f})")
        check(paths == (k // 2) ** 2, f"oversub={os}: ECMP paths preserved == {(k//2)**2}  (got {paths})")
        check(abs(bis - nb / os) < 1e-3, f"oversub={os}: bisection == full/{os}  ({bis/GBPS:.0f} vs {nb/os/GBPS:.0f} Gbps)")

    print("\n=== 2-tier leaf-spine ===")
    l = FatTree(k, n_tiers=2)
    check(len(l.hosts) == k * (k // 2), f"hosts == k*(k/2) = {k*(k//2)}")
    check(len(l.core) == k // 2, f"spines == k/2 = {k//2}")
    check(npaths(l, l.hosts[0], l.hosts[-1]) == k // 2, f"cross-leaf ECMP paths == #spines = {k//2}")
    check(abs(agg_down_up_ratio(l, "e0") - 1.0) < 1e-6, "leaf down:up ratio == 1 (non-blocking)")
    l2 = FatTree(k, n_tiers=2, oversub=2)
    check(abs(agg_down_up_ratio(l2, "e0") - 2.0) < 1e-6, "2-tier oversub=2: leaf down:up == 2")

    print("\n=== sim vs theory < 1% on a no-congestion ring transfer (each fabric) ===")
    BYTES = 64 * 1024 * 1024
    fabrics = {
        "3tier_nonblocking": FatTree(k),
        "3tier_os2":         FatTree(k, oversub=2),
        "3tier_os4":         FatTree(k, oversub=4),
        "2tier":             FatTree(k, n_tiers=2),
    }
    for name, t in fabrics.items():
        ring = build_worker_ring(t.hosts, worker_count=16, start_index=0)
        for kf in (1, 4):
            sim_t = run_simple_ring_transfer(topo=t, ring=ring, bytes_per_neighbor=BYTES,
                                             flows_per_neighbor=kf, dt_s=5e-5, congestion=None)
            theo = compute_ring_theoretical_time(t, ring, BYTES, flows_per_neighbor=kf)["theoretical_time_s"]
            err = abs(sim_t - theo) / theo if theo else float("inf")
            check(err < 0.01, f"{name} k={kf}: sim/theory err {err*100:.2f}% < 1%")

    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
