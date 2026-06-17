from __future__ import annotations

from dataclasses import dataclass
import os
from random import random
import time
from typing import List, Optional, Dict, Any, Tuple
import csv
import itertools

from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

# --- bootstrap: make the simulator core (../sim.py) importable from this subfolder ---
import sys as _sys
from pathlib import Path as _BootPath
_RING_ROOT = _BootPath(__file__).resolve().parents[1]
if str(_RING_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_RING_ROOT))
# ------------------------------------------------------------------------------------
from sim import (
    FatTree,
    CongestionModel,
    BackgroundTrafficConfig,
    run_simple_ring_transfer,
    build_worker_ring,
)


# ----------------------------
# Sweep configuration
# ----------------------------
RUNS=10

TOPO_K = 16
LINK_GBPS = 100.0
#SEED = 1

DT_S = 5e-5
BYTES_PER_NEIGHBOR = 256 * 1024 * 1024  # 64 MiB (smaller than 256 MiB for faster sweeps)
FLOWS_PER_NEIGHBOR = 1

# Ring sizes to test (must be <= number of hosts in the topology)
SWEEP_RING_SIZES = [4, 8, 16, 24, 32, 64]#, 48, 64, 96, 128, 192, 256]

# Congestion levels to test (fraction of links affected)
# 0.0 means "no congestion model" (baseline).
SWEEP_AFFECTED_FRACTIONS = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.4, 0.5, 0.6, 0.7, 0.8]

# Congestion intensity ranges (how much capacity is removed when congested)
CONGESTED_UTIL_LOW = 0.30
CONGESTED_UTIL_HIGH = 0.85
NORMAL_UTIL_LOW = 0.00
NORMAL_UTIL_HIGH = 0.05

# On/off dynamics (per tick probabilities)
P_ON = 0.003
P_OFF = 0.012

# Output
CSV_OUT = "results_ring_congestion.csv"


OUT_PNG = "ring_congestion_bars.png"


def _to_float(x: str) -> float:
    # Robust parsing if you later switch to comma decimals (e.g., "0,031234").
    x = str(x).strip()
    return float(x.replace(",", "."))


def load_results(csv_path: str) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    with open(csv_path, "r", newline="") as f:
        reader = csv.DictReader(f, delimiter=",")
        for r in reader:
            print(r)
            rows.append(
                {
                    "ring_size": int(r["ring_size"]),
                    "affected_fraction": _to_float(r["affected_fraction"]),
                    "completion_time_s": _to_float(r["completion_time_s"]),
                }
            )
    return rows


def mean_by_case(rows: List[Dict[str, object]]) -> Dict[Tuple[int, float], float]:
    acc: Dict[Tuple[int, float], List[float]] = {}
    for r in rows:
        key = (int(r["ring_size"]), float(r["affected_fraction"]))
        acc.setdefault(key, []).append(float(r["completion_time_s"]))

    return {k: float(np.mean(v)) for k, v in acc.items()}


def plot_grouped_bars(means: Dict[Tuple[int, float], float], out_png: str) -> None:
    ring_sizes = sorted({k[0] for k in means.keys()})
    fracs = sorted({k[1] for k in means.keys()})

    x = np.arange(len(ring_sizes))
    n = len(fracs)
    group_width = 0.85
    bar_w = group_width / max(n, 1)

    fig, ax = plt.subplots(figsize=(14, 7))

    for i, frac in enumerate(fracs):
        y = [means.get((rs, frac), np.nan) for rs in ring_sizes]
        ax.bar(x - group_width / 2 + (i + 0.5) * bar_w, y, width=bar_w, label=f"{frac:g}")

    ax.set_xticks(x)
    ax.set_xticklabels([str(rs) for rs in ring_sizes])
    ax.set_xlabel("Ring size")
    ax.set_ylabel("Completion time (s)")
    ax.legend(title="Network congestion (% of links)", ncols=1, frameon=False)
    ax.set_axisbelow(True)
    ax.grid(axis="y", linewidth=0.6, alpha=0.5)

    fig.tight_layout()
    fig.savefig(out_png, dpi=200)
    print(f"Saved: {out_png}")



def make_congestion(affected_fraction: float, seed: int) -> Optional[CongestionModel]:
    """Return a CongestionModel or None (for baseline)."""
    if affected_fraction <= 0.0:
        return None
    return CongestionModel(
        mode="onoff",
        seed=seed,
        affected_fraction=affected_fraction,
        congested_util_low=CONGESTED_UTIL_LOW,
        congested_util_high=CONGESTED_UTIL_HIGH,
        normal_util_low=NORMAL_UTIL_LOW,
        normal_util_high=NORMAL_UTIL_HIGH,
        p_on=P_ON,
        p_off=P_OFF,
    )


def run_one_case(topo: FatTree, ring_size: int, affected_fraction: float, seed: int) -> Dict[str, Any]:
    ring = build_worker_ring(topo.hosts, worker_count=ring_size, start_index=0)
    cong = make_congestion(affected_fraction, seed=seed)

    t = run_simple_ring_transfer(
        topo=topo,
        ring=ring,
        bytes_per_neighbor=BYTES_PER_NEIGHBOR,
        flows_per_neighbor=FLOWS_PER_NEIGHBOR,
        dt_s=DT_S,
        congestion=cong,
        background_cfg=None,
    )

    return {
        "k": TOPO_K,
        "link_gbps": LINK_GBPS,
        "dt_s": DT_S,
        "bytes_per_neighbor": BYTES_PER_NEIGHBOR,
        "flows_per_neighbor": FLOWS_PER_NEIGHBOR,
        "ring_size": ring_size,
        "affected_fraction": affected_fraction,
        "completion_time_s": t,
    }

def format_row(row):
    formatted = {}
    for k, v in row.items():
        if isinstance(v, float):
            formatted[k] = f"{v:.6f}".replace(".", ",")
        else:
            formatted[k] = v
    return formatted

def main() -> None:

    
    for it in range(RUNS):
        seed=time.time_ns()
        topo = FatTree(k=TOPO_K, link_capacity_Gbps=LINK_GBPS, seed=seed)

        # Validate ring sizes
        max_workers = len(topo.hosts)
        for rs in SWEEP_RING_SIZES:
            if rs > max_workers:
                raise ValueError(f"ring_size={rs} exceeds available hosts ({max_workers}).")

        rows: List[Dict[str, Any]] = []
        for ring_size, frac in itertools.product(SWEEP_RING_SIZES, SWEEP_AFFECTED_FRACTIONS):
            print(f"Running ring_size={ring_size}, affected_fraction={frac} ...")
            row = run_one_case(topo, ring_size, frac,seed)
            rows.append(row)
            print(f"  completion_time_s={row['completion_time_s']:.6f}")

        # Write results
        header_exists = os.path.exists(CSV_OUT)
        with open(CSV_OUT, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            if not header_exists:
                writer.writeheader()
            writer.writerows(rows)

    rows = load_results(CSV_OUT)
    means = mean_by_case(rows)  # averages across RUNS for each (ring_size, affected_fraction)
    plot_grouped_bars(means, OUT_PNG)
    
if __name__ == "__main__":
    main()