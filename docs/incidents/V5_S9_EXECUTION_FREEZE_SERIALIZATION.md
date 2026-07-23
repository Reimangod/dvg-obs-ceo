# V5-S9 execution-freeze serialization incident

## Scope

All three frozen S9 result files bind the execution-freeze record inside the
canonical source path ID, but do not expose the same record as a top-level
human-readable field.

## Cause

The `execution_freeze` argument was inserted into the source path ID payload,
as intended for cryptographic identity, but the intended top-level result
field was omitted because the edit matched the earlier `runner_version`
occurrence.

## Impact

- Energy, gradients, states, acceptance decisions, resources, work counters,
  and branch isolation are unchanged.
- The source path ID cannot match unless the exact code tag, tag commit,
  checkpoint digest, S8 manifest check, checkpoint check, and pre-execution
  output-absence check are identical.
- Human-readable provenance is less convenient in the raw result.

This is a reporting/provenance serialization defect, not a scientific
execution defect. Repeating several hours of deterministic exact-statevector
work would add no scientific evidence.

## Mitigation

The independent S9 audit reconstructs the exact freeze record and verifies the
canonical source path ID. The runner now also emits the record as a top-level
field for future results. The original result files remain immutable.
