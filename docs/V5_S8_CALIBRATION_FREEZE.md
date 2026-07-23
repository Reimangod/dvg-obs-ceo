# V5-S8 calibration freeze

Status: complete development calibration; protocol frozen for S9.

## Scientific outcome

S8 established that the implementation is operationally valid but did not
improve the known LiH V4.1 endpoint. Negative settings and the accounting
incident remain preserved.

| Calibration | CNOT | CNOT depth | Total depth | Parameters | Energy increase (Ha) | Exact attempts |
|---|---:|---:|---:|---:|---:|---:|
| H4 source | 158 | 73 | 270 | 24 | 0 | 0 |
| H4 recycled sequential | 132 | 60 | 222 | 18 | 5.1901649e-5 | 2 |
| LiH source | 107 | 30 | 171 | 15 | 0 | 0 |
| LiH width-1 atomic sequential | 89 | 30 | 145 | 13 | 1.0230682e-5 | 2 |
| LiH width-1 joint | 58 | 30 | 92 | 8 | 8.6901380e-5 | 1 |
| LiH energy-aware width-2, 3 rounds | 58 | 30 | 92 | 8 | 8.6901380e-5 | 6 |
| LiH energy-aware width-4 | 58 | 30 | 92 | 8 | 8.6901380e-5 | 12 |

The width-2 search retained low-energy paths that resource-only dominance had
discarded. Those paths compressed safely across additional rounds, but the
strong joint candidate repeatedly converged to the same 58-CNOT,
8-parameter structure. That structure had no eligible successor catalog.
Width four evaluated source ranks one through four and eight second-round
candidates without improving the endpoint.

This supports a development-only structural-floor hypothesis for the current
registered transformation family. It is not proof of a global optimum.

## Incident and correction

The first energy-aware result omitted work for a parent catalog that produced
zero exact proposals. Its quantum results were not invalidated, but its
aggregate work is prohibited from comparison. The artifact and finding are
preserved under
`dvg-obs-v5-s8-lih-energy-aware-width2-result-v1-incomplete`.

The corrected runner reports separately:

- exact-attempt work;
- every parent catalog's work, including terminal and unattempted catalogs;
- their complete aggregate.

The corrected width-2 and width-4 results passed independent 20-check audits
with quantum recomputation.

## Protocol frozen for S9

- width: 2;
- Top-K per parent: 2;
- maximum rounds: 3;
- maximum exact attempts: 6;
- beam dominance: resources plus actual source-relative energy increase;
- endpoint quota: 1;
- source-relative energy budget: 1e-4 Ha;
- target gradient infinity norm: at most 1e-8;
- joint candidate catalog: enabled;
- conditional target-native polishing: enabled;
- polishing internal L2 tolerance: 1e-8;
- threshold relaxation: prohibited;
- winner rule: minimum CNOT, parameters, total depth, CNOT depth, then energy
  and canonical path ID;
- complete catalog and exact-attempt work accounting: mandatory;
- paper Measurement Cost: undefined and reported as null.

Width four is not adopted because it doubled the LiH exact-attempt budget
without improving any guarded circuit endpoint. Width eight is not run:
the frozen per-parent selector exposes at most four unique attempts, and the
preregistered width-four stop rule was met.

## Claim boundary

All H2, H4, LiH, H6, and BeH2 cases in this repository are development cases.
S8 supports implementation validity, causal ablation, and a current-family
limitation. It does not support out-of-sample superiority, global optimality,
hardware/noise performance, or paper Measurement Cost claims.
