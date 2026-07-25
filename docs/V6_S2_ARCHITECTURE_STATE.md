# V6 S2 unified ArchitectureState

Status: implementation step; no molecular performance result

## Outcome

S2 introduces an immutable, identity-bound ArchitectureState. It combines:

- StatePreparationID, ProblemID, and MeasurementContextID;
- ordered CEO blocks and ansatz positions;
- canonical generator semantics;
- canonical parameter-map IR;
- circuit and native-synthesis provenance;
- full current resources;
- explicit computational-work counters;
- evidence inventory;
- transition-registry, protocol, and environment digests;
- parent-checkpoint and original-artifact provenance.

## Canonical parameter maps

CEO affine maps are stored as exact rational strings rather than binary
floating-point numbers. For example, an OVP-minus relation is represented as:

```text
J = [[1], [-1]]
```

using canonical strings `"1"` and `"-1"`. Noncanonical equivalents such as
`"2/2"` are rejected. S2 originally validated representation and shape. S4
tightened the invariant: affine and periodic-affine maps now recompute
Jacobian rank with exact rational row reduction and reject an incorrect
`declared_rank`. Generator relations remain a separate S4 proof axis.

The supported representations are:

```text
IDENTITY
AFFINE_EXACT
PERIODIC_AFFINE_EXACT
REGISTERED_ANALYTIC_MAP
```

Arbitrary unregistered nonlinear functions are not serializable as executable
V6 maps.

## Identity binding

ArchitectureState requires exact agreement between the ordered block IR and
StatePreparationID for:

- ansatz indices;
- canonical coefficient bytes;
- block family and order;
- generator-definition digest;
- qubit order.

Measurement-plan changes leave StatePreparationID unchanged but change
MeasurementContextID and the complete ArchitectureState digest. Generator
orientation, block order, coefficient, or qubit-order changes alter the
appropriate state identity.

## Resource and work boundaries

Current resources include parameters, logical blocks, CNOT, CNOT depth, and
total depth with circuit digest and counter/synthesizer/compiler provenance.
Parameter and block counts must agree with the IR.

The work ledger stores heterogeneous computational operations separately and
always serializes paper Measurement Cost as `null`.

## Replay boundary

`original_artifact_digest` and `normalized_ir_digest` are distinct fields.
Historical bytes are never expected to have the same digest as the normalized
V6 representation. S3 will use this distinction for differential replay.
