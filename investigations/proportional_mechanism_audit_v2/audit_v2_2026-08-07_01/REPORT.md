# Corrected proportional mechanism audit v2

- Hard mechanism gate: **PASS**
- Window-sensitivity gate: **PASS**
- Decision: **PASS_READY_FOR_PROPORTIONAL_N100_REVALIDATION**
- Traced simulations: 180
- Exact 1 ms sidecar/direct rows: 60
- Exact 1 ms worker-bridge rows: 60

## Mechanism observations

- Snapshot boundaries/calls: 2418/2418
- Snapshot/shadow weight mismatches: 0
- Snapshot state mutations: 0
- Idle-QP reactivations: 205
- Corrected/retained counterfactual weight mismatches: 452
- Maximum corrected/retained weight difference: 0.125
- Maximum final conservation error: 9.53674316406e-07 B

## Historical v1 comparison at 1 ms

- Bijective rows: 60
- Completion rows changed in binary64: 1
- Maximum absolute relative completion delta: 0.806452%
- Allocator-order changes outside one-tick ties: 0

## Window sensitivity

- Maximum cell/allocator/window median absolute delta: 0%
- Maximum individual absolute delta: 0.877193%
- Ordering reversals outside a one-tick tie: 0

## Scope

This audit covers only the corrected static proportional core. A pass
authorizes review before a full proportional n=100 revalidation; it does
not authorize n=1000, controller calibration, or dynamic-congestion claims.
No frozen result, paper, commit, or push is produced by this run.
