# V6-NS7 pre-execution import failure

- Stage: NS7, before the first candidate evaluation
- Symptom: `No module named 'adaptvqe'`
- Cause: the pinned upstream optimizer was imported before the existing
  upstream loader registered the vendored paper-era package path.
- Scientific impact: none. No candidate energy, gradient, statevector, or
  resource result was evaluated, and no NS7 artifact was written.
- Corrective action: move the optimizer import after `_algorithm_for`, which
  invokes the pinned upstream loader.
- Preventive control: an integration test now verifies that the optimizer
  becomes importable through the same loader order used by the runner.

The frozen NS6 queue, thresholds, initialization, optimizer settings, and
acceptance policy were not changed.
