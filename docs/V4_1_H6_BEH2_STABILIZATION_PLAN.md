# V4.1 H6/BeH2 stabilization and scale-transfer plan

Status: implementation plan only  
Parent result: `dvg-obs-v4-multisystem-results-v1`  
Parent commit: `488ec8b87079fd7ca63f1b3825cda3d6aecfa9f0`  
Intended branch: `v4.1-scale-transfer`  
Intended output root: `artifacts/v4.1/multisystem/`

## 1. Purpose and claim boundary

V4.1 is a corrective scale-transfer release of V4. Its purpose is to make the
same scientific path that completed on LiH execute correctly and audibly on:

- linear H6 at 1.5 A;
- linear H6 at 3.0 A;
- BeH2 at 3.0 A.

"Execute correctly" means that valid CEO transformations can be represented,
scale-dependent numerical diagnostics do not mechanically reject every state,
eligible candidates can reach exact VQE, and every accept or reject decision is
independently auditable. It does **not** mean that V4.1 must reproduce LiH's
reduction percentage. A zero-reduction result remains a valid V4.1 outcome.

All three molecular cases and their previous V4 outcomes have already been
observed. They are development and repair cases, not unseen confirmatory
evidence. V4.1 must not be presented as blind generalization evidence.

V4 and its result bundles remain immutable. V4.1 writes only under a new output
root and uses new protocol/result tags. No V4 artifact is overwritten, renamed,
or silently replaced.

## 2. Allowed and forbidden changes

### Allowed in V4.1

- exact support for registered two- and three-constituent MVP-to-OVP mappings;
- coordinate-scale-aware numerical solve certification;
- explicit failure taxonomy and complete rejection evidence;
- process locking, unique staging, crash recovery, and duplicate-run prevention;
- a preregistered sentinel exact-VQE path;
- generic H6/BeH2 runner and independent audit;
- documentation and regression tests needed for those corrections.

### Deferred to V5

- cardinality-aware beam search;
- candidate-local fresh Hessian-vector products;
- a separately learned or fitted compression curvature model;
- sequential multi-round compression and catalog rebuilding;
- new transformation families;
- molecule-specific thresholds;
- measurement reuse or a new measurement-cost definition;
- barrier-free or global Qiskit compilation;
- end-to-end modification of CEO-ADAPT-VQE* growth.

This boundary makes the V4-to-V4.1 ablation interpretable. A reduction change in
V4.1 can be attributed to correctness and scale-transfer fixes, rather than to a
new search architecture.

## 3. Frozen inputs and identities

V4.1 reuses the exact stored first-chemical-accuracy CEO* checkpoints used by
V4. Their paths, SHA-256 digests, internal checkpoint digests, exact energies,
resource snapshots, and statevector digests must be copied into the V4.1
protocol manifest before any exact candidate energy is evaluated.

Each run records and verifies three separate identities:

1. `StatePreparationID`: reference state, generator-definition digest, ansatz
   block structure and indices, canonical coefficient bytes, orbital parameters,
   qubit mapping, and qubit ordering.
2. `ProblemID`: Hamiltonian digest, molecule and geometry, basis, active space,
   frozen orbitals, and fermion-to-qubit mapping convention.
3. `MeasurementContextID`: state and problem IDs, observable-set digest,
   estimator version, grouping/measurement-plan version, and backend context.

For the exact noiseless V4.1 study, `MeasurementContextID` still identifies the
statevector estimator and resource backend. It must not be treated as part of
the quantum-state identity.

The following are fixed across V4 and V4.1 comparisons:

- source checkpoint;
- exact/noiseless energy model;
- paper-era CEO circuit synthesis and resource counter;
- generator normalization and qubit ordering;
- optimizer limits and independent acceptance checks;
- final cumulative energy budget rule;
- thread limits and random seeds.

Actual candidate energy and FCI energy are excluded from screening, ordering,
and candidate selection. The exact energy is used only by the final accuracy
retention check.

## 4. Definition of done

V4.1 is complete only when all of the following hold:

- all three cases terminate through the canonical runner;
- registered three-to-one MVP-to-OVP candidates no longer fail because of a
  two-to-one hard-coded assumption;
- every candidate failure has a registered category and evidence;
- coordinate rescaling cannot change a candidate's scientific eligibility;
- at least the preregistered sentinel candidates reach exact VQE unless a
  documented earlier fail-closed check rejects them;
- every rejection restores the complete runtime snapshot exactly;
- every accepted candidate remains within the cumulative accuracy guard;
- every resource claim comes from a full recount with the pinned counter;
- every result bundle and audit digest verifies independently;
- there are no orphan processes, ambiguous staging directories, or duplicate
  canonical results;
- the full test suite passes and the worktree is clean;
- protocol and result commits/tags are pushed to the private repository.

Circuit reduction is deliberately not in this definition. Making it mandatory
would create pressure to tune numerical gates after observing the molecular
outcomes.

## 5. Step-by-step execution plan

### S0 - Preserve V4 and preregister V4.1

#### Work

- Verify the V4 result tag, commit, three summary digests, and clean worktree.
- Create `v4.1-scale-transfer` from the tagged V4 result commit.
- Create a V4.1 protocol manifest containing frozen checkpoints, allowed code
  paths, numerical policies, sentinel selection rule, exact-attempt cap, output
  paths, stop rules, and claim boundary.
- Record that all H6/BeH2 outcomes are already observed development evidence.

#### Completion gate

- Manifest digest is reproducible.
- Protocol tag resolves to the exact preregistration commit.
- Execution refuses code/config changes after the tag except under registered
  result and audit paths.

#### Stop conditions

- Dirty tracked files overlap V4.1 scope.
- A checkpoint, resource counter, upstream vendor commit, or V4 result digest
  differs from the frozen record.

#### Git checkpoint

`dvg-obs-v4.1-s0-preregistration-v1`

### S1 - Reproduce and classify every previous failure

#### Work

- Add a read-only reproducer for the previous V4 H6/BeH2 summaries.
- Assert the known counts: H6 semantic-composition failures, surrogate-eligible
  states, quality rejections, zero exact attempts, and budget truncation.
- Map each failure to its source line and candidate family.
- Preserve the previous summaries as immutable regression fixtures by digest,
  not by copying or rewriting them.

#### Completion gate

- The reproducer explains every previous failure without an `unknown` bucket.
- It demonstrates that the three-constituent MVP-to-OVP candidates were created
  by the catalog but rejected by the exact primitive's two-to-one assumption.

#### Stop conditions

- A previous failure cannot be reproduced deterministically.
- The checkpoint/catalog reconstruction differs from the stored V4 evidence.

#### Git checkpoint

`dvg-obs-v4.1-s1-failure-reproduction-v1`

### S2 - Generalize exact MVP-to-OVP semantics

#### Work

- Derive the signed exact relation from registered pool parent IDs, canonical
  generator orientation, and CEO `sum`/`diff` metadata.
- Support an arbitrary registered MVP source dimension while requiring exactly
  one OVP target and exactly the registered nonzero signed parent relation.
- Represent unused constituents as exact-zero constraints.
- Continue using floating matrices only to validate the registered exact
  relation; never round floats to invent symbolic provenance.
- Include the signed relation in semantic identity and audit provenance.

For example, the registered relation

```text
source = (theta0, theta1, theta2)
target Jacobian = (1, -1, 0)^T
```

has exact constraints `theta0 + theta1 = 0` and `theta2 = 0`.

#### Required tests

- two-to-one sum and difference;
- three-to-one sum and difference with each possible zero constituent;
- parent-order permutation invariance;
- wrong parent, sign, normalization, dimension, or target rejection;
- exact RREF rank and canonical semantic-ID stability;
- numerical Jacobian agreement;
- sparse-generator equality;
- random-state unitary equality up to global phase;
- pinned upstream CEO circuit semantics;
- H6 catalog regression proving the known registered cases compose.

#### Completion gate

- Known valid H6 three-to-one candidates compose with zero unexplained semantic
  failures.
- Deliberately invalid relations remain fail-closed.
- Existing LiH/H2/H4 semantic IDs and behavior are unchanged unless the protocol
  explicitly records an identity-schema version bump.

#### Stop conditions

- Exact signs require inference from optimized coefficient values.
- Generator or circuit equivalence fails.
- A schema change aliases an old semantic ID to different mathematics.

#### Git checkpoint

`dvg-obs-v4.1-s2-exact-mvp-ovp-v1`

### S3 - Replace the scale-dependent quality veto with a numerical certificate

#### Work

- Preserve the upstream optimizer inverse Hessian byte-for-byte.
- Construct a temporary compression solve representation using canonical
  diagonal equilibration.
- Report both raw and equilibrated condition numbers.
- Retain raw condition number as a diagnostic, not the cross-system scientific
  veto at `100`.
- Require finite values, symmetry, SPD/Cholesky success, a fixed high numerical
  safety ceiling, feasibility, relative solve residual, and backward error.
- Retain constraint-direction coverage and secant-residual diagnostics as model
  evidence. Do not silently reinterpret them as probabilities of correctness.
- Map the solved target coordinates and inverse-Hessian action back to the
  canonical physical parameter coordinates before optimization.

The final exact VQE acceptance remains the accuracy proof. Passing this stage
only means that the candidate is numerically safe enough to test.

#### Required tests

- artificial diagonal coordinate rescaling over several orders of magnitude;
- invariance of constrained optimum, predicted penalty, physical coordinates,
  and scientific eligibility under that rescaling;
- agreement between scaled and unscaled well-conditioned LiH solves;
- backward-error and residual failure injection;
- non-SPD, singular, nonfinite, and excessive-condition fail-closed tests;
- H6 1.5 A sentinel regression showing that raw condition alone no longer
  rejects all otherwise-qualified candidates.

#### Completion gate

- LiH's accepted V4 candidate remains numerically and scientifically eligible.
- Coordinate rescaling does not change the result.
- No molecule-specific threshold or geometry branch exists.

#### Stop conditions

- Scaling changes the physical OBS prediction beyond tolerance.
- Numerical acceptance requires a threshold chosen from actual H6/BeH2 energy.
- The solve passes despite a failed backward-error or SPD certificate.

#### Git checkpoint

`dvg-obs-v4.1-s3-scale-aware-certificate-v1`

### S4 - Harden execution, staging, and crash recovery

#### Work

- Acquire an atomic per-case execution lock before creating staging.
- Store run UUID, host, process ID, start time, Git commit, protocol digest,
  checkpoint digest, and intended canonical output in the lock record.
- Use a run-UUID staging directory instead of a shared `.case.staging` path.
- Refuse a second writer for the same canonical case.
- Never automatically delete an orphan staging directory. Provide a read-only
  audit that classifies it as active, incomplete, complete duplicate, or
  inconsistent before an explicit recovery action.
- Write artifacts exclusively, fsync files/directories, verify internal digests,
  then atomically rename exactly one completed bundle to its canonical path.
- Verify process exit status and a final bundle digest before reporting success.
- Preserve inconsistent or nonidentical duplicates under an incident path.

#### Required tests

- two simultaneous writers;
- process interruption before and after summary write;
- stale lock with live/dead process evidence;
- identical duplicate bundle;
- nonidentical duplicate bundle;
- existing final output;
- fsync/write/rename failure injection;
- rerun refusal and explicit audited recovery.

#### Completion gate

- No test can create two canonical outputs or silently remove evidence.
- A tool-level early yield cannot be mistaken for process completion.

#### Stop conditions

- PID alone is used as proof that a run is current.
- Cleanup occurs before digest comparison.
- The runner can overwrite a final result.

#### Git checkpoint

`dvg-obs-v4.1-s4-execution-safety-v1`

### S5 - Freeze sentinel candidates before exact energy evaluation

#### Work

- Run the corrected, otherwise unchanged V4 deterministic search and full
  resource selection with S2/S3 only; do not run exact candidate energies.
- Select a fixed maximum per case using only registered semantics, predicted
  loss, non-target quality evidence, and full synthesized resource recount.
- Maintain CNOT-primary, CNOT-depth-primary, total-depth-primary, and
  parameter-primary endpoints; deduplicate identical structures.
- Persist candidate IDs, semantic/numerical IDs, selection order, prediction,
  resources, all diagnostics, and rejection reasons in the sentinel manifest.
- Cap exact attempts per case before execution. A recommended diagnostic cap is
  four unique structures, not four per endpoint.

#### Completion gate

- Candidate ordering can be replayed without Hamiltonian exact/FCI energy or
  actual candidate VQE energy.
- Sentinel manifest is committed and tagged before S7-S9 exact execution.

#### Stop conditions

- No candidate passes the numerical certificate: stop and amend the numerical
  model transparently; do not lower gates during execution.
- Candidate selection reads a prior exact-attempt result.

#### Git checkpoint

`dvg-obs-v4.1-s5-sentinel-freeze-v1`

### S6 - LiH/H2/H4 regression and low-cost transaction rehearsal

#### Work

- Run all unit/integration tests and the pinned upstream semantic tests.
- Replay H2/H4 calibration fixtures.
- Replay LiH screening, selection, exact optimization, acceptance, resource
  recount, and independent audit.
- Inject at least one deterministic rejection and verify exact rollback.
- Compare V4 and V4.1 LiH predictions, final energy, state fidelity, and
  resources. Any intended numerical difference must be explained before larger
  systems run.

#### Completion gate

- Full suite passes.
- LiH still completes through exact VQE and the accepted result meets every
  original independent acceptance check.
- Rollback restores state, ansatz, optimizer state, work counters, RNG state,
  and metadata exactly.

#### Stop conditions

- LiH loses its accepted candidate without a mathematically explained cause.
- H2/H4 semantics or resource counters drift.
- Transaction replay is not byte/digest exact.

#### Git checkpoint

`dvg-obs-v4.1-s6-regression-gate-v1`

### S7 - Execute H6 at 1.5 A

#### Work

- Verify freeze, lock, checkpoint, environment, and absence of a canonical
  result before starting.
- Run exactly the frozen sentinel queue. The search and resource selection that
  produced this queue were already completed and frozen in S5; they are not
  recomputed after any exact candidate energy becomes available.
- Independently audit the result before committing it.

#### Required output

- source reconstruction evidence;
- corrected semantic/failure counts;
- raw and scaled numerical diagnostics;
- sentinel and search selection evidence;
- predicted/preoptimization/postoptimization energy changes;
- full resource snapshots;
- exact transaction and rollback records;
- complete work counters and wall time;
- explicit search-completeness status.

#### Stop conditions

- unexplained failure;
- configuration drift;
- duplicate or ambiguous runner state;
- failure to restore after a rejected attempt;
- any attempt to tune the protocol from this result.

#### Git checkpoint

`dvg-obs-v4.1-h6-1p5-result-v1`

### S8 - Execute H6 at 3.0 A

S8 uses exactly the S7 protocol and code. No code/config change is allowed
between cases except a separately documented incident fix that invalidates and
requires replay of S7.

The accuracy budget is the smaller of the frozen V4 budget and the strict
remaining margin to chemical accuracy. It is always referenced to the original
CEO* checkpoint, not to a prior candidate or attempt.

#### Completion and stop gates

They are identical to S7.

#### Git checkpoint

`dvg-obs-v4.1-h6-3p0-result-v1`

### S9 - Execute BeH2 at 3.0 A

S9 uses exactly the S7/S8 protocol and code. It must not receive a special
threshold because its source dimension, curvature, or catalog differs.

#### Completion and stop gates

They are identical to S7.

#### Git checkpoint

`dvg-obs-v4.1-beh2-3p0-result-v1`

### S10 - Independent multisystem audit and V4/V4.1 comparison

#### Independent audit checks

- canonical bundle and every file digest;
- protocol-tag ancestry and allowed-diff policy;
- checkpoint/state/problem/measurement-context identities;
- independent source energy/state reconstruction;
- exact source resource reconstruction;
- semantic and numerical ID replay;
- sentinel ordering replay;
- absence of actual/FCI energy from screening and ranking;
- scaled/unscaled physical prediction consistency;
- optimizer completion and independent energy/state recomputation;
- constraint, KKT, and two-path gradient checks;
- full resource recount equality;
- exact rollback for every rejected attempt;
- endpoint-winner replay;
- cumulative chemical-accuracy retention;
- no staging, lock, process, or worktree residue.

#### Mandatory comparison table

For LiH, H6 1.5 A, H6 3 A, and BeH2 3 A, report:

- source and final absolute energy error;
- source-to-final energy increase;
- CNOT count and reduction;
- CNOT depth and reduction;
- total depth and reduction;
- parameter and logical-block counts and reductions;
- catalog, evaluated-state, and maximum-cardinality counts;
- semantic, numerical, quality, optimizer, and acceptance failures;
- full resource recounts and exact VQE attempts;
- energy/gradient/statevector work and wall time;
- exhaustive, surrogate-complete, or budget-truncated status.

Paper-equivalent Measurement Cost remains `null` unless the exact original
definition is implemented. Quadratic solves, HVPs, wall time, or local work
counters must not be relabeled as that metric.

#### Release gate

- All independent checks pass.
- Null results and unsuccessful attempts are included.
- No global-optimum, hardware-noise, shot-cost, or unseen-generalization claim
  is made.
- A V4.1 result tag points to the complete audited bundle.
- The private GitHub branch and tags match the local commits.

#### Git checkpoints

- `dvg-obs-v4.1-audit-result-v1`
- `dvg-obs-v4.1-multisystem-results-v1`

## 6. Incident and amendment policy

An incident is any crash, dead process, orphan staging, digest mismatch,
duplicate writer, environment drift, unexpected exception category, invalid
rollback, or discrepancy between independent and primary computations.

When an incident occurs:

1. stop the affected execution;
2. preserve all files and record their digests;
3. create an incident report containing timeline, command, commit, environment,
   state, root cause, scientific impact, and recovery decision;
4. add a regression test before changing code;
5. commit the fix under a new protocol amendment/tag;
6. invalidate and rerun every molecular result produced under affected code;
7. never reuse an affected result as final evidence.

A scientific protocol amendment is allowed only for a correctness or safety
defect. It must not be based on obtaining a preferred molecular reduction. The
old protocol and result remain preserved and explicitly superseded.

## 7. V4.1-to-V5 handoff evidence

V4.1 must produce evidence that determines V5's first research task:

- If predicted and actual losses agree and exact optimization is stable, V5 can
  prioritize resource-aware beam search.
- If predictions are poor but exact candidates can be compressed, V5 should
  prioritize candidate-local curvature refinement.
- If safe posthoc candidates consistently exceed the energy budget, V5 should
  investigate interleaved pruning followed by renewed ADAPT growth.
- If numerical/optimizer failures remain, V5 must first develop a separate
  compression curvature model with damping, restart, and held-out validation.

No V5 beam width, HVP budget, sequential batch size, or performance threshold is
to be frozen until the V4.1 sentinel evidence is audited.
