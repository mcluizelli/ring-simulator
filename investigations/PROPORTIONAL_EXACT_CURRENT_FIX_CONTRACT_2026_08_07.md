# Exact-current proportional fix — implementation contract

Date: 2026-08-07 (Asia/Jerusalem)

Status: approved next unit; frozen before changing `sim.py`.

Pre-implementation review clarification: rates are one simultaneous global
snapshot across all live groups, plus any non-controlled flow that is currently
active. The snapshot describes the boundary capacity state and takes effect in
the next tick; it is not a prediction of the next congestion transition.

## Observed defect

Audit v1 is sealed at
`investigations/proportional_mechanism_audit/audit_2026-08-07_01` with decision
`STOP_BEFORE_N1000_AND_REVIEW`. At the production 1 ms window, 7 allocations
in 2/60 selected rows used a retained `last_rate_Bps` whose normalized weight
differed from the prospective current weight. The largest weight difference was
0.0625 and the largest next-tick rate error was 0.75.

The pre-fix simulator SHA-256 is
`40edbacc28e61bb25769278382506c32611cf7fd9e14777480b6fd3d664fab69`.

Pre-fix function-source gates:

- `FlowLevelSimulator.step`: `3f655a6b205728ccb4aa1d8ed36230c13c51b8e70923b29276ca60adda8a3883`
- `run_simple_ring_transfer`: `bd654f652b074ed2b2a0e5f46be9ba80a6fe1c7a642978b86f8cb5a3a3accee9`
- `allocate_flow_rates`: `e4904e35882961073cce26e85b22395bdf5aee87799aac9e27bdd4a58668038d`

All three must remain source-identical after the patch.

## Required semantics

At a proportional redistribution boundary:

1. A logical edge is live iff the sum of its non-negative remaining bytes is
   positive.
2. The candidate active set is every persistent QP belonging to every live
   logical edge, including a QP whose current assigned chunk is zero, together
   with any external flow that is currently active.
3. Each candidate keeps its fixed 5-tuple and ECMP path.
4. One global rate vector is computed before any group's remaining bytes are
   changed. Rates use the selected allocator and the residual capacities in the
   congestion state produced by the just-finished tick.
5. Remaining bytes on each live logical edge are assigned in proportion to
   those prospective current rates. Zero-rate QPs receive zero. A live group
   whose rate sum is zero retains its current byte assignment.
6. Redistribution changes only `remaining_bytes`; it must not advance time,
   send bytes, mutate congestion, or alter rate-allocation caches.
7. A controlled ring QP with an empty path or a negative, NaN, or infinite rate
   is an invariant violation and fails explicitly.

This is the fluid-model oracle described in the paper. It is not a sender-side
rate estimator.

## Minimal implementation boundary

- Reuse the existing pure `allocate_flow_rates()` primitive.
- Add one read-only `FlowLevelSimulator` method that materializes fixed paths and
  current residual capacities for an explicitly supplied ordered set of flow
  IDs, then calls `allocate_flow_rates()`.
- Change only `run_ring_transfer_proportional()` to use this snapshot at a
  redistribution boundary.
- Do not refactor or change `FlowLevelSimulator.step()`.
- Do not change simple/equal, adaptive, AllReduce, topology, ECMP, or congestion
  update behavior.
- Do not overwrite Audit v1 or frozen results.

## Pre-patch failing tests

1. Snapshot rates include an idle persistent QP and use the declared candidate
   set rather than the current `remaining_bytes > 0` set.
2. Snapshot computation is read-only over time, bytes, last rates, congestion
   state, and max-min cache state.
3. The proportional runner calls the snapshot with all QPs of every live
   logical edge and actually uses the returned rates.
4. A controlled capacity/rate switch changes the prospective snapshot even
   while one candidate QP is idle.
5. Multiple live groups are included in one global call; completed groups are
   excluded and an external active flow is retained.

## Post-patch gates

- All new tests pass.
- Existing allocator and three legacy frozen snapshot tests pass.
- Simple/equal selected outputs remain binary64-exact to their sealed rows.
- Audit v1 script, specification, outputs, and hashes remain unchanged.
- Audit v2 uses a new script/output path and the same 180-cell matrix.
- Audit v2 requires zero stale/current mismatches and reruns the window gate.
- Corrected 1 ms results are compared to Audit v1 as historical deltas; they
  are not required to match the old proportional outputs.
- No `n=100` full campaign and no `n=1000` run before review of Audit v2.
