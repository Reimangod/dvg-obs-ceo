# S1 baseline parity

The clean wrapper executed the pinned, unmodified paper-era upstream with
`DVG_CEO`, TETRIS, and Hessian recycling. LiH at 3 Å matched the registered
reference exactly at the first chemical-accuracy checkpoint:

| Metric | Registered | Fresh run | Result |
|---|---:|---:|---|
| ADAPT iteration | 5 | 5 | exact |
| Energy (Ha) | -7.797909682469515 | -7.797909682469515 | exact |
| Parameters | 15 | 15 | exact |
| CNOT count | 107 | 107 | exact |
| CNOT depth | 30 | 30 | exact |
| Ansatz indices | registered sequence | same sequence | exact |
| Max coefficient difference | 0 | 0 | within 1e-9 |

The H2 1.5 Å smoke run also completed with one OVP block, one parameter,
9 CNOTs, and CNOT depth 7.

One earlier LiH run is retained as invalid because a process-wide CLI option
collided with PySCF's output handling. It is excluded from every comparison;
the reported parity is based on a complete rerun after the fix.

