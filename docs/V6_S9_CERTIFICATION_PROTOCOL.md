# V6-S9 isolated native rank-2 certification protocol

Status: implementation complete; no candidate outcome may be evaluated until
the implementation is committed and the worktree is clean.

## Purpose

V6-S9 answers two development questions only:

1. Can either frozen V6-S8.1 Top-2 rank-2 target be fully reoptimized while
   satisfying the fixed energy and stationarity gates?
2. How large is the error of the two frozen legacy-model-consistent
   OBS/KKT point predictions?

V6-S9 is not a circuit-primary performance experiment. Every frozen candidate
has the same S7 resource change relative to the S6 parent:

| Metric | Delta |
|---|---:|
| Parameters | -1 |
| Total depth | -2 |
| CNOT | +1 |
| CNOT depth | +1 |
| Logical blocks | 0 |

An accepted result is therefore classified as
`EXPLORATORY_NATIVE_RANK2_FEASIBILITY_ACCEPTED`, never as primary CNOT
compression.

## Frozen inputs and information boundary

The runner consumes the V6-S8.1 artifact as its only authoritative queue.
The historical S8 Top-1 field cannot select an S9 attempt. Before the first
candidate-energy call, the runner requires:

- a completely clean committed worktree;
- canonical single-thread environment variables;
- exact SHA-256 hashes for S6, S7, V6-S8.1, and the legacy quadratic model;
- exactly two V6-S8.1 exploratory candidate IDs in frozen order;
- an empty circuit-primary queue;
- no existing S9 result or transaction directory.

The resulting execution freeze records the commit, dependencies, input hashes,
thread settings, candidate order, thresholds, fallback rule, and claim
boundary. Candidate 1 cannot initialize, reorder, or recalibrate candidate 2.
FCI and chemical-accuracy values are not acceptance inputs.

## Optimization policy

The primary start is the constrained solution of the frozen 131-dimensional
legacy quadratic surrogate, pulled through the exact S6 forward map and then
expressed in the 128-dimensional target coordinates.

The recycled inverse Hessian is not transported. S8 demonstrated that such a
transport is gauge-sensitive. Both primary and fallback starts therefore use
an identity inverse Hessian.

At most one fallback is allowed per candidate. It is triggered only when the
primary optimizer is unsuccessful or its target-gradient infinity norm exceeds
`1e-8`. The fallback starts from the unoptimized S6 demotion seed. The selected
path is the one with the lower final gradient infinity norm; energy breaks an
exact tie. No later fallback or threshold relaxation is permitted.

## Independent certification

Each attempt independently records and checks:

- optimizer energy and an independent semantic energy call;
- native-circuit statevector and Hamiltonian expectation;
- semantic-target versus native-circuit state fidelity;
- target gradient;
- the retained components of a separately evaluated source-path gradient;
- pulled-back coordinate constraint residual;
- a target-native full-circuit paper-era resource recount;
- S7 versus S9 counter equality;
- optimizer status separately from scientific acceptance;
- predicted and actual loss, signed error, absolute error, ratio, and
  under/overestimation direction.

A resource mismatch is an incident and fails closed; it is not interpreted as
an improvement.

## Endpoint decisions and lineage

Two decisions are emitted from the same scientific evidence:

- `circuit-primary-v1`: CNOT and CNOT depth must both nonregress, and at least
  one must improve strictly;
- `exploratory-depth-parameter-v1`: total depth and parameter count must both
  improve strictly. CNOT regressions remain disclosed.

Even an exploratory acceptance is committed only to an isolated S9 transaction
branch. The S6 primary parent and the primary V6 lineage remain unchanged.
Current S9 candidates cannot become an S10 primary sequential parent.

## Rollback audit

Before molecular attempts, a synthetic transaction audit injects:

- optimizer exception;
- timeout;
- NaN/Inf;
- energy mismatch;
- gradient mismatch;
- malformed circuit;
- counter mismatch;
- partial serialization;
- interrupt.

Every scenario must restore the exact runtime snapshot and must leave no
committed artifact. This audit certifies the transaction lifecycle only, not
quantum numerical correctness.

## Post-S9 decision

- If no candidate passes energy and stationarity certification, the current
  `SPARSE_UCRY_RANK2` family stops.
- If at least one passes, the family is accuracy-feasible with a resource
  trade-off. The next work is a separately versioned resource-only context
  census and native-synthesis redesign.
- If S9 resources differ from S7, execution stops as a counter/synthesis
  incident.

S10 sequential search is not authorized by an S9 exploratory acceptance.
