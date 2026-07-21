# V3/V4 research and implementation plan

Status: draft. This document is a successor protocol and does not rewrite the
completed S0-S12 plan or reinterpret any frozen V2 result.

## 1. Purpose and naming

V3 is a short numerical-certification stage. It does not rediscover the
14-parameter LiH candidate already produced by V2 and is not presented as a new
compression algorithm. Its purpose is to determine whether that immutable
candidate can satisfy the existing first-order constrained-stationarity
criterion after one fixed, independently audited polishing procedure.

V4 is the main new algorithmic stage: Global OBS compression over compatible,
joint CEO transformations. It replaces the one-candidate greedy search with a
deterministic search over canonical constrained ansatz states.

The terms used in all code, artifacts, and papers shall be:

- `first-order constrained stationarity certificate`, not "KKT optimality
  proof";
- `development result` for LiH, because its V2 outcome is already known;
- `validation result` only for a system not used to design or tune V3/V4;
- `implementation work counters`, not paper Measurement Cost, unless the
  paper-era measurement definition is independently reproduced.

## 2. Immutable inherited facts

V3 and V4 inherit these values without retrospective modification:

- upstream CEO-ADAPT-VQE commit:
  `a3f89d03e6a03c89767d3cf8ee7657a57653dda0`;
- LiH, 3 Angstrom, STO-3G, Jordan-Wigner, exact noiseless simulation;
- CEO* checkpoint: iteration 5, energy `-7.797909682469515` Ha,
  15 parameters, 107 CNOTs, CNOT depth 30, total depth 171;
- V2 candidate: 14 parameters, 98 CNOTs, CNOT depth 30, total depth 158;
- V2 measured energy increase: approximately `3.7792e-12` Ha;
- cumulative energy budget: `1e-4` Ha;
- independent-energy tolerance: `1e-10` Ha;
- minimum state fidelity: `1 - 1e-10`;
- maximum constraint residual: `1e-10`;
- maximum stationarity residual: `1e-8`;
- V2 remains rejected and rolled back. A V3 result never edits or relabels the
  V2 artifact.

FCI energy is forbidden from candidate screening, ranking, polishing, and
acceptance. It may be joined only after a run has been committed or rolled
back, for reporting.

## 3. Common engineering rules

1. Do not edit `vendor/ceo-adapt-vqe`; keep it a pinned submodule.
2. Create V3 and V4 on separate feature branches and separate draft PRs.
3. Freeze each executable protocol with a manifest digest and immutable Git
   tag before its LiH or validation run.
4. Refuse dirty-tree, wrong-submodule, wrong-thread-count, or wrong-protocol
   execution.
5. Write artifacts atomically, never overwrite completed bundles, and retain
   failed trials.
6. Every exact VQE attempt runs inside the existing transaction/rollback
   mechanism, including crash, timeout, NaN, and partial-write handling.
7. Search order, tie-breaking, IDs, and artifact schemas must be deterministic.
8. Keep prediction/screening work, polishing work, baseline work, and final
   circuit resources in separate ledgers.
9. Preserve the three identity layers: StatePreparationID, ProblemID, and
   MeasurementContextID.
10. A smaller predicted circuit is never a result until the full physical
    ansatz is rebuilt and recounted.

## 4. V3: bounded stationarity certification

### V3-S0: Freeze the diagnostic question

Create an immutable V3 input manifest that references the exact S10 source
checkpoint, transformation, and rejected trial by SHA-256. No reselection,
alternative deletion, energy-threshold change, or candidate fallback is
allowed.

The V3 question is only:

> Can the existing 14-parameter candidate satisfy the unchanged `1e-8`
> first-order stationarity threshold using one preregistered polishing method?

Definition of done:

- source and candidate digests resolve exactly;
- all inherited criteria are serialized in the manifest;
- LiH is labeled diagnostic rather than validation;
- protocol tag exists before the diagnostic execution.

### V3-S1: Independent two-path gradient audit

At the same final candidate point `phi`, compute:

1. the target-native gradient directly from the 14-parameter target circuit;
2. `theta = c + J phi`, then the source-circuit gradient at that mapped point,
   followed by `J.T @ g_source`.

Do not use the original checkpoint gradient for the second path. Compare the
two vectors with preregistered absolute and relative tolerances, not bitwise
equality. Record componentwise differences, infinity/L2 norms, circuit/state
fidelity, and both work counts.

Required tests:

- analytic quadratic examples;
- every supported atomic transformation family;
- random-state source/target unitary checks;
- deliberate wrong-Jacobian and wrong-evaluation-point failures;
- CPU-stable tolerance behavior.

Definition of done: both paths agree on H2/H4 calibration cases. A disagreement
blocks polishing and V4 because it indicates a transformation or derivative
bug.

### V3-S2: Select and freeze one polishing method on H2/H4

Use one solver family only: target-native trust-region Newton-CG with a
deterministic central-difference Hessian-vector product from analytic gradient
vectors. The implementation must expose and ledger every gradient evaluation.

Before LiH, H2/H4 are used to freeze:

- finite-difference step policy;
- damping and initial/max trust radius;
- maximum polishing iterations;
- maximum gradient-vector and energy-evaluation budgets;
- permitted numerical termination statuses;
- failure and fallback policy.

There is no second solver family and no LiH-specific tuning. If calibration
cannot produce a stable fixed configuration within the preregistered work
budget, V3 terminates as unsuccessful and V4 proceeds without an accepted V3
candidate.

Definition of done:

- fixed configuration manifest and digest;
- deterministic replay on H2/H4;
- work ledger reconciles exactly;
- failure injection produces complete rollback.

### V3-S3: One LiH diagnostic execution

Run exactly one transaction on the immutable 14-parameter candidate. Record
optimizer termination separately from the independent certificate.

Acceptance requires all existing gates:

- finite values and physical scalar domain;
- cumulative energy increase at most `1e-4` Ha;
- independent energy agreement within `1e-10` Ha;
- state fidelity at least `1 - 1e-10`;
- constraint residual at most `1e-10`;
- target-native stationarity infinity norm at most `1e-8`;
- two-path gradient audit passed;
- exact full-circuit resource recount passed;
- transformation semantics passed;
- no CNOT, CNOT-depth, total-depth, parameter, or block regression;
- at least one resource strictly improved.

Second-order quantities are diagnostics only: approximate reduced-Hessian
minimum eigenvalue and independent directional curvature. They are not called
proofs and do not replace the first-order acceptance gate.

Definition of done: the transaction commits or rolls back once, retains all
evidence, and an independent auditor reproduces every gate.

### V3-S4: Close V3 immediately

V3 ends after the one LiH diagnostic regardless of outcome.

- If accepted, report 15 to 14 parameters, 107 to 98 CNOTs, and total depth
  171 to 158 as a diagnostic LiH circuit improvement. Do not claim lower total
  VQE work or paper Measurement Cost without evidence.
- If rejected, report the remaining certificate failure and do not add another
  solver, threshold, or candidate.

Required deliverables:

- protocol and input manifests;
- gradient-agreement artifact;
- polishing configuration and work ledger;
- transaction and independent audit;
- concise V3 result document;
- passing full test suite and green CI;
- result tag and draft PR.

## 5. V3 time/scope stop rules

V3 is deliberately bounded:

- one immutable LiH candidate;
- one solver family;
- one calibration stage using H2/H4;
- one frozen LiH execution;
- no threshold relaxation;
- no candidate reselection;
- no second polishing campaign after observing LiH.

Any additional search belongs to V4. This prevents a small diagnostic stage
from delaying the main algorithm.

## 6. V4: Global OBS compression

### V4-S0: Preregister claims, endpoints, and datasets

Freeze three data roles:

- H2/H4: calibration and engineering tests;
- LiH 3 Angstrom: observed development benchmark;
- one previously unused molecular system: confirmatory validation, selected
  and frozen after feasibility-only resource inspection and before viewing any
  V4 energy outcome.

Freeze two co-primary endpoints:

1. Circuit-primary: CNOT, CNOT depth, total depth, parameters, predicted loss.
2. Parameter-primary: parameters, CNOT depth, CNOT, total depth, predicted
   loss.

Both endpoints require CNOT and CNOT depth to be no worse than CEO*. Any
experiment permitting a positive circuit regression is labeled secondary and
cannot support the primary performance claim.

Definition of done: protocol, endpoint order, hard guards, Top-K budget,
validation system, and all stop rules are tagged before validation.

### V4-S1: Exact canonical ConstraintState IR

Represent a search node as a canonical constrained ansatz state containing:

- active source blocks and target block families;
- exact constraint provenance;
- normalized exact/integer/rational rows for `[A | b]` where supported;
- source-to-target map and target dimension;
- structural and transformation digests;
- predicted loss and Hessian diagnostics;
- exact full-circuit resource snapshot.

Do not construct identity digests from platform-dependent floating SVD, QR, or
RREF output. Known deletion, signed tying, and OVP relations use exact symbolic
normalization. Transformations requiring non-exact coefficients retain a
canonical provenance IR and canonical float bytes, and are never deduplicated
solely by approximate row-space equality.

Definition of done: permutation, row scaling, and application-order property
tests produce identical IDs for mathematically identical exact constraints and
different IDs for distinct constraints.

### V4-S2: Composition and compatibility engine

Build compatibility as more than a pairwise graph. Pairwise edges provide fast
screening, but every completed batch must pass a global validator covering:

- mutually exclusive target families;
- deletion containment;
- overlapping constituent transformations;
- generator ordering and block dependencies;
- full rank and affine feasibility;
- source/target generator semantics;
- actual circuit construction.

Supported transformations initially remain those already synthesis-certified:
constituent deletion, QE/MVP block deletion, MVP to QE, MVP to existing
OVP-plus/minus, and existing exact signed ties. Arbitrary Hessian directions
and uncertified generator merges are excluded.

Definition of done: exhaustive small synthetic catalogs match the global
validator, and deliberately incompatible triples are rejected even when all
pairs appear compatible.

### V4-S3: Joint OBS prediction and candidate-specific confidence

Stack compatible affine constraints and compute the joint constrained optimum
using the existing nonzero-gradient quadratic kernel. Add:

- `constraint_direction_coverage`;
- projected internal and held-out secant residuals;
- conditioning of the relevant constrained solve;
- prediction error stratified by transformation family;
- an H2/H4 empirical safety envelope.

The safety envelope is not called a statistical confidence interval. It is a
calibration-set screening guard. Final acceptance always uses independently
measured energy, gradient, state, constraints, and resources.

For a fixed SPD quadratic model and nested feasible sets, predicted constrained
loss must be nondecreasing as constraints are added. Property tests verify this
before it is used as a branch-and-bound pruning rule.

Definition of done: joint predictions agree with direct quadratic solves,
monotonicity holds within fixed numerical tolerance, and singular/infeasible
states fail closed.

### V4-S4: Deterministic branch-and-bound search

Implement deterministic exploration over canonical ConstraintState nodes.
Prune only with auditable safe bounds:

- predicted energy lower bound already exceeds the registered budget;
- even the maximum remaining parameter/resource reduction cannot beat the
  incumbent;
- an optimistic resource bound cannot improve either endpoint;
- transformation or Hessian-quality gates fail.

Maintain stable tie-breaking and deduplicate by canonical state digest. Record
visited, expanded, deduplicated, pruned, infeasible, and completed counts plus
the reason for every pruned branch.

Definition of done: on small catalogs, branch-and-bound returns the same Pareto
set and endpoint winners as exhaustive enumeration.

### V4-S5: Full-resource Pareto selector

Rebuild and recount the complete physical ansatz for each surviving completed
state. Atomic transformations may temporarily appear non-improving; primary
resource guards apply to the final joint batch.

Produce:

- all non-dominated feasible predicted candidates;
- circuit-primary winner;
- parameter-primary winner;
- stable alternative structures up to the frozen Top-K budget;
- explicit equivalence-class deduplication.

No actual candidate energy, FCI energy, or post-optimization outcome is a
selector input.

Definition of done: selector replay from saved inputs exactly reproduces the
same Top-K list and digest.

### V4-S6: H2/H4 calibration and protocol freeze

Use H2/H4 to fix:

- empirical prediction safety envelope;
- maximum search nodes and wall/work budget;
- Top-K exact VQE attempts;
- continuation schedule, if continuation is retained;
- polishing and fallback limits;
- endpoint hard caps and tie-breaking.

Candidate failures do not silently alter ranking or thresholds. All attempts
are retained. Calibration results cannot later be pooled with validation.

Definition of done: deterministic replay, complete failure ledger, independent
audit, frozen selector/configuration digest, and pre-validation tag.

### V4-S7: Paired LiH development experiment

Clone the same immutable CEO* iteration-5 checkpoint into:

- no-compression control;
- circuit-primary Global OBS transaction;
- parameter-primary Global OBS transaction.

Optimize at most the preregistered Top-K candidates per endpoint. Each attempt
uses a fresh exact clone; failed attempts cannot contaminate later trials.
Commit only candidates passing the full existing acceptance criteria and the
two-path stationarity audit. Preserve rejected candidates as counterfactual
diagnostics.

Because LiH informed V4, report this as development evidence only.

Definition of done: a paired comparison bundle and independent audit reproduce
all source digests, attempts, rollbacks/commits, resource counts, and work.

### V4-S8: Frozen unseen-system validation

Run the unchanged tagged V4 protocol once on the preregistered unused system.
Do not change thresholds, Top-K, objective order, solver, or work budget after
viewing the result. A null or negative result is retained and reported.

Definition of done: complete audited paired artifacts exist for CEO* control
and both V4 endpoints, with no configuration drift from the frozen manifest.

### V4-S9: Ablation and reporting

Report separately:

- CEO* versus V2 official rollback result;
- V2 rejected single candidate;
- V3 certification result;
- V4 circuit-primary and parameter-primary results;
- Global OBS with/without candidate-specific confidence;
- branch-and-bound versus exhaustive search on tractable calibration cases;
- screening/prediction work, exact-VQE work, and final circuit resources.

Required trajectory fields include energy/error, ADAPT/compression iteration,
wall time, energy evaluations, gradient-vector and component equivalents,
parameters, blocks/operators, CNOT, CNOT depth, and total depth. Paper
Measurement Cost remains unavailable unless separately reproduced.

Definition of done: tables, Pareto plots, prediction-versus-actual plots,
machine-readable CSV/JSON, source hashes, and independent audits all agree.

### V4-S10: Release gate

Before calling V4 complete:

- full unit/property/integration/failure-injection tests pass;
- CI passes on the supported clean environment;
- upstream submodule and all protocol tags are verified;
- repository remains Private unless the user explicitly changes it;
- large raw artifacts are excluded from Git and represented by byte count and
  SHA-256 manifests;
- draft PR contains claim boundaries and known negative results;
- no result is described as a general improvement without unseen-system
  validation.

## 7. Success levels

Scientific validity is independent of performance and is achieved when the
protocol executes and audits correctly, including a null result.

Performance labels are:

- `valid reduction`: accepted candidate, unchanged accuracy/certificate gates,
  no CNOT or CNOT-depth regression, and at least one strict resource reduction;
- `V2-exceeding reduction`: strictly improves the accepted resource vector
  beyond the official V2 rollback result and, separately, beyond the rejected
  14-parameter diagnostic candidate where claimed;
- `strong development result`: at least 15% CNOT reduction or at least 20%
  parameter reduction versus CEO* with no CNOT-depth regression on LiH;
- `validation-supported result`: the frozen unseen-system run also Pareto-
  dominates its matched CEO* control under the same acceptance gates.

The strong thresholds are reporting labels, not reasons to tune or rerun.

## 8. Immediate execution order

1. Review and freeze this draft without altering S0-S12 history.
2. Create the V3 branch and complete V3-S0 through V3-S4 continuously.
3. Close V3 after its single LiH diagnostic, whether accepted or rejected.
4. Create a fresh V4 branch from the reviewed base, not from mutable V3 runtime
   artifacts.
5. Complete V4-S0 through V4-S6 before any V4 LiH execution.
6. Run LiH as development, freeze the unseen-system protocol, then validate.
7. Publish only claims supported by the corresponding evidence level.

