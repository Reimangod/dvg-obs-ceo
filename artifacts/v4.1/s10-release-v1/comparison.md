# V4.1 S10 audited comparison

Primary comparison uses `cnot_primary` for V4.1 and the preregistered `circuit_primary` for V4. LiH V4.1 is an exact regression replay of V4.

| Case | Method | Source abs. error (Ha) | Final abs. error (Ha) | E increase (Ha) | CNOT | ΔCNOT | CNOT depth | ΔCNOT depth | Depth | ΔDepth | Params | ΔParams | Blocks | ΔBlocks | Attempts | Accepted | Search |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| lih-3.0 | V4 | 0.000933477032892 | 0.00102037841248 | 8.69013795919e-05 | 58 | 49 | 30 | 0 | 92 | 79 | 8 | 7 | 8 | 7 | 2 | 1 | surrogate-complete |
| lih-3.0 | V4.1-regression | 0.000933477032892 | 0.00102037841248 | 8.69013795919e-05 | 58 | 49 | 30 | 0 | 92 | 79 | 8 | 7 | 8 | 7 | 2 | 1 | surrogate-complete |
| h6-1.5 | V4 | 0.00139189550728 | 0.00139189550728 | 0 | 879 | 0 | 306 | 0 | 1595 | 0 | 137 | 0 | 79 | 0 | 0 | 0 | budget-truncated |
| h6-1.5 | V4.1 | 0.00139189550728 | 0.00148010977283 | 8.82142655487e-05 | 858 | 21 | 300 | 6 | 1546 | 49 | 131 | 6 | 78 | 1 | 4 | 3 | budget-truncated |
| h6-3.0 | V4 | 0.00150724064212 | 0.00150724064212 | 0 | 785 | 0 | 294 | 0 | 1493 | 0 | 149 | 0 | 95 | 0 | 0 | 0 | budget-truncated |
| h6-3.0 | V4.1 | 0.00150724064212 | 0.00157858546963 | 7.13448275151e-05 | 768 | 17 | 293 | 1 | 1455 | 38 | 144 | 5 | 94 | 1 | 4 | 4 | budget-truncated |
| beh2-3.0 | V4 | 0.00133623439362 | 0.00133623439362 | 0 | 284 | 0 | 94 | 0 | 458 | 0 | 38 | 0 | 32 | 0 | 0 | 0 | budget-truncated |
| beh2-3.0 | V4.1 | 0.00133623439362 | 0.0014328494253 | 9.66150316817e-05 | 239 | 45 | 89 | 5 | 393 | 65 | 33 | 5 | 27 | 5 | 4 | 3 | budget-truncated |

`Δ` is source minus final, so a positive number is a reduction. Exact/FCI energy is offline reporting only and was absent from S5 screening and ranking.

| Case | Method | Catalog | Evaluated | Max card. | Semantic fail | Numerical fail | Quality fail | Optimizer fail | Acceptance fail | Recounts | Exact attempts | Energy eval. | Grad vectors | Grad components | Statevectors | Source wall (s) | Exact wall (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| lih-3.0 | V4 | 15 | 168 | 7 | n/a | 0 | 119 | 2 | 1 | 9 | 2 | 169 | 146 | 1297 | 14 | 94.0808 | n/a |
| lih-3.0 | V4.1-regression | 15 | 168 | 7 | n/a | 0 | 119 | 2 | 1 | 9 | 2 | 169 | 146 | 1297 | 14 | 94.0808 | n/a |
| h6-1.5 | V4 | 319 | 10000 | 7 | 9792 | 0 | 71 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 2749.97 | n/a |
| h6-1.5 | V4.1 | 319 | 10000 | 8 | 0 | 0 | 944 | 1 | 1 | 1202 | 4 | 671 | 661 | 85605 | 22 | 2749.97 | 242.423 |
| h6-3.0 | V4 | 359 | 10000 | 9 | 9728 | 0 | 59 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 3637.67 | n/a |
| h6-3.0 | V4.1 | 359 | 10000 | 8 | 0 | 0 | 1056 | 0 | 0 | 341 | 4 | 214 | 214 | 30837 | 20 | 3637.67 | 89.2248 |
| beh2-3.0 | V4 | 56 | 10000 | 9 | 0 | 0 | 1325 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 5957.48 | n/a |
| beh2-3.0 | V4.1 | 56 | 10000 | 9 | 0 | 0 | 1250 | 2 | 1 | 76 | 4 | 215 | 191 | 6590 | 24 | 5957.48 | 333.35 |

Paper-equivalent Measurement Cost remains `null`; quadratic solves, simulator work, and wall time are not substitutes.
