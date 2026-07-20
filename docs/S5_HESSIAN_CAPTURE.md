# S5 Hessian capture and quality diagnostics

## Evaluation-free observation

S5 temporarily wraps the exact `minimize_bfgs` object referenced by the pinned
upstream module. It does not replace the optimizer or evaluate energy/gradient
again. The wrapper forwards each existing Jacobian call once, copies its result
for provenance, composes the existing optimizer callback, and restores the
original function in `finally`. A process lock rejects nested capture.

Observing the Jacobian calls is necessary. When the upstream optimizer computes
the initial gradient internally, callback-only capture misses the first BFGS
pair. The registered H2 run had four optimizer iterations: the initial version
captured only three pairs, while the corrected observer captures all four and
fails closed if pair count differs from `nit`.

## Quality fields

For each optimization S5 records:

- initial/final parameters, gradients, and inverse Hessians;
- every internal `(s, y)` pair, curvature, normalized curvature, and validity;
- finite/symmetry/SPD/eigenvalue/condition diagnostics;
- valid/invalid update counts and Hessian age;
- internal secant residuals and direction coverage;
- separately supplied held-out residuals;
- optimizer status/message/nit/nfev/njev;
- gradient L2/RMS/infinity, projected-gradient, constraint, and KKT residuals.

Internal BFGS pairs are never relabeled as held-out. A held-out pair must be
created independently and is rejected if its content digest overlaps an
internal pair.

## Registered H2 OFF/ON result

Observer OFF and ON matched exactly for all registered scientific and work
fields: energy, error, trajectory, ansatz indices/coefficients, scientific-state
digest, parameters, CNOT count/depth trajectories, nfev, and component-equivalent
ngev. Wall time is excluded because observer bookkeeping intentionally adds
classical overhead; environment is provenance rather than a trajectory value.

The captured one-dimensional H2 optimization had:

- 4 optimizer iterations and 4 captured BFGS pairs;
- 5 function and 5 gradient evaluations;
- final gradient/KKT residual `1.4253661584362476e-9`;
- minimum inverse-Hessian eigenvalue `0.7236341907057654`;
- condition number `1.0`, age `0`, coverage `1.0`;
- internal max secant residual `0.06911580093004739`;
- zero held-out secants.

The matrix is numerically usable under the S5 numerical policy. This does not
mean it is calibrated as a pruning-loss predictor: held-out fidelity is still
unknown and must be measured in S8.

## Claim boundary

S5 establishes complete, non-invasive capture and diagnostic separation on the
registered H2 case. It does not establish Hessian predictive accuracy on H4 or
LiH, and it does not authorize candidate acceptance. Resource reductions and
energy safety remain untested at this stage.
