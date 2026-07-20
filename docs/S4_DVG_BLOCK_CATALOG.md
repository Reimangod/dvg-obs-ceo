# S4 DVG block introspection and candidate catalog

## Recovered upstream semantics

S4 follows the pinned paper-era implementation rather than inferring blocks
from parameter magnitude:

- a non-parent operator with `ceo_type=sum/diff` is an OVP block;
- consecutive parent QEs with identical support are one MVP circuit block;
- one parent QE on its own is a single-QE block;
- a non-parent single excitation with no CEO type is also a single-QE block.

Grouping follows the actual paper-era accumulated-resource path: each ADAPT
iteration is passed to `get_circuit` separately. Selection iteration and
TETRIS-layer positions are retained per parameter, and parent QEs are never
merged into one MVP across an iteration boundary.

Every block records ordered ansatz positions, pool indices, coefficient
context, generator and constituent-QE digests, support, normalization,
orientation, circuit implementation, and verified particle/spin symmetry.
Structural block IDs exclude numeric coefficients; a separate numeric-context
digest binds the current values.

## Candidate universe

S4 generates:

- OVP/single-QE block deletion;
- MVP whole-block deletion;
- each MVP constituent deletion;
- MVP to each constituent single QE;
- every exactly representable native OVP sum/difference on the same support.

Each candidate includes both `A theta=b` and a canonical native Jacobian `J`,
target generator digests, semantic-conflict positions, and an equivalence-class
ID. Thus, for a two-QE MVP, “delete one constituent” and “convert to the other
single QE” remain traceable as different hypotheses but are identifiable as
the same structural transformation.

## Important upstream failure reproduced

The official MVP circuit routine expects all eight Pauli terms. Constraining a
two-QE MVP to equal or opposite coefficients cancels four terms; calling the
MVP routine in place then raises `ValueError: 'YXXX' is not in list`. Therefore
parameter constraints alone are not a safe circuit transformation. Accepted
MVP-to-OVP candidates must rebuild the block with the official native OVP
circuit. This is also why “parameter deletion” is not automatically “circuit
deletion.”

## Verification

The pinned four-qubit DVG pool probe recovered OVP, MVP, and single-QE blocks
and produced nine candidates. All nine passed generator, unitary, and random
state comparisons at tolerance `1e-10`; all six nonempty target circuits also
matched their target generator unitaries up to global phase. The global phase
is recorded because it is physically irrelevant but numerically visible. A
second independent artifact generation produced the identical SHA-256 digest.

Nine S4 tests pass locally after the S6 iteration-boundary audit, including two
pinned-upstream integration tests; the stage-equivalent full suite has 41
passing tests. The paper-era Qiskit stack emits 95 known
deprecation warnings locally. Minimal CI, which intentionally does not build
the costly baseline extra, runs the seven dependency-independent S4 tests and
reports the two integration tests as explicit skips. The pinned integration
artifact is committed so this distinction is auditable.

S6 auditing corrected two representation assumptions without changing the
registered S4 probe digest: blocks are split at paper-counter iteration
boundaries, and empty iteration segments are retained after deletion. Both are
covered by regression tests.

## Claim boundary

S4 validates block recovery and exact small-block transformations. It does not
show that any candidate is energetically safe, resource-improving in a full
ansatz, or useful on LiH. Those require Hessian quality, full-circuit recount,
transactional reoptimization, and calibration in S5-S9.
