"""
Parallel driver for the D.6 congestion-models sweep.

Identical methodology to experiments/experiment_congestion_models.py — same models, params,
seeds, per-seed pairing and analysis — but distributes the independent
(model, seed) units across a process pool. Because every cell is deterministic
in (model, seed, k), the output is bit-for-bit identical to the serial run; only
the wall-clock time differs.

Usage:
    python experiments/run_congestion_parallel.py [n_seeds] [n_workers]   # defaults: 100, 10
"""
from __future__ import annotations

import multiprocessing as mp
import os
import sys

# Reuse the single source of truth for params + analysis from the serial script.
# --- bootstrap: make the simulator core (../sim.py) importable from this subfolder ---
import sys as _sys
from pathlib import Path as _BootPath
_RING_ROOT = _BootPath(__file__).resolve().parents[1]
if str(_RING_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_RING_ROOT))
# ------------------------------------------------------------------------------------
import random

from experiment_congestion_models import (
    AFFECTED_FRACTION, BYTES_PER_NEIGHBOR, DT_S, LINK_GBPS, MODELS, OUT_DIR,
    PLACEMENT, RING_SIZE, SEED_BASE, SWEEP_K, TOPO_K, analyze, make_congestion,
    plot_speedup, print_summary, save_csv,
)
from sim import FatTree, build_worker_ring, run_simple_ring_transfer

# Per-worker global (built once per process; the topology is deterministic).
# The RING is NOT a global: placement varies per seed, exactly as in the serial
# script, so it has to be rebuilt inside each (model, seed) unit.
_TOPO = None


def _init() -> None:
    global _TOPO
    _TOPO = FatTree(k=TOPO_K, link_capacity_Gbps=LINK_GBPS)


def _make_ring(seed: int):
    """Placement per seed — mirrors experiment_congestion_models.run_sweep."""
    if PLACEMENT == "contiguous":                       # old, buggy v6.1 behaviour
        return build_worker_ring(_TOPO.hosts, worker_count=RING_SIZE, start_index=0)
    return random.Random(SEED_BASE + seed).sample(_TOPO.hosts, RING_SIZE)


def _work(task):
    model, seed = task
    cong_seed = 1000 + seed   # same seed convention as the serial script
    ring = _make_ring(seed)   # same placement for every k -> valid per-seed pairing
    out = []
    for k in SWEEP_K:
        cong = make_congestion(model, cong_seed)
        t = run_simple_ring_transfer(
            topo=_TOPO, ring=ring, bytes_per_neighbor=BYTES_PER_NEIGHBOR,
            flows_per_neighbor=k, dt_s=DT_S, congestion=cong,
        )
        out.append({"model": model, "seed": seed, "k": k, "completion_time_s": t})
    return out


def main():
    n_seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    n_workers = int(sys.argv[2]) if len(sys.argv) > 2 else min(10, os.cpu_count() or 4)

    tasks = [(m, s) for m in MODELS for s in range(n_seeds)]
    print(f"D.6 parallel sweep: {list(MODELS)} × k={SWEEP_K} × {n_seeds} seeds "
          f"= {len(tasks)} (model,seed) units on {n_workers} workers "
          f"(P={RING_SIZE}, M={BYTES_PER_NEIGHBOR // (1024*1024)} MiB)\n")

    rows = []
    with mp.Pool(processes=n_workers, initializer=_init) as pool:
        for i, res in enumerate(pool.imap_unordered(_work, tasks), 1):
            rows.extend(res)
            if i % max(1, len(tasks) // 20) == 0 or i == len(tasks):
                print(f"  [{i}/{len(tasks)}] (model,seed) units done", flush=True)

    # Sort to a stable order so results.csv is reproducible regardless of
    # completion order (model order, then seed, then k).
    model_order = {m: i for i, m in enumerate(MODELS)}
    rows.sort(key=lambda r: (model_order[r["model"]], r["seed"], r["k"]))

    save_csv(rows, OUT_DIR / "results.csv",
             ["model", "seed", "k", "completion_time_s"])
    summary = analyze(rows)
    save_csv(summary, OUT_DIR / "summary.csv",
             ["model", "k", "n_seeds", "speedup_mean", "speedup_ci_low",
              "speedup_ci_high", "speedup_min", "speedup_max"])
    plot_speedup(summary, OUT_DIR / "speedup_by_model.png")
    print_summary(summary)


if __name__ == "__main__":
    main()
