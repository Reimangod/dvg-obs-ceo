# S12 exact OGM-aware reuse result

## Decision

The exact term-level reuse mechanism is mathematically safe and passed all
OFF/ON parity checks, but it is **not adopted as a default performance feature**
for noiseless LiH CEO*. Its LiH reduction is only 369 of 517,893 fresh Pauli
expectation kernels (0.07125%). The added cache, identity, and plan-construction
complexity is not justified by that reduction alone.

| Case | Energy terms | OGM gradient union | Overlap/hits | OFF fresh | ON fresh | Reduction |
|---|---:|---:|---:|---:|---:|---:|
| H2 1.5 Å | 14 | 52 | 8 | 66 | 58 | 12.12% |
| LiH 3.0 Å | 630 | 517,263 | 369 | 517,893 | 517,524 | 0.07125% |

For both cases:

- reuse OFF and ON energies are bitwise equal;
- reuse OFF and ON gradient-vector digests are identical;
- the termwise energy and raw gradients agree with the pinned official sparse
  evaluator within the preregistered `1e-10` tolerance;
- StatePreparationID and ProblemID are identical across energy and gradient
  contexts, while MeasurementContextID remains distinct;
- finite shots and noisy estimators fail closed.

## Meaning of “OGM-aware” here

The gradient branch first forms the distinct union of Pauli terms across all
CEO pool gradient observables. This avoids double-counting repeated gradient
terms before energy-to-gradient reuse is applied. The cache then removes only
identical terms already available from the final energy context.

This is compatible with an OGM pipeline, but it does **not** reproduce the
paper's OGM commuting-collection construction or its measurement-cost bound.
The LiH union contains 517,263 non-identity terms, showing why grouping into
commuting collections is essential. A term count is not a collection count and
is not a shot count.

## Failure retained

Protocol v1 stopped on H2 because the audit compared an unthresholded
`2.02e-9` gradient norm with the official ranker's zero. The official ranker
intentionally discards individual gradients below `1e-8`. Protocol v1.1 fixes
the audit by comparing raw gradient vectors first, then independently checking
the official cutoff. No reuse threshold or success condition was relaxed.

## Engineering findings

- LiH protocol v1.1 took roughly 48 minutes because OpenFermion expanded 1,200
  Hamiltonian/operator products and the conservative parity run evaluated both
  OFF and ON branches independently.
- Each full LiH event ledger is about 258.5 MiB. Raw ledgers are stored under
  the Git-ignored `artifacts/raw/` tree; Git tracks their sizes, SHA-256 hashes,
  semantic ledger digests, summaries, and the independent audit.
- Future work should cache the immutable observable plan and use a streaming or
  aggregate ledger. These are engineering optimizations and must preserve the
  current semantic digests and OFF/ON results.

## Scientific boundary and next research direction

The result supports correctness of exact cross-context Pauli reuse. It does not
support a meaningful LiH performance improvement, a finite-shot advantage, or
the paper-equivalent Measurement Cost. A stronger measurement result requires
reuse at the commuting-collection/raw-outcome level plus an explicit shot and
covariance model. That extension should be a new preregistered protocol rather
than a reinterpretation of these counts.

The reuse idea follows the energy-to-next-operator-selection flow described in
[arXiv:2507.16879](https://arxiv.org/abs/2507.16879). CEO*'s OGM and measurement
cost definition remain those of
[Ramoa et al.](https://doi.org/10.1038/s41534-025-01039-4).
