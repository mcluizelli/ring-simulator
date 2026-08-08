# Rate-model revalidation log and Jose meeting brief

**Opened:** 2026-08-06 09:04 IDT
**Owner:** Ibrahem Hmad
**State:** Units 2A--6 complete; corrected proportional `n=100` revalidation passed; Unit 7 and `n=1000` are not started
**Commit/push:** forbidden for this sequence; all work remains uncommitted

This side file is the durable account of what was discovered, changed, and
decided during the rate-model correction. It is intentionally outside the
Overleaf clone. It is both an execution log and the source for the next meeting
with Dr. Jose Yallouz; diagnostic `n=3` sentinel percentages are not research
findings and must not be quoted from it or from the gate. The same restriction
applies to effect sizes from the timing-only `n=5` pilot.

## 0. Day-wide verified change trail

This section records the full 2026-08-06 paper work, not only the rate-model
branch of it.

### Pushed checkpoint — Overleaf commit `2b4507b`

Commit message: `Clarify fabric setup after Jose's review` (06:38 IDT). It
changed only `paper_infocom.tex` and removed the orphan
`fig_efficiency.pdf`. Its reviewed content was:

- submission hygiene: preserved `%\anonfalse`, replaced the stale paper number
  with `Paper #TBD`, and made the double-blind note venue-neutral;
- debris cleanup and the punctuation/style pass, with paper digits protected by
  the approved whitelist;
- retirement of Jose's dashed-line question after checking both caption and
  rendered legend;
- retirement of Jose's “define a Fat-Tree first” comment after defining the
  three-tier and two-tier fabrics before paths/ECMP;
- the real reporting correction exposed by that comment: the three-tier fabrics
  have 1,024 hosts, the leaf-spine has 128, and each topology draws from its own
  host set. The production drivers already did this correctly, so no data were
  rerun; the paper description was corrected and Jose was credited in the
  ledger;
- documentation resynchronised to 7/3/1 open comments at that checkpoint.

### Current uncommitted paper unit — directed physical fabric

The paired `JY#1`/`IH#1` question was then resolved. The physical network is now
`G=(V,\mathcal{L})`; each full-duplex connection contributes two directed arcs
`\ell`, with a separate `c_\ell` per direction. Logical ring edges retain `e`.
A full downstream notation sweep found no residual `G=(V,E)` or `c_e`, and the
two comments were retired with their verbatim text preserved in the ledger.
This was another description-only correction; no run or frozen datum changed.
The live uncommitted count is 6/2/1.

### Rate-model audit opened by the directed-fabric sprint

The notation sweep exposed that `FlowLevelSimulator.step` computes a minimum of
independent per-link equal shares, not network-wide max-min. The sidecar gate,
proof, literature check, frozen crossing audit, and the execution plan below are
the resulting third unit. This distinction remains uncommitted and no paper
rate-model wording has yet changed.

## 1. Decisions already made by Ibrahem

- Use the hybrid path: name the frozen/legacy model truthfully now, add a
  selectable network-wide unweighted max-min allocator next, and revalidate all
  rate- or completion-time-dependent paper results before final submission.
- Current precise name: **link-local equal-share bottleneck-rate model**; code
  enum: `link_local_equal_share`; short prose: **local-share model**.
- The uncommitted Unit 4 implementation adds `network_maxmin` through
  progressive filling, protected by feasibility and bottleneck-certificate
  tests. It has not yet produced paper evidence.
- Controller policy: first run the frozen controller configuration to isolate
  allocator effects; if tuning is justified, tune explicitly on disjoint seeds,
  lock the parameters, and retain both frozen-controller and tuned results.
- Congestion production campaign: upgrade to `n=1000` in principle; final go/no-go
  follows the measured pilot ETA.
- Keep a compact legacy robustness baseline ready; decide whether it enters the
  paper only at stage 8.
- ASTRA-Sim does not enter the current evidence chain. A pinned ASTRA-Sim/ns-3
  replay remains future cross-validation. SimGrid is the direct literature
  precedent if the paper needs one for a flow-level max-min abstraction.
- Do not overwrite frozen results. Do not commit or push. The `n=5` timing gate
  remains unstarted pending review; `n=100` and `n=1000` require later gates.

## 2. Unit 1 — snapshot and inventory

### 2.1 Repository baseline before this unit

| Repository | Branch | HEAD / local upstream | Baseline worktree |
|---|---|---|---|
| `paper-overleaf` | `main` | `2b4507b1baab3daec987cf02d2ea9d6f43f2b316` | one modified file: `paper_infocom.tex`; no staged files |
| `ring-simulator` | `ibrahim-paper` | `02c8ac9f3bedc3a621ae42b9180af2b4122a468d` | 19 modified, 5 deleted, 39 untracked; no staged files |

Both local HEADs matched their recorded upstream refs (0 ahead, 0 behind); no
network fetch was performed. `git diff --check` was clean. The umbrella
`simulator/` directory, including the root truth documents and progress-report
builders, is not a Git repository, so hashes below are the review baseline.
The complete pre-unit porcelain listing is preserved in
[`worktree_baseline.txt`](../investigations/rate_model_revalidation_2026_08_06/worktree_baseline.txt),
SHA-256 `e4bd4cd147e97eeb068a7eb0241e70af28298ceb82381f715f27cfc306ba8da6`.

### 2.2 Critical baseline hashes

| File | SHA-256 before unit 1 |
|---|---|
| `ring-simulator/sim.py` | `815d499af4bc3ba5387428dcda6e618f537c758a9a0ceea2d2c605831cf9e60e` |
| `paper-overleaf/paper_infocom.tex` | `24fbd8d9854d2eebcdfaf64859ec4ad53757101fcc13f70c83a4cab2557abd67` |
| `paper-overleaf/mybib.bib` | `fe6542536b400dc4575ce76f050921dcfcd425d8006cad5bde2095383cd37286` |
| master `../README.md` | `5cedd3c1bfedfb0bb2ec3d952151c73ad1edbe79a4f1b6beea80068bd033e3e4` |
| `PROJECT_STATE.md` | `4337e39e73b341969ecda26bae40b70358a63e6171275b335f0445925da5d371` |
| `OVERLEAF_WORKFLOW.md` | `19e4709349d83180f13220e87ff14b9f3b5569adec14b86f719b2f4e443f25a8` |
| `CLAUDE.md` | `c0754e4ad699104941073873cde15ca8bbd03a1d6bb409ddaa99ca637a6a31ba` |
| `ring-simulator/README.md` | `b6463ffcc368f8afb887a5c822e285071916c3df03f8acbfb14462ee97ade748` |
| `ring-simulator/LOCAL_NOTES.md` | `ec45aa5a395aea8dcf09a77ac3f726e108a3a1c00b5a0eeecc5ba92202361a4a` |
| `ring-simulator/paper/JOSE_REVIEW_2026-07-21.md` | `74f3f8a44fc0a070f33190c1b64c79e9a24d50604a35c1ceca7a8b8fbdc82d57` |
| `ring-simulator/paper/MAXMIN_RATE_MODEL_GATE_2026-08-06.md` | `77a9cb5dd7d7578908342784c1ee7f2a160cb48898a89819f4637e54cd0b23fb` |
| `ring-simulator/paper/build_ieee_eval_figs.py` | `1bba7ea0e04851e260969a026edb0eca567751662b4b6e635e513ac11b1e7921` |
| local/Overleaf `fig_gap_closure.pdf` | `e44ae93221d6d267bbdda72ad78256b848575bd08154383023d5d3fbbaa6d167` |
| local/Overleaf `fig_saturation.pdf` | `bc3255f9671965abbdfcc3d73f73914177aa69e032463b48d8ec6112eb972806` |
| `progress_report/tracker/tasks_data.json` | `353a2b35c6d918e0b707f0d265ed636b509cc44d39c0d3fae424e1da300c7b96` |
| `progress_report/tracker/TASKS.html` | `b07aeb36d0282e9630f2e1064e6d2d8f783e792f2b5dbd8f781971bfdb600b35` |
| `progress_report/build_sprint_en.py` | `ae95acc72ca4f909b3ffa10e078090b1b8932c0a459cb9e2be976d9f45d01981` |
| `progress_report/build_sprint_he.py` | `482a31cb8804c42a000c7b5f6a12d5004c3ab6064adc09d70390b35e19378bf5` |
| `progress_report/progress_report_EN.pdf` | `55018fd10202295fc4907e9554ebba658a9a0c667ee7ad0468f9511ec724be84` |
| `progress_report/progress_report_HE.pdf` | `0913ef8b1a3941271c22fdabdb63452cd97c2de076d3b76f7242bafe2bf5ec86` |

The full immutable-input snapshot covers all 63 `results/**/*.csv` files
(21,210,573 bytes). Its sorted data-row manifest hash is
`09a1418e965b9c2d597721ff0d3b1e8db937a19ce667accfa2cf1f469664c24e`;
the complete per-file list is
[`frozen_csv_sha256.txt`](../investigations/rate_model_revalidation_2026_08_06/frozen_csv_sha256.txt).
The read-only audit program is
[`audit_frozen_reference.py`](../investigations/rate_model_revalidation_2026_08_06/audit_frozen_reference.py),
SHA-256 `bf19c51c3f76147884091e63fefa3b7d6afdd83d9ff2c70e63ea8d442edcaf1a`.
It imports no simulator code, writes no file, and reproduced the counts in
Section 3 when run from the repository root.

### 2.3 Review-unit scope frozen by this inventory

The lexical audit found 64 semantic allocator/reference occurrences on 49 lines
in 20 live source files after excluding the gate itself, frozen CSVs, mirrors,
backups, and unrelated uses such as max-concurrent-flow. Expanding aliases such
as `compute_ring_theoretical_time`, `opt_time`, and `Bstar_Bps` produces a wider
dependency map, not a blind replacement count. The three-layer disposition is:

| Layer | Files / representative snapshot lines | Disposition |
|---|---|---|
| Truth now, unit 2A | `paper_infocom.tex:228,277--283,381--382,432,502,535`; `build_ieee_eval_figs.py:5,69--70,139,174,199`; master `README.md:127`; `CLAUDE.md:127`; `PROJECT_STATE.md:117`; ring `README.md:153`; `LOCAL_NOTES.md:142,225,232,284,747`; `lit_congestion_models.md:47`; `summary_C3_fattree_topology.md:20,34,36`; tracker source | Rename the legacy allocator and static reference without changing results; correct the TCP claim; rebuild only the two affected figures; append dated corrections where the source text is a historical record. |
| Truth now, unit 2B | `build_sprint_en.py:114,164,315,382--384,551,569,603,616,809`; `build_sprint_he.py:196,307,362,530,692` | Separate bilingual review and PDF rebuild; EN and HE must express the same scope. |
| With allocator and revalidation | `sim.py:701--716,921--994,1094--1102`; active experiment drivers, validators, report/figure consumers, output metadata | Preserve the legacy API through unit 3. In the later code patch add explicit allocator modes and model-aware reference names; new numeric outputs go only to new result versions. |
| Historical with correction | `JOSE_REVIEW_2026-07-21.md`; historical `ROADMAP.md`/`STATUS.md`; delivered presentation builders and old tracker recalls | Do not rewrite history. Add one dated erratum pointing to the gate and the new campaign provenance. |
| Quarantined for its own comment sprint | `paper/mechanism_split.tex:34--63`; open `IH#2` near paper line 343 | Do not partially clean now. The former also contains the retired impossible toy; handle it with `JY#6`. Handle the latter with `JY#5`/`IH#2`. |

**Unit 2A — paper and current truth.** The exact paper targets are lines 228,
277--283, 381--382, 432, 502, and 535 in the snapshot. The `fair-share` wording
inside the still-open `IH#2` block near line 343 is explicitly excluded and stays
for the `JY#5`/`IH#2` sprint. Paper digits and the 6/2/1 comment counts must not
change. The two affected rendered figure labels are generated by
`paper/build_ieee_eval_figs.py`; only `fig_saturation` and `fig_gap_closure` may
be rebuilt for this terminology unit. The current builder and corresponding
local/Overleaf PDFs were hashed before any edit.

Current truth documents in this review include the master `README.md`,
`CLAUDE.md`, `PROJECT_STATE.md`, `OVERLEAF_WORKFLOW.md`,
`ring-simulator/README.md`, `LOCAL_NOTES.md`, the live congestion-model and C.3
research summaries, and the tracker source. In particular,
`LOCAL_NOTES.md` must lose the unsupported statement that this is the model to
which TCP converges. Historical ledgers and roadmaps are not silently rewritten;
they receive a dated correction that preserves the old text. `sim.py`, frozen
CSVs, and numeric results remain outside this unit.

One known false docstring therefore remains deliberately queued until the
post-regression allocator patch: `sim.py` currently says the proportional runner
should not beat `compute_ring_theoretical_time` by more than about 1%. The frozen
audit refutes that statement; it must be corrected when `sim.py` is first
authorised to change, not smuggled into the terminology-only unit.

`paper/mechanism_split.tex` is not input by the live paper and still contains an
older, physically impossible toy as well as the stale allocator name. It is
quarantined from reuse and will be handled with `JY#6`, rather than receiving a
partial blind rename in unit 2A.

**Unit 2B — progress-report builders.** Only
`progress_report/build_sprint_en.py` and `build_sprint_he.py` are edited as a
separate review unit. They must agree semantically, rebuild both PDFs, and be
reviewed against the baseline hashes above. `_data.py`, style/RTL helpers, and
frozen CSVs are read-only dependencies.

**Unit 3 — legacy regression.** Add a standalone standard-library test file;
do not edit `sim.py`. Hard-code logical fields and IEEE-754 double bits, not raw
CSV serialization. Each default invocation will later be paired with an
explicit `link_local_equal_share` invocation after that mode exists. The three
fixtures frozen now are:

| Fixture | Frozen row | Exact completion time |
|---|---|---:|
| N0 equal | `3tier_nb,P=64,seed=0,k=8` in `v10.1` | `0.005399999999999995` |
| O0 proportional | `3tier_os4,P=64,seed=0,k=8` in `v11.1` | `0.007399999999999983` |
| C10 baseline | `P=64,affected_fraction=0.1,baseline,run=1` in `v5.5` | `0.06005000000000121` |

The N0 fixture also freezes `opt_time=0.00536870912`,
`equal_split_gap=0.005828380584715909`, `Bstar_Bps=12500000000.0`,
`top_used=748`, and `max_top_contention=4`. O0 freezes all five source fields;
C10 freezes all eight source fields. A fresh topology and, for C10, a fresh
stateful congestion object are required for every test invocation.

**Dated correction, 2026-08-06:** the first inventory table recorded C10 as
`run=0`. That was the driver's zero-based `run_idx`, not the durable CSV field;
the frozen row is one-based `run=1`. The CSV's `seed=51966` is the topology/run
seed, while the deterministically offset congestion-process seed is `52066`.
The completion time and reconstruction methodology were already correct; this
correction separates the two coordinate systems explicitly.

### 2.4 Numeric and mutation guards

- `paper_infocom.tex` numeric whitelist for unit 2A: **empty**. No paper digit
  sequence may be added, removed, or changed.
- New digits in this side log and the gate are limited to snapshot hashes,
  timestamps, frozen-audit counts/coordinates, and the verified bibliographic
  metadata below.
- `sim.py` must retain SHA-256
  `815d499af4bc3ba5387428dcda6e618f537c758a9a0ceea2d2c605831cf9e60e`
  through units 1--3.
- All 63 frozen CSVs must reproduce the manifest hash above after every unit.
- No stage/commit/push; no figure other than the two explicitly named above may
  change in unit 2A.

## 3. Frozen realised-versus-reference audit

The prerequisite scan requested before Corollary 1 and the captions is now
recorded in Section 5.1 of the gate. Its decisive result is:

- fixed/equal runs: zero strict crossings in 56,000 paper-producing rows, plus
  zero in 100 validation rows;
- `v11.1` proportional runs joined to the paired `v10.1` references:
  9,440 of 32,000 rows have `t_prop < opt_time`; 7,335 are more than 1% below;
  27 of 32 cells contain a crossing and 13 have a negative mean gap;
- worst paired row: `3tier_os4,P=64,seed=634,k=4`, where
  `0.01275 s < 0.019822925981538463 s` (35.68% below);
- at `k=8`, the two negative-mean cells plotted in the paper are
  `3tier_os4/P=64` (-2.6456%) and `2tier/P=64` (-0.9692%).

Therefore the correction is not merely defensive. It is empirically required
for the universal “no split does better” sentence and the gap-closure “bound”
label. The equal-split saturation curves do not cross the reference, so their
caption change is prophylactic with respect to those rows but still required to
identify the model and scope truthfully. The full replacement term for the
current frozen artifact is **static full-concurrency local-model proportional-split
reference over the same hashed paths**; after that definition, captions may use
the shorter **static local-model reference**.

## 4. Canonical Das et al. BibTeX

Use only the metadata printed in the published PDF; do not copy the stale
author-page BibTeX (`pages = {to appear}` and a different author order). The
approved minimal record is:

```bibtex
@inproceedings{das2005lowstate,
  author    = {Abhimanyu Das and Debojyoti Dutta and Ahmed Helmy and
               Ashish Goel and John Heidemann},
  title     = {Low-State Fairness: Lower Bounds and Practical Enforcement},
  booktitle = {Proceedings IEEE INFOCOM 2005},
  volume    = {4},
  pages     = {2436--2446},
  year      = {2005},
  doi       = {10.1109/INFCOM.2005.1498529}
}
```

The paper supports the local-versus-global fairness distinction and the fact
that a downstream-bottlenecked flow can strand upstream capacity. It does not
prove our componentwise lower-bound theorem; that proof remains self-contained.

## 5. What to tell Jose before the production runs

### Established now

1. The implementation used by every frozen campaign is not network-wide
   max-min. It independently divides every link by its active user count and
   gives each flow the minimum of those local shares; downstream bottlenecks can
   strand capacity upstream.
2. Jose's questions triggered a real methodological audit, not cosmetic cleanup.
   The code is reproducible and the frozen data are intact, but the allocator
   name and the scope of the static reference were too broad.
3. The static reference is crossed by the frozen proportional dynamics in
   production-size data. This is why “optimal ceiling” and “no split does
   better” must be corrected now.

### Two-row meeting picture

The sharpest way to show the finding is to keep the policies and scope visible:

| Frozen paper-producing rows | Realised time strictly below the static reference | Meeting phrasing |
|---|---:|---|
| Fixed equal-byte split | `0 / 56,000` | Equal never crosses the reference in the scanned frozen rows. |
| Dynamic proportional split (`v11.1`) | `9,440 / 32,000` (`29.5%`) | Proportional crosses it in about a third of the rows. |

This is evidence about the frozen campaigns, not a universal statement about every
network. It demonstrates why the old “ceiling” label was correct for neither the
dynamic proportional policy nor the claim we want to make to Jose.

### Emerging contribution — present as a hypothesis until revalidation

The local allocator appears to hide part of the benefit of proportional byte
splitting precisely where heterogeneous paths, oversubscription, and congestion
create reclaimable capacity. This could become a substantive result: conclusions
about multi-path splitting depend not only on routing and byte placement, but
also on whether the flow-level simulator reallocates stranded capacity globally.

Do **not** attach a final percentage to that claim yet. The sidecar sentinels are
`n=3` diagnostics only. The planned paired `n=100` pilot, followed by approved
`n=1000` production campaigns, will determine the magnitude, whether controller
parameters transfer, and whether the finding survives across all paper cells.

### One-sentence meeting version

> The audit found that our simulator was reproducible but mislabeled: it used a
> conservative link-local sharing rule rather than global max-min, and the first
> evidence suggests that correcting this may reveal additional proportional-split
> headroom under heterogeneous congestion; we are preserving the old baseline and
> running a paired, versioned revalidation before changing any reported number.

## 6. Unit-by-unit change journal

### Unit 1 — complete, approved by Ibrahem

**Before:** no durable hash manifest for all frozen CSVs; the gate did not test
whether realised production rows crossed the static reference; the meeting
decisions and emerging-contribution framing were scattered across chat.

**After:** preserved the full dirty-worktree baseline, added the 63-file SHA-256
manifest and a deterministic read-only audit program; added the full frozen
crossing audit to the gate; corrected the gate's Das link to the published PDF;
opened this decision/change log. No paper text, `sim.py`, frozen CSV, progress
builder, or generated paper figure was changed. The CSV audit was run once; no
simulation or test was run.

**Review gate:** passed. Ibrahem independently reproduced the counts, including the two
`k=8` cells used by the figure, and approved Unit 2A.

### Unit 2A — complete, awaiting Ibrahem review

**Before:** the paper called the allocator `max--min`, presented the fixed-rate
proportional calculation as an `optimal-split bound`, and repeated that status in
the two rendered figures and current truth documents. The builder's three visible
labels said `bound`/`bounds`; historical ledgers lacked a superseding correction.

**After:** the paper now defines the **link-local equal-share bottleneck-rate
model**, scopes Proposition 1 and Corollary 1 to a fixed full-concurrency rate
snapshot, and names the plotted quantity the **static full-concurrency local-model
reference**. Algorithm 1 shows the implemented per-link share and path bottleneck
directly. Only `fig_gap_closure` and `fig_saturation` were rebuilt; their three
visible substitutions are `bound` → `reference`, `optimal-split bound` → `static
local-model reference`, and `bounds diverge` → `refs diverge`. The current truth
documents were synchronized; old ledger/roadmap/status wording was preserved with
a dated correction; tracker source task `G.7` is the single superseding erratum.
`TASKS.html` remains deliberately unchanged for the separate derived-mirror rebuild.
The final reviewer micro-fix also states the time semantics explicitly: rates are
recomputed every simulator tick as the active set or residual capacity changes;
only the static comparison freezes the initial full-concurrency snapshot, before
any sub-flow or ring edge finishes.

**Paper/source guards:** the ordered paper digit stream is identical (`645 / 645`),
and the brace-aware comment bodies are identical byte-for-byte at `\JY 6 / \IH 2 /
\jose 1`. The exact phrase `optimal-split bound` is absent from both
`paper_infocom.tex` and `build_ieee_eval_figs.py`. The builder's normalized AST,
normalized source, and digit stream are identical to the pre-edit snapshot; exactly
the eight approved terminology literals changed.

**Figure gate:** an initial staged candidate was rejected because the longer word
`references` moved the annotation arrow endpoint by about `1.66` display pixels.
Nothing was promoted. The concise `refs diverge` label then passed: exact artist
geometry/data equality; exactly three approved text substitutions; all other text
boxes unchanged; identical page boxes, `55 / 297` vector drawings and semantic font
inventories; PNG dimensions unchanged at `1035×630 / 2148×765`. Final hashes are
`9e052003…` / `38c040c5…` for gap PDF/PNG and `7577b819…` / `2d6848ff…` for
saturation PDF/PNG. The local and Overleaf PDF hashes match.

**Build and scope guards:** `--both` is clean at `0 / 0 / 0 / 0`, `7 / 7` pages,
`574,519 / 550,993` bytes, with no `??`. `sim.py` (`815d499a…`),
`mechanism_split.tex` (`ed3c8126…`), the EN/HE builders (`ae95acc7…` /
`482a31cb…`), `TASKS.html` (`b07aeb36…`), and the `63` frozen-CSV manifest root
(`09a1418e…`) are unchanged. No simulation was run, no frozen result was written,
and no commit or push was made.

### Unit 2B — complete, awaiting Ibrahem review

**Before:** both live progress reports still called the allocator `max-min` or a
fair-share model, treated the fixed full-concurrency proportional calculation as an
optimal ceiling/bound, described dynamic crossings as false positives, and
generalized the proportional policy to a smaller `k*` or half the flows on every
congested fabric. Three reused historical rasters also carried those legacy labels
inside their pixels.

**After:** the English and Hebrew reports now use the same three-part vocabulary:
the **link-local equal-share bottleneck-rate model**, the **static
full-concurrency local-model reference over the same hashed paths**, and the
explicit caveat that this is not network-wide max-min. The reports now distinguish
the static snapshot from rates recomputed as the active set and residual capacities
change; call reference crossings real end-game release rather than a false result;
scope the `k*` comparison to cases where saturation is observed; and describe the
ideal proportional result as model sensitivity, not a proved upper bound or direct
deployment prediction. The topology saturation wording was softened from a unique
bisection diagnosis to a fabric-side limit consistent with the local model.

The three raster files were deliberately not rebuilt. Each current caption now
contains a visible correction adjacent to the unchanged image: `optimal-split
ceiling` is the static reference; `equal-split-bound` is an observed binding
limitation rather than a formal bound; and `reaches the ceiling` is the best speed
observed in that sweep rather than the static reference or a global optimum.

**Source and semantic guards:** the ordered ASCII-digit streams are byte-for-byte
identical to the frozen builders: EN `1,261 / 1,261`
(`1187098ab11f…`) and HE `1,445 / 1,445` (`b9263313e8f1…`). The exact stale phrase
`optimal-split bound` is absent from both builders. A nine-pair EN/HE claim matrix
was checked across the overview, allocator definition, simulator history,
topology finding, engine/validation scope, topology guard, saturation/launch
claim, dynamic crossing, and limitations. The English and Hebrew builders moved
from `ae95acc7… / 482a31cb…` to `9553c00e… / 14d66b16…`.

**PDF and raster guards:** both rebuilt PDFs remain `14` A4 pages with unchanged
semantic font inventories, no blank page, `??`, replacement glyph, clipping, or
overlap; all `28` pages were visually reviewed. Final sizes and hashes are EN
`1,763,025` bytes / `2bcf515b…`, HE `1,854,552` bytes / `bc40ad87…`.
All eight embedded rasters in each language are pixel-identical to baseline. The
three critical source-image hashes remain `feb64a61…`, `e77a7acd…`, and
`933b38d0…`; each appears exactly once per language and stays on the same page as
its correction caption.

**Scope guards:** `_data.py` (`17be0362…`), `_style.py` (`34ac56a0…`), `_rtl.py`
(`2df2dd0d…`), `sim.py` (`815d499a…`), and all three raster source files are
unchanged. All `63` frozen CSVs match their per-file snapshot (`0` mismatches,
`21,210,573` bytes) and reproduce root `09a1418e…`. No simulation or data rewrite
was run; no file was staged, committed, or pushed.

### Unit 3 — complete, awaiting Ibrahem review

**Before:** there was no standalone byte-exact regression protecting the three
frozen sentinel records. The sidecar gate compared completion times with an
absolute tolerance, so its claim of last-bit reproduction was stronger than its
actual assertion. The inventory also conflated C10's zero-based driver index
with its one-based CSV run label.

**After:** added
`validation/test_legacy_rate_model_regression.py`, a standard-library
`unittest` suite that reads no frozen CSV at runtime. It reconstructs N0, O0,
and C10 from fresh topology objects, plus a fresh stateful congestion object for
C10, and compares every frozen floating-point result by its exact IEEE-754
binary64 payload. The logical source fields are hard-coded and checked as well.
For C10 the test now distinguishes `run_idx=0`, CSV `run=1`, CSV/topology seed
`51966`, and congestion-process seed `52066`.

**Regression gate:** the three tests passed twice in fresh processes (`3 / 3`
both times, approximately `0.66 s` per process). `git diff --check` is clean;
`sim.py` remains byte-for-byte unchanged at SHA-256 `815d499a…`; the frozen
result tree still contains `63` CSVs and `21,210,573` bytes. No production
campaign was run, no frozen datum was written, and nothing was staged,
committed, or pushed.

**Next gate:** add the allocator seam with the legacy mode as the default, then
pair each fixture's default call with an explicit
`link_local_equal_share` call. Both paths must retain the exact bits above
before `network_maxmin` or any pilot is allowed to run.

### Unit 4 — allocator implementation complete, awaiting Ibrahem review

**Before:** `sim.py` had one implicit rate rule and no selectable allocator.
The independent sidecar established the intended network-wide max-min behavior,
but production runners could not request it and existing drivers could silently
reuse only the legacy model.

**After:** `sim.py` now exposes two explicit modes:
`link_local_equal_share` and `network_maxmin`. The legacy mode remains the
default, and the choice is propagated through the simple, proportional,
adaptive, and pipelined All-Reduce runners. The static full-concurrency
reference is mode-aware. The proportional-runner docstring no longer calls the
legacy calculation max-min or a universal upper bound.

The new allocator is network-wide unweighted progressive filling over all
active foreground and background flows and directed links. Its heap
implementation stores frozen load and active-user counts. The simulator caches
only path/user structure while the active flow set is unchanged; residual
capacities are recomputed every tick. The cache is explicitly tested across
flow arrival, flow completion, and changing congestion. Fixed ECMP paths are
the cache contract.

**Self-correction during review:** the first candidate used a tolerance scaled
by the largest capacity. Independent review showed that an unrelated large link
could then merge distinct small bottlenecks. A second review exposed the same
class of problem below `1e-12 B/s` due to an absolute floor. Both were fixed
before any pilot by using local ULP-scale comparisons, and permanent
heterogeneous- and tiny-capacity regressions were added. These were real generic
allocator defects even though neither affected the capacity range of the paper.

**Correctness gate:** the current `17` automated tests pass twice. They cover
the canonical `(20,50)` legacy versus `(20,80)` max-min example; capacity
feasibility; a max-min bottleneck certificate for every flow; the componentwise
legacy lower bound on `1,000` deterministic random networks; directed-edge
independence; zero capacity; pathless flows; order, ID, and scale invariance;
invalid inputs; a mode-aware static reference; all four runner paths; byte
conservation; and cache invalidation/recomputation. A separate comparison with
the original sidecar oracle covered `1,000` networks and `8,045` flows with zero
mismatches. Two independent reviews then matched the implementation to an exact
rational progressive-fill oracle on `30,000` random networks spanning roughly
`10^-250` to `10^250`, plus `2,000` stress cases with `50--800` flows, with no
remaining correctness finding.

**Legacy and sentinel gate:** default and explicit legacy calls reproduce N0,
O0, and C10 at the exact IEEE-754 payload. An independent reviewer also compared
the new default against the `sim.py` at `HEAD` across congestion and all four
runners and found it byte-exact. Selected no-congestion, on/off, and combined
oversubscription-plus-hot-spot production calls matched the independent sidecar
sentinels to the last bit. Those sentinels remain diagnostic and their effect
percentages are not paper findings.

**Performance gate:** profiling found repeated path/user reconstruction in the
first correct implementation. Caching immutable structure reduced the measured
one-worker max-min wall time for the worst sampled
`4:1/P=64/k=32/on-off/256 MiB` case from `56.705 s` to `8.496 s`, with identical
simulated completion time; its paired legacy call took `4.971 s`. The sampled
proportional `k=16` max-min call took `4.658 s` versus `3.159 s` for legacy.
Frozen-controller and background endpoint checks were also completed. These are
runtime diagnostics only, not scientific estimates.

**Mutation guards:** current `sim.py` is `63,083` bytes, SHA-256
`40edbacc28e61bb25769278382506c32611cf7fd9e14777480b6fd3d664fab69`.
All `63` frozen CSVs still match the immutable manifest (`0` mismatches,
`21,210,573` bytes, root `09a1418e…`). No frozen datum, paper figure, or paper
number was changed; no result directory was created; nothing was staged,
committed, or pushed.

**Next proposed gate, not started:** implement a fail-if-exists paired driver,
dry-run its matrix, then run a timing-only `n=5` profile on seeds
`{0,17,43,71,99}`. The reviewed minimal profile has `90` pair IDs (`180`
simulations) and covers no-congestion topology/split, all four congestion
regimes, oversubscription plus congestion, the frozen controller, and background
All-Reduce. It must stop after reporting a measured per-family ETA; it must not
auto-start `n=100`. The decision-complete `n=100` proposal currently contains
`134` arms per allocator, or `26,800` simulations total.

### Unit 5 â€” bounded `n=5` timing and coverage gate complete

**Before:** Unit 4 had a correct selectable allocator and exact legacy
regressions, but no fail-closed paired campaign driver, no measured whole-matrix
runtime, and no evidence that the frozen controller remained active under the
new allocator. The approved next action was limited to five sample IDs
`{0,17,43,71,99}` and had to stop before `n=100`.

**Driver and authorization:** added
`experiments/run_rate_allocator_pilot.py` and the read-only structural suite
`validation/test_rate_allocator_pilot_driver.py`. The driver hard-codes `18`
arms, `90` pair IDs, and `180` simulations; balances allocator-first order
`45/45`; builds fresh topology, congestion/background, ring, and simulator
state for every half-pair; writes one atomic parent-owned checkpoint only after
both halves pass; refuses existing output; supports locked crash recovery; and
contains no `n=100` execution path. The final dry-run printed the complete
canonical plan and bound approval to plan, driver, and `sim.py` hashes. Its
authorization was `93d1bd2c106ebcdd80dfdd6d939531a0ba9630c86fd7ca8ab3e01bea3254117e`;
the driver was `777018e1a408eb5274d5ee87700fc66e4396fd5d39722f625f22e48840efc431`
at execution and `sim.py` remained `40edbaccâ€¦`.

**Self-corrections before the successful run:** two fail-closed attempts were
preserved rather than overwritten. `_01` stopped on an adaptive byte-accounting
check at `1.430511474609375e-6 B` with zero remaining bytes; this is exactly `24`
ULPs at a `256 MiB` target. `_02` stopped on a simple-flow accumulated-byte
check at `1.2516975402832031e-6 B`. A direct five-seed/two-allocator audit found
a maximum simple discrepancy of `24.5` target ULPs. A background All-Reduce
preflight then found bit-level differences in only `2/480` foreground flows at
`k=1` and `16/1,920` at `k=4`, with maxima `2.0489e-8 B` and `1.397e-9 B`, zero
remaining bytes, and identical behavior under both allocators. No-background
All-Reduce was bit-exact. These findings exposed over-strict audit predicates,
not simulator or methodology defects. The validation-only gates now allow at
most `64` local binary64 ULPs for simple accumulation, adaptive overshoot, and
per-flow All-Reduce accumulation, while adaptive absolute error/remaining stay
bounded by `1 B`, All-Reduce remaining must be exactly zero, and independent
step and total checks remain at `64` ULPs. A `128`-ULP error is rejected in the
permanent tests. Neither `sim.py` nor a completion result changed.

**Successful gate:** `investigations/rate_allocator_pilot/n5_2026-08-06_03`
completed all `90/90` pairs and `180/180` runs in one measured pool segment and
wrote `COMPLETE.json` with status
`pilot_finished_ready_for_n100_decision`. Counts are exactly `100` simple, `20`
proportional, `20` adaptive, and `40` All-Reduce rows, with `36` rows per sample
ID and `90` per allocator. The legacy half matched `85` frozen rows by exact
IEEE-754 payload; the five OS4/hot-spot/proportional cross-factor rows are
explicitly `new_diagnostic`, not disguised frozen matches. Maximum recorded
byte-accounting error was `2.9802322387695312e-6 B`; maximum foreground remaining
was `0 B`.

**Controller coverage:** all five max-min runs were active in both approved
controller cells. The `af=0.1` cell recorded `339` add-flow events across its
five samples and the `af=0.5` cell recorded `820`. These are coverage counts,
not performance estimates; they show that the frozen controller did not collapse
to a no-op under `network_maxmin`, so no extra diagnostic cell is required before
an `n=100` decision.

**Measured ETA:** the eight-worker pool took `17.3225 s`, with measured effective
parallelism `7.057` for simulation-only work and `7.265` end-to-end. No pilot arm
crossed `60 s`; the slowest observed single run was about `2.61 s`. Applying the
approved `134`-template-per-allocator, `26,800`-simulation proposal gives a
heuristic eight-worker end-to-end `n=100` estimate of `0.685 h` centrally, with
scenario bounds `0.155--1.543 h`. These are min/median/`1.25Ã—max` runtime
scenarios, not confidence intervals. The placement contribution still uses a
conservative static/split proxy and must be labelled provisional. No `n=100`
run was started, and no `n=1000` ETA is reported before measuring `n=100`.

**Final mutation and scope guards:** the allocator/driver suites pass `25/25`.
All `63` frozen CSVs still match the immutable snapshot (`21,210,573` bytes,
root `09a1418eâ€¦`); the complete `results/` tree matches the run manifest;
`sim.py` is still `63,083` bytes / `40edbaccâ€¦`. No frozen datum, paper number,
or paper figure was changed. `_01` and `_02` remain incomplete audit trails;
`_03` is the sole completed pilot. Everything remains unstaged and uncommitted;
there was no commit or push.

**Next decision, not authorized here:** either approve the reviewed `n=100`
campaign (estimated central wall time about `41` minutes on eight workers) or
first refine the provisional placement proxy. The pilot effect ratios must not
be cited as scientific findings; their role is timing, regression, conservation,
and controller-coverage validation only.

### Unit 6 - complete paired `n=100` revalidation and analysis

**Exact scope:** the production-driver inventory was rebuilt rather than copied
from the timing pilot. It contains `134` arms: `80` static split, `16`
congestion, `24` frozen-controller, `8` background, and `6` direct placement
arms. With samples `0..99` and two allocators this is `13,400` complete pairs
and `26,800` simulations. The earlier pilot timing proxy's `81/23` family
classification was not reused; direct placement is present here. The fixed plan
hash is `47099eedb41d1574cc49a6e08a2f7bb20b6c14077531b32b80222be9519291ac`.

**Fail-closed corrections before completion:** two incomplete attempts remain
preserved as audit trails. `n100_2026-08-06_01` stopped after `9,794`
checkpoints because a pilot-era adaptive audit assumed a `64`-edge ring and
rejected a valid `P=16` controller map. The n=100 wrapper now checks the
authorized ring size and `k_max`; the simulator and scientific result did not
change. `n100_2026-08-06_02` stopped after `11,178` checkpoints on a simple-flow
byte error of `4.559755325317383e-6 B` in the legacy
`P=64, af=0.1, baseline, seed=80` controller cell. Direct reconstruction showed
zero remaining bytes, exact frozen completion time, and the same binary64
counter-scale effect under max-min. The error is about `76.5` target ULPs at
`256 MiB`, or roughly `1.7e-14` of the target. The n=100 validation-only simple
gate therefore uses a `128` target-ULP envelope; a permanent test accepts the
`128` boundary, rejects `256`, and still requires exactly zero remaining bytes.
The pilot/core gates for the other runners remain unchanged.

Before the clean attempt, `41/41` allocator, legacy, pilot, n=100, spawn, and
source-binding tests passed. A separate worst-tail preflight replayed the
slowest frozen sample in every one of the `24 + 8 + 6 = 38`
controller/background/placement arms: `38/38` exact legacy matches, zero
remaining bytes, and maximum conservation error `1.8775463104248047e-6 B`.

**Successful sealed run:**
`investigations/rate_allocator_n100/n100_2026-08-06_03` completed in one timing
segment under authorization
`db7c48d266e713408b250308d062798cf24319edad60b8261cb5b449529aa97e`.
Execution hashes were n=100 driver `7d01a2e...`, paired engine `777018e1...`,
and `sim.py` `40edbacc...`. `COMPLETE.json` reports
`n100_revalidation_complete_ready_for_analysis`; a read-only `--resume` check
returned exit `0`. An independent audit then rehashed all `13,400`
checkpoints, the timing segment, all four exports, and both manifests. Counts
are exactly `13,400` rows per allocator and `100` samples in each of `134`
arms. All `13,400` legacy halves are exact binary64 frozen matches; all
`13,400` max-min halves are explicitly new-allocator rows. Maximum recorded
conservation error is the already-audited `4.559755325317383e-6 B`; maximum
remaining foreground bytes is `0`.

The sealed frozen snapshot is still `63` CSVs / `21,210,573` bytes / root
`09a1418e965b9c2d597721ff0d3b1e8db937a19ce667accfa2cf1f469664c24e`.
The pre-existing `results/` tree is still `99` files / root
`d63aba765ee1aecb338e5fa3cf3e083fc2999bfe1a16cd7c695a051821b3a129`.
No frozen row, paper source, figure, or paper number changed.

**Paired scientific result:** the reproducible analysis is sealed separately at
`investigations/rate_allocator_n100/n100_2026-08-06_03_analysis`; its verification
mode passes. It uses `20,000` percentile-bootstrap draws. Each arm is analyzed
as paired `n=100`; the cross-cell headline resamples the `100` sample IDs as
clusters and keeps all `32` matched equal/proportional cells together inside a
draw. This avoids pretending that the `3,200` cell rows are independent.

For the static sweep, all `4,800` equal-split pairs are bit-identical across
allocators. Of `3,200` proportional pairs, max-min is faster in `1,036`,
bit-identical in `2,164`, and slower in `0`. Consequently the geometric
proportional-over-equal advantage rises from `1.132643` under the legacy local
model to `1.165098` under network max-min. The ratio of those advantages is
`1.028654`, with seed-clustered 95% CI `[1.027142, 1.030205]`. In plain terms,
the local allocator masked about `2.87%` of proportional splitting's
multiplicative advantage in this matrix. Of the `32` cells, `23` have a
positive geometric amplification, `9` are exactly unchanged, and `0` weaken;
`19` of the `23` also have a pointwise 95% CI above one. Those cell intervals
have no multiplicity correction, so the seed-clustered result is the primary
inference. The largest point estimates are `2tier/P=64/k=8` (`1.1457`),
`3tier_os2/P=64/k=4` (`1.1219`), and `3tier_os4/P=64/k=8` (`1.1161`).

**Controller boundary:** fixed policies contain `12,600` pairs and have zero
max-min-slower cases. The exception is the adaptive controller whose thresholds
were deliberately frozen for allocator isolation: among its `800` pairs,
max-min is faster in `549`, bit-identical in `167`, and slower in `84`. The
adaptive event count changes in `523/800` pairs, including `70/84` of the slower
ones. This does not overturn the fixed-state max-min rate bound; it shows that
the rate model changes the controller's decisions and trajectory. These
controller numbers are diagnostic only. A fair method comparison requires
recalibration on declared, disjoint tuning seeds before evaluation seeds are
run.

**Runtime and next gate:** measured eight-worker pool time is
`1,709.2803 s` (`28.49 min`), with end-to-end effective parallelism `7.920`.
The same-matrix linear `n=1000` planning projection is `4.748 h`; it is not a
confidence interval. No `n=1000` execution path was invoked and no `n=1000`
run was started. The next recommended unit is to freeze a controller-calibration
protocol and disjoint seed sets, run a bounded calibration pilot, and return
its selected thresholds plus holdout gate before deciding which full `n=1000`
families to authorize. Everything remains unstaged and uncommitted; there was
no commit or push.

### Proposed Unit 7 - controller recalibration protocol, not started

The bounded recommendation is to tune only the rate threshold
`theta in {0.10, 0.15, 0.20, 0.25, 0.30}`. Keep the mechanism-defining
`1 ms` measurement window, `10 ms` cooldown, and `k_max=4` fixed. This avoids
turning calibration into a new controller design or a large generic grid.

Use `32` declared tuning sample IDs from a new namespace outside both `0..999`
and the frozen campaign, across `P in {16,64}` and
`af in {0,0.1,0.3,0.5}`. Each seed/cell runs the five adaptive thresholds plus
paired baseline and static `k=4`, for `8 * 32 * 7 = 1,792` max-min simulations.
Select one threshold once. Then evaluate that locked threshold on `100` new,
disjoint holdout IDs with baseline and static `k=4`, for
`8 * 100 * 3 = 2,400` simulations. A holdout failure is reported as a failure;
it must not trigger another tuning round on the holdout seeds.

The selection objective must be resource-aware rather than completion-only,
or the optimizer will trivially reproduce static `k=4`. The proposed primary
anchors follow the paper's existing controller story: on `P=64, af=0.1`, the
upper paired 95% CI for `T_adaptive/T_static4` is at most `1.03` while mean QP
cost is at most `0.60` of static `k=4`; on `P=64, af=0.5`, the corresponding
limits are `1.05` and `0.95`. The `af=0` cells are negative controls and
`af=0.3` is a transition/robustness cell. Among thresholds satisfying the
anchors, minimize equal-cell-weight mean QP cost; break a tie by the smaller
worst-cell completion ratio and then by closeness to the existing `0.20`.
These numerical anchors require Ibrahem's explicit approval before execution.

Measured n=100 controller worker times project about `2.6 min` for tuning and
`3.9 min` for the holdout on eight workers, before a conservative overhead
allowance. These are planning estimates, not confidence intervals. No Unit 7
runner or output has been created and no calibration simulation has started.

### Unit 6B - corrected proportional current-boundary revalidation complete

**Question and frozen scope:** Audit v2 showed that proportional splitting had
retained the previous interval's `last_rate_Bps` when constructing the next
boundary weights. The corrected implementation uses the prospective current
boundary snapshot. The frozen revalidation covered only the complete static
proportional matrix: `32` arms, samples `0..99`, `3,200` paired jobs, and
`6,400` simulations. It included no controller, congestion, background, TCP,
or `n=1000` cell. The frozen specification is
`investigations/CORRECTED_PROPORTIONAL_N100_SPEC_2026_08_07.md`, SHA-256
`0bfb2286b52f0dc5266c8e80a08e7d2de8e7508565e5f07b25caee8e4a508090`.

**Fail-closed operational correction:** the first clean attempt,
`investigations/corrected_proportional_n100/n100_2026-08-07_01`, completed all
`3,200` checkpoints and all twelve analysis exports, but Windows rejected a
second-handle read of the byte-locked `.run.lock` while the completion inventory
was being hashed. It therefore has neither `completion_manifest.json` nor
`COMPLETE.json` and is not a completed campaign. It remains untouched as an
audit trail: `3,217` prior-final files, `41,140,189` bytes, tree digest
`be3af87a965e4c0dbf277c5611287ea83cbb39ce79a84b8e29837db425028258`.
The production driver now hashes and verifies `.run.lock` through the already
held lock handle, while retaining the lock as a signed artifact. Path, file
identity, size, timestamp, and before/after stability checks fail closed. The
Windows regression and the full focused suite pass `17/17`.

**Successful sealed run:** the final driver SHA-256 is
`7b65d37635a3d8315517f0076602cb4c663c1c0659ef1dbb3ee56e3053b10f9b`.
The absent-output dry-run authorized
`investigations/corrected_proportional_n100/n100_2026-08-07_02` with
`13335625e7cb960694bd201c6856e6e65bb9b666f59a7507ae3e053eefb456b8`.
The mandatory `33`-pair preflight passed before the remaining `3,167` pairs.
The run exited `0`, signed `3,217` prior artifacts, and wrote `COMPLETE.json`
last. Its completion-manifest SHA-256 is
`6355cda3b07e025da2e88c8544a1a82760212510203e1b5f0ba08930c6691810`;
its analysis SHA-256 is
`119978e8c6edca3dfe58a1b5d55b9d6d628c9bec2fe778f260d105d7a89120ca`.
The independent auditor returned
`PASS_INDEPENDENT_CORRECTED_PROPORTIONAL_N100_AUDIT`. Frozen inputs, Audit v1,
Audit v2, the historical campaign, and the existing `results/` tree retained
their authorized roots. `n1000_started` is `false`.

**Scientific result:** the predeclared paired estimand is
`R = T_network_maxmin / T_link_local_equal_share`. Across the `3,200` pairs,
the seed-clustered geometric mean is `0.972203291`, with deterministic 95%
bootstrap interval `[0.970734487, 0.973630124]`. Network max-min is faster by at
least two `50 us` ticks in `970` pairs, faster by one tick in `66`, exactly tied
in `2,164`, and slower in `0`. The inverse ratio is about `1.0286`, so the
network allocator improves the geometric completion factor by about `2.86%`
in this static proportional matrix. Leave-one-seed-out values remain within
`[0.972075, 0.972455]`; no single seed controls the conclusion.

The current-boundary correction changes `65/6,400` allocator rows across `61`
pairs relative to the sealed historical execution: `55` rows move by `-1`
tick, `8` by `+1`, and `2` by `+4`. There is no material ordering reversal.
The historical global ratio was `0.972144248`; the corrected value changes it
by only about `0.0061%` relatively. Thus the correction is methodologically
necessary but does not overturn the allocator conclusion. Under the same
allocator, no corrected proportional row is slower than its matched equal row
by more than the one-tick tolerance. The equal-over-proportional geometric
factor is `1.132734` under link-local allocation and `1.165121` under network
max-min, a ratio of about `1.02859`.

**Replication check and boundary:** all scientific exports from the unsealed
`_01` and sealed `_02` are byte-identical. In `results_long.csv`, the only
differences are the four declared wall/CPU timing fields; all scientific fields
are identical in all `6,400` rows. The accepted stopping status is
`READY_TO_DECIDE_PROPORTIONAL_N1000_SCOPE`, not authorization to execute it.
The result supports only the static proportional matrix. It does not establish
a controller, congestion, background, TCP, or general-workload claim. No paper
edit, commit, push, or `n=1000` run was performed in this unit.

**Recommended next gate, not started:** do not extend all `32` arms immediately.
The global static-proportional question is already decision-complete; the
remaining uncertainty is arm heterogeneity. If Ibrahem authorizes a scale-up,
use an eight-arm confirmatory extension with samples `100..999`, analyzed
separately from the discovery samples:

- `2tier`: `P=64,k=8` and `P=16,k=8`;
- `3tier_nb`: `P=64,k=4` and `P=16,k=4`;
- `3tier_os2`: `P=64,k=4` and `P=64,k=16`;
- `3tier_os4`: `P=64,k=8` and `P=64,k=4`.

These are four strong-versus-near-null contrasts selected from the completed
`n=100` discovery result. The extension would add `7,200` paired jobs and
`14,400` simulations. At the measured `22.1653` pairs/s, raw pool time is about
`5.4 min`; allow roughly `8--12 min` including validation, analysis, signing,
and independent audit. Because legacy results for the conventional `0..999`
seed range already exist, call this a predeclared confirmatory extension, not a
blind holdout. Require the four high-effect holdout intervals to remain below
one; estimate the near-null non-tie incidence without forcing significance or
claiming equivalence. Do not report a selected-subset global mean. A full
`32`-arm extension would add `28,800` pairs and mainly narrow an already
decisive global interval. Controller calibration remains a separate Unit 7 and
must not be bundled with this static confirmation.

### Status continuation — 2026-08-08

The “uncommitted” and “commit/push forbidden” statements above record the
authorization boundary in force when the corresponding units were executed.
They are preserved as historical execution facts, not as the current repository
state. Ibrahem later explicitly authorized a reviewed commit/push checkpoint
before any `n=1000` execution; exact repository and Overleaf commit hashes are
recorded only after their publication gates pass.

The allocator implementation, byte-exact legacy regression, sealed paired
`n=100` revalidation, and corrected-current-boundary audit are complete. The
frozen paper-producing results remain unchanged and continue to describe the
link-local equal-share model. The new `network_maxmin` evidence is a separate
revalidation branch and must not be substituted into the paper before its own
integration decision.

The eight-arm extension proposed in Unit 6B was considered and superseded by
Ibrahem’s explicit decision to run all `32` canonical static-proportional arms
for samples `100..999`, paired under both allocators. This is an authorization
and coverage decision, not a result. No `n=1000` allocator claim may enter the
paper until the extension passes source binding, preflight, completion sealing,
independent audit, and the predeclared combined `0..999` analysis. Controller
recalibration remains a separate Unit 7 and is not bundled with this static
extension.

The reviewed pre-`n=1000` scientific baseline was published on 2026-08-08 as
ring-simulator commit `bde20148389772cceab9dd2c81f25e8f26c658ba`; the branch
then measured `0/0` against `origin/ibrahim-paper`. The canonical Overleaf clone
remained clean and unchanged at `887efcf` because all six live figure PDFs were
already byte-identical. Full raw evidence for the successful pilot and `n=100`
campaigns is retained outside source Git in five read-only, content-addressed
archives indexed by `SEALED_ARTIFACT_ARCHIVE_INDEX_2026_08_08.json`. The index
records that no off-machine replica has yet been established; the source trees
remain present and were not deleted.
