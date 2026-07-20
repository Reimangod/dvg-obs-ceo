# S10 LiH paired execution

S10 uses one canonical LiH 3 Å CEO-ADAPT-VQE* checkpoint at the first strict
chemical-accuracy crossing. The checkpoint must reproduce iteration 5, energy
`-7.797909682469515`, 15 parameters, 107 CNOTs, and CNOT depth 30 under the
pinned paper-era implementation.

Before molecular execution, code and protocol are committed and tagged
`dvg-obs-s10-lih-primary-protocol-v1.1`. The runner refuses a dirty worktree or a
HEAD different from that tag. S9 selector digest
`09823d0d82b3029ff7f25eeb2d5e22a6208e4029cdcf6ba28365339cf0a62216`
is also checked at runtime.

Protocol v1 failed during preflight before `algorithm.initialize()` because it
incorrectly demanded equality between the pinned source constant `0.0015936` Ha
and the exact 1 kcal/mol conversion `0.0015936014376405157` Ha in the baseline
manifest. Version 1.1 uses the official pinned-source value, records both values,
and preserves the zero-iteration failure artifact.

## Paired comparison

The complete runtime snapshot is serialized and deserialized twice. Equality of
all three snapshot digests proves that the no-pruning and DVG-OBS-CEO branches
start from the same ansatz, coefficients, energy, gradient, inverse Hessian,
statevector, work counters, metadata, and RNG states.

Candidate screening uses only the recycled-Hessian general constrained OBS
prediction and deterministic structural full-circuit counts. It does not optimize
every candidate. The frozen selector chooses zero or one candidate. If none is
eligible, no-selection is the registered result.

For a selected candidate, projection-on is optimized first. Projection-off is
run once only when the primary optimizer reports failure. Both paths' work is
retained. Acceptance uses the immutable checkpoint energy budget, independent
energy/state recomputation, KKT residual, transformation constraint, and physical
versus structural resource recount. Failure triggers complete transaction
rollback.

## Academic boundary

FCI error is used to locate the common first-accuracy source checkpoint. FCI
energy is not present in `CandidateScore`, `AcceptanceEvidence`, or the
transaction decision, so it cannot favor a pruning candidate or cause one to be
accepted. It is added to the final offline-evaluation section.
LiH is not called a blind holdout because its baseline was already observed.
Energy/gradient/statevector counters are reported separately and are not labeled
as the paper's measurement cost.

The primary run permits one optimized candidate and one accepted compression
round. Terminal, online, or multi-round results require distinct run IDs and are
not pooled with this causal comparison.
