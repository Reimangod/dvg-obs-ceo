# PRA critical-path evidence plan

## Certified native rank demotion of CEO-ADAPT ansätze

Status: research and implementation plan; no new performance claim  
Parent release: `v6.1-t2-negative-result-complete-v1`  
Parent commit: `406ccbf49691aec638d78951959cdc6eeb7f472f`  
Development branch: `pra-critical-path`  
Regime: exact noiseless statevector simulation  
Intended article type: *Physical Review A* Regular Article  

## 1. Purpose

The shortest defensible path toward a PRA submission is not another sequence
of feature versions. It is an evidence program that determines whether the
already implemented synthesis-certified CEO rank demotion produces
reproducible, matched-work Pareto improvements beyond the single positive H4
development condition.

The central research claim under test is:

> A registered three-to-two parameter demotion of a full-rank MVP-CEO block,
> implemented with a dedicated native circuit and guarded by independent
> semantic, energy, stationarity, transaction, and full-circuit resource
> certification, can add new matched-work energy-resource Pareto points to
> converged CEO-ADAPT ansätze.

This statement is a hypothesis until the development and prospective gates
below pass. The plan does not guarantee a positive result or publication.

## 2. Evidence already fixed

The following are immutable development evidence:

- V6 established native, registered rank-two target circuits.
- H4 1.5 Å late checkpoint admitted two sequential demotions with numerical
  state preservation and strict CNOT, CNOT-depth, total-depth, and parameter
  reductions.
- The resulting H4 point is historically nondominated through an
  energy/CNOT-depth tradeoff, but matched-work superiority is not established.
- The tested H6 1.5 Å and 3.0 Å candidate families were not certified under
  the frozen NS7/NS10 protocols.
- BeH2 3.0 Å had no eligible frozen rank-three MVP block.
- V6.1 showed that conditional tangent/QFI redundancy alone cannot separate
  all accepted and rejected sequential demotions.

None of these artifacts may be rewritten or relabeled as prospective.

## 3. Corrections to the interpretation boundary

### 3.1 Gradient semantics

The historical NS7 field `source_gradient_infinity` was evaluated at the
mapped candidate point in the full source-coordinate system. It is not the
gradient of the original source checkpoint.

Future schemas use four separate quantities:

```text
source_checkpoint_parameter_gradient_infinity
candidate_full_source_coordinate_gradient_infinity
candidate_target_coordinate_gradient_infinity
candidate_orthonormal_tangent_gradient_infinity
```

For an embedding `theta = c + J phi`, constrained stationarity is assessed in
the target tangent space. A nonzero full-coordinate gradient is permitted
along the constraint normal. Both `J^T g` and the projection `Q^T g`, where
`Q` is an orthonormal basis of `range(J)`, are reported. The orthonormal
projection is the primary coordinate-invariant stationarity evidence.

### 3.2 H6 claim

The permitted statement is:

> The registered rank-two families were not certified on the two tested H6
> source checkpoints under the frozen optimization protocols.

The evidence does not establish impossibility for H6, failure for every rank
family, or general failure of CEO rank demotion.

### 3.3 Journal criteria

All numerical submission gates in this plan are conservative internal
decisions. They are not represented as official PRA acceptance requirements.

## 4. Scope

### Included

- gradient-semantics and source-identity audit;
- historical and stationarity-normalized source definitions;
- formal rank-two normal registry and equivalence rules;
- primary-source prior-art audit;
- outcome-free applicability census;
- a second independent development test;
- matched-work comparison and minimum causal ablations;
- one unseen validation molecule at two preregistered geometries;
- release, reproduction, and manuscript evidence package.

### Excluded from the critical path

- QFI or tangent-based production selection;
- reachability as a production selector;
- new optimizer search after observing a frozen outcome;
- repair growth or additional ADAPT operators;
- measurement reuse, OGM changes, or a new Measurement Cost definition;
- noisy simulation or hardware claims;
- changes to qubit mapping between methods;
- claims that V6 is best for all molecules.

Pointwise target-manifold reachability is optional descriptive analysis only.
It may be attempted after the second independent positive condition, under a
separate preregistration. A numerical fidelity maximum is not called a global
proof without a certified bound.

## 5. Stage overview

| Stage | Purpose | Performance computation |
|---|---|---|
| S0 | Immutable parent and evidence ledger | No |
| S1 | Gradient semantics and identity audit | No new optimization |
| S2 | Two-layer source protocol | Source-only |
| S3 | Normal registry and mathematical scope | No |
| S4 | Prior-art and novelty audit | No |
| S5 | Outcome-free applicability census | No candidate energy |
| S6 | Independent development evaluation | Yes |
| S7 | Matched-work and causal ablation | Yes |
| S8 | Final prospective protocol freeze | No |
| S9 | One molecule × two-geometry validation | Yes, once |
| S10 | Scientific and editorial strength gate | No new search |
| S11 | Reproducible release and manuscript package | Reproduction only |

Every stage ends with an immutable artifact, audit, commit, and annotated tag.
A failed gate records `NOT_AUTHORIZED` for dependent stages.

## 6. S0 — immutable parent and evidence ledger

### Actions

- bind the parent tag and peeled commit;
- record the vendored CEO* commit and dependency lock digest;
- hash V6 NS7--NS10 and V6.1 T0--T2 artifacts;
- classify every system/geometry as development, prospective, or excluded;
- record every prior outcome already visible to the researchers;
- create a new artifact root without moving historical artifacts.

### Intended paths

```text
artifacts/pra_path/
src/dvg_obs_ceo/pra_path/
tests/pra_path/
docs/PRA_CRITICAL_PATH_*.md
```

### Prohibitions

- no modification of `artifacts/v6/` or `artifacts/v6_1/`;
- no force-push of audited branches or tags;
- no claim that the new branch makes old data prospective.

### Exit gate

All hashes, labels, and parent references reconcile from a clean clone.

## 7. S1 — gradient semantics and source-identity audit

This is the first required technical stage. No source is reoptimized before
it completes.

### Required comparisons

For H6 1.5 Å and 3.0 Å, compare NS7 and NS10 controls using:

```text
StatePreparationID
ProblemID
MeasurementContextID where applicable
ansatz structure digest
ansatz index digest
coefficient digest
source statevector digest
source energy
Hamiltonian digest
reference-state digest
qubit mapping and ordering
```

Independently recompute at the unmodified source checkpoint:

- full parameter gradient;
- energy;
- normalized state digest;
- ansatz and block structure;
- ADAPT pool gradient if reconstructible.

For each stored candidate independently recompute:

- full source-coordinate gradient `g`;
- target coordinate gradient `J^T g`;
- orthonormal tangent gradient `Q^T g`;
- normal component and a KKT multiplier/residual;
- finite-difference spot checks in target coordinates.

### Decision tree

1. IDs and digests match and source is stationary:
   classify the old issue as ambiguous field naming; preserve all decisions.
2. IDs differ:
   open a source-mismatch incident; old H6 comparison remains development-only
   and is not used as a causal baseline.
3. Source is genuinely nonstationary:
   create a stationarity-normalized source under S2 and rerun every compared
   method from that common source.

### Outputs

- machine-readable semantics supplement;
- field dictionary with units, evaluation point, coordinate system, and
  normalization;
- source-identity reconciliation report;
- regression tests preventing candidate and checkpoint gradients from sharing
  a field name.

### Exit gate

Every gradient field has one unambiguous evaluation point and coordinate
system, and NS7/NS10 source identity is established or explicitly rejected.

## 8. S2 — two-layer source protocol

### 8.1 Historical source

`historical_paper_endpoint_source` preserves paper-era and previous-project
comparison endpoints. It is used only for historical reproduction.

### 8.2 Stationarity-normalized source

`stationarity_normalized_source` is the causal starting point for new
development, matched-work, and prospective comparisons.

Required source evidence:

- fixed molecule, geometry, basis, active space, frozen orbitals, mapping,
  ordering, pool, TETRIS/selection rules, optimizer, and seed policy;
- parameter gradient `||grad_theta E||_infinity <= 1e-8`;
- independent analytic/finite-difference agreement;
- ADAPT pool-gradient and stopping rule stored separately;
- optimizer status, energy change, iteration/work ledger;
- exact state, coefficient, structure, Hamiltonian, and problem digests;
- full source resource recount.

If the historical source already passes these conditions, it may receive both
roles without changing its coefficients.

### Work reporting

Two comparisons are retained:

1. post-checkpoint compression work, where common deterministic source
   polishing is shown separately;
2. end-to-end work, where source production and polishing are included.

### Exit gate

All methods in a causal comparison begin from byte-identical source
coordinates and structure.

## 9. S3 — normal registry and mathematical scope

### Registry freeze

Before candidate outcomes, define:

- allowed coefficient alphabet;
- primitive-vector and global-sign canonicalization;
- zero-component policy;
- constituent ordering and generator orientation;
- permutation equivalence rules;
- native-synthesis availability;
- semantic family embedding;
- structural resource-nonworsening filter;
- canonical queue and deduplication.

The existing discrete registry and the two NS7 normals are not assumed to be
complete representatives without proof.

### Symmetry proof obligation

If `(1,1,1)` and `(1,1,-1)` are claimed to represent all nonzero `±1`
patterns, prove that the three constituent slots are equivalent under a
permutation that preserves:

- ordered generators and signs;
- source/target family semantics;
- parameter-map normalization;
- native circuit resources;
- surrounding ansatz context.

If this is not established, each inequivalent canonical normal is retained.
No general integer-normal or all-rank-two-Grassmannian completeness claim is
made.

### Exit gate

The method is described either as a complete search over a proved finite
registry or as a deliberately limited synthesis-certified registry.

## 10. S4 — primary-source prior-art and novelty audit

Search and compare:

- CEO MVP/OVP definitions and native circuits;
- parameter tying and block-rank reduction;
- post-ADAPT operator pruning;
- low-rank excitation and coupled-excitation blocks;
- native multi-parameter excitation synthesis;
- variational-manifold and circuit compression;
- QFI/effective-dimension parameter removal;
- sequential and dynamic pruning.

For every work, store publication status:

```text
peer reviewed
accepted
preprint
software/documentation only
```

### Required novelty matrix

| Feature | Prior work | This work | Evidence |
|---|---|---|---|
| Three-to-two CEO family |  |  | theorem/registry |
| Dedicated target-native circuit |  |  | QASM/equivalence |
| Pointwise/statewise evidence |  |  | audit |
| Transactional approximate demotion |  |  | implementation |
| Full-circuit recount |  |  | independent counter |
| Matched-work sequential evaluation |  |  | prospective data |

### Claim freeze

Do not use “new rank transition” in the manuscript until the audit supports
it. A safe fallback is:

> a synthesis-certified registered rank demotion not present in the compared
> V4.1 implementation.

### Exit gate

The novelty statement has direct primary citations and does not collapse the
contribution into generic pruning.

## 11. S5 — outcome-free applicability census

### Development screening order

1. preregistered H4 geometries for low-cost reproducibility;
2. preregistered non-H4 development systems;
3. a separate ordered list reserved for prospective validation.

Systems used in development cannot later be called prospective.

### Permitted census fields

- qubit count and Hilbert-space feasibility;
- source-generation success/failure;
- rank-three MVP block count;
- registered and native-synthesizable transition count;
- structural resource deltas;
- estimated source-generation and recount work.

### Forbidden census fields

- post-demotion energy;
- accepted candidate count;
- optimizer success;
- fidelity/reachability outcome;
- final Pareto status;
- exact/reference energy used for selection.

Every screened system, including zero-candidate systems, is retained. Selecting
validation only among systems with an eligible block defines a conditional
applicability population; the manuscript must report the screen-out rate and
limit claims accordingly.

### Exit gate

Development queues and the prospective candidate-selection rule are frozen
using structural information only.

## 12. S6 — independent development evaluation

### Execution order

1. low-cost H4 geometry reproducibility test;
2. one or more non-H4 development systems selected by S5;
3. all eligible registry candidates in a queue frozen before outcomes.

The H4 1.5 Å late result remains historical development and is not counted as
a new prospective result.

### Candidate certification

For each attempted demotion:

- target initialization follows one frozen rule;
- optimizer, iteration cap, starts, and fallback are fixed;
- source remains immutable;
- candidate energy is independently recomputed;
- `Delta E <= 1e-4 Ha` relative to the normalized common source;
- orthonormal tangent stationarity is `<= 1e-8`;
- target-coordinate stationarity and KKT normal component are reported;
- semantic/native state and energy agree within frozen tolerances;
- constraint residual passes;
- full native circuit is rebuilt and recounted;
- at least one primary physical resource strictly improves;
- no primary physical resource worsens under the frozen policy;
- commit or complete rollback is recorded.

### Development success

A condition succeeds only if it adds a new nondominated
energy-resource point within its declared work envelope.

Preferred continuation condition:

- at least one additional H4 geometry demonstrates reproducibility; and
- at least one separate molecule demonstrates cross-system applicability.

If no non-H4 positive condition is found within the frozen development set,
the PRA performance route stops. No new normal, optimizer, or threshold is
added after outcomes.

## 13. S7 — matched-work comparison and causal ablation

### Primary methods

1. immutable CEO* source;
2. same-structure reoptimization;
3. magnitude pruning;
4. V5 sequential rebuilding;
5. rank constraint with the old MVP physical circuit;
6. native rank circuit, single round;
7. full sequential native rank demotion.

V4.1 and V5.1 are secondary only when the identical source can be reconstructed
and their work ledger is complete. Otherwise report `UNAVAILABLE` or
`UNMATCHED`, never an inferred matched result.

### Work vector

Store, without arbitrary summation:

\[
W=(N_E,N_G,N_{\mathrm{gradcomp}},N_{\mathrm{HVP}},
N_{\mathrm{exact}},N_{\mathrm{recount}},N_{\mathrm{rewrite}},
N_{\mathrm{states}},N_{\mathrm{rounds}}).
\]

Failed, rejected, and rolled-back attempts count toward work.

### Work envelopes

Freeze `LOW`, `MEDIUM`, and `HIGH` componentwise caps using development data
only. All methods stop when the next operation would exceed a cap. Wall time
is secondary and is reported on one pinned environment.

No heterogeneous work vector is relabeled as the CEO paper's Measurement
Cost. Paper Measurement Cost remains null unless computed by its original
definition.

### Primary figures

- energy loss versus CNOT;
- energy loss versus CNOT depth;
- energy loss versus total depth;
- energy loss versus parameter count;
- cumulative work versus CNOT reduction;
- cumulative work versus CNOT-depth reduction.

### Exit gate

At least two independent development conditions must gain a new matched-work
nondominated point for the internal PRA submission path to continue.

## 14. S8 — final prospective protocol freeze

Freeze in one tagged manifest:

- source-generation and stationarity protocol;
- normal registry and structural filter;
- candidate order and tie rules;
- optimizer and complete fallback policy;
- energy, stationarity, semantic, and resource tolerances;
- transactional rollback;
- work profiles;
- comparator set;
- winner/Pareto policy;
- validation molecule-selection rule;
- rerun and incident policy.

### Validation selection

Use an ordered molecule list fixed before performance outcomes. Select the
first molecule for which both preregistered geometries:

- can generate the frozen CEO* source;
- are statevector feasible under the declared limit;
- satisfy the predefined structural applicability requirement.

Excluded candidates and reasons remain public. The selected molecule and two
geometry IDs are committed and tagged before any demotion energy is evaluated.

### Exit gate

An independent audit can determine every runtime decision from the frozen
manifest without human scientific intervention.

## 15. S9 — prospective one-molecule/two-geometry validation

Run once per geometry:

1. generate or load the frozen stationarity-normalized CEO* source;
2. verify all IDs, hashes, stationarity, and resources;
3. execute the frozen candidate queue;
4. execute matched-work comparators;
5. perform independent energy, gradient, state, transaction, and resource
   audits;
6. join exact/high-accuracy references only for offline reporting;
7. preserve positive, negative, and no-candidate outcomes.

Only a failed run caused by a documented engineering defect may be repeated.
The defect, partial-output status, correction commit, and unchanged scientific
protocol must be recorded before rerun.

### Internal validation gate

- at least one of two geometries adds a new matched-work nondominated point;
- the other geometry remains fully reported;
- no thresholds, registry entries, source rules, or optimizers change after
  either outcome.

## 16. S10 — scientific and editorial strength gate

This stage does not tune the method.

### Internal PRA submission gate

Proceed to a PRA submission package only if:

1. prior-art audit supports a distinct methodological contribution;
2. a native physical CNOT or depth reduction is independently verified;
3. two independent development conditions add matched-work Pareto points;
4. at least one prospective geometry adds a matched-work Pareto point;
5. all null/negative outcomes are retained and explained within evidence;
6. causal ablation separates parameter tying, extra optimization, native
   synthesis, and sequential rebuilding;
7. every accepted point passes semantic, energy, coordinate-invariant
   stationarity, transaction, and resource audits;
8. a clean environment reproduces tables and figures.

### Effect-size assessment

Five-to-ten-percent reduction is an editorial heuristic, not a scientific
acceptance threshold. Report confidence intervals or deterministic spreads
where applicable and assess:

- magnitude of the strongest prospective physical-resource improvement;
- consistency across conditions;
- computational work required to obtain it;
- strength of the mathematical and mechanism explanation.

If the evidence remains one small H4-only improvement, do not describe the
method as generally performance improving. Journal selection is based on
scope and contribution, not a presumed hierarchy or unsupported acceptance
probability.

## 17. S11 — reproducible release and manuscript package

### Release

- public GitHub tag and release;
- persistent archive/DOI such as Zenodo;
- source and vendored dependency commits;
- lockfile and container;
- machine-readable sources, queues, outcomes, work ledgers, and manifests;
- negative/no-candidate results and incident logs;
- audited CSV tables and figure-generation scripts;
- one-command audit and reproduction guide;
- Data Availability and Code Availability statements.

### Main figures

1. CEO block rank registry and target-native circuit;
2. embedding, pointwise, native, stationarity, and resource evidence layers;
3. matched-work energy-CNOT frontier;
4. matched-work energy-CNOT-depth frontier;
5. cumulative work-resource curves;
6. development applicability and positive/negative map;
7. two-geometry prospective validation;
8. minimum causal ablation.

V6.1 QFI No-Go belongs in a mechanism-limit subsection or supplement and is
not presented as a production feature.

## 18. System-engineering requirements at every stage

### Artifact safety

- atomic write-new only;
- canonical finite JSON;
- schema and implementation versions;
- input/output hashes;
- no in-place migration of historical data;
- separate temporary, result, audit, and release roots;
- complete rollback after any rejected transformation.

### Execution safety

- clean committed worktree for outcome-producing runs;
- annotated pre-outcome tag;
- pinned single-thread numerical environment;
- deterministic sort, tie, and seed policies;
- hard work caps enforced before an operation starts;
- heartbeat/progress ledger for long jobs;
- resumability only from audited checkpoints;
- independent recomputation of accepted results.

### Identity safety

Keep distinct:

- `StatePreparationID`: state-preparation semantics and exact coefficients;
- `ProblemID`: Hamiltonian and molecular problem;
- `MeasurementContextID`: observable set, grouping/estimator, and backend
  context.

Energy or gradient evidence is reusable only when all required identities and
measurement semantics match.

### Version control

- one branch per protocol-changing phase;
- one intentional commit per logical stage;
- annotated tag before and after outcome-producing execution;
- no force-push or tag replacement;
- CI, local tests, isolation check, and release audit before result tags;
- corrections use new commits, tags, and provenance supplements.

## 19. Academic-transparency requirements

- distinguish mathematical proof, numerical certification, and empirical
  observation;
- distinguish historical, development, and prospective evidence;
- identify peer-reviewed papers and preprints separately;
- keep FCI/high-accuracy reference data outside runtime selection;
- report every screened system and every frozen candidate;
- include rejected attempts and their work;
- never infer physical reduction from parameter deletion alone;
- never call a historical Pareto comparison matched-work;
- never claim generalization from one molecule or correlated geometries;
- record all protocol amendments and the outcomes already visible when made.

## 20. Completion conditions

The program is complete in either of two ways.

### Positive completion

S0--S11 complete, the internal PRA submission gate passes, and the
reproducible manuscript package supports the narrow central claim.

### Negative completion

A preregistered gate fails, dependent stages are marked `NOT_AUTHORIZED`, and
the release explains:

- where the method ceased to apply;
- whether failure arose from no candidate, energy, stationarity, resources,
  work, or reproducibility;
- which narrower scientific claim remains supported.

Negative completion is not repaired by adding another selector, optimizer, or
normal after observing outcomes.

## 21. Immediate execution order

```text
S0  immutable parent/evidence ledger
S1  gradient semantics and NS7/NS10 identity audit
S2  historical/normalized source protocol
S3  normal-registry scope proof
S4  prior-art novelty audit
S5  outcome-free census and queue freeze
S6  second independent development positive test
S7  matched-work minimum ablation
S8  final prospective freeze
S9  one molecule × two geometries
S10 internal PRA strength decision
S11 release and manuscript package
```

No later-stage performance computation is authorized until all preceding
gates pass.
