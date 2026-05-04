# Resource Efficiency: Speedup vs. Total QP Cost — 2026-04-29

This folder re-analyzes the Stage 2 (static + adaptive) and Stage 3 (Ring
All-Reduce) experiments without running new simulations. The new metric is
total QP cost across the ring (`total_qps = P * k`, or `P * k_mean` for the
adaptive controller). The point is to make the trade-off between speedup and
queue-pair consumption visible, in line with the meeting reframe toward
resource efficiency.

## Notation

| Symbol | Meaning |
|---|---|
| **P**            | Number of workers in the ring (`ring_size` in CSV) |
| **k**            | Parallel RDMA flows per ring edge — the multi-flow parameter; k=1 is the baseline (`flows_per_neighbor` in CSV) |
| **TOPO_K**       | Fat-Tree radix (port count per switch); 16 in all experiments |
| **B\***          | Bottleneck bandwidth: slowest ring edge's aggregate throughput |
| **T**            | Ring completion time |
| **affected_fraction** | Fraction of `agg_core` and `edge_agg` links subjected to bursty congestion (NOT a per-link utilization) |
| **5-tuple**      | `(src, dst, sport, dport, proto)`. ECMP hashes this to choose one path per flow |
| **QP**           | RDMA Queue Pair. One flow ≈ one QP |
| **k_mean / k_max** | Adaptive only: per-edge mean / heaviest k at end of run, across the P ring edges (`final_k_mean`, `final_k_max` in CSV) |
| **total_qps**    | Sum of per-edge final k values across the ring = P × `k_mean` |
| **Speedup**      | `T(k=1)_mean / T(k)_mean` at the same `(P, congestion)` cell (ratio of means, not mean of ratios) |

## Topology and the meaning of P=16

`TOPO_K=16` builds a 1024-host Fat-Tree (64 hosts/pod, 8 hosts per ToR).
The simulator's ECMP path enumeration returns:

| Source/destination relation | ECMP paths | Multi-flow can help? |
|---|---|---|
| Same ToR (edge switch)      | 1            | No — single host–edge–host hop |
| Same pod, different edge    | 8            | Yes (8 aggregation switches) |
| Different pods              | 64 = 8 × 8   | Yes (most diversity, classic case) |

`build_worker_ring(start_index=0)` selects the first P consecutive hosts.
For our chosen ring sizes:

| P  | Intra-ToR ring edges | Intra-pod cross-edge | Cross-pod | Multi-flow benefit |
|----|----------------------|----------------------|-----------|--------------------|
| 4  | 4 / 4                | 0                    | 0         | None — all single-path |
| 8  | 8 / 8                | 0                    | 0         | None — fits in one ToR |
| **16** | 14 / 16          | **2 / 16**           | 0         | Benefit on the 2 cross-edge links |
| 32 | 28 / 32              | 4 / 32               | 0         | Same shape, more variance |

So **P=16 is the smallest size where multi-flow has any effect at all**, and
the benefit comes from raising B\* on the two cross-edge intra-pod ring
links via the pod's 8 aggregation switches. The classic cross-pod story
(64-way ECMP across pods) is **not** what these experiments demonstrate
yet — that requires P > 64 in this topology and is on the long-term roadmap.

## Methodology note (read first)

The plots in this folder are **scatter plots of two metrics** (speedup on
the y-axis, total QPs on the x-axis). They are **not a Pareto frontier in
the formal sense** — we did not compute the non-dominated subset of points.
Every (k, congestion) data point we collected is shown, including dominated
ones. When the term "Pareto" appears in earlier drafts, it was informal
shorthand; this README uses "trade-off scatter" or "speedup-vs-QP-cost
plot" to be precise.

A second methodology note: each cell `(P, k, congestion)` is averaged over
3 seeds. With the on/off Markov congestion model, that is a noisy estimate.
We have not yet computed confidence intervals.

## Plots

- `tradeoff_static_speedup_vs_qps.png` — for static multi-flow at P=16,
  speedup vs. total QPs, one line per congestion level. The shape is the
  classic diminishing-returns curve: most of the gain (1.00× to 1.39×) at
  50% congestion comes from k=1 to k=4; doubling k again to k=8 buys only
  a modest extra speedup (1.39× to 1.64×) for double the QP cost.

- `tradeoff_adaptive_vs_static.png` — direct comparison of baseline (k=1),
  static k=4, and the adaptive controller, all at P=16. Each method is
  plotted at every congestion level. The adaptive controller's points sit
  to the left of static k=4's points at the same y-value, meaning fewer
  QPs for the same speedup. This is the strongest visual argument for the
  resource-efficiency framing.

- `tradeoff_allreduce_speedup_vs_qps.png` — same plot type, but for the
  full pipelined Ring All-Reduce. Speedup numbers are smaller than the
  simple ring (pipelining creates concurrent contention from our own
  flows), but the curve shape is similar.

## Headline numbers (with seed-to-seed range)

At P=16, 50% targeted congestion, **n=3 seeds**. Speedup is computed per-seed
(each seed compared to its own baseline run) and then averaged. The "range"
column is the min-to-max across the 3 per-seed speedups — a direct view of
how stable the multi-flow benefit is to which congestion realization happens.

| Method                | Total QPs       | k_mean      | k_max | Time (ms, mean) | Time range (ms) | Speedup (mean) | Speedup range |
|-----------------------|-----------------|-------------|-------|-----------------|-----------------|----------------|---------------|
| Baseline (k=1)        | 16              | 1.00        | 1.00  | 58.4            | 38.3..76.2      | 1.00×          | 1.00..1.00    |
| Static k=4            | 64              | 4.00        | 4.00  | 38.3            | 35.6..40.7      | 1.54×          | 0.99..2.14    |
| **Adaptive (k_max≤4)** | **20.3 ± 2.1** | **1.27 ± 0.13** | 3.67 | **38.2**     | 30.1..48.5      | **1.55×**      | **1.25..2.11** |

Three things to read from this table:

1. **The 3.15× resource saving is robust.** `total_qps` for adaptive is 20.3 ± 2.1 (CV ≈ 10%); static k=4 is fixed at 64 by construction. The ratio sits between 64/22.4 ≈ 2.86× and 64/18.2 ≈ 3.52×. Stable.

2. **The adaptive controller is *more consistent* than static k=4** under heavy congestion. Static k=4's per-seed speedup spans 0.99..2.14 — one of the 3 seeds saw essentially no improvement over baseline. Adaptive's per-seed speedup spans 1.25..2.11 — every single seed got at least a 1.25× improvement. This is a previously-hidden positive result for the adaptive controller, not just resource saving but also tail-of-distribution robustness.

3. **The point speedup numbers are themselves noisy** because at 50% congestion the baseline (k=1) varies a lot across seeds (38..76 ms). Per-seed pairing reduces but does not eliminate this variance. With n=3 seeds, "1.54×" is best read as "around 1.5×, almost certainly between 1.0× and 2.2×".

The mechanism behind the resource saving: only a few edges (the ones whose ECMP path actually crosses a congested switch) get promoted close to k=4; the rest stay near k=1. The heaviest edge under the adaptive controller (k_max=3.67) is almost as heavily loaded as static k=4, but the *average* edge sits at k_mean=1.27. The win comes from the light edges, not from making the bottleneck edge cheaper.

See `efficiency_summary.csv` for the full table including std and min/max columns for every cell.

## Reading the plots

The plots in this folder show **error bars** at every data point:

- **Vertical bars** = the speedup range (min to max) observed across the 3 seeds at that cell, with per-seed pairing (each seed's k>1 run is compared to that same seed's baseline).
- **Horizontal bars on `tradeoff_adaptive_vs_static.png`** = the std of `total_qps` across seeds (only meaningful for the adaptive method, which has variable QP allocation; static and baseline have fixed QP counts by construction).
- **Tight bars** mean the multi-flow benefit was consistent across seeds.
- **Wide bars** mean the benefit was sensitive to which congestion realization happened — more seeds would tighten this.

The point on each marker is the **mean across the 3 seeds**. The trend — multi-flow points to the left of static k=4 at the same y-value — is **directionally robust** in every individual seed, even where bars are wide.

## Why bars are wide at heavy congestion

At 50% `affected_fraction`, the on/off Markov congestion process happens to give very different congestion patterns across seeds. One seed might see most congestion bursts hit the 2 cross-edge ring links (severe slowdown); another might see them on irrelevant links (no slowdown at all). With n=3, this lottery dominates seed-to-seed variation. A re-run with n=10 fixed seeds would tighten the bars proportionally to √(10/3) ≈ 1.8×.

## Comparability caveats

- The static-experiment baseline (k=1 at 50% congestion) is 44.1 ms; the
  adaptive-experiment baseline at the same setting is 58.4 ms. The two
  numbers come from different seeds. Within each experiment file, methods
  are directly comparable; across files they are not.
- The "3.15×" comparison above uses static k=4 and adaptive both from the
  same file (the adaptive CSV), so the comparison is internally consistent.

## How to reproduce

```
python analyze_efficiency.py
```

The script reads:
- `results/v2.0_multiflow_2026-04-11/static/results.csv`
- `results/v2.0_multiflow_2026-04-13/adaptive/results.csv`
- `results/v3.0_allreduce_2026-04-13/multiflow/results.csv`

and writes to `results/v4.0_efficiency_2026-04-29/`.
