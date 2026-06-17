"""
v5.0 — Parallel large-n re-run of static / adaptive / allreduce experiments.

Outputs to: results/v5.0_n{N}_{TODAY}/
    static/results.csv
    adaptive/results.csv
    allreduce/results.csv

Usage:
    python run_v5_parallel.py --n 1000 --workers 10 [--exp static|adaptive|allreduce|all]

Streams rows to CSV with checkpointing every 500 runs so a crash never loses
more than a few minutes of work.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import os
import sys
import time
from datetime import date
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Avoid numpy/openblas threading collision with multiprocessing.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")


def _lower_priority():
    """Drop process priority so the run doesn't choke the desktop.

    Fixed: previously the ctypes call silently failed on 64-bit Python because
    GetCurrentProcess's return type defaulted to int (truncating the HANDLE
    pseudo-value). We now declare argtypes/restype explicitly via wintypes.
    """
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel32.SetPriorityClass.restype = wintypes.BOOL
            BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
            ok = kernel32.SetPriorityClass(
                kernel32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS
            )
            if not ok:
                err = ctypes.get_last_error()
                print(f"[priority] WARNING: SetPriorityClass failed (err={err})", flush=True)
        else:
            os.nice(10)
    except Exception as e:
        print(f"[priority] WARNING: {e}", flush=True)


def _set_wakelock():
    """Prevent the system from going to sleep while the run is in progress.
    On Windows uses SetThreadExecutionState. On Linux/macOS this is a no-op
    (suspend timers there typically respect process activity)."""
    if sys.platform == "win32":
        try:
            import ctypes
            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            ES_AWAYMODE_REQUIRED = 0x00000040
            # Keep system awake but allow display to sleep.
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
            )
            print("[wakelock] system sleep disabled for the duration of this run", flush=True)
        except Exception as e:
            print(f"[wakelock] WARNING: failed to set wakelock — {e}", flush=True)


def _release_wakelock():
    if sys.platform == "win32":
        try:
            import ctypes
            ES_CONTINUOUS = 0x80000000
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        except Exception:
            pass


def _worker_init():
    _lower_priority()

import numpy as np  # noqa: E402

# --- bootstrap: make the simulator core (../sim.py) importable from this subfolder ---
import sys as _sys
from pathlib import Path as _BootPath
_RING_ROOT = _BootPath(__file__).resolve().parents[1]
if str(_RING_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_RING_ROOT))
# ------------------------------------------------------------------------------------
from sim import (  # noqa: E402
    FatTree,
    CongestionModel,
    AdaptiveConfig,
    build_worker_ring,
    run_simple_ring_transfer,
    run_adaptive_ring_transfer,
    run_ring_allreduce,
)

# ─── Common config ──────────────────────────────────────────────────
TOPO_K = 16
LINK_GBPS = 100.0
DT_S = 5e-5
BYTES_PER_NEIGHBOR = 256 * 1024 * 1024  # 256 MiB

CONG_PARAMS = dict(
    congested_util_low=0.50, congested_util_high=0.95,
    normal_util_low=0.00, normal_util_high=0.05,
    p_on=0.01, p_off=0.005,
    target_layers=["agg_core", "edge_agg"],
)

# Static sweep — same scope as v2.0 to allow direct comparison
STATIC_K_VALUES = [1, 2, 4, 8]
STATIC_RING_SIZES = [4, 8, 16, 32]
STATIC_FRACTIONS = [0.0, 0.1, 0.3, 0.5]

# Adaptive sweep — match experiment_adaptive.py defaults
ADAPTIVE_RING_SIZES = [8, 16]
ADAPTIVE_FRACTIONS = [0.0, 0.1, 0.3, 0.5]
ADAPTIVE_STATIC_K = 4

# AllReduce sweep — match experiment_allreduce_multiflow.py
ALLREDUCE_K_VALUES = [1, 2, 4, 8]
ALLREDUCE_RING_SIZES = [8, 16]
ALLREDUCE_FRACTIONS = [0.0, 0.3, 0.5]
ALLREDUCE_BYTES = 256 * 1024 * 1024
ALLREDUCE_PIPELINE_WINDOW = 4

# Light-mode overrides — applied when --light is passed.
LIGHT_STATIC_K_VALUES = [1, 2, 4]
LIGHT_STATIC_RING_SIZES = [8, 16]
LIGHT_STATIC_FRACTIONS = [0.0, 0.3, 0.5]
LIGHT_ADAPTIVE_RING_SIZES = [16]
LIGHT_ADAPTIVE_FRACTIONS = [0.3, 0.5]
LIGHT_ALLREDUCE_K_VALUES = [1, 2, 4]
LIGHT_ALLREDUCE_RING_SIZES = [16]
LIGHT_ALLREDUCE_FRACTIONS = [0.3, 0.5]

# Cross-pod (full) overrides — applied when --cross-pod is passed.
# Adds P=64 (cross-pod regime in TOPO_K=16) to the sweep.
CROSS_STATIC_K_VALUES = [1, 2, 4, 8]
CROSS_STATIC_RING_SIZES = [4, 8, 16, 32, 64]
CROSS_STATIC_FRACTIONS = [0.0, 0.1, 0.3, 0.5]
CROSS_ADAPTIVE_RING_SIZES = [16, 32]
CROSS_ADAPTIVE_FRACTIONS = [0.0, 0.1, 0.3, 0.5]
CROSS_ALLREDUCE_K_VALUES = [1, 2, 4, 8]
CROSS_ALLREDUCE_RING_SIZES = [16]
CROSS_ALLREDUCE_FRACTIONS = [0.0, 0.3, 0.5]


def make_congestion(frac: float, seed: int):
    if frac <= 0.0:
        return None
    return CongestionModel(mode="onoff", seed=seed, affected_fraction=frac, **CONG_PARAMS)


# ─── Workers ────────────────────────────────────────────────────────

def _static_worker(args: Tuple[int, int, int, float, int]) -> Dict[str, Any]:
    run_idx, k_val, ring_size, frac, base_seed = args
    seed = base_seed + run_idx * 10_000_001
    topo = FatTree(k=TOPO_K, link_capacity_Gbps=LINK_GBPS, seed=seed)
    ring = build_worker_ring(topo.hosts, worker_count=ring_size, start_index=0)
    cong = make_congestion(frac, seed + int(frac * 1000))
    t = run_simple_ring_transfer(
        topo=topo, ring=ring, bytes_per_neighbor=BYTES_PER_NEIGHBOR,
        flows_per_neighbor=k_val, dt_s=DT_S, congestion=cong,
    )
    return {
        "run": run_idx + 1,
        "seed": seed,
        "flows_per_neighbor": k_val,
        "ring_size": ring_size,
        "affected_fraction": frac,
        "completion_time_s": t,
    }


def _adaptive_worker(args: Tuple[int, int, float, int]) -> Dict[str, Any]:
    run_idx, ring_size, frac, base_seed = args
    seed = base_seed + run_idx * 10_000_001
    topo = FatTree(k=TOPO_K, link_capacity_Gbps=LINK_GBPS, seed=seed)
    ring = build_worker_ring(topo.hosts, worker_count=ring_size, start_index=0)
    cong = make_congestion(frac, seed + int(frac * 1000))
    cfg = AdaptiveConfig(measurement_window_s=0.001, threshold=0.2,
                         k_max=4, cooldown_ticks=200)
    result = run_adaptive_ring_transfer(
        topo=topo, ring=ring, bytes_per_neighbor=BYTES_PER_NEIGHBOR,
        adaptive_cfg=cfg, dt_s=DT_S, congestion=cong,
    )
    k_values = list(result["final_k_per_edge"].values())
    return {
        "run": run_idx + 1, "seed": seed, "ring_size": ring_size,
        "affected_fraction": frac, "method": "adaptive",
        "completion_time_s": result["completion_time_s"],
        "final_k_mean": float(np.mean(k_values)),
        "final_k_max": int(max(k_values)),
    }


def _adaptive_static_worker(args: Tuple[int, int, float, int, int]) -> Dict[str, Any]:
    run_idx, ring_size, frac, base_seed, k_static = args
    seed = base_seed + run_idx * 10_000_001
    topo = FatTree(k=TOPO_K, link_capacity_Gbps=LINK_GBPS, seed=seed)
    ring = build_worker_ring(topo.hosts, worker_count=ring_size, start_index=0)
    cong = make_congestion(frac, seed + int(frac * 1000))
    t = run_simple_ring_transfer(
        topo=topo, ring=ring, bytes_per_neighbor=BYTES_PER_NEIGHBOR,
        flows_per_neighbor=k_static, dt_s=DT_S, congestion=cong,
    )
    method = "baseline" if k_static == 1 else f"static(k={k_static})"
    return {
        "run": run_idx + 1, "seed": seed, "ring_size": ring_size,
        "affected_fraction": frac, "method": method,
        "completion_time_s": t,
        "final_k_mean": float(k_static), "final_k_max": int(k_static),
    }


def _allreduce_worker(args: Tuple[int, int, int, float, int]) -> Dict[str, Any]:
    run_idx, k_val, ring_size, frac, base_seed = args
    seed = base_seed + run_idx * 10_000_001
    topo = FatTree(k=TOPO_K, link_capacity_Gbps=LINK_GBPS, seed=seed)
    ring = build_worker_ring(topo.hosts, worker_count=ring_size, start_index=0)
    cong = make_congestion(frac, seed + int(frac * 1000))
    ar = run_ring_allreduce(
        topo=topo, ring=ring, total_bytes_M=ALLREDUCE_BYTES,
        flows_per_neighbor=k_val, dt_s=DT_S,
        pipelined=True, pipeline_window=ALLREDUCE_PIPELINE_WINDOW,
        alpha_s=0.0, congestion=cong,
    )
    cong2 = make_congestion(frac, seed + int(frac * 1000))
    t_simple = run_simple_ring_transfer(
        topo=topo, ring=ring, bytes_per_neighbor=ALLREDUCE_BYTES,
        flows_per_neighbor=k_val, dt_s=DT_S, congestion=cong2,
    )
    return {
        "run": run_idx + 1, "seed": seed,
        "flows_per_neighbor": k_val, "ring_size": ring_size,
        "msg_bytes": ALLREDUCE_BYTES, "affected_fraction": frac,
        "allreduce_time_s": ar.total_time_s,
        "simple_transfer_time_s": t_simple,
        "mean_step_s": float(np.mean(ar.step_times_s)),
        "std_step_s": float(np.std(ar.step_times_s)),
        "max_step_s": float(max(ar.step_times_s)),
        "p99_step_s": float(np.percentile(ar.step_times_s, 99)),
        "total_steps": len(ar.step_times_s),
    }


# ─── Streaming runner with checkpointing ────────────────────────────

def run_pool(name: str, worker_fn, tasks, fieldnames, out_csv: Path,
             workers: int, checkpoint_every: int = 500):
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    total = len(tasks)
    print(f"\n[{name}] starting {total:,} tasks on {workers} workers — output: {out_csv}",
          flush=True)
    written = 0
    t_start = time.perf_counter()
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        f.flush()
        with Pool(workers, initializer=_worker_init) as pool:
            for row in pool.imap_unordered(worker_fn, tasks, chunksize=8):
                w.writerow(row)
                written += 1
                if written % checkpoint_every == 0:
                    f.flush()
                    elapsed = time.perf_counter() - t_start
                    rate = written / elapsed
                    eta = (total - written) / max(rate, 1e-9)
                    print(f"[{name}] {written:,}/{total:,}  "
                          f"({100*written/total:.1f}%)  "
                          f"rate={rate:.1f}/s  eta={eta/60:.1f} min", flush=True)
    elapsed = time.perf_counter() - t_start
    print(f"[{name}] DONE in {elapsed/60:.1f} min — wrote {written:,} rows", flush=True)


# ─── Experiment orchestration ───────────────────────────────────────

def run_static(n: int, out_dir: Path, workers: int):
    base_seed = 0xBEEF
    combos = list(itertools.product(STATIC_K_VALUES, STATIC_RING_SIZES, STATIC_FRACTIONS))
    tasks = [(run_idx, k, P, frac, base_seed)
             for run_idx in range(n)
             for k, P, frac in combos]
    fieldnames = ["run", "seed", "flows_per_neighbor", "ring_size",
                  "affected_fraction", "completion_time_s"]
    run_pool("static", _static_worker, tasks, fieldnames,
             out_dir / "static" / "results.csv", workers)


def run_adaptive(n: int, out_dir: Path, workers: int):
    base_seed = 0xCAFE
    fieldnames = ["run", "seed", "ring_size", "affected_fraction", "method",
                  "completion_time_s", "final_k_mean", "final_k_max"]
    out_csv = out_dir / "adaptive" / "results.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    print(f"\n[adaptive] streaming combined adaptive+baseline+static(k=4) to {out_csv}",
          flush=True)

    tasks_adaptive = [(run_idx, P, frac, base_seed)
                      for run_idx in range(n)
                      for P, frac in itertools.product(ADAPTIVE_RING_SIZES, ADAPTIVE_FRACTIONS)]
    tasks_baseline = [(run_idx, P, frac, base_seed, 1)
                      for run_idx in range(n)
                      for P, frac in itertools.product(ADAPTIVE_RING_SIZES, ADAPTIVE_FRACTIONS)]
    tasks_static = [(run_idx, P, frac, base_seed, ADAPTIVE_STATIC_K)
                    for run_idx in range(n)
                    for P, frac in itertools.product(ADAPTIVE_RING_SIZES, ADAPTIVE_FRACTIONS)]
    total = len(tasks_adaptive) + len(tasks_baseline) + len(tasks_static)
    written = 0
    t_start = time.perf_counter()

    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        f.flush()
        with Pool(workers, initializer=_worker_init) as pool:
            for batch_name, fn, tasks in [
                ("adaptive", _adaptive_worker, tasks_adaptive),
                ("baseline", _adaptive_static_worker, tasks_baseline),
                (f"static(k={ADAPTIVE_STATIC_K})", _adaptive_static_worker, tasks_static),
            ]:
                print(f"[adaptive] batch={batch_name}: {len(tasks):,} tasks", flush=True)
                for row in pool.imap_unordered(fn, tasks, chunksize=8):
                    w.writerow(row)
                    written += 1
                    if written % 500 == 0:
                        f.flush()
                        elapsed = time.perf_counter() - t_start
                        rate = written / elapsed
                        eta = (total - written) / max(rate, 1e-9)
                        print(f"[adaptive] {written:,}/{total:,}  "
                              f"({100*written/total:.1f}%)  "
                              f"rate={rate:.1f}/s  eta={eta/60:.1f} min", flush=True)
    print(f"[adaptive] DONE in {(time.perf_counter()-t_start)/60:.1f} min — "
          f"wrote {written:,} rows", flush=True)


def run_allreduce(n: int, out_dir: Path, workers: int):
    base_seed = 0xFACE
    combos = list(itertools.product(ALLREDUCE_K_VALUES, ALLREDUCE_RING_SIZES, ALLREDUCE_FRACTIONS))
    tasks = [(run_idx, k, P, frac, base_seed)
             for run_idx in range(n)
             for k, P, frac in combos]
    fieldnames = ["run", "seed", "flows_per_neighbor", "ring_size", "msg_bytes",
                  "affected_fraction", "allreduce_time_s", "simple_transfer_time_s",
                  "mean_step_s", "std_step_s", "max_step_s", "p99_step_s", "total_steps"]
    run_pool("allreduce", _allreduce_worker, tasks, fieldnames,
             out_dir / "allreduce" / "results.csv", workers)


# ─── Main ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=1000, help="seeds per cell")
    parser.add_argument("--workers", type=int, default=max(cpu_count() - 2, 1))
    parser.add_argument("--exp", choices=["static", "adaptive", "allreduce", "all"],
                        default="all")
    parser.add_argument("--out-tag", default=None)
    parser.add_argument("--light", action="store_true",
                        help="reduced sweep scope (skip P=32, k=8, intermediate congestions)")
    parser.add_argument("--cross-pod", action="store_true",
                        help="extended sweep including P=64 cross-pod, all k, all congestions")
    parser.add_argument("--no-wakelock", action="store_true",
                        help="disable Windows sleep prevention")
    args = parser.parse_args()

    global STATIC_K_VALUES, STATIC_RING_SIZES, STATIC_FRACTIONS
    global ADAPTIVE_RING_SIZES, ADAPTIVE_FRACTIONS
    global ALLREDUCE_K_VALUES, ALLREDUCE_RING_SIZES, ALLREDUCE_FRACTIONS

    if args.light:
        STATIC_K_VALUES = LIGHT_STATIC_K_VALUES
        STATIC_RING_SIZES = LIGHT_STATIC_RING_SIZES
        STATIC_FRACTIONS = LIGHT_STATIC_FRACTIONS
        ADAPTIVE_RING_SIZES = LIGHT_ADAPTIVE_RING_SIZES
        ADAPTIVE_FRACTIONS = LIGHT_ADAPTIVE_FRACTIONS
        ALLREDUCE_K_VALUES = LIGHT_ALLREDUCE_K_VALUES
        ALLREDUCE_RING_SIZES = LIGHT_ALLREDUCE_RING_SIZES
        ALLREDUCE_FRACTIONS = LIGHT_ALLREDUCE_FRACTIONS
    elif args.cross_pod:
        STATIC_K_VALUES = CROSS_STATIC_K_VALUES
        STATIC_RING_SIZES = CROSS_STATIC_RING_SIZES
        STATIC_FRACTIONS = CROSS_STATIC_FRACTIONS
        ADAPTIVE_RING_SIZES = CROSS_ADAPTIVE_RING_SIZES
        ADAPTIVE_FRACTIONS = CROSS_ADAPTIVE_FRACTIONS
        ALLREDUCE_K_VALUES = CROSS_ALLREDUCE_K_VALUES
        ALLREDUCE_RING_SIZES = CROSS_ALLREDUCE_RING_SIZES
        ALLREDUCE_FRACTIONS = CROSS_ALLREDUCE_FRACTIONS

    # Drop priority of the parent (workers inherit + reapply via _worker_init).
    _lower_priority()
    if not args.no_wakelock:
        _set_wakelock()
    import atexit
    atexit.register(_release_wakelock)

    today = date.today().isoformat()
    if args.light:
        suffix = "light_"
    elif args.cross_pod:
        suffix = "crosspod_"
    else:
        suffix = ""
    tag = args.out_tag or f"v5.1_{suffix}n{args.n}_{today}"
    out_dir = (_RING_ROOT / "results") / tag
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== v5.0 parallel run ===")
    print(f"Date:    {today}")
    print(f"n:       {args.n}")
    print(f"workers: {args.workers}")
    print(f"mode:    {'LIGHT (reduced scope)' if args.light else 'FULL'}")
    print(f"out:     {out_dir}")
    print(f"exp:     {args.exp}")
    print(f"static:  k={STATIC_K_VALUES} P={STATIC_RING_SIZES} cong={STATIC_FRACTIONS}")
    print(f"adapt:   P={ADAPTIVE_RING_SIZES} cong={ADAPTIVE_FRACTIONS}")
    print(f"allred:  k={ALLREDUCE_K_VALUES} P={ALLREDUCE_RING_SIZES} cong={ALLREDUCE_FRACTIONS}")
    print(flush=True)

    t_global = time.perf_counter()
    if args.exp in ("static", "all"):
        run_static(args.n, out_dir, args.workers)
    if args.exp in ("adaptive", "all"):
        run_adaptive(args.n, out_dir, args.workers)
    if args.exp in ("allreduce", "all"):
        run_allreduce(args.n, out_dir, args.workers)

    print(f"\n=== ALL DONE in {(time.perf_counter()-t_global)/60:.1f} min ===")


if __name__ == "__main__":
    main()
