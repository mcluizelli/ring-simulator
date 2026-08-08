# Paper revision and Jose-meeting log — 2026-08-06

This is the durable record of the uncommitted paper pass performed after the
`2b4507b` Overleaf baseline. It records what changed, why it changed, and what
was independently checked. Historical entries in `JOSE_REVIEW_2026-07-21.md`
remain untouched except for appended retirement/correction records.

## 1. Scope and invariants

- No `sim.py` edit. Its SHA-256 remains
  `815d499af4bc3ba5387428dcda6e618f537c758a9a0ceea2d2c605831cf9e60e`.
- No frozen CSV edit. All 63 manifest entries and 21,210,573 bytes reproduce
  `frozen_csv_sha256.txt`; aggregate manifest SHA-256 remains
  `09a1418e965b9c2d597721ff0d3b1e8db937a19ce667accfa2cf1f469664c24e`.
- No new experiment and no regenerated result table. The deep numerical gate
  only reconstructs deterministic initial rate snapshots in memory.
- No commit, push, or staging in this pass.

## 2. Jose/IH comment closure, one item at a time

| Item | Before | After and reason |
|---|---|---|
| No split | Proposition 1 contained the edge-level idea, but the ring comparator was unnamed and Jose called it a worst case. | Defined `B*_{ns}(k,h)` as the best-single-subflow oracle in the same frozen snapshot. It is neither a worst-case guarantee nor a one-QP rerun. |
| Byte split / QP cap | `b` and “QP budget” were ambiguous. | Defined the split vectors and their timing; imposed NCCL's per-connection `K <= 128` cap per ring edge; kept `sum k_e` as a reported cost, not a global constraint. |
| Placement / path length | Placement-dependent path counts and the role of hop count were implicit. | Stated `m=1`, `r/2`, and `(r/2)^2` for same-ToR, same-pod, and cross-pod pairs; stated that path arcs constrain rate but the model has no separate per-hop latency. |
| Design / algorithm | Flow-count selection, byte allocation, and Ring All-Reduce were mixed together; the algorithm caption described stale one-window behavior. | Separated the offline `k*` rule from equal/proportional allocation, kept the collective schedule unchanged, and described per-tick rates plus periodic reallocation. |
| Physical allocation | The worker-to-host and ring construction procedure was incomplete. | Added uniform sampling without replacement, one worker per host, seeded sample order including wrap-around, topology-specific host populations, and within-fabric pairing. |
| Related Work / IH | The live comments asked for recent work and identified Ethereal/MP-RDMA-x and its ring result. | Added the closest-mechanism comparison, stopped claiming multi-QP as novel, scoped the contribution to occupancy, `k`, and measured-rate allocation, and stated the evaluated regime difference. See the source-status hold in Section 7 below. |
| Jose's alternative Introduction | Its valid mechanism facts were already present, but it claimed novelty, disjoint paths, and an unqualified aggregate rate. | Retired without copying the unsafe clauses; the ledger preserves the full proposal and the disposition. |

Final live source count: `JY 0 / IH 0 / jose 0`. Every retired block is preserved
verbatim in the ledger and has a dated rationale.

## 3. Scientific corrections beyond comment retirement

- Replaced the inaccurate network-wide `max-min` label with
  **link-local equal-share bottleneck-rate model** and scoped the static
  proportional quantity as a fixed full-concurrency local-model reference.
- Added Das et al.'s published INFOCOM 2005 record for the distinction between
  local link sharing and network-wide fairness.
- Removed “ceiling,” “upper bound,” and “only NCCL knobs” language where the
  evidence did not justify it.
- Scoped Proposition 1, Corollary 1, and Algorithm 1 to their actual fixed-rate
  or dynamic semantics.
- Corrected the displayed `k` sweep from the ambiguous `{2,...,32}` to the
  actual tested set `{2,4,8,16,32}`.
- Clarified that the `2.26x` value at `P=16` is the paired static-control arm;
  the separate static sweep is `2.22x`. This is an estimator/source distinction,
  not a contradictory result.
- Corrected the `k*>32` table semantics: speed-up and efficiency are reported
  at the largest tested `k=32`, not at an unobserved `k*`.
- Made the experiment families reproducible in Setup: 64 MiB per ring edge for
  the saturation/proportional sweeps, 256 MiB per ring edge for the
  headline/congestion/placement/controller runs, and a 256 MiB total payload
  for the background All-Reduce run. Primary sweeps use random placement;
  robustness checks explicitly vary placement or `n`.
- Separated the cross-`k` estimands instead of attaching one estimator's CI to
  another estimator's point value: the ratio of means is 1.117 (11.7%), while
  the mean paired ratio is 1.116 with CI `[1.109, 1.124]`.
- Stated that controller curves and adaptive stars are separate seed families,
  each paired internally to its own `k=1` baseline.
- Corrected the headline scope: `2.84x` is a ring-step completion-time result
  from one simultaneous ring-neighbor transfer, not a full end-to-end
  All-Reduce result. The background campaign is the full pipelined All-Reduce.
- Restricted the offline static decision to the uniform subspace `k_e = k`;
  the per-edge controller remains a separate heuristic.
- Recorded that proportional allocation receives exact current model rates in
  simulation; sender-side estimation delay and noise are not modeled.
- Named equal splitting as explicit NCCL split mode rather than the current
  NCCL default, and recorded the proportional/controller timing parameters.
- Added the frozen background-flow distribution and all four congestion-process
  parameters needed to reproduce the reported regimes.
- Marked the table's distinct-path row as a cross-pod analytic `m=64` quantity,
  not a random-placement average.

## 4. Structure and language

- Rewrote the abstract compactly while retaining the mechanism, model scope,
  tested regimes, and load-bearing results.
- Moved the `k*` definition into Design, separated Setup method from robustness
  checks, and added a compact limitations paragraph.
- Standardized US spelling and terminology (`realized`, `hot spot`, `speed-up`,
  noun/adjective uses of `queue pairs`/`queue-pair`).
- Active TeX contains zero `---` em-dash tokens. The compiled PDF contains one
  em dash, solely IEEEtran's generated `Abstract—` label.
- Figure builders were changed only where visible terminology changed. Frozen
  data and axes are unchanged; the tiny saturation annotation endpoint shift is
  a glyph-width consequence of `realised` -> `realized`, not a data/geometric
  change.

## 5. Numerical gate

`paper/audit_paper_claims_2026_08_06.py --deep-model --workers 8` is a read-only
gate. The final source passes **225/225** checks. Among them:

- every frozen CSV hash/size and the `sim.py` hash;
- headline, congestion-regime, placement, background, saturation, `k*`,
  flexible-split, cross-`k`, and controller values;
- 32,000 equal/proportional paired configurations with zero proportional slowdowns at matched
  `k`;
- 9,440/32,000 dynamic proportional crossings of the static reference;
- deterministic reconstruction of all 40,000 fixed-snapshot cells, including
  exact reference reproduction, one-sided tick error, maximum/mean errors of
  0.80%/0.46%, and the 67.2% predicted versus 67.5% measured `k=8` gap.

The final review and submission builds are 7 pages each, with 0 errors,
undefined references, multiply-defined labels, or overfull boxes. They have
identical extracted text and are visually identical across all 7 inspected
pages; their independent PDF byte hashes differ because of build metadata.
Active TeX has no reviewer invocation and no source em dash; the rendered PDF's
single em dash is IEEEtran's generated Abstract label.

## 6. Meeting picture: the model audit is a research result

| Frozen paper-producing rows | Realized time strictly below the static reference | Meeting phrasing |
|---|---:|---|
| Fixed equal-byte split | `0 / 56,000` | Equal never crosses the reference in the scanned frozen rows. |
| Dynamic proportional split (`v11.1`) | `9,440 / 32,000` (`29.5%`) | Proportional crosses it in about a third of the rows. |

This is a statement about the frozen campaigns, not a universal networking
claim. It supports the hypothesis that the local allocator can mask some of the
proportional policy's advantage and motivates the separately approved
network-wide-max-min revalidation campaign. Do not quote the `n=3` sentinel
percentages as a result.

## 7. Ethereal source status — checked 2026-08-06

Authoritative public records checked:

- arXiv: <https://arxiv.org/abs/2407.00550>
- the authors' research-group publication list, grouped by type:
  <https://stygianet.cs.purdue.edu/publications-type.html>

The public record supports the following precise statement:

> Ethereal is currently an arXiv technical report and has no publicly
> documented conference publication.

Details: arXiv v1 was submitted on 30 June 2024 as *Challenging the Need for
Packet Spraying in Large-Scale Distributed Training*. Version 2 was posted on
25 February 2025 under the Ethereal title and is marked “Extended version.” The
group page lists it under **Tech Reports / arXiv** as CoRR, not under conference
or workshop proceedings. No claim is made about a private submission or review
process, which is not publicly observable.

Internal source policy set by Ibrahem: Ethereal may remain a learning/comparison
reference, but must not be an evidentiary anchor for a paper claim. The current
BibTeX deliberately contains no conference venue. The active paper still cites
the preprint in the Introduction and Related Work; a future source-focused
sprint must independently corroborate, replace, or remove every claim that
would otherwise rely on it before submission. This pass records the hold and
does not silently perform that later editorial decision.

## 8. Still open after this pass

- Implement the separately approved allocator mode and run the staged
  `n=100` -> approved `n=1000` revalidation; do not overwrite legacy results.
- Decide at the evidence-integration stage whether the compact legacy baseline
  belongs in the paper.
- Resolve the Ethereal evidence-source hold described above.
- Rebuild the generated tracker mirror from its already-corrected source in its
  separately scoped derived-artifact unit.
- Venue/page-budget cuts and any optional figure-density redesign remain later
  decisions with Ibrahem and Jose.

## 9. Continuation — 2026-08-08

The “no `sim.py` edit” and “no commit/push” statements in Section 1 describe
the bounded paper pass performed on 2026-08-06 and remain historically correct.
Subsequent, separately approved research units added a selectable
`network_maxmin` allocator while preserving `link_local_equal_share` as the
byte-exact legacy default. The current audited `sim.py` SHA-256 is
`96505cefe2e5aa761b80080d77145bfd384c688ce4a8ca5792f8f7ce17ef59bd`;
the historical `815d499a...` value above is intentionally retained as the
original paper-pass baseline.

The paired `n=100` allocator revalidation and the corrected proportional
current-boundary audit passed their independent gates without modifying any
frozen result. Ibrahem subsequently authorized a full `32`-arm `n=1000`
static-proportional extension over samples `100..999`. That authorization does
not change the paper’s evidence until the run is sealed, independently audited,
and explicitly integrated. The controller-calibration question, the Ethereal
evidence-source hold, and venue/page-budget decisions remain separate open
items.
