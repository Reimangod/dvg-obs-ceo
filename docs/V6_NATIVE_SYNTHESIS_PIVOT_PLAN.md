# V6-NS: primary-resource native-synthesis pivot

Status: new development protocol after immutable V6-S9 closure

## Decision

The current `SPARSE_UCRY_RANK2` optimization protocol is stopped. V6-NS is
not S10 and does not reopen the V6-S8.1 queue. Its question is:

> Can a mathematically registered rank-adaptive CEO target be synthesized as
> a familywise-correct native circuit that does not regress CNOT count or CNOT
> depth and strictly improves a preregistered physical endpoint?

Predictor refinement, optimizer replacement, QFI, repair growth, and
sequential search are out of scope until a primary-resource-eligible circuit
exists.

## Evidence boundary

The following V6-S9 evidence is immutable:

- result commit `21654bf`;
- tag `v6-s9-native-rank2-not-certified-v1`;
- V6-S8.1 Top-2 order;
- both candidate outcomes and exact rollbacks;
- status of the current optimization protocol: `STOPPED`;
- S10 authorization: `false`.

V6-NS may reuse abstract generator relations and familywise semantic proofs.
It may not reinterpret an S9 rejection as an acceptance, extend S9
optimization, add the third S8 candidate, or mutate the S6 primary parent.

## External technical basis

The CEO paper gives explicit reference constructions:

- an MVP-CEO with up to three constituent QEs can use 13 CNOTs;
- the reported OVP-CEO construction uses 9 CNOTs and CNOT depth 7.

These are reference bounds, not proof that a new rank-2 family can attain
them. Parameterized-circuit equivalence checking based on ZX calculus is
available in QCEC, and recent uniformly controlled-structure work studies
sparsity-aware decompositions. These are candidate verification and synthesis
tools only. Their applicability to the CEO target must be demonstrated, not
assumed.

Primary references:

- Ramôa et al., npj Quantum Information 11, 86 (2025),
  <https://doi.org/10.1038/s41534-025-01039-4>
- Peham, Burgholzer, and Wille, arXiv:2210.12166,
  <https://arxiv.org/abs/2210.12166>
- van de Wetering et al., arXiv:2401.12877,
  <https://arxiv.org/abs/2401.12877>
- Xu et al., arXiv:2512.08675,
  <https://arxiv.org/abs/2512.08675>

## Hard resource gate

A candidate is primary-eligible only if one of the following holds after
target-native full-circuit recount with the frozen paper-era counter:

1. `delta_CNOT < 0` and `delta_CNOT_depth <= 0`;
2. `delta_CNOT <= 0` and `delta_CNOT_depth < 0`;
3. `delta_CNOT <= 0`, `delta_CNOT_depth <= 0`,
   `delta_total_depth < 0`, and `delta_parameters < 0`.

Parameter reduction alone is a negative resource result. Local block counts
alone are insufficient; the gate is evaluated on the full ansatz. Any S7/S9
counter discrepancy is an incident, not a gain.

## NS0 — Immutable closure and source contract

Actions:

- verify S9 commit, tag, result digest, audit digest, and rollback inventory;
- declare the old optimization protocol and queue read-only;
- create separate IDs for abstract target unitary, native realization,
  synthesis rule, counter configuration, and context.

Definition of done:

- a machine-readable closure manifest resolves every immutable S9 input and
  forbids primary-lineage mutation.

## S9-D — Read-only stationarity mechanism audit

Actions:

- use only saved S9 coordinates, gradients, optimizer messages, and BFGS
  inverse-Hessian surrogates;
- report gradient component distribution and whether large components are
  located inside the demoted block;
- report surrogate symmetry, definiteness, conditioning, and gradient
  alignment with low-curvature surrogate directions;
- explicitly mark unavailable step-history and line-search internals.

Restrictions:

- no energy, gradient, HVP, statevector, or optimizer rerun;
- no new candidate;
- no acceptance reassessment;
- no claim that BFGS curvature is the exact physical Hessian.

Definition of done:

- the diagnostic explains only what the saved evidence supports and lists
  every unavailable mechanism.

## NS1 — Abstract target-family registry

Actions:

- define each target independently of any circuit implementation as an exact
  generator map;
- start with a small discrete registry:
  ordered subsets and symmetry-motivated `G_i + G_j`, `G_i - G_j` plus a
  remaining constituent;
- restrict coefficients to a canonical discrete set such as `0`, `+1`, and
  `-1`;
- prove rank, independence, normalization, commutation requirements, and
  source/target parameter orientation.

Restrictions:

- no Hamiltonian, molecular energy, S9 outcome, or continuous
  outcome-informed coefficient fitting may define the registry.

Definition of done:

- every family has a canonical semantic ID and exact generator-relation
  evidence, or is rejected.

## NS2 — Reference circuits and lower-bound targets

Actions:

- reconstruct the paper-era MVP3 and OVP reference circuits under the exact
  frozen gate alphabet, qubit ordering, barrier policy, and resource counter;
- define local and full-context hard bounds before search;
- identify common basis changes, parity networks, control sectors, and
  cancellation opportunities.

Definition of done:

- reference circuits reproduce their expected counts, and every later search
  candidate has a fixed comparison target.

## NS3 — Bounded native synthesis

Independent search lanes:

1. shared parity/basis-change network;
2. sparse-UCRY specialization;
3. direct active-subspace decomposition;
4. bounded parameterized superoptimization.

Every lane fixes before execution:

- gate alphabet;
- maximum CNOT and depth;
- parameter map;
- maximum topology/depth/search states;
- deterministic traversal and tie-break;
- timeout and work counters.

The search operates on one CEO block, not a molecular ansatz. Generic Qiskit
compilation is not a scientific synthesis rule.

Definition of done:

- every enumerated topology has a deterministic ID, complete bounded-search
  trace, and explicit accepted/rejected reason.

## NS4 — Familywise verification

Verification ladder:

1. exact algebraic generator derivation;
2. symbolic parameterized equivalence where supported;
3. exact parameter-map and orientation check;
4. arbitrary-context substitution proof;
5. independent numerical unitary regression;
6. random-parameter and random-state regression.

Numerical fidelity alone cannot establish exactness. Tool timeout or unsupported
gates produce `NOT_CERTIFIED`, not acceptance.

Definition of done:

- a candidate has familywise and contextual evidence strong enough for native
  substitution, or is rejected.

## NS5 — Resource-only context census

Only candidates certified in NS4 are inserted, without energy or optimization,
into preregistered development contexts:

- late H4;
- H6 1.5 A;
- H6 3.0 A;
- BeH2 3.0 A;
- other structurally eligible rank-3 MVP blocks already available in frozen
  artifacts.

For each context:

```text
native substitution
-> separately registered bounded exact-rewrite closure
-> full-circuit resource recount
```

Direct substitution and post-closure resources are reported separately.
Molecule-specific compiler choices are prohibited.

Definition of done:

- the census publishes all eligible contexts, including no-gain and regression
  cases, with no quantum-energy evaluations.

## NS6 — Primary candidate freeze

Actions:

- apply the hard resource gate;
- freeze all primary-eligible semantic candidates and their context evidence;
- use deterministic resource-only ranking and a fixed work cap;
- atomically freeze a later energy-evaluation queue.

If no candidate passes, rank-adaptive V6 receives a primary-synthesis No-Go.
No energy experiment is run.

## NS7 — New energy/stationarity protocol

This stage exists only if NS6 yields a primary-eligible candidate. It requires
a new pre-outcome protocol with:

- optimizer and fallback fixed before outcomes;
- unchanged energy and stationarity thresholds unless independently calibrated
  before the queue is visible;
- independent energy, state, gradient, semantics, and resource certification;
- exact rollback and matched-work accounting;
- no reuse of S9 outcome to tune molecule-specific settings.

Only an NS7 acceptance may reopen a later sequential-search design.

## Final Go/No-Go

V6 rank adaptation continues only if a newly certified transition passes the
hard full-circuit resource gate. It becomes a PRA performance candidate only
after a new frozen energy/stationarity protocol passes in multiple development
conditions and later unseen validation.

The rank-adaptive PRA track stops if no primary-eligible circuit remains after:

- direct synthesis of registered target families;
- sparse-UCRY specialization;
- exact-rewrite closure;
- the discrete family registry;
- bounded symbolic search;
- the development context census.

Negative results remain publishable evidence, but are not relabeled as
compression success.
