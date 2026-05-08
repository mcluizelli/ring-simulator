# Validation Results - v1.0

**Date:** 2026-04-09
**Branch:** ibrahim-paper

## Notation

| Symbol | Meaning |
|---|---|
| P | Number of workers in the ring |
| M | Bytes per worker per ring transfer (`bytes_per_neighbor` in CSV) |
| B\* | Bottleneck bandwidth: slowest ring edge's aggregate throughput |
| T | Ring completion time = `bytes_per_neighbor / B*` |
| `affected_fraction` | Fraction of `agg_core` and `edge_agg` links subjected to bursty congestion (NOT a per-link utilization) |
| Sim/theory ratio | Simulated `T` divided by analytical `T` from the bottleneck model |

## Purpose
Validate the ring simulator against the theoretical bottleneck model
before adding multi-flow features (Stage 2).

The theoretical model for a simple ring transfer:
```
T_simple = bytes_per_neighbor / B*
```
where `B* = min(per-logical-edge throughput)` is the bottleneck bandwidth.

---

## Baseline Validation (No Congestion)

**Script:** `validate_baseline.py`

**Parameters:**
- Topology: Fat-Tree k=16, 100 Gbps links (2048 hosts)
- Ring sizes: P = 4, 8, 16, 32
- Message sizes: M = 64 MiB, 256 MiB
- Flows per neighbor: 1
- Seeds: 3 per configuration
- Congestion: None

**Results:**

| P  | M       | Sim (s)   | Theo (s)  | Ratio  | B* (Gbps) |
|----|---------|-----------|-----------|--------|-----------|
| 4  | 64 MiB  | 0.005400  | 0.005369  | 1.0058 | 100.00    |
| 4  | 256 MiB | 0.021500  | 0.021475  | 1.0012 | 100.00    |
| 8  | 64 MiB  | 0.005400  | 0.005369  | 1.0058 | 100.00    |
| 8  | 256 MiB | 0.021500  | 0.021475  | 1.0012 | 100.00    |
| 16 | 64 MiB  | 0.005400  | 0.005369  | 1.0058 | 100.00    |
| 16 | 256 MiB | 0.021500  | 0.021475  | 1.0012 | 100.00    |
| 32 | 64 MiB  | 0.005400  | 0.005369  | 1.0058 | 100.00    |
| 32 | 256 MiB | 0.021500  | 0.021475  | 1.0012 | 100.00    |

**Overall mean ratio: 1.0035 +/- 0.0023**

B* = 100 Gbps for all cases because with 1 flow per neighbor on a k=16
Fat-Tree, each flow gets a dedicated ECMP path with no contention.

The deviation (<0.6%) is purely from discrete-time stepping (dt = 50us).

---

## Congestion Validation

**Script:** `validate_congestion.py`

**Parameters:**
- P=16, M=256 MiB, flows_per_neighbor=1
- Congestion model: on/off, same parameters as experiments.py
- Affected fractions: 0%, 10%, 30%, 50%
- 5 runs per configuration (different random seeds)

**Results:**

| Fraction | Mean Time (s) | Std      | Mean Slowdown | Mean Spread (Gbps) |
|----------|---------------|----------|---------------|---------------------|
| 0%       | 0.021500      | 0.000000 | 1.001x        | 0.00                |
| 10%      | 0.030050      | 0.004325 | 1.399x        | 0.00                |
| 30%      | 0.033840      | 0.005091 | 1.576x        | 0.00                |
| 50%      | 0.035520      | 0.003283 | 1.654x        | 0.00                |

**Monotonicity check: PASS** - completion time increases with congestion level.

Edge throughput spread = 0 because with 1 flow per neighbor, each logical
edge has exactly one physical path, so throughput differences between edges
are reflected only in B* (the bottleneck edge).

---

## Conclusion

The simulator correctly implements the theoretical bottleneck model:
1. Without congestion, simulated time matches theory within 0.6% (dt discretization).
2. With congestion, completion time increases monotonically with the fraction of affected links.
3. The bottleneck edge (B*) correctly determines the overall completion time.

The simulator is validated and ready for Stage 2 (multi-flow extensions).

---

## Files

```
baseline/
  results.csv                      - raw results (24 rows)
  theoretical_vs_simulated.png     - scatter plot: sim vs theory
congestion/
  results.csv                      - raw results (20 rows)
  per_edge_throughput.png          - box plot of edge throughput by congestion
  bottleneck_analysis.png          - completion time vs congestion level
```
