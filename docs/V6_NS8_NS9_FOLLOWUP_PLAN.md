# V6-NS8/NS9 bounded follow-up plan

Status: frozen before NS8 diagnostic recomputation and NS9 candidate energy

## Claim boundary

NS7 remains immutable. NS8 is an outcome-aware mechanism and historical
frontier audit; it cannot change an NS7 decision. NS9 is a new bounded H4
development experiment. None of these stages establishes cross-molecule or
PRA performance.

## NS8-A — H4 mechanism audit

For both accepted NS7 H4 families, recompute:

- source/candidate and candidate/candidate state fidelity;
- particle number, spin-z, and spin-squared expectation and variance;
- leading determinant probabilities;
- the full target analytic gradient;
- centered finite-difference gradients at steps `5e-7`, `1e-6`, and `2e-6`;
- a centered analytic-gradient Hessian at step `1e-4`;
- symmetry, conditioning, and maximum-gradient-component diagnostics.

The original optimizer trajectory was not recorded by NS7 and is reported as
unavailable. It is not recreated and presented as historical evidence.

## NS8-B — same-source historical frontier audit

The H4 source identity, energy, state digest, and resource counts must match
before comparison. The audit includes only reconstructible same-source points:

- CEO* source;
- both NS7 native-rank2 points;
- the V5 round-1 intermediate;
- the V5 two-round endpoint.

V4.1, V5.1, and a standalone magnitude-pruning endpoint are reported as
unavailable for this exact late checkpoint unless an audited artifact exists.
They are not imputed. Pareto comparison uses source-relative energy loss,
CNOT, CNOT depth, total depth, and parameters. Energy differences within
`1e-12 Ha` are equal for dominance. Work is reported as a vector and is not
collapsed to Measurement Cost.

## NS9 — bounded full-catalog H4 sequential pilot

NS9 starts only from the two accepted NS7 H4 roots and never edits them. The
source has two eligible rank-three MVP blocks. The already-demoted block is
fixed by the root; the remaining block may use either registered normal:

- `(1,1,-1)`;
- `(1,1,1)`.

This creates exactly four frozen attempts, ordered by root family ID and then
child family ID.

Fixed protocol:

- context: `h4-1.5-late`;
- architecture-diversity roots: two;
- total rank-demotion rounds including NS7: two;
- new exact attempts: four;
- initialization: Euclidean projection of the accepted root coordinates;
- optimizer: pinned upstream BFGS;
- initial inverse Hessian: identity;
- maximum iterations: 200 per attempt;
- gradient and stationarity threshold: `1e-8`;
- cumulative source-relative energy budget: `1e-4 Ha`;
- fallback: none;
- finite-difference certificate: five deterministic coordinates;
- native synthesis: the frozen NS3 shortest-parity implementation;
- full-circuit resource policy: `circuit-primary-v1`;
- winner rule: retain every accepted nondominated point;
- failed attempt: functional discard with unchanged roots;
- FCI, chemical accuracy, Measurement Cost, and molecule-specific tuning:
  prohibited.

The hard work cap is four exact attempts, 800 optimizer iterations, 820
optimizer energy evaluations, 820 gradient-vector evaluations, 40
finite-difference energy evaluations, and four full resource recounts.

## Gates

NS9 mechanism Go requires at least one additional certified rank transition.
Scientific-frontier Go separately requires at least one NS9 point not
dominated by the reconstructible same-source legacy frontier. Failure of the
frontier gate stops the H6 optimizer ablation. A resource or semantic
regression also stops the pilot.
