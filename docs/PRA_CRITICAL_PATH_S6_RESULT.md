# PRA critical path S6 result

Decision: `NO_GO_S6_REQUIRED_CROSS_SYSTEM_EVIDENCE_ABSENT`

The full frozen queue of 24 candidates was attempted exactly once:
three development conditions, two rank-3 MVP blocks per condition, and four
familywise-native target families per block.

| Case | Attempted | Accepted | Best CNOT reduction | Best CNOT-depth reduction | Best total-depth reduction | Best parameter reduction |
|---|---:|---:|---:|---:|---:|---:|
| H4 1.0 Å | 8 | 7 | 2 | 0 | 4 | 1 |
| H4 2.0 Å | 8 | 7 | 2 | 0 | 4 | 1 |
| H5 1.5 Å | 8 | 0 | 0 | 0 | 0 | 0 |

Both independent H4 geometries add certified energy-resource tradeoff points.
This strongly improves the reproducibility evidence beyond the historical H4
1.5 Å result. It does not satisfy the preregistered cross-system gate.

## Why H5 was rejected

All eight H5 candidates:

- remain inside the `1e-4 Ha` energy-loss budget;
- pass semantic/native state and independent energy agreement;
- pass the constraint and componentwise resource gates;
- reduce one parameter and two or four total-depth layers;
- include four candidates with two fewer CNOTs, two of which also reduce
  CNOT depth by one.

Nevertheless, every H5 optimization reaches the frozen 200-iteration cap.
The final coordinate-invariant orthonormal-tangent gradient remains between
approximately `1.8e-6` and `9.6e-5`, above the frozen `1e-8` threshold.
Consequently, optimizer completion and constrained stationarity both fail.

This is classified as
`OPTIMIZER_CAP_AND_STATIONARITY_NOT_CERTIFIED`. The independent result audit
found no corrupt artifact, NaN, queue omission, semantic mismatch, resource
recount mismatch, or rollback failure. It is a valid negative result. The
threshold and optimizer may not be changed after observing this outcome.

## Consequence

S7 matched-work execution, S8 prospective freeze, and S9 prospective
validation are not authorized by the current plan. Running them would violate
the predeclared gate. S10 may record the scientific closure decision, and S11
may publish a reproducible negative-result package.

No general molecular performance claim or PRA submission claim is established.
