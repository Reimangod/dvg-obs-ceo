# V6-NS8 H4 mechanism and frontier result

Status: complete, independently audited

## Mechanism

Both accepted NS7 candidates reproduce the H4 source state to numerical
precision:

| Normal | Source/candidate fidelity | Analytic gradient infinity | Largest full-FD gradient infinity |
|---|---:|---:|---:|
| `(1,1,-1)` | `0.9999999999999998` | `6.94e-9` | below `1e-8` |
| `(1,1,1)` | `1.0` | `9.31e-9` | below `1e-8` |

The candidate/candidate fidelity is `1.0`. Particle number is 4, spin-z is
zero, and spin-squared is zero to numerical precision for the source and both
candidates. Thus, at this checkpoint the native rank transition is not merely
energy recovering: the reoptimized candidates reproduce the source state
numerically. This is pointwise state evidence, not a familywise source-state
preservation theorem.

All 23 target coordinates were checked with centered finite differences at
three step sizes. The analytic maximum-gradient component was explicitly
included. Numerical Hessians are highly ill-conditioned and contain only tiny
negative eigenvalues near numerical precision; they are diagnostics, not
exact physical-Hessian proofs. NS7 did not record optimizer iterates, so no
historical trajectory is reconstructed.

## Same-source frontier

The exact H4 late source identity, energy, state digest, and resource counts
match the audited V5 artifact. Under a `1e-12 Ha` energy-equivalence tolerance:

| Point | Energy loss (Ha) | CNOT | CNOT depth | Total depth | Parameters | Frontier |
|---|---:|---:|---:|---:|---:|---|
| NS7 `(1,1,-1)` | numerical zero | 156 | 73 | 266 | 23 | dominated |
| NS7 `(1,1,1)` | numerical zero | 156 | 73 | 266 | 23 | dominated |
| V5 round 1 | numerical zero | 145 | 73 | 246 | 21 | nondominated |
| V5 round 2 | `5.19e-5` | 132 | 60 | 222 | 18 | nondominated |

Therefore NS7 establishes a new native rank-transition mechanism but does not
add a same-source energy-resource Pareto point over the reconstructible V5
history. V4.1, V5.1, and standalone magnitude endpoints are unavailable for
this exact late checkpoint and are not imputed. A prospectively shared
matched-work superiority claim is not established.
