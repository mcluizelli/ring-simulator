"""Fail-closed paired n=100 revalidation for the two rate allocators.

This campaign replays every paper-producing cell that depends on the rate
allocator, once with the frozen legacy allocator and once with network-wide
max-min.  The matrix is fixed here: 134 arms, samples 0..99, 13,400 paired
jobs, and 26,800 simulations.  Output is allowed only below
``investigations/rate_allocator_n100``; ``results`` is immutable.

The driver deliberately has no n=1000 execution mode.  A fresh run requires a
hash printed by ``--dry-run``.  Interrupted runs may be continued only with
``--resume`` and their original manifest.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import multiprocessing as mp
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))
EXPERIMENTS_DIR = ROOT / "experiments"
if str(EXPERIMENTS_DIR) in sys.path:
    sys.path.remove(str(EXPERIMENTS_DIR))
sys.path.insert(0, str(EXPERIMENTS_DIR))

import run_rate_allocator_pilot as core  # noqa: E402
import sim  # noqa: E402


DRIVER_PATH = Path(__file__).resolve()
CORE_DRIVER_PATH = Path(core.__file__).resolve()
SIM_PATH = ROOT / "sim.py"
OUTPUT_ROOT = (ROOT / "investigations" / "rate_allocator_n100").resolve()

SAMPLE_IDS = tuple(range(100))
ALLOCATORS = (sim.RATE_ALLOCATOR_LINK_LOCAL, sim.RATE_ALLOCATOR_NETWORK_MAXMIN)
LEGACY_ALLOCATOR = sim.RATE_ALLOCATOR_LINK_LOCAL
MAXMIN_ALLOCATOR = sim.RATE_ALLOCATOR_NETWORK_MAXMIN

TOPO_K = 16
LINK_GBPS = 100.0
DT_S = 5e-5
MIB = 1024 * 1024
PLACEMENT_SEED_BASE = 9000
CONTROLLER_SEED_BASE = 0xCAFE
BACKGROUND_SEED_BASE = 0xBEEF
SEED_STRIDE = 10_000_001

EXPECTED_ARM_COUNTS = {
    "static_split": 80,
    "congestion": 16,
    "controller": 24,
    "background": 8,
    "placement": 6,
}
EXPECTED_FAMILY_PAIRS = {
    family: arms * len(SAMPLE_IDS) for family, arms in EXPECTED_ARM_COUNTS.items()
}
EXPECTED_RUNNER_ROWS = {
    "simple": 17_200,
    "proportional": 6_400,
    "adaptive": 1_600,
    "allreduce": 1_600,
}
PAIR_COUNT = 13_400
SIMULATION_COUNT = 26_800

ORACLE_PATHS = {
    **core.ORACLE_PATHS,
    "placement": ROOT / "results" / "placement_policies_n1000" / "results.csv",
}
METHODOLOGY_SOURCES = (
    ROOT / "experiments" / "run_k_saturation_n1000.py",
    ROOT / "experiments" / "run_flexible_split_n1000.py",
    ROOT / "experiments" / "experiment_congestion_models.py",
    ROOT / "experiments" / "run_v5_parallel.py",
    ROOT / "experiments" / "run_background_n1000.py",
    ROOT / "experiments" / "run_placement_policies_n1000.py",
)

_CORE_MAKE_TOPOLOGY_AND_RING = core._make_topology_and_ring
_CORE_ATTACH_ORACLE_VERDICT = core._attach_oracle_verdict
_CORE_FINITE_POSITIVE = core._finite_positive
_CORE_CONSERVATION_GATE = core._conservation_gate
_WORKER_EXPECTED_ADAPTIVE_EDGES: Optional[int] = None
_WORKER_EXPECTED_ADAPTIVE_K_MAX: Optional[int] = None


def _arm_specs() -> List[Dict[str, Any]]:
    common = {
        "topology_k": TOPO_K,
        "link_Gbps": LINK_GBPS,
        "dt_s": DT_S,
        "placement": "uniform_without_replacement",
    }
    fabrics = {
        "3tier_nb": (3, 1.0),
        "3tier_os2": (3, 2.0),
        "3tier_os4": (3, 4.0),
        "2tier": (2, 1.0),
    }
    arms: List[Dict[str, Any]] = []

    # Exact v10.1 equal-split matrix: 4 fabrics x 2 P x 6 k = 48 arms.
    for fabric, (n_tiers, oversub) in fabrics.items():
        for ring_size in (16, 64):
            for k in (1, 2, 4, 8, 16, 32):
                arms.append(
                    {
                        **common,
                        "arm_id": f"equal_{fabric}_p{ring_size}_k{k}",
                        "family": "static_split",
                        "runner": "simple",
                        "policy": "equal",
                        "fabric": fabric,
                        "n_tiers": n_tiers,
                        "oversub": oversub,
                        "ring_size": ring_size,
                        "k": k,
                        "bytes_per_neighbor": 64 * MIB,
                        "oracle_kind": "equal",
                    }
                )

    # Exact v11.1 proportional matrix: 4 fabrics x 2 P x 4 k = 32 arms.
    for fabric, (n_tiers, oversub) in fabrics.items():
        for ring_size in (16, 64):
            for k in (2, 4, 8, 16):
                arms.append(
                    {
                        **common,
                        "arm_id": f"proportional_{fabric}_p{ring_size}_k{k}",
                        "family": "static_split",
                        "runner": "proportional",
                        "policy": "proportional",
                        "fabric": fabric,
                        "n_tiers": n_tiers,
                        "oversub": oversub,
                        "ring_size": ring_size,
                        "k": k,
                        "bytes_per_neighbor": 64 * MIB,
                        "redistribution_window_s": 1e-3,
                        "oracle_kind": "proportional",
                    }
                )

    congestion_common = {
        **common,
        "family": "congestion",
        "runner": "simple",
        "policy": "equal",
        "fabric": "3tier_nb",
        "n_tiers": 3,
        "oversub": 1.0,
        "ring_size": 16,
        "bytes_per_neighbor": 256 * MIB,
        "oracle_kind": "congestion",
    }
    congestion_modes = {
        "onoff": {
            "mode": "onoff",
            "target_layers": ["agg_core", "edge_agg"],
            "affected_fraction": 0.3,
            "congested_util_low": 0.50,
            "congested_util_high": 0.95,
            "normal_util_low": 0.0,
            "normal_util_high": 0.05,
            "p_on": 0.01,
            "p_off": 0.005,
        },
        "iid": {
            "mode": "iid",
            "target_layers": ["agg_core", "edge_agg"],
            "affected_fraction": 0.3,
            "congested_util_low": 0.50,
            "congested_util_high": 0.95,
            "normal_util_low": 0.0,
            "normal_util_high": 0.05,
        },
        "hot_spot": {
            "mode": "hot_spot",
            "target_layers": ["agg_core", "edge_agg"],
            "affected_fraction": 0.3,
            "congested_util_low": 0.50,
            "congested_util_high": 0.95,
        },
        "microburst": {
            "mode": "microburst",
            "target_layers": ["agg_core", "edge_agg"],
            "affected_fraction": 0.3,
            "burst_prob": 0.001,
            "burst_ticks": 2,
            "burst_util_low": 0.80,
            "burst_util_high": 0.98,
            "normal_util_low": 0.0,
            "normal_util_high": 0.05,
        },
    }
    for mode, congestion in congestion_modes.items():
        for k in (1, 2, 4, 8):
            arms.append(
                {
                    **congestion_common,
                    "arm_id": f"congestion_{mode}_p16_k{k}",
                    "k": k,
                    "congestion": congestion,
                }
            )

    controller_common = {
        **common,
        "family": "controller",
        "fabric": "3tier_nb",
        "n_tiers": 3,
        "oversub": 1.0,
        "bytes_per_neighbor": 256 * MIB,
        "controller": {
            "measurement_window_s": 0.001,
            "threshold": 0.2,
            "k_max": 4,
            "cooldown_ticks": 200,
        },
        "oracle_kind": "controller",
        "controller_evaluation": "frozen_for_allocator_isolation_no_recalibration",
    }
    methods = (
        ("baseline", "simple", "equal", 1),
        ("static_k4", "simple", "equal", 4),
        ("adaptive", "adaptive", "adaptive", 1),
    )
    for ring_size in (16, 64):
        for affected_fraction in (0.0, 0.1, 0.3, 0.5):
            for method_id, runner, policy, k in methods:
                frozen_method = "static(k=4)" if method_id == "static_k4" else method_id
                arms.append(
                    {
                        **controller_common,
                        "arm_id": (
                            f"controller_p{ring_size}_af{int(affected_fraction * 10):02d}_"
                            f"{method_id}"
                        ),
                        "runner": runner,
                        "policy": policy,
                        "ring_size": ring_size,
                        "k": k,
                        "affected_fraction": affected_fraction,
                        "frozen_method": frozen_method,
                    }
                )

    background_common = {
        **common,
        "family": "background",
        "runner": "allreduce",
        "policy": "pipelined_allreduce",
        "fabric": "3tier_nb",
        "n_tiers": 3,
        "oversub": 1.0,
        "ring_size": 16,
        "total_bytes": 256 * MIB,
        "pipelined": True,
        "pipeline_window": 4,
        "alpha_s": 0.0,
        "background": {
            "size_dist": "lognormal",
            "mean_bytes": 50 * MIB,
            "sigma_logn": 1.0,
            "locality": "mixed",
            "p_local": 0.5,
        },
        "oracle_kind": "background",
    }
    for k in (1, 4):
        for rate in (0, 200, 500, 1000):
            arms.append(
                {
                    **background_common,
                    "arm_id": f"background_p16_k{k}_rate{rate}",
                    "k": k,
                    "arrival_rate_fps": rate,
                }
            )

    placement_common = {
        **common,
        "family": "placement",
        "runner": "simple",
        "policy": "equal",
        "fabric": "3tier_os4",
        "n_tiers": 3,
        "oversub": 4.0,
        "ring_size": 64,
        "bytes_per_neighbor": 256 * MIB,
        "affected_fraction": 0.5,
        "oracle_kind": "placement",
    }
    for placement_policy in ("compact_pod", "random", "spread"):
        for k in (1, 8):
            arms.append(
                {
                    **placement_common,
                    "arm_id": f"placement_{placement_policy}_p64_k{k}",
                    "placement_policy": placement_policy,
                    "k": k,
                }
            )

    counts = {
        family: sum(arm["family"] == family for arm in arms)
        for family in EXPECTED_ARM_COUNTS
    }
    if counts != EXPECTED_ARM_COUNTS:
        raise RuntimeError(f"n=100 arm counts changed: {counts}")
    if len(arms) != 134 or len({arm["arm_id"] for arm in arms}) != 134:
        raise RuntimeError("n=100 matrix must contain 134 uniquely named arms")
    return arms


def _materialize_pair(
    arm: Mapping[str, Any], arm_index: int, sample_index: int
) -> Dict[str, Any]:
    sample_id = SAMPLE_IDS[sample_index]
    config = json.loads(json.dumps(arm))
    config["sample_id"] = sample_id
    config["placement_seed"] = PLACEMENT_SEED_BASE + sample_id
    config["topology_seed"] = 1

    family = config["family"]
    if family == "congestion":
        config["congestion"]["seed"] = 1000 + sample_id
    elif family == "controller":
        topology_seed = CONTROLLER_SEED_BASE + sample_id * SEED_STRIDE
        config["topology_seed"] = topology_seed
        affected_fraction = float(config["affected_fraction"])
        if affected_fraction > 0.0:
            config["congestion"] = {
                "mode": "onoff",
                "seed": topology_seed + int(affected_fraction * 1000),
                "affected_fraction": affected_fraction,
                "congested_util_low": 0.50,
                "congested_util_high": 0.95,
                "normal_util_low": 0.0,
                "normal_util_high": 0.05,
                "p_on": 0.01,
                "p_off": 0.005,
                "target_layers": ["agg_core", "edge_agg"],
            }
        else:
            config["congestion"] = None
    elif family == "background":
        rate = int(config["arrival_rate_fps"])
        config["background_seed"] = (
            None
            if rate == 0
            else BACKGROUND_SEED_BASE + sample_id * SEED_STRIDE + rate
        )
    elif family == "placement":
        config["congestion"] = {
            "mode": "onoff",
            "seed": PLACEMENT_SEED_BASE + sample_id,
            "affected_fraction": 0.5,
            "congested_util_low": 0.50,
            "congested_util_high": 0.95,
            "normal_util_low": 0.0,
            "normal_util_high": 0.05,
            "p_on": 0.01,
            "p_off": 0.005,
            "target_layers": ["agg_core", "edge_agg"],
        }

    kind = config["oracle_kind"]
    if kind in {"equal", "proportional"}:
        oracle_key: Dict[str, Any] = {
            "fabric": config["fabric"],
            "P": config["ring_size"],
            "seed": sample_id,
            "k": config["k"],
        }
    elif kind == "congestion":
        oracle_key = {
            "model": config["congestion"]["mode"],
            "seed": sample_id,
            "k": config["k"],
        }
    elif kind == "controller":
        oracle_key = {
            "run": sample_id + 1,
            "seed": config["topology_seed"],
            "ring_size": config["ring_size"],
            "affected_fraction": config["affected_fraction"],
            "method": config["frozen_method"],
        }
    elif kind == "background":
        oracle_key = {
            "run": sample_id,
            "k": config["k"],
            "arrival_rate_fps": config["arrival_rate_fps"],
        }
    elif kind == "placement":
        oracle_key = {
            "policy": config["placement_policy"],
            "seed": sample_id,
            "k": config["k"],
        }
    else:
        raise RuntimeError(f"unknown oracle kind {kind}")

    ordinal = arm_index * len(SAMPLE_IDS) + sample_index
    order = list(ALLOCATORS if ordinal % 2 == 0 else reversed(ALLOCATORS))
    return {
        "pair_id": f"a{arm_index + 1:03d}_{config['arm_id']}__s{sample_id:03d}",
        "arm_index": arm_index,
        "sample_index": sample_index,
        "sample_id": sample_id,
        "execution_order": order,
        "config": config,
        "config_sha256": core._digest(config),
        "oracle_key": oracle_key,
    }


def build_plan() -> Dict[str, Any]:
    arms = _arm_specs()
    pairs = [
        _materialize_pair(arm, arm_index, sample_index)
        for arm_index, arm in enumerate(arms)
        for sample_index, _ in enumerate(SAMPLE_IDS)
    ]
    if len(pairs) != PAIR_COUNT or len({p["pair_id"] for p in pairs}) != PAIR_COUNT:
        raise RuntimeError("n=100 pair cardinality or uniqueness changed")
    family_counts = {
        family: sum(pair["config"]["family"] == family for pair in pairs)
        for family in EXPECTED_FAMILY_PAIRS
    }
    if family_counts != EXPECTED_FAMILY_PAIRS:
        raise RuntimeError(f"n=100 family pair counts changed: {family_counts}")
    first = {
        allocator: sum(pair["execution_order"][0] == allocator for pair in pairs)
        for allocator in ALLOCATORS
    }
    if first != {ALLOCATORS[0]: PAIR_COUNT // 2, ALLOCATORS[1]: PAIR_COUNT // 2}:
        raise RuntimeError(f"allocator-first order is not balanced: {first}")
    plan: Dict[str, Any] = {
        "schema": "rate-allocator-n100-plan-v1",
        "sample_ids": list(SAMPLE_IDS),
        "allocators": list(ALLOCATORS),
        "arms": arms,
        "pairs": pairs,
        "arm_count": len(arms),
        "pair_count": len(pairs),
        "simulation_count": SIMULATION_COUNT,
        "arm_family_counts": EXPECTED_ARM_COUNTS,
        "family_pair_counts": family_counts,
        "controller_policy": "frozen_for_isolation_calibration_deferred_to_disjoint_seeds",
        "placement_scope": "direct_three_policy_sweep_not_a_proxy",
        "no_n1000_execution_path": True,
    }
    plan["plan_sha256"] = core._digest(plan)
    return plan


def _methodology_hashes() -> Dict[str, str]:
    return {
        path.relative_to(ROOT).as_posix(): core._sha256_file(path)
        for path in METHODOLOGY_SOURCES
    }


def _authorization_sha256(
    plan: Mapping[str, Any],
    *,
    sim_hash: Optional[str] = None,
    driver_hash: Optional[str] = None,
    core_hash: Optional[str] = None,
) -> str:
    return core._digest(
        {
            "plan_sha256": plan["plan_sha256"],
            "sim_sha256": sim_hash or core._sha256_file(SIM_PATH),
            "driver_sha256": driver_hash or core._sha256_file(DRIVER_PATH),
            "paired_engine_sha256": core_hash or core._sha256_file(CORE_DRIVER_PATH),
        }
    )


def _verify_source_hashes(sim_hash: str, driver_hash: str, core_hash: str) -> None:
    if core._sha256_file(SIM_PATH) != sim_hash:
        raise RuntimeError("sim.py changed after n=100 authorization")
    if core._sha256_file(DRIVER_PATH) != driver_hash:
        raise RuntimeError("n=100 driver changed after dry-run authorization")
    if core._sha256_file(CORE_DRIVER_PATH) != core_hash:
        raise RuntimeError("paired execution engine changed after n=100 authorization")


def _configure_core() -> None:
    core.DRIVER_PATH = DRIVER_PATH
    core.PILOT_ROOT = OUTPUT_ROOT
    core.SAMPLE_IDS = SAMPLE_IDS
    core._make_topology_and_ring = _make_topology_and_ring
    core._attach_oracle_verdict = _attach_oracle_verdict
    core._finite_positive = _finite_timing_value
    core._adaptive_gate = _adaptive_gate
    core._conservation_gate = _conservation_gate


def _finite_timing_value(value: Any, label: str) -> float:
    """Permit a zero CPU-clock delta while retaining strict physical-time gates."""
    numeric = float(value)
    if "cpu time" in label.lower():
        if not math.isfinite(numeric) or numeric < 0.0:
            raise RuntimeError(f"{label} must be non-negative and finite; got {value!r}")
        return numeric
    return _CORE_FINITE_POSITIVE(value, label)


def _adaptive_gate(result: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate the adaptive trace against the authorized ring size and k_max."""
    if _WORKER_EXPECTED_ADAPTIVE_EDGES is None or _WORKER_EXPECTED_ADAPTIVE_K_MAX is None:
        raise RuntimeError("adaptive gate lacks an authorized pair context")
    expected_edges = _WORKER_EXPECTED_ADAPTIVE_EDGES
    k_max = _WORKER_EXPECTED_ADAPTIVE_K_MAX
    final_map = result["final_k_per_edge"]
    history = list(result["k_history"])
    completion = float(result["completion_time_s"])
    if len(final_map) != expected_edges:
        raise RuntimeError(
            f"adaptive final map has {len(final_map)} edges, expected {expected_edges}"
        )
    if any(int(k) < 1 or int(k) > k_max for k in final_map.values()):
        raise RuntimeError(f"adaptive final k outside [1,{k_max}]")
    if history != sorted(history, key=lambda item: item[0]):
        raise RuntimeError("adaptive history is not time ordered")
    current = {index: 1 for index in range(expected_edges)}
    for event_time, edge_index, new_k in history:
        if float(event_time) > completion:
            raise RuntimeError("adaptive event occurs after completion")
        edge_index = int(edge_index)
        if edge_index not in current:
            raise RuntimeError(f"adaptive event references unknown edge {edge_index}")
        if int(new_k) != current[edge_index] + 1:
            raise RuntimeError("adaptive event does not increment k by one")
        current[edge_index] = int(new_k)
    final_by_index = {index: int(final_map[edge]) for index, edge in enumerate(final_map)}
    if current != final_by_index:
        raise RuntimeError("adaptive event history does not reconstruct final k")
    event_count = len(history)
    if event_count != sum(int(k) - 1 for k in final_map.values()):
        raise RuntimeError("adaptive event count disagrees with final k map")
    return {
        "passed": True,
        "edge_count": len(final_map),
        "event_count": event_count,
        "final_k_mean": statistics.fmean(int(k) for k in final_map.values()),
        "final_k_max": max(int(k) for k in final_map.values()),
    }


def _simple_roundoff_tolerance(target: float) -> float:
    return max(1e-6, 128 * math.ulp(float(target)))


def _conservation_gate(
    config: Mapping[str, Any], result: Any, engine: core.PilotAuditedSimulator
) -> Dict[str, Any]:
    """Use the n=100-observed simple-counter envelope; delegate other runners."""
    if str(config["runner"]) != "simple":
        return _CORE_CONSERVATION_GATE(config, result, engine)
    flows = core._foreground_flows(engine, "simple")
    by_edge: Dict[Tuple[str, str], List[sim.Flow]] = {}
    for flow in flows:
        by_edge.setdefault((flow.five_tuple.src, flow.five_tuple.dst), []).append(flow)
    if len(by_edge) != int(config["ring_size"]):
        raise RuntimeError("simple runner captured the wrong number of logical edges")
    target = float(config["bytes_per_neighbor"])
    tolerance = _simple_roundoff_tolerance(target)
    maximum_error = 0.0
    for edge_flows in by_edge.values():
        delivered = sum(flow.sent_bytes for flow in edge_flows)
        error = abs(delivered - target)
        maximum_error = max(maximum_error, error)
        if error > tolerance:
            raise RuntimeError(
                f"simple byte-conservation error {error} B exceeds "
                f"n=100 audit tolerance {tolerance} B"
            )
    remaining = sum(max(0.0, flow.remaining_bytes) for flow in flows)
    if remaining != 0.0:
        raise RuntimeError(f"simple runner has {remaining} foreground bytes remaining")
    return {
        "passed": True,
        "foreground_flow_count": len(flows),
        "checks": len(by_edge),
        "remaining_foreground_bytes": remaining,
        "maximum_abs_error_bytes": maximum_error,
        "maximum_abs_error_bytes_hex": core._f64_hex(maximum_error),
        "non_bit_exact_flow_count": 0,
        "maximum_per_flow_error_bytes": 0.0,
        "maximum_per_flow_error_bytes_hex": core._f64_hex(0.0),
        "roundoff_tolerance_B": tolerance,
        "roundoff_tolerance_target_ulps": 128,
    }


def _validate_output_path(raw: str, *, require_absent: bool) -> Path:
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    resolved = candidate.resolve()
    if resolved == OUTPUT_ROOT or OUTPUT_ROOT not in resolved.parents:
        raise RuntimeError(f"output must be a new child of {OUTPUT_ROOT}; got {resolved}")
    results_root = (ROOT / "results").resolve()
    if resolved == results_root or results_root in resolved.parents:
        raise RuntimeError("n=100 output is forbidden inside results/")
    if require_absent and resolved.exists():
        raise FileExistsError(f"refusing existing output {resolved}; use --resume")
    return resolved


def _make_topology_and_ring(
    config: Mapping[str, Any]
) -> Tuple[sim.FatTree, List[str]]:
    if config["family"] != "placement":
        return _CORE_MAKE_TOPOLOGY_AND_RING(config)
    topo = sim.FatTree(
        k=int(config["topology_k"]),
        link_capacity_Gbps=float(config["link_Gbps"]),
        seed=int(config["topology_seed"]),
        n_tiers=int(config["n_tiers"]),
        oversub=float(config["oversub"]),
    )
    policy = config["placement_policy"]
    p = int(config["ring_size"])
    if policy == "compact_pod":
        ring = list(topo.hosts[:p])
    elif policy == "random":
        ring = random.Random(int(config["placement_seed"])).sample(topo.hosts, p)
    elif policy == "spread":
        by_pod: Dict[str, List[str]] = defaultdict(list)
        for host in topo.hosts:
            by_pod[host.split("_")[0]].append(host)
        rng = random.Random(int(config["placement_seed"])); pods = sorted(by_pod)
        per = p // len(pods)
        picked = {pod: rng.sample(by_pod[pod], per) for pod in pods}
        ring = [picked[pod][i] for i in range(per) for pod in pods]
    else:
        raise RuntimeError(f"unknown placement policy {policy}")
    if len(ring) != p or len(set(ring)) != p:
        raise RuntimeError(f"invalid placement ring for {policy}")
    return topo, ring


_WORKER_CORE_HASH = ""


def _worker_init(sim_hash: str, driver_hash: str, core_hash: str) -> None:
    global _WORKER_CORE_HASH
    _configure_core()
    _verify_source_hashes(sim_hash, driver_hash, core_hash)
    _WORKER_CORE_HASH = core_hash
    core._worker_init(sim_hash, driver_hash)


def _run_pair_worker(pair: Mapping[str, Any]) -> Dict[str, Any]:
    global _WORKER_EXPECTED_ADAPTIVE_EDGES, _WORKER_EXPECTED_ADAPTIVE_K_MAX
    _configure_core()
    _verify_source_hashes(
        core._WORKER_SIM_HASH,
        core._WORKER_DRIVER_HASH,
        _WORKER_CORE_HASH,
    )
    config = pair["config"]
    if config["runner"] == "adaptive":
        _WORKER_EXPECTED_ADAPTIVE_EDGES = int(config["ring_size"])
        _WORKER_EXPECTED_ADAPTIVE_K_MAX = int(config["controller"]["k_max"])
    else:
        _WORKER_EXPECTED_ADAPTIVE_EDGES = None
        _WORKER_EXPECTED_ADAPTIVE_K_MAX = None
    try:
        checkpoint = core._run_pair_worker(pair)
    finally:
        _WORKER_EXPECTED_ADAPTIVE_EDGES = None
        _WORKER_EXPECTED_ADAPTIVE_K_MAX = None
    _verify_source_hashes(
        core._WORKER_SIM_HASH,
        core._WORKER_DRIVER_HASH,
        _WORKER_CORE_HASH,
    )
    return checkpoint


def _oracle_indexes() -> Dict[str, Dict[Tuple[Any, ...], Dict[str, str]]]:
    indexes = _CORE_ORACLE_INDEXES()
    placement: Dict[Tuple[Any, ...], Dict[str, str]] = {}
    for row in core._read_csv(ORACLE_PATHS["placement"]):
        key = (row["policy"], int(row["seed"]), int(row["k"]))
        if key in placement:
            raise RuntimeError(f"duplicate placement oracle key {key}")
        placement[key] = row
    indexes["placement"] = placement
    return indexes


_CORE_ORACLE_INDEXES = core._oracle_indexes


def _attach_oracle_verdict(
    checkpoint: Dict[str, Any],
    indexes: Mapping[str, Mapping[Tuple[Any, ...], Dict[str, str]]],
) -> None:
    pair = checkpoint["pair_spec"]
    if pair["config"]["oracle_kind"] != "placement":
        _CORE_ATTACH_ORACLE_VERDICT(checkpoint, indexes)
        return
    key = pair["oracle_key"]
    packed = (key["policy"], int(key["seed"]), int(key["k"]))
    try:
        frozen = indexes["placement"][packed]
    except KeyError as exc:
        raise RuntimeError(f"missing frozen placement oracle row {packed}") from exc
    legacy = next(row for row in checkpoint["rows"] if row["allocator"] == LEGACY_ALLOCATOR)
    actual_hex = core._f64_hex(legacy["oracle_actual"]["completion_time_s"])
    expected_hex = core._f64_hex(frozen["t"])
    if actual_hex != expected_hex:
        raise RuntimeError(f"legacy result mismatch for {pair['pair_id']}: completion_time_s")
    legacy["oracle_verdict"] = {
        "status": "exact_binary64_match",
        "source": ORACLE_PATHS["placement"].relative_to(ROOT).as_posix(),
        "key": key,
        "comparisons": {
            "completion_time_s": {
                "actual_hex": actual_hex,
                "expected_hex": expected_hex,
                "equal": True,
            }
        },
    }
    maxmin = next(row for row in checkpoint["rows"] if row["allocator"] == MAXMIN_ALLOCATOR)
    maxmin["oracle_verdict"] = {
        "status": "not_applicable_new_allocator",
        "exact_frozen_source": None,
    }


def _global_gate(
    plan: Mapping[str, Any], checkpoints: Mapping[str, Mapping[str, Any]]
) -> Dict[str, Any]:
    if len(checkpoints) != PAIR_COUNT:
        raise RuntimeError(f"global gate expected {PAIR_COUNT} checkpoints")
    rows = [row for pair_id in sorted(checkpoints) for row in checkpoints[pair_id]["rows"]]
    if len(rows) != SIMULATION_COUNT:
        raise RuntimeError(f"global gate expected {SIMULATION_COUNT} rows")
    if len({(row["pair_id"], row["allocator"]) for row in rows}) != SIMULATION_COUNT:
        raise RuntimeError("duplicate pair/allocator row")
    allocator_counts = {
        allocator: sum(row["allocator"] == allocator for row in rows)
        for allocator in ALLOCATORS
    }
    if allocator_counts != {allocator: PAIR_COUNT for allocator in ALLOCATORS}:
        raise RuntimeError(f"allocator row count mismatch: {allocator_counts}")
    runner_counts = {
        runner: sum(row["runner"] == runner for row in rows)
        for runner in EXPECTED_RUNNER_ROWS
    }
    if runner_counts != EXPECTED_RUNNER_ROWS:
        raise RuntimeError(f"runner row count mismatch: {runner_counts}")
    family_rows = {
        family: sum(row["family"] == family for row in rows)
        for family in EXPECTED_FAMILY_PAIRS
    }
    expected_family_rows = {
        family: pair_count * 2 for family, pair_count in EXPECTED_FAMILY_PAIRS.items()
    }
    if family_rows != expected_family_rows:
        raise RuntimeError(f"family row count mismatch: {family_rows}")
    sample_rows = {
        sample: sum(int(row["sample_id"]) == sample for row in rows)
        for sample in SAMPLE_IDS
    }
    if set(sample_rows.values()) != {268}:
        raise RuntimeError(f"per-sample row count mismatch: {sample_rows}")
    first_counts = {
        allocator: sum(
            row["allocator"] == allocator and int(row["execution_position"]) == 0
            for row in rows
        )
        for allocator in ALLOCATORS
    }
    if first_counts != {allocator: PAIR_COUNT // 2 for allocator in ALLOCATORS}:
        raise RuntimeError(f"execution-order balance changed: {first_counts}")
    planned_ids = {pair["pair_id"] for pair in plan["pairs"]}
    if set(checkpoints) != planned_ids:
        raise RuntimeError("completed pair-ID set differs from authorized plan")

    exact_legacy = sum(
        row["allocator"] == LEGACY_ALLOCATOR
        and row["oracle_verdict"]["status"] == "exact_binary64_match"
        for row in rows
    )
    maxmin_new = sum(
        row["allocator"] == MAXMIN_ALLOCATOR
        and row["oracle_verdict"]["status"] == "not_applicable_new_allocator"
        for row in rows
    )
    if exact_legacy != PAIR_COUNT or maxmin_new != PAIR_COUNT:
        raise RuntimeError(
            f"oracle cardinality mismatch: legacy={exact_legacy}, maxmin={maxmin_new}"
        )

    adaptive_coverage: Dict[str, Any] = {}
    for pair_id, checkpoint in checkpoints.items():
        config = checkpoint["pair_spec"]["config"]
        if config["runner"] != "adaptive":
            continue
        row = next(r for r in checkpoint["rows"] if r["allocator"] == MAXMIN_ALLOCATOR)
        key = f"P{config['ring_size']}_af{config['affected_fraction']}"
        item = adaptive_coverage.setdefault(key, {"runs": 0, "event_count": 0})
        item["runs"] += 1
        item["event_count"] += int(row["scalar_metrics"]["adaptive_event_count"])
    expected_adaptive = {
        f"P{p}_af{af}" for p in (16, 64) for af in (0.0, 0.1, 0.3, 0.5)
    }
    if set(adaptive_coverage) != expected_adaptive:
        raise RuntimeError("adaptive cell coverage changed")
    for key, item in adaptive_coverage.items():
        item["passed"] = item["runs"] == 100 and (
            key.endswith("af0.0") or item["event_count"] > 0
        )
        if not item["passed"]:
            raise RuntimeError(f"inactive or incomplete frozen controller cell {key}: {item}")

    max_conservation = max(
        float(row["conservation"]["maximum_abs_error_bytes"]) for row in rows
    )
    max_remaining = max(
        float(row["conservation"]["remaining_foreground_bytes"]) for row in rows
    )
    return {
        "passed": True,
        "pair_count": len(checkpoints),
        "row_count": len(rows),
        "allocator_counts": allocator_counts,
        "runner_counts": runner_counts,
        "family_row_counts": family_rows,
        "sample_row_count_min": min(sample_rows.values()),
        "sample_row_count_max": max(sample_rows.values()),
        "first_position_counts": first_counts,
        "exact_frozen_legacy_matches": exact_legacy,
        "new_allocator_rows": maxmin_new,
        "adaptive_coverage": adaptive_coverage,
        "direct_placement_pairs": EXPECTED_FAMILY_PAIRS["placement"],
        "maximum_conservation_error_B": max_conservation,
        "maximum_foreground_remaining_B": max_remaining,
    }


def _paired_rows(
    checkpoints: Mapping[str, Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    out = []
    for pair_id in sorted(checkpoints):
        checkpoint = checkpoints[pair_id]
        config = checkpoint["pair_spec"]["config"]
        indexed = {row["allocator"]: row for row in checkpoint["rows"]}
        legacy = float(indexed[LEGACY_ALLOCATOR]["completion_time_s"])
        maxmin = float(indexed[MAXMIN_ALLOCATOR]["completion_time_s"])
        out.append(
            {
                "pair_id": pair_id,
                "arm_id": config["arm_id"],
                "sample_id": checkpoint["pair_spec"]["sample_id"],
                "family": config["family"],
                "runner": config["runner"],
                "policy": config["policy"],
                "placement_policy": config.get("placement_policy", ""),
                "fabric": config["fabric"],
                "ring_size": config["ring_size"],
                "k": config["k"],
                "affected_fraction": config.get("affected_fraction", ""),
                "congestion_model": (config.get("congestion") or {}).get("mode", ""),
                "arrival_rate_fps": config.get("arrival_rate_fps", ""),
                "frozen_method": config.get("frozen_method", ""),
                "legacy_time_s": repr(legacy),
                "maxmin_time_s": repr(maxmin),
                "maxmin_over_legacy": repr(maxmin / legacy),
                "maxmin_delta_pct": repr((maxmin / legacy - 1.0) * 100.0),
                "campaign_use": "paired_n100_revalidation",
            }
        )
    return out


def _arm_summary(pair_rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in pair_rows:
        groups[str(row["arm_id"])].append(row)
    out = []
    for arm_id in sorted(groups):
        selected = groups[arm_id]
        legacy = [float(row["legacy_time_s"]) for row in selected]
        maxmin = [float(row["maxmin_time_s"]) for row in selected]
        ratios = [m / l for l, m in zip(legacy, maxmin)]
        first = selected[0]
        out.append(
            {
                "arm_id": arm_id,
                "family": first["family"],
                "n_pairs": len(selected),
                "legacy_mean_s": repr(statistics.fmean(legacy)),
                "maxmin_mean_s": repr(statistics.fmean(maxmin)),
                "paired_ratio_mean": repr(statistics.fmean(ratios)),
                "paired_ratio_median": repr(statistics.median(ratios)),
                "paired_ratio_min": repr(min(ratios)),
                "paired_ratio_max": repr(max(ratios)),
                "maxmin_faster_count": sum(ratio < 1.0 for ratio in ratios),
                "bit_equal_count": sum(
                    core._f64_hex(l) == core._f64_hex(m)
                    for l, m in zip(legacy, maxmin)
                ),
                "maxmin_slower_count": sum(ratio > 1.0 for ratio in ratios),
                "inference_note": "descriptive_only_CI_and_claim_audit_follow",
            }
        )
    return out


def _runtime_summary(
    checkpoints: Mapping[str, Mapping[str, Any]],
    workers: int,
    timing_segments: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    rows = [row for checkpoint in checkpoints.values() for row in checkpoint["rows"]]
    pool_elapsed = sum(float(segment["elapsed_pool_wall_s"]) for segment in timing_segments)
    sim_sum = sum(float(row["simulation_wall_time_s"]) for row in rows)
    total_sum = sum(float(row["wall_time_s"]) for row in rows)
    effective_sim = sim_sum / pool_elapsed
    effective_total = total_sum / pool_elapsed
    if not (0.0 < effective_total <= workers * 1.25):
        raise RuntimeError(f"implausible measured parallelism {effective_total}")
    return {
        "schema": "rate-allocator-n100-runtime-v1",
        "workers": workers,
        "segments": len(timing_segments),
        "recovered_segments": sum(
            bool(segment.get("recovered_after_interruption"))
            for segment in timing_segments
        ),
        "measured_n100_pool_wall_s": pool_elapsed,
        "worker_simulation_wall_sum_s": sim_sum,
        "worker_end_to_end_wall_sum_s": total_sum,
        "effective_simulation_parallelism": effective_sim,
        "effective_end_to_end_parallelism": effective_total,
        "n1000_projection": {
            "simulations": SIMULATION_COUNT * 10,
            "central_wall_hours_linear_same_matrix_same_workers": pool_elapsed * 10 / 3600.0,
            "semantics": "linear planning estimate from measured n=100; not a confidence interval",
            "automatic_start": False,
        },
    }


def _timing_path(output: Path, index: int) -> Path:
    return output / "timing_segments" / f"segment_{index:03d}.json"


def _load_timing_segments(
    output: Path, checkpoints: Mapping[str, Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    segments: List[Dict[str, Any]] = []
    covered: set[str] = set()
    for path in sorted((output / "timing_segments").iterdir()):
        if path.name == ".staging" and path.is_dir():
            if any(not child.is_file() or ".tmp-" not in child.name for child in path.iterdir()):
                raise RuntimeError("timing staging contains an unknown artifact")
            continue
        if not path.is_file() or path.suffix != ".json":
            raise RuntimeError(f"unexpected timing artifact {path.name}")
        segment = json.loads(path.read_text(encoding="utf-8"))
        index = len(segments) + 1
        if segment.get("schema") != "rate-allocator-n100-timing-segment-v1":
            raise RuntimeError(f"wrong timing schema in {path.name}")
        if path.name != f"segment_{index:03d}.json" or segment.get("segment_index") != index:
            raise RuntimeError(f"non-sequential timing segment {path.name}")
        pair_ids = list(segment.get("pair_ids", []))
        if not pair_ids or len(pair_ids) != len(set(pair_ids)):
            raise RuntimeError(f"invalid pair list in {path.name}")
        if covered.intersection(pair_ids) or any(pid not in checkpoints for pid in pair_ids):
            raise RuntimeError(f"overlapping or unknown timing pair in {path.name}")
        if any(
            checkpoints[pid]["parent_timing"]["segment_index"] != index for pid in pair_ids
        ):
            raise RuntimeError(f"checkpoint timing index mismatch in {path.name}")
        elapsed = core._finite_positive(segment["elapsed_pool_wall_s"], "pool wall")
        if any(
            float(checkpoints[pid]["parent_timing"]["pool_elapsed_at_checkpoint_s"])
            > elapsed
            for pid in pair_ids
        ):
            raise RuntimeError(f"checkpoint after segment end in {path.name}")
        expected_sim = sum(
            float(row["simulation_wall_time_s"])
            for pid in pair_ids
            for row in checkpoints[pid]["rows"]
        )
        expected_total = sum(
            float(row["wall_time_s"])
            for pid in pair_ids
            for row in checkpoints[pid]["rows"]
        )
        if core._f64_hex(segment["worker_simulation_wall_sum_s"]) != core._f64_hex(expected_sim):
            raise RuntimeError(f"simulation-wall sum mismatch in {path.name}")
        if core._f64_hex(segment["worker_end_to_end_wall_sum_s"]) != core._f64_hex(expected_total):
            raise RuntimeError(f"end-to-end wall sum mismatch in {path.name}")
        covered.update(pair_ids); segments.append(segment)
    return segments


def _recover_timing_segments(
    output: Path,
    checkpoints: Mapping[str, Mapping[str, Any]],
    existing: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    covered = {pid for segment in existing for pid in segment["pair_ids"]}
    groups: Dict[int, List[str]] = defaultdict(list)
    for pair_id, checkpoint in checkpoints.items():
        if pair_id not in covered:
            groups[int(checkpoint["parent_timing"]["segment_index"])].append(pair_id)
    next_index = len(existing) + 1
    for index in sorted(groups):
        if index != next_index:
            raise RuntimeError(f"cannot recover timing segment {index}; expected {next_index}")
        pair_ids = sorted(groups[index])
        segment = {
            "schema": "rate-allocator-n100-timing-segment-v1",
            "segment_index": index,
            "pair_ids": pair_ids,
            "elapsed_pool_wall_s": max(
                float(checkpoints[pid]["parent_timing"]["pool_elapsed_at_checkpoint_s"])
                for pid in pair_ids
            ),
            "worker_simulation_wall_sum_s": sum(
                float(row["simulation_wall_time_s"])
                for pid in pair_ids for row in checkpoints[pid]["rows"]
            ),
            "worker_end_to_end_wall_sum_s": sum(
                float(row["wall_time_s"])
                for pid in pair_ids for row in checkpoints[pid]["rows"]
            ),
            "recovered_after_interruption": True,
            "timing_note": "ends at last durable checkpoint; crash overhead excluded",
        }
        core._atomic_json_once(_timing_path(output, index), segment)
        next_index += 1
    return _load_timing_segments(output, checkpoints)


def _new_manifest(plan: Mapping[str, Any], output: Path, workers: int) -> Dict[str, Any]:
    sim_hash = core._sha256_file(SIM_PATH)
    driver_hash = core._sha256_file(DRIVER_PATH)
    core_hash = core._sha256_file(CORE_DRIVER_PATH)
    return {
        "schema": "rate-allocator-n100-run-v1",
        "created_local": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "output": str(output),
        "workers": workers,
        "python": sys.version,
        "platform": platform.platform(),
        "multiprocessing_start_method": "spawn",
        "plan_sha256": plan["plan_sha256"],
        "plan": plan,
        "sim_sha256": sim_hash,
        "driver_sha256": driver_hash,
        "paired_engine_sha256": core_hash,
        "authorization_sha256": _authorization_sha256(
            plan, sim_hash=sim_hash, driver_hash=driver_hash, core_hash=core_hash
        ),
        "methodology_source_sha256": _methodology_hashes(),
        "git": core._git_state(),
        "frozen_before": core.audit_frozen_csvs(),
        "results_tree_before": core.snapshot_results_tree(),
        "checkpoint_policy": "one atomic parent-written JSON per complete allocator pair",
        "campaign_use": "paired_n100_scientific_revalidation",
        "controller_policy": "frozen_for_isolation_no_recalibration",
        "automatic_next_stage": None,
    }


def _existing_checkpoints(
    output: Path,
    plan: Mapping[str, Any],
    indexes: Mapping[str, Mapping[Tuple[Any, ...], Dict[str, str]]],
) -> Dict[str, Dict[str, Any]]:
    _configure_core()
    return core._existing_checkpoints(output, plan, indexes)


def _finalize(
    output: Path,
    plan: Mapping[str, Any],
    checkpoints: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, Any],
    timing_segments: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    covered = {pid for segment in timing_segments for pid in segment["pair_ids"]}
    if covered != set(checkpoints):
        raise RuntimeError("timing provenance does not cover every checkpoint")
    gate = _global_gate(plan, checkpoints)
    rows = [
        row
        for pair_id in sorted(checkpoints)
        for row in sorted(checkpoints[pair_id]["rows"], key=lambda item: item["allocator"])
    ]
    flat = [core._flat_row(row) for row in rows]
    for row in flat:
        row["pilot_use"] = "paired_n100_revalidation"
    pair_rows = _paired_rows(checkpoints)
    arm_rows = _arm_summary(pair_rows)
    runtime = _runtime_summary(checkpoints, int(manifest["workers"]), timing_segments)
    core._atomic_write_once(output / "results_long.csv", core._csv_bytes(flat))
    core._atomic_write_once(output / "pairs.csv", core._csv_bytes(pair_rows))
    core._atomic_write_once(output / "arm_summary.csv", core._csv_bytes(arm_rows))
    core._atomic_json_once(output / "runtime.json", runtime)

    frozen_after = core.audit_frozen_csvs()
    if frozen_after != manifest["frozen_before"]:
        raise RuntimeError("frozen CSV snapshot changed during n=100")
    results_after = core.snapshot_results_tree()
    if results_after != manifest["results_tree_before"]:
        raise RuntimeError("results/ tree changed during n=100")
    _verify_source_hashes(
        manifest["sim_sha256"],
        manifest["driver_sha256"],
        manifest["paired_engine_sha256"],
    )
    if _methodology_hashes() != manifest["methodology_source_sha256"]:
        raise RuntimeError("methodology source changed during n=100")

    export_names = ("results_long.csv", "pairs.csv", "arm_summary.csv", "runtime.json")
    exports = {
        name: {
            "bytes": (output / name).stat().st_size,
            "sha256": core._sha256_file(output / name),
        }
        for name in export_names
    }
    checkpoint_artifacts = {
        f"checkpoints/{pair_id}.json": {
            "bytes": core._checkpoint_path(output, pair_id).stat().st_size,
            "sha256": core._sha256_file(core._checkpoint_path(output, pair_id)),
        }
        for pair_id in sorted(checkpoints)
    }
    timing_artifacts = {
        f"timing_segments/segment_{index:03d}.json": {
            "bytes": _timing_path(output, index).stat().st_size,
            "sha256": core._sha256_file(_timing_path(output, index)),
        }
        for index in range(1, len(timing_segments) + 1)
    }
    completion = {
        "schema": "rate-allocator-n100-completion-v1",
        "plan_sha256": plan["plan_sha256"],
        "pair_count": PAIR_COUNT,
        "simulation_count": SIMULATION_COUNT,
        "gate": gate,
        "runtime": runtime,
        "frozen_after": frozen_after,
        "results_tree_after": results_after,
        "exports": exports,
        "checkpoints": checkpoint_artifacts,
        "timing_segments": timing_artifacts,
        "run_manifest": {
            "bytes": (output / "run_manifest.json").stat().st_size,
            "sha256": core._sha256_file(output / "run_manifest.json"),
        },
        "controller_recalibrated": False,
        "n1000_started": False,
        "automatic_next_stage": None,
    }
    core._atomic_json_once(output / "completion_manifest.json", completion)
    complete = {
        "schema": "rate-allocator-n100-complete-v1",
        "plan_sha256": plan["plan_sha256"],
        "completion_manifest_sha256": core._sha256_file(output / "completion_manifest.json"),
        "run_manifest_sha256": completion["run_manifest"]["sha256"],
        "status": "n100_revalidation_complete_ready_for_analysis",
    }
    core._atomic_json_once(output / "COMPLETE.json", complete)
    return completion


def _verify_complete(output: Path, manifest: Mapping[str, Any]) -> Dict[str, Any]:
    complete = json.loads((output / "COMPLETE.json").read_text(encoding="utf-8"))
    if complete.get("schema") != "rate-allocator-n100-complete-v1":
        raise RuntimeError("COMPLETE schema mismatch")
    if complete.get("status") != "n100_revalidation_complete_ready_for_analysis":
        raise RuntimeError("COMPLETE status mismatch")
    if complete.get("plan_sha256") != manifest["plan_sha256"]:
        raise RuntimeError("COMPLETE plan mismatch")
    completion_path = output / "completion_manifest.json"
    if core._sha256_file(completion_path) != complete["completion_manifest_sha256"]:
        raise RuntimeError("completion manifest hash mismatch")
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    if completion.get("schema") != "rate-allocator-n100-completion-v1":
        raise RuntimeError("completion schema mismatch")
    if completion.get("pair_count") != PAIR_COUNT or completion.get("simulation_count") != SIMULATION_COUNT:
        raise RuntimeError("completion cardinality mismatch")
    if completion.get("gate", {}).get("passed") is not True:
        raise RuntimeError("completed global gate is not true")
    if core._sha256_file(output / "run_manifest.json") != complete["run_manifest_sha256"]:
        raise RuntimeError("run manifest changed after completion")
    for group in ("exports", "checkpoints", "timing_segments"):
        for name, expected in completion[group].items():
            path = output / name
            if path.stat().st_size != expected["bytes"] or core._sha256_file(path) != expected["sha256"]:
                raise RuntimeError(f"completed artifact changed: {name}")
    if core.audit_frozen_csvs() != manifest["frozen_before"]:
        raise RuntimeError("frozen inputs changed after completion")
    if core.snapshot_results_tree() != manifest["results_tree_before"]:
        raise RuntimeError("results/ changed after completion")
    _verify_source_hashes(
        manifest["sim_sha256"], manifest["driver_sha256"], manifest["paired_engine_sha256"]
    )
    return completion


def execute_or_resume(
    plan: Mapping[str, Any],
    output: Path,
    *,
    workers: Optional[int],
    resume: bool,
    confirmed_authorization: Optional[str] = None,
) -> Dict[str, Any]:
    _configure_core()
    if resume:
        if not output.is_dir():
            raise RuntimeError(f"resume directory does not exist: {output}")
    else:
        if confirmed_authorization != _authorization_sha256(plan):
            raise RuntimeError("execution authorization changed before directory creation")
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        output.mkdir(parents=False, exist_ok=False)
        (output / "checkpoints").mkdir(exist_ok=False)
        (output / "timing_segments").mkdir(exist_ok=False)

    with core.ExclusiveRunLock(output / ".run.lock"):
        manifest_path = output / "run_manifest.json"
        if resume:
            if not manifest_path.is_file():
                raise RuntimeError("resume requires run_manifest.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("schema") != "rate-allocator-n100-run-v1":
                raise RuntimeError("resume manifest schema mismatch")
            if manifest.get("plan_sha256") != plan["plan_sha256"] or manifest.get("plan") != plan:
                raise RuntimeError("resume plan differs from current fixed matrix")
            if Path(manifest.get("output", "")).resolve() != output:
                raise RuntimeError("resume output path differs from manifest")
            expected_auth = _authorization_sha256(
                plan,
                sim_hash=manifest.get("sim_sha256"),
                driver_hash=manifest.get("driver_sha256"),
                core_hash=manifest.get("paired_engine_sha256"),
            )
            if manifest.get("authorization_sha256") != expected_auth:
                raise RuntimeError("resume authorization is inconsistent")
            workers = int(manifest["workers"])
            _verify_source_hashes(
                manifest["sim_sha256"], manifest["driver_sha256"], manifest["paired_engine_sha256"]
            )
            if core.audit_frozen_csvs() != manifest["frozen_before"]:
                raise RuntimeError("frozen inputs changed since run start")
            if core.snapshot_results_tree() != manifest["results_tree_before"]:
                raise RuntimeError("results/ changed since run start")
            if _methodology_hashes() != manifest["methodology_source_sha256"]:
                raise RuntimeError("methodology source changed since run start")
            if (output / "COMPLETE.json").exists():
                return _verify_complete(output, manifest)
        else:
            if workers is None or not 1 <= workers <= 8:
                raise RuntimeError("fresh execution requires 1..8 workers")
            manifest = _new_manifest(plan, output, workers)
            if manifest["authorization_sha256"] != confirmed_authorization:
                raise RuntimeError("execution sources changed while creating manifest")
            core._atomic_json_once(manifest_path, manifest)

        if workers is None or not 1 <= workers <= 8:
            raise RuntimeError("worker count unavailable or outside 1..8")
        indexes = _oracle_indexes()
        checkpoint_map = _existing_checkpoints(output, plan, indexes)
        segments = _load_timing_segments(output, checkpoint_map)
        segments = _recover_timing_segments(output, checkpoint_map, segments)
        pending = [pair for pair in plan["pairs"] if pair["pair_id"] not in checkpoint_map]
        if pending:
            pool_start = time.perf_counter()
            segment_index = len(segments) + 1
            context = mp.get_context("spawn")
            executor = ProcessPoolExecutor(
                max_workers=workers,
                mp_context=context,
                initializer=_worker_init,
                initargs=(
                    manifest["sim_sha256"],
                    manifest["driver_sha256"],
                    manifest["paired_engine_sha256"],
                ),
            )
            try:
                futures = {executor.submit(_run_pair_worker, pair): pair for pair in pending}
                completed = len(checkpoint_map)
                report_every = max(1, PAIR_COUNT // 100)
                for future in as_completed(futures):
                    pair = futures[future]
                    checkpoint = future.result()
                    _attach_oracle_verdict(checkpoint, indexes)
                    checkpoint["plan_sha256"] = plan["plan_sha256"]
                    checkpoint["parent_timing"] = {
                        "segment_index": segment_index,
                        "pool_elapsed_at_checkpoint_s": time.perf_counter() - pool_start,
                    }
                    core._validate_checkpoint(checkpoint, pair, plan["plan_sha256"])
                    core._atomic_json_once(
                        core._checkpoint_path(output, pair["pair_id"]), checkpoint
                    )
                    checkpoint_map[pair["pair_id"]] = checkpoint
                    completed += 1
                    if completed == PAIR_COUNT or completed % report_every == 0:
                        elapsed = time.perf_counter() - pool_start
                        rate = (completed - (PAIR_COUNT - len(pending))) / elapsed
                        remaining = PAIR_COUNT - completed
                        eta_min = remaining / max(rate, 1e-12) / 60.0
                        print(
                            f"[{completed:,}/{PAIR_COUNT:,}] pairs gated; "
                            f"segment ETA {eta_min:.1f} min",
                            flush=True,
                        )
            except BaseException:
                executor.shutdown(wait=False, cancel_futures=True)
                raise
            else:
                executor.shutdown(wait=True)
            elapsed = time.perf_counter() - pool_start
            pair_ids = sorted(pair["pair_id"] for pair in pending)
            segment = {
                "schema": "rate-allocator-n100-timing-segment-v1",
                "segment_index": segment_index,
                "pair_ids": pair_ids,
                "elapsed_pool_wall_s": elapsed,
                "worker_simulation_wall_sum_s": sum(
                    float(row["simulation_wall_time_s"])
                    for pair_id in pair_ids for row in checkpoint_map[pair_id]["rows"]
                ),
                "worker_end_to_end_wall_sum_s": sum(
                    float(row["wall_time_s"])
                    for pair_id in pair_ids for row in checkpoint_map[pair_id]["rows"]
                ),
                "recovered_after_interruption": False,
                "timing_note": "complete pool attempt measured through executor shutdown",
            }
            core._atomic_json_once(_timing_path(output, segment_index), segment)
        checkpoint_map = _existing_checkpoints(output, plan, indexes)
        segments = _load_timing_segments(output, checkpoint_map)
        return _finalize(output, plan, checkpoint_map, manifest, segments)


def dry_run(plan: Mapping[str, Any], output: Path) -> None:
    _configure_core()
    frozen = core.audit_frozen_csvs()
    results_snapshot = core.snapshot_results_tree()
    sim_hash = core._sha256_file(SIM_PATH)
    driver_hash = core._sha256_file(DRIVER_PATH)
    core_hash = core._sha256_file(CORE_DRIVER_PATH)
    auth = _authorization_sha256(
        plan, sim_hash=sim_hash, driver_hash=driver_hash, core_hash=core_hash
    )
    print("RATE-ALLOCATOR n=100 DRY-RUN (NO FILES, NO SIMULATIONS)")
    print(f"output={output}")
    print(f"plan_sha256={plan['plan_sha256']}")
    print(f"authorization_sha256={auth}")
    print(f"driver_sha256={driver_hash}")
    print(f"paired_engine_sha256={core_hash}")
    print(f"sim_sha256={sim_hash}")
    print(
        f"matrix=134 arms x 100 samples x 2 allocators = "
        f"{PAIR_COUNT} pairs / {SIMULATION_COUNT} simulations"
    )
    print(f"arm_family_counts={json.dumps(EXPECTED_ARM_COUNTS, sort_keys=True)}")
    print(f"family_pair_counts={json.dumps(EXPECTED_FAMILY_PAIRS, sort_keys=True)}")
    print(f"runner_rows={json.dumps(EXPECTED_RUNNER_ROWS, sort_keys=True)}")
    print(f"pair_ids_sha256={core._digest([p['pair_id'] for p in plan['pairs']])}")
    print(f"first_pair={plan['pairs'][0]['pair_id']}")
    print(f"last_pair={plan['pairs'][-1]['pair_id']}")
    print(
        f"frozen={frozen['count']} CSVs / {frozen['total_bytes']} bytes / "
        f"root {frozen['root_sha256']}"
    )
    print(
        f"results_snapshot={results_snapshot['file_count']} files / "
        f"root {results_snapshot['root_sha256']}"
    )
    print(f"methodology_source_sha256={json.dumps(_methodology_hashes(), sort_keys=True)}")
    print("ARM_SPECS_CANONICAL_JSON_BEGIN")
    print(json.dumps(plan["arms"], sort_keys=True, separators=(",", ":"), allow_nan=False))
    print("ARM_SPECS_CANONICAL_JSON_END")
    command = subprocess.list2cmdline(
        [
            sys.executable,
            str(DRIVER_PATH),
            "--execute",
            "--output",
            str(output),
            "--confirm-authorization-sha256",
            auth,
            "--workers",
            "8",
        ]
    )
    print("AUTHORIZED_EXECUTION_TEMPLATE")
    print(command)
    print("STOP: dry-run completed; n=1000 is not reachable from this driver")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--resume", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--confirm-authorization-sha256")
    parser.add_argument("--workers", type=int)
    args = parser.parse_args(argv)
    if args.dry_run:
        if args.confirm_authorization_sha256 is not None or args.workers is not None:
            parser.error("--dry-run accepts neither confirmation nor workers")
    elif args.execute:
        if args.confirm_authorization_sha256 is None or args.workers is None:
            parser.error("--execute requires confirmation and workers")
    elif args.resume:
        if args.confirm_authorization_sha256 is not None or args.workers is not None:
            parser.error("--resume reads authorization and workers from the manifest")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    plan = build_plan()
    output = _validate_output_path(args.output, require_absent=not args.resume)
    if args.dry_run:
        dry_run(plan, output)
        return 0
    execute_or_resume(
        plan,
        output,
        workers=args.workers,
        resume=bool(args.resume),
        confirmed_authorization=args.confirm_authorization_sha256,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
