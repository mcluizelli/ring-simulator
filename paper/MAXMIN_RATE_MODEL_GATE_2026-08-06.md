# Rate-model gate and JY/IH directed-fabric closeout

**Date:** 2026-08-06
**Status:** investigation complete; Unit 2A terminology correction applied locally;
no production allocator or frozen result changed
**Decision recommended:** **hybrid** — name the existing artifact truthfully now,
then add network-wide unweighted max-min as a versioned allocator and revalidate
before the paper's final quantitative claims are frozen.

## 1. Scope and immutability

This gate answered two separate questions:

1. Close the paired `JY#1`/`IH#1` question about directed versus undirected
   fabric notation, including a downstream `e`/`c_e` sweep.
2. Determine whether the production allocator is correctly described as
   max-min, whether its rate is a lower bound on network-wide unweighted
   max-min, and whether the existing numerical conclusions can therefore be
   retained without reruns.

The investigation obeyed the freeze boundary:

- `sim.py` was not edited. Its SHA-256 after the gate is
  `815d499af4bc3ba5387428dcda6e618f537c758a9a0ceea2d2c605831cf9e60e`.
- No frozen CSV was written. The four input CSV modification times all predate
  this gate.
- At the time this gate was run, no occurrence of `max-min` or `max--min` in the paper
  had been changed. The later approved Unit 2A terminology patch changes wording only.
- New simulation output exists only under
  [`investigations/maxmin_gate_2026_08_06/`](../investigations/maxmin_gate_2026_08_06/).
- Everything described here remains uncommitted.

The sidecar oracle and its full machine-readable results are:

- [`maxmin_gate_2026_08_06.py`](../investigations/maxmin_gate_2026_08_06.py)
- [`summary.json`](../investigations/maxmin_gate_2026_08_06/summary.json)
- [`snapshot_rates.csv`](../investigations/maxmin_gate_2026_08_06/snapshot_rates.csv)
- [`paired_completion.csv`](../investigations/maxmin_gate_2026_08_06/paired_completion.csv)

## 2. `JY#1` + `IH#1`: directed fabric

### 2.1 Change made

The physical and logical graphs are now unambiguous in
[`paper_infocom.tex`](../../paper-overleaf/paper_infocom.tex):

- physical fabric: directed `G=(V,\mathcal{L})`;
- full-duplex physical connection: two directed arcs `\ell`, with a separate
  capacity `c_\ell` in each direction;
- collective: a directed logical ring;
- logical ring edge: `e`.

The paired `\JY{maybe undirect?}` and its `\IH{...}` reply were removed only
after that clarification was in the body. The retirement record was appended to
[`JOSE_REVIEW_2026-07-21.md`](JOSE_REVIEW_2026-07-21.md); it explicitly says
that this representation audit does not certify the separate max-min label.

### 2.2 Exact comment and digit guards

- `\JY`: 7 -> 6; exactly the intended block removed; all six survivors are
  byte-identical.
- `\IH`: 3 -> 2; exactly the paired reply removed; both survivors are
  byte-identical.
- `\jose`: 1 -> 1, byte-identical.
- Paper digit diff: no digit sequence was added. The only removed sequences
  were `10`, `4`, `25`, `12`, and `13`, all inside the removed literature note.
- Documentation was rebuilt without blind renumbering and now reports 6/2/1.

### 2.3 Full downstream notation sweep

Mechanical gate:

| Pattern | Current count | Meaning |
|---|---:|---|
| `G=(V,E)` | 0 | old overloaded graph notation gone |
| `c_e` | 0 | no physical capacity uses logical `e` |
| `G=(V,\mathcal L)` | 1 | physical graph definition |
| `c_\ell` | 1 | physical directed-arc capacity definition |

A standalone-token scan found 54 textual `e` tokens on 28 lines. One is the
package name `algorithm2e`; all other 53 are logical ring-edge uses. Every
downstream occurrence of `e`, `k_e`, `(k_e)_e`, `f_{e,j}`, `b_e`, and `\tau_e`
was inspected in context. No physical-edge use remains.

### 2.4 Build and rendered verification

`python build_paper_local.py --both` completed cleanly:

| Build | Errors / undefined / multiply-defined / overfull | Pages | Bytes |
|---|---|---:|---:|
| Review | 0 / 0 / 0 / 0 | 7 | 563,141 |
| Submission | 0 / 0 / 0 / 0 | 7 | 539,904 |

The clean warning counts were observed in the build output but that console log
was not persisted; the generated PDF page counts and byte sizes remain directly
verifiable.

Pages 2--3 of both PDFs were rendered and visually inspected. The new paragraph
is clean and the remaining review comments render as expected.

## 3. What the production allocator actually computes

For the active fixed-path flow set `F`, let `n_\ell` be the number of active
flows whose path contains directed arc `\ell`, and let `C_\ell` be its current
residual capacity. The production step computes

\[
r_i^{\mathrm{local}}
=\min_{\ell\in p_i}\frac{C_\ell}{n_\ell}.
\]

It first assigns every flow the equal local share at each traversed link, then
takes the minimum share along the path. It does **not** return unused capacity
from a flow bottlenecked elsewhere to the other users of an upstream link.

This is feasible, but it is not generally network-wide max-min. A two-flow
counterexample is enough:

- both flows share a 100-unit first link;
- flow 1 then traverses a private 20-unit link;
- flow 2 then traverses a private 100-unit link.

The production rule gives `(20, 50)`. Progressive max-min gives `(20, 80)` by
reclaiming the 30 units stranded on the first link. The distinction is the
standard one between link-local fair shares and global fairness: local fair
queueing alone can strand capacity when a flow is bottlenecked downstream
([Das et al., *Low-State Fairness*](https://www.cise.ufl.edu/~helmy/papers/Fairness-Infocom05-published.pdf)).

The precise, non-overclaiming name for the existing model is therefore:

> **link-local equal-share bottleneck model**

or, where space is tight:

> **local equal-share fluid model**

These are descriptive labels, not claimed as a canonical named algorithm; the
literature precedent supports the local-versus-global distinction.

It should not be called max-min, approximate max-min, or fair sharing without
the `link-local` qualifier.

## 4. The lower-bound theorem

### 4.1 Statement

For nonempty fixed paths, finite nonnegative capacities, unweighted active
backlogged flows, unit resource coefficients, and no per-flow peak caps,

\[
r_i^{\mathrm{local}}
=\min_{\ell\in p_i}\frac{C_\ell}{n_\ell}
\le r_i^{\mathrm{MM}}
\quad\text{for every flow }i.
\]

Thus the proposed lower bound is **true under those assumptions**.

### 4.2 Proof

Run unweighted progressive filling. Suppose flow `i` freezes at water level
`t=r_i^{MM}` because link `\ell\in p_i` saturates. Every flow on `\ell` that
froze earlier has rate at most `t`, and every still-unfrozen flow using `\ell`
is at `t`. Hence

\[
C_\ell
=\sum_{j\text{ earlier on }\ell}r_j
 + |F_\ell^{\mathrm{active}}|t
\le n_\ell t.
\]

Therefore `t >= C_\ell/n_\ell`, and

\[
r_i^{MM}=t
\ge \frac{C_\ell}{n_\ell}
\ge \min_{q\in p_i}\frac{C_q}{n_q}
=r_i^{\mathrm{local}}.
\]

Feasibility by itself would not prove componentwise dominance; the progressive
filling argument is essential.

### 4.3 Limits of the theorem

The unweighted formula is not a lower bound for weighted max-min. With strictly
positive weights, the corresponding lower bound is

\[
w_i\min_{\ell\in p_i}
\frac{C_\ell}{\sum_{j:\ell\in p_j}w_j}.
\]

The unweighted theorem also requires correct active-flow counts, fixed paths,
no demand/peak caps below the proposed share, and immediate recomputation when
flows or capacities change.

### 4.4 Does the theorem make all existing times conservative?

No. It proves more than nothing, but less than the paper currently needs.

| Case | Conservativeness follows? | Reason |
|---|---|---|
| Static equal split; fixed sub-flow bytes and paths | **Yes** | Every sub-flow receives at least its local-model rate under network-wide max-min. |
| Exogenous capacity process, recomputed every tick | **Yes**, for fixed bytes and the same capacity trace/tick boundaries | The instantaneous bound can be coupled over departures. |
| Exogenous background arrivals with fixed traces | **Yes**, for fixed bytes | Requires identical arrival times, sizes, paths, capacities, and recomputation boundaries, with no allocator feedback into those inputs. |
| Proportional redistribution | **Not in general** | The two allocators assign different remaining bytes using measured rates; stale measurements can reverse the ordering. |
| Adaptive controller | **No general bound** | Rate thresholds create different flow sets and paths. |
| Pipelined All-Reduce | **No general proof** | New flow injection depends on earlier completion events. |
| Speedup ratios | **No** | Both numerator and denominator change; two conservative absolute times do not order their ratio. |

Consequently, the theorem supports retaining the frozen data as a named
conservative baseline for static fixed-byte runs. It does not validate the
existing proportional, controller, gap-closure, or speedup numbers as
network-wide max-min results.

For the two dynamic rows marked “Yes,” use induction at common tick boundaries.
Let $R_i$ denote remaining bytes. Initially
$R_i^{MM}=R_i^{local}$ and $S_{MM}=S_{local}$. As the induction invariant,
$R_i^{MM}\le R_i^{local}$ for every arrived flow, hence
$S_{MM}\subseteq S_{local}$. For a surviving flow,

\[
r_i^{MM}(S_{MM})
\ge r_i^{local}(S_{MM})
\ge r_i^{local}(S_{local}),
\]

because removing competitors can only increase the local formula. With the same
tick duration and exogenous capacity, this rate inequality preserves the
remaining-byte invariant through the tick; identical exogenous arrivals enter
both systems with equal bytes and paths. Completions then preserve the active-set
inclusion. This proves absolute completion-time and makespan conservativeness
under the stated exogenous-input conditions. It does not rely on max-min itself
being monotone under flow removal (that property is false in general), and it
does not order speedup ratios.

## 5. Independent sidecar max-min oracle

The sidecar implements exact unweighted progressive filling without editing
`sim.py`. During a test run it temporarily substitutes the simulator class in
memory, invokes the canonical run functions, and restores the original class.
Each allocation is checked for capacity feasibility and a max-min bottleneck
certificate.

Guards passed:

- analytical counterexample: local `(20, 50)`, max-min `(20, 80)`;
- 1,000 random fixed-path networks, 6,419 flow instances, zero lower-bound
  violations;
- exact frozen reproduction, to the last stored float, for representative
  `N0 equal`, `O0 proportional`, and `C10 baseline` rows;
- zero writes to frozen inputs, verified from the sidecar's read-only open paths
  and post-run file modification times (the JSON flag is descriptive, not an
  independent write detector);
- deterministic topology, placement, seed, and canonical flow-construction
  inputs were held fixed for the direct paired calls. Recorded placement,
  nominal-capacity, and route digests are diagnostics, not a complete pairing
  proof for adaptive flow creation or pipelined All-Reduce; dynamic capacity
  traces are controlled by identical exogenous seeds rather than represented by
  the nominal-capacity digest.

### 5.1 Frozen-data audit: realised time versus the static reference

Before changing Corollary 1 or either paper caption that calls
`compute_ring_theoretical_time` an optimal-split bound, every frozen CSV carrying
a directly comparable realised and reference time was scanned. The scan was
strict (`realised < reference`), with a second count at more than 1% below the
reference; rows were joined only on the full paired key
`(fabric, P, seed, k)`. No CSV was edited and no simulation was run. The complete
63-file frozen-input hash snapshot is
[`frozen_csv_sha256.txt`](../investigations/rate_model_revalidation_2026_08_06/frozen_csv_sha256.txt).
The deterministic read-only scan is reproduced by
[`audit_frozen_reference.py`](../investigations/rate_model_revalidation_2026_08_06/audit_frozen_reference.py);
it imports no simulator code and writes no file.

The fixed/equal-split side is clean. There are zero strict violations in all
56,000 paper-producing rows of `v9.0`, `v10.0`, and `v10.1`, and zero in the
additional 100 directly comparable validation rows from `v1.0` and `v3.0`.
In particular, the dashed `v10.1` saturation curves are not crossed by their
equal-split curves in the frozen data.

The proportional side does cross the reference:

| Frozen proportional set | Paired rows | `t_prop < opt_time` | More than 1% below |
|---|---:|---:|---:|
| `v11.0` joined to `v10.0` | 3,200 | 951 | 736 |
| `v11.1` joined to `v10.1` | 32,000 | 9,440 | 7,335 |

`v12.0` contains the same 951 crossings plus its added `k=32` rows, and
`v12.1` reproduces the `3tier_os4/P=64` subset; they are overlapping frozen
artifacts, not independent extra evidence. In `v11.1`, 27 of 32 aggregate cells
contain at least one strict crossing, and 13 of 32 have a negative mean
`mean_gap_prop_pct`. The two `k=8` cells directly visible in the gap-closure
figure are `3tier_os4/P=64` (-2.6456%) and `2tier/P=64` (-0.9692%). The largest
crossing is `3tier_os4/P=64`, seed 634, `k=4`:
`t_prop=0.01275 s` versus `opt_time=0.019822925981538463 s`, 35.68% below the
reference. The source rows are `v11.1/results.csv:30539` and
`v10.1/results.csv:45808`.

This makes the terminology correction **substantive, not prophylactic**.
`compute_ring_theoretical_time` is a static full-concurrency reference under the
legacy link-local model: it freezes the initially active flow set and sums those
initial per-path rates. The dynamic proportional runner recomputes rates and
redistributes remaining bytes as flows and logical edges finish. The observed
crossings are therefore incompatible with the current universal sentence “no
split does better” and with treating the static value as a global ceiling. They
are consistent with capacity being released after departures, but this audit
does not by itself assign a unique causal decomposition. The safe current name
is **static full-concurrency local-model proportional-split reference over the
same hashed paths**. For the equal-split saturation caption the qualifier is prophylactic
with respect to the plotted crossings, but still required for model accuracy;
for Corollary 1 and the gap-closure caption it corrects an empirically false
scope claim.

## 6. Snapshot gate: where the allocators diverge

The snapshot matrix used 360 allocations and 124,800 flow instances across
`P in {16,64}`, `k in {2,8,16}`, ten placements, three fabric capacities, and
clean versus persistent-hot-spot conditions. There were zero lower-bound
violations. The strict-flow column below is the unweighted mean of the 60
per-snapshot fractions in each fabric/condition group; it is not a pooled
flow-instance percentage.

| Fabric | Condition | Mean per-snapshot strict-flow fraction | Mean aggregate-rate ratio `MM/local` | Largest per-flow ratio |
|---|---|---:|---:|---:|
| Non-blocking | clean | 0.37% | 1.0010 | 1.33x |
| Non-blocking | hot spot | 44.18% | 1.1460 | 5.17x |
| 2:1 oversubscribed | clean | 0.78% | 1.0007 | 1.50x |
| 2:1 oversubscribed | hot spot | 40.44% | 1.1520 | 6.38x |
| 4:1 oversubscribed | clean | 11.55% | 1.0157 | 2.00x |
| 4:1 oversubscribed | hot spot | 31.74% | 1.1964 | 4.67x |

This is why a clean non-blocking-only gate would have been nearly blind. The
requested congestion and oversubscription cells expose substantial stranded
capacity.

## 7. Paired completion-time gate

The dynamic gate contains 63 paired rows. Negative percentages mean that exact
progressive-filling max-min completed sooner than the frozen/local model. These
are diagnostic sentinels (`n=3`), not replacements for the production `n=1000`
campaigns.

| Cell | Arm | Mean time change | Most changed seed |
|---|---|---:|---:|
| `N0`, non-blocking clean | equal `k=1,8` | 0.00% | 0.00% |
| `N0`, non-blocking clean | proportional `k=8` | -6.06% | -18.18% |
| `O0`, 4:1 clean | equal `k=1,8,32` | 0.00% | 0.00% |
| `O0`, 4:1 clean | proportional `k=8` | -9.13% | -13.51% |
| `O0`, 4:1 clean | proportional `k=16` | -9.34% | -14.29% |
| `C10`, on/off 10% | baseline `k=1` | 0.00% | 0.00% |
| `C10`, on/off 10% | static `k=4` | -0.53% | -1.07% |
| `C10`, on/off 10% | adaptive | -3.87% | -5.17% |
| `C50`, on/off 50% | baseline `k=1` | -2.58% | -5.54% |
| `C50`, on/off 50% | static `k=4` | -7.10% | -11.27% |
| `C50`, on/off 50% | adaptive | -4.78% | -10.34% |
| `B1000`, background | `k=1,4`, 0/1000 flows/s | 0.00% | 0.00% |
| `XOH`, 4:1 + hot spot | equal `k=8` | -1.93% | -3.10% |
| `XOH`, 4:1 + hot spot | proportional `k=8` | -17.87% | -31.08% |

The background cases did exercise strict allocator differences, but the ring
makespan stayed equal at 50-microsecond tick resolution in these sentinels. That
is a null result for these rows, not proof of allocator equivalence.

### 7.1 Ratios and policy decisions also change

Selected mean changes in the reported speedup (`T_k=1 / T_arm`) were:

| Cell / arm | Mean speedup change | Range over three seeds |
|---|---:|---:|
| `N0` proportional `k=8` | +7.41% | 0 to +22.22% |
| `O0` proportional `k=8` | +10.18% | +6.99% to +15.63% |
| `O0` proportional `k=16` | +10.49% | +5.56% to +16.67% |
| `C10` adaptive | +4.04% | +2.45% to +5.45% |
| `C50` adaptive | +2.59% | **-4.58%** to +11.53% |
| `XOH` proportional `k=8` | +24.01% | +4.15% to +45.10% |

The `C50` adaptive sign reversal in one seed directly demonstrates why the
lower-bound theorem cannot be promoted into a speedup-ratio guarantee.

The adaptive controller also selected a different final flow set in all six
sentinel placements; network-wide max-min reduced mean final `k` by 0.047 to
0.156 flows per logical edge. Thus this is not merely a constant time rescaling.

## 8. What comparable simulators model and what they call it

### 8.1 ASTRA-Sim

ASTRA-Sim has no dependency role in the current evidence chain: it is not
imported by our simulator, produced none of the frozen CSVs or figures, and is
not currently cited in `paper_infocom.tex`. Its present role is methodological
comparison and terminology discipline. The internal related-work study also
lists an ASTRA-Sim cross-check as a possible future validation experiment; that
experiment has not been run and is not evidence behind the current paper.

ASTRA-Sim is backend-pluggable, so it has no single end-to-end rate model. The
public build exposes separate congestion-unaware and congestion-aware analytical
executables
([ASTRA-Sim CMake source](https://github.com/astra-sim/astra-sim/blob/518bd513ae110428cd62eb60efc0f3993fd53c70/astra-sim/network_frontend/analytical/CMakeLists.txt#L24-L74)).

- The congestion-unaware analytical backend computes an alpha-beta-style delay,
  `hops * latency + size / bandwidth`, with no active-flow allocator
  ([source](https://github.com/astra-sim/astra-network-analytical/blob/e8c5119f8d5a690b955e25c37a74359f23ac64cc/congestion_unaware/basic-topology/BasicTopology.cpp#L48-L60)).
  ASTRA-Sim 2.0 says it estimates delay analytically instead of simulating
  packet-level behavior and identifies non-trivial congestion and link
  oversubscription as limitations
  ([paper, p. 6, Section IV-C and footnote 5](https://arxiv.org/pdf/2303.14006)).
- The congestion-aware analytical backend is an in-order per-link chunk queue:
  a busy directed link appends the chunk, later dequeues the queue front,
  occupies the link for `size/B`, and schedules arrival after
  `latency + size/B`
  ([Link.cpp](https://github.com/astra-sim/astra-network-analytical/blob/e8c5119f8d5a690b955e25c37a74359f23ac64cc/congestion_aware/network/Link.cpp#L52-L134)).
  That is a FIFO single-server model, not simultaneous max-min sharing.
- ASTRA-Sim 3.0 renames the earlier Analytical model **Simple**, identifies it
  as alpha-beta based, and distinguishes scale-out `Simple` from the newer
  `Simple-NoC`. Its Clos case study uses the **ns-3 packet-level backend**
  ([ASTRA-Sim 3.0, pp. 2 and 10](https://arxiv.org/pdf/2606.10440)). Official
  ASTRA material describes that ns-3 backend as packet-level and event-based,
  with RDMA, congestion control, and ECMP; therefore rates emerge from queue and
  protocol dynamics rather than a global closed-form allocator
  ([MICRO 2024 tutorial, slide 2](https://astra-sim.github.io/assets/tutorials/micro-2024/7_demo_suppl_ns3.pdf)).
  The pinned FIFO finding above applies to the reviewed public 2.0 analytical
  source and is not automatically a claim about every `Simple-NoC` mechanism
  described in the 3.0 paper.
- Garnet is a cycle-accurate, flit-granular router model with virtual-channel
  and credit flow control. Ordered virtual networks use queueing arbiters while
  other switch arbiters are round-robin; both are local flit-arbitration rules,
  not network-wide max-min allocation
  ([gem5 Garnet documentation](https://www.gem5.org/documentation/general_docs/ruby/garnet-2/)).

Therefore the reviewed public ASTRA-Sim backends do not provide precedent for
calling the production formula max-min. They provide precedent for naming the
abstraction explicitly and qualifying its scope.

### 8.2 Direct max-min precedent

SimGrid is the clean direct precedent. Its Linear Max-Min (LMM) engine recomputes
instantaneous action rates under shared capacity constraints, and its **Raw
network model** explicitly names the policy “max-min sharing.” Its default TCP
model also uses LMM but adds RTT-dependent priorities, so it is not pure
unweighted equal sharing
([LMM models](https://simgrid.org/doc/latest/Models.html#lmm-based-models),
[Raw model](https://simgrid.org/doc/latest/Models.html#raw-network-model), and
[TCP models](https://simgrid.org/doc/latest/Models.html#the-tcp-models)). SimGrid
itself presents Raw as a simplified abstraction rather than a faithful TCP or
UDP model.

This supports two conclusions:

1. Network-wide max-min is a standard and defensible flow-level abstraction,
   but not a novelty claim by itself and not physical ground truth.
2. Under Section 4's assumptions, the current local formula is a
   capacity-stranding, componentwise-lower-bound approximation to network-wide
   unweighted max-min, not max-min itself.

## 9. Decision analysis

### Option A — rename with precedent and lower bound only

Scientifically defensible only if the paper explicitly scopes every result to
the local model. The safest concise conservativeness claim is limited to static
fixed-byte absolute times; the paper could cover the dynamic exogenous cases
only with all coupling conditions in Section 4.4 stated explicitly. It preserves
the frozen data, but cannot retain the implication that proportional, adaptive,
or speedup results are max-min results. The gate's up-to-45.10% speedup-ratio
change is too large to dismiss as nomenclature alone.

**Verdict:** acceptable as an honest interim artifact or a deliberately scoped
stress model; not the strongest final paper.

### Option B — replace the allocator and revalidate now

This aligns implementation and terminology and is mandatory if the final paper
wants to continue saying max-min. The allocator change must be versioned, every
campaign and derived artifact that depends on rate allocation or completion
time rerun, affected figures rebuilt, and every affected numerical claim
re-derived. Pure topology, placement, and path-only artifacts need not be rerun.
Frozen local-model artifacts must remain immutable.

**Verdict:** strongest implementation--paper alignment, but it loses the useful
provenance distinction unless the old model is also named and retained.

### Option C — hybrid: rename now, correct in the next version

Name the existing code and frozen outputs as the **link-local equal-share
bottleneck model**, record the theorem and its limits, then add a selectable
network-wide unweighted max-min allocator in a new simulator/result version.
Run full revalidation before the final paper freezes or submits. Retain the old
fixed-byte absolute-time results covered by Section 4.4 as a conservative
baseline; retain proportional, adaptive, and speedup results only as
sensitivity/provenance baselines rather than overwriting them.

**Verdict: recommended.** It gives immediate truthfulness, preserves a complete
audit trail, and still requires the final quantitative paper to be revalidated
with the allocator consistent with its stated max-min model. “Next version”
here means the next version of this research artifact **before submission**,
not deferred post-publication.

## 10. Recommended implementation order (requires approval)

1. Make a small terminology-only paper patch for the current artifact:
   `max-min fair sharing` -> `link-local equal-share bottleneck model`, plus the
   fixed-path lower-bound statement and its exact scope. Do not change numbers.
2. Add an allocator mode in a new code version; keep the legacy mode for exact
   reproduction and add network-wide unweighted progressive max-min with
   feasibility/certificate tests.
3. Freeze the gate oracle as the reference test and add the two-flow `(20,80)`
   counterexample to automated tests.
4. Rerun every paper-producing driver whose outputs depend on rate allocation
   or completion time into new result directories; do not overwrite any current
   CSV. Reuse path-only/topology-only artifacts only after a dependency audit.
5. Rebuild all figures and re-audit every number, with special attention to
   proportional split, adaptive control, gap closure, and all speedup ratios.
6. Promote the network-wide max-min results to the final paper if that remains
   the stated model. Keep the legacy lower-bound comparison as a robustness
   result if it remains concise and informative.

Until those steps are approved and completed, the current paper should not be
submitted with the phrase `max-min fair sharing` attached to these frozen data.
