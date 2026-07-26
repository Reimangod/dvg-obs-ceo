# V6-NS10 H6 optimizer-scalability result

Status: complete, independently audited

## Outcome

The frozen trust-region ablation did not certify any of the four immutable
NS7 H6 rank-two candidates.

| Context | Normal | Energy loss (Ha) | Final gradient infinity | Iterations | Decision |
|---|---|---:|---:|---:|---|
| H6 1.5 A | `(1,1,-1)` | `5.75e-5` | `2.66e-5` | 200 | rejected |
| H6 1.5 A | `(1,1,1)` | `4.66e-5` | `9.78e-6` | 200 | rejected |
| H6 3.0 A | `(1,1,-1)` | `1.91e-5` | `4.68e-5` | 200 | rejected |
| H6 3.0 A | `(1,1,1)` | `1.37e-5` | `8.39e-6` | 200 | rejected |

All candidates remained inside the frozen energy budget and passed constraint,
semantic/native state, energy, finite-difference, and resource checks. They
failed stationarity and optimizer-success after reaching the 200-iteration
cap.

Both same-structure controls were already stationary at their source points:

| Context | Initial/final gradient infinity | Iterations | Decision |
|---|---:|---:|---|
| H6 1.5 A | `3.48e-9` | 1 | certified control |
| H6 3.0 A | `1.91e-9` | 1 | certified control |

Thus the failure is not explained by H6 dimensionality alone under this
solver. The fixed constrained landscapes or chosen rank-two families remain
implicated. This does not prove that no constrained stationary point exists,
and it does not authorize trying further optimizers without a new protocol.
NS7 decisions remain unchanged.
