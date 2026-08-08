# Corrected proportional n=1000 extension contract (2026-08-08)

## Purpose and scope

This is a fixed-size, paired validation extension of the corrected proportional
allocator study.  It runs the 32 canonical proportional arms (`a049` through `a080`) for
seeds 100 through 999.  Each pair is evaluated once with
`link_local_equal_share` and once with `network_maxmin`, from independently
constructed mutable instances whose serialized config, topology, ring, route,
and process-initial-state digests are identical.

The extension-only result is the primary result.  A secondary n=1000 summary
combines it with the sealed corrected n=100 compact exports for seeds 0 through
99.  The secondary join is read-only and must not consult ignored/raw n=100
checkpoints.  No equal-policy, controller, congestion, background, placement,
or recalibration arm is part of this campaign.

This is not a blind holdout or a confirmatory sample.  The earlier n=100 result
informed the decision to extend, legacy v11 link-local rows already exist for
all extension seeds, and a prior diagnostic max-min gate observed six exact
pairs in four seed clusters (174, 199, 353, and 657).  Neither v11 nor that
diagnostic is an estimator input here.  A predeclared sensitivity view removes
all four exposed seed clusters from the same extension result.

## Immutable lineage

- Immutable baseline ancestor:
  `f2d8f88ec3cef01c250987df88245dc4361c245b`.
- A fresh execution must start at a clean, pushed current HEAD whose history
  contains that baseline.  The current HEAD, upstream 0/0 state, source bytes,
  output path, worker count, and plan digest are bound into the dry-run
  authorization.  The execution commit is therefore expected to be later than
  the baseline commit that preceded this sidecar.
- Scientific source bytes are pinned by SHA-256 in the driver: `sim.py`, the
  canonical n=100 matrix driver, the paired production worker, the corrected
  n=100 driver, and this specification.
- The prior max-min gate source is separately byte-bound only to establish the
  declared exposure set.  Its outcomes are provenance, not estimator data.
- Resume permits only files below the authorized output directory to make the
  Git worktree non-clean.  An unrelated dirty path is fatal.

The current-input seal is intentionally narrower than a frozen-results-tree
seal: no legacy `results/` artifact is an execution or primary-analysis input.
Only source bytes and the explicitly named compact corrected-n=100 bundle are
bound and reverified before/after.  Legacy v11 and the sentinel diagnostics are
excluded rather than silently bound as data inputs.

The sealed n=100 compact reference is
`investigations/corrected_proportional_n100/n100_2026-08-07_02`:

| File | SHA-256 |
|---|---|
| `COMPLETE.json` | `ab9945a3d9826fc1a75af55657e65f246369bb322ed676972a379f9f33bf21ed` |
| `completion_manifest.json` | `6355cda3b07e025da2e88c8544a1a82760212510203e1b5f0ba08930c6691810` |
| `pairs.csv` | `d3acdacc328dfa567c816918b331ff8f6ef8bf27c36e226b0083aa4860e81f9b` |
| `results_long.csv` | `e599ea81f137abe0daee218ad465d86668e8a9ba38d40e7c7eb3a9f23461c7c8` |

The driver verifies the four files, the COMPLETE-to-manifest link, and the
compact CSV bijection before it creates a new output directory.  It also
recomputes every n=100 canonical config SHA-256 and matches it to both allocator
rows in `results_long.csv` via the run manifest signed by the completion
manifest.

## Fixed matrix and deterministic order

- Canonical arm indices: 48 through 79 (human IDs `a049` through `a080`).
- Extension seeds: exactly 100 through 999.
- `sample_index = sample_id`.
- Pair ordinal: `arm_index * 1000 + sample_id`.
- Allocator order alternates by ordinal parity.  The complete extension has
  14,400 pairs in each allocator-first order.
- Extension: 32 arms x 900 seeds = 28,800 pairs = 57,600 simulations.
- Secondary combined view: 32 arms x 1,000 seeds = 32,000 pairs.

Canonical SHA-256 gates (canonical JSON encoding) are:

| Payload | SHA-256 |
|---|---|
| 32-arm list | `467f87d72a89bf9bb15e80d824f43a5465f6731e3b890f1cea05e93a0f383b09` |
| extension pair-ID list | `12f52040dbc480e3566dd9d25c4c89ae4d4cf40910bf5c30fc6834a54817268c` |
| combined pair-ID list | `3bd51d5ba6f303b4dcd0750f7a18d1e9c9a310962dfa339454cd6d9809f24717` |

The existing v11 frozen values for seeds 100 through 999 are not controls and
are not inputs to this campaign.  They may be examined later only as clearly
labelled diagnostics of the superseded link-local run.

## Preflight and execution

The mandatory preflight is all 32 arms at seeds 100 and 101: 64 paired jobs,
128 simulations.  It must establish:

1. the exact pair-ID set and 32/32 allocator-first balance;
2. two allocator rows per pair with matching initial-state digests and distinct
   mutable instances;
3. positive finite timing, exact execution positions, and the strengthened
   proportional conservation gate (all logical edges complete, zero remaining
   foreground bytes, and at most 1e-6 byte maximum absolute error);
4. immutable sources and compact n=100 seals unchanged;
5. signed preflight checkpoints and timing coverage.

Only after `preflight_complete.json` is written and reverified may the remaining
28,736 pairs run.  `--preflight-only` deliberately stops at that boundary;
`--resume` continues the same signed run.  Every checkpoint is create-once.
Interrupted timing coverage is recovered as a new signed timing segment; an
existing segment or checkpoint is never overwritten.

A crash after `completion_manifest.json` but before `COMPLETE.json` is a legal
partial state.  Resume must revalidate that manifest and may write only the
missing, last completion marker.  Any arbitrary extra root artifact remains
fatal in every partial state.

There is no adaptive stopping.  This is a fixed n=1000 validation.  A run is
complete only with all 28,800 extension pairs and 57,600 allocator rows.

## Output boundary

The only legal output root is a direct child of
`investigations/cp_n1000`.  A fresh target must
not exist.  `results/`, the sealed n=100 tree, and every other campaign tree
are read-only.

Partial root allowlist:

- `.run.lock`
- `run_manifest.json`
- `preflight_complete.json`
- `checkpoints/`
- `timing_segments/`

Final root additions:

- `results_long.csv` (57,600 extension rows)
- `pairs.csv` (28,800 extension rows)
- `arm_analysis.csv` (32 extension summaries)
- `combined_arm_analysis.csv` (32 secondary summaries)
- `analysis.json`
- `runtime.json`
- `gate.json`
- `completion_manifest.json`
- `COMPLETE.json` (written last)

No other root file or directory is accepted.  Empty atomic-write staging
directories are removed before sealing.  The completion manifest hashes every
artifact except itself and `COMPLETE.json`; `COMPLETE.json`, written last,
hashes the completion manifest and run manifest.

## Analysis contract

For every pair, the primary effect is

`network_maxmin completion time / link_local_equal_share completion time`.

Ratios below one favor network max-min.  The global estimate is the exponential
of the mean log-ratio.  Uncertainty uses a seed-cluster bootstrap: a seed is the
resampling unit and its 32 arm log-ratios stay together.  PCG64 seed 20260807
and 20,000 replicates are fixed.  The raw little-endian uint32 bootstrap-index
matrix hashes are:

| Scope | Shape | SHA-256 |
|---|---|---|
| extension primary | 20,000 x 900 | `901e342e8d8849fcdd8bec11e7019b6b1a24d2ab73d62c61ec8eba8009f171d4` |
| extension sensitivity (excluding 174, 199, 353, 657) | 20,000 x 896 | `92c451c7526085b32723402f91f2b06c0806e5345ebd6a74122db6267d1481ea` |
| combined secondary | 20,000 x 1,000 | `983cc7176ab26dfcbaa22467b888439c67557da634f2bf3945721c64e42c3070` |

The global directional label is mechanical and limited:

- upper 95% bootstrap bound below 1: `network_maxmin_faster`;
- lower bound above 1: `link_local_equal_share_faster`;
- otherwise: `global_interval_includes_one`.

The interval quantifies placement-seed-cluster variation conditional on this
fixed 32-arm topology/model matrix.  It is not population-wide uncertainty and
does not include topology-family or network-model uncertainty.  Per-arm
summaries are descriptive.  The 896-cluster exposure sensitivity is also
descriptive, and the secondary combined estimate is labelled secondary
everywhere.  No result automatically changes a paper claim: the final gate
requires an independent audit and an explicit research decision.

## Completion gates

`COMPLETE.json` is permitted only if all of the following hold:

- exact matrix, pair-ID, source, Git-lineage, and output-boundary gates pass;
- all checkpoints and rows pass conservation and paired-initial-state checks;
- seed/arm/allocator bijections are exact;
- the sealed n=100 compact rows are exactly seeds 0 through 99 and join without
  overlap to the extension's seeds 100 through 999;
- extension, 896-cluster sensitivity, and combined bootstrap-index hashes match
  this specification;
- `analysis.json`, both CSV summary layers, runtime, and gate agree on all
  cardinalities and digests;
- immutable sources and compact references match before and after execution.

The completion status is
`COMPLETE_PENDING_INDEPENDENT_AUDIT_AND_RESEARCH_DECISION`.  The output remains
an investigation artifact until its independent auditor passes.
