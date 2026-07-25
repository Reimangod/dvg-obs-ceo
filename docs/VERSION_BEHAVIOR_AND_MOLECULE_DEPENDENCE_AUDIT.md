# V4.1 / V5 / V5.1 behavior and molecule-dependence audit

## 1. Scope

This report analyzes the existing V4.1, V5, and V5.1 implementations and
development results. It does not propose a new compression method.

The audited historical parent is commit
`3818fd1005de262b5e6c38517f85c331d04e8dbb`. Corrections on branch
`stable-v5-correctness-audit` preserve all historical result artifacts and add
non-destructive errata.

The central conclusion is:

> The different molecular outcomes are mostly explained by the registered
> resource-first objectives, CEO block topology, local inverse-Hessian quality,
> optimizer/stationarity behavior, finite search budgets, and the narrow
> algebraic applicability of V5.1. They are not evidence of one unexplained
> random failure.

All three versions are **post-processing algorithms for a fixed CEO*
checkpoint**. They do not rerun ADAPT operator growth or change the original
CEO* gradient-based operator selection.

## 2. Common execution substrate

### 2.1 Recovering physical CEO blocks

All versions reconstruct physical blocks from the frozen ansatz. Consecutive
parent QEs with the same support and ADAPT iteration are grouped as one MVP;
registered non-parent sum/difference CEOs are OVPs.

Current code:

```python
def recover_dvg_blocks(pool, ansatz_indices, coefficients,
                       cumulative_parameter_counts):
    ...
    if all(in_parent):
        family = "MVP" if len(indices) > 1 else "single-QE"
    ...
    elif ceo_type in {"sum", "diff"}:
        family = "OVP"
```

Source: `src/dvg_obs_ceo/block_ir.py:151-263`.

This distinction is critical. Removing one coefficient inside an MVP may
reduce parameters without removing the physical circuit block. Removing an
entire single-QE or OVP block is much more likely to reduce CNOT and total
depth directly.

### 2.2 Registered transformations

The candidate catalog contains:

- whole OVP or single-QE block deletion;
- whole MVP deletion;
- deletion of MVP constituents;
- MVP to one constituent QE;
- MVP to a registered sum/difference OVP.

The implementation starts at
`src/dvg_obs_ceo/block_ir.py:436`. MVP-to-OVP conversion uses registered parent
metadata and an exact signed generator relation; it does not infer an operator
identity from a small coefficient.

### 2.3 What “state fidelity” means in V4.1/V5

V4.1/V5 pruning is allowed to change the quantum state. The acceptance record
passes repeat-recomputation fidelity:

```python
independent_state_fidelity = \
    selected["independent_state_recomputation_fidelity"]
kkt_residual = selected["gradient_infinity"]
```

Source: `src/dvg_obs_ceo/v5_s8_h4_width1.py:506-514`.

`source_candidate_state_fidelity` is recorded separately at
`src/dvg_obs_ceo/s8_probe.py:346-347`, but it is not a requirement that the
compressed state equal the CEO* source. Therefore molecule-dependent energy
changes are expected. The principal accuracy protection is the source-relative
energy budget plus stationarity and independent recomputation.

V5.1 is different: it explicitly verifies source-to-target state fidelity and
energy equality for an exact algebraic rewrite.

## 3. V4.1

### 3.1 Execution flow

V4.1 performs one global compression attempt family from the original CEO*
checkpoint:

1. reconstruct source state, energy, blocks, and full circuit resources;
2. enumerate all registered block transformations;
3. form compatible multi-block batches;
4. predict energy change with the recycled inverse Hessian;
5. perform a full paper-era circuit recount;
6. form CNOT, CNOT-depth, total-depth, and parameter endpoints;
7. freeze at most four unique sentinels;
8. independently optimize every sentinel from the same CEO* source;
9. accept or fully roll back.

The CNOT-primary ordering is explicitly resource-first:

```python
"cnot_primary":
    ("cnot_count", "cnot_depth", "total_depth", "parameter_count")
```

Source: `src/dvg_obs_ceo/v4_1_multisystem.py:38-43`.

The exact-stage winner is the first accepted candidate in each frozen endpoint
list, not the accepted candidate with the lowest measured energy:

```python
def winner(endpoint):
    return next(
        semantic_id
        for semantic_id in s5["selection"][endpoint]
        if attempt_by_semantic[semantic_id]["transaction_status"] == "accepted"
    )
```

Source: `src/dvg_obs_ceo/v4_1_exact_multisystem.py:305-315`.

### 3.2 Strengths

- Operator identities come from pool provenance and exact generator checks.
- Full-circuit resources are recounted; parameter removal is not assumed to be
  circuit removal.
- Every exact sentinel starts from the same source, making one-shot comparisons
  easier to interpret.
- Candidate and target energies, gradients, and states are independently
  reconstructed.
- Rejected attempts restore runtime state exactly.
- V4.1 bundles use locks, staging, file inventories, fsync, and atomic
  directory promotion.

### 3.3 Limitations

- It is a one-shot approximation around one fixed inverse Hessian.
- Predictor quality is not required to have held-out secant evidence:
  `require_held_out_evidence=False` at
  `src/dvg_obs_ceo/v4_1_exact_multisystem.py:152-165`.
- H6 and BeH2 searches stop at 10,000 completed states, so they are
  budget-truncated best-found searches.
- At most four exact sentinels are tested.
- The primary release endpoint is not accuracy-first.
- Historical multisystem acceptance used an FCI-derived chemical margin. Those
  results are now labelled development/oracle-assisted; forward code uses only
  the fixed source-relative budget.

### 3.4 Molecule-specific behavior

| Case | Source parameters / blocks | Dominant block structure | V4.1 primary effect |
|---|---:|---|---|
| LiH 3.0 Å | 15 / 15 | all single blocks | seven whole blocks removed; large circuit reduction |
| H6 1.5 Å | 137 / 79 | 56 MVP blocks | mostly internal MVP rewrites; only one net block removed |
| H6 3.0 Å | 149 / 95 | 42 MVP, 53 single | five rewrites but only one net block removed |
| BeH2 3.0 Å | 38 / 32 | mostly single/OVP; only 6 MVP | five whole blocks removed |

This explains the large contrast:

- LiH: CNOT `107 → 58`, parameters `15 → 8`, total depth `171 → 92`;
- H6 1.5 Å: CNOT `879 → 858`, parameters `137 → 131`;
- H6 3.0 Å: CNOT `785 → 768`, parameters `149 → 144`;
- BeH2: CNOT `284 → 239`, parameters `38 → 33`.

H6 parameter changes often remain inside an MVP and therefore do not remove a
whole physical block. LiH and BeH2 contain more profitable whole-block
deletions.

### 3.5 Why V4.1 primary accuracy differs

V4.1 accepted alternatives can have lower energy loss than the primary
resource endpoint:

| Case | Primary energy increase | Lower-energy accepted evidence |
|---|---:|---:|
| H6 1.5 Å | `8.8214e-5` Ha | `5.7638e-5` Ha |
| H6 3.0 Å | `7.1345e-5` Ha | approximately `4.02e-5` Ha |
| BeH2 3.0 Å | `9.6615e-5` Ha | `4.9485e-5` Ha |

This is not optimizer corruption. The frozen endpoint policy deliberately
prioritizes resources before measured energy.

LiH has a lower-energy 60-CNOT/9-parameter trial, but it was rolled back and
must not be called an eligible result.

## 4. V5

### 4.1 Execution flow

V5 reuses the V4.1 transformation family, but rebuilds the catalog after an
accepted compression and follows multiple trajectories:

1. build the global candidate catalog at the current path;
2. use recycled-inverse-Hessian OBS predictions;
3. apply resource and predictor-quality filters;
4. perform exact target optimization;
5. accept or reject;
6. rebuild blocks, candidates, curvature coordinates, and resources on accepted
   child paths;
7. retain a bounded Pareto beam;
8. stop on round, exact-attempt, or terminal-catalog limits.

The kernel is implemented at
`src/dvg_obs_ceo/v5_multitrajectory.py:294`.

The final raw winner is resource-first:

```python
return (
    state.resources.cnot_count,
    state.resources.parameter_count,
    state.resources.total_depth,
    state.resources.cnot_depth,
    state.cumulative_energy_increase_hartree,
    state.path_id,
)
```

Historical parent source:
`src/dvg_obs_ceo/v5_multitrajectory.py:225-233`.

Thus energy is only the fifth key. A lower-CNOT point is selected even when
another accepted point has a lower variational energy.

### 4.2 What “risk-aware” currently does

The production uncertainty margin was fixed to zero:

```python
uncertainty_margin_hartree=0.0
```

Source: `src/dvg_obs_ceo/v5_s8_h4_width1.py:261`.

The main quality classification is based on target inverse-Hessian condition
number:

- good: condition number at most `1e8`;
- boundary: above `1e8` and at most `1e12`;
- poor: above `1e12`.

Boundary records request refinement in metadata, but the S9 screening score
does not receive a nonzero uncertainty penalty. Safety is primarily provided
by the later exact optimization and acceptance gate.

The `kkt` label in the acceptance record is the target gradient infinity norm,
with threshold `1e-8`; it is not the residual of the separate matrix-free
affine KKT solver. This distinction matters when describing the implementation
academically.

### 4.3 Strengths over V4.1

- Sequential rebuilding can expose candidates that do not exist at the
  original source.
- Multiple accepted paths can preserve different resource/energy trade-offs.
- Every branch uses an isolated runtime clone and verifies that the parent was
  unchanged.
- All accepted branches pass exact energy, gradient, state-recomputation, and
  resource checks.
- Work from rejected candidates and terminal catalogs is retained.

### 4.4 Limitations

- V5 does not improve ADAPT operator growth; it only compresses the fixed CEO*
  ansatz.
- It still uses the same local recycled curvature approximation for screening.
- The raw release objective is resource-first, not accuracy-first.
- H6 and BeH2 joint searches are budget-truncated.
- V5 uses more exact and search work than V4.1; method and compute budget are
  confounded.
- Conditional polishing has finite HVP/gradient budgets and does not always
  rescue near-threshold stationarity failures.
- Historical S9 used an FCI-derived acceptance margin.
- Before the correction branch, proposal endpoint labels were reconstructed
  from rank modulo a different endpoint order. The beam recomputed physical
  resources, limiting numerical impact, but provenance was wrong.

### 4.5 Molecule-specific behavior

#### LiH 3.0 Å

LiH has no MVP blocks in the audited source topology. V4.1 already reaches
58 CNOT and 8 parameters. Wider and longer V5 searches repeatedly reach the
same structural floor, and the terminal catalog contains no eligible
successor.

V5 therefore adds search work but does not improve the release structure.

#### H6 1.5 Å

The first joint compression succeeds:

- CNOT: 858;
- parameters: 132;
- energy increase: `8.4637e-5` Ha;
- gradient infinity norm: approximately `5.66e-9`.

Three later proposals are rejected because the final gradient norm is around
`1.06e-8–1.43e-8`, slightly above the `1e-8` threshold; one also exceeds the
cumulative energy budget. Conditional polishing reaches its finite work limit
in affected paths.

The stopping cause is therefore mainly target optimization/stationarity near a
hard threshold, not absence of a large initial catalog.

#### H6 3.0 Å

All six exact attempts converge through the primary BFGS path with gradient
norms below `1e-8`. Sequential catalog rebuilding remains productive.

Three different facts must not be mixed:

- V4.1 primary: 768 CNOT, 144 parameters, `ΔE=7.1345e-5`;
- V5 strict comparison point: 758 CNOT, 142 parameters,
  `ΔE=6.9151e-5`;
- V5 raw resource winner: 741 CNOT, 138 parameters,
  `ΔE=7.8493e-5`.

An accepted V5 point has energy below the stored CEO* checkpoint, showing that
additional reoptimization escaped the earlier local solution. That energy gain
cannot be attributed solely to structural compression.

#### BeH2 3.0 Å

The first seven-atomic joint compression reaches:

- 221 CNOT;
- 31 parameters;
- `ΔE=9.8518e-5` Ha.

It consumes about 98.5% of the `1e-4` Ha source-relative budget. Later
proposals exceed the cumulative budget; one also misses stationarity. This is
why BeH2 obtains a large resource reduction but a worse accuracy point than
the conservative V4.1 endpoint.

### 4.6 Unequal computation

| Case | V4.1 search states / exact attempts | V5 expanded states / exact attempts |
|---|---:|---:|
| LiH 3.0 Å | 168 / 2 | 877 / 6 |
| H6 1.5 Å | 10,000 / 4 | 26,010 / 4 |
| H6 3.0 Å | 10,000 / 4 | 45,273 / 6 |
| BeH2 3.0 Å | 10,000 / 4 | 16,295 / 4 |

Therefore V5’s H6 3.0 Å improvement is a best-found result under a larger
search/optimization budget, not a matched-cost superiority result.

## 5. V5.1

### 5.1 Exact fusion behavior

V5.1 does not prune by predicted energy. It searches for an exact algebraic
redundancy between a registered OVP and a later MVP. Candidate enumeration is
implemented at `src/dvg_obs_ceo/v5_1_exact_fusion.py:79`; joint application is
at `src/dvg_obs_ceo/v5_1_exact_fusion.py:197`.

The conditions include:

- equal qubit support;
- exact registered signed generator relation;
- relevant parent generators commute;
- intervening blocks are disjoint from the support;
- simultaneous candidates do not conflict.

The accepted OVP coordinate is added to the registered MVP parent coordinates,
then the OVP parameter and index are physically removed:

```python
for position, weight in zip(
        candidate.mvp_positions, candidate.exact_signed_relation):
    coefficients[position] += float(weight) * ovp_coordinate
del coefficients[candidate.ovp_position]
del indices[candidate.ovp_position]
```

Source: `src/dvg_obs_ceo/v5_1_exact_fusion.py`.

The transformation kernel itself now checks the registered generator identity,
parent commutators, and the complete OVP commuting corridor before changing
coordinates. The molecular runners additionally recompute source-target state
fidelity, energy drift, and full physical/structural circuit resources. This
defense in depth prevents a future direct caller from bypassing the operator
audit.

### 5.2 Strengths

- No new optimizer start is needed.
- Accepted rewrites preserve the state and energy to numerical tolerance.
- Resource improvement is not confounded by extra variational optimization.
- Generator provenance and commutation conditions are auditable.

### 5.3 Narrow applicability

| Case | Source block topology | Structural audit | Candidates |
|---|---|---|---:|
| LiH 3.0 Å | 11 OVP, 0 MVP, 4 single | no MVP absorption target | 0 |
| H6 1.5 Å | 15 OVP, 56 MVP, 8 single | 14 support matches; 12 blocked by intervening overlap | 2 |
| H6 3.0 Å | 19 OVP, 42 MVP, 34 single | 21 support matches; all blocked by intervening overlap | 0 |
| BeH2 3.0 Å | 22 OVP, 6 MVP, 4 single | all 132 OVP–MVP pairs have different support | 0 |

Only H6 1.5 Å contains the required OVP/MVP order, support, and commuting
pattern. Re-enumerating every accepted V4.1 ansatz does not change this
conclusion: H6 1.5 Å retains two candidates, while H6 3.0 Å and BeH2 retain
zero. Candidate prevalence is controlled by the exact operator-selection
history and block ordering, not molecule size or an energy threshold.

The published H6 1.5 Å applications reduce 18 CNOT, 2 parameters, 26 total
depth layers, and 2 blocks without changing energy. V5.1 does not improve
accuracy; it preserves the accuracy of the selected parent.

## 6. Why performance changes across molecules

The observed variation is explained by the following interacting causes.

### Cause 1 — Physical block topology

Whole-block deletions generate large CNOT/depth reductions. Internal MVP
rewrites may reduce parameters but leave most of the block circuit in place.
This is the strongest explanation for LiH/BeH2 versus H6 resource reductions.

### Cause 2 — The release objective is resource-first

V4.1 and V5 primary choices do not minimize measured variational energy. They
prefer CNOT and other resources first. Different systems expose different
Pareto trade-offs, so the selected energy loss varies.

### Cause 3 — Different source accuracy margins

The CEO* checkpoints do not begin equally far inside chemical accuracy.
H6 3.0 Å has much less remaining margin than LiH. The same `1e-4` Ha
source-relative loss therefore has a different effect on final FCI error.

### Cause 4 — Local inverse-Hessian approximation quality

The recycled inverse Hessian is a local model around the CEO* optimum.
Prediction-to-actual loss agreement is excellent on LiH, less uniform on H6,
and can underpredict loss on BeH2. Exact acceptance prevents unsafe commits,
but prediction error changes which limited attempts are spent productively.

### Cause 5 — Optimizer and stationarity behavior

H6 3.0 Å converges reliably below the gradient threshold. H6 1.5 Å repeatedly
lands just above it, while BeH2 spends most of the energy budget in its first
aggressive step. The same candidate machinery therefore produces different
accepted path lengths.

### Cause 6 — Finite and unequal search budgets

H6 and BeH2 searches are truncated and depend on canonical traversal order.
V5 also uses more search and exact work than V4.1. Reported points are
best-found, not global optima under equal cost.

### Cause 7 — V5.1 requires a rare exact pattern

V5.1 can only act where the exact OVP/MVP algebra and circuit ordering permit
it. H6 1.5 Å happens to contain two patterns; the other audited systems contain
none.

### Cause 8 — Additional reoptimization can improve the local solution

Some V5 energy improvements arise because additional optimizer starts find a
better variational point. This is not the same scientific effect as removing a
redundant circuit block.

## 7. Corrected engineering and scientific issues

The correction branch changes infrastructure and correctness only; it does not
introduce a new compression method.

### 7.1 FCI firewall

Forward runtime code now rejects chemical-accuracy enforcement:

```python
if enforce_chemical_accuracy:
    raise V5S8LiHMultiTrajectoryError(
        "runtime chemical-accuracy enforcement is forbidden; "
        "use the offline scientific audit"
    )
return 1e-4, None
```

Source: `src/dvg_obs_ceo/v5_s8_lih_multitrajectory.py:93-111`.

Poisoning tests verify that arbitrary exact-energy values cannot change the
runtime budget. Historical artifacts are not rewritten and are labelled
development/oracle-assisted in
`artifacts/v5/release/correctness-errata-v1.json`.

### 7.2 Canonical three-layer scientific identity

The simplified native-endian State ID has been removed from the production
path. Runtime identity now delegates to:

- `StatePreparationSpec`;
- `ProblemSpec`;
- `MeasurementContextSpec`.

Source: `src/dvg_obs_ceo/molecular_identity.py` and
`src/dvg_obs_ceo/v5_s8_h4_width1.py:86-101`.

The state identity includes reference state, generator definition digest,
actual recovered block structure, indices, big-endian canonical coefficient
bytes, mapping, and qubit ordering.

### 7.3 Atomic artifact publication

New artifacts are written to a unique staging file/directory, fsynced, and
atomically promoted:

- `src/dvg_obs_ceo/artifact_io.py:48`;
- `src/dvg_obs_ceo/artifact_io.py:68`.

Fault-injection tests verify that a failed promotion leaves no partial
canonical file or directory.

### 7.4 Endpoint provenance

The Pareto selector now records the endpoint associated with every unique
attempt. Multitrajectory proposals consume that explicit endpoint rather than
reconstructing it from rank modulo a mismatched list:

- `src/dvg_obs_ceo/v5_pareto.py`;
- `src/dvg_obs_ceo/v5_s8_h4_width1.py:303`;
- `src/dvg_obs_ceo/v5_s8_lih_multitrajectory.py:240`.

### 7.5 Strict comparator

Strict V5 success is now evaluated only against the registered V4.1
`cnot_primary` comparator, not a cross-product with every accepted V4.1 point.

Source: `src/dvg_obs_ceo/v5_s9_audit.py:138-154`.

### 7.6 Release and claim disambiguation

The original strict-development release and the later post-outcome
resource-priority amendment remain separate policies. Tests prevent them from
being treated as the same canonical choice. H6/BeH2 forward claim text is now
case-specific.

### 7.7 CI and evergreen audit

GitHub CI now fetches full history/tags, installs the baseline scientific
dependencies, and freezes BLAS/OpenMP threads. The release audit has a real CLI
entry point and returns a nonzero status on failure.

### 7.8 V5.1 kernel and artifact contracts

`apply_exact_fusion()` and `apply_exact_fusions()` now fail closed unless the
actual Pauli operators satisfy the registered identity and commutation
requirements. A deliberately false metadata/operator pairing is covered by a
regression test.

All three V5.1 result artifact families are checked against
`schemas/v5-exact-fusion-result-v1.schema.json`. V5.1 publication also uses the
same atomic file writer described above.

## 8. Objective assessment of the “run all versions and choose minimum energy” idea

The concern about inefficiency is correct. V4.1, V5, and V5.1 have overlapping
candidate generation and expensive exact optimization. Running every path and
then choosing the lowest energy would:

- add all family search costs;
- increase optimizer starts and energy/gradient evaluations;
- confound compression benefit with additional optimization;
- make comparison with either original version unfair unless total work is
  reported;
- still provide only a best-observed result, not a global guarantee.

This report therefore does not recommend or implement that mechanism. The
current evidence is used only to explain each existing version’s behavior and
failure modes.

## 9. Final assessment

| Version | Main advantage | Main limitation | Systems where it is strongest in current evidence |
|---|---|---|---|
| V4.1 | Auditable one-shot global block-aware compression with strong rollback | fixed-source approximation, resource-first endpoints, truncated search | LiH and BeH2 whole-block deletion |
| V5 | sequential rebuilding can continue compression and maintain multiple paths | greater work, resource-first winner, optimizer/stationarity and budget sensitivity | H6 3.0 Å |
| V5.1 | exact lossless circuit reduction with no optimizer confound | requires rare OVP/MVP algebraic and ordering pattern | H6 1.5 Å only |

No single version has demonstrated universal superiority. The molecule
dependence is technically understandable from the implementation and stored
evidence. Future claims must keep final circuit quality, variational energy,
and total search/optimization work as separate axes.
