# V6-NS7 frozen energy and stationarity certification

Status: frozen before any NS7 candidate energy evaluation

## Authority

NS7 consumes only the resource-only queue in
`artifacts/v6/ns6/primary-candidate-freeze-v1.json`. The queue contains two
families and one canonical block per family/context, for six attempts total:

- H4 1.5 A late checkpoint: two;
- H6 1.5 A S6 checkpoint: two;
- H6 3.0 A checkpoint: two.

The frozen BeH2 3.0 A checkpoint has no rank-three MVP block and therefore
cannot validate this transition.

## Fixed optimization policy

- global affine target dimension: source parameters minus one;
- initialization: Euclidean projection onto the registered rank-two plane;
- optimizer: pinned upstream BFGS;
- initial inverse Hessian: identity;
- maximum iterations: 200;
- gradient tolerance and acceptance threshold: `1e-8`;
- fallback: none;
- energy budget relative to each source checkpoint: `1e-4 Ha`;
- identical policy for every molecule and family.

No S9 optimizer outcome is an initialization or ranking input.

## Certification

Each attempt independently checks:

- optimizer and independent semantic energies;
- native-circuit Hamiltonian expectation;
- semantic/native state fidelity;
- projected analytic target gradient;
- deterministic finite-difference gradient spot checks;
- exact affine constraint residual;
- NS5 versus NS7 full-circuit resource equality;
- circuit-primary hard resource gate.

FCI and chemical accuracy are not acceptance inputs.

## Mutation and failure boundary

Attempts are functional and isolated: the frozen source object is never
mutated. Before/after source digests must be identical. The final result is
written atomically only after all six attempts complete. Candidate outcomes
cannot modify the queue, policy, or later attempts.

An accepted attempt remains a development result. Because no eligible BeH2
validation transition exists, NS7 cannot establish molecule-general or PRA
performance claims in this run.
