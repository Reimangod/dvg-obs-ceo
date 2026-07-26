# V6-NS10 H6 optimizer-scalability ablation

Status: frozen before trust-region outcomes

## Entry and purpose

NS9 passed its additional-transition and legacy-frontier gates. NS10 therefore
tests whether the four immutable H6 NS7 failures are sensitive to optimizer
scaling. It is an outcome-informed development ablation and cannot revise NS7.

## Fixed comparison

Existing NS7 identity-BFGS results are reused without rerunning. One new
target-coordinate optimizer is registered:

```text
scipy.optimize.minimize(method="trust-constr")
hessian update: scipy.optimize.BFGS(init_scale=1.0)
initialization: the same Euclidean plane projection used by NS7
maximum iterations: 200
gtol: 1e-8
xtol: 1e-12
barrier_tol: 1e-12
fallback: none
```

The identical policy is used for H6 1.5 A and H6 3.0 A and for both registered
normals. One unconstrained same-structure control per context uses the same
trust-region optimizer from the frozen source coordinates.

## Queue and work cap

- rank-two candidate attempts: four;
- same-structure controls: two;
- maximum optimizer starts: six;
- maximum iterations: 1,200;
- maximum energy evaluations: 1,500;
- maximum gradient-vector evaluations: 1,500;
- finite-difference energy evaluations: 60;
- full native resource recounts: four.

FCI, chemical accuracy, Measurement Cost, threshold relaxation, additional
optimizers, H6-specific settings, and successful-result filtering are
prohibited.

## Interpretation

- Trust candidate passes: optimizer-sensitive evidence for that fixed family.
- Controls pass while candidate fails: constraint/family or constrained
  landscape remains implicated.
- Controls also fail: this optimizer does not resolve scalability.

Any pass remains a development ablation. Cross-molecule superiority and PRA
performance remain unestablished.
