# V5.1-S11b S9 integration result

The outcome-informed exploratory integration passed every frozen check. The two
S10-certified exact fusions were composed with the frozen S9 H6 1.5 Å winner
without optimization:

| Metric | S9 V5 source | V5.1 fused S9 point | Change |
|---|---:|---:|---:|
| Energy increase from CEO* (Ha) | 8.4636578e-5 | 8.4636578e-5 | 0 |
| CNOT | 858 | 840 | -18 |
| Parameters | 132 | 130 | -2 |
| Total depth | 1549 | 1523 | -26 |
| CNOT depth | 301 | 301 | 0 |
| Logical blocks | 78 | 76 | -2 |

State fidelity was `1.0`; generator identity and commutator residuals were
zero. No optimizer was started.

## H6 1.5 Å V5.1 Pareto choices

| Point | Energy increase (Ha) | CNOT | Parameters | Total depth | CNOT depth | Blocks |
|---|---:|---:|---:|---:|---:|---:|
| V4.1 + exact fusion | 8.8214266e-5 | 840 | 129 | 1520 | 300 | 76 |
| S9 V5 + exact fusion | 8.4636578e-5 | 840 | 130 | 1523 | 301 | 76 |

Neither point dominates the other: the first has lower circuit resources, and
the second has lower energy loss. Both strictly and losslessly improve the
specific compressed point from which they were derived.

This integration was designed after inspecting S10/S11 feasibility and is
therefore explicitly classified as outcome-informed development evidence. It
must not be presented as confirmatory or out-of-sample validation.
