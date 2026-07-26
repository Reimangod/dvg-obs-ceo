# V6-NS9 bounded H4 sequential result

Status: complete, independently audited

Four outcome-blind attempts combined the two accepted NS7 roots with the two
registered normals on the remaining H4 rank-three MVP block.

| Root normal | Child normal | Energy loss (Ha) | Gradient infinity | CNOT | CNOT depth | Total depth | Parameters | Decision |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `(1,1,-1)` | `(1,1,-1)` | numerical zero | `2.07e-9` | 154 | 71 | 262 | 22 | accepted |
| `(1,1,-1)` | `(1,1,1)` | numerical zero | `1.03e-8` | 154 | 71 | 262 | 22 | rejected |
| `(1,1,1)` | `(1,1,-1)` | numerical zero | `4.93e-9` | 154 | 71 | 262 | 22 | accepted |
| `(1,1,1)` | `(1,1,1)` | numerical zero | `4.80e-9` | 154 | 71 | 262 | 22 | accepted |

The rejection remains outside the frozen stationarity threshold and its BFGS
run reported precision loss. No threshold or optimizer change was applied.

Every attempt reduced the original source by 4 CNOTs, 2 CNOT-depth layers, 8
total-depth layers, and 2 parameters. The three accepted points reproduce the
source state to numerical precision. They are not dominated by the
reconstructible V5 frontier: V5 round 1 has fewer CNOTs but worse CNOT depth,
and V5 round 2 has lower resources but a nonzero energy loss.

This passes the additional-transition and development energy-resource
frontier gates. It authorizes a separately frozen H6 optimizer-scalability
ablation, not a change to NS7 and not a PRA performance claim.
