# Multi-Flow Results - v2.0

**Date:** 2026-04-13 (updated from 2026-04-11 initial run)
**Branch:** ibrahim-paper

## Notation

| Symbol | Meaning |
|---|---|
| P | Number of workers in the ring (`ring_size` in CSV) |
| k | Parallel RDMA flows per ring edge — the multi-flow parameter; k=1 is the baseline |
| TOPO_K | Fat-Tree radix (port count per switch); 16 in all experiments |
| B\* | Bottleneck bandwidth: slowest ring edge's aggregate throughput |
| T | Ring completion time (`completion_time_s` in CSV) |
| `affected_fraction` | Fraction of `agg_core` and `edge_agg` links subjected to bursty congestion (NOT a per-link utilization) |
| `k_mean` / `k_max` | Adaptive only: per-edge mean / heaviest k at end of run, across the P ring edges (`final_k_mean`, `final_k_max` in CSV) |
| `total_qps` | Sum of per-edge final k values across the ring = P × `k_mean` |
| Speedup | `T(k=1)_mean / T(k)_mean` at the same `(P, congestion)` cell |

## Purpose

Evaluate multi-flow per ring edge as a mechanism to exploit ECMP path
diversity under congestion, and compare static vs adaptive flow allocation.

## Congestion Model

Congestion targets **agg-core and edge-agg links only** (where ECMP provides
alternative paths). Host-edge links are unaffected. Parameters:
- Utilization when congested: [0.50, 0.95]
- On/off dynamics: p_on=0.01, p_off=0.005
- Affected fractions tested: 0%, 10%, 30%, 50%

## Static Multi-Flow (static/)

**Script:** `experiment_static_multiflow.py`

Swept k=[1,2,4,8] x P=[4,8,16,32] x congestion=[0%,10%,30%,50%], 3 runs.

Key results (P=16):

| Congestion | k=1     | k=2     | k=4     | k=8     | Speedup |
|------------|---------|---------|---------|---------|---------|
| 0%         | 0.0215  | 0.0215  | 0.0215  | 0.0215  | 1.00x   |
| 10%        | 0.0339  | 0.0278  | 0.0236  | 0.0243  | 1.39x   |
| 30%        | 0.0550  | 0.0373  | 0.0362  | 0.0295  | 1.86x   |
| 50%        | 0.0441  | 0.0350  | 0.0317  | 0.0268  | 1.64x   |

**Finding:** Static multi-flow provides up to 1.86x speedup under congestion.
No effect without congestion.

## Adaptive Controller (adaptive/)

**Script:** `experiment_adaptive.py`

Three-way comparison: baseline (k=1), static (k=4), adaptive (k_max=4).
P=[8,16], 3 runs per config.

Key results (P=16):

| Congestion | Baseline | Static k=4 | Adaptive | Speedup |
|------------|----------|------------|----------|---------|
| 0%         | 0.0215   | 0.0215     | 0.0215   | 1.00x   |
| 10%        | 0.0303   | 0.0280     | 0.0247   | 1.22x   |
| 50%        | 0.0584   | 0.0383     | 0.0382   | 1.53x   |

**Findings:**
- Adaptive matches static performance with fewer total flows (k_avg=1.1-1.4)
- Selective allocation: only congested edges get extra flows
- No overhead without congestion (stays at k=1)

## Files

```
static/
  results.csv
  completion_vs_k.png         - 2x2 grid: completion time vs k per congestion
  heatmap_k_vs_congestion.png - speedup heatmap (P=16)
  speedup_bars.png            - grouped bars at 30% congestion
adaptive/
  results.csv
  comparison.png              - baseline vs static vs adaptive grouped bars
  k_distribution.png          - flow allocation by congestion level
```
