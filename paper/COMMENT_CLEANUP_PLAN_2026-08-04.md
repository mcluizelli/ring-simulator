# Comment-cleanup plan — 2026-08-04
## Execution log appended 2026-08-05

| round | approved | done | comment counts after |
|---|---|---|---|
| 1 | delete the 3 zero-information `\IH` replies; promote IH#7 into §III; fix IH#11's count | `\IH` 11 → 8; §III gained the placement sentence (95.1% / 66.5%, read from `ke_table.csv`); "eleven" → **thirteen** (13 new keys counted in the body) | JY 12 · IH 8 · jose 8 |
| 2 | retire JY#6; add a back-reference for JY#9 then retire it | JY#6 deleted (Lemma 1 + proof sit directly after it, 0 references to it); §V now reads "…\texttt{NCCL\_IB\_QPS\_PER\_CONNECTION} setting (Section~\ref{sec:bg})…", which made JY#9 **and** IH#8 redundant | **JY 10 · IH 7 · jose 8** |

**Two defects of my own were found and fixed during round 2**, both created by the §III
restructure and both invisible to the checks that existed at the time:

* `\eqref{eq:bstar}--\eqref{eq:T}` printed as **"(4)–(2)"** — the reorder made the range
  run backwards. An undefined-reference check passes on this, because both labels exist;
  order is a separate property. Now covered by **R10** in `scratchpad/regression_check.py`.
* "speeding a non-bottleneck edge does not help" was said **twice** — once in the new
  Eq. (2) sentence and once in the old bottleneck paragraph. Deleting that paragraph fixed
  both problems at once.

IH#7 was **not** deleted as planned. Jose's question had two halves; the paper now answers
the placement half in the body, but hop count appears **0 times** in the rendered text, so
the reply was rewritten to say plainly that we do not model it and to ask whether he wants
that closed. Deleting it would have hidden an open question.

Standing verification: `scratchpad/refresh_snapshot.ps1 <expected-zip-bytes>` refreshes the
snapshot behind a size gate, then runs `regression_check.py` (R1–R10) and
`verify_IH_claims.py`. Three earlier checker runs reported failures that had already been
fixed, purely because the snapshot was stale — hence the gate.

---

**Status of the original plan below: PLAN ONLY. Nothing in the paper was changed to produce it.**
Method: 6 agents produced a per-comment disposition from an exact snapshot of the live
Overleaf source; every "fully handled" verdict was then given to an independent
adversarial checker whose default answer was "not upheld". **13 of 21 were overturned.**
Three findings were then re-verified by me personally against the source.

Inventory: **12 `\JY`** (Jose's asks, 1,651 chars) · **8 `\jose`** (prose he drafted,
8,199 chars) · **11 `\IH`** (our replies, 2,388 chars). Total **12,238 chars — 28% of the
source body**. The rendered body (what `\commfalse` prints) is 30,993 of 43,231 chars.

---

## 0. THREE BLOCKERS — fix these *before* deleting any comment

These are cases where deleting a comment would silently remove something the paper needs.
All three were verified by me, not just reported.

### B1. `eq:bstar-ns` is defined **only inside Jose's comment**, and the body references it
* `\label{eq:bstar-ns}` — **1 occurrence in the source, 0 in the rendered body.**
* `\eqref{eq:bstar-ns}` — **2 in the source, 1 in the rendered body** (inside Proposition 1).
* Consequence: with `\commfalse` the reference dangles. With comments on it compiles at
  0 warnings, which is why the earlier audit missed it — **that audit tested the wrong
  configuration**, the same class of mistake as the `\times` bug.
* **This is mine.** I relabelled Jose's equation inside his comment and then pointed
  Proposition 1 at it.
* Fix: lift the two-line equation out of `\JY#4` into running text next to
  Eq. (`eq:bstar`), keep Jose's comment (or a one-line reply) as the record.

### B2. The full-duplex justification exists **only inside `\IH#2`**
* `full-duplex` — 1 in source, **0 in rendered body**. `each direction` — 1, **0**.
* The body still reads *"The fabric is a directed graph $G=(V,E)$ with edge capacities
  $c_e$"* with no justification anywhere a reader can see.
* Fix: promote one sentence into the body (links are full-duplex; $c_e$ applies per
  direction), then the comment can go.

### B3. `$k_e$` carries **two different meanings**
* line 252 — *"A ring edge $e$ carried by $k_e$ flows"* → **number of flows** (my text).
* line 313 (Lemma 1) and line 542 (Table II) — $k_e$ = **expected number of distinct
  paths**, which is also how the abstract uses it.
* A reviewer meeting `$k_e \le K$` cannot tell which quantity is bounded.
* Fix: rename one of them (suggestion: keep $k_e$ for distinct paths — it is already in
  the abstract, the lemma and the table — and use $k(e)$ or $\kappa_e$ for the flow count).

---

## 1. Per-comment disposition

`final` is after the adversarial pass. **OVERTURNED** = the checker found the body does
not really discharge the comment.

### Jose's asks — `\JY`

| id | his words (verbatim) | final | action |
|---|---|---|---|
| JY#1 | *"complete the contributions and add to the introduction the toy example we discuss"* | fully handled | **keep for Jose** — both parts are in §I; let him confirm before it goes |
| JY#2 | *"maybe undirect?"* | not handled | **his decision + B2** — body still says "directed"; the agreed fix was never applied |
| JY#3 | *"maybe better to defune a FT topology first?"* | OVERTURNED | **keep + ask** — Fat-Tree is now described *three* times (Background 196-198, Model 224-227, unadopted `\jose` 173-174); "pod" is never defined; the 2:1 / 4:1 / 2-tier fabrics are not defined in the model at all |
| JY#4 | *"Consider also the definition of worstcase where we are not allowed to split the traffic"* | partly | **blocker B1** — content answered in Prop. 1, but his equation is the only definition and it lives inside his own comment |
| JY#5 | *"1) byte slpit is not defined 2) what do you mean by QP budget?"* | OVERTURNED | **keep + fix** — (1) closed by the split-vector definition; (2) only *renamed*: $K$ appears twice, with no value, range or link to the 1–128 NCCL limit. Also: the Problem minimises $T(M,P,k)$, which contains no $b_e$ and takes a scalar $k$ |
| JY#6 | *"seems you need to define a theorem and proof"* | **upheld** | **safe to delete** — Lemma 1 + IEEEproof are in the body |
| JY#7 | *"the probability for a collision depends on the workers location… path length is 2 links… 4 links"* | partly | **needs work** — `path length` and `hop` appear **0 times** in the rendered body. We answer the path *count*, never the path *length*. (Note: his items 2 and 3 both say "same POD"; item 3 is cross-pod.) |
| JY#8 | *"Rewrite the section explaining your algorithmic approach defining split methods"* | OVERTURNED | **keep for Jose** — Algorithm 1 + the mechanism figure exist; checker found the "define an all-reduce algorithm" half weaker than he asked |
| JY#9 | *"Maybe start the section explaining about this parameter"* | OVERTURNED | **keep briefly** — explained in §II, but the checker disputes that §V "starts" with it |
| JY#10 | *"I am missing some information about the allocation method in the physical nodes of FT"* | OVERTURNED | **keep for Jose** — Setup now states it and adds a placement sweep; checker found residual gaps |
| JY#11 | *"What are the dashed lines in graph?"* | **upheld** | **keep + one-line reply**, then delete |
| JY#12 | *"You need a much more extensive relate work…"* | OVERTURNED | **keep for Jose** — 11 venue-verified additions are in; he should see them against his three-conference instruction |

### Jose's drafted prose — `\jose` (8,199 chars, 67% of all comment mass)

| id | what it is | final | action |
|---|---|---|---|
| jose#1 | alternative **abstract** | partly | **his decision** — we repositioned instead of adopting; he must sign off |
| jose#2, #3 | intro paragraphs | OVERTURNED (near-duplicate) | delete **after** he sees the diff |
| jose#4 | contributions paragraph | **upheld** | **safe to delete** — superseded by richer body text |
| jose#5, #6, #7 | Fat-Tree / ring-optimality / QP background | partly | delete after his pass; **note:** 6 citation keys (`greenberg2009vl2`, `kandula2009detailed`, `sergeev2018horovod`, `wang2020overlapping`, `infiniband2015specification`, `nvidia2023nccl`) appear **only** inside these blocks and will leave the paper with them |
| jose#8 | the 43-char fragment *"all-reduce collective implementation"* mid-sentence | not handled | **ask him** — no verb, no referent; we cannot guess what he wanted |

### Our replies — `\IH`

| id | final | action |
|---|---|---|
| IH#3, IH#6, IH#9, IH#10 | **upheld** | **safe to delete** — pure acknowledgements whose content is visibly in the body |
| IH#2 | not handled | **promote into body** (blocker B2), then delete |
| IH#4 | partly | **blocker B1** — it claims the equation is "now above"; true only while comments are on |
| IH#7 | partly | **promote** — the 95% / 66% placement contrast reached the abstract but not §III, which is where Jose asked for it |
| IH#1 | partly | **keep** — it ends with an unanswered request for his sign-off on the abstract pivot |
| IH#5, IH#8, IH#11 | OVERTURNED | keep until the matching `\JY` is resolved |

---

## 2. Proposed order of work

**Phase 0 — blockers (must precede any deletion).** B1 move the equation into the body ·
B2 promote the full-duplex sentence · B3 resolve the `$k_e$` collision. Then verify by
building **with `\commfalse`** and confirming 0 errors *and* 0 warnings — the check the
earlier audit skipped.

**Phase 1 — archive.** Append the full comment thread verbatim (all 31 items) to
`JOSE_REVIEW_2026-07-21.md` before anything is deleted, so the record survives outside
the `.tex`.

**Phase 2 — delete the 6 that are safe now.** JY#6 · jose#4 · IH#3 · IH#6 · IH#9 · IH#10.

**Phase 3 — the content gaps, if we want them closed.** JY#7 path length · JY#5 define
$K$ and make the Problem well-posed in its own decision variables · JY#3 reconcile the
three Fat-Tree descriptions and define "pod".

**Phase 4 — Jose's calls.** JY#2 directed vs undirected · jose#1 the abstract ·
jose#8 what the fragment meant · plus his review of everything in Phase 2/3.

---

## 3. What I would *not* do

* **Do not bulk-delete all comments.** Three of them are currently load-bearing (B1, B2,
  and IH#7's numbers), and 8,199 chars of Jose's own drafting should not be discarded
  without his sign-off.
* **Do not delete his comments to make the file tidy before he has read the answers.**
  Six comments are answered but he has never seen the answers; the paper trail is the
  point of the `keep-for-jose` verdict.
