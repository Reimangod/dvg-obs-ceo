# V3/V4 research and implementation plan

Status: draft revision 2. This document is a successor protocol and does not
rewrite the completed S0-S12 plan or reinterpret any frozen V2 result.

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
- `development result` only; confirmatory molecular validation is deferred
  while new ordinary GSD-ADAPT and CEO* executions are out of scope;
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
- minimum independent state recomputation fidelity: `1 - 1e-10`;
- maximum constraint residual: `1e-10`;
- maximum stationarity residual: `1e-8`;
- V2 remains rejected and rolled back. A V3 result never edits or relabels the
  V2 artifact.

FCI energy is forbidden from candidate screening, ranking, polishing, and
acceptance. It may be joined only after a run has been committed or rolled
back, for reporting.

### Baseline non-reexecution rule

No new ordinary GSD-ADAPT or CEO* run is performed in V3 or V4. Existing
audited H2/H4/LiH checkpoints, trajectories, and resource artifacts are the
only baseline inputs. Each reuse verifies the source SHA-256, schema, upstream
commit, problem identity, and circuit-counter version. V3/V4 may evaluate and
optimize a compressed target cloned from an existing checkpoint, but they do
not regrow the source ansatz.

Consequences:

- normal ADAPT and CEO* wall time are not spent again;
- stored baseline values remain comparison references and are never inferred
  from a new run;
- no unseen-molecule validation is claimed in the current V4 scope, because a
  matched unseen CEO* source checkpoint would require a new CEO* execution;
- generality or out-of-sample performance claims are prohibited. A future
  validation phase requires a separately authorized and preregistered protocol.

## 3. Common engineering rules

1. Do not edit `vendor/ceo-adapt-vqe`; keep it a pinned submodule.
2. Create V3 and V4 on separate feature branches and separate draft PRs.
3. Freeze each executable protocol with a manifest digest and immutable Git
   tag before its LiH run.
4. Refuse dirty-tree, wrong-submodule, wrong-thread-count, or wrong-protocol
   execution.
5. Write artifacts atomically, never overwrite completed bundles, and retain
   failed trials.
6. Every exact VQE attempt runs inside the existing transaction/rollback
   mechanism, including crash, timeout, NaN, and partial-write handling.
7. Search order, tie-breaking, IDs, and artifact schemas must be deterministic.
8. Keep prediction/screening work, polishing work, reused-baseline provenance,
   and final circuit resources in separate ledgers.
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
- independent state recomputation fidelity at least `1 - 1e-10`. This compares
  two independent recomputations of the same candidate state and is an
  implementation certificate, not source-candidate fidelity;
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

Source-candidate fidelity is recorded only as an exact-simulator research
diagnostic. It is not an acceptance gate and is not presented as a
hardware-free measurement.

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

Freeze two data roles using existing audited source checkpoints only:

- H2/H4: calibration and engineering tests;
- LiH 3 Angstrom: observed development benchmark.

No new ordinary ADAPT or CEO* source run is permitted. Confirmatory molecular
validation is outside this protocol. Synthetic/property tests do not count as
molecular validation.

Freeze two co-primary endpoints:

1. Circuit-primary: CNOT, CNOT depth, total depth, parameters, predicted loss.
2. Parameter-primary: parameters, CNOT depth, CNOT, total depth, predicted
   loss.

Both endpoints require CNOT, CNOT depth, and total depth to be no worse than
the immutable stored CEO* checkpoint. Any experiment permitting a positive
circuit regression is labeled secondary and cannot support the primary
performance claim.

Definition of done: protocol, endpoint order, hard guards, Top-K budget,
source artifact digests, and all stop rules are tagged before LiH development.

### V4-S1: Exact canonical ConstraintState IR

Represent a search node as a canonical constrained ansatz state containing:

- active source blocks and target block families;
- exact constraint provenance;
- exact rational reduced row-echelon representation of `[A | b]` where
  supported;
- source-to-target map and target dimension;
- structural and transformation digests;
- predicted loss and Hessian diagnostics;
- exact full-circuit resource snapshot.

Use two identities. `ConstraintSemanticID` contains exact transformation
primitives, block/slot provenance, registered symbolic tokens such as
`sqrt(2)`, and an exact rational RREF (or equivalent exact canonical row-space
form). `ConstraintNumericalID` contains canonical float64 bytes for `A`, `b`,
`c`, and `J` plus matrix diagnostics.

Do not construct semantic identity digests from platform-dependent floating
SVD, QR, or RREF output. Transformations that lack an exact symbolic form are
not deduplicated solely by approximate row-space equality.

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
The search is exact only with respect to the frozen quadratic surrogate and
candidate catalog. It is never described as globally optimal under the true
VQE objective.

Descendant pruning is permitted only for monotone structural/surrogate bounds:

- the fixed-surrogate predicted energy lower bound already exceeds the
  registered screening budget;
- even the maximum remaining parameter/resource reduction cannot beat the
  incumbent;
- an optimistic resource bound cannot improve either endpoint;
- an exact semantic conflict, target-family exclusion, deletion containment,
  rank impossibility, or affine infeasibility makes every descendant invalid.

Candidate-specific condition-number failure, insufficient direction coverage,
projected secant residual failure, or a numerical solve failure rejects only
the current completed state. It does not automatically prune descendants or
siblings because those diagnostics are not monotone under added constraints.

Maintain stable tie-breaking and deduplicate by canonical state digest. Record
visited, expanded, deduplicated, pruned, infeasible, and completed counts plus
the reason for every pruned branch.

Every result records one search status:

- `exhaustive`: the complete canonical catalog was enumerated;
- `surrogate-complete`: branch-and-bound proved completion under the frozen
  surrogate/catalog;
- `budget-truncated`: a deterministic work bound stopped the search, so output
  is called `best found candidate`, not `global winner`;
- `numerical-failure`: a required invariant or solver failed;
- `infrastructure-timeout`: a large emergency wall-time limit stopped the run;
  the output is not a normal scientific result.

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

The preregistered ranking order selects the formal winner. All frozen Top-K
candidates are evaluated independently, but actual energy is used only for
pass/fail. Among passing candidates, the highest-ranked preregistered candidate
is the endpoint winner. If one canonical structure appears in both endpoints,
it is executed once and attributed to both by structure digest.

No actual candidate energy, FCI energy, or post-optimization outcome is a
selector input.

Definition of done: selector replay from saved inputs exactly reproduces the
same Top-K list and digest.

### V4-S6: H2/H4 calibration and protocol freeze

Use H2/H4 to fix:

- empirical prediction safety envelope;
- maximum expanded nodes;
- maximum completed states;
- maximum quadratic solves;
- maximum full-resource recounts;
- Top-K exact VQE attempts;
- continuation schedule, if continuation is retained;
- polishing and fallback limits;
- endpoint hard caps and tie-breaking.

Wall time is telemetry only, except for a deliberately large emergency safety
timeout. Reaching that timeout produces `infrastructure-timeout` and no normal
scientific winner. Formal stopping depends only on deterministic counters.

Candidate failures do not silently alter ranking or thresholds. All attempts
are retained. Calibration results cannot later be pooled with validation.

Definition of done: deterministic replay, complete failure ledger, independent
audit, frozen selector/configuration digest, and pre-LiH tag. The full V4
configuration is frozen after H2/H4 and before LiH; it is not changed after the
LiH result is observed.

### V4-S7: Paired LiH development experiment

Load the existing audited CEO* iteration-5 checkpoint once and create target
transactions for:

- circuit-primary Global OBS transaction;
- parameter-primary Global OBS transaction.

Do not rerun CEO* and do not run ordinary GSD-ADAPT. The unchanged source
snapshot, energy, circuit resources, and prior trajectory are read from their
immutable audited artifacts. Pairing means common checkpoint identity, not a
new baseline execution.

Optimize at most the preregistered Top-K candidates per endpoint. Each attempt
uses a fresh exact clone; failed attempts cannot contaminate later trials.
Commit only candidates passing the full existing acceptance criteria and the
two-path stationarity audit. Preserve rejected candidates as counterfactual
diagnostics.

Because LiH informed V4, report this as development evidence only.

Definition of done: a paired comparison bundle and independent audit reproduce
all source digests, attempts, rollbacks/commits, resource counts, and work.

### V4-S8: Deferred validation gate

No unseen-system run is performed in the current scope because the user has
excluded new CEO* and ordinary ADAPT executions. Consequently V4-S8 is a
documented deferment, not a missing run and not a passed validation gate.

A future confirmatory study requires a separate protocol that freezes, before
execution:

- permission to generate a matched CEO* source checkpoint;
- the molecule and geometry selection rule;
- whether the checkpoint is selected by a CEO* internal gradient criterion or
  by first chemical accuracy;
- any explicitly permitted FCI checkpoint-selection oracle;
- all V4 thresholds, solver settings, and deterministic budgets.

One unseen system would support only a `validation-supported result`, not a
claim of general applicability. General claims require broader preregistered
coverage such as two molecules or one molecule at two geometries.

### V4-S9: Ablation and reporting

Report separately:

- stored CEO* reference versus the V2 official rollback result, without a new
  CEO* execution;
- V2 rejected single candidate;
- V3 certification result;
- V4 circuit-primary and parameter-primary results;
- Global OBS with/without candidate-specific confidence;
- branch-and-bound versus exhaustive search on tractable calibration cases;
- screening/prediction work, exact-VQE work, and final circuit resources.

Ablations run only on synthetic catalogs, H2/H4 calibration artifacts, and LiH
development. They are not run on a future confirmatory system before its
primary result; any later validation ablation is explicitly exploratory.

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
- no result is described as validated, out-of-sample, or generally applicable
  in the current no-new-baseline scope;
- normal ADAPT and CEO* execution counters remain zero for V3/V4, with all
  reused source artifact digests recorded.

## 7. Success levels

Scientific validity is independent of performance and is achieved when the
protocol executes and audits correctly, including a null result.

Performance labels are:

- `valid reduction`: accepted candidate, unchanged accuracy/certificate gates,
  no parameter, CNOT, CNOT-depth, or total-depth regression, and at least one
  strict resource reduction;
- `accepted CEO*-improving reduction`: an accepted candidate whose resource
  vector `(parameters, CNOT, CNOT depth, total depth)` is componentwise no worse
  than the immutable CEO* reference and strictly better in at least one
  component;
- `diagnostic-candidate-exceeding reduction`: an accepted candidate whose same
  resource vector componentwise dominates the rejected 14-parameter V2
  diagnostic candidate and is strictly better in at least one component;
- `strong development result`: at least 15% CNOT reduction or at least 20%
  parameter reduction versus the stored CEO* reference with no CNOT-depth or
  total-depth regression on LiH.

`validation-supported result` is unavailable in the current scope. It may be
used only by a future separately frozen unseen-system protocol with a matched
source checkpoint.

The strong thresholds are reporting labels, not reasons to tune or rerun.

## 8. Immediate execution order

1. Review and freeze this draft without altering S0-S12 history.
2. Create the V3 branch and complete V3-S0 through V3-S4 continuously.
3. Close V3 after its single LiH diagnostic, whether accepted or rejected.
4. Review and tag V3 code. Create V4 from that reviewed code tag so it inherits
   the gradient audit, certificate schema, ledger, and polishing code, but never
   from mutable V3 runtime artifacts or post-result local tuning.
5. Complete V4-S0 through V4-S6 before any V4 LiH execution.
6. Freeze the complete V4 protocol after H2/H4, then run LiH development once
   without configuration changes.
7. Do not execute ordinary GSD-ADAPT, CEO*, or unseen-system validation in the
   current scope. Reuse only audited source artifacts.
8. Run ablations on synthetic/H2/H4/LiH development data and publish only
   claims supported by the corresponding evidence level.
