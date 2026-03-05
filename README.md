# Fat-Tree Flow-Level Simulator (ECMP + Ring Collectives)

## Overview

This repository implements a **flow-level network simulator in Python** designed to evaluate collective communication patterns over **data center fat-tree topologies**. The simulator models flows at the network level, including **ECMP routing**, **link contention**, **background traffic**, and **collective communication patterns such as ring neighbor exchange and ring all-reduce**.

The simulator uses a **discrete-time fluid model**. Each simulation step updates the bandwidth allocation across links, computes per-flow bottlenecks, and advances the amount of transmitted data. This approach allows scalable experimentation with network behavior without simulating individual packets.

The simulator is intended for experimentation with **distributed training workloads**, **data center communication patterns**, and **network congestion effects**.

---

# Architecture of the Simulator

The code is organized into several main components. Each component represents a logical abstraction of a data center network or communication workload.

---

# 1. Fat-Tree Network Topology

The `FatTree` class constructs a **3-tier k-ary fat-tree topology**, a common architecture used in data centers.

The topology contains four types of nodes:

* **Hosts**
* **Edge (ToR) switches**
* **Aggregation switches**
* **Core switches**

The parameter `k` determines the size of the topology.

```
Pods = k
Edge switches per pod = k/2
Aggregation switches per pod = k/2
Hosts per edge switch = k/2
Core switches = (k/2)^2
```

Example:

```python
topo = FatTree(k=6, link_capacity_Gbps=100.0)
```

Increasing `k` has the following effects:

| Parameter  | Effect                             |
| ---------- | ---------------------------------- |
| Larger `k` | More hosts and switches            |
| Larger `k` | More ECMP paths                    |
| Larger `k` | Higher network bisection bandwidth |
| Larger `k` | Increased simulation complexity    |

The link capacity can also be modified:

```python
link_capacity_Gbps=100
```

This parameter directly controls **per-link bandwidth** and therefore impacts flow completion times.

---

# 2. ECMP Routing

Flows are routed using **Equal Cost Multi Path (ECMP)** routing.

The function:

```
ecmp_pick_path()
```

selects one path among multiple equal-cost routes using a deterministic hash of the **5-tuple**:

```
(src, dst, sport, dport, protocol)
```

Changing the number of flows between workers affects ECMP load balancing.

Example:

```
flows_per_neighbor = 1
```

vs

```
flows_per_neighbor = 10
```

More flows increase the probability that traffic spreads across multiple paths.

---

# 3. Flow-Level Simulation Model

The simulator uses a **discrete-time fluid model** implemented in the `FlowLevelSimulator` class.

Each simulation step performs the following operations:

1. Background traffic generation
2. Congestion updates
3. Link flow aggregation
4. Fair bandwidth allocation
5. Data transmission update

Bandwidth sharing is modeled as **max-min fairness per link**:

```
link_share = link_capacity / number_of_flows
```

The flow rate becomes the **minimum share along its path**.

---

# 4. Simulation Time Step

The simulation advances using a fixed time step `dt_s`.

Example:

```python
dt_s = 5e-5
```

This corresponds to:

```
50 microseconds
```

Impact of changing `dt_s`:

| dt value   | Impact                          |
| ---------- | ------------------------------- |
| Smaller dt | Higher accuracy                 |
| Smaller dt | Slower simulation               |
| Larger dt  | Faster simulation               |
| Larger dt  | Less precise bandwidth dynamics |

Typical useful values:

```
1e-4  (100 µs)
1e-3  (1 ms)
```

---

# 5. Worker Ring Construction

The simulator models **ring-based communication**, common in distributed machine learning.

Workers are arranged in a logical ring:

```python
ring = build_worker_ring(topo.hosts, worker_count=30)
```

Each worker sends data to the next worker in the ring.

Increasing `worker_count` has several effects:

| Parameter    | Impact                        |
| ------------ | ----------------------------- |
| More workers | More flows                    |
| More workers | More network contention       |
| More workers | More steps in ring all-reduce |

---

# 6. Ring Neighbor Communication

The simplest workload implemented is a **neighbor transfer**.

Each worker sends a fixed amount of data to its next neighbor:

```python
bytes_per_neighbor = 256 * 1024 * 1024
```

Impact of this parameter:

| Value        | Effect                     |
| ------------ | -------------------------- |
| Larger value | Longer completion time     |
| Larger value | Higher network utilization |

Parallel flows can be used to increase ECMP spreading:

```python
flows_per_neighbor = 10
```

---

# 7. Ring All-Reduce

The simulator includes a model of the **ring all-reduce algorithm**.

The algorithm consists of two phases:

1. **Reduce-scatter**
2. **All-gather**

Total number of steps:

```
2 * (P - 1)
```

where `P` is the number of workers.

Example configuration:

```python
run_ring_allreduce(
    total_bytes_M=1 * 1024 * 1024 * 1024,
    flows_per_neighbor=10,
    pipelined=True,
    pipeline_window=4
)
```

Key parameters:

### total_bytes_M

Total tensor size per worker.

Increasing this value increases communication volume.

---

### flows_per_neighbor

Number of parallel flows per neighbor communication.

Effects:

* increases ECMP spreading
* increases link contention

---

### pipelined

If enabled, multiple steps of the ring execute simultaneously.

```
pipelined=True
```

This mimics implementations used in **NCCL and MPI**.

---

### pipeline_window

Controls how many steps can run concurrently.

```
pipeline_window = 4
```

Impact:

| Value  | Effect                    |
| ------ | ------------------------- |
| Larger | Higher concurrency        |
| Larger | Higher network contention |

---

# 8. Random Congestion Model

The `CongestionModel` introduces stochastic link utilization.

Two modes are supported:

```
mode="iid"
mode="onoff"
```

The on/off model simulates bursty congestion.

Key parameters:

```
affected_fraction
congested_util_low
congested_util_high
p_on
p_off
```

Example:

```
affected_fraction = 0.15
```

This means 15% of links may experience congestion.

---

# 9. Background Traffic Generator

The simulator can generate **cross-traffic flows**.

Configuration example:

```python
bg_cfg = BackgroundTrafficConfig(
    arrival_rate_fps=800,
    size_dist="lognormal",
    mean_bytes=100 * 1024 * 1024,
    locality="mixed"
)
```

Important parameters:

### arrival_rate_fps

Flow arrival rate per second.

Higher values increase background load.

---

### size_dist

Flow size distribution:

```
fixed
lognormal
pareto
```

Heavy-tailed distributions simulate real data center traffic.

---

### locality

Traffic locality pattern.

Options:

```
uniform
same_edge
same_pod
mixed
```

Locality significantly affects which network tiers become congested.

---

# 10. Running the Simulator

Run the main experiment:

```
python simulator.py
```

The script runs four scenarios:

1. Baseline ring communication
2. Random link congestion
3. Background cross-traffic
4. Ring all-reduce under cross-traffic

The output reports **flow completion times** and **average step latency**.

---

