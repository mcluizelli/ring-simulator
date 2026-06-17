"""
Validate that each CongestionModel mode produces its intended temporal pattern.
Task D.5 (epic: congestion-models). See docs/research/lit_congestion_models.md.

For each mode we drive the model for a fixed number of ticks on a small set of
affected links and report: mean utilization, fraction of ticks "congested"
(util > 0.2), and the mean length of a congested run (burst). The expected
pattern for each mode is asserted.
"""
from __future__ import annotations

from statistics import mean
# --- bootstrap: make the simulator core (../sim.py) importable from this subfolder ---
import sys as _sys
from pathlib import Path as _BootPath
_RING_ROOT = _BootPath(__file__).resolve().parents[1]
if str(_RING_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_RING_ROOT))
# ------------------------------------------------------------------------------------
from sim import CongestionModel

DT_S = 5e-5            # 50 us per tick (matches the simulator)
TICKS = 8000          # 400 ms
EDGES = [(f"u{i}", f"v{i}") for i in range(20)]   # 20 dummy links


def run(mode: str, **kw) -> dict:
    cm = CongestionModel(mode=mode, seed=7, affected_fraction=1.0, **kw)
    cm.attach(EDGES, target_edges=EDGES)
    # record the utilisation series of one representative edge
    probe = EDGES[0]
    series = []
    for _ in range(TICKS):
        cm.update_tick()
        series.append(cm.residual_capacity(probe, 1.0))  # residual fraction
    util = [1.0 - r for r in series]                      # utilisation = 1 - residual

    congested = [u > 0.2 for u in util]
    frac_congested = sum(congested) / len(congested)

    # mean burst length = mean length of consecutive congested runs
    runs, cur = [], 0
    for c in congested:
        if c:
            cur += 1
        elif cur:
            runs.append(cur); cur = 0
    if cur:
        runs.append(cur)
    mean_burst_ticks = mean(runs) if runs else 0.0

    return {
        "mean_util": mean(util),
        "frac_congested": frac_congested,
        "mean_burst_ticks": mean_burst_ticks,
        "mean_burst_ms": mean_burst_ticks * DT_S * 1000,
        "n_bursts": len(runs),
    }


def main() -> None:
    print(f"{'mode':<11} {'mean_util':>9} {'frac_cong':>9} {'burst_ticks':>12} {'burst_ms':>9} {'n_bursts':>9}")
    print("-" * 64)
    results = {}
    for mode in ["onoff", "iid", "hot_spot", "incast", "microburst"]:
        r = run(mode)
        results[mode] = r
        print(f"{mode:<11} {r['mean_util']:>9.3f} {r['frac_congested']:>9.3f} "
              f"{r['mean_burst_ticks']:>12.1f} {r['mean_burst_ms']:>9.2f} {r['n_bursts']:>9}")

    print("\n--- Intended-pattern checks ---")
    ok = True

    # hot_spot: persistent (almost always congested), mean util in the congested band
    r = results["hot_spot"]
    c1 = r["frac_congested"] > 0.97 and 0.45 < r["mean_util"] < 0.65
    print(f"[{'PASS' if c1 else 'FAIL'}] hot_spot persistent & mid-band "
          f"(frac>0.97, 0.45<mean<0.65): frac={r['frac_congested']:.3f}, mean={r['mean_util']:.3f}")
    ok &= c1

    # incast: near-total saturation (mean util very high), persistent
    r = results["incast"]
    c2 = r["frac_congested"] > 0.97 and r["mean_util"] > 0.85
    print(f"[{'PASS' if c2 else 'FAIL'}] incast near-saturation "
          f"(frac>0.97, mean>0.85): frac={r['frac_congested']:.3f}, mean={r['mean_util']:.3f}")
    ok &= c2

    # microburst: rare & very short (sub-ms) bursts, low mean util
    r = results["microburst"]
    c3 = r["mean_util"] < 0.15 and r["mean_burst_ms"] < 1.0 and r["n_bursts"] > 0
    print(f"[{'PASS' if c3 else 'FAIL'}] microburst rare & sub-ms "
          f"(mean<0.15, burst<1ms, n>0): mean={r['mean_util']:.3f}, "
          f"burst={r['mean_burst_ms']:.2f}ms, n={r['n_bursts']}")
    ok &= c3

    # onoff: bursts are ms-scale (longer than microburst), trackable by the 1ms controller
    r = results["onoff"]
    c4 = r["mean_burst_ms"] > 1.0
    print(f"[{'PASS' if c4 else 'FAIL'}] onoff bursts are ms-scale "
          f"(>1ms, trackable): burst={r['mean_burst_ms']:.2f}ms")
    ok &= c4

    # key contrast: onoff bursts are much longer than microburst bursts
    c5 = results["onoff"]["mean_burst_ms"] > 5 * results["microburst"]["mean_burst_ms"]
    print(f"[{'PASS' if c5 else 'FAIL'}] onoff bursts >> microburst bursts "
          f"({results['onoff']['mean_burst_ms']:.2f}ms vs {results['microburst']['mean_burst_ms']:.2f}ms)")
    ok &= c5

    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
