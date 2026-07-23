# V4-S4 deterministic Global OBS search

V4-S4 searches the registered H2/H4 constraint catalog using a deterministic
depth-first traversal. It evaluates every nonempty canonical candidate subset
at most once. Candidate choices from the same source block are mutually
exclusive.

Descendants are pruned only when the fixed positive-definite quadratic
surrogate proves that the cumulative predicted loss already exceeds the
registered `1e-4` Hartree screening budget, or when exact semantics prove the
branch infeasible. A candidate-specific numerical or evidence failure rejects
only that completed state; it cannot reject descendants.

The audit runs both exhaustive enumeration and branch-and-bound on H2 and H4.
Their eligible canonical state-ID sets must match exactly. Work is bounded by
deterministic counters, and every pruning reason is retained. No VQE energy,
FCI energy, ordinary ADAPT iteration, or CEO* iteration is evaluated in S4.

“Complete” in this stage means complete only under the frozen quadratic
surrogate and registered candidate catalog. It is not a global-optimum claim
for the nonlinear VQE energy.
