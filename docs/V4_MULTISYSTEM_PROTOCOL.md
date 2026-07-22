# V4 Global OBS multisystem protocol

This protocol applies the already frozen V4 configuration to the stored
CEO-ADAPT-VQE* first-chemical-accuracy checkpoints for linear H6 at 1.5 A,
linear H6 at 3 A, and BeH2 at 3 A.

The source CEO* trajectories are not rerun. V4 uses the checkpoint gradient,
recycled inverse Hessian, registered block transformations, deterministic
Global OBS search, full paper-era circuit recount, and exact noiseless
acceptance gates. Actual candidate energy and FCI energy are excluded from
screening and ranking; they enter only independent pass/fail checks. The final
energy-increase budget is the smaller of the frozen 1e-4 Ha budget and the
strict remaining margin to chemical accuracy, so accepted compression cannot
trade accuracy for a better circuit.

No threshold, candidate family, search budget, optimizer limit, fallback rule,
or ranking criterion is relaxed from `v4-s6-frozen-config-v1.json`. Protocol
v1.1 adds a molecule-independent, strictly stronger final accuracy guard.
Rejected attempts are placed in atomic rollback directories and must restore
the complete source runtime snapshot.

Known symbolic composition conflicts are recorded separately from numerical
failures and conservatively do not prune descendants. Every surrogate-eligible
candidate rejected by the Hessian-quality gate persists its failed checks.

All source checkpoints were observed before this protocol was frozen. The
results are therefore exploratory multisystem generalization evidence, not
blind confirmatory validation. Paper-equivalent Measurement Cost remains
unavailable and no local work counter may be substituted for it.
