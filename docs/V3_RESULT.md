# V3 stationarity-certification result

Status: closed, calibration unsuccessful. No LiH V3 transaction was run.

## Scope and immutable question

V3 asked whether the single S10 LiH 14-parameter diagnostic candidate could
meet the unchanged `1e-8` first-order stationarity threshold using one fixed
target-native trust-region Newton-CG polishing method. V3 did not rediscover a
candidate, rerun ordinary GSD-ADAPT or CEO*, or change the rejected V2 result.

## Completed evidence

- S0 verified 48 provenance, scope, candidate, threshold, and source-artifact
  checks.
- S1 independently compared direct target gradients with `J.T @ g_source` on
  all 17 stored H2/H4 candidates. The maximum infinity-norm difference was
  `2.220446049250313e-16`; all state and energy equivalence checks passed.
- S2 preregistered one SciPy 1.10.1 trust-NCG family with analytic gradients,
  central-difference HVPs, fixed trust radii, deterministic work budgets, and
  no fallback.

## S2 calibration outcome

Sixteen of 17 H2/H4 candidates already met the unchanged `1e-8` infinity-norm
certificate and required no SciPy iteration. One H4 candidate started at
`1.6579406564645738e-8` and remained at approximately
`1.6579406493522075e-8`. It exhausted the fixed budget of 128 gradient-vector
evaluations and 64 HVP calls without a resolvable energy improvement.

The failed input coordinates were restored exactly. The deliberate budget
failure injection also left its input unchanged. Normal ADAPT and CEO* ADAPT
iteration counters remained zero.

## Stop-rule decision

The V3 plan states that an unstable H2/H4 configuration ends V3 without a LiH
attempt. Therefore:

- V3-S3 was not executed;
- no LiH candidate was committed or newly rejected by V3;
- V2 remains rejected and rolled back;
- no circuit improvement, total-work reduction, validation, or paper
  Measurement Cost claim is made for V3;
- further stationarity work belongs to V4 rather than a LiH-specific V3
  retuning campaign.

Two failed S2 protocol revisions are retained. V1 exposed an incorrect
zero-dimensional work-reconciliation rule and missing preflight short circuit.
V1.1 exposed invalid `NaN` failure serialization. V1.2 retained a strict JSON
failed-result bundle and is the terminal V3 calibration record.
