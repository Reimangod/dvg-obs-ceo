# V5 risk-aware sequential exact-constraint OBS plan

Status: implementation plan; no V5 performance result yet  
Parent release: `dvg-obs-v4.1-multisystem-results-v1`  
Parent branch: `v4.1-scale-transfer`  
Intended branch: `v5-risk-aware-sequential`  
Intended output root: `artifacts/v5/`  
Study regime: exact statevector, noiseless, post-hoc compression of immutable CEO* checkpoints

## 1. Purpose and non-guarantee

V5 investigates whether risk-aware, sequential, exact-constraint OBS
compression can improve the circuit-resource-versus-energy-loss frontier of
V4.1 under a fixed and fully reported compression-work budget.

No plan can guarantee that a new algorithm will outperform V4.1 before the
experiment is run. V5 therefore protects performance by construction:

- the immutable CEO* and V4.1 results are always retained;
- a V5 variant is adopted only when an independently audited result
  Pareto-dominates the applicable comparison under the frozen acceptance rules;
- a failed round rolls back to the last committed checkpoint;
- a failed ablation is retained as a negative result and is not merged into the
  final method;
- thresholds are never relaxed to obtain a preferred molecular result.

The primary research hypothesis is:

> Risk-aware sequential exact-constraint OBS compression achieves a better
> circuit-resource-versus-energy-loss trade-off than one-shot V4.1 compression
> under a fixed optimization-work budget.

Here, **exact-constraint** means that CEO block transformations and parameter
relations have exact registered semantics. It does not mean exact ground-state
energy or an exact quadratic energy model.

## 2. Evidence that determines the V5 path

All current molecules and geometries are development data. None may be called
an unseen validation case.

| Case | CEO* CNOT | V4.1 CNOT | CNOT reduction | Total-depth reduction | Parameter reduction | Energy increase (Ha) | Exact attempts | Search status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| LiH 3.0 A | 107 | 58 | 49 (45.79%) | 79 (46.20%) | 7 (46.67%) | 8.6901e-5 | 2 | surrogate-complete |
| H6 1.5 A | 879 | 858 | 21 (2.39%) | 49 (3.07%) | 6 (4.38%) | 8.8214e-5 | 4 | budget-truncated |
| H6 3.0 A | 785 | 768 | 17 (2.17%) | 38 (2.55%) | 5 (3.36%) | 7.1345e-5 | 4 | budget-truncated |
| BeH2 3.0 A | 284 | 239 | 45 (15.85%) | 65 (14.19%) | 5 (13.16%) | 9.6615e-5 | 4 | budget-truncated |

This evidence leads to the following decisions.

1. V4.1 remains the one-shot causal baseline. V5 starts from its verified
   implementation, not from legacy V2/V3 code.
2. The first V5 mechanism is sequential commit, reoptimization, and catalog
   rebuilding. This directly tests whether new redundancy appears after a
   safe compression.
3. Beam search is secondary. Increasing the cardinality of the existing V4.1
   family already showed limited H6 gains, so wider search alone is not the
   principal hypothesis.
4. Candidate-local HVP refinement is conditional. The selected V4.1 attempts
   show useful but imperfect predictions; fresh curvature is spent only where
   it can change a decision.
5. Optimizer polishing is a last-stage repair, not a way to retry every
   candidate until one passes.
6. New transformation families are deferred until the sequential hypothesis is
   tested. Parameter deletion counts only when the corresponding physical
   circuit structure is removed and the full circuit is recounted.
7. Measurement reuse, OGM, global compilation, and modified CEO growth are not
   part of V5 core. They change different causal factors and require separate
   protocols.

## 3. Claim and comparison boundary

### 3.1 Canonical comparisons

The required comparisons are:

- immutable CEO* source checkpoint;
- audited V4.1 one-shot result;
- V5 sequential width-1;
- V5 sequential multi-trajectory;
- each preregistered V5 ablation.

Ordinary ADAPT and a newly executed CEO* growth run are outside this plan. The
stored CEO* checkpoint is still the immutable source used to measure cumulative
energy and circuit changes.

### 3.2 Frozen scientific conditions

The following remain identical across V4.1 and V5:

- source checkpoint and all three identity layers;
- Hamiltonian, active space, mapping, qubit order, and reference state;
- exact/noiseless estimator;
- paper-era CEO circuit semantics and resource counter;
- no barrier-free global Qiskit compilation;
- `1e-8` target-gradient infinity-norm acceptance gate;
- exact constraint and independent energy checks;
- source-relative algorithmic energy budget of `1e-4 Ha`;
- chemical-accuracy threshold for benchmark reporting and benchmark-only guard.

### 3.3 Information firewall

FCI energy and actual candidate energy are forbidden inputs to screening and
ranking. At round start, the accepted checkpoint, catalog, ranking, Top-K,
evaluation order, and winner rule are frozen.

The algorithmic remaining budget is updated only between rounds:

```text
B_remaining = 1e-4 - (E_committed - E_source)
```

FCI is used only for benchmark acceptance/reporting. The deployable acceptance
contract is reported separately and consists of source-relative actual energy,
stationarity, exact constraints, and resource recount.

## 4. V5 algorithm contract

For each path and round:

1. Load and verify the last immutable committed checkpoint.
2. Rebuild the candidate catalog from that checkpoint.
3. Validate exact CEO semantics before numerical prediction.
4. Predict loss with the existing nonzero-gradient affine constrained
   quadratic/KKT model.
5. Attach deterministic numerical-risk diagnostics.
6. Construct a multiobjective Pareto set; do not use a single weighted resource
   score as the primary selector.
7. Refine only high-value, decision-uncertain candidates with matrix-free HVP.
8. Freeze Top-K, exact evaluation order, and the deterministic winner rule.
9. Run exact VQE within the fixed work budget.
10. Apply target-native conditional polishing only when its preregistered
    trigger fires.
11. Independently recompute energy, stationarity, constraints, state identity,
    and full-circuit resources.
12. Commit one winner or roll back the current round only.
13. Update actual cumulative energy and all work counters.
14. Stop on no eligible candidate, insufficient remaining energy/work budget,
    maximum attempted rounds, or an incident.

### 4.1 Pareto selector

The selector retains separate axes:

```text
risk-adjusted predicted loss (minimize)
CNOT reduction              (maximize; primary)
CNOT-depth reduction        (maximize; secondary)
total-depth reduction       (maximize; secondary)
parameter reduction         (maximize; co-primary)
logical-block reduction     (maximize; structural certificate)
```

The development risk margin is a ranking/refinement heuristic, not a hard
scientific guarantee. It may use constrained-solve residual, projected secant
residual, finite-difference sensitivity, HVP/recycled-model disagreement, and a
clearly labelled development-set error summary.

Hard pre-exact rejection is limited to registered causes such as semantic
invalidity, nonfinite data, rank/solve failure, failed transformation
certificate, no physical resource benefit under the frozen resource contract,
or unambiguous algorithmic-budget infeasibility.

### 4.2 Matrix-free curvature refinement

V5 must not replace the existing predictor with the simplified stationary OBS
formula. The source-coordinate local model is

```text
q(x + delta) = q(x) + g^T delta + 1/2 delta^T H delta
A(x + delta) = b
```

and retains the nonzero gradient, affine offset, parameter tying, deletion, and
registered CEO transformations. HVP supplies the action `H v` to refine this
model or its KKT solve.

For an exact affine target map `x = c + J phi`, target-native polishing uses

```text
gradient_phi = J^T gradient_x
H_phi v      = J^T H_x (J v)
```

Solver routing is explicit:

- SPD reduced Hessian: direct factorization or CG;
- symmetric indefinite/singular KKT operator: MINRES with verified symmetry,
  residual, and breakdown handling;
- unconstrained target-native polishing with indefinite curvature:
  trust-region Krylov;
- any damping `H + mu I`: record `mu`, trigger, pre/post prediction, residual,
  and effect on ranking.

Finite-difference HVP requires a preregistered step-size study, central
difference accounting as two gradient-vector evaluations, direction-reversal
checks, and nonfinite/asymmetry fail-closed behavior.

### 4.3 Winner rule

The exact winner rule is frozen before molecular execution:

1. remove candidates failing independent acceptance;
2. retain the nondominated actual-resource set;
3. choose maximum CNOT reduction;
4. tie-break by parameter reduction, total-depth reduction, CNOT-depth
   reduction, smaller actual source-relative energy increase, then canonical
   candidate ID.

No extra candidate is introduced after seeing a Top-K actual result in the same
round.

## 5. Work accounting and fairness

Every attempted and rejected operation is included. Raw counters are retained
without collapsing unlike work into a hidden scalar:

- energy evaluations;
- gradient-vector evaluations;
- gradient-component equivalents;
- analytic and finite-difference HVP calls;
- quadratic/KKT solves and iterations;
- exact VQE attempts;
- optimizer iterations and starts;
- full resource recounts;
- expanded search states;
- attempted and accepted rounds;
- statevector evaluations;
- wall and CPU time as environment-dependent diagnostics.

Primary matched caps apply to maximum attempted rounds, exact VQE attempts,
energy evaluations, gradient-vector/component work, optimizer starts, and total
compression wall-time safety limits. Accepted rounds are an outcome, not a
fairness cap. Method-specific work such as HVP and search states is reported
separately and is also included in the resource-reduction-versus-work frontier.

The primary scientific plots are:

- CNOT reduction versus actual cumulative energy increase;
- parameter reduction versus actual cumulative energy increase;
- CNOT/parameter reduction versus gradient-component-equivalent work;
- reduction versus exact-attempt count;
- round-by-round energy, CNOT, CNOT depth, total depth, parameters, and blocks;
- predicted versus actual loss before and after HVP refinement.

Paper-equivalent Measurement Cost remains `null` unless the paper's exact
definition is separately implemented. V5 work counters must not be renamed as
Measurement Cost.

## 6. Required ablations

Features are added one at a time.

| ID | Selector | Search | Curvature | Rounds | Optimizer |
|---|---|---|---|---:|---|
| A | V4.1 | V4.1 | recycled | 1 | V4.1 |
| B | risk-aware Pareto | V4.1 | recycled | 1 | V4.1 |
| C | risk-aware Pareto | width-1 | recycled | sequential | V4.1 |
| D | risk-aware Pareto | multi-trajectory | recycled | sequential | V4.1 |
| E | risk-aware Pareto | multi-trajectory | conditional HVP | sequential | V4.1 |
| F | risk-aware Pareto | multi-trajectory | conditional HVP | sequential | conditional polishing |

Additional pruning baselines required by the existing preregistration remain:
magnitude, magnitude plus position, diagonal-Hessian saliency,
single-coordinate OBS, and general-constraint one-shot OBS. These use the same
source checkpoint and acceptance/resource contract. Their different internal
work is reported, not concealed by forcing meaningless counter equality.

## 7. Step-by-step implementation and execution

Every step begins with: clean-worktree check, parent/tag verification,
dependency/environment digest, relevant artifact verification, and test suite.
Every step ends with: independent audit, failure-injection where applicable,
new tests, artifact digest verification, no orphan process/staging/lock, and a
dedicated Git commit/tag. A failed completion gate stops progression.

### S0 - Freeze V5 question, evidence, and branch

#### Work

- Verify the V4.1 release bundle digest and reproduce the comparison table.
- Create `v5-risk-aware-sequential` from the audited V4.1 release commit.
- Register all five existing systems as development data.
- Freeze claim boundaries, primary endpoints, information firewall, allowed
  code paths, output roots, incident policy, and adoption/non-adoption rule.
- Record all literature and software sources with version/date.

#### Completion gate

- Machine-readable preregistration and human-readable plan agree.
- V4/V4.1 artifacts are read-only and digest-stable.
- No legacy V2/V3 import or result alias exists.

#### Git checkpoint

`dvg-obs-v5-s0-preregistration-v1`

### S1 - V5 telemetry, schema, and immutable evidence ledger

#### Work

- Version schemas for path, round, candidate, solver, optimizer, work, and
  rollback events.
- Separate diagnostics available for all candidates from actual values
  available only for exact attempts.
- Preserve rejected candidates, retries, non-winners, and all work.
- Add StatePreparationID, ProblemID, MeasurementContextID, source/parent/path
  checkpoint digests, code/protocol digests, and causal role to every record.
- Add a read-only migration/audit path; never rewrite V4.1 artifacts in place.

#### Completion gate

- Canonical serialization and digest replay pass under key/order perturbation.
- Truncated, duplicated, cross-path, and identity-mismatched records fail closed.

#### Git checkpoint

`dvg-obs-v5-s1-ledger-v1`

### S2 - Nested path/round transaction and complete rollback

#### Work

- Implement immutable path checkpoints and nested tentative rounds.
- Commit energy, parameters, ansatz/block IR, optimizer/inverse-Hessian state,
  identities, resources, budget, RNG, counters, and catalog parent digest.
- A failed round restores the last committed checkpoint exactly.
- Whole-path invalidation occurs only for corruption, invalid prior semantics,
  failed cumulative recomputation, or broken provenance.

#### Completion gate

- Byte/digest-exact rollback after semantic, solver, optimizer, acceptance,
  resource, serialization, hard-crash, and cancellation failures.
- No failed branch changes another branch or the source state.

#### Git checkpoint

`dvg-obs-v5-s2-nested-transaction-v1`

### S3 - Sequential width-1 scientific kernel

#### Work

- Implement one-path, one-winner-per-round execution using the unchanged V4.1
  predictor and optimizer.
- Rebuild and independently verify the catalog after every commit.
- Prove that round 1 reproduces V4.1 when selector settings are identical.
- Add stop rules for budget, no eligible candidate, attempted rounds, exact
  attempts, and incident.

#### Completion gate

- H2/H4 exhaustive fixtures match independent enumeration.
- Round-1 V4.1 equivalence passes for LiH and stored multisystem fixtures.
- A second round uses only the committed state and produces a distinct,
  correctly identified catalog or a certified no-change result.

#### Git checkpoint

`dvg-obs-v5-s3-sequential-width1-v1`

### S4 - Risk-aware Pareto selector

#### Work

- Implement nondominated sorting over separate energy/resource axes.
- Implement deterministic tie-breaking and the information firewall.
- Add risk diagnostics only for ranking and refinement triggers.
- Freeze no-physical-resource-benefit and optional no-regression policies.
- Select preregistered sentinel exact attempts from good, boundary, and poor
  diagnostic strata to measure quality-gate false exclusions.

#### Completion gate

- Scaling and candidate-order permutation do not change canonical selection.
- FCI/actual-energy poisoning tests prove ranking independence.
- A near-zero predicted loss cannot create an unbounded scalar score.

#### Git checkpoint

`dvg-obs-v5-s4-risk-pareto-v1`

### S5 - Matrix-free affine KKT/HVP refinement

#### Work

- Add an `H v` interface without replacing the V4.1 model semantics.
- Validate HVP against explicit small-system Hessians and directional finite
  differences.
- Implement solver routing, preconditioning, residual/backward-error checks,
  damping provenance, and deterministic failure categories.
- Calibrate only whether HVP can change a decision safely; do not tune for a
  desired molecular CNOT result.

#### Completion gate

- Analytic/explicit/finite-difference HVP agreement on tractable fixtures.
- Existing KKT solution is reproduced when supplied with the same Hessian.
- Indefinite, singular, asymmetric, noisy-step, and nonconvergent cases fail
  closed or use a registered fallback.
- HVP work is fully counted.

#### Git checkpoint

`dvg-obs-v5-s5-matrix-free-kkt-v1`

### S6 - Conditional target-native polishing

#### Work

- Implement target-native reduced-coordinate objective/gradient/HVP.
- Primary start is the OBS/recycled-Hessian projection.
- A second least-squares start is allowed only by a frozen trigger and budget.
- Trust-region Krylov is used only after constraints are eliminated by the
  exact target map; it is not presented as a direct constrained KKT solver.
- Keep the unchanged `||g_target||_inf <= 1e-8` acceptance gate. RMS gradient is
  diagnostic/trigger only.

#### Completion gate

- Source- and target-coordinate energies/gradients agree independently.
- Polishing never turns a semantic, resource, or clear energy failure into an
  eligible candidate.
- Failed polishing restores the pre-polishing tentative state exactly.

#### Git checkpoint

`dvg-obs-v5-s6-polishing-v1`

### S7 - Budgeted multi-trajectory search

#### Work

- Implement canonical path IDs, state deduplication, diversity rule, endpoint
  quota, and deterministic expansion.
- Calibrate widths in `{1, 2, 4, 8}` on development data using fixed exact/work
  caps and retain the complete frontier.
- Compare one-shot beam, sequential width-1, and sequential multi-trajectory.
- Freeze width, Top-K, attempted-round limit, exact-attempt limit, and winner
  rule before the final development reevaluation.

#### Completion gate

- Width 1 exactly reproduces S3.
- Expansion-order and process-count changes do not alter canonical results.
- Duplicate states are not paid for or evaluated twice.
- Wider search is adopted only if its audited frontier justifies its extra work.

#### Git checkpoint

`dvg-obs-v5-s7-multitrajectory-v1`

### S8 - Low-cost calibration and causal ablation

#### Work

- Run A-F and pruning baselines first on H2/H4, then development LiH.
- Run finite-difference step, risk-trigger, solver, beam-width, and work-cap
  sensitivity analyses without hiding negative settings.
- Evaluate predictor error on all exact attempts and the sentinel strata.
- Freeze the complete V5 protocol after this step.

#### Completion gate

- Each feature's incremental effect and incremental work are identifiable.
- No threshold is selected solely because it improves one molecule.
- At least width-1 sequential execution is scientifically and operationally
  valid; otherwise V5 stops with a negative result.

#### Git checkpoint

`dvg-obs-v5-s8-calibration-freeze-v1`

### S9 - Frozen development reevaluation

#### Work

- Reevaluate LiH 3.0 A, H6 1.5 A, H6 3.0 A, and BeH2 3.0 A with the frozen
  protocol and matched work-cap frontier.
- Do not change code or thresholds between cases except through an incident
  amendment that invalidates and reruns all affected results.
- Independently audit every path, round, rejected attempt, winner, and rollback.

#### Performance gates

- **Safety:** every adopted result retains all frozen accuracy, stationarity,
  semantics, and resource certificates.
- **Non-regression:** final release selects V4.1 when no V5 point Pareto-improves
  it; V5 cannot make the published best-known result worse.
- **Primary success:** at the same or lower actual energy increase and within a
  frozen work cap, V5 reduces more CNOT or more parameters than V4.1 without
  violating the registered guarded endpoints.
- **Strong development success:** improvement appears in at least two of the
  four development cases and includes one H6 case.
- **Negative but valid:** no improvement, with complete evidence, remains a
  publishable algorithmic limitation but does not support a superiority claim.

#### Git checkpoints

- `dvg-obs-v5-lih-development-v1`
- `dvg-obs-v5-h6-1p5-development-v1`
- `dvg-obs-v5-h6-3p0-development-v1`
- `dvg-obs-v5-beh2-3p0-development-v1`

### S10 - Decision gate for new transformation families

This step is conditional and must not be silently folded into core V5.

#### Enter only if

- sequential catalogs expose no additional accepted structural compression on
  H6 under the frozen family; and
- search/curvature/optimizer diagnostics show that the limitation is structural,
  rather than numerical or work-budget related.

#### Work

- Enumerate candidate transformations from exact CEO block algebra.
- Require generator/unitary equivalence, symbolic provenance, exact parameter
  maps, and actual physical circuit removal.
- Treat the extension as V5.1 or a separately ablated V5 extension.

#### Stop condition

- Never invent a transformation from optimized floating coefficients alone.
- Never count parameter removal if the CEO block remains in the circuit.

### S11 - Confirmatory validation gate

No existing case is unseen. A generalization claim requires explicit authority
to generate or obtain a new matched CEO* checkpoint for a previously unused
molecule or geometry.

Before opening that result:

- tag code, protocol, thresholds, work caps, and expected tables;
- run exactly once, apart from registered system incidents;
- prohibit tuning after inspection;
- report it as confirmatory only if the identity and execution contract match.

Without S11, all V5 claims remain development claims.

### S12 - Independent release audit and paper artifacts

#### Required release outputs

- CEO*, V4.1, A-F, and adopted-V5 comparison tables;
- round/time/work trajectories for energy, CNOT, CNOT depth, total depth,
  parameters, and blocks;
- resource-versus-energy and resource-versus-work frontiers;
- predictor calibration before/after HVP;
- complete attempt/rejection/rollback tables;
- sentinel quality-gate analysis;
- work-budget and wall-time tables;
- Fig. 11/14/15-equivalent plots only where their definitions are faithfully
  supported, with deviations explicitly labelled;
- machine-readable manifests, schemas, digests, environment lock, and commands;
- a limitations and negative-results report.

#### Release gate

- independent reconstruction matches every reported scientific value;
- all 3-layer identities and parent checkpoint chains verify;
- no FCI/actual-energy leakage is detected;
- every accepted state passes energy, stationarity, constraints, and full
  resource recount independently;
- every failed round restores its committed parent exactly;
- all work, failures, amendments, and excluded claims are present;
- full test suite and expensive molecular replay suite pass;
- worktree is clean and private remote branch/tags match local history.

#### Git checkpoints

- `dvg-obs-v5-audit-result-v1`
- `dvg-obs-v5-development-results-v1`
- a later confirmatory tag only if S11 is authorized and passed.

## 8. Continuous anomaly audit

The canonical runner performs these checks before, during, and after every
step/round:

### Before

- clean worktree and expected commit/tag ancestry;
- dependency, environment, upstream, protocol, and checkpoint digests;
- no existing canonical result, active lock, or ambiguous staging;
- sufficient disk/memory and configured process/thread limits;
- source identity, energy, state, and resources reconstructed independently.

### During

- heartbeat plus process identity, not PID alone;
- finite energy/gradient/HVP values;
- monotonic work counters and immutable source/parent IDs;
- solver residual, symmetry, rank, and condition diagnostics;
- transaction journal fsync before mutation and after tentative writes;
- no candidate/result information entering a forbidden selector field.

### After

- independent energy, gradient, constraint, state, and resource recomputation;
- exact rollback/commit digest chain;
- atomic artifact publication and full manifest verification;
- no orphan worker, lock, staging directory, or duplicate canonical output;
- test/replay success and clean worktree.

Any anomaly stops the affected run. Evidence is preserved before recovery.

## 9. Incident, amendment, and Git policy

An incident includes a crash, orphan/stale state, digest mismatch, duplicate
writer, environment drift, unknown failure, nonexact rollback, counter
regression, solver disagreement, selector leakage, or audit mismatch.

Required response:

1. Stop the affected path/run.
2. Preserve and hash all evidence; never overwrite or clean it first.
3. Record timeline, command, host, environment, commit, protocol, identities,
   root cause, scientific impact, and recovery decision.
4. Add a failing regression test before the fix.
5. Commit the fix as a protocol amendment with a new version/tag.
6. Invalidate and rerun every result affected by that code path.
7. Keep superseded artifacts and explicitly exclude them from final evidence.

Git rules:

- one branch for V5 core; conditional transformation expansion uses another
  branch or V5.1;
- one focused commit per completed step and separate result/audit commits;
- no force-push or history rewrite of protocol/result tags;
- no generated artifact overwrite; canonical outputs are content-addressed or
  versioned;
- push only to the private repository and verify remote commit/tag digests;
- never commit credentials, machine secrets, or uncontrolled large scratch
  files.

## 10. Decision tree after V5 core

```text
Sequential width-1 improves V4.1?
├─ yes → test whether multi-trajectory improves the work frontier
└─ no
   ├─ new safe catalog redundancy exists but ranking misses it
   │  └─ prioritize Pareto/beam selection
   ├─ candidates are sensitive to curvature diagnostics
   │  └─ prioritize conditional HVP refinement
   ├─ candidates pass energy/resources but fail marginal stationarity
   │  └─ prioritize conditional target-native polishing
   └─ no physically beneficial candidate exists in the family
      └─ enter separately registered transformation-family V5.1
```

The decision is based on audited diagnostics, not on the desire to reach a
specific CNOT percentage.

## 11. Supported and forbidden claims

If S9 succeeds, V5 may claim a better **development** resource-energy/work
frontier for the specific stored checkpoints and exact noiseless model. If S11
also passes, a bounded confirmatory generalization claim may be made.

V5 must not claim:

- guaranteed improvement on arbitrary molecules;
- a global optimum;
- lower hardware shot cost or paper Measurement Cost;
- noise robustness;
- end-to-end CEO-ADAPT growth acceleration;
- superiority caused by a component that did not pass its ablation;
- unseen validation from H2, H4, LiH, H6, or BeH2 already inspected here.

## 12. Primary references used to constrain implementation

- SciPy `trust-krylov`: Hessian-vector-product trust-region scalar
  minimization; it is not a general constrained KKT solver:
  <https://docs.scipy.org/doc/scipy/reference/optimize.minimize-trustkrylov.html>
- SciPy `MINRES`: symmetric linear systems, including indefinite or singular
  systems, with `LinearOperator` support:
  <https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.minres.html>
- Pruned-ADAPT-VQE, arXiv:2504.04652:
  <https://arxiv.org/abs/2504.04652>
- Param-ADAPT-VQE, arXiv:2602.04253:
  <https://arxiv.org/abs/2602.04253>
- HA-ADAPT-VQE, arXiv:2606.13118:
  <https://arxiv.org/abs/2606.13118>

The three ADAPT papers motivate comparison classes but do not by themselves
prove that their transformations, costs, or guarantees are equivalent to V5.
Any paper comparison must be confirmed from the full text, supplementary
material, and available code before a final claim is written.
