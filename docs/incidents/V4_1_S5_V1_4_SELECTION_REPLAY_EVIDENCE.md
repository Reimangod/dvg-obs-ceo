# V4.1 S5 v1.4 incident: incomplete selection replay evidence

## Status

All three v1.4 screening bundles completed without semantic, numerical, or
resource-construction failures. They are preserved but superseded before any
exact candidate-energy evaluation.

## Defect

Each bundle stores the four selected sentinels with full prediction, quality,
and resource evidence. It does not store the energy-blind selector input table
for every quality-passed candidate. Consequently, a third party cannot replay
the Pareto set and four endpoint orderings from the standalone artifact without
rerunning circuit synthesis.

This violates the preregistered S5 completion gate even though it does not
change the selected candidates.

## Correction

V1.5 persists, in canonical semantic-ID order, every selector input's candidate
IDs, semantic and numerical IDs, fixed-surrogate predicted loss, target
structure, iteration boundaries, and complete paper-era resource snapshot.
Quality rejections also retain the numerical diagnostics and complete quality
policy result instead of only failed-check names.

The producer reconstructs all `GlobalResourceCandidate` values from this table,
replays the four-endpoint selector, and requires byte-equivalent selection
content before finalizing the bundle. Tests reject missing evidence and any
selection tamper.

## Scientific impact and recovery

The v1.4 values remain valid observed screening output but are not final S5
evidence. No exact/FCI or candidate VQE energy informed the correction. V1.5
uses unchanged candidates, budgets, thresholds, numerical policy, resource
backend, and endpoint ordering, writes to a new root, and must reproduce v1.4
scientific fields exactly.
