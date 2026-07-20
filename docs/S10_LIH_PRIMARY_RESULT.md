# S10 LiH first-accuracy primary result

The preregistered v1.2 run completed from the canonical single-thread numerical
environment. It exactly reproduced the registered CEO-ADAPT-VQE* checkpoint:

| Metric | Canonical checkpoint |
|---|---:|
| ADAPT iteration | 5 |
| Energy (Ha) | -7.797909682469515 |
| FCI error (Ha) | 0.0009334770328921493 |
| Parameters | 15 |
| Logical blocks | 15 |
| CNOTs | 107 |
| CNOT depth | 30 |
| Total depth | 171 |

All source, no-pruning, and V2 branch snapshot digests were identical. The
frozen selector screened 15 equivalence-class representatives, found seven
eligible candidates, and selected one block deletion. No actual candidate
energy or FCI value was a selector input.

## Selected trial

The selected source was the iteration-3 OVP-sum block at ansatz position 6,
pool index 602, with coefficient `-8.345958119142507e-7`. General constrained
OBS predicted a cumulative energy increase of
`3.796066518614031e-12` Ha. Reoptimization measured approximately
`3.78e-12` Ha.

The candidate circuit had:

| Metric | Before | Candidate | Delta |
|---|---:|---:|---:|
| CNOTs | 107 | 98 | -9 |
| CNOT depth | 30 | 30 | 0 |
| Total depth | 171 | 158 | -13 |
| Parameters | 15 | 14 | -1 |
| Logical blocks | 15 | 14 | -1 |

Energy budget, independent energy, independent state, transformation,
full-circuit recount, and Pareto checks passed. Projection-on reported precision
loss, so the one registered projection-off fallback ran. Its KKT infinity norm
was `2.3287183258695764e-8`, above the frozen `1e-8` limit. KKT was the only
failed acceptance check.

The transaction therefore restored the exact pre-attempt snapshot and retained
the trial under `transactions/failed`. The committed V2 primary result remains
identical to no-pruning: 107 CNOTs, depth 30, total depth 171, and 15 parameters.

## Interpretation boundary

This is evidence that the DVG-aware OBS predictor identified a physically
low-impact, resource-reducing block. It is not evidence that the primary V2
accepted a reduction. Relaxing KKT now would be post-result tuning. Any revised
stationarity policy must be a separately versioned study calibrated without
reusing this LiH outcome as validation evidence.

The independent audit passed 14 invariants, including selector replay, exact
rollback digest, absence of a commit directory, FCI separation, and the null
paper-measurement-cost claim.
