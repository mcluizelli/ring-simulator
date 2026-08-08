# Proportional mechanism audit — frozen specification

Date frozen: 2026-08-07 (Asia/Jerusalem)

Pre-execution review correction: the 1% median gate is evaluated separately for
each neighboring window. The correction was made before authorization or any
matrix execution so that one stable window cannot mask one unstable window.

Status: diagnostic gate only. It is not a paper estimator and must not mutate
`sim.py`, any frozen CSV, or the paper. A failed gate blocks the planned
`n=1000` core run and returns the mechanism for review.

## Question

The production proportional runner redistributes each logical edge's remaining
bytes every 1 ms using `Flow.last_rate_Bps`. A persistent QP may legitimately
receive new work after its current chunk drains. The audit distinguishes that
reuse from an allocation based on a stale observation, which would not support
the paper's current wording, “exact current model rate.”

## Immutable inputs

- `sim.py`: `40edbacc28e61bb25769278382506c32611cf7fd9e14777480b6fd3d664fab69`
- `experiments/run_rate_allocator_n100.py`: `7d01a2e598c799b0c533fb650f33b8537f51fa3187f427fcf9ada108d56fd8b4`
- `experiments/run_rate_allocator_pilot.py`: `777018e1a408eb5274d5ee87700fc66e4396fd5d39722f625f22e48840efc431`
- sealed run: `investigations/rate_allocator_n100/n100_2026-08-06_03`
- sealed `pairs.csv`: `1f414755c340daa84b9b0df83c60e36991129111bca2bce1dc4165e5f6541764`
- sealed `results_long.csv`: `70c75d05ff4e593266f809e8daf6f6ece058c8ff925b309200fe01669c74c8dd`
- sealed `COMPLETE.json`: `c4caaf8bb203eff3b815236c3bc848d8d483b521571c3ab71a47a32f135eadfa`
- frozen-results root: `09a1418e965b9c2d597721ff0d3b1e8db937a19ce667accfa2cf1f469664c24e`

Any mismatch aborts before simulation.

## Fixed matrix

Cells:

1. `proportional_3tier_os4_p64_k2` — exact-effect control in the sealed run.
2. `proportional_3tier_os4_p64_k16` — paper flagship cell.
3. `proportional_2tier_p64_k8` — strongest selected sealed effect.

Seeds: `0, 11, 22, 33, 44, 55, 66, 77, 88, 99`.

Redistribution windows: `0.5, 1, 2 ms`, exactly `10, 20, 40` ticks at the
frozen `dt=50 us`.

Rate allocators: `link_local_equal_share`, `network_maxmin`.

Total: 3 cells × 10 seeds × 3 windows × 2 allocators = 180 traced
simulations. The 60 simulations at 1 ms are additionally replayed through the
unmodified production pair worker and compared with the sealed checkpoints.

## Boundary observations

For every redistribution boundary the sidecar records or aggregates:

- `sum(sent)+sum(remaining)` per logical edge before and after redistribution;
- zero/negative/non-finite rates and live edges with zero finite rate sum;
- QPs that go from zero remaining bytes to positive remaining bytes;
- the age, in ticks, of every rate used for such a reassignment;
- the fraction and number of bytes assigned to previously idle QPs;
- the next-tick measured rate after a reactivation;
- a prospective current-rate vector computed for all persistent QPs on every
  still-live logical edge under the same topology, residual capacities, and
  allocator state.

The prospective vector is a shadow diagnostic only. It never changes the
production trajectory or completion time.

## Hard gates

1. The 1 ms sidecar completion and delivered-byte vectors are binary64-exact
   matches to the production runner.
2. The fresh production replay's scientific fields match all 30 selected sealed
   pair checkpoints. Timing fields and object IDs are excluded.
3. Every logical edge finishes with at most `1e-6` byte conservation error,
   matching the existing proportional-runner audit tolerance.
4. No negative raw rate, non-finite used weight, non-causal rate observation, or
   live edge with zero finite rate sum is allowed.
5. Reuse itself is allowed. A rate older than the just-finished tick is allowed
   only if its normalized allocation weight matches the prospective current
   weight within `1e-12`. Otherwise the “exact current rate” mechanism gate
   fails.
6. The source, frozen-result, and selected sealed-checkpoint hashes must be
   unchanged after execution.

## Window-sensitivity interpretation

This is a descriptive engineering lock, not a significance test. Relative to
the 1 ms result, the audit reports per-run tick and relative deltas for 0.5 and
2 ms. The 1 ms setting is considered numerically stable only if:

- no allocator ordering reverses outside a one-tick tie;
- every cell/allocator/window median absolute relative deviation is at most 1%; and
- no individual absolute relative deviation exceeds 5%.

These thresholds are decision thresholds for whether to proceed, not effect
estimates for the paper. Any hard-gate failure dominates this sensitivity rule.

## Explicit exclusions

- no `n=1000` execution;
- no controller calibration;
- no congestion or background-traffic claim;
- no correction of `sim.py` or paper wording inside this audit;
- no commit or push.
