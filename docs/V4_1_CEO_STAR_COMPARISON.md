# CEO* and V4.1 audited comparison

## Comparison contract

- `CEO*` is the immutable source checkpoint used by V4.1. V4.1 does not run a
  new CEO* or ordinary-ADAPT growth iteration.
- The primary V4.1 result is the preregistered `cnot_primary` endpoint. LiH is
  the exact V4.1 regression replay of the accepted V4 result.
- All resource values use the same paper-era full-ansatz QASM counter. No new
  barrier-free or global Qiskit compilation is used.
- `reduction` is `CEO* - V4.1`; positive values mean a smaller circuit.
- Exact/FCI energy is offline evaluation evidence only. It was absent from
  screening, candidate ordering, and sentinel selection.

## Energy and accuracy

| Case | CEO* energy (Ha) | V4.1 energy (Ha) | Energy increase (Ha) | CEO* absolute FCI error (Ha) | V4.1 absolute FCI error (Ha) | Chemical accuracy retained |
|---|---:|---:|---:|---:|---:|---:|
| LiH 3.0 A | -7.797909682470 | -7.797822781090 | 0.000086901380 | 0.000933477033 | 0.001020378412 | Yes |
| H6 1.5 A | -2.994173530325 | -2.994085316059 | 0.000088214266 | 0.001391895507 | 0.001480109773 | Yes |
| H6 3.0 A | -2.799451659012 | -2.799380314185 | 0.000071344828 | 0.001507240642 | 0.001578585470 | Yes |
| BeH2 3.0 A | -15.335468001671 | -15.335371386640 | 0.000096615032 | 0.001336234394 | 0.001432849425 | Yes |

The chemical-accuracy threshold is `0.0015936 Ha`. H6 3.0 A retains only
approximately `0.0000150 Ha` of margin, so it is a valid but boundary-near
result rather than a large accuracy margin.

## Circuit resources

| Case | Metric | CEO* | V4.1 | Reduction | Reduction rate |
|---|---|---:|---:|---:|---:|
| LiH 3.0 A | CNOT | 107 | 58 | 49 | 45.79% |
|  | CNOT depth | 30 | 30 | 0 | 0.00% |
|  | Total depth | 171 | 92 | 79 | 46.20% |
|  | Parameters | 15 | 8 | 7 | 46.67% |
|  | Logical blocks | 15 | 8 | 7 | 46.67% |
| H6 1.5 A | CNOT | 879 | 858 | 21 | 2.39% |
|  | CNOT depth | 306 | 300 | 6 | 1.96% |
|  | Total depth | 1595 | 1546 | 49 | 3.07% |
|  | Parameters | 137 | 131 | 6 | 4.38% |
|  | Logical blocks | 79 | 78 | 1 | 1.27% |
| H6 3.0 A | CNOT | 785 | 768 | 17 | 2.17% |
|  | CNOT depth | 294 | 293 | 1 | 0.34% |
|  | Total depth | 1493 | 1455 | 38 | 2.55% |
|  | Parameters | 149 | 144 | 5 | 3.36% |
|  | Logical blocks | 95 | 94 | 1 | 1.05% |
| BeH2 3.0 A | CNOT | 284 | 239 | 45 | 15.85% |
|  | CNOT depth | 94 | 89 | 5 | 5.32% |
|  | Total depth | 458 | 393 | 65 | 14.19% |
|  | Parameters | 38 | 33 | 5 | 13.16% |
|  | Logical blocks | 32 | 27 | 5 | 15.63% |

## Exact-stage cost and failure evidence

| Case | Search status | Search states | Exact attempts | Accepted | Rolled back | Energy evaluations | Gradient vectors | Gradient components | Statevectors | Exact-stage wall time |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LiH 3.0 A | surrogate-complete | 168 | 2 | 1 | 1 | 169 | 146 | 1,297 | 14 | unavailable |
| H6 1.5 A | budget-truncated | 10,000 | 4 | 3 | 1 | 671 | 661 | 85,605 | 22 | 242.42 s |
| H6 3.0 A | budget-truncated | 10,000 | 4 | 4 | 0 | 214 | 214 | 30,837 | 20 | 89.22 s |
| BeH2 3.0 A | budget-truncated | 10,000 | 4 | 3 | 1 | 215 | 191 | 6,590 | 24 | 333.35 s |

These are simulator/software work counters, not the paper's Measurement Cost.
Paper-equivalent Measurement Cost remains `null` for both sides of this local
comparison because its original definition is not implemented in the current
V4.1 evaluation pipeline.

## Alternative frozen endpoints

| Case | Endpoint | Accepted result | Energy increase (Ha) | CNOT | CNOT depth | Total depth | Parameters | Blocks |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| H6 1.5 A | CNOT-primary / total-depth-primary | Yes | 0.000088214266 | 858 | 300 | 1546 | 131 | 78 |
|  | CNOT-depth-primary | Yes | 0.000057638158 | 865 | 298 | 1552 | 130 | 78 |
|  | Parameter-primary | No (KKT rejection) | - | - | - | - | - | - |
| H6 3.0 A | CNOT / CNOT-depth / total-depth-primary | Yes | 0.000071344828 | 768 | 293 | 1455 | 144 | 94 |
|  | Parameter-primary | Yes | 0.000078609408 | 770 | 294 | 1456 | 143 | 93 |
| BeH2 3.0 A | CNOT / parameter / total-depth-primary | Yes | 0.000096615032 | 239 | 89 | 393 | 33 | 27 |
|  | CNOT-depth-primary | Yes | 0.000059829644 | 271 | 87 | 431 | 35 | 31 |

## Interpretation boundary

V4.1 improves every registered resource metric relative to its matching CEO*
checkpoint for the selected primary result, except LiH CNOT depth, which is
unchanged. The improvement is not computationally free: it requires screening,
full resource recounts, and up to four exact VQE attempts. H6 and BeH2 searches
are budget-truncated, so these are audited best-found development results, not
global optima or unseen-system generalization evidence.

## Evidence sources

- `artifacts/v4.1/s10-release-v1/comparison.json`
- `artifacts/v4.1/s10-release-v1/multisystem-audit.json`
- `artifacts/v4.1/multisystem/<case>/summary.json`
- `artifacts/v4.1/multisystem/_audits/<case>.json`

The S10 bundle digest is
`e2ad6896fa79f568ed7ff625e4ad4ee074566dad8d6eda9e9a6ef41c16d05dba`.
