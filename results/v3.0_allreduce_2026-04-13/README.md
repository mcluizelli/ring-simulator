# All-Reduce Results - v3.0

**Date:** 2026-04-13
**Branch:** ibrahim-paper

## Purpose

Evaluate multi-flow on the full pipelined Ring All-Reduce algorithm
(2(P-1) steps: Reduce-Scatter + All-Gather), which is the actual
communication pattern used in NCCL/Horovod for distributed ML training.

## Validation (validation/)

**Script:** `validate_allreduce.py`

Verified: T_allreduce = 2(P-1) * (M/P) / B* against simulation.
Non-pipelined, no congestion, alpha=0.

| P  | M       | Steps | Sim (s)   | Theo (s)  | Ratio  |
|----|---------|-------|-----------|-----------|--------|
| 4  | 256 MiB | 6     | 0.032400  | 0.032212  | 1.0058 |
| 8  | 256 MiB | 14    | 0.037800  | 0.037581  | 1.0058 |
| 16 | 256 MiB | 30    | 0.040500  | 0.040265  | 1.0058 |

**Mean ratio: 1.0182 +/- 0.018** (error from dt discretization across steps).

## Multi-Flow All-Reduce (multiflow/)

**Script:** `experiment_allreduce_multiflow.py`

Pipelined All-Reduce (pipeline_window=4) with targeted core/agg congestion.
Swept k=[1,2,4,8] x P=[8,16] x congestion=[0%,30%,50%], 3 seeds.

Key results (P=16):

| Congestion | k=1     | k=2     | k=4     | k=8     | Speedup |
|------------|---------|---------|---------|---------|---------|
| 0%         | 0.0405  | 0.0405  | 0.0405  | 0.0405  | 1.00x   |
| 30%        | 0.0550  | 0.0471  | 0.0455  | 0.0446  | 1.23x   |
| 50%        | 0.0629  | 0.0487  | 0.0461  | 0.0450  | 1.40x   |

**Findings:**
- Multi-flow provides up to **1.40x speedup** on pipelined All-Reduce
- The pipelining smooths per-step variation but the overall bottleneck
  (B*) still determines completion time
- P=8 shows no effect because with few ring edges, all ECMP paths
  are clean (ring doesn't span enough pods to hit congested links)

## Background Traffic (background/)

**Script:** `experiment_allreduce_background.py`

Tested with BackgroundTrafficGenerator (200-1000 flows/sec, lognormal sizes).

| Rate (fps) | k=1 (s) | k=4 (s) | Speedup |
|------------|---------|---------|---------|
| 0          | 0.0405  | 0.0405  | 1.00x   |
| 200        | 0.0405  | 0.0405  | 1.00x   |
| 500        | 0.0405  | 0.0405  | 1.00x   |
| 1000       | 0.0414  | 0.0409  | 1.01x   |

**Finding:** Background traffic at these rates barely affects a k=16
Fat-Tree (2048 hosts, enormous aggregate capacity). The CongestionModel
approach (targeted core/agg congestion) is more effective at creating
the concentrated contention scenarios where multi-flow helps. Real-world
congestion hotspots occur under oversubscription or when many jobs share
the same core switches — the CongestionModel captures this.

## Files

```
validation/
  results.csv
  allreduce_theoretical_vs_simulated.png
multiflow/
  results.csv
  allreduce_completion_vs_k.png    - completion time vs k per congestion
  allreduce_step_times.png         - mean vs P99 step time
  allreduce_vs_simple.png          - speedup comparison: AR vs simple transfer
background/
  results.csv
  background_effect.png            - completion time vs arrival rate
  step_time_cdf.png                - step time distribution
```
