# V4 Global OBS result

Status: strong LiH development result; confirmatory validation deferred.

## Primary outcome

V4 applied a frozen, deterministic Global OBS search to the stored LiH 3 A
CEO-ADAPT-VQE* first-accuracy checkpoint. It did not rerun ordinary ADAPT or
CEO*. Candidate ranking used the recycled inverse Hessian, checkpoint gradient,
registered transformations, confidence guards, and structurally recounted
resources. Actual candidate energy and the stored FCI value were not selector
inputs.

| Quantity | stored CEO* source | accepted V4 | Change |
|---|---:|---:|---:|
| Energy (Ha) | -7.797909682469515 | -7.797822781089923 | +8.690137959188604e-5 |
| Parameters | 15 | 8 | -7 (-46.67%) |
| CNOT | 107 | 58 | -49 (-45.79%) |
| CNOT depth | 30 | 30 | 0 (0.00%) |
| Total depth | 171 | 92 | -79 (-46.20%) |

The measured energy increase is below the frozen cumulative `1e-4` Ha budget.
The accepted point passed independent energy/state recomputation, exact
constraint checks, two-path gradient equivalence, full-circuit resource recount,
and the unchanged `1e-8` first-order stationarity gate. Its stationarity
infinity norm was `6.3719367560111095e-9`.

This meets the preregistered **strong development result** label through both a
45.79% CNOT reduction and a 46.67% parameter reduction, with no CNOT-depth or
total-depth regression. The label is a development-performance classification,
not a validation claim.

## Search and exact attempts

- Search status: `surrogate-complete` under the frozen catalog and quadratic
  surrogate; this does not mean global optimality for the true VQE energy.
- Search work: 337 expanded nodes, 168 completed quadratic solves, 41 safely
  pruned branches, and zero numerical failures.
- 127 states were inside the predicted energy budget; 8 survived the frozen
  confidence/quality guards; 4 were Pareto candidates.
- Two unique candidates were evaluated exactly. The first was accepted and is
  the winner for both co-primary endpoints. The second was rolled back because
  its stationarity residual `1.8828317193114036e-8` exceeded `1e-8`, despite
  acceptable energy and circuit resources.

The confidence guard is therefore materially active rather than decorative.
On tractable H2/H4 catalogs, branch-and-bound reproduced the exhaustive
eligible sets. H2/H4 contained no positive safe Global OBS examples under the
frozen `1e-4` budget, so they certify implementation behavior but do not by
themselves establish broad molecular performance.

## Negative results retained

- V2's 14-parameter candidate remains rejected and rolled back under its frozen
  stationarity gate. V4 does not relabel it after observing later results.
- V3 stopped at H2/H4 calibration because its single preregistered polishing
  method did not reliably repair the marginal stationarity case. No V3 LiH run
  occurred and no threshold was relaxed.
- V4-S8 is `deferred-not-passed`: no unseen molecule with a matched frozen CEO*
  checkpoint exists in the authorized no-new-baseline scope.
- The two fail-closed S7 serialization/ordering incidents and the S9 reporting
  reconstruction incident remain documented. None changed frozen thresholds or
  scientific values.

## Claim boundary

The supported claim is limited to accepted structural compression of one
already-observed LiH development checkpoint in an exact noiseless simulator.
It does not establish blind, out-of-sample, hardware, or general molecular
superiority. Paper-equivalent Measurement Cost is `N/A`; implementation work
counters must not be substituted for it.

V4 does not train a machine-learning model. Its inverse-Hessian quadratic
surrogate is constructed from the checkpoint's deterministic optimization
state and fixed calibration guards.

## Reproducible evidence

- Machine-readable report: `artifacts/v4/s9-report-v1-1/report.json`
- Comparison table: `artifacts/v4/s9-report-v1-1/comparison.csv`
- Exact-attempt table: `artifacts/v4/s9-report-v1-1/exact-attempts.csv`
- Trajectory table: `artifacts/v4/s9-report-v1-1/trajectory.csv`
- Pareto table: `artifacts/v4/s9-report-v1-1/pareto-candidates.csv`
- Independent S7 audit: `artifacts/v4/s7-lih-independent-audit-v1.json`
- Deferred-validation gate: `artifacts/v4/s8-deferred-validation-gate-v1.json`
- S10 local release audit: `artifacts/v4/s10-local-release-audit-v1.json`
- Paper-equivalent figure bundle: `output/pdf/v4-paper-equivalent-v1/`

The final local release suite passed all 162 tests. The 95 emitted warnings are
deprecation warnings from the pinned paper-era OpenFermion/Qiskit dependency
stack; they are retained as technical debt and were not converted into hidden
test suppressions.
