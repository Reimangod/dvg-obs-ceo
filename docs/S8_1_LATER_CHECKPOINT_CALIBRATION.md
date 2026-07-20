# S8.1: Outcome-informed later-checkpoint calibration

## Why this extension exists

The immutable S8 primary run had no positive safe label, so it could not measure
safe-candidate precision or recall. Before S8.1 execution, a separate protocol
tag fixed two later H4 checkpoints while retaining the original `1e-4 Ha`
budget and every optimizer, candidate, and acceptance condition. S8.1 is
explicitly outcome-informed development work, not confirmatory evidence.

## Checkpoint behavior

The registered iteration-8 checkpoint did not exist: H4 reached the FCI energy
after completed ADAPT iteration 7, and the next convergence probe returned zero
gradient norm without incrementing the iteration counter. The iteration-8 case
was retained as a registered checkpoint failure and was not replaced.

The second registered case allowed iteration 12 or earlier algorithmic
convergence. It therefore used the valid terminal iteration-7 checkpoint:

- energy: `-1.9961503255188093 Ha`;
- FCI difference: `8.88e-16 Ha`;
- parameters: 24;
- recycled inverse-Hessian dimension: 24;
- condition number: 2843.6;
- 49 valid internal updates and complete secant-direction coverage.

The official analytic Hessian was computed, but was not positive definite. The
exact-Hessian oracle was marked unavailable without diagonal shifts, clipping,
or pseudoinverse regularization. The recycled BFGS inverse Hessian remained
numerically SPD. This distinction is expected in an overparameterized ansatz:
the physical energy surface may contain flat/redundant directions even when the
optimizer maintains an SPD approximation.

## Candidate result

The catalog retained 74 candidate rows and executed 62 unique transformation
classes. All 62 completed both projection paths without candidate-level crash.
At the unchanged threshold, 59 passed every actual acceptance label and 3
failed only because optimizer success and KKT were not both satisfied.

General-constraint OBS classified the candidates as:

- true positive: 30;
- false positive: 0;
- false negative: 29;
- true negative: 3;
- precision: 1.0;
- recall: 0.508;
- false-safe rate: 0.0.

The best preregistered lexicographic resource choice among OBS-predicted-safe
candidates was an MVP whole-block deletion:

- predicted change: `5.196184022661202e-5 Ha`;
- actual change: `4.44e-16 Ha`;
- CNOT: `-13`;
- CNOT depth: `0`;
- total depth: `-24`;
- parameters: `-3`;
- logical blocks: `-1`;
- optimizer energy evaluations: 31.

At this terminal exact-energy checkpoint, nearly all accepted transformations
reoptimized back to the same ground energy. Consequently, rank correlations
became negative and are not physically informative: the actual losses are
largely tied at numerical zero while OBS provides conservative nonzero damage
estimates. The relevant S9 evidence is false-safe control, not terminal ranking.

Projection ON accepted 59 candidates versus 57 for OFF and used 3311 versus
3402 optimizer energy evaluations across all classes. This remains a
statevector work comparison, not paper measurement cost.

## Audit and selector gate

The first independent audit exposed a filename-classification bug: a failure
record matched the broad `checkpoint-*.json` glob and was mistaken for a normal
checkpoint. The auditor was corrected to enumerate successful checkpoints from
the summary and validate failure records under a separate schema. Both the S8
and S8.1 bundles then passed, and the full suite passed 74 tests.

The preregistered S9 gate is satisfied: there are actual positive and negative
labels, general OBS has zero false-safe candidates, and all attempts/work are
retained. S9 may now freeze a conservative selector. This does not imply that a
first-accuracy LiH checkpoint will contain an eligible candidate; selecting no
candidate remains a valid safe outcome.
