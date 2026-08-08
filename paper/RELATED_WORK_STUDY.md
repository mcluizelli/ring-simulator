# Related work we must read properly, not just cite

**Opened 2026-08-05.** This file exists because a positioning paragraph was being written
from an internal summary rather than from the papers themselves. The point of reading
these is **to learn from them and to sharpen what we propose** — not to find grounds for
dismissing them. Several of these authors are plausible reviewers; all of them are doing
serious work on a problem adjacent to ours.

Rule that follows from that: **no characterisation of another paper's thesis, scope or
limitations goes into ours until someone has read the paper end to end and recorded it
here.** Until then, either say nothing about it, or keep the claim inside an `\IH{}`
comment where it is visibly ours and unpublished.

---

## 1. Ethereal — the closest prior work · PRIORITY

Addanki, Goyal, Marinos, Schmid. *Ethereal: Divide and Conquer Network Load Balancing in
Large-Scale Distributed Training.* arXiv:2407.00550**v2** (25 Feb 2025); the id 2407.00550 first appeared in 2024.
Local copy: `paper/refs/ethereal_2407.00550v2.pdf` (15 pp; gitignored — not ours to
redistribute).

### Status: **READ END TO END, 2026-08-05.** All five questions answered below.

### Answers to the five questions

**1 · How does it size the pieces? EQUAL BYTES.** Proof of Theorem 1, p.5:
> *"ALG splits each of the r flows into s/g flows, **each of size f₁·g/s**, and assigns
> r/g (an integer) flows of size f₁·g/s to each uplink."*

The size is a function of `s` (spines) and `g = gcd(r,s)` only. Whole-document search:
`proportion` 0, `throughput` 0, `fair share` 0, `heterogen` 0, `capacit` 1 (an *input* at
initialisation, p.6, never in a sizing expression). Their uniformity is uniformity over
paths they **choose** and can therefore assume equivalent.

**Consequence for our contribution (iii): it survives, and is now stateable precisely.**
Ethereal equalises *bytes* across paths it selects and treats as homogeneous. We cannot
select paths, ours are heterogeneous in realised rate, and we equalise *finishing times*
`b_j/f_j`. Different objective, different regime — but we must stop implying they split
without a principle.

**2 · Do they cover ring All-Reduce? YES — and report no benefit for it.** p.8:
> *"For ring and double binary tree, we observe similar performance under any
> load-balancing algorithm … ring algorithm inherently has a uniform distribution of
> traffic over disjoint paths in a leaf-spine topology."*

Repeated for their fat-tree in the Fig. 4 caption, p.10, so "that was only leaf-spine" is
**not** an adequate answer. Message sizes 4–256 MB, i.e. our range. **This is the single
most important sentence in their paper for us and the paper must address it.** The
defensible answer is regime, not error: their fabrics are 1:1 and carry no injected
contention, and their null result is consistent with our own smallest numbers.

**3 · Evaluation topologies.** p.8: leaf-spine, 256 GPUs, 16 ToR + 16 spine; fat-tree,
512 GPUs, 32 ToR + 32 spine + 16 core; every switch 32×400 Gbps; NIC 400 Gbps; 500 ns
link latency; Astra-Sim. Derived from the port counts (they never state a ratio):
**1:1 at every tier in both topologies.** Their whole steady-state evaluation is in the
hash-constrained regime — the complement of ours.

**4 · Capacity-constrained fabrics under another name? NO.** Nothing in the setup or the
evaluation varies tier capacity. The only perturbation studied is a link failure.

**5 · What to adopt from them.**
* Their observation (iii) — *"the completion time of a collective is more critical than
  individual flow completion times"* — is the principle behind our Proposition 1, stated
  more crisply than we state it. Worth adopting with credit.
* **Their disclaimer is our best positioning**, p.5, immediately after the proof:
  > *"We emphasize that the same result cannot be derived for hash-based ECMP since it
  > does not explicitly converge based on the number of flows, but rather on the entropy
  > of the input to the hash function, which is a non-trivial task to control in practice."*

  They set aside exactly the regime we address. This is more generous to them and
  stronger for us than any limitation we could assert.
* Their Theorem 1 pairs an equivalence result with a **minimality** result. Ours is a
  one-line max-ratio argument. We must never write "no prior work proves splitting
  optimality".

### ⚠ Exposure this read uncovered

**Their baseline `MP-RDMA-x` is our design point.** Table 1, p.3, classifies MP-RDMA as
*Sub-flow / ECMP / None*; p.8 defines the baseline as *"MP-RDMA-x, which splits every flow
by a factor of x"*, evaluated at x ∈ {2,4,8} including on ring. **Careful:** this is
Ethereal's simplified baseline, not the modified transport of Lu et al. (`lu2018mprdma`)
that our Related Work describes separately — do not conflate them. They also explain why
it underperforms *for their workloads* (p.9): *"the number of flows in recursive doubling
is extremely low to have sufficient entropy to ECMP even by splitting every flow"*, and
note MP-RDMA-8 holding >4000 queue pairs in all-to-all.

Consequence: **the mechanism cannot be presented as new.** Our novelty is `m̂(k)`, `k*`
and the proportional sizing. Their x tops out at 8; our sweep runs to 32 and beyond,
which is where regime-dependence appears.

### What was changed in the paper on the strength of this read
Two claims of ours were **false** and are now gone: *"neither derives how many flows a
fabric regime needs"* and *"reports the queue-pair counts … rather than a rule for
choosing them"*. They do derive a count and prove it minimal. Replaced with a positive
statement about what **we** add, plus a verbatim quotation of what they do. An `\IH{}`
note at the Related Work paragraph records the three items still to settle.

---

## 2. Others to read before the related-work section is final

### How the risk was scoped, so this list stays short
An audit of the rendered body found **22 distinct cite keys, 19 of which characterise
another paper** — they tell the reader what that work does. Those are not equally risky.
Three tiers:

* **Absence claims** — we say a paper does *not* do something. Highest risk: the Ethereal
  read produced two such claims of ours and **both were wrong**. Each needs its source.
* **Contrast claims** — *"All of these change switches, transports, or controllers; we
  change none"* over 5 keys, and the analogous sentence over 4 more. These say what
  *they* change, using canonical facts (Hedera = central controller, MPTCP = subflows at
  the transport). Low risk; leave them.
* **Provenance** (`fattree`, `ncclx`, `rfc2992`) — naming a technique. No risk.

So the requirement is **not** to read 19 papers. It is to hold no absence claim we have
not sourced. After the Ethereal read and the rewording of 2026-08-05, **the paper makes
no unverified absence claim**; the two that existed were replaced by positive statements
about what we add.

### PRIORITY — only needed if we want to reinstate a comparative claim

* **ParaLet** (`cao2024paralet`) — cited beside Ethereal as studying "the same knob …
  flowlets". We previously wrote that *neither* sizes the flow count; that half of the
  sentence is now removed. **Read before writing any comparative claim about it.**
  Question to answer: at what granularity does it split, and is the count derived from
  anything (flowlet gap? path count? load?).
* **UCCL** (`zhou2026uccltran`) — we previously wrote *"it, too, ships no sizing rule"*;
  that clause is now deleted. **Read before reinstating anything like it.** Question:
  does its multipathing choose a number of paths per collective flow, and how?

### Lower priority — the characterisation is short and conventional

* **Meta's RoCE fabric** (`gangidi2024rdma`) — cited for QP-scaling raising ECMP entropy.
  We should know exactly what they scale and to what, since we call it "the production
  response".
* **CAVER** (`deng2024caver`) — congestion-aware RDMA path selection. Our steering study
  (`reports/flexible_split/stage3_steering_headroom/`, n=30) speaks to it directly but is
  not in the paper.
* **iBing** (`zong2025ibing`) — cited both for single-flow utilisation degrading with ring
  size and as a bidirectional scheme that restructures the ring. Two distinct claims on
  one citation; verify both.


---

## 3. The differentiation study — understanding before positioning · PHASE D, stages 2–3

**Commissioned by Ibrahem, 2026-08-05.** His directive, which sets this task's bar: the
MP-RDMA finding must be *understood* first, and the outcome must make the paper stand on
its own research value — **not "a published baseline plus a tweak"**. There may be
further differences nobody has articulated yet; the agent who takes this task is expected
to understand and *find* them. Sequencing: runs **after** the section sprints (phase B) —
order and cleaning come first.

### Already established (verified 2026-08-05, sources in §1 — do not re-litigate)

* Ethereal's baseline `MP-RDMA-x` = *"splits every flow by a factor of x"* over stock
  ECMP, x ∈ {2,4,8}, no re-routing (their Table 1). That is our knob. They also explain
  why it underperforms *in their workloads* — too few flows for hash entropy — and note
  MP-RDMA-8 holding >4000 QPs in all-to-all.
* Their pieces are **equal bytes** over paths they **choose** and treat as homogeneous;
  ours are **rate-proportional** over paths the **hash** assigns, heterogeneous in
  realised rate. Different objective: equal demand per link vs equal finishing time
  (Prop. 1).
* Their x stops at 8; our sweep reaches 32+, where the regime-dependence appears. Their
  fabrics are 1:1 at every tier with no injected contention; our gains concentrate under
  oversubscription + contention.
* Their carve-out is our territory: *"the same result cannot be derived for hash-based
  ECMP…"* (p.5).
* **A third axis, verified but never articulated in our paper — the information model.**
  Their four observations exploit *static application knowledge* (flow sizes known on
  arrival, equal within a step). Our split exploits *measured network state* (fair-share
  rates at run time). Knowledge-driven vs measurement-driven division is an architectural
  difference, not a parameter difference.
* An honest gap on our side: they handle link failures (per-QP timeout, re-route); we do
  not address failures at all. Acknowledge it; do not hide it.

### The five questions — each answered by READING, with quoted evidence

1. **Is the closed-form path-occupancy analysis new?** Search the ECMP / load-balancing
   literature for any prior "distinct paths occupied by k hashed flows" (birthday-style)
   result. Leads to check — **all UNVERIFIED, from memory; verify existence and
   relevance before citing**: WCMP, Presto, the CONGA/HULA lineage, flowlet papers,
   hash-polarisation analyses (Alibaba HPN names the problem). If nothing prior exists,
   contribution (i) is *understated* today and should be claimed more firmly; if
   something exists, cite it and scope ours precisely.
2. **Is rate-proportional byte division for collectives known?** Leads (UNVERIFIED):
   BlueConnect (heterogeneous-bandwidth all-reduce decomposition), BytePS, TACCL /
   topology-aware collective compilers, Blink. For each: does it size pieces by a
   *measured* rate? Is there an optimality argument? Prop. 1's delta must be stated
   against whatever actually exists, not against silence.
3. **Is a closed-loop per-edge flow-count controller novel in this space?** Check what
   adapts in MPTCP path management, CONGA/HULA, and Ethereal's own failure path:
   adaptive at what granularity, driven by what signal, with what stability story.
4. **What else differs that nobody has articulated?** Work the axes systematically:
   objective function · information model (above) · who chooses paths · topology and
   capacity assumptions · failure story · QP-budget accounting · message-size range ·
   collective coverage (they run four collectives, we run ring only — a scoping
   difference to state plainly, not to hide).
5. **Synthesis — the value proposition.** Draft the paragraph that says what this paper
   *is*: the characterisation-and-sizing study of the deployable design point — hashed
   ECMP multi-QP — that production ships and prior work benchmarks but nobody sized.
   Then propose **up to three concrete strengthenings with costs**, for Ibrahem and Jose
   to choose from; candidates already on the table: an Astra-Sim cross-check of the ring
   null-result in *our* regime (turns the rebuttal from inference into measurement);
   packet-level spot-validation of m̂(k); a placement-aware per-edge k rule driven by the
   m̂ the model already gives.

### Ground rules for this study

Tier-L discipline throughout: full reads, quotes with page numbers, versions pinned,
local copies in `refs/`. Findings land in this file; wording diffs are proposed, never
applied without approval. The **minimal** MP-RDMA acknowledgment in the paper (one
sentence — blocker stage 1 in `PROJECT_STATE.md` §7.1) does **not** wait for this study;
the study decides the *final* positioning, not the interim honesty.
