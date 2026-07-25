# V6 PRA research and implementation plan

## Certified Rank-Adaptive CEO Ansatz Surgery

Status: preregistration and implementation plan; no V6 performance claim yet  
Parent branch: `stable-v5-correctness-audit`  
Verified parent HEAD at plan creation: `6e0984c`  
Intended development branch: `v6-certified-rank-adaptive`  
Intended source root: `src/dvg_obs_ceo/v6_rank_adaptive/`  
Intended test root: `tests/v6_rank_adaptive/`  
Intended artifact root: `artifacts/v6/`  
Study regime: exact statevector, noiseless, post-checkpoint CEO ansatz compression  
Target venue: *Physical Review A*, Regular Article  

## 1. Purpose, central hypothesis, and non-guarantee

V6 is not a collection of every proposed improvement. It tests one central
research hypothesis:

> The internal parameter freedom of CEO-ADAPT blocks can be adaptively reduced
> on a native-synthesis-certified rank lattice, producing new accuracy-resource
> Pareto points under frozen energy, stationarity, and computational-work
> constraints.

The proposed methodological contribution is:

1. define CEO block rank and registered lower-rank target families;
2. separate target-family embedding, source-point preservation, native
   synthesis, contextual validity, and physical-resource improvement;
3. accept physical compression only after rebuilding and recounting the full
   native circuit;
4. compare all methods under preregistered, matched computational-work
   envelopes;
5. retain negative results, failed transformations, rollbacks, and protocol
   changes as immutable evidence.

No plan can guarantee superior performance before prospective execution.
Engineering containment of old points is not scientific superiority. The
scientific question is whether V6 creates new nondominated points under the
same work budget.

The intended paper claim is narrower than “V6 is always best”:

> Synthesis-certified rank adaptation improves the matched-work
> accuracy-resource frontier on multiple molecular conditions, and its
> successes and failures can be explained by CEO block topology, available
> native rank transitions, and the energy/stationarity budget.

## 2. Scope and claim boundary

### 2.1 V6 core includes

V6 core contains only:

- bounded, registered exact rewrites;
- a synthesis-certified CEO block-rank lattice;
- guarded approximate rank demotion;
- native target-circuit synthesis;
- full-circuit CNOT, CNOT-depth, total-depth, parameter, and logical-block
  recounting;
- transactional sequential checkpoint compression;
- matched-work Pareto search and evaluation;
- the minimum target-native optimization needed to certify a candidate.

### 2.2 V6 core excludes

The following are not part of the V6 core causal claim:

- QFI-based ranking or trust regions;
- repair-operator growth or continued architecture search;
- machine learning;
- noisy simulation or hardware experiments;
- changes to qubit mapping or hardware topology;
- OGM, measurement reuse, or a redefined Measurement Cost;
- unrestricted e-graphs or generic global compilation;
- barrier-free full-ansatz Qiskit compilation;
- molecule-specific thresholds selected after seeing V6 outcomes.

ExcitationSolve may be added only as a separately registered optimizer
ablation for operator families whose algebra and abstract parameter occurrence
have been verified. It is never treated as the source of rank compression.

### 2.3 Existing code and results remain immutable

- V4.1, V5, and V5.1 source files and completed artifacts are not rewritten.
- Historical artifacts are not migrated in place.
- V6 adapters may read historical artifacts, but every normalized
  representation receives a new digest and explicit provenance.
- No historical result is relabeled as prospective validation.
- Existing CEO* development checkpoints are reused; they are not regrown.
- Ordinary ADAPT-VQE is outside the V6 comparison scope.

Prospective validation still requires an independently defined CEO* source
checkpoint because V6 is a post-checkpoint compression algorithm. If no
unseen, preregistered CEO* checkpoint exists and generating one remains out of
scope, unseen molecular validation is impossible and a generalization claim is
prohibited. A new validation checkpoint, if authorized, is baseline
production—not a new CEO* performance study—and must be generated using a
frozen, paper-era-compatible protocol without FCI-guided stopping.

## 3. Evidence inherited from V4.1, V5, and V5.1

All previously examined molecules and geometries are development data,
including H2, early and late H4, LiH 3.0 A, H6 1.5 A, H6 3.0 A, and BeH2
3.0 A.

The existing audit establishes the following design facts:

- the strongest legacy method differs by molecular condition;
- LiH is near the structural floor of the existing candidate family;
- H6 is MVP-heavy, and constituent-parameter deletion often leaves an
  expensive physical block in place;
- V5 can improve a result through sequential rebuilding, but some improvements
  use more search work than V4.1;
- V5.1 exact fusion opportunities are rare and strongly dependent on block
  ordering and support;
- parameter reduction is not a physical-circuit result unless the target is
  natively resynthesized and the full circuit is recounted;
- FCI/exact reference energy must remain offline reporting information and
  must not enter runtime ranking or acceptance.

V6 must address the structural problem directly. Renaming existing
MVP-to-OVP, MVP-to-QE, constituent deletion, and whole-block deletion
operations as a “rank lattice” is not sufficient novelty.

## 4. Mathematical contract

### 4.1 Source block family

For CEO block \(b\), let the ordered, canonical constituent generators be

\[
\mathcal{G}_b = \{G_{b,1},\ldots,G_{b,m_b}\}, \qquad
m_b \in \{1,2,3\}.
\]

The source family is

\[
U_b^{(S)}(\theta_b)
=
\exp\left(\sum_{i=1}^{m_b}\theta_{b,i}G_{b,i}\right).
\]

Generator normalization, sign, support, ordering, mapping, and orientation are
part of the semantic identity. Two generators are never declared equal from a
display label alone.

### 4.2 Target family and rank

A registered target family \(t\) is defined by

\[
\theta_b=f_{b,t}(\phi_b).
\]

The general theory may admit analytic \(f_{b,t}\), but the first V6
implementation permits only:

```text
AFFINE_EXACT
PERIODIC_AFFINE_EXACT
REGISTERED_ANALYTIC_MAP
```

For an affine target,

\[
\theta_b=c_{b,t}+J_{b,t}\phi_b,
\qquad
r_{b,t}=\operatorname{rank}(J_{b,t}).
\]

Arbitrary user-supplied nonlinear maps are rejected in V6. A registered
analytic map requires a named proof or derivation, canonical serialization,
domain restrictions, a deterministic inverse/membership procedure when
needed, and independent tests.

### 4.3 Exact target embedding

A target is an exact subfamily only when

\[
\forall\phi,\quad
U_T(\phi)
=e^{i\gamma(\phi)}U_S(f(\phi)).
\]

This is a family-level property. It does not imply that the current source
point belongs to the target.

### 4.4 Source-point preservation

Parameter membership is one sufficient route:

\[
\exists\phi_s:\quad \theta_s=f(\phi_s).
\]

Pointwise unitary preservation is stronger and representation independent:

\[
\exists\phi_s,\gamma_s:\quad
U_T(\phi_s)=e^{i\gamma_s}U_S(\theta_s).
\]

For a fixed reference state, pointwise state preservation is weaker:

\[
U_T(\phi_s)|\psi_{\mathrm{ref}}\rangle
=
e^{i\gamma_s}U_S(\theta_s)|\psi_{\mathrm{ref}}\rangle.
\]

State preservation at a single checkpoint is not registered as a general
rewrite rule. It is valid only for the recorded state and context.

### 4.5 Approximate rank demotion

If the source point is not shown to belong to the target family, the move is
approximate even when the target family is an exact source subfamily and its
native implementation is correct. Approximate moves require:

- target-native reoptimization;
- independent energy recomputation;
- independent stationarity recomputation;
- constraint and semantic validation;
- full-circuit resource verification;
- transaction commit or complete rollback.

## 5. Evidence model

Evidence is stored on orthogonal axes. A single flat label is generated only
for human-readable reporting.

### 5.1 Transformation evidence

```text
TargetEmbeddingEvidence
SourceParameterMembershipEvidence
SourceStateEquivalenceEvidence
SourceUnitaryEquivalenceEvidence
NativeSynthesisEvidence
ContextualRewriteEvidence
```

Each evidence record contains:

- source and target semantic IDs;
- scope;
- evidence strength;
- method or theorem identifier;
- tolerances when numerical;
- input and output digests;
- implementation and schema versions;
- pass, fail, or not-established status;
- failure reason and supporting artifact.

### 5.2 Evidence strength

```text
ALGEBRAICALLY_PROVEN
SYMBOLICALLY_PROVEN
PROVENANCE_DERIVED
NUMERICALLY_VALIDATED
NOT_ESTABLISHED
```

Finite-dimensional matrix comparisons, state fidelity, energy equality,
random-state tests, and finite parameter samples are numerical validation, not
mathematical proof.

### 5.3 Semantic scope

```text
PARAMETER_MAP
POINTWISE_STATE
POINTWISE_UNITARY
FAMILYWISE_UNITARY
```

### 5.4 Context scope

```text
CHECKPOINT_FULL_STATE
PREFIX_STATE
LOCAL_BLOCK
ARBITRARY_CIRCUIT_CONTEXT
```

### 5.5 Native-synthesis scope

```text
POINTWISE
FAMILYWISE
```

### 5.6 Optimization requirement

```text
NONE
POLISHING
FULL_REOPTIMIZATION
```

### 5.7 Resource evidence

`ResourceDeltaEvidence` is separate from transformation exactness and records:

```text
parameters
logical_blocks
cnot_count
cnot_depth
total_depth
resource_counter_version
native_synthesizer_version
compiler_configuration
qubit_order
before_digest
after_digest
```

A rank or parameter reduction with no strict physical-resource improvement is
recorded as:

```text
rank_reduction: true
physical_compression: false
```

It is retained as a negative structural result and is not counted as circuit
compression.

## 6. Registered rank lattice

### 6.1 Two-constituent CEO

```text
rank 2: full MVP
rank 1: OVP-plus / OVP-minus / constituent QE
rank 0: whole-block deletion
```

### 6.2 Three-constituent same-spin CEO

```text
rank 3: full MVP
rank 2: synthesis-certified native rank-2 CEO
rank 1: registered pairwise OVP-plus / OVP-minus / constituent QE
rank 0: whole-block deletion
```

The rank-2 node is the primary feasibility question. “Set one MVP parameter to
zero but keep the original MVP circuit” is a parameter constraint, not a new
native rank-2 circuit.

### 6.3 Transition-registry requirements

Every transition must declare:

- source and target family IDs;
- allowed constituent count and spin/support pattern;
- parameter map and rank;
- generator relation;
- native synthesis implementation;
- expected logical and physical resource changes;
- exact or approximate source-move status;
- applicable context;
- unit tests, metamorphic tests, and deliberate failure tests.

Unknown families and unregistered composite generators fail closed.

## 7. V6 round algorithm

Each sequential round operates only on the last committed checkpoint:

```text
verify committed checkpoint and identities
        |
bounded exact-rewrite pre-pass
        |
build registered CEO rank catalog
        |
native synthesis and full resource pre-recount
        |
joint affine KKT/OBS screening
        |
construct predicted Pareto set
        |
freeze candidate IDs, order, Top-K, and work budget
        |
run independent target-native exact VQE attempts
        |
independently certify energy, stationarity, semantics, and resources
        |
commit one accepted state or roll back the round
        |
rebuild the complete catalog from the committed state
```

### 7.1 Bounded exact-rewrite pre-pass

Only registered rules are allowed initially:

- V5.1 OVP-to-MVP absorption;
- same-generator fusion;
- inverse cancellation;
- exact signed-coordinate absorption;
- bounded commuting-corridor moves;
- exact zero-coordinate block elimination.

The deterministic stopping limits are:

```text
maximum rewrite depth
maximum rewrite states
maximum expression size
maximum corridor length
```

Wall-clock time is measured but is not the formal stopping rule. Rewrite
search work is not “free” merely because a successful exact rewrite has zero
energy loss.

### 7.2 Candidate eligibility

Pre-outcome amendment: the versioned S8.1 freeze separates a
`circuit-primary` track, protecting both CNOT count and CNOT depth, from an
`exploratory depth/parameter` track. Candidates that regress either protected
circuit-primary resource cannot support the primary performance claim, even
when they proceed as explicitly labeled exploratory feasibility attempts.
See `docs/V6_S8_1_PRE_OUTCOME_PROTOCOL_FREEZE.md`.

A candidate enters numerical screening only if:

- its target family and parameter map are registered;
- generator orientation and support are canonical;
- a native synthesis path exists;
- the target full circuit can be constructed deterministically;
- semantic checks do not fail;
- at least one physical resource strictly improves;
- the preregistered primary resource does not regress;
- all required identities and source digests match.

### 7.3 Screening and ranking

The existing nonzero-gradient affine KKT/OBS model is retained. It is not
replaced by a stationary, diagonal-only, or magnitude-only approximation.

The candidate vector remains multiobjective:

\[
\left(
\widehat{\Delta E},
N_{\mathrm{CNOT}},
D_{\mathrm{CNOT}},
D_{\mathrm{total}},
N_{\mathrm{param}},
N_{\mathrm{block}}
\right).
\]

No hidden weighted scalar is the primary ranking rule. Hard pre-exact rejection
is limited to:

- semantic invalidity;
- nonfinite input or result;
- invalid rank or affine map;
- infeasible or failed constrained solve;
- missing native synthesis;
- no physical-resource gain;
- deterministic work-cap exhaustion;
- unambiguous predicted energy-budget infeasibility.

Prediction margins are empirical ranking diagnostics, not certified upper
bounds.

### 7.4 Candidate freeze

Before evaluating actual candidate energy, an immutable artifact records:

- source checkpoint and identity digests;
- candidate semantic IDs;
- predicted evidence and resources;
- complete ranking and tie-breaks;
- Top-K and evaluation order;
- remaining energy and work budgets;
- protocol, code, and environment digests.

Actual energy may not reorder or introduce candidates in the same round.

### 7.5 Exact attempt and acceptance

Optimizer termination and scientific acceptance are separate records.
Acceptance requires all frozen gates:

\[
E_{\mathrm{candidate}}-E_{\mathrm{source}}
\le 10^{-4}\ {\rm Ha},
\]

\[
\lVert g_{\mathrm{target}}\rVert_\infty
\le 10^{-8},
\]

plus:

- independent energy agreement;
- independent state recomputation;
- target constraint residual;
- two-path gradient audit where a source-target map is used;
- semantic and context evidence;
- native full-circuit resource recount;
- primary-resource nonregression;
- complete work ledger;
- successful atomic transaction publication.

FCI energy, chemical-accuracy margin, and post-hoc winner information are not
available to runtime ranking, screening, optimization, or acceptance.

### 7.6 Commit and rollback

- A candidate is published only through the atomic artifact transaction.
- A failed candidate leaves no partial committed state.
- If all candidates fail, the round rolls back to the last accepted
  checkpoint.
- A later-round failure never invalidates an earlier accepted checkpoint.
- Crash, timeout, signal, NaN, malformed artifact, counter mismatch, and audit
  failure all follow the same fail-closed rollback contract.

## 8. Sequential and beam search

V6 reuses the audited transactional sequential framework but does not claim it
as new.

Beam width is calibrated only on development data from:

```text
1, 2, 4
```

Beam retention uses:

1. actual accepted Pareto nondominance;
2. a preregistered endpoint quota;
3. canonical semantic ID tie-breaking.

No single weighted score may discard all alternatives. Search stops on:

- no eligible candidate;
- insufficient remaining energy budget;
- a work-profile cap;
- maximum sequential rounds;
- no strict physical-resource gain;
- a recorded incident.

## 9. Work accounting and matched comparison

### 9.1 Work vector

\[
W =
\left(
N_E,
N_G,
N_{\mathrm{gradcomp}},
N_{\mathrm{HVP}},
N_{\mathrm{exact}},
N_{\mathrm{recount}},
N_{\mathrm{rewrite}}
\right).
\]

The ledger separately stores:

- energy evaluations;
- gradient-vector evaluations;
- gradient-component equivalents;
- HVP evaluations;
- exact VQE attempts;
- full resource recounts;
- rewrite generation and verification work;
- optimizer iterations;
- search states;
- wall-clock and CPU time;
- failures, retries, and rejected operations.

These heterogeneous quantities are not collapsed into the CEO paper's
Measurement Cost. Measurement Cost is outside the present noiseless study
unless it is independently reimplemented under a separate protocol.

### 9.2 Budget profiles

Development calibration freezes three named envelopes:

```text
LOW
MEDIUM
HIGH
```

Each profile places explicit hard caps on every relevant work component,
including exact attempts, gradient components, HVPs, search states, resource
recounts, rewrite states, and sequential rounds.

Wall-clock time is reported under fixed hardware and thread settings but is not
the sole comparison or stopping rule.

### 9.3 Comparators

Under the same source checkpoint and work profile, compare:

- V4.1 one-shot compression;
- V5 sequential rebuilding;
- V5.1 exact fusion;
- magnitude pruning;
- rank adaptation without native resynthesis;
- same-structure reoptimization only;
- bounded exact rewrite only;
- full V6.

Existing legacy artifacts may be used only when their work ledger and protocol
are sufficiently reconstructible. Otherwise the comparison is labeled
unmatched or unavailable rather than silently imputed.

Containment mode may seed legacy points for engineering regression tests. Its
hypervolume or “best result” is never used as scientific performance evidence.

## 10. Identity, provenance, and replay

V6 preserves the three-layer identity model:

- `StatePreparationID`;
- `ProblemID`;
- `MeasurementContextID`.

The ArchitectureState additionally records:

```text
ordered block IR
generator semantics
canonical coefficients
parameter maps
native synthesis provenance
resources
work ledger
evidence inventory
parent checkpoint
protocol and environment
```

Historical replay levels are:

| Level | Meaning |
|---|---|
| L0 | original artifact byte digest and inventory verified |
| L1 | semantic normalization to V6 IR completed |
| L2 | source state, energy, and resources reconstructed |
| L3 | candidate catalog and ranking replayed |
| L4 | exact attempts, decisions, and rollback replayed |
| L5 | complete trajectory and work ledger replayed |

Every replay artifact declares:

```text
original_artifact_digest
normalized_ir_digest
reconstructible_fields
unavailable_fields
derived_fields
replay_strength
```

Missing historical data are never inferred and presented as original evidence.

## 11. Development and prospective validation

### 11.1 Development set

All cases whose outcomes influenced the design are development data:

- H2;
- early and late H4;
- LiH 3.0 A;
- H6 1.5 A;
- H6 3.0 A;
- BeH2 3.0 A.

These cases may determine:

- transition families;
- native circuit designs;
- numerical tolerances;
- candidate ordering;
- beam width and Top-K;
- optimizer policy;
- work profiles;
- stopping and failure rules.

They may not be called unseen validation.

### 11.2 Validation-system selection

Before V6 outcome inspection, select one feasible new molecule and at least two
geometries, preferably one equilibrium-side and one stretched condition.
Candidate systems may include H2O, H8, or a preregistered small-active-space
N2 case.

Selection may inspect only:

- qubit and active-space size;
- exact-statevector feasibility;
- molecular specification and mapping;
- availability or authorized generation of a CEO* source checkpoint;
- checkpoint generation cost;
- offline reference-energy feasibility;
- whether the source artifact and block catalog are structurally valid.

The selector may not inspect V6 compression rate, candidate energy, accepted
rank transitions, or prospective Pareto performance.

### 11.3 Prospective execution

Before validation:

- code is tagged;
- dependencies and thread settings are frozen;
- transition registry is frozen;
- all numerical thresholds and work profiles are frozen;
- candidate and winner rules are frozen;
- validation geometries are recorded;
- source-checkpoint generation/stopping rules are frozen;
- FCI/reference energies are isolated from runtime.

The validation cases are executed once under the frozen primary protocol.
Operational reruns are allowed only for a documented system failure and must
reuse the identical input and protocol digest.

## 12. Step-by-step implementation plan

Only one step is active at a time. A step may advance only after its tests,
artifact audit, documentation, and definition of done all pass. Each completed
step receives an intentional Git commit. Failed gates are reported; they are
not bypassed by silently adding QFI, repair, or molecule-specific tuning.

### S0 — Parent freeze and literature/claim audit

Actions:

- verify clean worktree, branch, HEAD, remote, submodule state, and CI;
- create an annotated parent tag;
- write a parent release manifest containing commit, submodule, environment,
  thread settings, test count, CI run, artifact inventory SHA-256, and claim
  boundary;
- verify all paper-specific factual claims against primary sources;
- distinguish peer-reviewed sources from preprints;
- create the V6 feature branch only after the parent freeze passes.

Tests and audits:

- tag points to the intended commit;
- artifact inventory is deterministic;
- manifest rejects dirty tree, incorrect dependency, and wrong submodule;
- links, DOI metadata, and quoted resource counts are source-checked.

Definition of done:

- immutable parent tag and manifest;
- clean V6 branch;
- no scientific result generated.

### S1 — Claim contract, schemas, and transition registry skeleton

Actions:

- implement schema-only definitions for evidence axes, semantic/context scope,
  native-synthesis scope, resource evidence, and classification;
- define transition-registry interfaces and fail-closed unknown-family
  behavior;
- define the V6 claim and prohibited-claim manifest;
- define protocol versioning and compatibility rules.

Tests and audits:

- schema round trips;
- unknown enum and future-version rejection;
- canonical serialization and stable digest;
- deliberate conflation of numerical validation with algebraic proof fails.

Definition of done:

- no transformation can be marked exact without required evidence fields;
- no physical-compression result can exist without resource evidence.

### S2 — Unified ArchitectureState IR and identities

Actions:

- build a new V6 ArchitectureState under
  `src/dvg_obs_ceo/v6_rank_adaptive/`;
- adapt existing StatePreparationID, ProblemID, and MeasurementContextID;
- represent ordered CEO blocks, generators, parameters, rank maps, native
  synthesis, resources, work, evidence, and parent checkpoint;
- preserve original and normalized digests.

Tests and audits:

- deterministic round trip and digest;
- qubit-order, generator-sign, coefficient-byte, orbital-parameter, and block
  order mutations change the appropriate identity;
- measurement-plan changes do not change StatePreparationID;
- incompatible ProblemID or MeasurementContextID blocks result reuse.

Definition of done:

- V6 states are reconstructible and cannot silently alias semantically
  different states or problems.

### S3 — Full differential replay of V4.1, V5, and V5.1

Actions:

- implement read-only adapters for legacy artifacts;
- normalize them to ArchitectureState;
- replay source, catalog, ranking, exact attempts, decisions, rollback,
  resources, and work to the maximum supported level;
- expose unavailable and derived fields.

Tests and audits:

- fixture-based L0-L5 replay;
- replay strength never exceeds available evidence;
- source and endpoint digests agree where reconstruction is possible;
- legacy artifacts remain byte-identical.

Definition of done:

- all legacy cases have an explicit replay report;
- no guessed field is represented as recorded history;
- discrepancies become incidents, not patched history.

### S4 — Mathematical evidence kernels

Actions:

- implement affine and periodic-affine parameter-map validation;
- implement source parameter membership;
- implement statewise and unitarywise numerical validators;
- implement generator-relation and commutation proof records;
- implement context-scope enforcement;
- add familywise versus pointwise native-synthesis evidence.

Tests and audits:

- analytic toy examples with known maps;
- periodic-equivalent parameters;
- global-phase equivalence;
- noninjective parameter examples;
- wrong-sign, wrong-support, wrong-order, and wrong-reference failures;
- numerical evidence cannot be promoted to algebraic evidence.

Definition of done:

- target embedding and source preservation are independently reportable;
- all unsupported cases fail closed.

### S5 — Native rank-transition feasibility study

This is the first major research Go/No-Go gate.

Actions:

- derive and implement candidate native circuits for at least one transition
  absent from V4.1, with the three-constituent MVP to native rank-2 CEO as the
  primary target;
- prove or explicitly delimit its target-family semantics;
- validate the native circuit familywise when possible;
- rebuild representative full ansätze and recount all resources;
- record transitions with rank reduction but no physical gain.

Go criteria:

- at least one transition absent from V4.1;
- registered mathematical target embedding;
- verified native synthesis at the claimed scope;
- strict full-circuit CNOT or depth gain;
- no semantic or contextual failure.

No-Go response:

- do not describe the existing transition set as a new rank-adaptive
  algorithm;
- retain the feasibility study and negative result;
- stop the rank-adaptive track for scientific review;
- consider bounded-exact-rewrite or repair as a separately preregistered
  research track rather than silently changing V6.

Definition of done:

- a signed feasibility report records Go or No-Go with machine-readable
  supporting evidence.

### S6 — Bounded exact-rewrite engine

Actions:

- port the audited V5.1 rule through the new registry;
- add only registered fusion, cancellation, absorption, zero-coordinate, and
  bounded commuting-corridor rules;
- implement deterministic search limits and canonical state deduplication;
- recount resources for every accepted rewrite.

Tests and audits:

- rule-level algebraic or provenance tests;
- context and commutation failures;
- deterministic saturation under reordered enumeration;
- bounded termination;
- no energy-loss claim is confused with zero search work.

Definition of done:

- the engine terminates deterministically and publishes a complete rule/work
  trace.

### S7 — Rank-candidate generation and native resource recount

Actions:

- enumerate registered lower-rank nodes per eligible CEO block;
- synthesize target-native circuits before screening;
- perform full-circuit resource recount;
- reject candidates with no strict physical gain;
- generate canonical candidate IDs independent of enumeration order.

Tests and audits:

- all registered 2- and 3-constituent lattice edges;
- duplicate and symmetry-equivalent candidate handling;
- candidate-order metamorphic tests;
- resource-counter version and configuration pinning;
- parameter-only reductions remain negative resource results.

Definition of done:

- every screened candidate has semantic, synthesis, and resource evidence.

### S8 — Predictor, Pareto screening, and candidate freeze

Actions:

- reuse the nonzero-gradient affine KKT/OBS predictor through an explicit
  adapter;
- add multiobjective predicted Pareto selection;
- implement deterministic Top-K and tie-breaking;
- atomically freeze candidates before actual energies are evaluated;
- prohibit FCI/reference-energy access through dependency and poisoning tests.

Tests and audits:

- nonzero-gradient analytic quadratics;
- singular/indefinite and failed KKT cases;
- permutation invariance;
- FCI poisoning and candidate-energy leakage tests;
- exact work-cap boundary tests.

Definition of done:

- the same frozen input produces the same candidate order and digest;
- actual outcomes cannot alter the current round's candidate list.

### S9 — Exact attempt, independent certification, and rollback

Protocol amendment: S9 is governed by
`docs/V6_S9_CERTIFICATION_PROTOCOL.md` and the V6-S8.1 Top-2 freeze. The
current candidates are exploratory total-depth/parameter feasibility attempts,
not circuit-primary candidates. Accepted exploratory attempts remain isolated
from the primary lineage, and cannot become an S10 primary parent.

Actions:

- run target-native optimization in the existing transaction boundary;
- independently recompute energy, target gradient, state, constraints,
  semantics, and resources;
- separate optimizer status from scientific acceptance;
- publish complete accepted and rejected attempt records;
- inject failures at every transaction stage.

Tests and audits:

- crash, NaN, timeout, interrupt, malformed output, and partial-write failures;
- energy/stationarity boundary cases;
- two-path gradient mismatch;
- resource regression;
- prior-checkpoint restoration and artifact immutability.

Definition of done:

- all failures return to the last valid checkpoint without orphaned committed
  artifacts.

### S10 — Sequential/beam search and work-profile comparator

Entry hold: the current V6-S8.1 rank-2 queue does not authorize S10. After S9,
the project first follows the preregistered Go/No-Go in the S9 protocol:
stop the current family if accuracy/stationarity fails, or study native
synthesis/resource-only context if feasibility passes. S10 requires a new
circuit-primary-eligible candidate and a separately frozen amendment.

Actions:

- integrate S6-S9 into sequential rounds;
- implement beam widths 1, 2, and 4 for development calibration;
- implement LOW, MEDIUM, and HIGH work envelopes;
- implement same-checkpoint matched-work comparators;
- keep containment and scientific budgeted modes separate.

Tests and audits:

- cap enforcement for every work component;
- exact accounting reconciliation;
- rollback after later-round failure;
- beam tie determinism;
- refusal to present unmatched legacy work as matched.

Definition of done:

- all result bundles identify their source, budget profile, actual work vector,
  and comparison validity.

### S11 — Low-cost calibration and protocol freeze

Actions:

- use H2/H4 and cheap development checkpoints to calibrate numerical
  tolerances, beam width, Top-K, work profiles, and optimizer policy;
- freeze a primary protocol and clearly labeled secondary ablations;
- create a calibration report with all attempted configurations, including
  failures.

Restrictions:

- no unseen validation outcome is available;
- no molecule-specific production threshold;
- acceptance thresholds are not relaxed to obtain resource gains.

Definition of done:

- a hashed protocol manifest fixes all choices needed for H6 pilot and later
  validation.

### S12 — H6 1.5 A development pilot

Actions:

- execute the frozen primary protocol on the MVP-heavy H6 1.5 A checkpoint;
- run matched-work legacy and required ablations where reconstructible;
- produce energy-resource and work-resource frontiers;
- repeat only the preregistered deterministic replay/audit, not adaptive
  retuning.

Engineering Go criteria:

- native CNOT or depth is reduced;
- energy and stationarity gates pass;
- the result improves on magnitude pruning;
- a new matched-work nondominated point is added;
- replay is deterministic;
- rollback and work ledgers reconcile.

Failure response:

- record the null or negative result;
- diagnose topology, synthesis availability, prediction, optimization, and
  work limits separately;
- do not add QFI or repair inside the frozen pilot.

Definition of done:

- an immutable pilot bundle and independent audit state Go or No-Go.

### S13 — Development evaluation, ablation, and final freeze

Actions:

- apply the pilot protocol to LiH 3.0 A, H6 3.0 A, and BeH2 3.0 A;
- execute the mandatory ablations;
- analyze block topology, rank-transition prevalence, energy-budget use, and
  physical compressibility;
- freeze the final prospective-validation protocol.

Mandatory ablations:

| Ablation | Causal effect |
|---|---|
| CEO* source | immutable source |
| V4.1 | one-shot compression |
| V5 | sequential rebuilding |
| V5.1 | exact fusion |
| magnitude pruning | simple parameter criterion |
| bounded exact rewrite only | lossless rewrite contribution |
| rank adaptation without native synthesis | parameter/rank reduction only |
| native synthesis only | circuit-construction contribution |
| V6 without joint selection | selection contribution |
| V6 without sequential rebuilding | sequential contribution |
| same-structure reoptimization | extra optimizer work |
| full V6 | proposed method |

Definition of done:

- settings are frozen before choosing or running prospective validation;
- all development successes and failures are reported.

### S14 — Prospective unseen validation

Actions:

- select and preregister one new molecule and two geometries under Section 11;
- verify or generate the source checkpoints under the frozen source protocol;
- execute V6 once per case under the frozen primary protocol;
- join FCI/high-accuracy references only for offline reporting;
- retain null results without retuning.

Tests and audits:

- protocol/tag/digest match;
- runtime process has no reference-energy access;
- work and artifact reconciliation;
- independent resource and energy audit;
- rerun policy compliance.

Definition of done:

- both prospective cases have complete, immutable result bundles, including
  negative outcomes.

### S15 — Release and PRA manuscript package

Actions:

- create an immutable release tag;
- publish code, schemas, machine-readable artifacts, CSV/JSON tables, figure
  scripts, environment lock/container, incident logs, and negative results;
- archive a release with a persistent identifier such as Zenodo;
- write the Data Availability Statement and code availability statement;
- generate manuscript tables and figures only from audited release artifacts.

Definition of done:

- a clean clone can reproduce audits and figures;
- no manuscript number is manually copied from an unaudited run;
- claims pass the gate in Section 15.

## 13. Mandatory anomaly audit at every step

Every S-step must answer and record:

### Scientific validity

- Did the code use only information permitted by the protocol?
- Was any threshold changed after observing a target result?
- Are exact, numerically validated, and approximate claims separated?
- Is the comparator matched in source, Hamiltonian, circuit semantics, and
  work?
- Does a parameter reduction correspond to a recounted physical reduction?
- Are negative and null results retained?

### System engineering

- Is the worktree and dependency state expected?
- Are IDs, digests, schemas, and versions consistent?
- Are writes atomic and completed bundles immutable?
- Does every failure path roll back fully?
- Are NaN, nonfinite, partial-write, and counter mismatch cases fail closed?
- Are runs deterministic under the pinned environment and thread settings?
- Does CI test the actual scientific release gate rather than a reduced proxy?

### Reporting

- Can every table cell trace to a machine-readable artifact?
- Are prediction, optimization, verification, and reporting costs separated?
- Are development and prospective validation labels correct?
- Are unmatched comparisons clearly labeled?
- Are any post-hoc changes versioned rather than overwritten?

An unanswered or failed item blocks advancement unless it is recorded as a
formal exception with scientific-owner approval and a new protocol version.

## 14. Version-control and repository policy

Recommended commit sequence:

```text
S0  parent freeze and V6 protocol
S1  evidence schemas and transition registry
S2  ArchitectureState IR
S3  legacy replay adapters and audit
S4  mathematical evidence kernels
S5  native rank-transition feasibility
S6  bounded exact rewrite
S7  rank catalog and native recount
S8  predictor, Pareto selector, candidate freeze
S9  exact certification and rollback
S10 sequential search and matched-work comparator
S11 calibration freeze
S12 H6 pilot result and audit
S13 development ablation and validation freeze
S14 prospective validation results
S15 release and manuscript package
```

Rules:

- one intentional commit per completed logical step;
- no force-push of an audited or result-bearing branch;
- no editing completed artifact bundles;
- protocol changes require a new version and commit;
- performance runs begin only from a clean tagged state;
- result commits contain manifests and small audited summaries, not
  unreviewed temporary files;
- GitHub CI, local tests, and release audit must all pass before a phase tag;
- the repository may be private during development, but PRA release artifacts
  must have a stable public availability path no later than publication
  requirements permit.

## 15. PRA submission gate

This is an internal submission decision, not a guaranteed acceptance rule.
PRA submission proceeds only if:

1. at least one native rank transition absent from V4.1 is established;
2. the transition produces a strict full-circuit CNOT or depth reduction;
3. at least two development conditions gain new matched-work nondominated
   points;
4. at least one of two prospective validation conditions gains a new
   nondominated point;
5. the other validation condition does not disappear from reporting and is
   either nonregressing or mechanistically explained as a null/negative result;
6. ablation isolates the effect of rank adaptation from extra optimization,
   sequential search, and native synthesis alone;
7. all accepted points pass energy, stationarity, identity, semantic,
   transaction, and resource audits;
8. the complete code/data/figure package is independently reproducible;
9. incidents, failures, post-hoc versions, and negative results are disclosed.

Submission is postponed or the research claim is changed if:

- no new native rank transition exists;
- only parameter count falls while CNOT and depth do not;
- improvement appears only on H6 1.5 A;
- matched-work comparison removes the apparent advantage;
- all prospective validation conditions fail;
- improvement is explained only by more optimizer work;
- multiple added mechanisms are inseparable by ablation;
- numerical validation is the only basis for a mathematical-exactness claim.

## 16. Intended paper structure and figures

### 16.1 Paper structure

1. CEO block structure and the parameter-to-circuit compression gap
2. Certified rank lattice and transformation evidence
3. Native synthesis and guarded approximate demotion
4. Transactional matched-work algorithm
5. Development and ablation results
6. Prospective molecular validation
7. Mechanism analysis and limitations
8. Reproducibility and data availability

### 16.2 Primary figures

- diagram of the registered CEO rank lattice and evidence layers;
- energy error versus CNOT Pareto frontier;
- energy error versus CNOT depth Pareto frontier;
- energy error versus total depth Pareto frontier;
- energy error versus parameter count Pareto frontier;
- physical-resource reduction versus computational work;
- block topology/rank-transition prevalence versus compressibility;
- mandatory ablation results;
- prospective validation outcomes.

High-dimensional hypervolume may be reported secondarily only after the
reference point, normalization, objective subset, minimization direction, and
work budget are frozen. Two-dimensional frontiers remain the primary evidence.

## 17. Allowed and prohibited claims

### Allowed when supported

> We introduce a synthesis-certified rank-adaptive compression method for
> CEO-ADAPT ansätze. The method separates exact family embeddings, pointwise
> state-preserving rewrites, and guarded approximate rank demotions, and
> accepts physical compression only after native full-circuit resynthesis and
> independent energy and stationarity certification.

> Under matched computational-work budgets, the method adds new nondominated
> energy-resource points beyond registered one-shot, sequential, and
> exact-fusion CEO compression baselines on multiple molecular conditions.

### Prohibited without new evidence

- “best for every molecule”;
- “global optimum”;
- “mathematically exact” from numerical fidelity alone;
- “Measurement Cost reduction”;
- “hardware advantage”;
- “universal VQE compression”;
- unseen generalization without prospective validation;
- matched-work superiority when the work ledger is incomplete;
- circuit reduction inferred only from parameter count.

## 18. Starting primary references

All claims must be rechecked against the primary source during S0.

1. M. A. Ramôa *et al.*, “Reducing the resources required by ADAPT-VQE using
   coupled exchange operators and improved subroutines,” *npj Quantum
   Information* (2025):
   <https://www.nature.com/articles/s41534-025-01039-4>
2. “Fast gradient-free optimization of excitations in variational quantum
   eigensolvers,” *Communications Physics* (2025):
   <https://www.nature.com/articles/s42005-025-02375-9>
3. Quartz quantum-circuit superoptimization:
   <https://doi.org/10.1145/3519939.3523433>
4. *Physical Review A* scope and acceptance criteria:
   <https://journals.aps.org/pra/about>
5. *Physical Review A* author and Data Availability requirements:
   <https://journals.aps.org/pra/authors>

## 19. Final decision boundary

The highest-risk question is not whether a larger search or a different
optimizer can be implemented. It is:

> Can V6 establish at least one new CEO rank transition that has valid target
> semantics, a verified native circuit, and a strict full-ansatz physical
> resource gain beyond the transitions already available in V4.1?

S5 answers this question before expensive molecular execution. If S5 is
No-Go, the rank-adaptive PRA claim stops. If S5 is Go, S12-S14 determine
whether the new mechanism creates reproducible matched-work Pareto
improvements rather than merely spending more classical computation.

V6-Core remains valuable infrastructure in either outcome, but it is not
presented as a performance-improving algorithm unless the prospective evidence
supports that claim.
