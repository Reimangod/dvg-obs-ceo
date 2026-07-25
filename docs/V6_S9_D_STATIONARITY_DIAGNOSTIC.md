# V6-S9-D read-only stationarity diagnostic

Status: completed without new quantum or optimizer work

## Result

The saved final gradients are not narrowly localized to the demoted rank-2
block.

| Candidate suffix | Components above `1e-8` | Fraction | Maximum inside demoted block | Global maximum | Global maximum inside block |
|---|---:|---:|---:|---:|---|
| `dc96ba44d20a` | 103 / 128 | 80.47% | 4.54e-8 | 3.10e-7 | no |
| `54d1ebd0cac4` | 102 / 128 | 79.69% | 1.39e-7 | 2.81e-7 | no |

This is evidence of broad residual nonstationarity under the frozen optimizer
protocol, rather than one isolated omitted-generator component.

## Saved BFGS surrogate

The final inverse-Hessian surrogates are numerically symmetric and their
symmetric parts are positive definite:

| Candidate suffix | Surrogate condition number | Implied minimum curvature | Gradient squared alignment with five lowest-curvature directions |
|---|---:|---:|---:|
| `dc96ba44d20a` | 1.68e4 | 3.73e-4 | 4.13e-4 |
| `54d1ebd0cac4` | 2.52e4 | 2.41e-4 | 1.20e-4 |

The conditioning is nontrivial. However, the saved final gradient has less than
0.05% squared alignment with the five lowest-curvature directions of the BFGS
surrogate. The available data therefore do not support the stronger claim that
flat directions alone caused failure.

These are optimizer-generated BFGS surrogates, not exact molecular Hessians.
No physical-curvature claim is made.

## What cannot be recovered

S9 did not save:

- per-iteration coordinate or step-norm trajectories;
- line-search trial points or Wolfe-condition diagnostics;
- exact final Hessians or new HVPs.

S9-D intentionally did not rerun any optimizer, energy, gradient, HVP,
statevector, or circuit calculation. It cannot distinguish conclusively among
target expressivity, parameterization, line search, and iteration-cap effects.
It does not reassess either S9 acceptance decision.

## Decision

The diagnostic does not justify reopening the stopped
`SPARSE_UCRY_RANK2` protocol. Native primary-resource synthesis remains the
next research bottleneck.
