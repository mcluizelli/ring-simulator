from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Iterable
import hashlib
import math
import random


Node = str
Edge = Tuple[Node, Node]  # directed (u -> v)


# ----------------------------
# Utilities
# ----------------------------

def stable_hash_int(*parts: object) -> int:
    """Deterministic hash across runs."""
    h = hashlib.blake2b(digest_size=8)
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"|")
    return int.from_bytes(h.digest(), "big")


# ----------------------------
# Flow objects
# ----------------------------

@dataclass(frozen=True)
class Flow5Tuple:
    src: Node
    dst: Node
    sport: int
    dport: int
    proto: int = 6  # TCP-like


@dataclass
class Flow:
    fid: int
    five_tuple: Flow5Tuple
    path: List[Node]
    remaining_bytes: float
    sent_bytes: float = 0.0
    last_rate_Bps: float = 0.0


@dataclass
class AdaptiveConfig:
    """Configuration for the adaptive multi-flow controller."""
    measurement_window_s: float = 0.001   # 20 ticks at dt=50µs
    threshold: float = 0.2               # add flow if rate < (1-threshold) * nominal
    k_max: int = 8                        # max flows per logical edge
    cooldown_ticks: int = 200             # min ticks between additions (~10ms)
    base_sport: int = 10000
    dport: int = 20000
    proto: int = 6


@dataclass
class LogicalEdgeState:
    """Runtime state for one logical ring edge during adaptive simulation."""
    src: Node
    dst: Node
    edge_index: int
    total_bytes_target: float
    flow_ids: List[int]
    current_k: int = 1
    last_add_tick: int = 0
    window_bytes_start: float = 0.0
    window_time_start: float = 0.0

    def total_sent(self, flows: Dict[int, Flow]) -> float:
        return sum(flows[fid].sent_bytes for fid in self.flow_ids)

    def total_remaining(self, flows: Dict[int, Flow]) -> float:
        return sum(flows[fid].remaining_bytes for fid in self.flow_ids
                   if flows[fid].remaining_bytes > 0)

    def aggregate_rate(self, flows: Dict[int, Flow]) -> float:
        return sum(flows[fid].last_rate_Bps for fid in self.flow_ids
                   if flows[fid].remaining_bytes > 0)


# --- Drop-in replacement: 3-tier k-ary Fat-Tree (Edge/ToR + Agg + Core) ---
# Replace ONLY your current FatTree class with this one.
# Everything else in your simulator can stay unchanged.


class FatTree:
    """
    Standard 3-tier k-ary fat-tree:

    Parameters:
      k: even integer

    Structure:
      - Pods: k
      - Edge(ToR) switches per pod: k/2
      - Aggregation switches per pod: k/2
      - Hosts per edge switch: k/2
      - Core switches: (k/2)^2, indexed c{g}_{i}
          g = core group in [0..k/2-1]
          i = index within group in [0..k/2-1]

    Links (bidirectional, modeled as two directed edges):
      host <-> edge
      edge(p,e) <-> agg(p,a) for all a
      agg(p,a) <-> core(a,i) for all i   (agg index selects the core group)
    """

    def __init__(self, k: int, link_capacity_Gbps: float = 100.0, seed: int = 1) -> None:
        if k % 2 != 0:
            raise ValueError("k must be even for a k-ary fat-tree.")
        self.k = k
        self.rng = random.Random(seed)

        self.capacity_Bps: float = link_capacity_Gbps * 1e9 / 8.0
        self.nodes: List[Node] = []
        self.adj: Dict[Node, List[Node]] = {}
        self.edge_of: Dict[Edge, float] = {}  # directed capacity (B/s)

        self.core: List[Node] = []
        self.agg: List[Node] = []
        self.edge: List[Node] = []
        self.hosts: List[Node] = []

        self._build()

    def _add_node(self, n: Node) -> None:
        if n not in self.adj:
            self.adj[n] = []
            self.nodes.append(n)

    def _add_link(self, u: Node, v: Node, cap_Bps: Optional[float] = None) -> None:
        self._add_node(u)
        self._add_node(v)
        self.adj[u].append(v)
        self.edge_of[(u, v)] = self.capacity_Bps if cap_Bps is None else cap_Bps

    def _build(self) -> None:
        k = self.k
        k2 = k // 2

        # Core: groups g, index i => total (k/2)^2
        for g in range(k2):
            for i in range(k2):
                c = f"c{g}_{i}"
                self.core.append(c)
                self._add_node(c)

        # Pods
        for p in range(k):
            # Edge(ToR) switches in pod p
            for e in range(k2):
                esw = f"e{p}_{e}"
                self.edge.append(esw)
                self._add_node(esw)

                # Hosts under this edge switch
                for h in range(k2):
                    host = f"h{p}_{e}_{h}"
                    self.hosts.append(host)
                    self._add_node(host)
                    self._add_link(host, esw)
                    self._add_link(esw, host)

            # Aggregation switches in pod p
            for a in range(k2):
                asw = f"a{p}_{a}"
                self.agg.append(asw)
                self._add_node(asw)

            # Edge <-> Agg (full bipartite within pod)
            for e in range(k2):
                esw = f"e{p}_{e}"
                for a in range(k2):
                    asw = f"a{p}_{a}"
                    self._add_link(esw, asw)
                    self._add_link(asw, esw)

            # Agg(p,a) <-> Core(group=a, i=0..k/2-1)
            # This is the standard fat-tree wiring that enables ECMP.
            for a in range(k2):
                asw = f"a{p}_{a}"
                for i in range(k2):
                    c = f"c{a}_{i}"
                    self._add_link(asw, c)
                    self._add_link(c, asw)

    # ---- Helpers for routing ----

    def get_edges_by_layer(self) -> Dict[str, List[Edge]]:
        """
        Classify all directed edges by their layer in the Fat-Tree.

        Returns dict with keys:
            'host_edge'  — host ↔ edge switch (single-path, no ECMP alternative)
            'edge_agg'   — edge ↔ aggregation switch (intra-pod diversity)
            'agg_core'   — aggregation ↔ core switch (inter-pod diversity)

        In a real Fat-Tree, congestion mainly occurs at agg↔core (where
        cross-pod traffic converges) and to a lesser extent edge↔agg.
        Host↔edge links are typically not congested because they carry
        only that host's traffic.
        """
        layers: Dict[str, List[Edge]] = {
            "host_edge": [],
            "edge_agg": [],
            "agg_core": [],
        }
        for (u, v) in self.edge_of:
            u0, v0 = u[0], v[0]
            if u0 == "h" or v0 == "h":
                layers["host_edge"].append((u, v))
            elif (u0 == "e" and v0 == "a") or (u0 == "a" and v0 == "e"):
                layers["edge_agg"].append((u, v))
            elif (u0 == "a" and v0 == "c") or (u0 == "c" and v0 == "a"):
                layers["agg_core"].append((u, v))
        return layers

    def host_to_edge(self, host: Node) -> Node:
        # host name: h{p}_{e}_{h}
        p, e, _ = map(int, host[1:].split("_"))
        return f"e{p}_{e}"

    def host_to_pod(self, host: Node) -> int:
        p, _, _ = map(int, host[1:].split("_"))
        return p

    def equal_cost_paths_hosts(self, src_host: Node, dst_host: Node) -> List[List[Node]]:
        """
        Enumerate equal-cost paths between two hosts.

        Cases:
          1) Same edge switch: 1 path
          2) Same pod, different edge: k/2 paths via different aggs
          3) Different pods: (k/2)^2 paths via (agg index a) and (core index i)
        """
        if src_host == dst_host:
            return [[src_host]]

        k2 = self.k // 2
        src_edge = self.host_to_edge(src_host)
        dst_edge = self.host_to_edge(dst_host)
        src_pod = self.host_to_pod(src_host)
        dst_pod = self.host_to_pod(dst_host)

        # same ToR
        if src_edge == dst_edge:
            return [[src_host, src_edge, dst_host]]

        # same pod
        if src_pod == dst_pod:
            paths: List[List[Node]] = []
            for a in range(k2):
                asw = f"a{src_pod}_{a}"
                # host -> src_edge -> agg -> dst_edge -> host
                paths.append([src_host, src_edge, asw, dst_edge, dst_host])
            return paths

        # different pods
        paths: List[List[Node]] = []
        for a in range(k2):
            asw_src = f"a{src_pod}_{a}"
            asw_dst = f"a{dst_pod}_{a}"
            for i in range(k2):
                core = f"c{a}_{i}"
                # host -> src_edge -> agg(src,a) -> core(a,i) -> agg(dst,a) -> dst_edge -> host
                paths.append([src_host, src_edge, asw_src, core, asw_dst, dst_edge, dst_host])
        return paths

    def ecmp_pick_path(self, five_tuple) -> List[Node]:
        """
        ECMP: hash 5-tuple, pick one among equal-cost paths.
        Requires stable_hash_int to be defined in your file (as you already have).
        """
        paths = self.equal_cost_paths_hosts(five_tuple.src, five_tuple.dst)
        if len(paths) == 1:
            return paths[0]
        h = stable_hash_int(
            five_tuple.src, five_tuple.dst, five_tuple.sport, five_tuple.dport, five_tuple.proto
        )
        return paths[h % len(paths)]
    
# ----------------------------
# Random congestion: residual-capacity impairment
# ----------------------------

@dataclass
class CongestionModel:
    """
    Background utilization u(e,t) in [0,1] reduces capacity:
      residual_cap = (1-u)*nominal_cap

    mode:
      - "iid": per tick independent utilization draws
      - "onoff": persistent bursts via per-link on/off process
    """
    mode: str = "onoff"
    seed: int = 1

    affected_fraction: float = 0.10

    congested_util_low: float = 0.30
    congested_util_high: float = 0.80
    normal_util_low: float = 0.00
    normal_util_high: float = 0.10

    p_on: float = 0.002
    p_off: float = 0.010

    # Which Fat-Tree layers to target for congestion.
    # None = all edges (legacy behavior).
    # List of layer names from FatTree.get_edges_by_layer():
    #   "agg_core", "edge_agg", "host_edge"
    # Realistic setting: ["agg_core", "edge_agg"] — congestion only on
    # links where ECMP provides alternative paths (cross-pod traffic).
    target_layers: Optional[List[str]] = None

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self._affected: Optional[set[Edge]] = None
        self._state: Dict[Edge, bool] = {}
        self._util: Dict[Edge, float] = {}

    def attach(self, all_edges: List[Edge], target_edges: Optional[List[Edge]] = None) -> None:
        """
        Select which edges are subject to congestion.

        Parameters:
            all_edges: all directed edges in the topology (used as fallback)
            target_edges: if provided, congestion is sampled ONLY from this
                subset. Use FatTree.get_edges_by_layer() to target specific
                layers (e.g., agg_core + edge_agg for realistic data-center
                congestion where cross-pod traffic causes link saturation).
        """
        pool = target_edges if target_edges is not None else all_edges
        m = max(1, int(self.affected_fraction * len(pool)))
        self._affected = set(self.rng.sample(pool, m))
        for e in self._affected:
            self._state[e] = False

    def _draw_util(self, congested: bool) -> float:
        if congested:
            return self.rng.uniform(self.congested_util_low, self.congested_util_high)
        return self.rng.uniform(self.normal_util_low, self.normal_util_high)

    def update_tick(self) -> None:
        if self._affected is None:
            raise RuntimeError("CongestionModel.attach(...) must be called first.")
        self._util.clear()

        if self.mode == "iid":
            for e in self._affected:
                spike = (self.rng.random() < 0.05)
                self._util[e] = self._draw_util(congested=spike)
            return

        if self.mode == "onoff":
            for e in self._affected:
                congested = self._state[e]
                if congested:
                    if self.rng.random() < self.p_off:
                        congested = False
                else:
                    if self.rng.random() < self.p_on:
                        congested = True
                self._state[e] = congested
                self._util[e] = self._draw_util(congested)
            return

        raise ValueError(f"Unknown mode: {self.mode}")

    def residual_capacity(self, edge: Edge, nominal_cap_Bps: float) -> float:
        u = self._util.get(edge, 0.0)
        return max(0.0, (1.0 - u) * nominal_cap_Bps)


# ----------------------------
# Random congestion: background traffic injection
# ----------------------------

@dataclass
class BackgroundTrafficConfig:
    seed: int = 1
    arrival_rate_fps: float = 200.0  # flows per second

    size_dist: str = "lognormal"     # "lognormal" | "pareto" | "fixed"
    mean_bytes: float = 2 * 1024 * 1024
    sigma_logn: float = 1.0
    pareto_alpha: float = 1.3
    pareto_xm_bytes: float = 64 * 1024
    fixed_bytes: float = 1 * 1024 * 1024

    locality: str = "mixed"          # "uniform" | "same_edge" | "same_pod" | "mixed"
    p_local: float = 0.5             # for "mixed"

    base_sport: int = 30000
    dport: int = 40000
    proto: int = 6


class BackgroundTrafficGenerator:
    def __init__(self, topo: FatTree, cfg: BackgroundTrafficConfig):
        self.topo = topo
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        self._sport_counter = 0

    def _draw_flow_size(self) -> float:
        c = self.cfg
        if c.size_dist == "fixed":
            return float(c.fixed_bytes)
        if c.size_dist == "lognormal":
            sigma = c.sigma_logn
            mu = math.log(max(1.0, c.mean_bytes)) - 0.5 * sigma * sigma
            x = self.rng.lognormvariate(mu, sigma)
            return float(max(1.0, x))
        if c.size_dist == "pareto":
            U = max(1e-12, self.rng.random())
            x = c.pareto_xm_bytes / (U ** (1.0 / c.pareto_alpha))
            return float(max(1.0, x))
        raise ValueError(f"Unknown size_dist={c.size_dist}")

    def _pick_uniform_pair(self) -> Tuple[Node, Node]:
        src = self.rng.choice(self.topo.hosts)
        dst = self.rng.choice(self.topo.hosts)
        while dst == src:
            dst = self.rng.choice(self.topo.hosts)
        return src, dst

    def _pick_same_edge_pair(self) -> Tuple[Node, Node]:
        esw = self.rng.choice(self.topo.edge)
        p, e = map(int, esw[1:].split("_"))
        candidates = [h for h in self.topo.hosts if h.startswith(f"h{p}_{e}_")]
        src, dst = self.rng.sample(candidates, 2)
        return src, dst

    def _pick_same_pod_pair(self) -> Tuple[Node, Node]:
        pod = self.rng.randrange(self.topo.k)
        candidates = [h for h in self.topo.hosts if h.startswith(f"h{pod}_")]
        src, dst = self.rng.sample(candidates, 2)
        return src, dst

    def _pick_pair(self) -> Tuple[Node, Node]:
        loc = self.cfg.locality
        if loc == "uniform":
            return self._pick_uniform_pair()
        if loc == "same_edge":
            return self._pick_same_edge_pair()
        if loc == "same_pod":
            return self._pick_same_pod_pair()
        if loc == "mixed":
            if self.rng.random() < self.cfg.p_local:
                return self._pick_same_pod_pair()
            return self._pick_uniform_pair()
        raise ValueError(f"Unknown locality={loc}")

    @staticmethod
    def _poisson(rng: random.Random, lam: float) -> int:
        # Knuth algorithm; OK for small lam (dt small)
        L = math.exp(-lam)
        k = 0
        p = 1.0
        while p > L:
            k += 1
            p *= rng.random()
        return max(0, k - 1)

    def inject_for_tick(self, sim: "FlowLevelSimulator") -> List[int]:
        dt = sim.dt_s
        lam = self.cfg.arrival_rate_fps * dt
        arrivals = self._poisson(self.rng, lam)

        fids: List[int] = []
        for _ in range(arrivals):
            src, dst = self._pick_pair()
            size = self._draw_flow_size()
            sport = self.cfg.base_sport + (self._sport_counter % 20000)
            self._sport_counter += 1
            ft = Flow5Tuple(src=src, dst=dst, sport=sport, dport=self.cfg.dport, proto=self.cfg.proto)
            fids.append(sim.add_flow(ft, size))
        return fids


# ----------------------------
# Flow-level simulator
# ----------------------------

class FlowLevelSimulator:
    """
    Discrete-time fluid model:
      - ECMP pins each flow to exactly one equal-cost path
      - each directed link shares capacity equally among flows using it
      - each flow gets bottleneck share along its path
    """

    def __init__(
        self,
        topo: FatTree,
        dt_s: float = 5e-5,
        congestion: Optional[CongestionModel] = None,
        background: Optional[BackgroundTrafficGenerator] = None,
    ) -> None:
        if dt_s <= 0:
            raise ValueError("dt_s must be positive.")
        self.topo = topo
        self.dt_s = dt_s
        self.time_s: float = 0.0

        self._next_fid: int = 1
        self.flows: Dict[int, Flow] = {}
        self.edge_bytes_sent: Dict[Edge, float] = {}

        self.congestion = congestion
        if self.congestion is not None:
            all_edges = list(self.topo.edge_of.keys())
            target = None
            if hasattr(self.congestion, 'target_layers') and self.congestion.target_layers is not None:
                layers = self.topo.get_edges_by_layer()
                target = []
                for layer_name in self.congestion.target_layers:
                    target.extend(layers.get(layer_name, []))
            self.congestion.attach(all_edges, target_edges=target)

        self.background = background

    def add_flow(self, five_tuple: Flow5Tuple, bytes_to_send: float) -> int:
        if bytes_to_send <= 0:
            raise ValueError("bytes_to_send must be positive.")
        path = self.topo.ecmp_pick_path(five_tuple)
        fid = self._next_fid
        self._next_fid += 1
        self.flows[fid] = Flow(fid=fid, five_tuple=five_tuple, path=path, remaining_bytes=float(bytes_to_send))
        return fid

    @staticmethod
    def _path_edges(path: List[Node]) -> List[Edge]:
        if len(path) <= 1:
            return []
        return list(zip(path[:-1], path[1:]))

    def _flow_edges(self, f: Flow) -> List[Edge]:
        return self._path_edges(f.path)

    def get_edge_avg_throughput(self, edges: Optional[List[Edge]] = None) -> Dict[Edge, float]:
        """Average throughput (bytes/s) on each edge over the simulation so far."""
        if self.time_s <= 0:
            target = edges if edges is not None else list(self.edge_bytes_sent.keys())
            return {e: 0.0 for e in target}
        if edges is not None:
            return {e: self.edge_bytes_sent.get(e, 0.0) / self.time_s for e in edges}
        return {e: b / self.time_s for e, b in self.edge_bytes_sent.items()}

    def step(self) -> None:
        # Inject background flows first (arrive during this tick)
        if self.background is not None:
            self.background.inject_for_tick(self)

        # Update congestion process (affects residual capacities this tick)
        if self.congestion is not None:
            self.congestion.update_tick()

        active = [f for f in self.flows.values() if f.remaining_bytes > 0]

        # link -> flow list
        link_users: Dict[Edge, List[int]] = {}
        for f in active:
            for e in self._flow_edges(f):
                link_users.setdefault(e, []).append(f.fid)

        # compute per-link fair share using effective capacity
        link_share: Dict[Edge, float] = {}
        for e, fids in link_users.items():
            nominal = self.topo.edge_of.get(e, 0.0)
            cap = nominal
            if self.congestion is not None:
                cap = self.congestion.residual_capacity(e, nominal)
            link_share[e] = (cap / max(1, len(fids))) if cap > 0 else 0.0

        # per-flow bottleneck rate
        for f in active:
            edges = self._flow_edges(f)
            if not edges:
                f.last_rate_Bps = float("inf")
            else:
                f.last_rate_Bps = min(link_share.get(e, 0.0) for e in edges)

        # advance bytes
        for f in active:
            rate = f.last_rate_Bps
            if not math.isfinite(rate) or rate <= 0:
                continue
            send = min(f.remaining_bytes, rate * self.dt_s)
            f.remaining_bytes -= send
            f.sent_bytes += send
            if send > 0:
                for e in self._flow_edges(f):
                    self.edge_bytes_sent[e] = self.edge_bytes_sent.get(e, 0.0) + send

        self.time_s += self.dt_s

    def run_until(
        self,
        done_predicate,
        max_steps: int = 10_000_000,
    ) -> float:
        for _ in range(max_steps):
            if done_predicate():
                return self.time_s
            self.step()
        raise RuntimeError("Simulation did not finish within max_steps.")


# ----------------------------
# Ring builders and traffic
# ----------------------------

def build_worker_ring(hosts: List[Node], worker_count: int, start_index: int = 0) -> List[Node]:
    if worker_count < 2:
        raise ValueError("worker_count must be >= 2.")
    if worker_count > len(hosts):
        raise ValueError("worker_count exceeds host count.")
    return [hosts[(start_index + i) % len(hosts)] for i in range(worker_count)]


def add_ring_neighbor_flows(
    sim: FlowLevelSimulator,
    ring: List[Node],
    bytes_per_neighbor: float,
    flows_per_neighbor: int = 1,
    base_sport: int = 10000,
    dport: int = 20000,
    proto: int = 6,
) -> List[int]:
    """
    Each worker i sends bytes_per_neighbor to (i+1) mod P.
    flows_per_neighbor splits this into parallel flows with different 5-tuples (ECMP spreading).
    """
    if bytes_per_neighbor <= 0:
        raise ValueError("bytes_per_neighbor must be positive.")
    if flows_per_neighbor < 1:
        raise ValueError("flows_per_neighbor must be >= 1.")

    fids: List[int] = []
    P = len(ring)
    per_flow_bytes = bytes_per_neighbor / flows_per_neighbor
    for i in range(P):
        src = ring[i]
        dst = ring[(i + 1) % P]
        for j in range(flows_per_neighbor):
            ft = Flow5Tuple(
                src=src,
                dst=dst,
                sport=base_sport + i * 100 + j,
                dport=dport,
                proto=proto,
            )
            fids.append(sim.add_flow(ft, per_flow_bytes))
    return fids


# ----------------------------
# Ring all-reduce (step-based)
# ----------------------------

@dataclass
class AllReduceResult:
    total_time_s: float
    step_times_s: List[float]


def add_one_allreduce_step(
    sim: FlowLevelSimulator,
    ring: List[Node],
    step_bytes_total: float,
    flows_per_neighbor: int,
    step_id: int,
    base_sport: int = 50000,
    dport: int = 51000,
    proto: int = 6,
) -> List[int]:
    fids: List[int] = []
    P = len(ring)
    per_flow_bytes = step_bytes_total / max(1, flows_per_neighbor)

    for i in range(P):
        src = ring[i]
        dst = ring[(i + 1) % P]
        for j in range(flows_per_neighbor):
            ft = Flow5Tuple(
                src=src,
                dst=dst,
                sport=base_sport + step_id * 10_000 + i * 100 + j,
                dport=dport,
                proto=proto,
            )
            fids.append(sim.add_flow(ft, per_flow_bytes))
    return fids


def run_ring_allreduce(
    topo: FatTree,
    ring: List[Node],
    total_bytes_M: float,
    flows_per_neighbor: int = 1,
    dt_s: float = 5e-5,
    pipelined: bool = True,
    pipeline_window: int = 4,
    alpha_s: float = 0.0,
    congestion: Optional[CongestionModel] = None,
    background_cfg: Optional[BackgroundTrafficConfig] = None,
    max_steps: int = 15_000_000,
) -> AllReduceResult:
    if total_bytes_M <= 0:
        raise ValueError("total_bytes_M must be positive.")
    P = len(ring)
    if P < 2:
        raise ValueError("Ring must have at least 2 workers.")
    if pipeline_window < 1:
        raise ValueError("pipeline_window must be >= 1.")

    background = BackgroundTrafficGenerator(topo, background_cfg) if background_cfg is not None else None
    sim = FlowLevelSimulator(topo, dt_s=dt_s, congestion=congestion, background=background)

    chunk_bytes = total_bytes_M / P
    steps_each_phase = P - 1
    total_steps = 2 * steps_each_phase

    step_times: List[float] = []

    if not pipelined:
        for s in range(total_steps):
            step_fids = add_one_allreduce_step(sim, ring, chunk_bytes, flows_per_neighbor, step_id=s)
            t_start = sim.time_s

            def done_step() -> bool:
                return all(sim.flows[fid].remaining_bytes <= 0 for fid in step_fids)

            sim.run_until(done_step, max_steps=max_steps)
            t_end = sim.time_s
            step_times.append((t_end - t_start) + alpha_s)

        return AllReduceResult(total_time_s=sim.time_s + alpha_s * total_steps, step_times_s=step_times)

    # pipelined
    step_to_fids: Dict[int, List[int]] = {}
    step_start: Dict[int, float] = {}
    injected = 0
    completed = 0

    init = min(pipeline_window, total_steps)
    for s in range(init):
        step_to_fids[s] = add_one_allreduce_step(sim, ring, chunk_bytes, flows_per_neighbor, step_id=s)
        step_start[s] = sim.time_s
        injected += 1

    for _ in range(max_steps):
        if completed >= total_steps:
            break

        sim.step()

        done_steps = [s for s, fids in step_to_fids.items()
                      if all(sim.flows[fid].remaining_bytes <= 0 for fid in fids)]
        if not done_steps:
            continue

        for s in sorted(done_steps):
            t_done = sim.time_s
            step_times.append((t_done - step_start[s]) + alpha_s)
            del step_to_fids[s]
            del step_start[s]
            completed += 1

            if injected < total_steps:
                ns = injected
                step_to_fids[ns] = add_one_allreduce_step(sim, ring, chunk_bytes, flows_per_neighbor, step_id=ns)
                step_start[ns] = sim.time_s
                injected += 1

    if completed < total_steps:
        raise RuntimeError("All-reduce did not complete within max_steps.")

    return AllReduceResult(total_time_s=sim.time_s + alpha_s * total_steps, step_times_s=step_times)


# ----------------------------
# Example drivers
# ----------------------------

def compute_ring_theoretical_time(
    topo: FatTree,
    ring: List[Node],
    bytes_per_neighbor: float,
    flows_per_neighbor: int = 1,
    base_sport: int = 10000,
    dport: int = 20000,
    proto: int = 6,
) -> Dict:
    """
    Compute the theoretical completion time for a ring transfer WITHOUT
    running a simulation.  Replicates the exact 5-tuple construction from
    add_ring_neighbor_flows() so that ECMP path selection is identical.

    Returns dict with:
        theoretical_time_s        – bytes_per_neighbor / B*
        bottleneck_bandwidth_Bps  – B* (min logical-edge throughput)
        per_logical_edge_throughput – {(src,dst): throughput_Bps}
        edge_contention            – {physical_edge: num_ring_flows}
    """
    P = len(ring)
    per_flow_bytes = bytes_per_neighbor / flows_per_neighbor

    # 1. Build 5-tuples and get ECMP paths (identical logic to add_ring_neighbor_flows)
    logical_edge_flows: Dict[Edge, List[List[Node]]] = {}  # (src,dst) -> list of paths
    edge_flow_count: Dict[Edge, int] = {}  # physical edge -> count

    for i in range(P):
        src = ring[i]
        dst = ring[(i + 1) % P]
        logical_edge = (src, dst)
        logical_edge_flows.setdefault(logical_edge, [])

        for j in range(flows_per_neighbor):
            ft = Flow5Tuple(
                src=src, dst=dst,
                sport=base_sport + i * 100 + j,
                dport=dport,
                proto=proto,
            )
            path = topo.ecmp_pick_path(ft)
            logical_edge_flows[logical_edge].append(path)

            # Count contention on each physical edge
            path_edges = list(zip(path[:-1], path[1:]))
            for e in path_edges:
                edge_flow_count[e] = edge_flow_count.get(e, 0) + 1

    # 2. For each flow, compute bottleneck rate = min(link_cap / contention) over its path
    per_logical_edge_throughput: Dict[Edge, float] = {}

    for logical_edge, paths in logical_edge_flows.items():
        total_throughput = 0.0
        for path in paths:
            path_edges = list(zip(path[:-1], path[1:]))
            if not path_edges:
                continue
            flow_rate = min(
                topo.edge_of.get(e, 0.0) / max(1, edge_flow_count.get(e, 1))
                for e in path_edges
            )
            total_throughput += flow_rate
        per_logical_edge_throughput[logical_edge] = total_throughput

    # 3. Bottleneck = min logical-edge throughput
    bottleneck_bw = min(per_logical_edge_throughput.values()) if per_logical_edge_throughput else 0.0
    theoretical_time = bytes_per_neighbor / bottleneck_bw if bottleneck_bw > 0 else float("inf")

    return {
        "theoretical_time_s": theoretical_time,
        "bottleneck_bandwidth_Bps": bottleneck_bw,
        "per_logical_edge_throughput": per_logical_edge_throughput,
        "edge_contention": edge_flow_count,
    }


def run_simple_ring_transfer(
    topo: FatTree,
    ring: List[Node],
    bytes_per_neighbor: float,
    flows_per_neighbor: int,
    dt_s: float = 5e-5,
    congestion: Optional[CongestionModel] = None,
    background_cfg: Optional[BackgroundTrafficConfig] = None,
    max_steps: int = 12_000_000,
    return_metrics: bool = False,
):
    """
    Run a simple ring neighbor transfer.

    When return_metrics is False (default), returns a float (completion time)
    for backward compatibility.

    When return_metrics is True, returns a dict with detailed metrics:
        completion_time_s, theoretical_time_s, bottleneck_bandwidth_Bps,
        per_logical_edge_throughput_Bps, ring_edges, ring_size,
        bytes_per_neighbor, flows_per_neighbor
    """
    background = BackgroundTrafficGenerator(topo, background_cfg) if background_cfg is not None else None

    sim = FlowLevelSimulator(topo, dt_s=dt_s, congestion=congestion, background=background)

    ring_fids = add_ring_neighbor_flows(sim, ring, bytes_per_neighbor, flows_per_neighbor=flows_per_neighbor)

    def done_ring() -> bool:
        return all(sim.flows[fid].remaining_bytes <= 0 for fid in ring_fids)

    completion_time = sim.run_until(done_ring, max_steps=max_steps)

    if not return_metrics:
        return completion_time

    # Build logical edge list and compute per-logical-edge simulated throughput
    P = len(ring)
    ring_edges = [(ring[i], ring[(i + 1) % P]) for i in range(P)]

    # Group flows by logical edge and compute simulated throughput
    per_logical_edge_sim_throughput: Dict[Edge, float] = {}
    for i in range(P):
        src = ring[i]
        dst = ring[(i + 1) % P]
        logical_edge = (src, dst)
        # Sum sent_bytes of all flows on this logical edge
        edge_bytes = sum(
            sim.flows[fid].sent_bytes
            for fid in ring_fids
            if sim.flows[fid].five_tuple.src == src and sim.flows[fid].five_tuple.dst == dst
        )
        per_logical_edge_sim_throughput[logical_edge] = edge_bytes / completion_time if completion_time > 0 else 0.0

    # Static theoretical analysis (only meaningful without congestion/background)
    theory = compute_ring_theoretical_time(
        topo, ring, bytes_per_neighbor, flows_per_neighbor
    )

    return {
        "completion_time_s": completion_time,
        "theoretical_time_s": theory["theoretical_time_s"],
        "bottleneck_bandwidth_Bps": theory["bottleneck_bandwidth_Bps"],
        "per_logical_edge_sim_throughput_Bps": per_logical_edge_sim_throughput,
        "per_logical_edge_theoretical_throughput_Bps": theory["per_logical_edge_throughput"],
        "edge_contention": theory["edge_contention"],
        "ring_edges": ring_edges,
        "ring_size": P,
        "bytes_per_neighbor": bytes_per_neighbor,
        "flows_per_neighbor": flows_per_neighbor,
    }


def run_adaptive_ring_transfer(
    topo: FatTree,
    ring: List[Node],
    bytes_per_neighbor: float,
    adaptive_cfg: AdaptiveConfig,
    dt_s: float = 5e-5,
    congestion: Optional[CongestionModel] = None,
    background_cfg: Optional[BackgroundTrafficConfig] = None,
    max_steps: int = 15_000_000,
) -> Dict:
    """
    Adaptive multi-flow ring transfer.

    Starts with k=1 flow per logical ring edge and dynamically adds flows
    when throughput is below nominal capacity. New flows get different
    5-tuples so ECMP routes them to alternative physical paths.

    Returns a dict with:
        completion_time_s, final_k_per_edge, k_history,
        per_logical_edge_throughput, ring_size, bytes_per_neighbor
    """
    P = len(ring)
    if P < 2:
        raise ValueError("Ring must have at least 2 workers.")

    background = BackgroundTrafficGenerator(topo, background_cfg) if background_cfg is not None else None
    sim = FlowLevelSimulator(topo, dt_s=dt_s, congestion=congestion, background=background)

    cfg = adaptive_cfg
    nominal_cap = topo.capacity_Bps  # per-link nominal capacity (bytes/s)

    # --- Phase A: Initialize with k=1 per logical edge ---
    edge_states: List[LogicalEdgeState] = []
    for i in range(P):
        src = ring[i]
        dst = ring[(i + 1) % P]
        ft = Flow5Tuple(
            src=src, dst=dst,
            sport=cfg.base_sport + i * 100 + 0,
            dport=cfg.dport, proto=cfg.proto,
        )
        fid = sim.add_flow(ft, bytes_per_neighbor)
        es = LogicalEdgeState(
            src=src, dst=dst, edge_index=i,
            total_bytes_target=bytes_per_neighbor,
            flow_ids=[fid], current_k=1,
            window_bytes_start=0.0, window_time_start=0.0,
        )
        edge_states.append(es)

    # Event log for convergence plots
    k_history: List[tuple] = []  # (time_s, edge_index, new_k)

    # --- Phase B: Main simulation loop with adaptive control ---
    # Performance: track completed edges to skip them, check completion
    # periodically (not every tick), cache total_sent per window.
    done_edges: set = set()
    check_interval = 10  # check completion every 10 ticks (500µs)
    safe_max = min(max_steps, int((bytes_per_neighbor / (topo.capacity_Bps * 0.01)) / dt_s))

    tick = 0
    for _ in range(safe_max):
        sim.step()
        tick += 1

        # === Measurement window (only for active edges) ===
        if sim.time_s - edge_states[0].window_time_start >= cfg.measurement_window_s:
            for i, es in enumerate(edge_states):
                if i in done_edges:
                    continue

                # Cache total_sent (expensive — call once per edge per window)
                current_sent = es.total_sent(sim.flows)

                # Mark done if finished
                if current_sent >= es.total_bytes_target - 1.0:
                    done_edges.add(i)
                    continue

                # Throughput measurement over this window
                window_duration = sim.time_s - es.window_time_start
                if window_duration > 0:
                    window_throughput = (current_sent - es.window_bytes_start) / window_duration

                    # Decision: is this edge underperforming?
                    if (window_throughput < nominal_cap * (1.0 - cfg.threshold)
                            and es.current_k < cfg.k_max
                            and tick - es.last_add_tick >= cfg.cooldown_ticks):

                        remaining = es.total_remaining(sim.flows)
                        if remaining > 0:
                            # Count only ACTIVE flows (not completed ones)
                            active_fids = [fid for fid in es.flow_ids
                                           if sim.flows[fid].remaining_bytes > 0]
                            n_active_plus_new = len(active_fids) + 1
                            new_per_flow = remaining / n_active_plus_new

                            # Redistribute remaining bytes across active flows only
                            for fid in active_fids:
                                sim.flows[fid].remaining_bytes = new_per_flow

                            # Create new flow with unique 5-tuple for ECMP diversity
                            new_ft = Flow5Tuple(
                                src=es.src, dst=es.dst,
                                sport=cfg.base_sport + es.edge_index * 100 + es.current_k,
                                dport=cfg.dport, proto=cfg.proto,
                            )
                            new_fid = sim.add_flow(new_ft, new_per_flow)
                            es.flow_ids.append(new_fid)
                            es.current_k += 1
                            es.last_add_tick = tick
                            k_history.append((sim.time_s, es.edge_index, es.current_k))

                # Reset window (use cached current_sent)
                es.window_bytes_start = current_sent
                es.window_time_start = sim.time_s

            # Quick completion check after window processing
            if len(done_edges) == len(edge_states):
                break

        # === Periodic completion check (every check_interval ticks) ===
        elif tick % check_interval == 0:
            for i, es in enumerate(edge_states):
                if i not in done_edges:
                    if es.total_sent(sim.flows) >= es.total_bytes_target - 1.0:
                        done_edges.add(i)
            if len(done_edges) == len(edge_states):
                break

    # --- Phase C: Build return metrics ---
    completion_time = sim.time_s

    per_logical_edge_throughput = {}
    final_k_per_edge = {}
    for es in edge_states:
        edge_key = (es.src, es.dst)
        sent = es.total_sent(sim.flows)
        per_logical_edge_throughput[edge_key] = sent / completion_time if completion_time > 0 else 0.0
        final_k_per_edge[edge_key] = es.current_k

    return {
        "completion_time_s": completion_time,
        "final_k_per_edge": final_k_per_edge,
        "k_history": k_history,
        "per_logical_edge_throughput": per_logical_edge_throughput,
        "ring_size": P,
        "bytes_per_neighbor": bytes_per_neighbor,
    }


def main() -> None:
    topo = FatTree(k=6, link_capacity_Gbps=100.0, seed=1)
    ring = build_worker_ring(topo.hosts, worker_count=30, start_index=0)

    print("=== Baseline: ring neighbor transfer (no congestion) ===")
    t0 = run_simple_ring_transfer(
        topo=topo,
        ring=ring,
        bytes_per_neighbor=256 * 1024 * 1024 , #256* 1024 * 1024
        flows_per_neighbor=10,
    )

    print(f"Completion time: {t0:.6f} s")

    print("\n=== Residual-capacity random congestion (on/off) ===")
    cong = CongestionModel(
        mode="onoff",
        seed=7,
        affected_fraction=0.15,
        congested_util_low=0.40,
        congested_util_high=0.85,
        p_on=0.003,
        p_off=0.012,
    )
    t1 = run_simple_ring_transfer(
        topo=topo,
        ring=ring,
        bytes_per_neighbor= 256 * 1024 * 1024,
        flows_per_neighbor=1,
        congestion=cong,
    )
    print(f"Completion time: {t1:.6f} s")

    print("\n=== Background cross-traffic (Poisson + lognormal sizes) ===")
    bg_cfg = BackgroundTrafficConfig(
        seed=42,
        arrival_rate_fps=800.0,
        size_dist="lognormal",
        mean_bytes=100 * 1024 * 1024,
        sigma_logn=1.2,
        locality="mixed",
        p_local=0.6,
    )

    t2 = run_simple_ring_transfer(
        topo=topo,
        ring=ring,
        bytes_per_neighbor=256 * 1024 * 1024,
        flows_per_neighbor=1,
        background_cfg=bg_cfg,
    )
    print(f"Completion time: {t2:.6f} s")

    print("\n=== Ring all-reduce (pipelined) under cross-traffic ===")
    ar = run_ring_allreduce(
        topo=topo,
        ring=ring,
        total_bytes_M=1 * 1024 * 1024 * 1024,   # 1 GiB payload per worker
        flows_per_neighbor=10,                   # multi-flow to induce ECMP spreading
        pipelined=False,                         # activates pipelined execution of ring steps. Instead of waiting for each step to finish before starting the next one, the simulator allows multiple steps to overlap in time. This models the behavior of real collective implementations such as NCCL or MPI, where chunks are streamed continuously through the ring.
        pipeline_window=4,                       #The parameter pipeline_window=4 determines how many steps may be active simultaneously. In this case, up to four ring steps can inject traffic concurrently. A larger window increases concurrency and typically improves throughput, but it also increases link contention because more flows are active at the same time.
        alpha_s=0.0,
        background_cfg=bg_cfg,
    )
    print(f"All-reduce total time: {ar.total_time_s:.6f} s; mean step: {sum(ar.step_times_s)/len(ar.step_times_s):.6f} s")


if __name__ == "__main__":
    main()