# Corrected proportional mechanism audit v2 — frozen specification

Date frozen: 2026-08-07 (Asia/Jerusalem)

Status: post-fix diagnostic gate. This audit validates the corrected prospective
boundary-snapshot mechanism before any full proportional `n=100` revalidation.
It is not a paper estimator and has no `n=1000` execution path.

## Question

At each redistribution boundary, does the corrected production runner use one
simultaneous current-rate vector for every persistent QP of every live logical
edge, including idle QPs, and does the corrected trajectory remain numerically
stable across the already frozen 0.5, 1, and 2 ms window probe?

Audit v1 remains the immutable historical record of the defect. Audit v2 must
not overwrite or reinterpret it. Differences from v1 are reported as the
effect of the mechanism correction, not treated as regression failures.

## Immutable inputs

- corrected `sim.py`: `96505cefe2e5aa761b80080d77145bfd384c688ce4a8ca5792f8f7ce17ef59bd`
- `experiments/run_rate_allocator_n100.py`: `7d01a2e598c799b0c533fb650f33b8537f51fa3187f427fcf9ada108d56fd8b4`
- `experiments/run_rate_allocator_pilot.py`: `777018e1a408eb5274d5ee87700fc66e4396fd5d39722f625f22e48840efc431`
- implementation contract: `b324de9f5c2f74443334901231df366759097299e84505c39b31e5fa6ce7d6c5`
- Audit v1 script: `7cde3d0892b93b653f76200c40493604141a60dca611da4c368a52668f62a727`
- Audit v1 specification: `076a29c0441a24d331747e3442a129feda1eb718fe77f03c8f45395d40077f05`
- Audit v1 completion seal: `a6e4c00a80c6bfb179af68f9308e2e91e2fab8aaed6ceda10a09cbe9494419ad`
- sealed paired `n=100` run and selected checkpoint inventory used by v1
- frozen-results root: `09a1418e965b9c2d597721ff0d3b1e8db937a19ce667accfa2cf1f469664c24e`

The v1 completion seal is authoritative for every v1 output artifact: each
listed file's hash and byte size must match, and no unsealed file may appear in
that directory. Every immutable input is checked before, after, and immediately
before sealing v2.

## Fixed matrix

Exactly the v1 matrix is reused:

1. `proportional_3tier_os4_p64_k2`
2. `proportional_3tier_os4_p64_k16`
3. `proportional_2tier_p64_k8`

Seeds: `0, 11, 22, 33, 44, 55, 66, 77, 88, 99`.

Windows: `0.5, 1, 2 ms`, exactly `10, 20, 40` ticks at `dt=50 us`.

Allocators: `link_local_equal_share` and `network_maxmin`.

Total: 180 traced simulations. The 60 production-window rows are also executed
through the corrected production runner and the paired `n=100` worker.

## Boundary trace

The sidecar reproduces the corrected production loop. At each boundary it:

1. constructs all live logical groups before changing any bytes;
2. builds the production candidate set in simulator insertion order: every QP
   of every live group plus each active non-ring flow;
3. obtains the used vector from `FlowLevelSimulator.snapshot_flow_rates()`;
4. derives expected candidate membership independently and directly from all
   groups' remaining bytes, then checks content, order, and uniqueness;
5. recomputes a wiring-independent shadow vector using the separately sealed v1
   prospective-rate implementation. The shadow intentionally shares the same
   pure allocator mathematics (including the max-min primitive); it is an
   independent check of candidate wiring and capacity materialization, not a
   second implementation of the allocation theorem;
6. compares normalized used and shadow weights before applying the used vector;
7. proves both rate computations are read-only by comparing boundary-state
   digests over time, flow identity/5-tuples/paths/byte/rate fields, next flow
   ID, topology, edge byte counters, congestion, and max-min cache fields before
   and after each computation;
8. records idle-QP reactivation, conservation, zero/non-finite rates, and the
   difference between the corrected vector and the historical retained
   `last_rate_Bps` vector.

The historical retained-rate comparison is diagnostic only. A difference is
expected precisely where v1 exposed stale weighting and cannot fail v2.

## Hard gates

1. Matrix identity and topology, ring, route, and per-window configuration
   pairing are exact.
2. Every normalized weight used by the corrected sidecar matches the independent
   prospective shadow within `1e-12`; no controlled rate is negative or
   non-finite; and neither rate computation mutates the captured boundary state.
   A live group whose rate sum is zero is allowed. Preservation of its byte
   split in the production runner is pinned separately by a focused regression
   that must pass before authorization.
3. Every logical edge conserves bytes within `1e-6 B`, has no negative remaining
   bytes, no NaN or infinity in any terminal/conservation metric, and finishes
   with zero remaining bytes.
4. At 1 ms, all 60 sidecar rows match the corrected production runner exactly in
   binary64 completion time and delivered-byte vector.
5. At 1 ms, all 60 fresh paired-worker rows match the corresponding corrected
   sidecar/direct row in binary64 completion time, simulated ticks,
   topology/ring/route/config digests, and passing conservation summaries. The
   paired-worker schema does not expose its delivered-byte vector; that vector
   is therefore proved only by the sidecar/direct-production gate in item 4,
   not claimed as an unavailable worker comparison. Pair specification,
   allocator set, and pair gate also remain exact. Corrected outcomes are not
   required to equal the historical sealed proportional outcomes.
6. The v1 artifact tree and every other immutable input remain unchanged.
7. Every trace executes at least one snapshot. The two production-window rows
   that exposed the v1 defect (`k=16, seed=33, link-local` and `2-tier k=8,
   seed=66, max-min`) must each observe an idle QP, a reactivation, and a
   nonzero counterfactual difference from retained `last_rate_Bps`.

## Window-sensitivity gate

The v1 engineering thresholds are unchanged and are evaluated separately for
each neighboring window:

- no allocator ordering reversal outside a one-tick tie;
- each cell/allocator/window median absolute relative deviation is at most 1%;
- each individual absolute relative deviation is at most 5%.

## Historical comparison and persisted evidence

For every 1 ms row, v2 performs a strict bijective join and compares the
corrected result with the corresponding v1
trace and reports exact equality, tick/time delta, relative completion-time
delta, and invariant digest equality. This comparison is not a hard gate on the
scientific outcome. V2 persists:

- all 180 corrected traces;
- the 60 corrected direct-production projections;
- all 30 fresh paired-worker checkpoints;
- the 60-row corrected-versus-v1 comparison;
- summary, report, run manifest, and completion seal.

## Decision and exclusions

If both hard and sensitivity gates pass, the only authorized conclusion is
`PASS_READY_FOR_PROPORTIONAL_N100_REVALIDATION`. It does not authorize `n=1000`.

Explicit exclusions: no full `n=100`, no `n=1000`, no controller calibration,
no dynamic-congestion claim, no frozen-result mutation, no paper edit, no
commit, and no push.

V2 may write only to a new, absent child of
`investigations/proportional_mechanism_audit_v2/`. It must reject `results/`,
the v1 output tree, the sealed `n=100` tree, and every existing target. The v2
script and specification hashes are captured by the dry-run authorization,
checked in every spawned worker, rechecked after execution, and recorded in the
final seal. `COMPLETE.json` is written last and signs every other artifact by
hash and byte size; temporary, failed, extra, or unsigned files preclude a
successful seal.

The authorization routine recomputes the digest of the complete plan rather
than trusting its stored `plan_sha256`, then also requires byte-semantic
equality with a freshly rebuilt canonical v2 plan. Output containment is
enforced inside `execute()` as well as the CLI. Artifact inventory is recursive;
nested files or directories are forbidden and cannot be hidden from
`COMPLETE.json`.
