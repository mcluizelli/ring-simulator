# Jose's review of `paper_infocom.tex` — captured 2026-07-21

Source: the live Overleaf project `6a4a6681fe9a24b42dafd90f`, read directly from the
editor buffer on 2026-07-21. The file grew **19,785 → 31,433 chars (304 → 432 lines)**.

Jose uses **two different mechanisms** — do not confuse them:

| Macro | Meaning | Count | Chars |
|---|---|---|---|
| `\JY{...}` | a **question / task** addressed to Ibrahem (renders blue, inline) | **17** | ~2.3k |
| `\jose{...}` | **proposed replacement/expansion prose** he drafted (renders blue) | **9** | **8,165** |

Nothing of ours was deleted. Our 2026-07-21 edits (+11.7% flagship, targeted-congestion
scoping, the four removed "ongoing" hedges) are all intact.

---

## A. Structural changes Jose made

| # | Change | Where | Note |
|---|---|---|---|
| A1 | **Anonymous mode turned ON** (`\anontrue`) | L44 | Title page now renders **"Anonymous Submission — Paper #1571"**. A submission number exists, so the abstract registration evidently happened. |
| A2 | **Reviewer-comment system added** | L24–36 | `\mycomm[3]`, `\comm[2]`, `\Fmycomm[3]` + no-op variants (L28–30) to switch all comments off; identities `\JY`=JOSE/blue, `\jose`=blue prose, `\IH`=Ibrahem/green, `\MC`=Marcelo/red. |
| A3 | **Notation macros** | L14–15 | `\eqdef` = `\triangleq`, `\Bstar` = `B^{*}`. |
| A4 | **§IV "The Theory of Multi-Path Rings" heading commented out** | L219 | Only the *heading* (1 of 26 lines); the content stays and now folds into §III System Model. A merge, not a deletion. |
| A5 | **Old heading "Multiple queue-pairs in practice" commented out** | L146 area | Replaced by his proposed prose block. |

## B. The 9 `\jose{}` proposed-prose blocks (8,165 chars)

These are **drafts he wrote for us to adopt/merge** — they are not yet part of the paper's
running text (they render as blue inline comments).

| # | Line | Chars | Where | Opening words |
|---|---|---|---|---|
| B1 | 77 | 1,587 | **inside the abstract** (58–81) | "As AI model sizes scale exponentially, the speed of distributed neural n…" |
| B2 | 95 | 1,065 | Introduction | "The explosive growth of large language models and foundation AI has shif…" |
| B3 | 109 | 1,082 | Introduction | "Modern data-center fabrics employ multi-path topologies such as Fat-Tree…" |
| B4 | 129 | 670 | Introduction (contributions) | "In this paper, we propose opening $k$ parallel RDMA flows per ring link,…" |
| B5 | 138 | 819 | Background | "A standard Fat-Tree data center topology built with radix-$r$ switches p…" |
| B6 | 146 | 1,906 | Background | "While there are several algorithms available for implementing the all-re…" |
| B7 | 153 | 985 | Background | "High-performance data center stacks and RDMA architectures expose mechan…" |
| B8 | 183 | 36 | System Model | "all-reduce collective implementation" |
| B9 | 263 | 15 | Design | "split the flows" |

**Consequence:** his prose cites keys that have **no `\bibitem`** yet →
`Thakur2005` (L90), `rfc2992` (L100), `greenberg2009vl2` + `kandula2009detailed` (L140),
`sergeev2018horovod` + `wang2020overlapping` (L147), `nvidia2023nccl` (L155).
Adopting B1–B7 requires adding these references.

## C. The 17 `\JY{}` comments, verbatim + analysis

Status legend — **[HAVE]** = we already have the answer/data (verified this session);
**[WRITE]** = writing/editorial only; **[NEW]** = needs new work.

| # | Line | Jose's comment (verbatim) | My reading | Status |
|---|---|---|---|---|
| C1 | 133 | "Ibrahem please complete the contributions and add to the introduction the toy example we discuss" | Two asks: finish the contributions list, and add the worked toy example (one congested ring edge; k flows bypass it) to §I. | **[WRITE]** high value |
| C2 | 182 | "maybe undirect?" | On "the fabric is a **directed** graph". Fat-Tree links are full-duplex; he suggests undirected. Directed is still defensible (a ring edge sends one way) — needs one justifying clause, not a model change. | **[WRITE]** |
| C3 | 187 | "maybe better to defune a FT topology first?" | Ordering: define the Fat-Tree before the model uses it. Largely pre-answered by his own B5 block. | **[WRITE]** |
| C4 | 198 | "Consider also the definition of worstcase where we are not allowed to split the traffic: `\Bstar(k) = \min_l \max_i f_i(l)`" | A **second bottleneck definition** for the no-split case (best single flow per link) vs. ours (sum over flows). Genuinely interesting: it is the analytic counterpart of our equal-vs-proportional gap. ⚠️ his snippet re-uses `\label{eq:bstar}` → the duplicate-label warning. | **[NEW]** theory, discuss |
| C5 | 214 | "I am not sure this is the right question to ask. 1) byte slpit is not defined 2) what do you mean by QP budget? Maybe you want to bound the number of flows in each link ring by $K$" | Attacks the Problem statement: define the byte split formally *before* using it, and replace the vague global budget `Σ k_e` with a per-link bound `k_e ≤ K`. | **[WRITE]** formalization |
| C6 | 226 | "Not sure I fully understand the below seems you need to define a theorem and proof" | Wants the ECMP-collision result stated as **Theorem + proof**, not prose. `k_e = m(1−(1−1/m)^k)` is a standard occupancy argument; we validated it to **1.6%** (C.3.7 stage 1). | **[HAVE]** + [WRITE] |
| C7 | 241 | "the probability for a collision depends on the workers location in the Fat Tree: 1) same rack — ECMP does not help 2) same POD $m=R/2$ … 2 links 3) same POD $m=(R/2)^2$ … 4 links. We migth model it somehow" | Placement-aware collisions. **We already do this**: §III states 1 / r/2 / (r/2)² paths, and stage 1 validated k_e separately for M=64 (cross-pod) and M=8 (same-pod). Needs surfacing, not new work. (His item 3 says "same POD" but means cross-pod.) | **[HAVE]** |
| C8 | 253 | "Rewrite the section explaining your algorithmic approach defining split methods and so on: … there is also importance on how the message is split among the different flows. Maybe we need to define an all-reduce algorithm" | **Directly answerable with an asset we already built**: `paper/mechanism_split.tex` — the algorithm2e Algorithm 1 (equal vs proportional, faithful to `sim.py::run_ring_transfer_proportional`) plus `fig_split_mechanism.pdf`. Never `\input` into the paper. | **[HAVE]** — highest ROI |
| C9 | 260 | "Maybe start the section explaining about this parameter" | Open §V by introducing k itself before discussing how to tune it. | **[WRITE]** |
| C10 | 289 | "What do you mean?" | On the setup sentence mixing "n=100 placements (n=1000 in the production run)". Now **more** pressing: Fig 3 and Fig 5 are n=1000 while Figs 1/2/4 and Tables I/II are n=100. Needs a per-figure n statement. | **[WRITE]** |
| C11 | 291 | "Do you mean you reduce the number of uplinks keeping the downlinks the same?" | **No** — Option B reduces agg→core *capacity* (cap/os) and **preserves all (r/2)² paths** (that is the whole point: isolate capacity from path diversity). One sharper sentence fixes it. | **[HAVE]** |
| C12 | 292 | "You need to explain the different congestion models?" | Fig 1 plots hot-spot / on-off / i.i.d. / micro-burst but never defines them. Definitions exist in `reports/congestion_models_report.pdf` + `sim.py::CongestionModel`. | **[HAVE]** + [WRITE] |
| C13 | 293 | "I am missing some information about the allocation method in the physical nodes of FT" | How the P workers are placed. We use uniform random placement per seed (`random.Random(SEED_BASE+seed).sample(hosts, P)`), matched across fabrics. A placement *study* (tracker C.3.5) does not exist and stays optional. | **[HAVE]** (method) |
| C14 | 301 | "Not sure I understand where the contention is?" | Where congestion is injected: `target_layers=["agg_core","edge_agg"]` — i.e. only on links ECMP can route around. | **[HAVE]** |
| C15 | 303 | "What do you mean by bypassable?" | Needs an explicit definition: a link with alternative equal-cost paths around it (agg–core), as opposed to a link on *every* path (host NIC, intra-rack) that no amount of multi-flow can avoid. This term carries our whole story — it must be defined. | **[WRITE]** important |
| C16 | 314 | "What are the dashed lines in graph?" | Fig 2's dashed = optimal-split bound. The caption *and* the legend already say so, so this is a legibility problem — make the dashed series unmistakable. | **[WRITE]** small |
| C17 | 393 | "You need a much more extensive relate work most of the cited works are from more than 10 years ago. Please revise all the papers in the following conference in the 5 last years: 1) Infocom 2) Sigcomm 3) NSDI" | **The biggest task.** Current refs: fattree'08, hedera'10, mptcp'11, thakur'05, rfc2992'00, zong2025ibing, ncclx'25 — five of seven are 10+ years old. Needs a real 2020-2025 INFOCOM/SIGCOMM/NSDI sweep. | **[NEW]** large |

## D. Compile state

* **Fixed by us 2026-07-21:** Jose's `\JY{}` at L393 contained a **blank line at L397**, which
  becomes a `\par` inside `\textbf` (via `\mycomm`) → `Runaway argument` +
  `Paragraph ended before \text@command was complete` + `Too many }'s`.
  Fix = deleting that one blank line (delta −1 char; every word of his text preserved).
  **Errors 2 → 0.**
* **Still open (Jose's, left untouched):** 8 warnings —
  `Label 'eq:bstar' multiply defined` (from his C4 equation snippet) and
  `Citation undefined` for the seven orphan keys listed in §B.

---

# PART 2 — Deep analysis and recommended action per point

Investigation done 2026-07-21. Every "Finding" below was read from a file or the live
editor **this session**; nothing is quoted from memory. Items marked ⚠️ are my own
derivation and still need checking against data before they enter the paper.

## E1 — C8: define the split algorithm  ← **start here**

**Finding.** The asset already exists and is complete: `paper/mechanism_split.tex`
(3,363 B, written 2026-07-15) contains **Algorithm 1** in `algorithm2e` showing both
policies with the single differing block highlighted, explicitly *"faithful to
`sim.py::run_ring_transfer_proportional`"*, plus a figure block for
`fig_split_mechanism.pdf` (25,183 B, exists). It was never `\input` anywhere.

**Recommendation.** `\input{mechanism_split.tex}` into §V (Design), which is exactly the
section Jose asked to rewrite. Prerequisites, both trivial:
1. add `\usepackage[ruled,vlined]{algorithm2e}` to the preamble;
2. upload `fig_split_mechanism.pdf` to Overleaf (native file-picker → manual drag-drop).

**Effort** ~30 min. **Risk** low — but it adds ~½ column, so re-check the 4-page budget.

## E2 — C1: the toy example  (solved by the *same* asset)

**Finding.** `mechanism_split.tex`'s figure caption already contains a fully worked toy:
one ring edge, k=4 flows with measured fair-share rates **100/50/25/100 Gbps**; equal split
finishes at **4.0t**, proportional at **1.45t** — a **×2.75** gap.

**Recommendation.** Reuse that exact toy as the introduction's worked example (Jose's
"the toy example we discuss"). One asset then answers **both** C1 and C8, and the intro and
design section stay numerically consistent. Write the contributions list at the same time.

## E3 — C4: the no-split worst case  (the most interesting theory point) ⚠️

**Jose proposes** `\Bstar(k) = \min_l \max_i f_i(l)` — the bottleneck when traffic *cannot*
be split, i.e. all bytes ride the single best of the k hashed flows.

**My derivation (NOT yet verified against data).** For one edge carrying B bytes over k
flows with fair-share rates f₁…f_k, the *effective* edge rate is:

| policy | edge finishes when | effective rate |
|---|---|---|
| equal split (NCCL default) | the **slowest** sub-flow drains B/k | **k·min_i f_i** |
| no split (Jose's definition) | the single best flow drains B | **max_i f_i** |
| throughput-proportional (ours) | all sub-flows finish together | **Σ_i f_i** |

This yields a crisp statement worth putting in the paper: equal splitting is **not**
merely below the optimum — it can fall below *not splitting at all*, exactly when
`k·min_i f_i < max_i f_i`, i.e. when the rate spread across hashed paths is wide.
Example: rates 100/10/10/10 → equal **40**, no-split **100**, proportional **130** Gbps.
That is the straggler pathology in one line, and it motivates the proportional split
analytically rather than only empirically.

**Recommendation.** Adopt Jose's definition as a **third reference curve** and state the
above as a small proposition. **Before using it:** (a) verify the algebra against the
simulator; (b) check whether `max_i f_i` can be recovered from frozen artifacts — v10.0
stores `t_sim` and `opt_time` (the optimal-split bound) but **not** per-flow rates, so this
may need a small offline re-analysis via `compute_ring_theoretical_time`'s
`edge_contention`, **not** a new simulation. ⚠️ Do not put numbers in the paper until this
is confirmed.
**Housekeeping:** his snippet re-uses `\label{eq:bstar}` → the duplicate-label warning.

## E4 — C6: theorem + proof for the collision model

**Finding (frozen `reports/k_optimal/stage1_analytic_ke/ke_table.csv`).** The closed form
`k_e(k) = m(1-(1-1/m)^k)` is validated in **three** placement contexts:

| context | m | max deviation | at k=8: measured vs model | per-flow efficiency |
|---|---|---|---|---|
| 3-tier cross-pod | 64 | 0.62% | 7.61 vs 7.576 | 95.1% |
| 3-tier same-pod, cross-ToR | 8 | 1.31% | 5.32 vs 5.251 | 66.5% |
| 2-tier cross-leaf | 8 | 1.60% | 5.28 vs 5.251 | 66.0% |

Global worst deviation **1.60%** — this is the paper's "within 1.6%" claim.

**Recommendation.** Promote to **Theorem + proof** (Jose is right that prose undersells it).
The proof is four lines: define indicator X_p = 1 if path p is hit by ≥1 of k i.i.d.
uniform hashes; P(X_p=0) = (1-1/m)^k; linearity of expectation over m paths. Add a
corollary for the marginal value of the (k+1)-th flow, `(1-1/m)^k`, which is where the
existing `k ≲ m ln 2` cap comes from. **Effort** ~1 h, no new data. High polish-per-hour.

## E5 — C7: placement-dependent collisions  (already answered by our own data)

**Finding.** Jose asks for the collision probability to depend on worker placement. The
table in E4 **is exactly that** — k_e validated separately per placement context, and §III
already states the 1 / (r/2) / (r/2)² path counts. Note the per-flow efficiency contrast at
k=8: **95.1%** cross-pod (m=64) vs **66.5%** same-pod (m=8) — multi-flow pays far more when
the pair is cross-pod. (Jose's item 3 says "same POD" where he means cross-pod.)

**Recommendation.** No new work — surface the E4 table (or its m=64 vs m=8 contrast) in the
theory section and cite it in reply. This also answers *"same rack → ECMP does not help"*:
m=1 ⟹ k_e≡1 ⟹ zero benefit, which the closed form gives for free.

## E6 — C5: fix the problem statement

**Jose's objection:** "byte split is not defined" and "what do you mean by QP budget?
Maybe bound the number of flows in each link by K".

**Recommendation — adopt, he is right on both counts.** Restate §III as: for each ring edge
e choose a flow count k_e and a **split vector** b_e = (b_{e,1},…,b_{e,k_e}) with
Σ_j b_{e,j} = M/P (the per-step bytes), minimising T subject to a **per-edge** cap
**k_e ≤ K**. The per-edge cap is strictly better than our global Σ_e k_e because it is the
quantity NCCL actually exposes (`NCCL_IB_QPS_PER_CONNECTION` is per connection), so the
formulation then matches the deployable knob. Defining b_e up front also gives equal vs
proportional a formal home (b_{e,j} = M/(P·k_e) vs b_{e,j} ∝ r_j).

## E7 — C15 + C14 + C11 + C12: the four clarifications, all sourced from code

| pt | Jose asks | Grounded answer (source read this session) |
|---|---|---|
| **C15** | "what do you mean by bypassable?" | `sim.py:411-416`: `target_layers` — *"congestion only on links where ECMP provides alternative paths"*. Define it as: a link with ≥2 equal-cost paths around it (agg–core, edge–agg), as opposed to a link on **every** path (host NIC, intra-rack) where no k helps. This term carries the whole story and must be defined on first use. |
| **C14** | "where is the contention?" | `target_layers=["agg_core","edge_agg"]` — injected only on those two layers. |
| **C11** | "do you reduce uplinks, keeping downlinks?" | **No.** Option B reduces agg→core *capacity* (`uplink_cap = capacity_Bps / oversub`, `sim.py:167,223`) and **preserves all (r/2)² paths** — deliberately isolating capacity from path diversity. |
| **C12** | "explain the congestion models" | `sim.py:372-417` gives all four verbatim: **iid** = per-tick independent draws (uncorrelated; a stress baseline the controller cannot track); **onoff** = persistent ms-scale bursts, per-link on/off Markov (the realistic regime, Benson IMC'10); **hot_spot** = a fixed link set congested every tick (persistent, deterministic); **microburst** = rare sub-ms spikes (2 ticks = 100 µs) *shorter than the 1 ms controller window* — the controller's temporal limit by construction. |

**Recommendation.** One compact "Congestion regimes" paragraph in §VI covering C12+C14+C15,
and one sentence in Setup for C11. All four are pure writing — no new runs.

## E8 — C10: state n per figure (now genuinely ambiguous — partly our doing)

**Finding.** After today's work the paper mixes two sample sizes:

| artefact | source | n |
|---|---|---|
| Fig 1 congestion | v6.1 | 100 |
| Fig 2 saturation | v10.0 | 100 |
| **Fig 3 cross-k** | **v12.1** | **1000** |
| Fig 4 gap-closure | v11.0 | 100 |
| **Fig 5 controller** | **v5.1 (P=16) + v5.2 (P=64)** | **1000** |
| Tables I & II | v10.0 / kstar_table | 100 |

**Recommendation.** Replace the vague "n=100 (n=1000 in the production run)" with an
explicit sentence naming which results are n=1000 (the cross-k payoff and the controller),
and keep n in every caption. Cheap, and removes a real reviewer stumble.

## E9 — C2 / C3 / C9 / C16: small editorial items

* **C2 "maybe undirect?"** — **keep directed, and say why.** `sim.py:11` is explicit:
  `Edge = Tuple[Node, Node]  # directed (u -> v)`, with an independent capacity entry per
  direction (`edge_of[(u,v)]`). That *is* the correct full-duplex model; going undirected
  would wrongly make the two directions share one capacity. One clause settles it.
* **C3** "define the Fat-Tree first" — largely pre-answered by Jose's own B5 block; adopt B5
  and the ordering complaint disappears.
* **C9** "start the section by explaining the parameter" — open §V by introducing k before
  discussing how to choose it.
* **C16** "what are the dashed lines?" — Fig 2's caption *and* legend already say
  "optimal-split bound", so this is legibility, not content: make the dashed series
  visually unmistakable (heavier dash / direct label on the curve).

## E10 — C17: the related-work sweep  (largest item — start immediately)

**Finding.** Five of the seven `\bibitem`s are 10+ years old (fattree'08, hedera'10,
mptcp'11, thakur'05, rfc2992'00); only IBing'25 and NCCLX'25 are recent. Jose's complaint is
factually correct and is the single most likely reviewer objection.

**Sweep completed 2026-07-21** (agent-run, then spot-verified by me — see E12). Mandatory
additions a reviewer will expect: **Meta RoCE** (SIGCOMM'24), **Alibaba HPN** (SIGCOMM'24),
**Ethereal** (arXiv 2407.00550), **ConWeave** (SIGCOMM'23), **REPS** (EuroSys'26),
**SwitchML** *or* **ATP** (NSDI'21, one is enough), **PC4** (INFOCOM'25), and **MP-RDMA**
(NSDI'18) kept only as the acknowledged ancestor. Budget half a day to write the section.

## E12 — ⚠️ POSITIONING RISK: the mechanism is no longer novel  (verified, act on this)

**I verified these claims myself against primary sources this session** — the sub-agent was
accurate (no fabrication this round), but these are consequential enough that I re-read them:

**Ethereal** — *"Ethereal: Divide and Conquer Network Load Balancing in Large-Scale
Distributed Training"*, Addanki, Goyal, Marinos, Schmid (arXiv 2407.00550). Verified from the
full text:
* It **uses our exact mechanism**: *"NCCL allows users to configure
  NCCL_IB_QPS_PER_CONNECTION and NCCL_IB_SPLIT_DATA_ON_QPS, which distribute data
  transmissions between a GPU pair across multiple queue pairs uniformly"*, and
  *"Meta leverages this property to effectively increase entropy for ECMP"*.
* It claims *"our study is the first to systematically explore their implications for
  transport protocol design in distributed training workloads"* and *"the first to combine
  flow splitting and source routing"*.
* Its thesis **argues against** multipath: singlepath transport per NIC nearly matches ideal
  packet spraying on CLOS topologies. A reviewer could read that as undercutting our
  motivation — we must address it head-on, not hope it is missed.

**Verified gaps that remain ours** (both checked in the full text):
1. **It never derives an optimal k** — it only reports empirical ceilings ("at most 32 queue
   pairs… at most 64 across all evaluations") framed as low overhead. Our regime-dependent
   **k\*** is genuinely unclaimed.
2. **The word "oversubscription" does not appear in it at all.** Our os2:1 / os4:1 sweep —
   where the whole effect lives (up to 6.52×) — is uncovered ground.
3. It **requires source routing** (path IDs in packet headers). We need only stock ECMP
   hashing → a materially weaker deployment assumption. This is our strongest framing lever.
4. Its split rule is combinatorial/open-loop; ours is measurement-driven/closed-loop
   (re-divide ∝ observed rate).

**Meta RoCE at Scale** (Gangidi et al., SIGCOMM 2024) — verified: ECMP performs poorly for
training due to **low flow entropy**, and QP-scaling 4 → 32 is discussed as the remedy. This
is our premise, from production. **Not citing it reads as unfamiliarity with the field.**

**Other near neighbours to cite and distinguish:** *ParaLet* (NAIC'24 workshop — parallel
flowlets on distinct source ports, few QPs, AI-training Clos: our mechanism, but no
split-ratio policy and no k\* rule); *MPCCS* (EuroSys'26 — "runtime traffic splitting" for
collectives, but scale-up/scale-out split, not k QPs inside one ECMP fabric); *CAVER*
(SIGCOMM'24 poster — "hunting less-congested paths", i.e. exactly the steering our C.3.8
study measured as mostly redundant → cite it and present our negative result as a
deliberate, evidence-backed refutation rather than leaving it uncited); *UCCL* (arXiv 2025).

**Strategic conclusion — and it confirms the framing we already chose.** Opening k QPs to
raise ECMP entropy is *shipped by Meta, standardized by OCP MRC, and published on by Ethereal
and ParaLet*. It cannot be the headline. What is still unclaimed is exactly our three
contributions: **(a)** a principled **k\*** as a function of fabric regime and
oversubscription, **(b)** measurement-driven **proportional** splitting vs NCCL's equal
split, **(c)** the **per-edge adaptive controller**. This independently validates the
characterization-led framing the expert panel agreed on 2026-07-07 — and it means the
abstract must not sound like "we propose multi-QP".

⚠️ **Unverified items from the sweep — do NOT cite until checked:** anything the agent marked
`VENUE UNCONFIRMED` (STrack, UCCL, Ethereal itself as a venue paper, McClure et al., Hopper),
the *"Characterization of LLM Development in the Datacenter"* item (the agent never reached a
primary source), and the Rail-only venue (cite as **HOTI 2024**, not HotNets 2023).

## E11 — B1-B7: Jose's proposed prose

**Finding on B1 (the alternative abstract).** It is a genuine improvement in framing —
opens with AI scale and the cost of stragglers, then ECMP pinning, then our fix — and,
importantly, **it already respects our scoping fixes**: it says "under **targeted
congestion**" and "half the available queue-pairs **on highly constrained fabrics**".
So Jose wrote it on top of our corrections rather than reverting them.
**B6** is a well-written expansion on why the ring is throughput-optimal (it also covers a
chunk of the still-open tracker task D.3, the all-reduce survey).

**Recommendation.** Adopt B1 largely as-is, but (i) keep our exact frozen numbers, and
(ii) consider adding the now-available P=64 controller result. Merge B2-B7 paragraph by
paragraph rather than wholesale. ⚠️ Two cautions: adopting them **requires adding the seven
missing `\bibitem`s** (Thakur2005, rfc2992, greenberg2009vl2, kandula2009detailed,
sergeev2018horovod, wang2020overlapping, nvidia2023nccl); and B6's phrase "saturates the
available **bidirectional** bandwidth" should be checked against our unidirectional ring
model before it goes in.

---

# PART 4 — Jose's VERBAL comments (meeting 2026-07-28, not in Overleaf)

Five items raised in the meeting. Analysis below is grounded in data read this session.

## M1 — "How are the workers chosen? The placement policy is not clear."

**Status of the paper today:** it never states the policy. The simulator uses
`random.Random(SEED_BASE+seed).sample(hosts, P)` — a uniform random draw of P hosts
from all 1024, redrawn per seed and reused across fabrics so comparisons stay paired.

**Why this is the sharpest of his comments:** placement sets *how much room multi-flow
has*, and we already have hard evidence — the placement bug (tracker A.5) was exactly a
change of policy, and it moved the headline from **2.84× to 2.45×**.

**The policy space worth naming:**

| policy | what it is | effect on the ring | effect on multi-flow |
|---|---|---|---|
| **compact (same ToR)** | all workers under one ToR (max 8 hosts at r=16) | fastest baseline — traffic never enters the fabric | **no benefit**: m=1, k_e≡1 |
| **compact (same pod)** | P=64 fills exactly one pod — *this is what the bug did* | few paths, most edges intra-rack | **weak**: measured 2.45× |
| **random (ours)** | uniform draw over all hosts | ~59/64 edges cross-pod | **2.84×** |
| **spread (one per pod)** | every ring edge cross-pod | slowest baseline, all traffic through core | **largest room** (not yet measured) |

**The tension to state explicitly:** compact placement gives the *best absolute* completion
time but the *least* multi-flow benefit; spread placement is the opposite. Random sits in
between and is the realistic case for a scheduler that does not co-locate a job.

**MEASURED 2026-07-28** (`results/placement_policies_2026-07-28`, os4, P=64, af=0.5, n=100,
paired; only the ring construction varies):

| policy | baseline k=1 | speed-up at k=8 | ring-edge path counts |
|---|---|---|---|
| **compact (one pod)** | **69 ms** | **2.48×** [2.40, 2.56] | 56 edges see 1 path, 8 see 8 |
| **random (ours)** | 403 ms | **3.60×** [3.47, 3.74] | 59 edges see 64 paths |
| **spread (all cross-pod)** | 407 ms | **3.43×** [3.23, 3.64] | **all 64 edges see 64 paths** |

Three results:
1. **The tension is real and large.** Compact placement is **5.8× faster in absolute time**
   (69 ms vs ~405 ms) yet yields the **smallest** multi-flow gain — there is nothing to
   spread over. Placement decides how much room the mechanism has.
2. **Random ≈ spread.** Baselines are within 1% (403 vs 407 ms) and the speed-up intervals
   overlap. Once most edges are cross-pod, *guaranteeing* that all of them are changes
   little. So our random draw is **not a lucky or unlucky corner** — a robustness result
   worth stating, and the direct answer to "how are the workers chosen?".
3. The distinct regime is **compact**, and that is exactly what the placement bug (A.5)
   silently selected.

⚠️ **CORRECTED 2026-08-04 — the original "overlapping confidence intervals" was the wrong
test.** These policies share one seed set, so the comparison must be **per-seed paired**;
overlap of the two independent per-policy CIs is a weaker and, here, misleading check.
Re-run at n=1000 (`results/placement_policies_n1000`,
`experiments/run_placement_policies_n1000.py` — identical to the frozen script except that
it writes a new version instead of overwriting the 2026-07-28 one):

| policy | n=100 (frozen) | **n=1000** |
|---|---|---|
| compact (one pod) | 2.48 [2.40, 2.56] | **2.46 [2.434, 2.487]** |
| random (ours) | 3.60 [3.47, 3.74] | **3.58 [3.538, 3.628]** |
| spread (all cross-pod) | 3.43 [3.23, 3.64] | **3.43 [3.366, 3.487]** |

Paired random-vs-spread: **+0.157 speed-up points, 95% CI [0.078, 0.233]** at n=1000 —
random is *slightly but resolvably better* than deliberate spreading, and spread still wins
on 416/1000 individual placements. At n=100 the paired ratio already said the same
(1.156 [1.074, 1.240]); only the unpaired CIs happened to overlap. The paper's sentence was
rewritten to state the deficit instead of claiming equality.

⚠️ Fabric note: this sweep runs on **os4**; the 2.84× headline is on the **non-blocking**
fabric. Do not compare 3.60 with 2.84 — the three policies are internally comparable.

Placement *optimisation* itself is a scheduler-side lever (TopoOpt, Crux) and should be
named as out of scope, not silently ignored.

## M2 — "Has it converged? Is n large enough?"  ✅ ANSWERED — yes

Measured on the frozen n=1000 headline run (`v5.4`, os4/P64/k=8/af=0.5):

| n | running mean | 95% CI half-width |
|---|---|---|
| 25 | 2.754 | ±0.196 |
| 50 | 2.861 | ±0.143 |
| 100 | 2.865 | ±0.094 |
| 400 | 2.875 | ±0.049 |
| **1000** | **2.844** | **±0.028** |

The mean is stable from n≈50 (all later values sit inside each other's intervals) and the
interval shrinks as 1/√n (0.196→0.028 over a 40× increase; √40≈6.3). **n=100 was already
within 0.8% of the n=1000 answer; n=1000 buys ±1% precision.** Worth stating in the paper.
Note the *per-placement* spread is large — min 1.54×, max 4.87×, std 0.46 — which is
precisely why the average is taken over placements, and why M1 matters.

## M3 — "Define oversubscription and non-blocking."

Both are used throughout and never defined. Grounded definitions:
* **Non-blocking** — full bisection: the fabric can sustain every host at line rate
  simultaneously. For r=16: 1024 hosts × 100 Gbps, bisection **51.2 Tbps**.
* **Oversubscribed x:1 (our Option B)** — we scale **aggregation–core link capacity** by
  1/x and **keep all (r/2)²=64 equal-cost paths**. This is deliberate: it varies capacity
  while holding path diversity fixed, so the multi-flow effect is not confounded with
  path count. (Note: an alternative "Option A" would remove uplinks, which changes both.)

## M4 — "Fig. 5 is unclear."

Partly overtaken: Fig 5 was rebuilt on 2026-07-28 from the placement-fixed data and now
shows P=64 (selectivity) rather than P=16 (the withdrawn QP-saving claim). **The residual
problem is real: the two adaptive stars carry no legend entry** — only one is annotated —
so a reader cannot tell what the second star is. Fix: add the stars to the legend.

## M5 — "Table II's efficiency computation is not accurate."  ⚠️ he has a point

The arithmetic is right (every cell = speed-up/k, verified against v10.0), but the
*metric* conflates two different losses. Dividing by **k** charges the mechanism for flows
that never reached a distinct path. Dividing by **k_e** (the effective distinct paths our
own §IV model predicts) separates them:

| k | speed-up | k_e | /k (paper) | /k_e |
|---|---|---|---|---|
| 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| 4 | 2.47 | 3.91 | 0.62 | 0.63 |
| 8 | 3.58 | 7.61 | 0.45 | 0.47 |
| 16 | 4.97 | 14.28 | 0.31 | 0.35 |
| **32** | **6.52** | **25.32** | **0.20** | **0.26** |

At k=32 the two differ by 30%. The gap **is** the hash-collision loss; what remains after
dividing by k_e is the genuine capacity-side diminishing return. **Recommendation:** add a
k_e column (or report both), which also makes the k_e model of §IV earn its place —
answering his "theorem and proof" comment (L226) at the same time.

---

# PART 3 — Proposed order of work (10 days to the 31 Jul deadline)

| Order | Items | Why now | Cost |
|---|---|---|---|
| **0** | **Positioning fix (E12)** — make sure the abstract/intro do **not** read as "we propose multi-QP"; lead with the characterization (k\*, proportional split, controller) and add an explicit paragraph distinguishing us from Ethereal / ParaLet / Meta on the two verified gaps (**no k\* derivation**, **no oversubscription**) plus our stock-ECMP-only deployment assumption | **Now the top risk** — it changes framing, and everything else is cosmetic if a reviewer thinks the mechanism is known | ~2 h |
| **1** | **C17 sweep** (done — write it up) | Cite the 8 expected papers; distinguish the 5 near neighbours | ½ day |
| **2** | **C8 + C1** | One existing asset answers both; biggest visible gain | ~1 h |
| **3** | **C12, C14, C15, C11, C7, C10** | All answerable from frozen material read today | ~2 h |
| **4** | **C6** theorem, **C5** reformulation | Real polish, no new data | ~2 h |
| **5** | **B1-B7** adopt/merge + the 7 `\bibitem`s | Depends on the C17 sweep | ~½ day |
| **6** | **C4** no-split bottleneck | Needs the ⚠️ verification in E3 first | ~2 h |
| **7** | **C2, C3, C9, C16** | Small editorial cleanups | ~1 h |

**Nothing in this list requires a new simulation run.** Only C4 might need a small offline
re-analysis of existing artifacts. Page budget is the main risk: C8 and B1-B7 both add
material to a paper already at 4 pages.

---

# PART 5 — State as of 2026-08-04 (supersedes PART 3's plan and E8's figure table)

Context: the INFOCOM'27 deadline (31 Jul AoE) passed **without submission** — new venue to
be chosen with Jose. Work continued to the strongest version. Doc: 31,433 → **43,063 chars**;
compile **Errors 0 / Warnings 3** (floor: `eq:bstar` dup inside Jose's C4 comment + BibTeX
empty-key + underfulls). Every claim below was verified against the live editor buffer or a
frozen CSV **on 2026-08-04**.

## 5.1 Comment ledger — 17 → 12 `\JY` remaining

Five comments were **deleted** after per-comment verification that the answer lives in the
paper body (C10 per-figure n now explicit in Setup; C11 Option B sentence; C12 congestion
regimes defined in §VI; C14 injection layers named; C15 "bypassable" defined at first use).

The 12 kept, current state:

| # | Comment (short) | State 2026-08-04 |
|---|---|---|
| C1 | toy example + contributions | ✅ in body (toy in §I from the 100/50/25/100 asset; contributions rewritten) — kept for Jose |
| C2 | "maybe undirect?" | ✅ justifying clause (directed = full-duplex, per-direction capacity) — **decision is Jose's** |
| C3 | define FT first | ✅ **2026-08-04**: `\textbf{Fat-Tree.}` definition added before Paths-and-ECMP (+`\IH`) |
| C4 | worst-case no-split B* | ⏳ **open** — the only remaining content item; needs E3's offline verification first |
| C5 | byte split undefined / QP budget | ✅ **2026-08-04**: formal split vector b_e after eq:T + Problem restated with per-edge k_e ≤ K (+`\IH`) |
| C6 | theorem + proof | ✅ **2026-08-04**: **Lemma 1** (`lem:ke`) + `IEEEproof` (occupancy/linearity), 1.6% check follows (+`\IH`) |
| C7 | placement-dependent collisions | ✅ in body (m = 1 / r/2 / (r/2)²; 95% vs 66% at k=8) — kept for Jose |
| C8 | define split algorithm | ✅ Algorithm 1 (algorithm2e) pasted into §V + `fig_split_mechanism` — kept for Jose |
| C9 | explain the parameter | ✅ **2026-08-04**: `NCCL_IB_QPS_PER_CONNECTION` explained at first mention in §II (static 1–128, run-fixed); §V uses the full name (+`\IH`) |
| C13 | allocation method | ✅ in body (uniform random per seed, paired; policy sweep 2.48×/3.60×/3.43× from `placement_policies_2026-07-28`) — kept for Jose |
| C16 | dashed lines | ✅ figure redesigned 2026-08-04 (bounds heavier/α=.85/above lines; legend "optimal-split bound (dashed, fabric colour)"; k=8 annotation) — kept until Jose sees |
| C17 | related work sweep | ✅ **2026-08-04**: section replaced with 3-thrust version (Production multi-flow / Fabric- and transport-side balancing / Collective-side acceleration) — kept for Jose |

## 5.2 What changed in the paper on 2026-08-04

1. **E12 positioning implemented** (adversarial 3-judge + 4-venue-group workflow):
   abstract fully rewritten (production-response framing; k* rule headlined; "never loses in
   any of 4,000 paired configurations"; honest 2.84× vs 1.25–1.33× spread; "only knobs NCCL
   already exposes"); intro approach paragraph names + cites Meta RoCE and Ethereal first and
   defuses Ethereal's counter-thesis with our own non-blocking 1.21× data point;
   contributions (i)/(ii) rewritten. Judge overreach caught twice (prop@32=7.82 exists in
   v12.1; "peaks" wording dropped anyway — curve still rising, never claim "peak").
2. **Related Work replaced** — see citation map in 5.4.
3. **v5.5 run** `results/v5.5_adaptive_n1000_placementfix` (n=1000, 24,000 sims,
   `efficiency_summary.csv` = 80 static rows from v5.4 + 24 adaptive rows, bootstrap
   nb=5000 seed=42). Controller §VI numbers now: P=64 af=0.1 **2.03× @ 131 QPs** (k=2 static
   1.50×), af=0.5 **2.11× @ 237** vs static k=4 2.15×; P=16 af=0.5 2.08× @ 57.9 vs k=4 2.26×
   — caption uses the "matches" two-result form.
4. **Figure wave** — 15 must_fix from a two-manager vision debate, all implemented (split
   figure re-encoded to TIME; controller stars hollow + value labels + leader arrows;
   saturation bounds emphasized + k=8 annotation + scale marking; gap-closure negative bars
   labelled −2.8/−1.0 (v11.0 structural end-game decay, verified from the frozen CSV);
   crossk two-leg anchored annotation; in-panel titles; float order). My own vision pass
   caught 4 more defects (clipped title, off-canvas label, 2 collisions) before upload.
5. **Formalization wave (1.3)**: FT definition, split vector, per-edge K bound, Lemma 1 +
   IEEEproof, NCCL parameter explanation (items C3/C5/C6/C9 above). `\newtheorem{lemma}`
   added to preamble; all new `\ref`s verified resolving.

## 5.3 Corrected figure → data map (E8's table is stale)

Read from `build_ieee_eval_figs.py` / `build_split_mechanism_fig.py` on 2026-08-04:

| figure | frozen source | n |
|---|---|---|
| speedup_by_model (congestion) | **v6.2**_congestion_models_randomplacement | 100 |
| saturation + efficiency | v10.0_k_saturation_2026-07-02 | 100 |
| crossk | v12.1_flagship_n1000_os4p64/crossk_n1000.csv | **1000** |
| gap_closure | v11.0_flexible_split_2026-07-02 | 100 |
| controller | **v5.5**_adaptive_n1000_placementfix (falls back v5.4 / v5.1) | **1000** |
| split_mechanism | toy (100/50/25/100 Gbps; ×2.75) — no CSV | — |

Setup states explicitly which results are n=1000 (crossk + controller). ⚠️ Camera-ready
note: the **uploaded** PDFs are core-font compacts (Times); the canonical embedded-font
builds live locally and must replace them before any final submission.

## 5.4 Citation map — every entry venue-verified from a primary source before entering `mybib.bib`

Added 2026-08-04 (13 new; `zong2025ibing` pre-existing): `gangidi2024rdma` (SIGCOMM'24,
full 14-author list), `qian2024hpn` (SIGCOMM'24), `song2023conweave` (SIGCOMM'23),
`deng2024caver` (SIGCOMM'24), `addanki2024ethereal` (arXiv 2407.00550),
`bonato2026reps` + `xu2026mpccs` (EuroSys'26), `lu2018mprdma` (NSDI'18),
`sapio2021switchml` + `lao2021atp` (NSDI'21), `qi2025pc4` (INFOCOM'25),
`cao2024paralet` (NAIC'24 wkshp), `zhou2026uccltran` (spot-audited at usenix.org —
its 3.3× claim conflicted with an agent's 4.5×, so **no UCCL numbers are quoted**).
Rule applied: respected venues only, no bare arXiv citations except Ethereal
(unavoidable neighbour) — and no number from any of them enters our text.

## 5.5 Verbal comments (PART 4) — current state

| | State |
|---|---|
| M1 placement | ✅ Setup paragraph: uniform-random policy + the 2.48/3.60/3.43 sweep |
| M2 convergence | ✅ Setup: n-stability sentence (n=100 within 0.8% of n=1000; ±1% CI) |
| M3 definitions | ✅ Setup: non-blocking = full bisection (51.2 Tbps here); oversubscription = agg-core capacity ÷ os, all m paths kept (verified in buffer 2026-08-04) |
| M4 Fig 5 stars | ✅ redesigned figure: stars carry value labels + leader arrows + caption naming both |
| M5 Table II /k vs /k_e | ✅ **CLOSED** — Table `tab:dimin` carries three rows: `distinct paths k_e` (1.0/2.0/3.9/7.6/14.3/25.3), `eff. /k` (1.00/0.85/0.62/0.45/0.31/0.20) and `eff. /k_e` (1.00/0.85/0.63/0.47/0.35/0.26), read from the buffer 2026-08-04 |

⚠️ **Self-correction (2026-08-04).** M5 was first written here as OPEN on the basis of a
search for `\label{tab:eff}` — a label that does not exist; the table is `tab:dimin`. The
lesson is the protocol's own rule: a negative result from a *guessed* identifier is not
evidence. Re-checked by enumerating every `table` environment in the buffer.

## 5.6 Open queue

1. **C4 / task 1.5 — VERIFIED 2026-08-04. One E3 claim is refuted; a better result
   replaces it.** Script: `scratchpad/verify_c4_nosplit.py` (P=64, seeds 0–9, k∈{2..32},
   200 cells) — no new simulation, only the deterministic ECMP enumeration that
   `compute_ring_theoretical_time` itself uses. Wider re-run in `verify_c4_full.py`.

   Final numbers are from the **full** run (`verify_c4_full.py`): **4,000 cells** =
   100 frozen seeds × P∈{16,64} × 4 fabrics × k∈{2,4,8,16,32}, 160,000 logical edges.

   * **Gate 1 — the machinery is exact.** Σ_i f_i reproduces the frozen `opt_time`
     in **4000/4000** cells (0 mismatch), so all three variants are computed from the
     same rates the frozen results already carry.
   * **Gate 2/3 — E3's headline claim is essentially REFUTED at ring level.** "Equal
     splitting can fall below not splitting at all" (k·min f < max f) holds on **332 of
     160,000** individual logical edges (0.21%), but decides the ring bottleneck in only
     **2 of 4,000** cells (0.05%). Reason: B\* is a *min over edges*, and the edge that
     sets the equal-split bottleneck is usually not the one with the widest rate spread.
     **The 100/10/10/10 example in E3 must not go in the paper as if it were typical** —
     it is a real but 0.05%-rare ring-level event. (The 10-seed pilot reported 0/200 and
     would have overstated this as impossible; the full run is the number to quote.)
   * **Gate 4 — the result actually worth having.** The static equal-split formula
     predicts the *simulated* equal-split completion time to within **0.80% max
     (0.46% mean, p95 0.58%)** over all 4,000 cells, and is optimistic (below the sim)
     in **4000/4000** — a one-sided error exactly consistent with the 50 µs tick
     quantum. That closes the equal-vs-proportional gap analytically:

     > **T_equal / T_opt = (Σ_i f_i) / (k · min_i f_i)** — the ratio of the mean to the
     > minimum of the per-path fair shares; it is 1 iff all hashed paths get equal
     > service, and grows exactly with the rate spread ECMP produces.

     This is a stronger answer to *"define a theorem and proof"* than Lemma 1 alone:
     Lemma 1 says how many distinct paths k flows reach, this says what the *spread*
     across those paths costs. It also motivates proportional splitting analytically
     rather than only empirically — the gap Fig. 4 measures.

     **Independent cross-check against a frozen CSV** — predicted equal-split penalty
     vs `v11.0_flexible_split_2026-07-02/summary.csv` `mean_gap_equal_pct`
     (3tier_os4, P=64), two unrelated computations:

     | k | measured gap (v11.0) | predicted (Σf)/(k·min f) − 1 |
     |---|---|---|
     | 2 | 10.88% | 9.5% |
     | 4 | 51.29% | 49.2% |
     | 8 | **64.03%** | **63.3%** |
     | 16 | 45.82% | 45.6% |

     The residual is the ratio-of-means vs mean-of-ratios difference plus the tick.
     The formula also reproduces the *non-monotonicity* — the penalty peaks at k=8 and
     falls again — which no hand-waving argument gives.
   * **Jose's own definition is well-posed** and computes to a *far worse* bound
     (no-split at k=32 ≈ 172 ms vs 5.4–6.7 ms) because a fair share f_i shrinks as k
     grows: opening k flows and using one is strictly wasteful. Useful as a stated
     reference point, not as a competitive curve.

   **IMPLEMENTED 2026-08-04 (approved).** §III now carries **Proposition 1**
   (`prop:spread`) with an `IEEEproof`, stating
   T_equal/T_opt = (Σ_i f_i)/(k·min_i f_i) and naming Jose's no-split bound as
   Eq. `eq:bstar-ns`. Validation re-run on the **full n=1000 sweep**: 40,000 cells,
   Σ_i f_i reproduces `opt_time` in 40000/40000, prediction error ≤ **0.80%**
   (mean 0.46%), one-sided in 40000/40000, and the predicted gap at k=8 matches the
   measured one to 0.3 points (67.2% vs 67.5%). The refuted pathology example was
   dropped; the honest ring-level rate (16 of 40,000) is stated instead.

   **Correction 2026-08-06 — `eq:bstar-ns`.** The implementation note above is
   historical, and its claim that the no-split expression was named as that equation
   is not present in the final source. The substance of the no-split case is covered
   by Proposition 1 (`prop:spread`) through the single-sub-flow bound
   (B/\max_j f_j). The unnumbered `\Bstar_{\mathrm{ns}}` equation remains inside
   Jose's live `\JY{...}` comment, so C4 is genuinely open for the §III sprint. This
   correction records the final-source state; the historical entry is intentionally
   left unchanged.
2. **R1/R2 — APPROVED and running (2026-08-04).** New producer scripts, new frozen
   versions; v10.0/v11.0 untouched:
   * **R1** `experiments/run_k_saturation_n1000.py` → `results/v10.1_k_saturation_n1000`
     (48,000 sims). Equivalence gate passed **before** launch: seeds 0–2 reproduce the
     frozen v10.0 rows bit-for-bit (144 rows, 864 fields, **0 mismatches**), so the only
     change is the seed count.
   * **R2** `experiments/run_flexible_split_n1000.py` → `results/v11.1_flexible_split_n1000`,
     pairing against v10.1 (same `SEED_BASE=9000` ring construction). Adds an explicit
     flagship line (equal@k32 / prop@k16 on os4/P=64) and prints the paired-configuration
     count behind the "never loses" claim.
   * **k\*** is recomputed by `reports/k_optimal/stage3_kstar_rule_n1000/kstar_analysis_n1000.py`
     — same EPS/grid/attribution as the frozen stage 3, but it prints n=100 vs n=1000
     **side by side** so a changed k\* is visible rather than silently swapped in.
     (The frozen stage-3 script's `RESULTS_ROOT` — `parents[2]/"simulator"/…` — does not
     resolve on this machine, where `reports/` sits *inside* `simulator/`; the new script
     resolves it correctly. Worth fixing in the frozen copy separately.)
   **RESULTS (both runs finished 2026-08-04, all guards clean):**

   * **R1 guards** — sim never beats the optimal-split bound: **0 violations**;
     k=1 equal==optimal: max gap **0.58%** (<1%).
   * **k\* is unchanged in 8 of 8 cells.** The rule headlined in the abstract is not
     an artifact of n=100. The decision margins are now unambiguous: the saturated
     cells sit at +0.0–0.4% marginal at the last doubling, the unsaturated ones at
     **+4.1% [3.4,4.8]** (os4/P16), **+33.7% [32.6,34.8]** (os4/P64) and
     **+11.3% [10.7,11.9]** (leaf-spine/P64) — none straddles the 3% threshold.
   * **R2 guard** — proportional never slower than equal: **0 violations of 32,000
     paired configurations** (was 4,000). The paper's claim was updated accordingly.
   * **Flagship reproduced independently**: R2's own paired computation gives
     equal@k32 / prop@k16 = **1.1163 [1.1088, 1.1241]** on os4/P=64 — against the
     v12.1 figure's [1.109, 1.124]. Two separate runs, same interval.
   * Speed-ups shifted only slightly, but every affected number in the paper was
     updated: Table I (1.21→**1.27**, 2.27→2.30, 4.54→4.61, 1.66→1.71, 2.02→2.05,
     3.90→3.99, 6.52→**6.61**, 2.82→2.80 and their per-QP columns), Table II
     (3.58→3.62, 4.97→5.00, 6.52→6.61; /k at k=32 0.20→0.21; /k_e at k=8 0.47→0.48),
     the k=8 coincidence sentences (3.55/3.58 → **3.58/3.62**, bounds 3.8/5.8 →
     **3.9/6.0**), the brute-force sentence (6.5×→6.6×, 0.20→0.21), and the
     **Ethereal-defense sentence** (`$1.21\times$ at $P{=}16$` → **1.27×**, CI
     [1.13,1.29] → [1.24,1.30] — the sharper number also makes the argument safer).
   * **Setup n-statement simplified**: "All results use $n{=}1000$ random placements,
     except the congestion-model sweep (Fig. 1), which uses $n{=}100$." Only three
     `n{=}100` mentions remain, all deliberate.
   * Figures rebuilt from v10.1/v11.1 and re-uploaded with SHA-256 verification
     (gap_closure 3,071 B, saturation 8,541 B — both hashes matched the local files
     before upload). Gap-closure now reads 67.5 / 29.9 / 10.2 / 19.8 with the
     negative proportional bars at −2.6 / −1.0 (they persist at n=1000, so the
     end-game decay of the bound is structural, not sampling noise).
   * Hand-typed numbers removed from `build_ieee_eval_figs.py`: the saturation
     annotation now reads its four values from the same CSV as the curves, so it
     cannot drift when the source version changes.
   * `fig_efficiency` is **not** included in the paper (verified: 6 `\includegraphics`)
     — it was rebuilt but needed no upload.
   * Compile after every wave: **Errors 0 / Warnings 3** (the known floor).

## 5.7 Figure-render bug found by the reader — and the verification gap behind it

**2026-08-04, reported by Ibrahem.** The uploaded figures showed `\times2.75` and
`3.58\times/3.62\times` as **literal LaTeX**, not `×`. Root cause: the compact
(core-font) build strips `$` to avoid mathtext font embedding, and `$\times$` has
no `\frac`/`\sum`/`_` to trigger the sanitizer's skip-guard — so the `$` went and
the bare command stayed. Confirmed by extracting the text layer of the *uploaded*
PDFs with PyMuPDF.

**The verification gap is the real lesson.** The SHA-256 gates proved the bytes
arrived intact and I viewed the *canonical* PNGs with vision — but the **compact**
build is a different render, and nobody ever looked at it. Hash integrity is not
content correctness.

Fixes applied:
* `_san` now maps `\times` → U+00D7 **before** stripping `$`, and **raises** if any
  backslash survives — the class of bug cannot ship silently again.
* The compact build now rasterises each PDF and asserts the text layer is
  backslash-free (`TEXT-CLEAN`) before emitting the relay payload; I also view the
  rasterised compact, not only the canonical.
* `fig_saturation` (8,549 B) and `fig_split_mechanism` (2,846 B) rebuilt, verified
  and re-uploaded.

### 5.7.0 The two audit leftovers, both closed by running (2026-08-04, later that day)

**(a) The background-traffic sentence was wrong — and its source had three defects.**
The audit could not trace "under $1\%$ up to 500 flows/s and about $2\%$ at 1000" to any
CSV in the current map. It traces to `results/v3.0_allreduce_2026-04-13/background`, and
reading `experiment_allreduce_background.py` shows why it should never have been quoted:

| # | defect | line |
|---|---|---|
| 1 | `NUM_RUNS = 3` — three seeds, in a paper whose every other number is n=1000 | :46 |
| 2 | `build_worker_ring(..., start_index=0)` — the **pod-local ring of A.5**, so background traffic on agg–core links could not reach the ring at all | :75 |
| 3 | `seed = int(time.time_ns())` — the frozen run is **not reproducible** | :73 |

Re-run as **`v13.0_background_n1000`** (`run_background_n1000.py`, 8,000 sims, random
placement, deterministic seeds, per-seed paired against the same placement at 0 fps,
bootstrap CI). Every physical parameter is unchanged; only those three things were fixed.

| rate | paper claimed | measured k=1 | measured k=4 |
|---|---|---|---|
| 200 fps | — | +1.42% [1.19, 1.65] | +0.66% [0.57, 0.75] |
| 500 fps | "under 1%" | **+3.46%** [3.12, 3.82] | +1.50% [1.37, 1.63] |
| 1000 fps | "about 2%" | **+6.65%** [6.24, 7.09] | +2.77% [2.62, 2.93] |

The Setup sentence was rewritten with these numbers. **A new positive result fell out of
the correction**: multi-flow damps background sensitivity by **2.4×** at the heaviest
rate (6.65% → 2.77%), so it buys robustness to diffuse load and not only speed. The same
stale claim was corrected in both sprint builders.

**(b) The controller dataset is now uniformly n=1000.** v5.7 fixed P=64; the static block
still held P=16 at n=100, and merging revealed P ∈ {4,8,32} as well. Both re-run
(`v5.8_static_af_p16_n1000`, 16,000 sims; `v5.9_static_af_smallP_n1000`, 48,000 sims) and
merged into **`v5.9_controller_all_n1000`**: 104 rows, ring sizes {4,8,16,32,64}, and
exactly one distinct `n_seeds` value — **1000**. The plotted P=64 series are unchanged
(2.028 / 2.462 / 2.146 / 2.844), so no paper number or figure moved; the point was that
a file named `all_n1000` must contain no n=100 cell.

### 5.7.1 The 10-agent precision audit that followed (2026-08-04)

Because the `\times` bug proved that *the verification checked the wrong property*, a
5-finder / 5-refuter fleet re-checked the whole chain against that generalisation
(number provenance, figure↔caption↔code, stale versions, script health, LaTeX render).
**24 findings.** What survived adversarial refutation, plus what I verified myself:

| finding | verdict |
|---|---|
| gap-closure caption said $64\%$; v11.1 gives **67.5%** | real — fixed to 68% |
| Table II caption said $6.5\times$ while its own body said $6.6\times$ | real — fixed |
| **controller caption claimed $n{=}1000$ for a curve that was $n{=}100$** | real — see below |
| duplicate `\label{eq:bstar}` made `\eqref` resolve to Jose's comment equation | real — his equation relabelled `eq:bstar-ns` (his words untouched) |
| empty `\cite{}` inside a `\jose{}` block = the BibTeX `""` warning | real — removed, prose untouched |
| an inserted comment left "in …, in each" (broken with `\commfalse`) | real — fixed |
| hand-typed `+11.7\%` in `build_ieee_eval_figs.py` | real — now computed from the plotted points |
| hand-typed `1.22×/2.02×` and `64.0%` in both sprint builders | real — now computed from `D.topology(8)` |
| "static k=4 at 50% rounds to 2.16 not 2.15" | **wrong** — 2.146 rounds to 2.15; the finder read the adaptive-block row (2.156), not the plotted static curve |
| "controller text says 2.06× but CSV says 2.00×" | refuted by the verifier (2.064 exists) — but it was the *n=100* row, which the re-run then replaced with 2.028 |

**The most valuable find, and the honest fix.** The controller figure plotted the
af=0.1 static curve from `v5.5`, whose rows for that load were still $n{=}100$, while
the caption said $n{=}1000$ for both static curves. Rather than soften the caption I
ran the missing arm — `experiments/run_static_af_n1000.py` → `v5.6_static_af_n1000`
(12,000 sims, af ∈ {0.0,0.1,0.3} at $n{=}1000$, identical constants and seed derivation
to `run_headline_n1000.py`) — and merged it into **`v5.7_controller_n1000`**, whose
entire $P{=}64$ block is now $n{=}1000$ (verified: 0 rows below it). The af=0.1 static
$k{=}4$ point moved **2.064 → 2.028**, and the story got *better*: the adaptive star
(2.034 at 131 QPs) now sits marginally **above** the static curve's 256-QP point, so
"matches static $k{=}4$ at half the queue-pairs" is literally true rather than
approximately. Paper numbers updated (2.06→2.03, 1.50→1.52).

**Compile is now Errors 0 / Warnings 0** — the first fully clean build.

**Figure redesign in the same pass** (the reader also found the figure hard to read,
and read the repeated "100 Gbps" row as a duplication):
* lanes are now labelled `flow 1 · 100 Gbps` … `flow 4 · 100 Gbps`, so the two
  100 Gbps rows read as two distinct sub-flows on two distinct paths;
* in-bar text is plain `1/4` vs `4/11 · 2/11 · 1/11 · 4/11` — exact, lighter, and
  **no mathtext at all**, which is why the file dropped 26,253 B → 2,846 B;
* panel titles shortened so they stop overflowing the 3.45in column;
* the caption gained the clause "(two of the four hashed onto distinct paths that
  happen to offer the same share)" so a reviewer cannot hit the same confusion.
4. **Phase-2 sync — DONE 2026-08-04.** `_data.py` now prefers v10.1 / v11.1 /
   `stage3_kstar_rule_n1000`, and `topology()` reads the same v10.1 rows (v10.0 was
   verified bit-identical to v9.0 at every shared k≤8 cell), so the sprint PDFs no
   longer put an n=100 table beside n=1000 ones; `flexible()` reads v11.1 for
   k ∈ {2,4,8,16} and only falls back to v12.0 for the k=32 arm. Both progress PDFs and
   the multiflow report rebuilt and checked for stale values (1.22/2.02/64.0%/6.52/6.45
   all gone; 1.28/2.05/67.5%/6.61 in). Tracker: **A.5 closed**, headline row
   2.47× → **2.844× CI[2.815,2.871]**, F.4/F.5 marked *not submitted — new venue*, new
   phase **G** with G.1 (n=1000 re-runs), G.2 (this audit), G.3 (the formalization);
   TASKS.html regenerated and diffed against the JSON (0 tasks missing). The IND-2026
   module 0.D.4 keeps its 2.47× as a historical record, now annotated as superseded.
   STATUS.md banner corrected to 2.844× with the reason. `analyze_v5.py` default tag
   → v5.3 (placement-fixed), `build_congestion_report.py` docstring → v6.2-preferred,
   `build_multiflow_report.py` → n=1000 k* figure + corrected reference string, and
   SUPERSEDED banners added to both n=100 stage READMEs.
5. **Comment cleanup phase 2** — the kept `\JY`s await Jose's review; C2 (undirect) and the
   abstract pivot are his decisions.

---

# APPENDIX — full comment thread, archived verbatim before deletion (2026-08-05)

## ID namespaces — read before using the appendix

The appendix IDs below are **snapshot-local**: they number all blocks present in the
2026-08-05 archive. Current work uses the stable LIVE IDs in `PROJECT_STATE.md` and
`OVERLEAF_WORKFLOW.md`. Equal numbers across the two namespaces do not necessarily name
the same block; never renumber the archive. This mapping covers every current LIVE block
and the two LIVE blocks retired on 2026-08-06:

| current stable ID | appendix snapshot ID | subject / status |
|---|---|---|
| `JY#1` | `JY#2` | directed/undirected — LIVE |
| `JY#2` | `JY#3` | define Fat-Tree first — retired 2026-08-06 |
| `JY#3` | `JY#4` | no-split case — LIVE |
| `JY#4` | `JY#5` | byte split / QP cap — LIVE |
| `JY#5` | `JY#6` | placement / path length — LIVE |
| `JY#6` | `JY#7` | algorithm and split methods — LIVE |
| `JY#7` | `JY#8` | physical worker allocation — LIVE |
| `JY#8` | `JY#9` | dashed lines — retired 2026-08-06 |
| `JY#9` | `JY#10` | related work — LIVE |
| `IH#1` | `IH#2` | directed-capacity reply — LIVE |
| `IH#2` | `IH#5` | placement / path-length reply — LIVE |
| `IH#3` | — | Ethereal read note — LIVE; added after the 2026-08-05 snapshot |
| `jose#1` | `jose#4` | alternative introduction paragraph — LIVE |

All **25** comment blocks as they stood in the live Overleaf source at the moment of
archiving (`paper_infocom.tex`, 48,069 bytes). Jose's wording is reproduced exactly, typos included.
This exists so that deleting a block from the `.tex` never destroys the record of what
was asked and what answered it.

| macro | count |
|---|---|
| `\JY` | 10 |
| `\jose` | 8 |
| `\IH` | 7 |
| `\MC` | 0 |

## `\JY` — Jose Yallouz — his ask (10 blocks)

### JY#1 — source line 168 (96 chars)

*Attached to:* …}

> Ibrahem please complete the contributions and add to the introduction the toy example we discuss

### JY#2 — source line 219 (15 chars)

*Attached to:* …\section{System Model and Problem Formulation}\label{sec:model}

> maybe undirect?

### JY#3 — source line 241 (43 chars)

*Attached to:* …(start of section)

> maybe better to defune a FT topology first?

### JY#4 — source line 262 (201 chars)

*Attached to:* …Equal splitting fixes $b_{e,j}=(M/P)/k_e$; Section~\ref{sec:design} chooses $b_e$ from measured rates.

> Consider also the definition of worstcase where we are not allowed to split the traffic: \begin{equation*} \Bstar_{\mathrm{ns}}(k) = \min_{l \in \text{ring}} \max_{1\le i\le k} f_i(l), \end{equation*}

### JY#5 — source line 327 (181 chars)

*Attached to:* …(start of section)

> I am not sure this is the right question to ask. 1) byte slpit is not defined 2) what do you mean by QP budget? Maybe you want to bound the number of flows in each link ring by $K$

### JY#6 — source line 371 (344 chars)

*Attached to:* …centralized re-routing~\cite{hedera}; we instead spread one logical flow at the endpoint and analyze it in closed form.

> I was thinking that the probability for a collision depends on the workers location in the Fat Tree: 1) In case they are in the same rack - ECMP does not help 2) in case they are in the same POD $m=R/2$ but the path length is 2 links 3) in case they are in the same POD $m=(R/2)^2$ but the path length is 4 links We migth model it somehow ...

### JY#7 — source line 388 (244 chars)

*Attached to:* …\section{Design}\label{sec:design}

> Rewrite the section explaining your algorithmic approach defining split methods and so on: I think there is also importance on how the message is split among the different flows. Maybe we need to define an all-reduce algorithm for this purpose

### JY#8 — source line 484 (86 chars)

*Attached to:* …n here). Oversubscription is modeled by reducing aggregation--core capacity while preserving all equal-cost paths ($m$ unchanged), isolating capacity from path diversity.

> I am missing some information about the allocation method in the physical nodes of FT.

### JY#9 — source line 526 (35 chars)

*Attached to:* …\end{figure}

> What are the dashed lines in graph?

### JY#10 — source line 616 (208 chars)

*Attached to:* …\section{Related Work}\label{sec:related}

> You need a much more extensive relate work most of the cited works are from more than 10 years ago. Please revise all the papers in the following conference in the 5 last years: 1) Infocom 2) Sigcomm 3) NSDI


## `\jose` — Jose Yallouz — prose he drafted (8 blocks)

### jose#1 — source line 90 (1,587 chars)

*Attached to:* …(start of section)

> As AI model sizes scale exponentially, the speed of distributed neural network training hinges on the performance of collective communication—specifically All-Reduce, which usually synchronizes gradients across thousands of GPUs through ring communication algorithm. Because a ring's throughput is strictly bounded by its single slowest link, network stragglers directly translate to idle computing and inflated training costs. On modern data-center fabrics utilizing Equal-Cost Multi-Path (ECMP) routing, each ring edge is hashed to a single physical path, causing a single congested switch to bottleneck the entire AI training run while parallel, equal-cost paths remain underutilized. To restore network balance and accelerate training, we open $k$ parallel RDMA flows per ring edge, leveraging ECMP to distribute traffic across disjoint paths and bypass hot spots. Addressing how many flows to open and how to divide message traffic, we model ring completion times, analyze multi-path hash distribution, and evaluate performance using extensive flow-level simulations. We show that throughput-proportional byte splitting consistently outperforms uniform splitting, achieving peak performance at roughly half the available queue-pairs on highly constrained fabrics. Ultimately, this multi-flow approach reduces collective completion time by up to 2.84× under targeted congestion and maps directly onto native multi-queue-pair knobs in NCCL, offering an immediately deployable performance boost for production AI clusters without requiring changes to the collective algorithm itself.

### jose#2 — source line 109 (1,065 chars)

*Attached to:* …collective runs no faster than its single slowest edge.

> The explosive growth of large language models and foundation AI has shifted data-center traffic workloads, making distributed machine learning (ML) training the dominant consumer of fabric bandwidth. Unlike traditional web applications characterized by bursty, independent flows, distributed AI workloads generate tightly coupled, collective communication patterns that saturate core network links for prolonged durations. In these workloads, collective communication operations consume a large and rapidly growing fraction of total execution time~\cite{ncclx}. Among these, Ring All-Reduce remains the quintessential workhorse for gradient synchronization: it achieves theoretical bandwidth optimality for large tensor payloads~\cite{thakur} and forms the core runtime engine of production libraries like NVIDIA NCCL. Executing a Ring All-Reduce across $P$ workers requires $2(P{-}1)$ tightly synchronized transfer steps along the ring edges. Consequently, the progress of the entire training job is strictly bounded by the throughput of its single slowest link.

### jose#3 — source line 123 (1,082 chars)

*Attached to:* …(Section~\ref{sec:related}).

> Modern data-center fabrics employ multi-path topologies such as Fat-Trees~\cite{fattree} that relies on Equal-Cost Multi-Path (ECMP) routing to balance traffic. To preserve packet ordering, ECMP statically maps each flow's 5-tuple hash to a single physical path, oblivious to real-time network load~\cite{rfc2992}. When a ring edge is mapped to a single RDMA flow, it becomes pinned to one fixed route. As a result, a single congested or oversubscribed switch along that route bottlenecks the entire collective—even while dozens of parallel, equal-cost paths within the fabric sit completely idle. Indeed, recent measurements demonstrate that single-flow utilization degrades sharply as ring sizes scale~\cite{zong2025ibing}. While hardware-level adaptive routing or packet spraying can spread a single flow across paths, these methods entail complex demands of packet reordering. In this work, we explicitly target standard, widely deployed fabrics where ECMP pins static paths per connection; advanced hardware routing mechanisms remain complementary (Section~\ref{sec:related}).

### jose#4 — source line 164 (670 chars)

*Attached to:* …(start of section)

> In this paper, we propose opening $k$ parallel RDMA flows per ring link, each assigned a distinct 5-tuple, allowing ECMP to naturally disperse the edge's traffic across disjoint physical paths, making the effective link bandwidth the aggregate sum of all active sub-paths. Crucially, this approach preserves the logical ring topology—avoiding complex topological reconfigurations~\cite{zong2025ibing}—while raising the collective's bottleneck bandwidth by up to $2.84\times$ under targeted network congestion. Remarkably, this can be achieved entirely through the native multi-queue-pair (multi-QP) configuration knobs already exposed by production runtimes like NCCL.

### jose#5 — source line 173 (819 chars)

*Attached to:* …\section{Background and Motivation}\label{sec:bg}

> A standard Fat-Tree data center topology built with radix-$r$ switches provides rich path diversity to support large-scale distributed training traffic \cite{fattree}. Specifically, between any two given hosts, the architecture exposes one intra-rack path, $r/2$ intra-pod paths, and $(r/2)^2$ cross-pod paths. To utilize these multi-path topologies without per-packet reordering overheads, Equal-Cost Multi-Path (ECMP) routing is universally deployed, hashing transport flows deterministically based on standard packet header fields (such as 5-tuples) \cite{rfc2992}. However, deterministic hashing under large-scale workloads frequently causes hash collisions and severe traffic unbalance, leaving certain paths heavily congested while other paths remain underutilized \cite{greenberg2009vl2, kandula2009detailed}.

### jose#6 — source line 181 (1,906 chars)

*Attached to:* …(start of section)

> While there are several algorithms available for implementing the all-reduce collective, the ring algorithm is \textit{throughput-optimal}, thus optimizing the performance of large message communication. The ring algorithm achieves this optimal throughput by transforming the global communication problem into a pipeline of localized point-to-point connection transfers. Instead of forcing nodes to broadcast data to everyone simultaneously—which quickly congests network switches and hits bandwidth bottlenecks—the ring topology organizes workers into a logical circle where each node communicates exclusively with its immediate neighbour. During this process, data of size $M$ is divided into $P$ equal chunks. By splitting the operation into a reduce-scatter phase followed by an all-gather phase, every network link in the ring is kept continuously busy transferring chunks of size $M/P$. This design fully saturates the available bidirectional bandwidth regardless of the worker count $P$, ensuring that the communication time depends only on the size of the message and the capacity of the slowest bottleneck link rather than scaling poorly with cluster size. Distributed deep learning frameworks heavily rely on the ring all-reduce collective communication primitive to synchronize gradient updates efficiently across $P$ participating workers\cite{sergeev2018horovod}. The standard ring implementation divides the process into $2(P-1)$ discrete steps, split evenly into a reduce-scatter phase followed by an all-gather phase \cite{thakur}. During every step, each node transfers a fixed chunk of $M/P$ bytes across its designated ring edge. Assuming uniform link capacities, the total execution time is analytically modeled as $T \approx 2(P-1)(M/P)/\Bstar$, where $\Bstar$ denotes the effective throughput of the slowest bottleneck connection link in the ring topology\cite{wang2020overlapping}.

### jose#7 — source line 188 (978 chars)

*Attached to:* …%\textbf{Multiple queue-pairs in practice.}

> High-performance data center stacks and RDMA architectures expose mechanisms to configure multiple parallel RDMA queue-pairs (QPs) per connection, enabling transport-layer striping across independent hardware contexts \cite{infiniband2015specification}. For instance, NVIDIA's Collective Communications Library (NCCL) implements this functionality via two configuration parameters, namely \textit{NCCL\_IB\_QPS\_PER\_CONNECTION} and \textit{NCCL\_IB\_SPLIT\_DATA\_ON\_QPS} \cite{nvidia2023nccl}. By default, the latter splits data bytes \emph{equally} across the available QPs, serving as a standard baseline; shifting from an equal split to a load-aware proportional split represents a natural and vital performance enhancement. Consequently, evaluating collective performance under realistic, congested data-center fabrics—rather than idealized, idle supercomputer environments—is essential to capturing the true benefits of fine-grained multi-path transport coordination .

### jose#8 — source line 237 (36 chars)

*Attached to:* …edge with its own capacity $c_e$. Host and ToR links carry the line rate $c$; oversubscription reduces aggregation--core capacities (Section~\ref{sec:eval}).

> all-reduce collective implementation


## `\IH` — our reply (7 blocks)

### IH#1 — source line 93 (339 chars)

*Attached to:* …-queue-pair knobs in NCCL, offering an immediately deployable performance boost for production AI clusters without requiring changes to the collective algorithm itself. }

> Repositioned: Meta ships QP-scaling and Ethereal publishes the same knob, so the abstract now leads with what stays ours --- the $k^\ast$ rule, the proportional split, the controller --- and shows the honest regime spread ($1.25$--$1.33\times$ unstructured vs $2.8$--$3.1\times$ persistent). Your hedges are kept. Please confirm the pivot.

### IH#2 — source line 219 (1,199 chars)

*Attached to:* …\section{System Model and Problem Formulation}\label{sec:model}

> I checked the convention rather than argue it. Papers that describe only the wiring do use undirected language, but every one I could verify that tracks \emph{capacity} uses a directed graph with one edge per direction: Hedera (NSDI'10), ``a network graph with directed edges. Each edge has a fixed capacity''; Jellyfish (NSDI'12), ``each network cable is considered as two links, one for each direction''; B4 (SIGCOMM'13), which reports its live topology in unidirectional edges; and, closest to us, Zhao et al.\ (NSDI'25) on collectives, ``modeled as a directed graph (digraph)''. Hedera in fact uses both: undirected for the wiring, directed once capacity enters. The reason matters here --- an undirected edge with a single shared capacity would impose forward plus reverse at most $c$, whereas the hardware allows $c$ each way, so it would understate any link the collective uses in both directions by up to a factor of two. I have kept ``directed'' and stated the full-duplex convention explicitly in the sentence above; that sentence is the real fix and is needed under either notation. Happy to switch to undirected if you prefer the look, as long as the per-direction capacity stays stated.

### IH#3 — source line 318 (439 chars)

*Attached to:* …$4{:}1$ fabric at $P{=}64$ it reproduces the measured equal-split gap at $k{=}8$ to within $0.3$ points ($67.2\%$ predicted vs.\ $67.5\%$ measured).

> Your no-split case is in Proposition~\ref{prop:spread} as the third regime. One correction to my own earlier reply: $\min_l\max_i f_i$ is the \emph{best} single sub-flow, so it is an oracle ceiling rather than a worst case --- under ECMP the flow cannot choose its path. It is worth stating because equal splitting falls below even that ceiling in only $16$ of $40{,}000$ configurations, i.e.\ the equal default is already doing real work.

### IH#4 — source line 336 (300 chars)

*Attached to:* …inner split is solved in closed form by Proposition~\ref{prop:spread}, and the outer choice of $\mathbf{k}$ is what the rest of the paper addresses.

> Adopted your reformulation, and went further: the objective now contains $b_e$, so equal and proportional splitting are two distinct feasible points rather than the same one. Your ``is this the right question'' was the real issue --- the old objective was constant in the split it asked us to choose.

### IH#5 — source line 376 (434 chars)

*Attached to:* …3) in case they are in the same POD $m=(R/2)^2$ but the path length is 4 links We migth model it somehow ...

> The placement half is now in the model text just above (same rack $m{=}1$, cross-pod $95\%$, same-pod $66\%$ at $k{=}8$). The path-length half of your question we do not model: hop count enters our results only through the fair-share rates $f_{e,j}$, not as a separate term, so we cannot say anything about $2$ versus $4$ links beyond what the rates already carry. Tell us if you want that made explicit --- it would need a new sweep.

### IH#6 — source line 484 (223 chars)

*Attached to:* …n here). Oversubscription is modeled by reducing aggregation--core capacity while preserving all equal-cost paths ($m$ unchanged), isolating capacity from path diversity.

> For each seed the $P$ workers are chosen uniformly at random among the hosts, and the same placement is reused on every fabric so the comparison is paired. Now also stated in Setup, with a placement-sensitivity measurement.

### IH#7 — source line 620 (210 chars)

*Attached to:* …2) Sigcomm 3) NSDI

> Rewritten below: thirteen venue-verified additions (SIGCOMM'23/'24, NSDI'18/'21, INFOCOM'25, EuroSys'26, OSDI'26, NAIC'24), every entry read at its primary page; Hedera and MPTCP kept as acknowledged ancestors.

---

# Retired 2026-08-05 — abstract and contributions, closed on our own authority

Ibrahem's standing instruction: *we do not wait for sign-off; every comment is our
responsibility to resolve fully and then clear.* A block is retired once the decision is
made, the wording is correct, and the reasoning is recorded here. Every retired block's
full text is preserved verbatim in the appendix above, and in the Overleaf git history.

## `\jose#1` — Jose's complete alternative abstract (1,587 chars)

Not a question and not an enrichment: a full counter-proposal, written end to end.
Resolved as **adopt the substance, reject the framing**.

| Jose's clause | disposition |
|---|---|
| training hinges on ring All-Reduce | ADOPTED — opening sentence |
| throughput bounded by the single slowest link | ADOPTED — verbatim in effect |
| ECMP hashes each edge to one path; a congested switch bottlenecks everything while equal-cost paths are underutilised | ADOPTED — near-verbatim ("…sit idle") |
| "**we open** $k$ parallel RDMA flows … to restore network balance" | **REJECTED (framing)** — Meta already ships QP-scaling and Ethereal publishes the same knob. Presenting the mechanism as our proposal invites "this already exists". Reframed: the mechanism is the production response; **ours is the rule** — $k^\ast$, the proportional split, the controller |
| how many flows / how to divide | ADOPTED — "We answer both" |
| model + hash analysis + flow-level simulation | ADOPTED — closed form, $1.6\%$, the $k$-sweep |
| proportional consistently beats uniform | ADOPTED and strengthened — "never loses in any of $32{,}000$ paired configurations" |
| peak at roughly half the queue-pairs | ADOPTED and sharpened — $11.7\%$ at half the flows |
| "across **disjoint** paths" | **REJECTED (incorrect)** — our measured $\hat m(k)=m(1-(1-1/m)^k)$, validated to $1.6\%$, shows collisions are first-order. Quantifying them *is* contribution (i); adopting "disjoint" would contradict our own model |
| "up to $2.84\times$ **under targeted congestion**" | **REJECTED (mislabelled)** — $2.84\times$ is the on/off headline cell (P=64, k=8, af=0.5, v5.4). The targeted maximum is $3.05\times$ (hot spot, v6.2). The identical phrasing was corrected in our Conclusion the same day |
| NCCL knobs, no change to the collective | ADOPTED — closing sentence |

His hedges were deliberately kept, and his motivational opening shaped §I rather than
being discarded. Nothing he wrote is lost.

## `\IH#1` — our reply asking him to confirm the pivot

Retired with it. The pivot is now an author decision, made on the evidence above and
recorded here; the commit message states it so it is visible in Overleaf's history.

## `\JY#1` — *"complete the contributions and add to the introduction the toy example"*

Both delivered and verified in the **submission** build (not merely behind a comment
macro): the three-item contribution list closes §I, and the toy example is the paragraph
above it. Each contribution was traced to the section that develops it, and every number
in the toy re-derived. Retired.

## Final wording pass applied to the abstract at the same time

* "a property of the fabric" → "set by the fabric **and by the workers' placement**" — the
  $95\%$/$66\%$ contrast is a placement effect, exactly as §III states; the old phrasing
  supported a fabric claim with a placement example.
* "the simulator's ECMP hash" → "**our flow-level** simulator's ECMP hash" — the abstract
  never said the results were simulated.
* Two over-long sentences split at a full stop, so the abstract now ends on the
  deployability claim rather than burying it in a subordinate clause.

**Remaining in the paper: `\JY` 7 · `\IH` 3 · `\jose` 1** (the third `\IH`, added later
the same day, is the Ethereal-read note at Related Work) — all genuinely undecided
(directed vs undirected, path length, and so on), each the
subject of a later sprint.

## Retired 2026-08-06 — JY (dashed lines)

Jose's comment, verbatim:

> What are the dashed lines in graph?

Retired after direct verification in both places where the answer must live. The
`fig:saturation` caption states “Solid: realised; dashed: the optimal-split bound
over the same hashed paths.” The rendered figure legend states “optimal-split bound
(dashed, fabric colour)”.

## Retired 2026-08-06 — JY (define Fat-Tree topology)

Jose's comment, verbatim:

> maybe better to defune a FT topology first?

Retired after the topology definition was completed before Paths and ECMP and
checked directly against `sim.py::FatTree` and `validation/validate_topology.py`.
The three-tier definition now states the pod structure, host count, path counts,
and capacity-only oversubscription; the two-tier leaf-spine is defined separately.

Jose's comment also exposed a real reporting imprecision in the evaluation setup:
the prose had applied “1024 hosts” and “the same placement ... across every fabric”
to the two-tier fabric. The production drivers had already done the correct thing:
`run_k_saturation_n1000.py` and `run_flexible_split_n1000.py` sample the three-tier
ring from 1024 hosts and the two-tier ring from its own 128-host population. This
was therefore a description-only correction to the paper; the frozen data and
methodology were correct, and no experiment was rerun or altered. Credit to Jose's
review for revealing the discrepancy.

## Retired 2026-08-06 — JY/IH (directed or undirected fabric)

Jose's comment, verbatim:

> maybe undirect?

The directed representation is retained and clarified. The physical fabric now uses
$G=(V,\mathcal{L})$: each full-duplex physical link contributes two directed arcs
$\ell\in\mathcal{L}$, one per direction, with a separate capacity constraint $c_\ell$.
The logical collective is named separately as a directed ring whose edges use $e$, so
physical-link capacity notation no longer collides with $k_e$, $b_e$, $f_{e,j}$, or
$\tau_e$ downstream.

This is a description-only correction of the representation already implemented in
`sim.py`: topology arcs, ECMP paths, congestion state, and contention accounting are all
keyed by ordered node pairs, and every physical connection is installed once in each
direction. No experiment was rerun and no frozen result changed. The accompanying `\IH`
reply was retired with the question; its literature survey remains preserved verbatim in
the appendix, but its universal claims were not copied into the paper.

Scope boundary: this retirement verifies only the per-direction graph representation. It
does not certify the separate `max-min` label used elsewhere. The allocator audit opened
during this sprint remains an independent gate, with no change yet to `sim.py`, frozen
data, or the paper's `max-min` wording.

**Remaining in the paper after this retirement: `\JY` 6 · `\IH` 2 · `\jose` 1.**

## Rate-model correction — 2026-08-06

Historical uses of “max-min,” “fair-share,” “optimal-split bound,” and “ceiling” in
this ledger are preserved as the record of what was believed and reviewed at the time.
The allocator audit established that every frozen campaign used the **link-local
equal-share bottleneck-rate model**, not network-wide max-min. Legacy
`compute_ring_theoretical_time`/`opt_time` values are static full-concurrency local-model
proportional-split references over the same hashed paths, not global ceilings for the
dynamic proportional runner. The C16/JY#8 retirement remains valid as a legibility
decision; Unit 2A corrects the name shown in the caption and rendered legend. See
`MAXMIN_RATE_MODEL_GATE_2026-08-06.md` and `RATE_MODEL_REVALIDATION_LOG_2026-08-06.md`.

## Retired 2026-08-06 — JY (no-split comparator)

Jose's comment, verbatim:

> Consider also the definition of worstcase where we are not allowed to split the traffic:
> \[
> \Bstar_{\mathrm{ns}}(k) = \min_{l \in \text{ring}} \max_{1\le i\le k} f_i(l).
> \]

The comment exposed a real presentation gap: Proposition 1 already bounded the
best single-subflow allocation for one ring edge, but the paper did not name the
corresponding ring-level comparator. The body now defines
`\Bstar_{\mathrm{ns}}(\mathbf{k},h)` as the minimum across ring edges of the
fastest hashed candidate in the same frozen full-concurrency rate snapshot.

The word “worstcase” was not retained because the maximum over sub-flows assumes
an oracle that observes the hash realization and selects the fastest candidate.
The new text therefore identifies it as a best-single-subflow oracle reference,
not a worst-case guarantee and not a rerun with one queue pair. This is a direct
consequence of Proposition 1 and the ring-time equation; no experiment was rerun
and no frozen result changed. Credit to Jose for prompting the missing distinction.

**Remaining in the paper after this retirement: `\JY` 5 · `\IH` 2 · `\jose` 1.**

## Retired 2026-08-06 — JY (byte split and queue-pair cap)

Jose's comment, verbatim:

> I am not sure this is the right question to ask. 1) byte slpit is not defined
> 2) what do you mean by QP budget? Maybe you want to bound the number of flows
> in each link ring by K

Jose identified two genuine ambiguities. The paper now defines
`\mathbf{b}=(b_e)_e` before the collective-time equation and states the feasible
split vector immediately after the multi-flow model. The problem formulation now
distinguishes the static decision `k_e` made before the ECMP realization from the
rate-informed split rule `b_e(h)`, and bounds every ring edge by NCCL's
per-connection cap `1 <= k_e <= K <= 128`.

The paper reports `\sum_e k_e` as a resource cost; it does not impose that sum as
a global budget. Proposition 1 solves the inner fixed-snapshot split, while the
outer static flow-count choice and the online controller remain separate. These
are formal description corrections only; no experiment was rerun and no frozen
result changed.

**Remaining in the paper after this retirement: `\JY` 4 · `\IH` 2 · `\jose` 1.**

## Retired 2026-08-06 — JY/IH (placement and path length)

Jose's comment, verbatim:

> I was thinking that the probability for a collision depends on the workers
> location in the Fat Tree: 1) In case they are in the same rack - ECMP does not
> help; 2) in case they are in the same POD m=R/2 but the path length is 2 links;
> 3) in case they are in the same POD m=(R/2)^2 but the path length is 4 links.
> We migth model it somehow ...

The accompanying IH reply is preserved verbatim in the comment inventory above.
The placement part is now explicit in the body: same-ToR pairs have `m=1`,
same-pod pairs have `m=r/2`, and cross-pod pairs have `m=(r/2)^2`. The third
case in the live comment said “same POD,” but the topology and the intended path
count show that it is the cross-pod case.

The path-length part is closed as a scope statement, not as a fabricated result.
`sim.py` assigns each flow the minimum local share across all directed arcs on
its path and advances bytes as rate times tick; it has no separate propagation
or switching-latency term per hop. The paper now states exactly that. No new
sweep is required for this description. A future quantitative claim isolating
the latency effect of two versus four switch-to-switch hops would require a
dedicated experiment that holds path diversity and capacity fixed.

**Remaining in the paper after this retirement: `\JY` 3 · `\IH` 1 · `\jose` 1.**

## Retired 2026-08-06 — JY (algorithm and split methods)

Jose's comment, verbatim:

> Rewrite the section explaining your algorithmic approach defining split
> methods and so on: I think there is also importance on how the message is
> split among the different flows. Maybe we need to define an all-reduce
> algorithm for this purpose.

The Design section now separates the two decisions explicitly. It first defines
the offline `k*` rule on the tested doubling grid, using the mean paired
completion-time gain for the current and every later doubling. It then defines
equal and measured-rate-proportional byte allocation across the selected flows.
The Ring All-Reduce reduce-scatter/all-gather schedule is stated to remain
unchanged; Algorithm 1 is the sender-side operation applied independently to
each active directed ring edge.

Jose's request also exposed stale dynamic wording in the algorithm caption. The
simulator recomputes bottleneck rates every tick as active flows and residual
capacity change, and the proportional policy reallocates after the first tick
and every window. The paper now says this instead of claiming that allocation
settles after the first window. Optimality is scoped to the fixed
full-concurrency rate snapshot proved in Proposition 1. These changes organize
and correct the description only; no frozen result changed and no experiment
was rerun.

**Remaining in the paper after this retirement: `\JY` 2 · `\IH` 1 · `\jose` 1.**

## Retired 2026-08-06 — JY (physical worker allocation)

Jose's comment, verbatim:

> I am missing some information about the allocation method in the physical
> nodes of FT.

The Setup now specifies the complete mapping used by the production drivers. For
each seed and topology, hosts are sampled uniformly without replacement, one
worker is assigned to every sampled host, and the seeded sample order defines
the directed ring including its wrap-around edge. Distinct 5-tuples for each
logical ring edge are then mapped by ECMP to that host pair's equal-cost paths.

The three three-tier capacity variants reuse the same sampled 1024-host ring. The
two-tier fabric is sampled separately from its own 128-host population with the
same seed. Within each fabric, the ring is held fixed across all `k` values and
both split policies, preserving per-seed pairing. This description is verified
against `run_k_saturation_n1000.py`, `run_flexible_split_n1000.py`, and the ECMP
path construction in `sim.py`; no data or methodology changed.

**Remaining in the paper after this retirement: `\JY` 1 · `\IH` 1 · `\jose` 1.**

## Retired 2026-08-06 — JY/IH (Related Work and Ethereal positioning)

Jose's comment, verbatim:

> You need a much more extensive relate work most of the cited works are from
> more than 10 years ago. Please revise all the papers in the following
> conference in the 5 last years: 1) Infocom 2) Sigcomm 3) NSDI.

The accompanying Ethereal read note remains preserved verbatim in the inventory
above. Its three blocking findings are now resolved in active prose. The Related
Work section cites recent production, transport, fabric, and collective systems
from the requested venue families, and it now makes the closest comparison
explicit: Ethereal's MP-RDMA-x is an ECMP sub-flow baseline matching our deployed
multi-QP mechanism, so the paper does not claim the mechanism itself as new.

The paper instead locates the contribution in hash occupancy under stock ECMP,
regime-specific selection of `k`, and measured-rate byte allocation. It also
addresses Ethereal's reported ring null result without dismissing it: that result
comes from evaluated 1:1 fabrics without injected contention and is consistent
with our smallest non-blocking result; our larger gains occur when path rates
become heterogeneous under oversubscription or concentrated contention. The
text also records that Ethereal handles link failures, which remain outside our
scope. These statements were verified against the pinned Ethereal v2 PDF in
`paper/refs`; no experiment or frozen result changed.

**Remaining in the paper after this retirement: `\JY` 0 · `\IH` 0 · `\jose` 1.**

## Retired 2026-08-06 — jose (alternative introduction paragraph)

Jose's proposed paragraph is preserved verbatim in the inventory above. Its
valid ideas are already present in the active Introduction: distinct 5-tuples
raise ECMP entropy, the logical ring is unchanged, the headline result is
reported, and production runtimes expose multi-QP controls.

The draft itself was not copied because four clauses are no longer defensible.
“We propose opening k” would present a deployed mechanism and Ethereal's
MP-RDMA-x baseline as our invention; “disjoint physical paths” is contradicted by
the ECMP collisions modeled in Section III; aggregate path rates require the
fixed-snapshot and shared-link qualifications now stated in Proposition 1; and
the measured-rate splitter is sender-side scheduling, not merely an existing
NCCL environment knob. The promotional adverb “Remarkably” was also omitted.

This retirement follows the Related Work correction, so the paper now preserves
the idea while locating novelty in the occupancy model, `k*` rule,
measured-rate byte allocation, and selective controller. No empirical claim or
frozen result changed.

**Remaining in the paper after this retirement: `\JY` 0 · `\IH` 0 · `\jose` 0.**

## Source-status correction — 2026-08-06 (Ethereal)

The Related Work retirement above records what was learned from the pinned
Ethereal v2 manuscript; it is not a conference-publication record. A fresh
public-source check on 2026-08-06 found arXiv:2407.00550 only: v1 was submitted
on 30 June 2024 as *Challenging the Need for Packet Spraying in Large-Scale
Distributed Training*, and v2 was posted on 25 February 2025 under the Ethereal
title with the comment “Extended version.” The authors' public group page lists
Ethereal under **Tech Reports / arXiv** (CoRR), not under conference or workshop
proceedings. No publicly documented conference publication was found; nothing
here infers whether a private submission or review process exists.

Per Ibrahem's source policy, Ethereal may be used as a learning and comparison
reference but must not be the evidentiary anchor for a paper claim. The current
BibTeX therefore names only the arXiv preprint and no venue. The active
Introduction/Related Work citations remain a documented future source-review
hold: independently corroborate, replace, or remove any claim that would
otherwise depend on this preprint before submission. This correction does not
rewrite the historical retirement above.
