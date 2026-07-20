# S8: H2/H4 predictor calibration

## Registered execution

The protocol and one correction were tagged before any S8 molecular result:

- `dvg-obs-s8-calibration-protocol-v1`
- `dvg-obs-s8-calibration-protocol-amendment-1`

The correction added the S7 optimizer-completion requirement that had been
accidentally omitted from the safe-label list. It did not change a molecule,
checkpoint, candidate, predictor, threshold, or optimizer budget.

H2 at 1.5 Å was evaluated after iteration 1 as an unsafe-deletion control. H4
at 1.5 Å reached the first strict chemical-accuracy crossing at iteration 4,
with energy `-1.9949017237736966 Ha`, FCI error
`0.0012486017451136533 Ha`, and 10 parameters. Both recycled inverse Hessians
passed the registered numerical-quality gate; the H4 matrix had condition
number 57.46, full secant-direction coverage, and 19 valid internal updates.
The official analytic Hessian was available for both systems.

The catalog contained 21 rows. Four rows were transformations already present
under another kind, so 17 equivalence classes were executed. Every class was
optimized from both preregistered warm starts. No candidate evaluation or
resource recount crashed.

## Primary outcome

No candidate passed every preregistered S7-style safe gate at the fixed local
budget of `1e-4 Ha`. H2 deletion raised the energy by `0.0872758 Ha`. For H4,
all 16 transformations exceeded the local budget; 15 also lost chemical
accuracy, while one preserved it.

The closest H4 candidate was an MVP-to-OVP-diff native transformation:

| Quantity | Result |
|---|---:|
| Actual energy increase | `0.00011278944956583103 Ha` |
| General OBS prediction | `0.0001089209841942998 Ha` |
| Exact-Hessian prediction | `0.0001174243162822611 Ha` |
| Final FCI error | `0.0013613911946794843 Ha` |
| CNOT change | `-4` |
| CNOT-depth change | `0` |
| Total-depth change | `-11` |
| Parameter change | `-1` |
| Logical-block change | `0` |
| Projected-gradient infinity norm | `1.31e-9` |

It passed chemical accuracy, independent energy/state, native constraint, KKT,
optimizer, semantic resource recount, and resource Pareto checks. It was
correctly rejected only because `1.1279e-4 > 1.0e-4 Ha`. The threshold is not
relaxed after seeing this result.

## Predictor evidence

Across the 17 executed transformations, rank correlations with actual
post-reoptimization energy change were:

| Predictor | Spearman | Kendall |
|---|---:|---:|
| Magnitude | 0.385 | 0.265 |
| Magnitude + position | 0.431 | 0.353 |
| Diagonal Hessian | 0.919 | 0.765 |
| Single-coordinate OBS (11 applicable) | 0.882 | 0.709 |
| General-constraint OBS | 0.963 | 0.868 |
| Exact-Hessian oracle | 0.983 | 0.926 |

This supports a ranking claim on these development systems: general-constraint
OBS ranked candidate damage substantially better than the two magnitude
heuristics and approached the exact-Hessian oracle. It does not yet support a
safe-candidate precision/recall claim because the primary label had no positive
candidate. All energy predictors therefore produced true negatives only at the
registered threshold.

Projection ON and OFF converged to indistinguishable energies for all 17
transformations. Projection ON used 199 optimizer energy evaluations versus 229
for OFF, and 145 versus 159 optimizer iterations. This is development evidence
for a lower-work warm start, not a paper measurement-cost result.

## Independent audit and next gate

The independent bundle audit recomputed checkpoint digests, candidate and
equivalence counts, every safe conjunction, primary-path binding, metrics, CSV
row counts, plot presence, and the absence of invented paper measurement cost.
All checks passed. The full software suite passed 73 tests.

The metric recomputation audit uses absolute tolerance `1e-14` and relative
tolerance `1e-12` only for floating descriptive statistics produced by
SciPy/NumPy. This prevents last-bit CPU/BLAS differences from failing CI while
recording the maximum observed difference and mismatch paths. Discrete fields,
candidate decisions, safety predicates, scientific thresholds, IDs, and
digests still require exact equality. This audit tolerance does not alter any
selector, optimizer, or reported molecular result.

S8's registered primary run is complete, but S9 cannot estimate positive-class
precision/recall from it. A separately preregistered later-checkpoint H4
calibration is required before freezing a selector. That extension must retain
the `1e-4 Ha` primary budget and cannot reclassify the near-miss above.

## Claim boundary

H2 and H4 are non-blind development systems. These results do not establish LiH
improvement, generalization, or paper-equivalent measurement savings.
