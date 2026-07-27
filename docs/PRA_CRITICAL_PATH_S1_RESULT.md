# PRA critical path S1 result

Decision: `GO_S2_FIELD_NAMING_CORRECTION`

Independent reconstruction established that the NS7 and NS10 H6 sources are
identical within every recorded state, structure, energy, and gradient check.
The source checkpoints are stationary:

| Context | Source parameter-gradient infinity norm |
|---|---:|
| H6 1.5 Å | `3.4753153774907952e-9` |
| H6 3.0 Å | `1.908776525727518e-9` |

The historical NS7 field `source_gradient_infinity` is the full
source-coordinate gradient at the mapped rank-two candidate, not the source
checkpoint gradient. The stored `target_gradient_infinity` is the constrained
target-coordinate gradient and was correctly used as the KKT residual.

All four H6 candidate gradients, constraint residuals, and finite-difference
checks were independently reproduced. No NS7 decision changes.

The correct H6 statement is:

> The registered rank-two families were not certified on the two stationary
> H6 source checkpoints under the frozen optimization protocols.

S2 is authorized. Source reoptimization is not required for these two H6
checkpoints.
