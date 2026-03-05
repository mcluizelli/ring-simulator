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

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self._affected: Optional[set[Edge]] = None
        self._state: Dict[Edge, bool] = {}
        self._util: Dict[Edge, float] = {}

    def attach(self, all_edges: List[Edge]) -> None:
        m = max(1, int(self.affected_fraction * len(all_edges)))
        self._affected = set(self.rng.sample(all_edges, m))
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

        self.congestion = congestion
        if self.congestion is not None:
            self.congestion.attach(list(self.topo.edge_of.keys()))

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

def run_simple_ring_transfer(
    topo: FatTree,
    ring: List[Node],
    bytes_per_neighbor: float,
    flows_per_neighbor: int,
    dt_s: float = 5e-5, 
    congestion: Optional[CongestionModel] = None,
    background_cfg: Optional[BackgroundTrafficConfig] = None,
    max_steps: int = 12_000_000,
) -> float:
    
    background = BackgroundTrafficGenerator(topo, background_cfg) if background_cfg is not None else None
    
    sim = FlowLevelSimulator(topo, dt_s=dt_s, congestion=congestion, background=background)

    ring_fids = add_ring_neighbor_flows(sim, ring, bytes_per_neighbor, flows_per_neighbor=flows_per_neighbor)

    def done_ring() -> bool:
        return all(sim.flows[fid].remaining_bytes <= 0 for fid in ring_fids)

    return sim.run_until(done_ring, max_steps=max_steps)


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