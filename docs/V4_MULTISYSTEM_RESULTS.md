# V4 multisystem results

Protocol: `dvg-obs-v4-multisystem-protocol-v1.1`  
Protocol commit: `9b3d1bff3fd9051321258444daabf461ad689adc`  
Execution model: exact noiseless statevector, stored first-chemical-accuracy
CEO-ADAPT-VQE* checkpoints, fixed Global OBS V4 search and acceptance gates.

## Outcome

| Case | CEO* / retained V4 error (mHa) | CNOT | CNOT depth | Total depth | Parameters | Logical blocks | Exact VQE attempts | Accepted V4 candidate |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| H6 1.5 A | 1.391896 | 879 | 306 | 1595 | 137 | 79 | 0 | none |
| H6 3.0 A | 1.507241 | 785 | 294 | 1493 | 149 | 95 | 0 | none |
| BeH2 3.0 A | 1.336234 | 284 | 94 | 458 | 38 | 32 | 0 | none |

V4 retained the source CEO* circuit in all three cases. Consequently, the
observed V4 reduction in CNOT, depth, parameters, and logical blocks is exactly
zero for this fixed protocol. Accuracy was not degraded.

## Selection evidence

| Case | Catalog candidates | Evaluated states | Surrogate-eligible states | Quality-passed states | Symbolic composition failures | Search status |
|---|---:|---:|---:|---:|---:|---|
| H6 1.5 A | 319 | 10000 | 71 | 0 | 9792 | budget-truncated |
| H6 3.0 A | 359 | 10000 | 59 | 0 | 9728 | budget-truncated |
| BeH2 3.0 A | 56 | 10000 | 1325 | 0 | 0 | budget-truncated |

Every surrogate-eligible state failed the frozen Hessian-quality gate, mainly
the target-Hessian condition-number check. No candidate reached full resource
selection or exact VQE optimization. The result therefore does not show that
no valid compression exists; it shows that none was certified within the
registered candidate family, frozen quality thresholds, deterministic traversal,
and 10,000-state search budget.

Known symbolic composition failures are reported separately from numerical
failures and do not prune descendants. All three runs report zero candidate
numerical failures. Exact/FCI energy was excluded from search and ranking; it
was available only to the final, strictly non-relaxing chemical-accuracy guard.

## Integrity audit

- Every source state and energy was independently reconstructed from its stored
  checkpoint before search.
- Every full source circuit was recounted with the pinned paper-era resource
  counter and matched the stored snapshot exactly.
- Each final `summary.json` canonical digest was independently recomputed and
  matched.
- No exact VQE transaction was started, so there is no accepted state or rollback
  whose correctness remains unaudited.
- The search was budget-truncated in all cases; no global-optimality claim is made.
- Paper-equivalent Measurement Cost remains unavailable and is not replaced by
  quadratic-solve or optimizer counters.

The H6 1.5 A protocol-v1 preliminary run is preserved under
`artifacts/v4/multisystem/_incidents/`. It produced the same no-winner outcome,
but conflated known symbolic conflicts with numerical failures and omitted the
individual quality-rejection evidence. It is not used as a final result.
