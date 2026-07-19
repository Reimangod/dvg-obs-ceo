# S2 scientific identity and telemetry

## Outcome

S2 separates three concepts that must not be conflated:

1. `StatePreparationID`: the prepared state, including ordered block structure,
   ordered coefficients encoded as canonical IEEE-754 bytes, mapping, and qubit
   ordering.
2. `ProblemID`: the Hamiltonian and molecular problem definition.
3. `MeasurementContextID`: the state and problem IDs plus observables,
   measurement plan, grouping, estimator, and backend context.

A measurement-plan change therefore leaves `StatePreparationID` unchanged but
changes `MeasurementContextID`. Cached measurements are reusable only when the
complete measurement-context ID is identical.

## Fail-closed invariants

- Every stored ID is recomputed from its canonical payload on read.
- The measurement context must bind the exact stored state and problem IDs.
- Block slot order must equal ansatz parameter order; equal lengths alone are
  insufficient.
- Non-finite identity coefficients and ambiguous negative zero are rejected or
  canonicalized before hashing.
- Telemetry is append-only JSONL with contiguous sequence numbers, an event
  hash chain, process locking, complete-write loops, and `fsync`.
- Tampered, non-UTF-8, invalid-time, blank, or truncated records are rejected
  before another event can be appended.
- Resource counters and optimizer work/norm diagnostics reject negative or
  non-finite values.

## Version policy

Schema version `1.0.0` is immutable. Existing artifacts are never silently
migrated or reinterpreted. A semantic change requires a new schema file, a new
ID prefix or version, an explicit one-way migration tool, and preservation of
both source and migrated artifacts with their digests. Until such a tool is
reviewed, unknown schema versions fail closed.

## Academic claim boundary

S2 establishes provenance and reuse safety only. It does not claim lower
energy, fewer CNOTs, lower depth, fewer parameters, or paper-equivalent
measurement savings. Work counters are explicit implementation counters;
`shots`, circuit executions, gradient components, and energy evaluations are
not interchangeable and are never collapsed into an unnamed “cost”.

## Verification

Nineteen tests pass, including schema round-trip, payload tamper detection,
cross-Hamiltonian reuse rejection, measurement-plan separation, hash-chain
tampering, truncated-write rejection, and invalid diagnostics. The complete
suite also retains S0/S1 isolation and baseline tests.
