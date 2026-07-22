# V4.1 S7 v1 resource-record audit false positive

## Status

Resolved before accepting or tagging the S7 result. The first H6 1.5 A exact
bundle is retained under `artifacts/v4.1/incidents/s7-audit-v1/h6-1.5` and is
not a canonical result.

## Observation

The exact run completed four preregistered sentinel attempts: three committed
and one rolled back exactly. The independent audit then failed closed at its
aggregate `attempt_audits` check.

## Root cause

The audit compared the complete physical-coefficient resource record with the
complete deterministic-structural resource record. These records deliberately
contain different `coefficient_policy` provenance, so record equality is not a
valid invariant. All four synthesized `ResourceSnapshot` values were equal,
which is the invariant used by the frozen acceptance decision.

## Correction and impact boundary

The audit now compares only the two `snapshot` payloads. No candidate,
prediction, optimizer, energy budget, acceptance rule, circuit counter, or
transaction implementation changed. Nevertheless, because audit code is part
of the frozen S7-S9 implementation, the corrected code receives a new v1.1 tag
and H6 1.5 A is replayed from the original checkpoint before S8 begins.

## Claim boundary

The retained v1 bundle is incident evidence only. Its numerical outcome is not
used for selection, tuning, or a performance claim.
