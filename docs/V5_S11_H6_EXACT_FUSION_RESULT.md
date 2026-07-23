# V5.1-S11 H6 exact-fusion result

The frozen joint-fusion execution passed all checks. Applying both S10
candidates to the frozen V4.1 H6 1.5 Å comparison point produced:

| Metric | V4.1 source | V5.1 exact fusion | Change |
|---|---:|---:|---:|
| Energy increase from CEO* (Ha) | 8.8214266e-5 | 8.8214266e-5 | +8.88e-16 |
| CNOT | 858 | 840 | -18 (-2.10%) |
| Parameters | 131 | 129 | -2 (-1.53%) |
| Total depth | 1546 | 1520 | -26 (-1.68%) |
| CNOT depth | 300 | 300 | 0 |
| Logical blocks | 78 | 76 | -2 (-2.56%) |

State fidelity was exactly `1.0` at the recorded precision. Both generator
identity residuals and all commutator residuals were zero. Physical and
deterministic-structural resource recounts agreed.

No optimizer was started: the work record contains two energy evaluations, two
statevector evaluations, four full resource recounts, and zero optimizer
iterations. The improvement therefore does not come from spending more
optimization work.

This establishes a strict lossless improvement over the frozen V4.1 source
point on every resource, with CNOT depth unchanged. It remains a
development-case result on H6 1.5 Å. The transformation family has no candidate
on the other three current cases, so global or out-of-sample superiority is not
claimed.
