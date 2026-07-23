# V5-S10 exact fusion gate result

The frozen V5.1 transformation-family gate passed. Two candidates were found
on H6 1.5 Å and both passed every registered check. No candidate was found on
LiH 3.0 Å, H6 3.0 Å, or BeH2 3.0 Å.

| Case | Candidates | Certified |
|---|---:|---:|
| LiH 3.0 Å | 0 | 0 |
| H6 1.5 Å | 2 | 2 |
| H6 3.0 Å | 0 | 0 |
| BeH2 3.0 Å | 0 | 0 |

Each H6 candidate independently produced:

| Metric | Source | Exact-fusion target |
|---|---:|---:|
| CNOT | 879 | 870 |
| Parameters | 137 | 136 |
| Total depth | 1595 | 1582 |
| CNOT depth | 306 | 306 |
| Logical blocks | 79 | 78 |

For both candidates, the registered generator identity residual and every
audited commutator residual were exactly zero. The independently reconstructed
energy drift was `4.440892098500626e-16` Ha and state fidelity was
`1.0000000000000004` before numerical clipping.

This is a lossless removal of a redundant OVP parameterization. It uses an
exact signed coordinate transfer to an existing MVP and physically removes the
OVP circuit. It is neither coefficient-magnitude pruning nor barrier-free
full-ansatz Qiskit compilation.

## Decision

S10 authorizes V5.1-S11 to compose the two certified rewrites, retest them from
frozen source and compressed checkpoints, and integrate them as a separately
ablated preprocessing/transaction family. S10 alone does not establish
performance superiority because the figures above are relative to the
uncompressed H6 source, not the matched V4.1 frontier.

Paper Measurement Cost remains undefined.
