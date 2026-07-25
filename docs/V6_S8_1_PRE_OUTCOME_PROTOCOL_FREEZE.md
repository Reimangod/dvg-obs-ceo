# V6 S8.1 pre-outcome endpoint and Top-2 freeze

Status: frozen before any S9 candidate energy evaluation

S8 remains immutable historical evidence. S8.1 resolves two ambiguities before
S9 rather than changing the protocol after seeing an outcome.

## Endpoint policy

Two tracks are explicitly separated:

| Track | Resource gate | Current S7 candidates |
|---|---|---|
| Circuit-primary | CNOT and CNOT depth nonregress; one strictly improves | rejected |
| Exploratory depth/parameter | Total depth and parameters strictly improve | eligible |

All three candidates change the S6 parent by:

```text
parameters      -1
total depth     -2
CNOT            +1
CNOT depth      +1
```

Therefore no S9 result from this queue can be reported as circuit-primary
CNOT compression. S9 is a native rank-2 feasibility and predictor-diagnostic
experiment.

## Why Top-2

The best two point predictions differ by only about `5.0e-7 Ha`, while all
three predictor records are `boundary`, require refinement, and have no
empirically calibrated uncertainty margin. Keeping only the point-estimate
winner would not test whether that difference is meaningful.

S8.1 freezes the best two candidates by:

1. predicted loss;
2. canonical candidate ID as the deterministic tie-break.

This is called `boundary-quality deterministic Top-2`, not risk-aware
selection. Actual S9 outcomes cannot reorder or introduce candidates.

## Scientific boundary

The second exact attempt adds work but provides:

- a ranking-order check;
- signed and absolute prediction errors for two locations;
- under/overestimation evidence;
- a first location-dependence diagnostic.

These outcomes are development evidence for later S11 calibration. They may
not be used to modify the current S9 queue, and they do not by themselves
establish a PRA performance result.
