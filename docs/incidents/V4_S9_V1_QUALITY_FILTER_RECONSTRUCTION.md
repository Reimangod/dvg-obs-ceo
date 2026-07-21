# V4 S9 v1 reporting incident: pre-filter candidates treated as selector inputs

## Status

Contained before publication. No V4 scientific result or S7 artifact was changed.

## What happened

The first S9 reporting run stopped with `V4ReportingError` before publishing a
report bundle. The reporting code iterated over all 127 search states whose
quadratic prediction was inside the energy budget, while the frozen S7 selector
had received only the 8 states that also passed the preregistered confidence and
quality filters.

The remaining 119 states correctly had no selector resource assessment. The
reporter incorrectly interpreted that absence as a reconstruction mismatch.

## Safety impact

- The failure occurred in derived reporting, after the S7 result and independent
  audit had been frozen.
- The reporter used a staging directory and stopped before atomic publication.
- The staging directory was empty; no partial table or figure was published.
- Energies, gradients, Hessians, candidate selection, optimization, and circuit
  resources in the S7 evidence are unaffected.

## Correction

S9 v1.1 reconstructs exactly the post-confidence selector inputs. It requires
their count to equal the selector's frozen `input_count`, and still verifies each
reconstructed structure digest against the frozen resource assessment.

This distinction is retained as an explicit ablation in the report:
127 prediction-budget candidates before confidence filtering and 8 after it.
