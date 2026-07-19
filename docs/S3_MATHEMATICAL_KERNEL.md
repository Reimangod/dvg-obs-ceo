# S3 mathematical kernel

## Model and references

At the current checkpoint `theta`, S3 defines the local quadratic model

`q(x)-q(theta) = g^T(x-theta) + 1/2 (x-theta)^T H (x-theta)`

with the recycled approximation `M ~= H^-1`. A transformation is represented
twice and cross-checked:

- source constraint: `A x = b`
- canonical target-native map: `x = c + J phi`

The implementation requires full row rank in `A`, full column rank in `J`,
`A J = 0`, `A c = b`, and `dim(phi) = dim(x)-rank(A)`. Source and target slot
orders, generator normalization, orientation, and units are mandatory fields.

The unconstrained Newton point is `u = theta - M g`. With
`r = A u - b`, the reported constraint penalty is

`P = 1/2 r^T (A M A^T)^-1 r`.

The current-checkpoint prediction is separately reported as

`Delta q = -1/2 g^T M g + P`.

These values have different references and must not be compared as if both
were removal losses. At a stationary checkpoint (`g=0`), deleting coordinate
`i` reduces to the familiar OBS saliency `theta_i^2/(2 M_ii)`.

For native target optimization, S3 computes

`H_target = J^T M^-1 J`, `M_target = H_target^-1`

using Cholesky solves. It never explicitly forms a matrix inverse and never
silently regularizes a rejected matrix.

## Numerical and engineering policy

- Input arrays are finite, defensively copied, and immutable.
- Symmetry, positive definiteness, condition number, rank, solve residual, and
  feasibility are checked explicitly.
- Rank SVD is used only for validation, never to define optimizer coordinates.
- Ill-conditioned, asymmetric, redundant, infeasible, or rank-deficient input
  fails closed.
- Tolerances are dimensionally named; energy roundoff is stated in Hartree.
- `quadratic-kernel-v1` is the semantic implementation version.

## Verification

Thirteen S3 tests cover coordinate deletion, multiple deletion,
`theta_1=theta_2`, `theta_1=-theta_2`, nonzero gradients, nonzero affine
constraints, source-slot permutation, target sign/basis rotation,
ill-conditioned rejection, analytic Newton directions, and the stationary OBS
formula. Randomized tests compare 120 SPD quadratic problems against direct KKT
solutions. The full repository suite has 32 passing tests.

## Claim boundary

S3 verifies algebra and numerical rejection behavior on quadratic models. It
does not establish that a recycled BFGS matrix is a sufficiently accurate
model of molecular VQE energy, nor that a candidate will retain chemical
accuracy after nonlinear reoptimization. Those are S5, S7, and S8 questions.
No CNOT, depth, parameter, energy, or measurement-cost performance claim is
made at S3.
