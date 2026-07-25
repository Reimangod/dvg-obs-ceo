# V6 S8 predictor, Pareto screen, and candidate freeze

Status: complete development freeze; empirical predictor calibration pending

## Correct Hessian-reuse adapter

The V4.1 accepted H6 model contains 131 coordinates, a nonzero gradient, and
a 131×131 recycled inverse Hessian. The saturated S6 parent has 129
coordinates after two exact OVP-to-MVP absorptions.

Deleting two Hessian rows and columns is not a valid coordinate transform.
Moving the old quadratic model to a canonical zero-OVP gauge was also tested
and rejected:

```text
canonical-gauge displacement L2       0.5136273445
recycled quadratic change             0.1319065245 Ha
relocated gradient infinity           0.2962632213
ranking influence                     false
```

The true quantum state is unchanged by the exact fusion. These large recycled
model changes therefore expose gauge inconsistency in the approximate Hessian,
not a physical energy change.

S8 instead replays both accepted S6 rules and constructs the exact linear
forward map

```text
F: R^131 -> R^129
rank(F) = 129
||F theta_V4.1 - theta_S6||_infinity = 0
```

Each rank-demotion constraint in S6 coordinates is pulled back to the original
131-dimensional model. KKT/OBS is then evaluated at the point where the
gradient and inverse Hessian were actually recorded. No Hessian transport,
silent damping, or gradient-zero assumption is used.

## Predictions and selection

All three S7 candidates pass the provisional `1e-4 Ha` development screening
budget:

| Candidate suffix | Predicted change from current |
|---|---:|
| `ba44d20a` | 1.4241450419e-6 Ha |
| `ebd0cac4` | 1.9254550859e-6 Ha |
| `38aebade` | 8.2035924213e-5 Ha |

Their native resource vectors are equal, so the lowest predicted-loss
candidate Pareto-dominates the other two and is the only frozen S9 attempt:

```text
v6-rank-candidate:
09e1064d9897af7ff16a9944cfe178a6042ba6536e70e73dd413dc96ba44d20a
```

Candidate and endpoint order use canonical IDs. Reversing the predictor input
order reproduces the same freeze digest. The predictor-call cap is exactly
three; a cap of two fails before partial screening.

## Information firewall

Only these legacy fields are read:

- `coordinates`;
- `gradient`;
- `final_inverse_hessian`.

The legacy energy field is not read. Screening records recursively reject
fields containing `actual` or `fci`, including nested fields. Candidate
energies are unavailable when the immutable freeze is written, so later S9
outcomes cannot change the current queue.

## Claim boundary

The recycled model passes algebraic and numerical solve checks, but its
empirical predictive error is not calibrated yet. Every record is therefore
marked `boundary` and `refinement_required`; a numeric uncertainty margin of
zero means “not yet calibrated,” not proven zero uncertainty.

S8 performs three quadratic predictor calls, two exact-rewrite replays, and
zero energy, gradient-vector, HVP, optimizer, or resource-recount operations.
It establishes no measured accuracy, accepted compression, matched-work
advantage, or paper Measurement Cost result.
