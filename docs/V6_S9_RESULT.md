# V6-S9 native rank-2 Top-2 result

Status: completed; current `SPARSE_UCRY_RANK2` family is not certified.

## Outcome

Both V6-S8.1 Top-2 candidates were evaluated from independent clones of the
same S6 parent. Neither candidate passed the fixed `1e-8` stationarity gate.
Both transactions rolled back exactly. The S6 primary parent remains
unchanged, and S10 sequential continuation is not authorized.

| Candidate suffix | Predicted loss (Ha) | Actual loss (Ha) | Prediction absolute error (Ha) | Final gradient infinity | Result |
|---|---:|---:|---:|---:|---|
| `dc96ba44d20a` | 1.4241450e-6 | 1.3931920e-6 | 3.0953060e-8 | 3.0980421e-7 | rejected: stationarity |
| `54d1ebd0cac4` | 1.9254551e-6 | 1.6126386e-6 | 3.1281652e-7 | 2.8128900e-7 | rejected: stationarity |

The first prediction overestimated the optimized loss by about 2.2% relative
to the actual loss. The second also overestimated it, by a materially larger
amount. These are two development points, not a statistical predictor
calibration.

## Gates that passed

For both candidates:

- energy increase was below `1e-4 Ha`;
- optimizer and independent native Hamiltonian energies agreed within
  `1e-10 Ha`;
- semantic target and native circuit state fidelity was numerically one;
- retained target and source-path gradients agreed with zero recorded
  infinity residual;
- the removed-coordinate constraint residual was zero;
- S9 reproduced the S7 full-circuit resource vector without an incident;
- parameters changed `129 -> 128`;
- total depth changed `1520 -> 1518`;
- CNOT changed `840 -> 841`;
- CNOT depth changed `300 -> 301`.

Thus the rank-2 family and its native synthesis were semantically and
energetically meaningful, but the frozen optimization/certification protocol
did not establish the required stationary point.

## Optimizer evidence

The primary OBS/KKT warm start and the single preregistered demoted-seed
fallback both reached the fixed 200-iteration limit for both candidates.
The primary path was better and was retained:

| Candidate suffix | Primary gradient infinity | Fallback gradient infinity |
|---|---:|---:|
| `dc96ba44d20a` | 3.0980421e-7 | 9.8103887e-7 |
| `54d1ebd0cac4` | 2.8128900e-7 | 6.2696377e-7 |

The stationarity threshold is not relaxed, the optimizer cap is not extended,
and the excluded third candidate is not added after seeing these outcomes.

## Engineering audit

All nine synthetic failure scenarios restored exact snapshots and left no
committed transaction. Both real rejected attempts also restored their
pre-attempt snapshot digests exactly. No primary-lineage artifact was
committed.

## Scientific decision

Under the preregistered V6-S9 decision rule:

```text
native synthesis feasible
energy budget feasible
fixed-protocol stationarity certification failed
current SPARSE_UCRY_RANK2 family: STOP
```

This is not evidence that every possible optimizer or every possible rank-2
family must fail. It is evidence that the current family did not satisfy the
frozen V6-S9 certification protocol. Continuing it by relaxing thresholds,
adding iterations, adding the third candidate, or entering S10 would be
post-outcome protocol drift.

Any future rank-adaptive work must begin as a new, separately frozen target
family or protocol. It must not be reported as continuation of this S9 queue.
