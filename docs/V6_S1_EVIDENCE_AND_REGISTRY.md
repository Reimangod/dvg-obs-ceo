# V6 S1 evidence schema and transition registry

Status: implementation step; no molecular performance result

## Purpose

S1 prevents three scientifically unsafe states:

1. numerical agreement being reported as algebraic proof;
2. an unverified or unknown transition entering candidate generation;
3. parameter reduction being silently equated with physical-circuit
   compression.

## Orthogonal evidence

The implementation separates:

- target embedding;
- source parameter membership;
- source state equivalence;
- source unitary equivalence;
- native synthesis;
- contextual rewrite validity;
- physical resource delta.

Evidence strength, semantic scope, context scope, synthesis scope,
optimization requirement, and resource effect are independent fields.

An algebraic exact claim requires passed algebraic or symbolic evidence for
target embedding, source unitary equivalence, native synthesis, and contextual
rewrite. Numerical evidence cannot satisfy this gate.

Pointwise state evidence is restricted to a checkpoint or prefix state and
cannot be labeled as familywise unitary evidence.

## Transition registry

Candidate generation may use a transition only when:

- the registry is frozen;
- the transition ID is known;
- its status is `VERIFIED`;
- it carries versioned evidence IDs;
- its source rank strictly exceeds its target rank;
- parameter-map, generator-relation, and native-synthesis IDs are explicit.

Duplicate transition IDs and duplicate semantic definitions fail closed.

S1 introduces no verified V6 rank transition. The rank-2 transition used in
tests is synthetic schema evidence only. Whether a physically useful
MVP-rank-3 to native-rank-2 transition exists is deliberately deferred to the
S5 Go/No-Go study.

## Resource boundary

`ResourceDeltaEvidence` records parameters, logical blocks, CNOT count, CNOT
depth, and total depth separately. It also records the counter, synthesizer,
compiler configuration, qubit order, and before/after digests.

A parameter-only reduction is a real parameter-resource gain but does not
imply CNOT or depth reduction. Later candidate eligibility must additionally
require the frozen primary physical-resource contract.

## Claim contract

`manifests/v6-s1-claim-contract-v1.json` fixes:

- the exact-statevector noiseless study regime;
- all known development cases;
- forbidden runtime information;
- prohibited claims;
- the distinction between work accounting and paper Measurement Cost.

No V6 performance or PRA-readiness claim is made by S1.
