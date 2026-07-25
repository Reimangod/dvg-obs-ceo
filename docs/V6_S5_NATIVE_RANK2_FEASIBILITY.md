# V6 S5 native rank-two feasibility

Status: **GO for a depth/parameter endpoint only**

## What is new

V4.1 already generated three-QE to two-QE parameter constraints using
`mvp-constituent-deletion`. It kept the paper-era MVP implementation, so the
rank reduction did not create a new native circuit.

S5 adds `v6-mvp3-rank2-sparse-ucry-v1`. For four same-spin orbitals, the three
QE generators rotate three disjoint pairs of complementary computational
basis states. A three-CNOT fanout maps each complementary pair to:

- one pivot-bit flip; and
- one distinct three-bit control label.

A uniformly controlled `Ry` then implements any retained pair of generators,
followed by the inverse fanout.

## Evidence

The exact basis map is

```text
y0 = x0
yi = xi xor x0, i = 1, 2, 3
```

For the pinned canonical same-spin pool, the control labels and angle scales
are:

| QE | control label | UCRY angle |
|---:|---:|---:|
| 6 | `011` | `+2 theta` |
| 7 | `110` | `-2 theta` |
| 8 | `101` | `+2 theta` |

All three ordered-subset rank-two maps have separate algebraic
target-embedding evidence. The native direct-sum construction has a symbolic
familywise derivation and arbitrary-context equal-local-unitary substitution
evidence. Twenty-one seeded matrix checks across all three retained pairs
have maximum unitary residual below `1.5e-15`; these checks corroborate rather
than replace the symbolic proof.

The UCRY decomposition follows the uniformly controlled rotation construction
implemented by pinned Qiskit and attributed there to Shende, Bullock, and
Markov: [arXiv:quant-ph/0406176](https://arxiv.org/abs/quant-ph/0406176).

## Full-ansatz feasibility result

The frozen H6 1.5 Å checkpoint contains two rank-three MVP blocks. Its source
reconstruction exactly matches all stored resources:

```text
parameters       137
logical blocks    79
CNOT             879
CNOT depth       306
total depth     1595
```

All six possible one-constituent demotions have:

```text
parameters       -1
logical blocks    0
CNOT              +1
CNOT depth         0 or +1
total depth        -2
```

Therefore this is **not CNOT compression**. It is a new nondominated
parameter/total-depth endpoint under the identical uncompiled full-QASM
counter. Later selection must keep it only for a total-depth or parameter
endpoint and must reject it when CNOT is the protected primary resource.

## GO boundary

S5 passes the plan's feasibility gate because:

- the native rank-two synthesis is absent from V4.1;
- all three mathematical target embeddings are registered;
- familywise native and context semantics are established;
- the frozen representative full ansatz has a strict total-depth gain;
- source reconstruction and independent numerical checks pass.

This GO does **not** establish:

- lower energy or preserved accuracy after demotion;
- a CNOT or CNOT-depth improvement;
- favorable matched-work performance;
- generalization beyond development data;
- paper Measurement Cost.

The source point generally does not lie in the rank-two subfamily, so an
actual demotion remains approximate unless membership is separately proven.
It must undergo later reoptimization, independent certification, and
transactional rollback.
