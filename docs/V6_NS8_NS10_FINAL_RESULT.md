# V6 native-rank follow-up final result

Status: all stages in `V6_NS8_NS9_FOLLOWUP_PLAN.md` completed

## Stage decisions

| Stage | Question | Decision |
|---|---|---|
| NS8-A | Do accepted NS7 H4 candidates preserve the source mechanism? | Yes, pointwise state fidelity is numerical one and full-gradient checks pass. |
| NS8-B | Does one NS7 demotion add a same-source legacy Pareto point? | No, the reconstructible V5 round-1 point dominates it. |
| NS9 | Can a second bounded native rank transition certify? | Yes, 3 of 4 attempts pass. |
| NS9 frontier | Does the two-transition result add a legacy-nondominated point? | Yes, through the energy/CNOT-depth tradeoff. |
| NS10 | Does one fixed trust-region optimizer recover the H6 NS7 failures? | No, 0 of 4 candidates pass; both same-structure controls pass. |

## Best audited H4 native-rank point

Relative to the CEO* H4 late source:

| Metric | Source | V6 NS9 | Change |
|---|---:|---:|---:|
| Energy loss | 0 | numerical zero | preserved |
| CNOT | 158 | 154 | -2.53% |
| CNOT depth | 73 | 71 | -2.74% |
| Total depth | 270 | 262 | -2.96% |
| Parameters | 24 | 22 | -8.33% |

The accepted NS9 states reproduce the source state to numerical precision.
The result is nondominated by the reconstructible V5 H4 points, but it does
not dominate them: V5 obtains fewer CNOTs and lower total depth at different
energy/CNOT-depth tradeoffs.

## Generality boundary

H6 remains negative under both the original NS7 identity-BFGS and the frozen
NS10 trust-region ablation. The unconstrained H6 sources are already
stationary, while every constrained trust-region attempt remains above the
`1e-8` stationarity threshold after 200 iterations. This implicates the fixed
constrained landscapes or registered families within the tested protocols,
not H6 dimensionality alone.

BeH2 has no eligible frozen rank-three MVP block. Consequently:

- native-rank feasibility is established;
- a positive H4 development mechanism and frontier point are established;
- cross-molecule robustness is not established;
- matched-work superiority over every legacy method is not established;
- prospective validation and PRA performance claims are not established.

No further optimizer or threshold search is authorized by this completed
follow-up plan.
