# V5 / V5.1 audited development release

## Outcome

Core V5 remains exactly as frozen in S9: one strict success on H6 3.0 Å and no
global-superiority claim.

The separately versioned V5.1 exact-fusion extension adds a strict, lossless
H6 1.5 Å improvement. Across the four development cases, V5/V5.1 therefore
meets the preregistered strong-development threshold of two improved cases,
including H6. This is still not confirmatory evidence because all cases were
used during development and the H6 1.5 Å integration is outcome-informed.

## H6 1.5 Å final Pareto front

| Point | Energy increase (Ha) | CNOT | Parameters | Total depth | CNOT depth | Blocks |
|---|---:|---:|---:|---:|---:|---:|
| CEO* source | 0 | 879 | 137 | 1595 | 306 | 79 |
| V4.1 comparison | 8.8214266e-5 | 858 | 131 | 1546 | 300 | 78 |
| V5.1 resource point | 8.8214266e-5 | **840** | **129** | **1520** | **300** | **76** |
| S9 V5 comparison | 8.4636578e-5 | 858 | 132 | 1549 | 301 | 78 |
| V5.1 lower-energy point | **8.4636578e-5** | **840** | **130** | **1523** | **301** | **76** |

Relative to CEO*, the V5.1 resource point removes 39 CNOTs, 8 parameters,
75 total-depth layers, 6 CNOT-depth layers, and 3 logical blocks. Relative to
the matched V4.1 point, it removes 18 CNOTs, 2 parameters, 26 total-depth
layers, and 2 blocks while preserving energy and CNOT depth.

The lower-energy point preserves the S9 V5 energy exactly and removes 18 CNOTs,
2 parameters, 26 total-depth layers, and 2 blocks from that point.

## Matched release choices

| Case | Audited choice | Interpretation |
|---|---|---|
| LiH 3.0 Å | V4.1-equivalent | V5 did not improve it; V5.1 has no candidate. |
| H6 1.5 Å | V5.1 Pareto front | Two exact lossless choices. |
| H6 3.0 Å | V5 strict point | Lower energy loss and all guarded resources than V4.1. |
| BeH2 3.0 Å | V4.1 | V5's larger resource reduction missed the frozen energy condition; V5.1 has no candidate. |

## What is and is not established

Established:

- every adopted exact fusion has registered parent-QE provenance;
- generator identities and required commutators were audited;
- state, energy, and physical circuit resources were independently recomputed;
- fusion used zero optimizer starts and did not improve results by adding
  optimization work;
- no barrier-free full-ansatz Qiskit compilation was introduced.

Not established:

- unseen-system or noisy-hardware generalization;
- global V5/V5.1 superiority;
- a paper-equivalent Measurement Cost;
- benefit of exact fusion outside H6 1.5 Å in the current case set.

The complete machine-readable release summary is
`artifacts/v5/release/summary-v1.json`.
