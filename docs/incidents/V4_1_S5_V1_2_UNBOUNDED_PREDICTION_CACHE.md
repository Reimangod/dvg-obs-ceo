# V4.1 S5 v1.2 incident: unbounded full-prediction cache

## Status and scope

Contained before any canonical sentinel result or exact candidate-energy
evaluation. The affected H6 1.5 A run is not scientific evidence and remains
preserved under `artifacts/v4.1/s5-sentinels-rerun-v2/`.

## Timeline

- The v1.2 run began from tagged commit `849879df2286e4846d1b78e88c6cbc49aff7680f`.
- Its crash-safe lease recorded run UUID
  `4f9c65e3-bfb1-40ea-9547-6c97f4d0ae9a` before computation.
- After 1:28:11 elapsed time, the process had used 26:08.47 CPU time. Memory
  increased from 6.4% to 11.4% while no canonical result existed.
- The process was intentionally interrupted. The lock and incomplete staging
  directory were not removed or reused.

## Root cause

The deterministic search evaluates each candidate set once, but the v1.2
runner retained the complete plan, target-native inverse Hessian, prediction,
and quality record for every evaluated state. Up to 10,000 large matrices were
therefore retained unnecessarily. The search also constructed target-native
diagnostics before knowing whether a state passed the fixed energy budget.

## Correction

V1.3 uses a fixed-source, memory-bounded constrained-Newton screening context.
It factors and validates the immutable source Hessian once, evaluates exactly
the same constrained optimum in constraint space, and retains no full
prediction cache. A complete target-native prediction and every original
quality check are still recomputed for each energy-eligible state before full
resource recount or sentinel selection.

The correction does not change candidates, IDs, search order, budgets, energy
thresholds, resource definitions, endpoint ordering, or quality policy.

## Regression evidence

- Random SPD systems across ten seeds and constraint ranks 1--4 require exact
  equality between the memory-bounded screening energy and the original full
  prediction energy.
- The direct quadratic value and constraint feasibility remain independently
  checked for every screened state.
- Disjoint exact-system composition is independently compared with a complete
  global exact RREF.
- The full suite passes before the v1.3 freeze.

## Scientific impact and recovery

No scientific result was produced, no exact/FCI or candidate VQE energy was
read, and no threshold was adapted. V1.2 is retained as an engineering
incident only. V1.3 must use a new root and frozen tag, and its sentinel output
must be committed before any S7--S9 exact execution.
