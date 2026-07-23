# V4.1 S5 v1.3 incident: retained-prediction telemetry understatement

## Status

Contained after H6 1.5 A surrogate screening and before any exact candidate
energy evaluation. The H6 1.5 A bundle is preserved but superseded. The H6
3.0 A run was interrupted before canonical output; its transaction lease
removed the lock and incomplete staging normally.

## Defect

V1.3 correctly removed the 10,000-state full-prediction cache. It then reported
`maximum_full_prediction_live_set: 1`. However, after energy filtering, the
runner retained full target-native prediction dictionaries for all 1,201
quality-passed resource candidates so that four selected sentinel records could
later be materialized. The field therefore understated retained full records.

This did not affect candidate IDs, predicted energies, quality decisions,
resource recounts, or endpoint selection. It did affect the truthfulness of a
new computation-cost telemetry field and is therefore not acceptable as final
evidence.

## Correction and regression

V1.4 stores only lightweight identity, target-structure, and resource evidence
for non-selected candidates. After selection, it recomputes the complete
prediction and quality record for exactly the frozen sentinel queue, verifies
semantic and numerical IDs, and fails closed on drift. Telemetry now reports
the actual number of full quality predictions and retained full-prediction
records.

Regression tests prove that only selected semantic IDs are replayed, preserve
selection order, and reject semantic or numerical identity drift.

## Recovery and claim boundary

The v1.3 H6 bundle and its hashes remain immutable. It is not final S5 evidence.
All three cases must be rerun under a new root and v1.4 tag. No exact/FCI or
candidate VQE energy informed this correction.
