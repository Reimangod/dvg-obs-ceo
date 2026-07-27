# PRA critical path S11 reproducible release

Status: negative-result release authorized by the frozen S6 and S10 gates  
Release tag: `pra-critical-path-negative-result-v1`

## Scientific outcome

The registered native rank-demotion method produced independently certified
resource tradeoff points at H4 1.0 Å and H4 2.0 Å. Seven of eight frozen
candidates were accepted at each geometry. The best accepted candidate at
each geometry reduced CNOT count by 2, total depth by 4, and parameter count
by 1; CNOT depth did not improve.

All eight H5 1.5 Å candidates were rejected. They passed the frozen energy,
semantic, native-circuit, and resource checks, but reached the 200-iteration
optimizer cap and did not meet the frozen coordinate-invariant tangent
stationarity threshold. The outcome is retained as non-certification, not
silently rescued by changing the optimizer or threshold.

The preregistered cross-system S6 gate therefore failed. S7 matched-work
execution, S8 prospective activation, and S9 prospective execution were not
authorized. S10 records `NO_GO_PRA_PERFORMANCE_SUBMISSION_PACKAGE`.

## Reproduction

Use Python 3.10. The dependency graph is fixed by `uv.lock`.

```bash
uv sync --extra baseline --extra test
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  uv run pytest -q tests/pra_path
uv run python -m dvg_obs_ceo.pra_path.release_audit audit
```

The release manifest records a SHA-256 file hash for every artifact and
verifies every internal artifact digest that exists. The S2 protocol predates
the internal-digest convention; its immutable Git object and file SHA-256 are
recorded without inventing an internal digest. The release contains a
case-level CSV and a complete attempt-level CSV, including rejected candidates
and unavailable values.

No container image was built, so this release does not claim container-level
environment identity. The lockfile is the environment freeze. No Zenodo DOI
has been minted and no DOI claim is made.

## Code and data availability

Code, immutable stage artifacts, audit code, tables, and the dependency lock
are available from
[`Reimangod/dvg-obs-ceo`](https://github.com/Reimangod/dvg-obs-ceo) under the
release tag `pra-critical-path-negative-result-v1`.

## Claim boundary

This package does not provide matched-work superiority, prospective
validation, paper-equivalent Measurement Cost, general molecular
superiority, or evidence that the package is ready for a PRA performance
submission. It is a reproducible record of two positive H4 development
conditions and one H5 non-certification under a frozen protocol.
