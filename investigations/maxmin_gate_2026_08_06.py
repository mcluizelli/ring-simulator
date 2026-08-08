"""Paired allocator gate: legacy bottleneck shares vs progressive max-min.

This is deliberately a sidecar investigation.  It imports the production simulator but
does not edit ``sim.py`` and never writes under ``results/``.  Frozen rows supply the
legacy side of reproduced production cells; a few guards rerun the legacy implementation
to ensure the current code still reproduces them.  New outputs go only under
``investigations/maxmin_gate_2026_08_06/``.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import math
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sim  # noqa: E402


OUT_DIR = ROOT / "investigations" / "maxmin_gate_2026_08_06"
DT = 5e-5
SEED_BASE = 9000
MIB = 1024 * 1024

Edge = Tuple[str, str]


def legacy_bottleneck_rates(
    flow_edges: Mapping[int, Sequence[Edge]], capacities: Mapping[Edge, float]
) -> Dict[int, float]:
    users: Dict[Edge, List[int]] = defaultdict(list)
    for fid, edges in flow_edges.items():
        for edge in edges:
            users[edge].append(fid)
    rates: Dict[int, float] = {}
    for fid, edges in flow_edges.items():
        if not edges:
            rates[fid] = math.inf
            continue
        rates[fid] = min(max(0.0, capacities.get(edge, 0.0)) / len(users[edge]) for edge in edges)
    return rates


def progressive_maxmin_rates(
    flow_edges: Mapping[int, Sequence[Edge]], capacities: Mapping[Edge, float]
) -> Dict[int, float]:
    """Unweighted progressive filling for fixed paths and non-negative capacities."""
    users: Dict[Edge, List[int]] = defaultdict(list)
    for fid, edges in flow_edges.items():
        for edge in edges:
            users[edge].append(fid)

    finite = {fid for fid, edges in flow_edges.items() if edges}
    rates = {fid: (0.0 if fid in finite else math.inf) for fid in flow_edges}
    unfrozen = set(finite)
    residual = {edge: max(0.0, float(capacities.get(edge, 0.0))) for edge in users}
    scale = max([1.0, *residual.values()])
    tol = 1e-10 * scale

    while unfrozen:
        counts: Dict[Edge, int] = {}
        delta = math.inf
        limiting: List[Edge] = []
        for edge, fids in users.items():
            count = sum(fid in unfrozen for fid in fids)
            if not count:
                continue
            counts[edge] = count
            candidate = max(0.0, residual[edge]) / count
            if candidate < delta - tol:
                delta = candidate
                limiting = [edge]
            elif abs(candidate - delta) <= tol:
                limiting.append(edge)

        if not math.isfinite(delta):
            raise AssertionError("an active flow has no finite-capacity path resource")

        for fid in unfrozen:
            rates[fid] += delta
        for edge, count in counts.items():
            residual[edge] = max(0.0, residual[edge] - delta * count)

        saturated = {edge for edge in limiting if residual[edge] <= tol}
        if not saturated:
            saturated = set(limiting)
        newly_frozen = {
            fid for fid in unfrozen if any(edge in saturated for edge in flow_edges[fid])
        }
        if not newly_frozen:
            raise AssertionError("progressive filling made no progress")
        unfrozen.difference_update(newly_frozen)

    _assert_rate_guards(flow_edges, capacities, rates)
    return rates


def _assert_rate_guards(
    flow_edges: Mapping[int, Sequence[Edge]],
    capacities: Mapping[Edge, float],
    rates: Mapping[int, float],
) -> None:
    users: Dict[Edge, List[int]] = defaultdict(list)
    for fid, edges in flow_edges.items():
        for edge in edges:
            users[edge].append(fid)
    scale = max([1.0, *[float(v) for v in capacities.values()]])
    tol = 1e-7 * scale
    loads = {edge: sum(rates[fid] for fid in fids) for edge, fids in users.items()}
    for edge, load in loads.items():
        if load > capacities.get(edge, 0.0) + tol:
            raise AssertionError(f"capacity violation on {edge}: {load} > {capacities.get(edge, 0.0)}")
    for fid, edges in flow_edges.items():
        if not edges:
            continue
        certificate = False
        for edge in edges:
            saturated = abs(loads[edge] - capacities.get(edge, 0.0)) <= tol
            no_larger_user = all(rates[other] <= rates[fid] + tol for other in users[edge])
            if saturated and no_larger_user:
                certificate = True
                break
        if not certificate:
            raise AssertionError(f"no max-min bottleneck certificate for flow {fid}")


class ProgressiveMaxMinSimulator(sim.FlowLevelSimulator):
    """Sidecar drop-in used only while the gate's context manager is active."""

    registry: List["ProgressiveMaxMinSimulator"] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.audit: Dict[str, float] = defaultdict(float)
        self.audit["max_rate_ratio"] = 1.0
        self.audit["max_reclaimed_fraction"] = 0.0
        self.__class__.registry.append(self)

    def step(self) -> None:
        if self.background is not None:
            self.background.inject_for_tick(self)
        if self.congestion is not None:
            self.congestion.update_tick()

        active = [flow for flow in self.flows.values() if flow.remaining_bytes > 0]
        flow_edges = {flow.fid: self._flow_edges(flow) for flow in active}
        used_edges = {edge for edges in flow_edges.values() for edge in edges}
        capacities: Dict[Edge, float] = {}
        for edge in used_edges:
            nominal = self.topo.edge_of.get(edge, 0.0)
            capacities[edge] = (
                self.congestion.residual_capacity(edge, nominal)
                if self.congestion is not None
                else nominal
            )

        mm_rates = progressive_maxmin_rates(flow_edges, capacities) if active else {}
        legacy_rates = legacy_bottleneck_rates(flow_edges, capacities) if active else {}

        self.audit["ticks"] += 1
        self.audit["flow_samples"] += len(active)
        users: Dict[Edge, List[int]] = defaultdict(list)
        for fid, edges in flow_edges.items():
            for edge in edges:
                users[edge].append(fid)
        reclaimed_this_tick = False
        for fid in mm_rates:
            legacy = legacy_rates[fid]
            mm = mm_rates[fid]
            tol = 1e-8 * max(1.0, abs(legacy), abs(mm))
            if mm + tol < legacy:
                raise AssertionError(f"lower-bound violation: flow {fid}: {legacy} > {mm}")
            if mm > legacy + tol:
                self.audit["strict_flow_samples"] += 1
            if legacy > 0 and math.isfinite(mm):
                self.audit["max_rate_ratio"] = max(self.audit["max_rate_ratio"], mm / legacy)
        for edge, fids in users.items():
            old_load = sum(legacy_rates[fid] for fid in fids)
            new_load = sum(mm_rates[fid] for fid in fids)
            cap = capacities[edge]
            gain = new_load - old_load
            if gain > 1e-8 * max(1.0, cap):
                reclaimed_this_tick = True
                self.audit["reclaimed_edge_samples"] += 1
                if cap > 0:
                    self.audit["max_reclaimed_fraction"] = max(
                        self.audit["max_reclaimed_fraction"], gain / cap
                    )
            self.audit["edge_samples"] += 1
        if reclaimed_this_tick:
            self.audit["reclaimed_ticks"] += 1

        for flow in active:
            flow.last_rate_Bps = mm_rates[flow.fid]
        for flow in active:
            rate = flow.last_rate_Bps
            if not math.isfinite(rate) or rate <= 0:
                continue
            sent = min(flow.remaining_bytes, rate * self.dt_s)
            flow.remaining_bytes -= sent
            flow.sent_bytes += sent
            if sent > 0:
                for edge in flow_edges[flow.fid]:
                    self.edge_bytes_sent[edge] = self.edge_bytes_sent.get(edge, 0.0) + sent
        self.time_s += self.dt_s


@contextlib.contextmanager
def patched_progressive_allocator() -> Iterable[None]:
    original = sim.FlowLevelSimulator
    ProgressiveMaxMinSimulator.registry = []
    sim.FlowLevelSimulator = ProgressiveMaxMinSimulator
    try:
        yield
    finally:
        sim.FlowLevelSimulator = original


def _aggregate_audit() -> Dict[str, float]:
    total: Dict[str, float] = defaultdict(float)
    for instance in ProgressiveMaxMinSimulator.registry:
        for key, value in instance.audit.items():
            if key.startswith("max_"):
                total[key] = max(total.get(key, 0.0), float(value))
            else:
                total[key] += float(value)
    flows = total.get("flow_samples", 0.0)
    edges = total.get("edge_samples", 0.0)
    ticks = total.get("ticks", 0.0)
    total["strict_flow_fraction"] = total.get("strict_flow_samples", 0.0) / flows if flows else 0.0
    total["reclaimed_edge_fraction"] = total.get("reclaimed_edge_samples", 0.0) / edges if edges else 0.0
    total["reclaimed_tick_fraction"] = total.get("reclaimed_ticks", 0.0) / ticks if ticks else 0.0
    return dict(total)


def run_progressive(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Tuple[Any, Dict[str, float]]:
    with patched_progressive_allocator():
        result = fn(*args, **kwargs)
    return result, _aggregate_audit()


def unit_guards() -> Dict[str, Any]:
    c = 100.0
    paths = {1: [("s", "a"), ("a", "x")], 2: [("s", "a"), ("a", "y")]}
    caps = {("s", "a"): c, ("a", "x"): 0.2 * c, ("a", "y"): c}
    old = legacy_bottleneck_rates(paths, caps)
    mm = progressive_maxmin_rates(paths, caps)
    if any(abs(old[fid] - expected) > 1e-9 for fid, expected in {1: 20.0, 2: 50.0}.items()):
        raise AssertionError(f"counterexample legacy mismatch: {old}")
    if any(abs(mm[fid] - expected) > 1e-9 for fid, expected in {1: 20.0, 2: 80.0}.items()):
        raise AssertionError(f"counterexample max-min mismatch: {mm}")

    rng = random.Random(20260806)
    tested = 0
    for _ in range(1000):
        n_links = rng.randint(1, 8)
        n_flows = rng.randint(1, 12)
        link_names = [(f"u{i}", f"v{i}") for i in range(n_links)]
        capacities = {edge: rng.uniform(0.01, 100.0) for edge in link_names}
        flow_edges = {
            fid: rng.sample(link_names, rng.randint(1, min(4, n_links)))
            for fid in range(n_flows)
        }
        r0 = legacy_bottleneck_rates(flow_edges, capacities)
        rmm = progressive_maxmin_rates(flow_edges, capacities)
        for fid in flow_edges:
            if r0[fid] > rmm[fid] + 1e-8 * max(1.0, rmm[fid]):
                raise AssertionError("random lower-bound counterexample")
        tested += n_flows
    return {
        "counterexample_legacy": old,
        "counterexample_maxmin": mm,
        "random_networks": 1000,
        "random_flows_checked": tested,
        "lower_bound_violations": 0,
    }


def digest_items(items: Any) -> str:
    payload = json.dumps(items, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def placement_digest(ring: Sequence[str]) -> str:
    return digest_items(list(ring))


def capacity_digest(topo: sim.FatTree) -> str:
    return digest_items(sorted((u, v, cap) for (u, v), cap in topo.edge_of.items()))


def route_digest(topo: sim.FatTree, ring: Sequence[str], k: int) -> str:
    engine = sim.FlowLevelSimulator(topo, dt_s=DT)
    fids = sim.add_ring_neighbor_flows(engine, list(ring), 64 * MIB, flows_per_neighbor=k)
    rows = []
    for fid in fids:
        flow = engine.flows[fid]
        rows.append((flow.five_tuple.src, flow.five_tuple.dst, flow.five_tuple.sport, flow.path))
    return digest_items(rows)


def read_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


FROZEN_EQUAL = read_rows(ROOT / "results" / "v10.1_k_saturation_n1000" / "results.csv")
FROZEN_PROP = read_rows(ROOT / "results" / "v11.1_flexible_split_n1000" / "results.csv")
FROZEN_ADAPT = read_rows(
    ROOT / "results" / "v5.5_adaptive_n1000_placementfix" / "adaptive" / "results.csv"
)
FROZEN_BG = read_rows(ROOT / "results" / "v13.0_background_n1000" / "results.csv")


def one_row(rows: Sequence[Dict[str, str]], **want: Any) -> Dict[str, str]:
    matches = []
    for row in rows:
        ok = True
        for key, value in want.items():
            raw = row[key]
            if isinstance(value, float):
                ok = ok and abs(float(raw) - value) < 1e-12
            elif isinstance(value, int):
                ok = ok and int(raw) == value
            else:
                ok = ok and raw == str(value)
        if ok:
            matches.append(row)
    if len(matches) != 1:
        raise AssertionError(f"expected one frozen row for {want}, found {len(matches)}")
    return matches[0]


def common_row(
    *, cell: str, arm: str, seed: int, topo: sim.FatTree, ring: Sequence[str], k: int,
    condition: str, legacy_time: float, mm_time: float, audit: Mapping[str, float],
    legacy_source: str,
) -> Dict[str, Any]:
    return {
        "cell": cell,
        "arm": arm,
        "seed": seed,
        "condition": condition,
        "P": len(ring),
        "k": k,
        "legacy_time_s": legacy_time,
        "maxmin_time_s": mm_time,
        "maxmin_vs_legacy_pct": 100.0 * (mm_time / legacy_time - 1.0),
        "legacy_source": legacy_source,
        "placement_digest": placement_digest(ring),
        "capacity_digest": capacity_digest(topo),
        "route_digest": route_digest(topo, ring, max(1, k)),
        "strict_flow_fraction": audit.get("strict_flow_fraction", 0.0),
        "max_rate_ratio": audit.get("max_rate_ratio", 1.0),
        "reclaimed_edge_fraction": audit.get("reclaimed_edge_fraction", 0.0),
        "reclaimed_tick_fraction": audit.get("reclaimed_tick_fraction", 0.0),
        "max_reclaimed_fraction": audit.get("max_reclaimed_fraction", 0.0),
        "maxmin_ticks": audit.get("ticks", 0.0),
    }


def congestion_v5(affected_fraction: float, run_idx: int, base_seed: int) -> sim.CongestionModel:
    seed = base_seed + run_idx * 10_000_001
    return sim.CongestionModel(
        mode="onoff",
        seed=seed + int(affected_fraction * 1000),
        affected_fraction=affected_fraction,
        congested_util_low=0.50,
        congested_util_high=0.95,
        normal_util_low=0.00,
        normal_util_high=0.05,
        p_on=0.01,
        p_off=0.005,
        target_layers=["agg_core", "edge_agg"],
    )


def background_cfg(rate: int, run_idx: int) -> Optional[sim.BackgroundTrafficConfig]:
    if rate <= 0:
        return None
    seed = 0xBEEF + run_idx * 10_000_001
    return sim.BackgroundTrafficConfig(
        seed=seed + rate,
        arrival_rate_fps=rate,
        size_dist="lognormal",
        mean_bytes=50 * MIB,
        sigma_logn=1.0,
        locality="mixed",
        p_local=0.5,
    )


def run_dynamic_gate() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    # N0/O0: exact frozen static cells, including equal and proportional policies.
    for cell, fabric, oversub, seeds in (
        ("N0", "3tier_nb", 1.0, [0, 199, 657]),
        ("O0", "3tier_os4", 4.0, [0, 353, 174]),
    ):
        equal_ks = [1, 8] if cell == "N0" else [1, 8, 32]
        prop_ks = [8] if cell == "N0" else [8, 16]
        for seed in seeds:
            topo = sim.FatTree(16, n_tiers=3, oversub=oversub)
            ring = random.Random(SEED_BASE + seed).sample(topo.hosts, 64)
            for k in equal_ks:
                frozen = one_row(FROZEN_EQUAL, fabric=fabric, P=64, seed=seed, k=k)
                result, audit = run_progressive(
                    sim.run_simple_ring_transfer,
                    topo=topo,
                    ring=ring,
                    bytes_per_neighbor=64 * MIB,
                    flows_per_neighbor=k,
                    dt_s=DT,
                    congestion=None,
                )
                rows.append(common_row(
                    cell=cell, arm=f"equal_k{k}", seed=seed, topo=topo, ring=ring, k=k,
                    condition=f"{fabric}; no congestion", legacy_time=float(frozen["t_sim"]),
                    mm_time=float(result), audit=audit, legacy_source="v10.1 frozen",
                ))
            for k in prop_ks:
                frozen = one_row(FROZEN_PROP, fabric=fabric, P=64, seed=seed, k=k)
                result, audit = run_progressive(
                    sim.run_ring_transfer_proportional,
                    topo,
                    ring,
                    64 * MIB,
                    k,
                    dt_s=DT,
                )
                rows.append(common_row(
                    cell=cell, arm=f"prop_k{k}", seed=seed, topo=topo, ring=ring, k=k,
                    condition=f"{fabric}; no congestion", legacy_time=float(frozen["t_prop"]),
                    mm_time=float(result), audit=audit, legacy_source="v11.1 frozen",
                ))

    # C10/C50: exact frozen baseline/static/adaptive cells with selective on/off congestion.
    for af, seeds in ((0.1, [0, 278, 852]), (0.5, [0, 462, 869])):
        cell = f"C{int(af * 100):02d}"
        for seed in seeds:
            topology_seed = 0xCAFE + seed * 10_000_001
            topo = sim.FatTree(16, seed=topology_seed)
            ring = random.Random(SEED_BASE + seed).sample(topo.hosts, 64)
            for method, k in (("baseline", 1), ("static(k=4)", 4)):
                frozen = one_row(
                    FROZEN_ADAPT, run=seed + 1, ring_size=64,
                    affected_fraction=af, method=method,
                )
                result, audit = run_progressive(
                    sim.run_simple_ring_transfer,
                    topo=topo,
                    ring=ring,
                    bytes_per_neighbor=256 * MIB,
                    flows_per_neighbor=k,
                    dt_s=DT,
                    congestion=congestion_v5(af, seed, 0xCAFE),
                )
                rows.append(common_row(
                    cell=cell, arm=method, seed=seed, topo=topo, ring=ring, k=k,
                    condition=f"3tier_nb; onoff af={af}",
                    legacy_time=float(frozen["completion_time_s"]), mm_time=float(result),
                    audit=audit, legacy_source="v5.5 frozen",
                ))

            frozen = one_row(
                FROZEN_ADAPT, run=seed + 1, ring_size=64,
                affected_fraction=af, method="adaptive",
            )
            cfg = sim.AdaptiveConfig(
                measurement_window_s=0.001, threshold=0.2, k_max=4, cooldown_ticks=200
            )
            result, audit = run_progressive(
                sim.run_adaptive_ring_transfer,
                topo=topo,
                ring=ring,
                bytes_per_neighbor=256 * MIB,
                adaptive_cfg=cfg,
                dt_s=DT,
                congestion=congestion_v5(af, seed, 0xCAFE),
            )
            row = common_row(
                cell=cell, arm="adaptive", seed=seed, topo=topo, ring=ring,
                k=int(result["final_k_per_edge"] and max(result["final_k_per_edge"].values())),
                condition=f"3tier_nb; onoff af={af}",
                legacy_time=float(frozen["completion_time_s"]),
                mm_time=float(result["completion_time_s"]), audit=audit,
                legacy_source="v5.5 frozen",
            )
            row["legacy_final_k_mean"] = float(frozen["final_k_mean"])
            row["maxmin_final_k_mean"] = statistics.mean(result["final_k_per_edge"].values())
            rows.append(row)

    # B1000: exact frozen pipelined AllReduce cells with exogenous background arrivals.
    for seed in [0, 484, 731]:
        topo = sim.FatTree(16)
        ring = random.Random(SEED_BASE + seed).sample(topo.hosts, 16)
        for k in [1, 4]:
            for rate in [0, 1000]:
                frozen = one_row(FROZEN_BG, run=seed, k=k, arrival_rate_fps=rate)
                result, audit = run_progressive(
                    sim.run_ring_allreduce,
                    topo=topo,
                    ring=ring,
                    total_bytes_M=256 * MIB,
                    flows_per_neighbor=k,
                    dt_s=DT,
                    pipelined=True,
                    pipeline_window=4,
                    alpha_s=0.0,
                    background_cfg=background_cfg(rate, seed),
                )
                rows.append(common_row(
                    cell="B1000", arm=f"k{k}_rate{rate}", seed=seed, topo=topo,
                    ring=ring, k=k, condition=f"3tier_nb; background={rate} fps",
                    legacy_time=float(frozen["allreduce_time_s"]),
                    mm_time=float(result.total_time_s), audit=audit,
                    legacy_source="v13.0 frozen",
                ))

    # XOH: a new combined oversubscription+congestion stress cell, run on both allocators.
    for seed in [0, 1, 2]:
        topo = sim.FatTree(16, n_tiers=3, oversub=4.0)
        ring = random.Random(SEED_BASE + seed).sample(topo.hosts, 16)
        for policy, k in (("equal", 1), ("equal", 8), ("prop", 8)):
            def make_hotspot() -> sim.CongestionModel:
                return sim.CongestionModel(
                    mode="hot_spot", seed=1000 + seed, affected_fraction=0.3,
                    target_layers=["agg_core", "edge_agg"],
                    congested_util_low=0.50, congested_util_high=0.95,
                )

            if policy == "equal":
                legacy = sim.run_simple_ring_transfer(
                    topo=topo, ring=ring, bytes_per_neighbor=64 * MIB,
                    flows_per_neighbor=k, dt_s=DT, congestion=make_hotspot(),
                )
                mm, audit = run_progressive(
                    sim.run_simple_ring_transfer,
                    topo=topo, ring=ring, bytes_per_neighbor=64 * MIB,
                    flows_per_neighbor=k, dt_s=DT, congestion=make_hotspot(),
                )
            else:
                legacy = sim.run_ring_transfer_proportional(
                    topo, ring, 64 * MIB, k, dt_s=DT, congestion=make_hotspot()
                )
                mm, audit = run_progressive(
                    sim.run_ring_transfer_proportional,
                    topo, ring, 64 * MIB, k, dt_s=DT, congestion=make_hotspot()
                )
            rows.append(common_row(
                cell="XOH", arm=f"{policy}_k{k}", seed=seed, topo=topo, ring=ring, k=k,
                condition="3tier_os4; hot_spot af=0.3", legacy_time=float(legacy),
                mm_time=float(mm), audit=audit, legacy_source="gate recomputation",
            ))
    return rows


def snapshot_gate(n_seeds: int = 10) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for fabric, oversub in (("3tier_nb", 1.0), ("3tier_os2", 2.0), ("3tier_os4", 4.0)):
        for p in (16, 64):
            for k in (2, 8, 16):
                for seed in range(n_seeds):
                    for condition in ("none", "hot_spot"):
                        topo = sim.FatTree(16, n_tiers=3, oversub=oversub)
                        ring = random.Random(SEED_BASE + seed).sample(topo.hosts, p)
                        congestion = None
                        if condition == "hot_spot":
                            congestion = sim.CongestionModel(
                                mode="hot_spot", seed=1000 + seed, affected_fraction=0.3,
                                target_layers=["agg_core", "edge_agg"],
                                congested_util_low=0.50, congested_util_high=0.95,
                            )
                        engine = sim.FlowLevelSimulator(topo, dt_s=DT, congestion=congestion)
                        fids = sim.add_ring_neighbor_flows(
                            engine, ring, 64 * MIB, flows_per_neighbor=k
                        )
                        if congestion is not None:
                            congestion.update_tick()
                        flow_edges = {
                            fid: engine._flow_edges(engine.flows[fid]) for fid in fids
                        }
                        used = {edge for edges in flow_edges.values() for edge in edges}
                        caps = {}
                        for edge in used:
                            nominal = topo.edge_of[edge]
                            caps[edge] = (
                                congestion.residual_capacity(edge, nominal)
                                if congestion is not None else nominal
                            )
                        r0 = legacy_bottleneck_rates(flow_edges, caps)
                        rmm = progressive_maxmin_rates(flow_edges, caps)
                        def materially_gt(left: float, right: float) -> bool:
                            return left > right + 1e-8 * max(1.0, abs(left), abs(right))

                        violations = sum(materially_gt(r0[fid], rmm[fid]) for fid in fids)
                        strict = [fid for fid in fids if materially_gt(rmm[fid], r0[fid])]
                        finite_ratios = [rmm[fid] / r0[fid] for fid in fids if r0[fid] > 0]
                        rows.append({
                            "fabric": fabric, "P": p, "k": k, "seed": seed,
                            "condition": condition, "flows": len(fids),
                            "lower_bound_violations": violations,
                            "strict_flow_fraction": len(strict) / len(fids),
                            "mean_rate_ratio": statistics.mean(finite_ratios),
                            "max_rate_ratio": max(finite_ratios),
                            "sum_rate_ratio": sum(rmm.values()) / sum(r0.values()),
                            "placement_digest": placement_digest(ring),
                            "capacity_digest": capacity_digest(topo),
                            "route_digest": route_digest(topo, ring, k),
                        })
    return rows


def reproduction_guards() -> Dict[str, Any]:
    checks = []

    topo = sim.FatTree(16)
    ring = random.Random(SEED_BASE).sample(topo.hosts, 64)
    frozen = one_row(FROZEN_EQUAL, fabric="3tier_nb", P=64, seed=0, k=8)
    actual = sim.run_simple_ring_transfer(topo, ring, 64 * MIB, 8, dt_s=DT)
    checks.append(("N0 equal", actual, float(frozen["t_sim"])))

    topo = sim.FatTree(16, oversub=4.0)
    ring = random.Random(SEED_BASE).sample(topo.hosts, 64)
    frozen = one_row(FROZEN_PROP, fabric="3tier_os4", P=64, seed=0, k=8)
    actual = sim.run_ring_transfer_proportional(topo, ring, 64 * MIB, 8, dt_s=DT)
    checks.append(("O0 proportional", actual, float(frozen["t_prop"])))

    topo_seed = 0xCAFE
    topo = sim.FatTree(16, seed=topo_seed)
    ring = random.Random(SEED_BASE).sample(topo.hosts, 64)
    frozen = one_row(
        FROZEN_ADAPT, run=1, ring_size=64, affected_fraction=0.1, method="baseline"
    )
    actual = sim.run_simple_ring_transfer(
        topo, ring, 256 * MIB, 1, dt_s=DT, congestion=congestion_v5(0.1, 0, 0xCAFE)
    )
    checks.append(("C10 baseline", actual, float(frozen["completion_time_s"])))

    failures = []
    for name, actual, expected in checks:
        if abs(actual - expected) > 1e-12:
            failures.append({"name": name, "actual": actual, "frozen": expected})
    if failures:
        raise AssertionError(f"frozen reproduction failures: {failures}")
    return {
        "checks": [
            {"name": name, "actual": actual, "frozen": expected}
            for name, actual, expected in checks
        ],
        "failures": 0,
    }


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        return
    fields: List[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summarize(dynamic: Sequence[Mapping[str, Any]], snapshots: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    groups: Dict[Tuple[str, str], List[Mapping[str, Any]]] = defaultdict(list)
    for row in dynamic:
        groups[(str(row["cell"]), str(row["arm"]))].append(row)
    dynamic_summary = []
    for (cell, arm), rows in sorted(groups.items()):
        deltas = [float(row["maxmin_vs_legacy_pct"]) for row in rows]
        dynamic_summary.append({
            "cell": cell,
            "arm": arm,
            "n": len(rows),
            "legacy_mean_s": statistics.mean(float(row["legacy_time_s"]) for row in rows),
            "maxmin_mean_s": statistics.mean(float(row["maxmin_time_s"]) for row in rows),
            "mean_delta_pct": statistics.mean(deltas),
            "min_delta_pct": min(deltas),
            "max_delta_pct": max(deltas),
            "strict_allocator_ticks_seen": any(float(row["reclaimed_tick_fraction"]) > 0 for row in rows),
        })

    snap_groups: Dict[Tuple[str, str], List[Mapping[str, Any]]] = defaultdict(list)
    for row in snapshots:
        snap_groups[(str(row["fabric"]), str(row["condition"]))].append(row)
    snapshot_summary = []
    for (fabric, condition), rows in sorted(snap_groups.items()):
        snapshot_summary.append({
            "fabric": fabric,
            "condition": condition,
            "n_snapshots": len(rows),
            "flows": sum(int(row["flows"]) for row in rows),
            "lower_bound_violations": sum(int(row["lower_bound_violations"]) for row in rows),
            "mean_strict_flow_fraction": statistics.mean(float(row["strict_flow_fraction"]) for row in rows),
            "mean_sum_rate_ratio": statistics.mean(float(row["sum_rate_ratio"]) for row in rows),
            "max_rate_ratio": max(float(row["max_rate_ratio"]) for row in rows),
        })
    return {"dynamic": dynamic_summary, "snapshots": snapshot_summary}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-seeds", type=int, default=10)
    parser.add_argument("--skip-dynamic", action="store_true")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.time()
    unit = unit_guards()
    reproduction = reproduction_guards()
    snapshots = snapshot_gate(args.snapshot_seeds)
    dynamic = [] if args.skip_dynamic else run_dynamic_gate()
    summary = summarize(dynamic, snapshots)

    write_csv(OUT_DIR / "snapshot_rates.csv", snapshots)
    write_csv(OUT_DIR / "paired_completion.csv", dynamic)
    payload = {
        "created": "2026-08-06",
        "sim_py_sha256": hashlib.sha256((ROOT / "sim.py").read_bytes()).hexdigest(),
        "frozen_inputs_written": False,
        "unit_guards": unit,
        "reproduction_guards": reproduction,
        "summary": summary,
        "elapsed_s": time.time() - started,
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
