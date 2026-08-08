# Corrected proportional n=100 revalidation — frozen specification

Date frozen: 2026-08-07 (Asia/Jerusalem)

Status: authorized research revalidation after the sealed Audit v2 PASS. This
campaign is proportional-only and has no `n=1000` execution path.

## Question

Across the complete proportional matrix and the same 100 paired seeds used by
the prior allocator campaign, what changes after replacing retained
`last_rate_Bps` weights with the prospective current boundary snapshot, and how
does `network_maxmin` compare with `link_local_equal_share` under the corrected
mechanism?

The prior n=100 campaign is an immutable historical reference. Its proportional
completion times are not an oracle for corrected execution and are never an
exact-match gate.

## Immutable inputs

- corrected `sim.py`: `96505cefe2e5aa761b80080d77145bfd384c688ce4a8ca5792f8f7ce17ef59bd`
- canonical n=100 plan/topology wrapper:
  `7d01a2e598c799b0c533fb650f33b8537f51fa3187f427fcf9ada108d56fd8b4`
- paired execution core:
  `777018e1a408eb5274d5ee87700fc66e4396fd5d39722f625f22e48840efc431`
- sealed Audit v2 `COMPLETE.json`:
  `046f980e20312b2ff988ec3fd1a1185cd2df9c261acf4da61168a658661cccd9`
- historical n=100 `COMPLETE.json`:
  `c4caaf8bb203eff3b815236c3bc848d8d483b521571c3ab71a47a32f135eadfa`
- frozen-results root:
  `09a1418e965b9c2d597721ff0d3b1e8db937a19ce667accfa2cf1f469664c24e`

The new driver and this specification are bound by the dry-run authorization.
All inputs, the frozen CSV tree, the repository `results/` tree, Audit v2, and
the historical campaign are checked before, after, and before final sealing.

## Fixed matrix

The driver filters the current canonical n=100 plan without regenerating arm
semantics or renumbering pair IDs:

- 4 fabrics: `2tier`, `3tier_nb`, `3tier_os2`, `3tier_os4`;
- ring sizes `P=16,64`;
- QP counts `k=2,4,8,16`;
- seeds `0..99`;
- allocators `link_local_equal_share` and `network_maxmin`;
- runner/policy: static `proportional` only;
- redistribution window: 1 ms; `dt=50 us`.

Total: 32 arms × 100 paired seeds = 3,200 checkpoints and 6,400
simulations. Allocator-first order remains balanced 1,600/1,600. No controller,
congestion, background, placement, equal split, or `n=1000` cell is reachable.

The canonical retained arm and pair identifiers are immutable: arms `a049`
through `a080`, with pair-ID-list digest
`72c14abfa494a0896b79aa75abf5d8071e6697f14e2e323963a869a62bda31da`.

## Execution and historical reference

Each paired worker is the existing production worker and runs both allocators
from independently rebuilt but digest-identical initial state. The parent then
joins the corresponding checkpoint from the sealed historical n=100 campaign.
For both allocators it records old/new completion hex, tick and relative delta,
but never requires equality. Pair specification and config/topology/ring/route
and process-initial digests must remain exact across the historical join.

The campaign is resumable only from its own manifest and atomic checkpoints.
The fixed output is a new absent child of
`investigations/corrected_proportional_n100/`; `results/`, Audit v1/v2, the
historical n=100 tree, and every other existing output are forbidden targets.

Execution has two durability phases inside that same output and manifest. The
mandatory preflight first runs seed 0 for all 32 arms plus the already audited
pair `a079_proportional_2tier_p64_k8__s066`, for 33 pairs total. The preflight
must be sealed and pass its source, pair, conservation, historical-join, and
applicable Audit-v2 checks before the remaining 3,167 pairs may be scheduled.
Its Audit-v2 overlap is exactly four pairs/eight allocator rows: seed 0 for
arms `a069`, `a072`, and `a079`, plus `a079...s066`. The 6.15 ms named anchor
is therefore a preflight gate; the 6.30 ms `a072...s033` anchor is deliberately
deferred to the complete-campaign gate rather than silently added as a 34th
preflight pair.

Because all 33 selected sample IDs are even, their canonical first-allocator
order is intentionally 33 link-local / 0 network-max-min. This preflight cannot
test an order-specific wrapper defect. A no-simulation synthetic unit bridge
therefore passes a canonical odd-sample pair with the reverse order through the
new wrapper unchanged; the complete-campaign gate, not the preflight, enforces
the final 1,600/1,600 first-position balance.

## Hard gates

1. The plan is self-hashed and byte-semantic-equal to a fresh filter of the
   canonical n=100 plan: 32 arms, 3,200 unique pairs, 6,400 rows.
2. Every checkpoint contains exactly both allocators, execution positions 0/1,
   identical config/topology/ring/route/process-initial digests, and distinct
   mutable simulator/topology instances.
3. Completion, wall time, and simulation wall time are finite and positive;
   CPU and simulation-CPU times are finite and non-negative because a Windows
   clock sample may legitimately be zero. There are exactly `P*k` foreground
   flows and the integer conservation-check count equals `P` per row;
   every logical edge carries exactly 64 MiB within `1e-6` byte, every final
   foreground remaining-byte value is finite and exactly zero, and all
   conservation quantities are finite. The worker inspects those individual
   values while the simulator is alive and persists their nonzero count,
   minimum, and maximum; the existing clipped aggregate alone is not accepted
   as proof of per-flow completion.
4. Historical joining is bijective for all 3,200 pairs and 6,400 allocator
   rows. Config/topology/ring/route/process-initial digests must match; outcome
   equality is diagnostic only.
5. Every seed contributes exactly 64 rows; every arm contributes exactly 200
   rows; allocator order is balanced; no unplanned family or runner appears.
6. Sources and immutable trees are unchanged after execution. The completion
   manifest signs every prior run artifact, including the deliberately stable
   `.run.lock`, checkpoints, timing segments, exports, preflight seal, and
   report. `COMPLETE.json` hashes that completion manifest and is written last;
   neither file is required to hash itself.
7. All 30 paired 1 ms cases (60 allocator rows) from sealed Audit v2 match the
   fresh worker rows exactly for completion binary64 value, completion tick,
   config/topology/ring/route/process-initial digests, and conservation
   projection. The two
   named completion anchors remain 6.30 ms for
   `a072_proportional_3tier_os4_p64_k16__s033` under link-local allocation and
   6.15 ms for `a079_proportional_2tier_p64_k8__s066` under network max-min.
8. Final inventory is exact: no temporary, failed, staging, or extra artifact
   remains. The declared file set accounts for all prior signed artifacts, the
   completion manifest itself, and the last-written `COMPLETE.json`.

## Predeclared analysis

The primary paired estimand is
`R = T_network_maxmin / T_link_local`. `R < 1` means the network max-min
allocator completes faster. The global point estimate is the exponentiated
mean log ratio over all 3,200 pairs. Its deterministic 95% bootstrap interval
uses 20,000 resamples, RNG seed `20260807`, and resamples the 100 sample-ID
clusters; every draw preserves all 32 arms and both allocators for each selected
sample ID. The 6,400 allocator rows are never treated as independent samples.
The RNG is NumPy `Generator(PCG64(20260807))`. Interval endpoints are the 2.5th
and 97.5th percentiles computed by `numpy.quantile(method="linear")`. Each
bootstrap records the SHA-256 of its little-endian uint32, C-order resampling
index matrix together with its declared shape and dtype.

For each arm, a separate paired-seed bootstrap resamples its 100 seeds and
reports the geometric mean ratio and 95% interval. Per-arm intervals are
descriptive and carry no multiplicity-adjusted significance claim. Global,
arm, and fabric/P/k strata report geometric mean, median, minimum, maximum,
signed and absolute millisecond and tick deltas, and mutually exclusive tick
counts: faster at `delta_ticks <= -2`, exact tie at 0, one-tick tie at `-1` or
`+1`, and slower at `delta_ticks >= 2`. Leave-one-seed-out influence is
reported for the global log-ratio.

Across corrected-versus-historical rows, report changed-row counts, tick and
relative deltas, maximum absolute delta, and whether any allocator ordering
changes outside a one-tick tie. These are correction-impact diagnostics, not
new treatment-effect estimators. A material reversal means that the historical
allocator delta was at most -2 ticks and the corrected delta is at least +2,
or vice versa.

The equal comparator is exactly the 3,200 sealed static/simple/equal
counterparts (6,400 allocator rows) matched bijectively on
fabric/P/k/sample. Topology, ring, route, and process-initial digests must match
the corresponding proportional condition; config digests are expected to
differ because the policy differs. This matched 32-arm subset happens to be
allocator-identical in all 3,200 historical pairs, but that observed fact is
verified rather than assumed. For allocator `a`, report
`A_a = T_equal,a / T_corrected_proportional,a`. Equal-policy completion times
are not generally identical between allocators, so no identity such as
`A_network/A_link_local = 1/R` may be assumed. A corrected proportional row
slower than its same-allocator equal row by more than one tick is a paper-claim
review trigger, not an execution-integrity failure.

## Runtime and stopping rule

The prior proportional slice recorded 1,051.0 worker end-to-end seconds. At
eight workers the measured linear estimate is 2.19 minutes; 3.5–5 minutes is
the operational allowance including validation, sealing, and review.

Completion of this campaign does not authorize `n=1000`. After independent
artifact and scientific review, stop and return one of:

- `READY_TO_DECIDE_PROPORTIONAL_N1000_SCOPE`;
- `REVIEW_CORRECTED_N100_EFFECTS_BEFORE_SCALING`;
- `STOP_AND_FIX_N100_INTEGRITY_FAILURE`.

The mapping is fixed: any integrity, conservation, source-seal, historical
join, or Audit-v2 anchor failure yields `STOP_AND_FIX_N100_INTEGRITY_FAILURE`.
An interval containing 1 (inclusive), a same-allocator equal-policy claim
trigger, a material historical ordering reversal, or dependence on a single
seed yields
`REVIEW_CORRECTED_N100_EFFECTS_BEFORE_SCALING`. Only a global upper interval
bound below 1 with no review trigger yields
`READY_TO_DECIDE_PROPORTIONAL_N1000_SCOPE`.

Single-seed dependence is operationally present if any leave-one-seed-out
global geometric-mean ratio reaches or crosses 1 while the full-sample point
estimate is below 1 (or symmetrically crosses below 1 when the full estimate is
above 1).

No paper edit, controller calibration, commit, push, or n=1000 run is part of
this unit.
