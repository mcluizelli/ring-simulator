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
