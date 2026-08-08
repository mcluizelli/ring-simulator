"""Fail-closed paired n=5 timing gate for the two rate allocators.

This is a revalidation sidecar, not a production experiment.  Its scientific
matrix is fixed in this file: five sample IDs, eighteen arms, two allocators,
and ninety paired jobs.  It cannot start n=100, never writes under ``results``,
and refuses to overwrite an existing artifact.

Safe workflow (from the repository root)::

    python experiments/run_rate_allocator_pilot.py --dry-run \
        --output investigations/rate_allocator_pilot/n5_2026-08-06_01
    python experiments/run_rate_allocator_pilot.py --execute-pilot \
        --output investigations/rate_allocator_pilot/n5_2026-08-06_01 \
        --confirm-plan-sha256 <hash-from-dry-run> --workers 8

An interrupted run may be continued only with ``--resume --output <same-dir>``.
Checkpoints are one atomic JSON file per completed pair; workers never write.
"""

from __future__ import annotations

import os

# Set these before NumPy is imported in this process or spawned workers.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import argparse
import contextlib
import csv
import dataclasses
import hashlib
import io
import json
import math
import multiprocessing as mp
import platform
import random
import statistics
import struct
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sim  # noqa: E402


DRIVER_PATH = Path(__file__).resolve()
SIM_PATH = ROOT / "sim.py"
PILOT_ROOT = (ROOT / "investigations" / "rate_allocator_pilot").resolve()
FROZEN_MANIFEST = (
    ROOT
    / "investigations"
    / "rate_model_revalidation_2026_08_06"
    / "frozen_csv_sha256.txt"
)

SAMPLE_IDS = (0, 17, 43, 71, 99)
ALLOCATORS = (
    sim.RATE_ALLOCATOR_LINK_LOCAL,
    sim.RATE_ALLOCATOR_NETWORK_MAXMIN,
)
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

EXPECTED_FROZEN_COUNT = 63
EXPECTED_FROZEN_BYTES = 21_210_573
EXPECTED_FROZEN_ROOT = (
    "09a1418e965b9c2d597721ff0d3b1e8db937a19ce667accfa2cf1f469664c24e"
)
EXPECTED_FAMILY_PAIRS = {
    "static_split": 25,
    "congestion": 25,
    "controller": 20,
    "background": 20,
}
EXPECTED_RUNNER_ROWS = {
    "simple": 100,
    "proportional": 20,
    "adaptive": 20,
    "allreduce": 40,
}
N100_TARGET_SIMULATIONS = {
    "static_split": 16_200,
    "congestion": 3_200,
    "controller": 4_600,
    "background": 1_600,
    "placement_proxy": 1_200,
}

ORACLE_PATHS = {
    "equal": ROOT / "results" / "v10.1_k_saturation_n1000" / "results.csv",
    "proportional": ROOT / "results" / "v11.1_flexible_split_n1000" / "results.csv",
    "congestion": (
        ROOT
        / "results"
        / "v6.2_congestion_models_randomplacement_2026-07-27"
        / "results.csv"
    ),
    "controller": (
        ROOT
        / "results"
        / "v5.5_adaptive_n1000_placementfix"
        / "adaptive"
        / "results.csv"
    ),
    "background": ROOT / "results" / "v13.0_background_n1000" / "results.csv",
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return _sha256_bytes(_canonical_bytes(value))


def _f64_hex(value: Any) -> str:
    return struct.pack(">d", float(value)).hex()


def _finite_positive(value: Any, label: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise RuntimeError(f"{label} must be positive and finite; got {value!r}")
    return parsed


def _within_local_ulps(left: float, right: float, ulps: int = 64) -> bool:
    if left == right:
        return True
    if not math.isfinite(left) or not math.isfinite(right):
        return False
    return abs(left - right) <= ulps * max(math.ulp(left), math.ulp(right))


def _dataclass_config(instance: Any) -> Optional[Dict[str, Any]]:
    if instance is None:
        return None
    if not dataclasses.is_dataclass(instance):
        raise TypeError(f"expected dataclass config, got {type(instance)!r}")
    return {
        field.name: getattr(instance, field.name)
        for field in dataclasses.fields(instance)
    }


def _arm_specs() -> List[Dict[str, Any]]:
    common = {
        "topology_k": TOPO_K,
        "link_Gbps": LINK_GBPS,
        "dt_s": DT_S,
        "placement": "uniform_without_replacement",
    }
    congestion_common = {
        "affected_fraction": 0.3,
        "target_layers": ["agg_core", "edge_agg"],
    }
    arms: List[Dict[str, Any]] = [
        {
            **common,
            "arm_id": "nb_p64_equal_k8",
            "family": "static_split",
            "runner": "simple",
            "policy": "equal",
            "fabric": "3tier_nb",
            "n_tiers": 3,
            "oversub": 1.0,
            "ring_size": 64,
            "k": 8,
            "bytes_per_neighbor": 64 * MIB,
            "oracle_kind": "equal",
        },
        {
            **common,
            "arm_id": "os4_p64_equal_k1",
            "family": "static_split",
            "runner": "simple",
            "policy": "equal",
            "fabric": "3tier_os4",
            "n_tiers": 3,
            "oversub": 4.0,
            "ring_size": 64,
            "k": 1,
            "bytes_per_neighbor": 64 * MIB,
            "oracle_kind": "equal",
        },
        {
            **common,
            "arm_id": "os4_p64_equal_k32",
            "family": "static_split",
            "runner": "simple",
            "policy": "equal",
            "fabric": "3tier_os4",
            "n_tiers": 3,
            "oversub": 4.0,
            "ring_size": 64,
            "k": 32,
            "bytes_per_neighbor": 64 * MIB,
            "oracle_kind": "equal",
        },
        {
            **common,
            "arm_id": "os4_p64_prop_k16",
            "family": "static_split",
            "runner": "proportional",
            "policy": "proportional",
            "fabric": "3tier_os4",
            "n_tiers": 3,
            "oversub": 4.0,
            "ring_size": 64,
            "k": 16,
            "bytes_per_neighbor": 64 * MIB,
            "redistribution_window_s": 1e-3,
            "oracle_kind": "proportional",
        },
        {
            **common,
            "arm_id": "2tier_p64_equal_k32",
            "family": "static_split",
            "runner": "simple",
            "policy": "equal",
            "fabric": "2tier",
            "n_tiers": 2,
            "oversub": 1.0,
            "ring_size": 64,
            "k": 32,
            "bytes_per_neighbor": 64 * MIB,
            "oracle_kind": "equal",
        },
    ]

    congestion_models = {
        "onoff": {
            "congested_util_low": 0.50,
            "congested_util_high": 0.95,
            "normal_util_low": 0.0,
            "normal_util_high": 0.05,
            "p_on": 0.01,
            "p_off": 0.005,
        },
        "iid": {
            "congested_util_low": 0.50,
            "congested_util_high": 0.95,
            "normal_util_low": 0.0,
            "normal_util_high": 0.05,
        },
        "hot_spot": {
            "congested_util_low": 0.50,
            "congested_util_high": 0.95,
        },
        "microburst": {
            "burst_prob": 0.001,
            "burst_ticks": 2,
            "burst_util_low": 0.80,
            "burst_util_high": 0.98,
            "normal_util_low": 0.0,
            "normal_util_high": 0.05,
        },
    }
    for mode, params in congestion_models.items():
        arms.append(
            {
                **common,
                "arm_id": f"congestion_{mode}_p16_equal_k8",
                "family": "congestion",
                "runner": "simple",
                "policy": "equal",
                "fabric": "3tier_nb",
                "n_tiers": 3,
                "oversub": 1.0,
                "ring_size": 16,
                "k": 8,
                "bytes_per_neighbor": 256 * MIB,
                "congestion": {**congestion_common, "mode": mode, **params},
                "oracle_kind": "congestion",
            }
        )
    arms.append(
        {
            **common,
            "arm_id": "xoh_os4_p16_hotspot_prop_k8",
            "family": "congestion",
            "runner": "proportional",
            "policy": "proportional",
            "fabric": "3tier_os4",
            "n_tiers": 3,
            "oversub": 4.0,
            "ring_size": 16,
            "k": 8,
            "bytes_per_neighbor": 64 * MIB,
            "redistribution_window_s": 1e-3,
            "congestion": {
                **congestion_common,
                "mode": "hot_spot",
                "congested_util_low": 0.50,
                "congested_util_high": 0.95,
            },
            "oracle_kind": "new_diagnostic",
        }
    )

    controller_common = {
        **common,
        "family": "controller",
        "fabric": "3tier_nb",
        "n_tiers": 3,
        "oversub": 1.0,
        "ring_size": 64,
        "bytes_per_neighbor": 256 * MIB,
        "controller": {
            "measurement_window_s": 0.001,
            "threshold": 0.2,
            "k_max": 4,
            "cooldown_ticks": 200,
        },
        "oracle_kind": "controller",
    }
    arms.extend(
        [
            {
                **controller_common,
                "arm_id": "controller_af01_adaptive",
                "runner": "adaptive",
                "policy": "adaptive",
                "k": 1,
                "affected_fraction": 0.1,
                "frozen_method": "adaptive",
            },
            {
                **controller_common,
                "arm_id": "controller_af05_baseline",
                "runner": "simple",
                "policy": "equal",
                "k": 1,
                "affected_fraction": 0.5,
                "frozen_method": "baseline",
            },
            {
                **controller_common,
                "arm_id": "controller_af05_static_k4",
                "runner": "simple",
                "policy": "equal",
                "k": 4,
                "affected_fraction": 0.5,
                "frozen_method": "static(k=4)",
            },
            {
                **controller_common,
                "arm_id": "controller_af05_adaptive",
                "runner": "adaptive",
                "policy": "adaptive",
                "k": 1,
                "affected_fraction": 0.5,
                "frozen_method": "adaptive",
            },
        ]
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
        for rate in (0, 1000):
            arms.append(
                {
                    **background_common,
                    "arm_id": f"background_p16_k{k}_rate{rate}",
                    "k": k,
                    "arrival_rate_fps": rate,
                }
            )

    if len(arms) != 18:
        raise RuntimeError(f"fixed matrix must contain 18 arms, found {len(arms)}")
    if len({arm["arm_id"] for arm in arms}) != len(arms):
        raise RuntimeError("fixed matrix contains duplicate arm IDs")
    return arms


def _materialize_pair(arm: Mapping[str, Any], arm_index: int, sample_index: int) -> Dict[str, Any]:
    sample_id = SAMPLE_IDS[sample_index]
    config = json.loads(json.dumps(arm))
    config["sample_id"] = sample_id
    config["placement_seed"] = PLACEMENT_SEED_BASE + sample_id
    config["topology_seed"] = 1
    if config["family"] == "congestion":
        config["congestion_seed"] = 1000 + sample_id
    if config["family"] == "controller":
        topology_seed = CONTROLLER_SEED_BASE + sample_id * SEED_STRIDE
        config["topology_seed"] = topology_seed
        config["congestion"] = {
            "mode": "onoff",
            "seed": topology_seed + int(config["affected_fraction"] * 1000),
            "affected_fraction": config["affected_fraction"],
            "congested_util_low": 0.50,
            "congested_util_high": 0.95,
            "normal_util_low": 0.0,
            "normal_util_high": 0.05,
            "p_on": 0.01,
            "p_off": 0.005,
            "target_layers": ["agg_core", "edge_agg"],
        }
    elif "congestion" in config:
        config["congestion"]["seed"] = config["congestion_seed"]
    if config["family"] == "background":
        rate = int(config["arrival_rate_fps"])
        config["background_seed"] = (
            None
            if rate == 0
            else BACKGROUND_SEED_BASE + sample_id * SEED_STRIDE + rate
        )
    ordinal = arm_index * len(SAMPLE_IDS) + sample_index
    order = list(ALLOCATORS if ordinal % 2 == 0 else reversed(ALLOCATORS))
    pair_id = f"a{arm_index + 1:02d}_{config['arm_id']}__s{sample_id:03d}"
    oracle_key: Optional[Dict[str, Any]]
    kind = config["oracle_kind"]
    if kind in {"equal", "proportional"}:
        oracle_key = {
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
    else:
        oracle_key = None
    return {
        "pair_id": pair_id,
        "arm_index": arm_index,
        "sample_index": sample_index,
        "sample_id": sample_id,
        "execution_order": order,
        "config": config,
        "config_sha256": _digest(config),
        "oracle_key": oracle_key,
    }


def build_plan() -> Dict[str, Any]:
    arms = _arm_specs()
    pairs = [
        _materialize_pair(arm, arm_index, sample_index)
        for arm_index, arm in enumerate(arms)
        for sample_index, _ in enumerate(SAMPLE_IDS)
    ]
    if len(pairs) != 90:
        raise RuntimeError(f"fixed pilot must contain 90 pairs, found {len(pairs)}")
    if len({pair["pair_id"] for pair in pairs}) != 90:
        raise RuntimeError("fixed pilot contains duplicate pair IDs")
    family_counts = {
        family: sum(pair["config"]["family"] == family for pair in pairs)
        for family in EXPECTED_FAMILY_PAIRS
    }
    if family_counts != EXPECTED_FAMILY_PAIRS:
        raise RuntimeError(f"family counts changed: {family_counts}")
    per_sample = {
        sample: sum(pair["sample_id"] == sample for pair in pairs)
        for sample in SAMPLE_IDS
    }
    if set(per_sample.values()) != {18}:
        raise RuntimeError(f"each sample must contain 18 pairs: {per_sample}")
    first_allocator = {
        allocator: sum(pair["execution_order"][0] == allocator for pair in pairs)
        for allocator in ALLOCATORS
    }
    if first_allocator != {ALLOCATORS[0]: 45, ALLOCATORS[1]: 45}:
        raise RuntimeError(f"allocator order is not balanced: {first_allocator}")
    scientific = {
        "schema": "rate-allocator-pilot-plan-v1",
        "sample_ids": list(SAMPLE_IDS),
        "allocators": list(ALLOCATORS),
        "arms": arms,
        "pairs": pairs,
        "pair_count": 90,
        "simulation_count": 180,
        "family_pair_counts": family_counts,
        "no_n100_execution_path": True,
    }
    scientific["plan_sha256"] = _digest(scientific)
    return scientific


def _authorization_sha256(
    plan: Mapping[str, Any],
    *,
    sim_hash: Optional[str] = None,
    driver_hash: Optional[str] = None,
) -> str:
    """Bind execution approval to the matrix and both executable sources."""
    return _digest(
        {
            "plan_sha256": plan["plan_sha256"],
            "sim_sha256": sim_hash or _sha256_file(SIM_PATH),
            "driver_sha256": driver_hash or _sha256_file(DRIVER_PATH),
        }
    )


def _validate_output_path(raw: str, *, require_absent: bool) -> Path:
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    resolved = candidate.resolve()
    if resolved == PILOT_ROOT or PILOT_ROOT not in resolved.parents:
        raise RuntimeError(
            f"output must be a new child of {PILOT_ROOT}; got {resolved}"
        )
    results_root = (ROOT / "results").resolve()
    if resolved == results_root or results_root in resolved.parents:
        raise RuntimeError("pilot output is forbidden inside results/")
    if require_absent and resolved.exists():
        raise FileExistsError(
            f"refusing existing output {resolved}; use --resume or a new path"
        )
    return resolved


def audit_frozen_csvs() -> Dict[str, Any]:
    raw_lines = FROZEN_MANIFEST.read_text(encoding="utf-8").splitlines()
    data_lines = [line for line in raw_lines if line.strip() and not line.startswith("#")]
    if len(data_lines) != EXPECTED_FROZEN_COUNT:
        raise RuntimeError(f"frozen manifest has {len(data_lines)} entries, expected 63")
    mismatches = []
    total_bytes = 0
    for line in data_lines:
        expected_hash, raw_size, relative = line.split(maxsplit=2)
        expected_size = int(raw_size)
        path = ROOT / relative
        if not path.is_file():
            mismatches.append({"path": relative, "reason": "missing"})
            continue
        actual_size = path.stat().st_size
        actual_hash = _sha256_file(path)
        total_bytes += actual_size
        if actual_size != expected_size or actual_hash != expected_hash:
            mismatches.append(
                {
                    "path": relative,
                    "expected_bytes": expected_size,
                    "actual_bytes": actual_size,
                    "expected_sha256": expected_hash,
                    "actual_sha256": actual_hash,
                }
            )
    root_hash = _sha256_bytes("\n".join(data_lines).encode("utf-8"))
    if mismatches:
        raise RuntimeError(f"frozen CSV mutation detected: {mismatches[:3]}")
    if total_bytes != EXPECTED_FROZEN_BYTES or root_hash != EXPECTED_FROZEN_ROOT:
        raise RuntimeError(
            f"frozen snapshot identity changed: bytes={total_bytes}, root={root_hash}"
        )
    return {
        "count": len(data_lines),
        "total_bytes": total_bytes,
        "root_sha256": root_hash,
        "manifest_sha256": _sha256_file(FROZEN_MANIFEST),
        "mismatches": 0,
    }


def snapshot_results_tree() -> Dict[str, Any]:
    root = ROOT / "results"
    rows = []
    total_bytes = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(ROOT).as_posix()
        size = path.stat().st_size
        rows.append([relative, size, _sha256_file(path)])
        total_bytes += size
    return {
        "file_count": len(rows),
        "total_bytes": total_bytes,
        "root_sha256": _digest(rows),
    }


def _git_state() -> Dict[str, Any]:
    def run(*args: str) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout

    status = run("status", "--porcelain=v1")
    return {
        "head": run("rev-parse", "HEAD").strip(),
        "dirty": bool(status),
        "status_sha256": _sha256_bytes(status.encode("utf-8")),
        "status_lines": status.splitlines(),
    }


def _atomic_write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == payload:
            return
        raise FileExistsError(f"refusing to overwrite non-identical artifact {path}")
    staging = path.parent / ".staging"
    staging.mkdir(exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb", delete=False, dir=staging, prefix=f".{path.name}.tmp-"
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # Linking a fully flushed same-filesystem temporary file is an atomic
        # create-if-absent operation on NTFS and POSIX filesystems.  Unlike
        # os.replace(), it can never overwrite a target that appears in a race.
        os.link(temp_path, path)
        temp_path.unlink()
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _atomic_json_once(path: Path, value: Any) -> None:
    payload = json.dumps(
        value,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    _atomic_write_once(path, payload)


class ExclusiveRunLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any = None

    def __enter__(self) -> "ExclusiveRunLock":
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
            os.fsync(self.handle.fileno())
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            raise RuntimeError(f"another process holds {self.path}") from exc
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.handle is None:
            return
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


def _config_rng_payload(config: Any, rng: Any) -> Any:
    return {
        "config": _dataclass_config(config),
        "rng_state": repr(rng.getstate()) if rng is not None else None,
    }


class PilotAuditedSimulator(sim.FlowLevelSimulator):
    """Behavior-preserving capture seam used only inside a worker call."""

    registry: List["PilotAuditedSimulator"] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.requested_bytes: Dict[int, float] = {}
        congestion_payload = None
        if self.congestion is not None:
            congestion_payload = {
                **_config_rng_payload(self.congestion, self.congestion.rng),
                "affected_edges": list(self.congestion._affected or []),
                "state": sorted(self.congestion._state.items()),
                "util": sorted(self.congestion._util.items()),
                "burst_remaining": sorted(self.congestion._burst_remaining.items()),
            }
        background_payload = None
        if self.background is not None:
            background_payload = _config_rng_payload(
                self.background.cfg, self.background.rng
            )
        self.initial_process_sha256 = _digest(
            {"congestion": congestion_payload, "background": background_payload}
        )
        self.__class__.registry.append(self)

    def add_flow(self, five_tuple: sim.Flow5Tuple, bytes_to_send: float) -> int:
        fid = super().add_flow(five_tuple, bytes_to_send)
        self.requested_bytes[fid] = float(bytes_to_send)
        return fid


@contextlib.contextmanager
def _captured_simulator() -> Iterable[type[PilotAuditedSimulator]]:
    original = sim.FlowLevelSimulator
    PilotAuditedSimulator.registry = []
    sim.FlowLevelSimulator = PilotAuditedSimulator
    try:
        yield PilotAuditedSimulator
    finally:
        sim.FlowLevelSimulator = original
        if sim.FlowLevelSimulator is not original:
            raise RuntimeError("FlowLevelSimulator audit seam was not restored")


def _topology_digest(topo: sim.FatTree) -> str:
    return _digest(sorted((u, v, cap) for (u, v), cap in topo.edge_of.items()))


def _ring_digest(ring: Sequence[str]) -> str:
    return _digest(list(ring))


def _route_digest(config: Mapping[str, Any], topo: sim.FatTree, ring: Sequence[str]) -> str:
    rows = []
    p = len(ring)
    runner = config["runner"]
    if runner in {"simple", "proportional"}:
        k_values = range(int(config["k"]))
        for i in range(p):
            for j in k_values:
                five = sim.Flow5Tuple(
                    src=ring[i],
                    dst=ring[(i + 1) % p],
                    sport=10000 + i * 100 + j,
                    dport=20000,
                    proto=6,
                )
                rows.append([i, j, dataclasses.astuple(five), topo.ecmp_pick_path(five)])
    elif runner == "adaptive":
        k_max = int(config["controller"]["k_max"])
        for i in range(p):
            for j in range(k_max):
                five = sim.Flow5Tuple(
                    src=ring[i],
                    dst=ring[(i + 1) % p],
                    sport=10000 + i * 100 + j,
                    dport=20000,
                    proto=6,
                )
                rows.append([i, j, dataclasses.astuple(five), topo.ecmp_pick_path(five)])
    elif runner == "allreduce":
        steps = 2 * (p - 1)
        k = int(config["k"])
        for step in range(steps):
            for i in range(p):
                for j in range(k):
                    five = sim.Flow5Tuple(
                        src=ring[i],
                        dst=ring[(i + 1) % p],
                        sport=50000 + step * 10_000 + i * 100 + j,
                        dport=51000,
                        proto=6,
                    )
                    rows.append(
                        [step, i, j, dataclasses.astuple(five), topo.ecmp_pick_path(five)]
                    )
    else:
        raise RuntimeError(f"unknown runner for route digest: {runner}")
    return _digest(rows)


def _make_topology_and_ring(config: Mapping[str, Any]) -> Tuple[sim.FatTree, List[str]]:
    topo = sim.FatTree(
        k=int(config["topology_k"]),
        link_capacity_Gbps=float(config["link_Gbps"]),
        seed=int(config["topology_seed"]),
        n_tiers=int(config["n_tiers"]),
        oversub=float(config["oversub"]),
    )
    ring = random.Random(int(config["placement_seed"])).sample(
        topo.hosts, int(config["ring_size"])
    )
    return topo, ring


def _make_congestion(config: Mapping[str, Any]) -> Optional[sim.CongestionModel]:
    raw = config.get("congestion")
    if raw is None:
        return None
    return sim.CongestionModel(**dict(raw))


def _make_background(config: Mapping[str, Any]) -> Optional[sim.BackgroundTrafficConfig]:
    if config["family"] != "background" or int(config["arrival_rate_fps"]) <= 0:
        return None
    raw = dict(config["background"])
    return sim.BackgroundTrafficConfig(
        seed=int(config["background_seed"]),
        arrival_rate_fps=float(config["arrival_rate_fps"]),
        **raw,
    )


def _foreground_flows(
    engine: PilotAuditedSimulator, runner: str
) -> List[sim.Flow]:
    dport = 51000 if runner == "allreduce" else 20000
    return [flow for flow in engine.flows.values() if flow.five_tuple.dport == dport]


PROPORTIONAL_CONSERVATION_ULPS = 128


def _binary64_roundoff_tolerance(target: float) -> float:
    """Return the fixed byte floor or 128 ULPs at the target scale."""
    numeric = float(target)
    if not math.isfinite(numeric) or numeric <= 0.0:
        raise ValueError("roundoff-tolerance target must be finite and positive")
    return max(
        1e-6,
        PROPORTIONAL_CONSERVATION_ULPS * math.ulp(numeric),
    )


def _conservation_gate(
    config: Mapping[str, Any], result: Any, engine: PilotAuditedSimulator
) -> Dict[str, Any]:
    runner = str(config["runner"])
    flows = _foreground_flows(engine, runner)
    remaining = sum(max(0.0, flow.remaining_bytes) for flow in flows)
    maximum_error = 0.0
    checks = 0
    non_bit_exact_flow_count = 0
    maximum_per_flow_error = 0.0
    proportional_roundoff_tolerance: Optional[float] = None

    if runner == "simple":
        target = float(config["bytes_per_neighbor"])
        by_edge: Dict[Tuple[str, str], List[sim.Flow]] = {}
        for flow in flows:
            by_edge.setdefault((flow.five_tuple.src, flow.five_tuple.dst), []).append(flow)
        if len(by_edge) != int(config["ring_size"]):
            raise RuntimeError("simple runner captured the wrong number of logical edges")
        completion = float(result)
        for edge_flows in by_edge.values():
            delivered = sum(flow.sent_bytes for flow in edge_flows)
            error = abs(delivered - target)
            maximum_error = max(maximum_error, error)
            checks += 1
            # Thousands of binary64 increments can leave the accumulated byte
            # counter a few target ULPs from the exact integer.  Keep this gate
            # local to rounding scale rather than using a scientific byte-level
            # allowance (empirical pilot maximum before this fix: 24.5 ULPs).
            simple_tolerance = max(1e-6, 64 * math.ulp(target))
            if error > simple_tolerance:
                raise RuntimeError(f"simple byte-conservation error {error} B")
    elif runner == "proportional":
        target = float(config["bytes_per_neighbor"])
        delivered = result["per_edge_delivered_bytes"]
        if len(delivered) != int(config["ring_size"]):
            raise RuntimeError("proportional runner returned the wrong logical-edge count")
        delivered_values = [float(value) for value in delivered.values()]
        if any(not math.isfinite(value) for value in delivered_values):
            raise RuntimeError("proportional runner returned non-finite delivered bytes")
        proportional_roundoff_tolerance = _binary64_roundoff_tolerance(target)
        for value in delivered_values:
            error = abs(value - target)
            maximum_error = max(maximum_error, error)
            checks += 1
            if error > proportional_roundoff_tolerance:
                raise RuntimeError(f"proportional byte-conservation error {error} B")
    elif runner == "adaptive":
        target = float(config["bytes_per_neighbor"])
        by_edge: Dict[Tuple[str, str], List[sim.Flow]] = {}
        for flow in flows:
            by_edge.setdefault((flow.five_tuple.src, flow.five_tuple.dst), []).append(flow)
        if len(by_edge) != int(config["ring_size"]):
            raise RuntimeError("adaptive runner returned the wrong logical-edge count")
        for edge_flows in by_edge.values():
            delivered = sum(flow.sent_bytes for flow in edge_flows)
            edge_remaining = sum(max(0.0, flow.remaining_bytes) for flow in edge_flows)
            error = abs(delivered - target)
            maximum_error = max(maximum_error, error, edge_remaining)
            checks += 1
            # Summing up to k_max independently accumulated binary64 counters can
            # land a few ULPs above the exact target even though every individual
            # send is capped by remaining_bytes.  Preserve the scientific 1-byte
            # completion gate while treating only local rounding-scale overshoot
            # (64 target ULPs) as non-material.
            overdelivery_tolerance = max(1e-6, 64 * math.ulp(target))
            if (
                delivered > target + overdelivery_tolerance
                or error > 1.0
                or edge_remaining > 1.0
            ):
                raise RuntimeError(
                    "adaptive byte-conservation "
                    f"delivered_minus_target={delivered - target} "
                    f"error={error} remaining={edge_remaining} B"
                )
    elif runner == "allreduce":
        p = int(config["ring_size"])
        k = int(config["k"])
        expected_count = 2 * (p - 1) * p * k
        if len(flows) != expected_count:
            raise RuntimeError(
                f"AllReduce foreground flow count {len(flows)} != {expected_count}"
            )
        step_sent: Dict[int, float] = {}
        for flow in flows:
            requested = engine.requested_bytes[flow.fid]
            flow_error = abs(flow.sent_bytes - requested)
            maximum_per_flow_error = max(maximum_per_flow_error, flow_error)
            maximum_error = max(maximum_error, flow_error)
            if _f64_hex(flow.sent_bytes) != _f64_hex(requested):
                non_bit_exact_flow_count += 1
            if not _within_local_ulps(flow.sent_bytes, requested, ulps=64):
                raise RuntimeError(
                    f"AllReduce flow {flow.fid} sent {flow.sent_bytes} != requested {requested}"
                )
            if flow.remaining_bytes != 0.0:
                raise RuntimeError(f"AllReduce flow {flow.fid} has remaining bytes")
            step = (flow.five_tuple.sport - 50000) // 10_000
            step_sent[step] = step_sent.get(step, 0.0) + flow.sent_bytes
        if sorted(step_sent) != list(range(2 * (p - 1))):
            raise RuntimeError("AllReduce step IDs are incomplete")
        per_step_target = float(config["total_bytes"])
        for sent in step_sent.values():
            error = abs(sent - per_step_target)
            maximum_error = max(maximum_error, error)
            checks += 1
            tolerance = 64 * max(math.ulp(sent), math.ulp(per_step_target))
            if error > tolerance:
                raise RuntimeError(f"AllReduce step conservation error {error} B")
        total_expected = 2 * (p - 1) * per_step_target
        total_sent = sum(flow.sent_bytes for flow in flows)
        total_error = abs(total_sent - total_expected)
        maximum_error = max(maximum_error, total_error)
        if total_error > 64 * max(math.ulp(total_sent), math.ulp(total_expected)):
            raise RuntimeError(f"AllReduce total conservation error {total_error} B")
    else:
        raise RuntimeError(f"unknown runner {runner}")

    verdict = {
        "passed": True,
        "foreground_flow_count": len(flows),
        "checks": checks,
        "remaining_foreground_bytes": remaining,
        "maximum_abs_error_bytes": maximum_error,
        "maximum_abs_error_bytes_hex": _f64_hex(maximum_error),
        "non_bit_exact_flow_count": non_bit_exact_flow_count,
        "maximum_per_flow_error_bytes": maximum_per_flow_error,
        "maximum_per_flow_error_bytes_hex": _f64_hex(maximum_per_flow_error),
    }
    if proportional_roundoff_tolerance is not None:
        verdict.update(
            {
                "roundoff_tolerance_B": proportional_roundoff_tolerance,
                "roundoff_tolerance_B_hex": _f64_hex(
                    proportional_roundoff_tolerance
                ),
                "roundoff_tolerance_ulps": PROPORTIONAL_CONSERVATION_ULPS,
            }
        )
    return verdict


def _adaptive_gate(result: Mapping[str, Any]) -> Dict[str, Any]:
    final_map = result["final_k_per_edge"]
    history = list(result["k_history"])
    completion = float(result["completion_time_s"])
    if len(final_map) != 64:
        raise RuntimeError(f"adaptive final map has {len(final_map)} edges, expected 64")
    if any(int(k) < 1 or int(k) > 4 for k in final_map.values()):
        raise RuntimeError("adaptive final k outside [1,4]")
    if history != sorted(history, key=lambda item: item[0]):
        raise RuntimeError("adaptive history is not time ordered")
    current = {index: 1 for index in range(64)}
    for event_time, edge_index, new_k in history:
        if float(event_time) > completion:
            raise RuntimeError("adaptive event occurs after completion")
        edge_index = int(edge_index)
        if int(new_k) != current[edge_index] + 1:
            raise RuntimeError("adaptive event does not increment k by one")
        current[edge_index] = int(new_k)
    final_by_index = {
        index: int(final_map[edge]) for index, edge in enumerate(final_map)
    }
    if current != final_by_index:
        raise RuntimeError("adaptive event history does not reconstruct final k")
    event_count = len(history)
    expected_events = sum(int(k) - 1 for k in final_map.values())
    if event_count != expected_events:
        raise RuntimeError("adaptive event count disagrees with final k map")
    return {
        "passed": True,
        "edge_count": len(final_map),
        "event_count": event_count,
        "final_k_mean": statistics.fmean(int(k) for k in final_map.values()),
        "final_k_max": max(int(k) for k in final_map.values()),
    }


def _run_one(
    pair: Mapping[str, Any], allocator: str
) -> Tuple[Dict[str, Any], Tuple[Any, ...]]:
    total_wall_start = time.perf_counter()
    total_cpu_start = time.process_time()
    config = pair["config"]
    topo, ring = _make_topology_and_ring(config)
    congestion = _make_congestion(config)
    background_cfg = _make_background(config)
    topology_sha = _topology_digest(topo)
    ring_sha = _ring_digest(ring)
    route_sha = _route_digest(config, topo, ring)

    simulation_wall_start = time.perf_counter()
    simulation_cpu_start = time.process_time()
    with _captured_simulator() as capture:
        runner = config["runner"]
        if runner == "simple":
            result = sim.run_simple_ring_transfer(
                topo=topo,
                ring=ring,
                bytes_per_neighbor=float(config["bytes_per_neighbor"]),
                flows_per_neighbor=int(config["k"]),
                dt_s=float(config["dt_s"]),
                congestion=congestion,
                rate_allocator=allocator,
            )
            completion = float(result)
        elif runner == "proportional":
            result = sim.run_ring_transfer_proportional(
                topo=topo,
                ring=ring,
                bytes_per_neighbor=float(config["bytes_per_neighbor"]),
                flows_per_neighbor=int(config["k"]),
                dt_s=float(config["dt_s"]),
                window_s=float(config["redistribution_window_s"]),
                congestion=congestion,
                return_metrics=True,
                rate_allocator=allocator,
            )
            completion = float(result["completion_time_s"])
        elif runner == "adaptive":
            adaptive_cfg = sim.AdaptiveConfig(**dict(config["controller"]))
            result = sim.run_adaptive_ring_transfer(
                topo=topo,
                ring=ring,
                bytes_per_neighbor=float(config["bytes_per_neighbor"]),
                adaptive_cfg=adaptive_cfg,
                dt_s=float(config["dt_s"]),
                congestion=congestion,
                rate_allocator=allocator,
            )
            completion = float(result["completion_time_s"])
        elif runner == "allreduce":
            result = sim.run_ring_allreduce(
                topo=topo,
                ring=ring,
                total_bytes_M=float(config["total_bytes"]),
                flows_per_neighbor=int(config["k"]),
                dt_s=float(config["dt_s"]),
                pipelined=bool(config["pipelined"]),
                pipeline_window=int(config["pipeline_window"]),
                alpha_s=float(config["alpha_s"]),
                background_cfg=background_cfg,
                rate_allocator=allocator,
            )
            completion = float(result.total_time_s)
        else:
            raise RuntimeError(f"unknown runner {runner}")
    simulation_cpu_time = time.process_time() - simulation_cpu_start
    simulation_wall_time = time.perf_counter() - simulation_wall_start
    if len(capture.registry) != 1:
        raise RuntimeError(
            f"runner created {len(capture.registry)} simulator instances; expected one"
        )
    engine = capture.registry[0]
    conservation = _conservation_gate(config, result, engine)
    adaptive = _adaptive_gate(result) if config["runner"] == "adaptive" else None

    actual: Dict[str, Any] = {"completion_time_s": completion}
    scalar_metrics: Dict[str, Any] = {}
    if config["oracle_kind"] == "equal":
        reference = sim.compute_ring_theoretical_time(
            topo=topo,
            ring=ring,
            bytes_per_neighbor=float(config["bytes_per_neighbor"]),
            flows_per_neighbor=int(config["k"]),
            rate_allocator=allocator,
        )
        theory = float(reference["theoretical_time_s"])
        bstar = float(reference["bottleneck_bandwidth_Bps"])
        layers = topo.get_edges_by_layer()
        top = layers["agg_core"] if int(config["n_tiers"]) == 3 else layers["leaf_spine"]
        contention = reference["edge_contention"]
        top_used = sum(1 for edge in top if contention.get(edge, 0) > 0)
        max_top = max((contention.get(edge, 0) for edge in top), default=0)
        actual.update(
            {
                "t_sim": completion,
                "opt_time": theory,
                "equal_split_gap": completion / theory - 1.0,
                "Bstar_Bps": bstar,
                "top_used": top_used,
                "max_top_contention": max_top,
            }
        )
        scalar_metrics.update(
            {"theoretical_time_s": theory, "bottleneck_bandwidth_Bps": bstar}
        )
    elif config["oracle_kind"] == "proportional":
        actual["t_prop"] = completion
    elif config["oracle_kind"] == "congestion":
        actual["completion_time_s"] = completion
    elif config["oracle_kind"] == "controller":
        if adaptive is None:
            final_k_mean = float(config["k"])
            final_k_max = int(config["k"])
        else:
            final_k_mean = float(adaptive["final_k_mean"])
            final_k_max = int(adaptive["final_k_max"])
        actual.update(
            {"final_k_mean": final_k_mean, "final_k_max": final_k_max}
        )
        scalar_metrics.update(
            {
                "final_k_mean": final_k_mean,
                "final_k_max": final_k_max,
                "adaptive_event_count": adaptive["event_count"] if adaptive else 0,
            }
        )
    elif config["oracle_kind"] == "background":
        steps = np.asarray(result.step_times_s, dtype=float)
        if len(steps) != 30:
            raise RuntimeError(f"AllReduce returned {len(steps)} step times, expected 30")
        actual.update(
            {
                "allreduce_time_s": completion,
                "mean_step_s": float(steps.mean()),
                "p99_step_s": float(np.percentile(steps, 99)),
                "max_step_s": float(steps.max()),
            }
        )
        scalar_metrics.update(
            {
                "mean_step_s": actual["mean_step_s"],
                "p99_step_s": actual["p99_step_s"],
                "max_step_s": actual["max_step_s"],
                "step_count": len(steps),
            }
        )

    cpu_time = time.process_time() - total_cpu_start
    wall_time = time.perf_counter() - total_wall_start
    _finite_positive(completion, "completion time")
    _finite_positive(wall_time, "wall time")
    _finite_positive(cpu_time, "CPU time")
    row = {
        "pair_id": pair["pair_id"],
        "arm_id": config["arm_id"],
        "sample_id": pair["sample_id"],
        "family": config["family"],
        "runner": config["runner"],
        "policy": config["policy"],
        "allocator": allocator,
        "execution_position": pair["execution_order"].index(allocator),
        "config_sha256": pair["config_sha256"],
        "topology_sha256": topology_sha,
        "ring_sha256": ring_sha,
        "route_sha256": route_sha,
        "process_initial_sha256": engine.initial_process_sha256,
        "topology_instance_id": id(topo),
        "simulator_instance_id": id(engine),
        "congestion_instance_id": id(congestion) if congestion is not None else None,
        "background_instance_id": (
            id(engine.background) if engine.background is not None else None
        ),
        "completion_time_s": completion,
        "completion_time_hex": _f64_hex(completion),
        "simulated_ticks": int(round(engine.time_s / float(config["dt_s"]))),
        "wall_time_s": wall_time,
        "wall_time_hex": _f64_hex(wall_time),
        "cpu_time_s": cpu_time,
        "cpu_time_hex": _f64_hex(cpu_time),
        "simulation_wall_time_s": simulation_wall_time,
        "simulation_wall_time_hex": _f64_hex(simulation_wall_time),
        "simulation_cpu_time_s": simulation_cpu_time,
        "simulation_cpu_time_hex": _f64_hex(simulation_cpu_time),
        "scalar_metrics": scalar_metrics,
        "conservation": conservation,
        "adaptive_gate": adaptive,
        "oracle_actual": actual,
    }
    refs = (topo, ring, congestion, background_cfg, engine)
    return row, refs


_WORKER_SIM_HASH = ""
_WORKER_DRIVER_HASH = ""


def _verify_source_hashes(sim_hash: str, driver_hash: str) -> None:
    if _sha256_file(SIM_PATH) != sim_hash:
        raise RuntimeError("sim.py changed after the pilot was authorized")
    if _sha256_file(DRIVER_PATH) != driver_hash:
        raise RuntimeError("pilot driver changed after dry-run authorization")


def _worker_init(sim_hash: str, driver_hash: str) -> None:
    global _WORKER_SIM_HASH, _WORKER_DRIVER_HASH
    _WORKER_SIM_HASH = sim_hash
    _WORKER_DRIVER_HASH = driver_hash
    _verify_source_hashes(sim_hash, driver_hash)


def _run_pair_worker(pair: Mapping[str, Any]) -> Dict[str, Any]:
    _verify_source_hashes(_WORKER_SIM_HASH, _WORKER_DRIVER_HASH)
    rows = []
    retained_refs = []
    for allocator in pair["execution_order"]:
        row, refs = _run_one(pair, allocator)
        rows.append(row)
        retained_refs.append(refs)
        _verify_source_hashes(_WORKER_SIM_HASH, _WORKER_DRIVER_HASH)
    by_allocator = {row["allocator"]: row for row in rows}
    if set(by_allocator) != set(ALLOCATORS):
        raise RuntimeError("paired worker did not return both allocators")
    for field in (
        "config_sha256",
        "topology_sha256",
        "ring_sha256",
        "route_sha256",
        "process_initial_sha256",
    ):
        if len({row[field] for row in rows}) != 1:
            raise RuntimeError(f"paired initial-state mismatch in {field}")
    for field in (
        "topology_instance_id",
        "simulator_instance_id",
        "congestion_instance_id",
        "background_instance_id",
    ):
        values = [row[field] for row in rows if row[field] is not None]
        if len(values) == 2 and len(set(values)) != 2:
            raise RuntimeError(f"paired runs reused mutable instance {field}")
    return {
        "schema": "rate-allocator-pair-checkpoint-v1",
        "pair_id": pair["pair_id"],
        "pair_spec": pair,
        "rows": rows,
        "pair_gate": {
            "passed": True,
            "initial_digests_equal": True,
            "mutable_instances_distinct": True,
        },
    }


def _read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _oracle_indexes() -> Dict[str, Dict[Tuple[Any, ...], Dict[str, str]]]:
    def unique_index(
        kind: str, rows: Sequence[Dict[str, str]], key_fn: Any
    ) -> Dict[Tuple[Any, ...], Dict[str, str]]:
        index: Dict[Tuple[Any, ...], Dict[str, str]] = {}
        for row in rows:
            key = key_fn(row)
            if key in index:
                raise RuntimeError(f"duplicate frozen oracle key in {kind}: {key}")
            index[key] = row
        return index

    equal = unique_index(
        "equal",
        _read_csv(ORACLE_PATHS["equal"]),
        lambda row: (row["fabric"], int(row["P"]), int(row["seed"]), int(row["k"])),
    )
    proportional = unique_index(
        "proportional",
        _read_csv(ORACLE_PATHS["proportional"]),
        lambda row: (row["fabric"], int(row["P"]), int(row["seed"]), int(row["k"])),
    )
    congestion = unique_index(
        "congestion",
        _read_csv(ORACLE_PATHS["congestion"]),
        lambda row: (row["model"], int(row["seed"]), int(row["k"])),
    )
    controller = unique_index(
        "controller",
        _read_csv(ORACLE_PATHS["controller"]),
        lambda row: (
            int(row["run"]),
            int(row["seed"]),
            int(row["ring_size"]),
            float(row["affected_fraction"]),
            row["method"],
        ),
    )
    background = unique_index(
        "background",
        _read_csv(ORACLE_PATHS["background"]),
        lambda row: (int(row["run"]), int(row["k"]), int(row["arrival_rate_fps"])),
    )
    return {
        "equal": equal,
        "proportional": proportional,
        "congestion": congestion,
        "controller": controller,
        "background": background,
    }


def _oracle_row(
    pair: Mapping[str, Any], indexes: Mapping[str, Mapping[Tuple[Any, ...], Dict[str, str]]]
) -> Optional[Dict[str, str]]:
    kind = pair["config"]["oracle_kind"]
    key = pair["oracle_key"]
    if kind == "new_diagnostic":
        return None
    if kind in {"equal", "proportional"}:
        packed = (key["fabric"], int(key["P"]), int(key["seed"]), int(key["k"]))
    elif kind == "congestion":
        packed = (key["model"], int(key["seed"]), int(key["k"]))
    elif kind == "controller":
        packed = (
            int(key["run"]),
            int(key["seed"]),
            int(key["ring_size"]),
            float(key["affected_fraction"]),
            key["method"],
        )
    elif kind == "background":
        packed = (int(key["run"]), int(key["k"]), int(key["arrival_rate_fps"]))
    else:
        raise RuntimeError(f"unknown oracle kind {kind}")
    try:
        return dict(indexes[kind][packed])
    except KeyError as exc:
        raise RuntimeError(f"missing frozen oracle row {kind} {packed}") from exc


def _attach_oracle_verdict(
    checkpoint: Dict[str, Any], indexes: Mapping[str, Mapping[Tuple[Any, ...], Dict[str, str]]]
) -> None:
    pair = checkpoint["pair_spec"]
    kind = pair["config"]["oracle_kind"]
    legacy = next(row for row in checkpoint["rows"] if row["allocator"] == LEGACY_ALLOCATOR)
    if kind == "new_diagnostic":
        legacy["oracle_verdict"] = {
            "status": "new_diagnostic",
            "exact_frozen_source": None,
        }
    else:
        frozen = _oracle_row(pair, indexes)
        if frozen is None:
            raise RuntimeError("oracle unexpectedly absent")
        if kind == "equal":
            float_fields = ["t_sim", "opt_time", "equal_split_gap", "Bstar_Bps"]
            int_fields = ["top_used", "max_top_contention"]
        elif kind == "proportional":
            float_fields = ["t_prop"]
            int_fields = []
        elif kind == "congestion":
            float_fields = ["completion_time_s"]
            int_fields = []
        elif kind == "controller":
            float_fields = ["completion_time_s", "final_k_mean"]
            int_fields = ["final_k_max"]
        elif kind == "background":
            float_fields = [
                "allreduce_time_s",
                "mean_step_s",
                "p99_step_s",
                "max_step_s",
            ]
            int_fields = []
        else:
            raise RuntimeError(f"unsupported oracle kind {kind}")
        comparisons = {}
        for field in float_fields:
            actual_hex = _f64_hex(legacy["oracle_actual"][field])
            expected_hex = _f64_hex(frozen[field])
            comparisons[field] = {
                "actual_hex": actual_hex,
                "expected_hex": expected_hex,
                "equal": actual_hex == expected_hex,
            }
        for field in int_fields:
            actual = int(legacy["oracle_actual"][field])
            expected = int(frozen[field])
            comparisons[field] = {
                "actual": actual,
                "expected": expected,
                "equal": actual == expected,
            }
        failures = [field for field, verdict in comparisons.items() if not verdict["equal"]]
        if failures:
            raise RuntimeError(
                f"legacy result mismatch for {pair['pair_id']}: {failures}"
            )
        legacy["oracle_verdict"] = {
            "status": "exact_binary64_match",
            "source": ORACLE_PATHS[kind].relative_to(ROOT).as_posix(),
            "key": pair["oracle_key"],
            "comparisons": comparisons,
        }
    maxmin = next(row for row in checkpoint["rows"] if row["allocator"] == MAXMIN_ALLOCATOR)
    maxmin["oracle_verdict"] = {
        "status": "not_applicable_new_allocator",
        "exact_frozen_source": None,
    }


def _checkpoint_path(output: Path, pair_id: str) -> Path:
    return output / "checkpoints" / f"{pair_id}.json"


def _load_checkpoint(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"malformed checkpoint {path}") from exc
    return value


def _validate_checkpoint(
    checkpoint: Dict[str, Any], pair: Mapping[str, Any], plan_hash: str
) -> None:
    if checkpoint.get("schema") != "rate-allocator-pair-checkpoint-v1":
        raise RuntimeError(f"wrong checkpoint schema for {pair['pair_id']}")
    if checkpoint.get("pair_id") != pair["pair_id"]:
        raise RuntimeError(f"checkpoint pair ID mismatch for {pair['pair_id']}")
    if checkpoint.get("pair_spec") != pair:
        raise RuntimeError(f"checkpoint specification mismatch for {pair['pair_id']}")
    if checkpoint.get("plan_sha256") != plan_hash:
        raise RuntimeError(f"checkpoint plan hash mismatch for {pair['pair_id']}")
    rows = checkpoint.get("rows", [])
    if len(rows) != 2 or {row.get("allocator") for row in rows} != set(ALLOCATORS):
        raise RuntimeError(f"incomplete checkpoint for {pair['pair_id']}")
    for row in rows:
        if row.get("pair_id") != pair["pair_id"]:
            raise RuntimeError(f"checkpoint row ID mismatch for {pair['pair_id']}")
        if not row.get("conservation", {}).get("passed"):
            raise RuntimeError(f"failed conservation in {pair['pair_id']}")
        _finite_positive(row["completion_time_s"], "checkpoint completion")
        _finite_positive(row["wall_time_s"], "checkpoint wall time")
        _finite_positive(row["cpu_time_s"], "checkpoint CPU time")
        if row.get("config_sha256") != pair["config_sha256"]:
            raise RuntimeError(f"checkpoint config digest mismatch for {pair['pair_id']}")
        config = pair["config"]
        expected_fields = {
            "arm_id": config["arm_id"],
            "sample_id": pair["sample_id"],
            "family": config["family"],
            "runner": config["runner"],
            "policy": config["policy"],
        }
        for field, expected_value in expected_fields.items():
            if row.get(field) != expected_value:
                raise RuntimeError(
                    f"checkpoint {field} mismatch for {pair['pair_id']}"
                )
        expected_position = pair["execution_order"].index(row["allocator"])
        if int(row.get("execution_position", -1)) != expected_position:
            raise RuntimeError(f"execution-position mismatch for {pair['pair_id']}")
        if row.get("completion_time_hex") != _f64_hex(row["completion_time_s"]):
            raise RuntimeError(f"completion hex mismatch for {pair['pair_id']}")
        if row.get("wall_time_hex") != _f64_hex(row["wall_time_s"]):
            raise RuntimeError(f"wall-time hex mismatch for {pair['pair_id']}")
        if row.get("cpu_time_hex") != _f64_hex(row["cpu_time_s"]):
            raise RuntimeError(f"CPU-time hex mismatch for {pair['pair_id']}")
        _finite_positive(row["simulation_wall_time_s"], "simulation wall time")
        _finite_positive(row["simulation_cpu_time_s"], "simulation CPU time")
        if row.get("simulation_wall_time_hex") != _f64_hex(row["simulation_wall_time_s"]):
            raise RuntimeError(f"simulation wall-time hex mismatch for {pair['pair_id']}")
        if row.get("simulation_cpu_time_hex") != _f64_hex(row["simulation_cpu_time_s"]):
            raise RuntimeError(f"simulation CPU-time hex mismatch for {pair['pair_id']}")
        if config["runner"] == "adaptive":
            if not row.get("adaptive_gate", {}).get("passed"):
                raise RuntimeError(f"adaptive gate failed for {pair['pair_id']}")
        elif row.get("adaptive_gate") is not None:
            raise RuntimeError(f"unexpected adaptive gate for {pair['pair_id']}")
    parent_timing = checkpoint.get("parent_timing")
    if not isinstance(parent_timing, dict):
        raise RuntimeError(f"checkpoint timing provenance missing for {pair['pair_id']}")
    if not isinstance(parent_timing.get("segment_index"), int) or parent_timing["segment_index"] < 1:
        raise RuntimeError(f"checkpoint timing segment is invalid for {pair['pair_id']}")
    _finite_positive(
        parent_timing.get("pool_elapsed_at_checkpoint_s"),
        "checkpoint parent pool elapsed",
    )
    expected_pair_gate = {
        "passed": True,
        "initial_digests_equal": True,
        "mutable_instances_distinct": True,
    }
    if checkpoint.get("pair_gate") != expected_pair_gate:
        raise RuntimeError(f"pair gate payload mismatch for {pair['pair_id']}")
    if {int(row["execution_position"]) for row in rows} != {0, 1}:
        raise RuntimeError(f"pair execution positions are incomplete for {pair['pair_id']}")
    for field in (
        "config_sha256",
        "topology_sha256",
        "ring_sha256",
        "route_sha256",
        "process_initial_sha256",
    ):
        values = [row.get(field) for row in rows]
        if any(
            not isinstance(value, str)
            or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)
            for value in values
        ):
            raise RuntimeError(f"checkpoint has invalid digest {field}")
        if len(set(values)) != 1:
            raise RuntimeError(f"checkpoint pair-state mismatch in {field}")
    for field in ("topology_instance_id", "simulator_instance_id"):
        values = [row.get(field) for row in rows]
        if any(not isinstance(value, int) for value in values) or len(set(values)) != 2:
            raise RuntimeError(f"checkpoint has invalid/distinctness failure in {field}")
    config = pair["config"]
    instance_expectations = {
        "congestion_instance_id": config.get("congestion") is not None,
        "background_instance_id": (
            config["family"] == "background"
            and int(config["arrival_rate_fps"]) > 0
        ),
    }
    for field, expected_present in instance_expectations.items():
        values = [row.get(field) for row in rows]
        if expected_present:
            if any(not isinstance(value, int) for value in values) or len(set(values)) != 2:
                raise RuntimeError(f"checkpoint has invalid/distinctness failure in {field}")
        elif values != [None, None]:
            raise RuntimeError(f"checkpoint unexpectedly records {field}")


def _existing_checkpoints(
    output: Path,
    plan: Mapping[str, Any],
    indexes: Mapping[str, Mapping[Tuple[Any, ...], Dict[str, str]]],
) -> Dict[str, Dict[str, Any]]:
    checkpoint_dir = output / "checkpoints"
    expected = {pair["pair_id"]: pair for pair in plan["pairs"]}
    found: Dict[str, Dict[str, Any]] = {}
    for path in sorted(checkpoint_dir.iterdir()):
        if path.name == ".staging" and path.is_dir():
            if any(
                not child.is_file() or ".tmp-" not in child.name
                for child in path.iterdir()
            ):
                raise RuntimeError("checkpoint staging contains an unknown artifact")
            continue
        if not path.is_file() or path.suffix != ".json":
            raise RuntimeError(f"unexpected checkpoint artifact {path.name}")
        pair_id = path.stem
        if pair_id not in expected:
            raise RuntimeError(f"unknown checkpoint {path.name}")
        if pair_id in found:
            raise RuntimeError(f"duplicate checkpoint {pair_id}")
        checkpoint = _load_checkpoint(path)
        _validate_checkpoint(checkpoint, expected[pair_id], plan["plan_sha256"])
        # Recompute the frozen-oracle verdict from the recorded actual values;
        # never trust a Boolean copied from an interrupted or edited checkpoint.
        stored_verdicts = {
            row["allocator"]: row.get("oracle_verdict")
            for row in checkpoint["rows"]
        }
        probe = json.loads(json.dumps(checkpoint))
        for row in probe["rows"]:
            row.pop("oracle_verdict", None)
        _attach_oracle_verdict(probe, indexes)
        recomputed_verdicts = {
            row["allocator"]: row.get("oracle_verdict") for row in probe["rows"]
        }
        if stored_verdicts != recomputed_verdicts:
            raise RuntimeError(f"checkpoint oracle verdict mismatch for {pair_id}")
        found[pair_id] = checkpoint
    return found


def _flat_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    config = row
    scalar = row.get("scalar_metrics", {})
    oracle = row.get("oracle_verdict", {})
    conservation = row["conservation"]
    return {
        "pair_id": row["pair_id"],
        "arm_id": row["arm_id"],
        "sample_id": row["sample_id"],
        "family": row["family"],
        "runner": row["runner"],
        "policy": row["policy"],
        "allocator": row["allocator"],
        "execution_position": row["execution_position"],
        "completion_time_s": repr(row["completion_time_s"]),
        "completion_time_hex": row["completion_time_hex"],
        "simulated_ticks": row["simulated_ticks"],
        "wall_time_s": repr(row["wall_time_s"]),
        "cpu_time_s": repr(row["cpu_time_s"]),
        "simulation_wall_time_s": repr(row["simulation_wall_time_s"]),
        "simulation_cpu_time_s": repr(row["simulation_cpu_time_s"]),
        "config_sha256": row["config_sha256"],
        "topology_sha256": row["topology_sha256"],
        "ring_sha256": row["ring_sha256"],
        "route_sha256": row["route_sha256"],
        "process_initial_sha256": row["process_initial_sha256"],
        "conservation_max_error_B": repr(conservation["maximum_abs_error_bytes"]),
        "conservation_remaining_B": repr(conservation["remaining_foreground_bytes"]),
        "foreground_flow_count": conservation["foreground_flow_count"],
        "adaptive_event_count": scalar.get("adaptive_event_count", ""),
        "final_k_mean": scalar.get("final_k_mean", ""),
        "final_k_max": scalar.get("final_k_max", ""),
        "step_count": scalar.get("step_count", ""),
        "mean_step_s": scalar.get("mean_step_s", ""),
        "p99_step_s": scalar.get("p99_step_s", ""),
        "max_step_s": scalar.get("max_step_s", ""),
        "oracle_status": oracle.get("status", ""),
        "pilot_use": "timing_and_coverage_only_not_a_scientific_estimate",
    }


def _csv_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    if not rows:
        raise RuntimeError("cannot export empty CSV")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _global_gate(
    plan: Mapping[str, Any], checkpoints: Mapping[str, Mapping[str, Any]]
) -> Dict[str, Any]:
    if len(checkpoints) != 90:
        raise RuntimeError(f"global gate expected 90 checkpoints, found {len(checkpoints)}")
    rows = [row for pair_id in sorted(checkpoints) for row in checkpoints[pair_id]["rows"]]
    if len(rows) != 180:
        raise RuntimeError(f"global gate expected 180 rows, found {len(rows)}")
    if len({(row["pair_id"], row["allocator"]) for row in rows}) != 180:
        raise RuntimeError("duplicate pair/allocator row")
    allocator_counts = {
        allocator: sum(row["allocator"] == allocator for row in rows)
        for allocator in ALLOCATORS
    }
    if set(allocator_counts.values()) != {90}:
        raise RuntimeError(f"allocator row count mismatch: {allocator_counts}")
    runner_counts = {
        runner: sum(row["runner"] == runner for row in rows)
        for runner in EXPECTED_RUNNER_ROWS
    }
    if runner_counts != EXPECTED_RUNNER_ROWS:
        raise RuntimeError(f"runner row count mismatch: {runner_counts}")
    family_row_counts = {
        family: sum(row["family"] == family for row in rows)
        for family in EXPECTED_FAMILY_PAIRS
    }
    expected_family_rows = {
        family: pair_count * 2
        for family, pair_count in EXPECTED_FAMILY_PAIRS.items()
    }
    if family_row_counts != expected_family_rows:
        raise RuntimeError(f"family row count mismatch: {family_row_counts}")
    sample_row_counts = {
        sample: sum(int(row["sample_id"]) == sample for row in rows)
        for sample in SAMPLE_IDS
    }
    if set(sample_row_counts.values()) != {36}:
        raise RuntimeError(f"sample row count mismatch: {sample_row_counts}")
    first_position_counts = {
        allocator: sum(
            row["allocator"] == allocator and int(row["execution_position"]) == 0
            for row in rows
        )
        for allocator in ALLOCATORS
    }
    if first_position_counts != {ALLOCATORS[0]: 45, ALLOCATORS[1]: 45}:
        raise RuntimeError(f"execution-order balance changed: {first_position_counts}")
    actual_ids = sorted(checkpoints)
    planned_ids = sorted(pair["pair_id"] for pair in plan["pairs"])
    if actual_ids != planned_ids:
        raise RuntimeError("completed pair-ID set differs from dry-run plan")
    exact_oracles = sum(
        row["allocator"] == LEGACY_ALLOCATOR
        and row["oracle_verdict"]["status"] == "exact_binary64_match"
        for row in rows
    )
    diagnostics = sum(
        row["allocator"] == LEGACY_ALLOCATOR
        and row["oracle_verdict"]["status"] == "new_diagnostic"
        for row in rows
    )
    if exact_oracles != 85 or diagnostics != 5:
        raise RuntimeError(
            f"oracle cardinality mismatch: exact={exact_oracles}, diagnostic={diagnostics}"
        )

    coverage = {}
    for arm_id in ("controller_af01_adaptive", "controller_af05_adaptive"):
        selected = [
            row
            for row in rows
            if row["arm_id"] == arm_id and row["allocator"] == MAXMIN_ALLOCATOR
        ]
        events = sum(int(row["scalar_metrics"]["adaptive_event_count"]) for row in selected)
        coverage[arm_id] = {
            "runs": len(selected),
            "event_count": events,
            "passed": len(selected) == 5 and events > 0,
        }
    ready_for_n100 = all(item["passed"] for item in coverage.values())
    return {
        "passed": ready_for_n100,
        "mechanical_and_oracle_gates_passed": True,
        "row_count": len(rows),
        "pair_count": len(checkpoints),
        "allocator_counts": allocator_counts,
        "runner_counts": runner_counts,
        "family_row_counts": family_row_counts,
        "sample_row_counts": sample_row_counts,
        "first_position_counts": first_position_counts,
        "exact_frozen_legacy_matches": exact_oracles,
        "new_diagnostic_legacy_rows": diagnostics,
        "adaptive_coverage": coverage,
        "ready_for_n100_without_extra_diagnostic": ready_for_n100,
    }


def _load_timing_segments(
    output: Path, checkpoints: Mapping[str, Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    directory = output / "timing_segments"
    segments = []
    covered: set[str] = set()
    for path in sorted(directory.iterdir()):
        if path.name == ".staging" and path.is_dir():
            if any(
                not child.is_file() or ".tmp-" not in child.name
                for child in path.iterdir()
            ):
                raise RuntimeError("timing staging contains an unknown artifact")
            continue
        if not path.is_file() or path.suffix != ".json":
            raise RuntimeError(f"unexpected timing artifact {path.name}")
        segment = json.loads(path.read_text(encoding="utf-8"))
        if segment.get("schema") != "rate-allocator-pilot-timing-segment-v1":
            raise RuntimeError(f"wrong timing-segment schema in {path.name}")
        expected_name = f"segment_{len(segments) + 1:03d}.json"
        if path.name != expected_name or segment.get("segment_index") != len(segments) + 1:
            raise RuntimeError(f"non-sequential timing segment {path.name}")
        pair_ids = list(segment.get("pair_ids", []))
        if not pair_ids or len(pair_ids) != len(set(pair_ids)):
            raise RuntimeError(f"invalid pair list in {path.name}")
        if covered.intersection(pair_ids):
            raise RuntimeError(f"overlapping timing segments at {path.name}")
        if any(pair_id not in checkpoints for pair_id in pair_ids):
            raise RuntimeError(f"timing segment references unknown checkpoint: {path.name}")
        if any(
            checkpoints[pair_id]["parent_timing"]["segment_index"]
            != segment["segment_index"]
            for pair_id in pair_ids
        ):
            raise RuntimeError(f"checkpoint timing index mismatch in {path.name}")
        elapsed = _finite_positive(segment["elapsed_pool_wall_s"], "pool segment wall time")
        if any(
            float(checkpoints[pair_id]["parent_timing"]["pool_elapsed_at_checkpoint_s"])
            > elapsed
            for pair_id in pair_ids
        ):
            raise RuntimeError(f"checkpoint completion occurs after segment end in {path.name}")
        expected_sim = sum(
            float(row["simulation_wall_time_s"])
            for pair_id in pair_ids
            for row in checkpoints[pair_id]["rows"]
        )
        expected_total = sum(
            float(row["wall_time_s"])
            for pair_id in pair_ids
            for row in checkpoints[pair_id]["rows"]
        )
        if _f64_hex(segment["worker_simulation_wall_sum_s"]) != _f64_hex(expected_sim):
            raise RuntimeError(f"simulation-wall sum mismatch in {path.name}")
        if _f64_hex(segment["worker_end_to_end_wall_sum_s"]) != _f64_hex(expected_total):
            raise RuntimeError(f"end-to-end wall sum mismatch in {path.name}")
        if elapsed <= 0.0:
            raise RuntimeError(f"invalid elapsed time in {path.name}")
        covered.update(pair_ids)
        segments.append(segment)
    return segments


def _recover_timing_segments(
    output: Path,
    checkpoints: Mapping[str, Mapping[str, Any]],
    existing: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Close crash-truncated timing attempts from immutable checkpoint metadata."""
    covered = {pair_id for segment in existing for pair_id in segment["pair_ids"]}
    orphan_groups: Dict[int, List[str]] = {}
    for pair_id, checkpoint in checkpoints.items():
        if pair_id in covered:
            continue
        index = int(checkpoint["parent_timing"]["segment_index"])
        orphan_groups.setdefault(index, []).append(pair_id)
    next_index = len(existing) + 1
    for index in sorted(orphan_groups):
        if index != next_index:
            raise RuntimeError(
                f"cannot recover non-sequential timing attempt {index}; expected {next_index}"
            )
        pair_ids = sorted(orphan_groups[index])
        elapsed = max(
            float(checkpoints[pair_id]["parent_timing"]["pool_elapsed_at_checkpoint_s"])
            for pair_id in pair_ids
        )
        segment = {
            "schema": "rate-allocator-pilot-timing-segment-v1",
            "segment_index": index,
            "pair_ids": pair_ids,
            "elapsed_pool_wall_s": elapsed,
            "worker_simulation_wall_sum_s": sum(
                float(row["simulation_wall_time_s"])
                for pair_id in pair_ids
                for row in checkpoints[pair_id]["rows"]
            ),
            "worker_end_to_end_wall_sum_s": sum(
                float(row["wall_time_s"])
                for pair_id in pair_ids
                for row in checkpoints[pair_id]["rows"]
            ),
            "recovered_after_interruption": True,
            "timing_note": (
                "elapsed ends at the last durable checkpoint; post-checkpoint crash "
                "overhead is intentionally excluded"
            ),
        }
        _atomic_json_once(
            output / "timing_segments" / f"segment_{index:03d}.json",
            segment,
        )
        next_index += 1
    return _load_timing_segments(output, checkpoints)


def _timing_and_eta(
    checkpoints: Mapping[str, Mapping[str, Any]],
    workers: int,
    timing_segments: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    rows = [row for checkpoint in checkpoints.values() for row in checkpoint["rows"]]
    measured_pair_ids = {
        pair_id for segment in timing_segments for pair_id in segment["pair_ids"]
    }
    pool_elapsed = sum(float(segment["elapsed_pool_wall_s"]) for segment in timing_segments)
    measured_rows = [row for row in rows if row["pair_id"] in measured_pair_ids]
    worker_sim_wall = sum(float(row["simulation_wall_time_s"]) for row in measured_rows)
    worker_total_wall = sum(float(row["wall_time_s"]) for row in measured_rows)
    effective_sim_parallelism = worker_sim_wall / pool_elapsed if pool_elapsed else 0.0
    effective_total_parallelism = worker_total_wall / pool_elapsed if pool_elapsed else 0.0
    if measured_rows and not (0.0 < effective_total_parallelism <= workers * 1.25):
        raise RuntimeError(
            f"implausible measured parallelism {effective_total_parallelism} for {workers} workers"
        )
    groups: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["arm_id"], row["allocator"]), []).append(row)
    profiles = []
    for (arm_id, allocator), selected in sorted(groups.items()):
        wall = [float(row["wall_time_s"]) for row in selected]
        cpu = [float(row["cpu_time_s"]) for row in selected]
        sim_wall = [float(row["simulation_wall_time_s"]) for row in selected]
        sim_cpu = [float(row["simulation_cpu_time_s"]) for row in selected]
        profiles.append(
            {
                "arm_id": arm_id,
                "allocator": allocator,
                "family": selected[0]["family"],
                "runner": selected[0]["runner"],
                "n": len(selected),
                "wall_min_s": min(wall),
                "wall_median_s": statistics.median(wall),
                "wall_max_s": max(wall),
                "cpu_min_s": min(cpu),
                "cpu_median_s": statistics.median(cpu),
                "cpu_max_s": max(cpu),
                "simulation_wall_min_s": min(sim_wall),
                "simulation_wall_median_s": statistics.median(sim_wall),
                "simulation_wall_max_s": max(sim_wall),
                "simulation_cpu_min_s": min(sim_cpu),
                "simulation_cpu_median_s": statistics.median(sim_cpu),
                "simulation_cpu_max_s": max(sim_cpu),
                "over_60s": max(wall) > 60.0,
            }
        )

    family_eta = {}
    for family, target_runs in N100_TARGET_SIMULATIONS.items():
        proxy_family = "static_split" if family == "placement_proxy" else family
        selected = [row for row in rows if row["family"] == proxy_family]
        end_to_end_wall = [float(row["wall_time_s"]) for row in selected]
        simulation_wall = [float(row["simulation_wall_time_s"]) for row in selected]
        end_to_end_cpu = [float(row["cpu_time_s"]) for row in selected]
        simulation_cpu = [float(row["simulation_cpu_time_s"]) for row in selected]
        if family == "placement_proxy":
            sim_low = min(simulation_wall)
            sim_central = max(simulation_wall)
            sim_high = 1.25 * max(simulation_wall)
            total_low = min(end_to_end_wall)
            total_central = max(end_to_end_wall)
            total_high = 1.25 * max(end_to_end_wall)
            sim_cpu_central = max(simulation_cpu)
            total_cpu_central = max(end_to_end_cpu)
            proxy_note = "no direct placement arm; conservative slowest static/split proxy"
        else:
            sim_low = min(simulation_wall)
            sim_central = statistics.median(simulation_wall)
            sim_high = 1.25 * max(simulation_wall)
            total_low = min(end_to_end_wall)
            total_central = statistics.median(end_to_end_wall)
            total_high = 1.25 * max(end_to_end_wall)
            sim_cpu_central = statistics.median(simulation_cpu)
            total_cpu_central = statistics.median(end_to_end_cpu)
            proxy_note = "pilot family distribution proxy"
        serial_sim = {
            "lower": target_runs * sim_low,
            "central": target_runs * sim_central,
            "upper": target_runs * sim_high,
        }
        serial_total = {
            "lower": target_runs * total_low,
            "central": target_runs * total_central,
            "upper": target_runs * total_high,
        }
        family_eta[family] = {
            "target_simulations_n100": target_runs,
            "proxy_note": proxy_note,
            "central_serial_cpu_hours": {
                "simulation_only": target_runs * sim_cpu_central / 3600.0,
                "end_to_end_with_audit": target_runs * total_cpu_central / 3600.0,
            },
            "predicted_wall_hours_from_measured_parallelism": {
                "workers": workers,
                "simulation_only": {
                    bound: seconds / (effective_sim_parallelism * 3600.0)
                    for bound, seconds in serial_sim.items()
                },
                "end_to_end_with_audit": {
                    bound: seconds / (effective_total_parallelism * 3600.0)
                    for bound, seconds in serial_total.items()
                },
            },
        }
    total_wall = {}
    for scope in ("simulation_only", "end_to_end_with_audit"):
        total_wall[scope] = {
            bound: sum(
                item["predicted_wall_hours_from_measured_parallelism"][scope][bound]
                for item in family_eta.values()
            )
            for bound in ("lower", "central", "upper")
        }
    return {
        "schema": "rate-allocator-pilot-eta-v1",
        "scope": "n100 only; n1000 ETA forbidden until n100 is measured",
        "range_semantics": (
            "heuristic runtime scenarios, not confidence intervals: lower uses the "
            "pilot minimum, central the median (or conservative maximum for the "
            "placement proxy), and upper 1.25 times the pilot maximum"
        ),
        "measured_pool": {
            "workers": workers,
            "segments": len(timing_segments),
            "covered_pairs": len(measured_pair_ids),
            "pool_elapsed_wall_s": pool_elapsed,
            "worker_simulation_wall_sum_s": worker_sim_wall,
            "worker_end_to_end_wall_sum_s": worker_total_wall,
            "effective_simulation_parallelism": effective_sim_parallelism,
            "effective_end_to_end_parallelism": effective_total_parallelism,
            "recovered_segments": sum(
                bool(segment.get("recovered_after_interruption"))
                for segment in timing_segments
            ),
            "timing_quality": (
                "checkpoint-bounded_after_interruption"
                if any(
                    segment.get("recovered_after_interruption")
                    for segment in timing_segments
                )
                else "complete_pool_attempts"
            ),
        },
        "pilot_profiles": profiles,
        "family_eta": family_eta,
        "total_n100": {
            "templates_per_allocator": 134,
            "simulations": 26_800,
            "predicted_wall_hours": total_wall,
        },
        "arms_over_60s": [
            {"arm_id": profile["arm_id"], "allocator": profile["allocator"]}
            for profile in profiles
            if profile["over_60s"]
        ],
    }


def _finalize(
    output: Path,
    plan: Mapping[str, Any],
    checkpoints: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, Any],
    timing_segments: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    covered_pairs = {
        pair_id for segment in timing_segments for pair_id in segment["pair_ids"]
    }
    if covered_pairs != set(checkpoints):
        missing = sorted(set(checkpoints) - covered_pairs)
        raise RuntimeError(
            "timing provenance does not cover every checkpoint; "
            f"cannot report measured ETA (missing {missing[:3]})"
        )
    gate = _global_gate(plan, checkpoints)
    rows = [
        row
        for pair_id in sorted(checkpoints)
        for row in sorted(checkpoints[pair_id]["rows"], key=lambda item: item["allocator"])
    ]
    flat = [_flat_row(row) for row in rows]
    long_payload = _csv_bytes(flat)
    _atomic_write_once(output / "results_long.csv", long_payload)

    pair_rows = []
    for pair_id in sorted(checkpoints):
        checkpoint = checkpoints[pair_id]
        indexed = {row["allocator"]: row for row in checkpoint["rows"]}
        legacy = indexed[LEGACY_ALLOCATOR]
        maxmin = indexed[MAXMIN_ALLOCATOR]
        pair_rows.append(
            {
                "pair_id": pair_id,
                "arm_id": legacy["arm_id"],
                "sample_id": legacy["sample_id"],
                "family": legacy["family"],
                "legacy_time_s": repr(legacy["completion_time_s"]),
                "maxmin_time_s": repr(maxmin["completion_time_s"]),
                "maxmin_over_legacy": repr(
                    maxmin["completion_time_s"] / legacy["completion_time_s"]
                ),
                "pilot_use": "diagnostic_only_do_not_cite_as_effect_estimate",
            }
        )
    pairs_payload = _csv_bytes(pair_rows)
    _atomic_write_once(output / "pairs.csv", pairs_payload)

    eta = _timing_and_eta(checkpoints, int(manifest["workers"]), timing_segments)
    _atomic_json_once(output / "eta_by_family.json", eta)

    frozen_after = audit_frozen_csvs()
    if frozen_after != manifest["frozen_before"]:
        raise RuntimeError("frozen CSV snapshot changed during the pilot")
    results_after = snapshot_results_tree()
    if results_after != manifest["results_tree_before"]:
        raise RuntimeError("results/ tree changed during the pilot")
    _verify_source_hashes(manifest["sim_sha256"], manifest["driver_sha256"])

    exported = {
        name: {
            "bytes": (output / name).stat().st_size,
            "sha256": _sha256_file(output / name),
        }
        for name in ("results_long.csv", "pairs.csv", "eta_by_family.json")
    }
    checkpoint_artifacts = {
        f"checkpoints/{pair_id}.json": {
            "bytes": _checkpoint_path(output, pair_id).stat().st_size,
            "sha256": _sha256_file(_checkpoint_path(output, pair_id)),
        }
        for pair_id in sorted(checkpoints)
    }
    timing_artifacts = {
        f"timing_segments/segment_{index:03d}.json": {
            "bytes": (output / f"timing_segments/segment_{index:03d}.json").stat().st_size,
            "sha256": _sha256_file(output / f"timing_segments/segment_{index:03d}.json"),
        }
        for index in range(1, len(timing_segments) + 1)
    }
    worker_wall_sum = sum(float(row["wall_time_s"]) for row in rows)
    worker_cpu_sum = sum(float(row["cpu_time_s"]) for row in rows)
    completion_manifest = {
        "schema": "rate-allocator-pilot-completion-v1",
        "plan_sha256": plan["plan_sha256"],
        "pair_count": 90,
        "simulation_count": 180,
        "worker_wall_sum_s": worker_wall_sum,
        "worker_cpu_sum_s": worker_cpu_sum,
        "gate": gate,
        "eta_summary": eta["total_n100"],
        "frozen_after": frozen_after,
        "results_tree_after": results_after,
        "exports": exported,
        "checkpoints": checkpoint_artifacts,
        "timing_segments": timing_artifacts,
        "run_manifest": {
            "bytes": (output / "run_manifest.json").stat().st_size,
            "sha256": _sha256_file(output / "run_manifest.json"),
        },
        "automatic_next_stage": None,
        "n100_started": False,
        "n1000_eta_reported": False,
    }
    _atomic_json_once(output / "completion_manifest.json", completion_manifest)
    completion_manifest_hash = _sha256_file(output / "completion_manifest.json")
    complete = {
        "schema": "rate-allocator-pilot-complete-v1",
        "plan_sha256": plan["plan_sha256"],
        "completion_manifest_sha256": completion_manifest_hash,
        "run_manifest_sha256": completion_manifest["run_manifest"]["sha256"],
        "status": (
            "pilot_finished_ready_for_n100_decision"
            if gate["ready_for_n100_without_extra_diagnostic"]
            else "pilot_finished_n100_blocked_for_extra_controller_diagnostic"
        ),
    }
    _atomic_json_once(output / "COMPLETE.json", complete)
    return completion_manifest


def _new_manifest(plan: Mapping[str, Any], output: Path, workers: int) -> Dict[str, Any]:
    sim_hash = _sha256_file(SIM_PATH)
    driver_hash = _sha256_file(DRIVER_PATH)
    return {
        "schema": "rate-allocator-pilot-run-v1",
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
        "authorization_sha256": _authorization_sha256(
            plan, sim_hash=sim_hash, driver_hash=driver_hash
        ),
        "git": _git_state(),
        "frozen_before": audit_frozen_csvs(),
        "results_tree_before": snapshot_results_tree(),
        "checkpoint_policy": "one atomic parent-written JSON per complete pair",
        "pilot_use": "timing_and_coverage_only_not_a_scientific_effect_estimate",
        "automatic_next_stage": None,
    }


def _verify_complete(output: Path, manifest: Mapping[str, Any]) -> None:
    complete_path = output / "COMPLETE.json"
    complete = json.loads(complete_path.read_text(encoding="utf-8"))
    if complete.get("schema") != "rate-allocator-pilot-complete-v1":
        raise RuntimeError("COMPLETE schema mismatch")
    if complete.get("status") not in {
        "pilot_finished_ready_for_n100_decision",
        "pilot_finished_n100_blocked_for_extra_controller_diagnostic",
    }:
        raise RuntimeError("COMPLETE status is invalid")
    if complete.get("plan_sha256") != manifest["plan_sha256"]:
        raise RuntimeError("COMPLETE plan hash mismatch")
    completion_path = output / "completion_manifest.json"
    if _sha256_file(completion_path) != complete.get("completion_manifest_sha256"):
        raise RuntimeError("completion manifest hash mismatch")
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    if completion.get("schema") != "rate-allocator-pilot-completion-v1":
        raise RuntimeError("completion manifest schema mismatch")
    if completion.get("pair_count") != 90 or completion.get("simulation_count") != 180:
        raise RuntimeError("completion cardinality mismatch")
    gate = completion.get("gate", {})
    readiness = gate.get("ready_for_n100_without_extra_diagnostic")
    if gate.get("mechanical_and_oracle_gates_passed") is not True:
        raise RuntimeError("completion mechanical/oracle gate is not true")
    if gate.get("passed") is not readiness or not isinstance(readiness, bool):
        raise RuntimeError("completion gate/readiness status is inconsistent")
    expected_status = (
        "pilot_finished_ready_for_n100_decision"
        if readiness
        else "pilot_finished_n100_blocked_for_extra_controller_diagnostic"
    )
    if complete.get("status") != expected_status:
        raise RuntimeError("COMPLETE status disagrees with the hashed gate result")
    run_manifest_path = output / "run_manifest.json"
    if (
        _sha256_file(run_manifest_path) != complete.get("run_manifest_sha256")
        or _sha256_file(run_manifest_path) != completion["run_manifest"]["sha256"]
        or run_manifest_path.stat().st_size != completion["run_manifest"]["bytes"]
    ):
        raise RuntimeError("run manifest changed after completion")
    expected_exports = {"results_long.csv", "pairs.csv", "eta_by_family.json"}
    if set(completion.get("exports", {})) != expected_exports:
        raise RuntimeError("completion export set mismatch")
    expected_checkpoints = {
        f"checkpoints/{pair['pair_id']}.json" for pair in manifest["plan"]["pairs"]
    }
    if set(completion.get("checkpoints", {})) != expected_checkpoints:
        raise RuntimeError("completion checkpoint set mismatch")
    expected_segments = {
        f"timing_segments/segment_{index:03d}.json"
        for index in range(1, len(completion.get("timing_segments", {})) + 1)
    }
    if set(completion.get("timing_segments", {})) != expected_segments:
        raise RuntimeError("completion timing-segment set mismatch")
    for name, expected in completion["exports"].items():
        path = output / name
        if path.stat().st_size != expected["bytes"] or _sha256_file(path) != expected["sha256"]:
            raise RuntimeError(f"completed export changed: {name}")
    for name, expected in completion["checkpoints"].items():
        path = output / name
        if path.stat().st_size != expected["bytes"] or _sha256_file(path) != expected["sha256"]:
            raise RuntimeError(f"completed checkpoint changed: {name}")
    for name, expected in completion["timing_segments"].items():
        path = output / name
        if path.stat().st_size != expected["bytes"] or _sha256_file(path) != expected["sha256"]:
            raise RuntimeError(f"completed timing segment changed: {name}")
    audit_frozen_csvs()
    if snapshot_results_tree() != manifest["results_tree_before"]:
        raise RuntimeError("results/ tree changed after pilot completion")
    _verify_source_hashes(manifest["sim_sha256"], manifest["driver_sha256"])


def execute_or_resume(
    plan: Mapping[str, Any],
    output: Path,
    *,
    workers: Optional[int],
    resume: bool,
    confirmed_authorization: Optional[str] = None,
) -> Dict[str, Any]:
    if resume:
        if not output.is_dir():
            raise RuntimeError(f"resume directory does not exist: {output}")
    else:
        if confirmed_authorization != _authorization_sha256(plan):
            raise RuntimeError("execution authorization changed before directory creation")
        PILOT_ROOT.mkdir(parents=True, exist_ok=True)
        output.mkdir(parents=False, exist_ok=False)
        (output / "checkpoints").mkdir(exist_ok=False)
        (output / "timing_segments").mkdir(exist_ok=False)

    with ExclusiveRunLock(output / ".run.lock"):
        manifest_path = output / "run_manifest.json"
        if resume:
            if not manifest_path.is_file():
                raise RuntimeError("resume requires run_manifest.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("schema") != "rate-allocator-pilot-run-v1":
                raise RuntimeError("resume manifest schema mismatch")
            if manifest.get("plan_sha256") != plan["plan_sha256"] or manifest.get("plan") != plan:
                raise RuntimeError("resume plan differs from current fixed matrix")
            if Path(manifest.get("output", "")).resolve() != output:
                raise RuntimeError("resume output path differs from manifest")
            expected_authorization = _authorization_sha256(
                plan,
                sim_hash=manifest.get("sim_sha256"),
                driver_hash=manifest.get("driver_sha256"),
            )
            if manifest.get("authorization_sha256") != expected_authorization:
                raise RuntimeError("resume manifest authorization is inconsistent")
            workers = int(manifest["workers"])
            if not 1 <= workers <= 8:
                raise RuntimeError("resume worker count is outside the reviewed 1..8 range")
            _verify_source_hashes(manifest["sim_sha256"], manifest["driver_sha256"])
            if audit_frozen_csvs() != manifest["frozen_before"]:
                raise RuntimeError("frozen inputs changed since run start")
            if snapshot_results_tree() != manifest["results_tree_before"]:
                raise RuntimeError("results/ tree changed since run start")
            if (output / "COMPLETE.json").exists():
                _verify_complete(output, manifest)
                return json.loads((output / "completion_manifest.json").read_text(encoding="utf-8"))
        else:
            if workers is None or not 1 <= workers <= 8:
                raise RuntimeError("fresh execution requires 1..8 workers")
            manifest = _new_manifest(plan, output, workers)
            if manifest["authorization_sha256"] != confirmed_authorization:
                raise RuntimeError("execution sources changed while creating the manifest")
            _atomic_json_once(manifest_path, manifest)

        if workers is None:
            raise RuntimeError("worker count unavailable")
        indexes = _oracle_indexes()
        checkpoint_map = _existing_checkpoints(output, plan, indexes)
        existing_segments = _load_timing_segments(output, checkpoint_map)
        existing_segments = _recover_timing_segments(
            output, checkpoint_map, existing_segments
        )
        pending = [pair for pair in plan["pairs"] if pair["pair_id"] not in checkpoint_map]
        if pending:
            pool_start = time.perf_counter()
            segment_index = len(existing_segments) + 1
            context = mp.get_context("spawn")
            executor = ProcessPoolExecutor(
                max_workers=workers,
                mp_context=context,
                initializer=_worker_init,
                initargs=(manifest["sim_sha256"], manifest["driver_sha256"]),
            )
            try:
                futures = {executor.submit(_run_pair_worker, pair): pair for pair in pending}
                completed = len(checkpoint_map)
                for future in as_completed(futures):
                    pair = futures[future]
                    checkpoint = future.result()
                    _attach_oracle_verdict(checkpoint, indexes)
                    checkpoint["plan_sha256"] = plan["plan_sha256"]
                    checkpoint["parent_timing"] = {
                        "segment_index": segment_index,
                        "pool_elapsed_at_checkpoint_s": time.perf_counter() - pool_start,
                    }
                    _validate_checkpoint(checkpoint, pair, plan["plan_sha256"])
                    _atomic_json_once(
                        _checkpoint_path(output, pair["pair_id"]), checkpoint
                    )
                    checkpoint_map[pair["pair_id"]] = checkpoint
                    completed += 1
                    print(
                        f"[{completed:02d}/90] {pair['pair_id']} complete and gated",
                        flush=True,
                    )
            except BaseException:
                executor.shutdown(wait=False, cancel_futures=True)
                raise
            else:
                executor.shutdown(wait=True)
            pool_elapsed = time.perf_counter() - pool_start
            segment_pair_ids = sorted(pair["pair_id"] for pair in pending)
            segment_sim_wall = sum(
                float(row["simulation_wall_time_s"])
                for pair_id in segment_pair_ids
                for row in checkpoint_map[pair_id]["rows"]
            )
            segment_total_wall = sum(
                float(row["wall_time_s"])
                for pair_id in segment_pair_ids
                for row in checkpoint_map[pair_id]["rows"]
            )
            segment = {
                "schema": "rate-allocator-pilot-timing-segment-v1",
                "segment_index": segment_index,
                "pair_ids": segment_pair_ids,
                "elapsed_pool_wall_s": pool_elapsed,
                "worker_simulation_wall_sum_s": segment_sim_wall,
                "worker_end_to_end_wall_sum_s": segment_total_wall,
                "recovered_after_interruption": False,
                "timing_note": "complete pool attempt measured through executor shutdown",
            }
            _atomic_json_once(
                output
                / "timing_segments"
                / f"segment_{segment_index:03d}.json",
                segment,
            )
        checkpoint_map = _existing_checkpoints(output, plan, indexes)
        timing_segments = _load_timing_segments(output, checkpoint_map)
        return _finalize(output, plan, checkpoint_map, manifest, timing_segments)


def dry_run(plan: Mapping[str, Any], output: Path) -> None:
    # Read-only gates only.  This function must not create output or parent paths.
    frozen = audit_frozen_csvs()
    sim_hash = _sha256_file(SIM_PATH)
    driver_hash = _sha256_file(DRIVER_PATH)
    authorization_hash = _authorization_sha256(
        plan, sim_hash=sim_hash, driver_hash=driver_hash
    )
    arms = plan["arms"]
    print("RATE-ALLOCATOR PILOT DRY-RUN (NO FILES, NO SIMULATIONS)")
    print(f"output={output}")
    print(f"plan_sha256={plan['plan_sha256']}")
    print("plan_sha256_scope=canonical plan payload excluding its plan_sha256 self-field")
    print(f"authorization_sha256={authorization_hash}")
    print(f"driver_sha256={driver_hash}")
    print(f"sim_sha256={sim_hash}")
    print(
        f"matrix={len(arms)} arms x {len(SAMPLE_IDS)} samples x 2 allocators "
        f"= {len(plan['pairs'])} pairs / {plan['simulation_count']} simulations"
    )
    print(f"family_pair_counts={json.dumps(plan['family_pair_counts'], sort_keys=True)}")
    print(
        f"frozen={frozen['count']} CSVs / {frozen['total_bytes']} bytes / "
        f"root {frozen['root_sha256']}"
    )
    for index, arm in enumerate(arms, 1):
        print(
            f"ARM {index:02d} {arm['arm_id']} family={arm['family']} "
            f"runner={arm['runner']} P={arm['ring_size']} k={arm['k']}"
        )
    print("PAIR_IDS")
    for pair in plan["pairs"]:
        print(pair["pair_id"])
    print("CANONICAL_PLAN_JSON_BEGIN")
    print(
        json.dumps(
            plan,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    )
    print("CANONICAL_PLAN_JSON_END")
    command = subprocess.list2cmdline(
        [
            sys.executable,
            str(DRIVER_PATH),
            "--execute-pilot",
            "--output",
            str(output),
            "--confirm-plan-sha256",
            authorization_hash,
            "--workers",
            "8",
        ]
    )
    print("AUTHORIZED_EXECUTION_TEMPLATE")
    print(command)
    print("STOP: dry-run completed; n=100 is not reachable from this driver")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute-pilot", action="store_true")
    mode.add_argument("--resume", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--confirm-plan-sha256")
    parser.add_argument("--workers", type=int)
    args = parser.parse_args(argv)
    if args.dry_run:
        if args.confirm_plan_sha256 is not None or args.workers is not None:
            parser.error("--dry-run accepts neither confirmation nor workers")
    elif args.execute_pilot:
        if args.confirm_plan_sha256 is None or args.workers is None:
            parser.error("--execute-pilot requires --confirm-plan-sha256 and --workers")
    elif args.resume:
        if args.confirm_plan_sha256 is not None or args.workers is not None:
            parser.error("--resume reads the authorized plan and worker count from its manifest")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    plan = build_plan()
    if args.dry_run:
        output = _validate_output_path(args.output, require_absent=True)
        dry_run(plan, output)
        return 0
    if args.execute_pilot:
        output = _validate_output_path(args.output, require_absent=True)
        if args.confirm_plan_sha256 != _authorization_sha256(plan):
            raise RuntimeError(
                "authorization mismatch; the plan, sim.py, or driver differs from dry-run"
            )
        completion = execute_or_resume(
            plan,
            output,
            workers=int(args.workers),
            resume=False,
            confirmed_authorization=args.confirm_plan_sha256,
        )
    else:
        output = _validate_output_path(args.output, require_absent=False)
        completion = execute_or_resume(
            plan, output, workers=None, resume=True, confirmed_authorization=None
        )
    print(json.dumps(completion, indent=2, sort_keys=True, allow_nan=False))
    print("STOPPED: pilot complete; n=100 was not started")
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
