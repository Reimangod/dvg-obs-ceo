# V6-NS9 wrong-entrypoint pre-execution failure

- Stage: NS9 queue freeze, before candidate evaluation
- Symptom: the module entry point invoked the pilot runner and failed its
  canonical-thread preflight because no queue freeze existed.
- Cause: `python -m ...ns9_sequential_pilot --freeze` does not dispatch the
  setuptools `freeze_main` entry point; the module main ignores that argument.
- Scientific impact: none. No candidate energy, gradient, optimizer, or
  statevector evaluation occurred. Neither freeze nor result artifact existed.
- Corrective action: invoke the dedicated `freeze_main` callable explicitly.
- Preventive control: documentation records separate freeze and execution
  entry points. The frozen queue, thresholds, and work caps are unchanged.
