# Proportional mechanism audit

- Hard mechanism gate: **FAIL**
- Window-sensitivity gate: **PASS**
- Decision: **STOP_BEFORE_N1000_AND_REVIEW**
- Traced simulations: 180
- Exact 1 ms sidecar/production rows: 60
- Exact fresh/sealed scientific rows: 60

## Mechanism observations

- QP reactivations: 208
- Reactivations using a rate older than the just-finished tick: 24
- Positive stale weights: 24
- Stale weights differing from prospective current weights: 17
- Maximum used-rate age: 3 ticks
- Maximum stale/current normalized-weight difference: 0.0625
- Maximum final conservation error: 9.53674316406e-07 B

## Window sensitivity

- Maximum cell/allocator/window median absolute delta: 0%
- Maximum individual absolute delta: 1.6129%
- Ordering reversals outside a one-tick tie: 0

## Scope

This gate covers the static proportional core only. It does not validate
controller calibration or stale-rate behavior under time-varying congestion.
No `sim.py`, frozen result, paper, commit, or push was produced by this run.

## Hard-gate failures

- stale_shadow_mismatch_count=17
