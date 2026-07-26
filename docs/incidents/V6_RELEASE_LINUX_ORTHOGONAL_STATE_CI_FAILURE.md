# V6 release Linux orthogonal-state CI failure

- Affected run: GitHub Actions `30184182622`
- Affected commit: `a1199f7184c716998d5412d556573c3465e0b3af`
- Local result before discovery: 471 passed on macOS
- Linux result: 470 passed, 1 failed

## Cause

For two orthogonal states, the floating-point overlap was a tiny nonzero value
on macOS but exactly zero on Linux. The exact-zero branch returned an infinite
global-phase residual. Evidence serialization correctly rejects nonfinite JSON,
so Linux raised `IdentityError` instead of returning a failed equivalence
record.

## Correction

Orthogonal and numerically orthogonal pairs now receive:

- canonical fallback phase `1 + 0i`;
- finite limiting residual
  `hypot(norm(source), norm(target))`;
- ordinary `FAILED` numerical evidence when outside tolerance.

The test now requires a finite `sqrt(2)` residual and canonical phase for the
orthogonal normalized fixture. No V6 NS7-NS10 scientific artifact used this
failing orthogonal-state path, so recorded quantum outcomes and decisions are
unchanged.
