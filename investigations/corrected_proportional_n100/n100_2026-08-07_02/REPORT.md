# Corrected proportional n=100 revalidation

Status: `READY_TO_DECIDE_PROPORTIONAL_N1000_SCOPE`

## Primary paired result

- Pairs: 3200
- Geometric mean R=T_network/T_link: 0.972203291
- Cluster-bootstrap 95% CI: [0.970734487, 0.973630124]
- Exact bootstrap-index SHA-256: `97a42157ab7dd18246ac02f284afb9da83a406f01b467cae35efaab2ad7a654f`

## Diagnostics

- Corrected historical rows changed: 65 / 6400
- Material allocator-order reversals: 0
- Same-allocator equal-policy claim triggers: 0
- Single-seed dependence: False

All intervals use paired seed clusters. The 6,400 allocator rows were not treated as independent observations.
No n=1000 execution is authorized by this report.
