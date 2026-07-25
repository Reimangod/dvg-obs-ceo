# V6-NS7 result

Status: completed development certification

## Outcome

The frozen NS7 queue evaluated six attempts: two preregistered affine
rank-two families in each of H4 1.5 A, H6 1.5 A, and H6 3.0 A.

| Context | Normal | Energy loss (Ha) | Target gradient infinity norm | CNOT | CNOT depth | Total depth | Parameters | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| H4 1.5 A | `(1,1,-1)` | `-8.88e-16` | `6.94e-9` | `-2` | `0` | `-4` | `-1` | accepted |
| H4 1.5 A | `(1,1,1)` | `-2.22e-16` | `9.31e-9` | `-2` | `0` | `-4` | `-1` | accepted |
| H6 1.5 A | `(1,1,-1)` | `5.69e-5` | `7.37e-5` | `-2` | `-2` | `-4` | `-1` | rejected |
| H6 1.5 A | `(1,1,1)` | `4.65e-5` | `1.99e-5` | `-2` | `-2` | `-4` | `-1` | rejected |
| H6 3.0 A | `(1,1,-1)` | `1.76e-5` | `5.17e-5` | `-2` | `0` | `-4` | `-1` | rejected |
| H6 3.0 A | `(1,1,1)` | `1.37e-5` | `5.79e-6` | `-2` | `0` | `-4` | `-1` | rejected |

All H6 attempts remained inside the frozen `1e-4 Ha` energy budget, but
reached the 200-iteration cap and failed the preregistered `1e-8`
stationarity threshold. They are not relabeled as successes.

## Independent checks

- semantic/native circuit fidelity was at least one to floating-point
  precision for all attempts;
- the largest optimizer/native energy disagreement was below `4.0e-15 Ha`;
- the largest analytic/finite-difference gradient spot-check error was below
  `2.5e-9`;
- every NS7 full-circuit resource recount exactly matched the NS5 frozen
  resource result;
- every source snapshot was unchanged;
- no fallback, outcome-informed queue change, FCI threshold, chemical
  accuracy rule, or measurement-cost claim was used.

## Decision and claim boundary

The result is `GO_DEVELOPMENT_PRIMARY_NATIVE` because two H4 transitions pass
all frozen checks and reduce CNOT count, total depth, and parameter count.
It is not a molecule-general or PRA performance result: neither H6 context
passed stationarity, and the frozen BeH2 checkpoint contained no eligible
rank-three MVP block, so unseen validation was not attempted.

The next sequential-search design is therefore reopened only as a bounded
development question. It must not inherit a claim that this transition is
already robust across molecules.
