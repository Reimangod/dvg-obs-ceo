# S11 LiH 3 Å direct comparison

## Outcome

The pinned ordinary GSD-ADAPT run reached strict chemical accuracy at ADAPT
iteration 6 and independently reproduced the paper's first-accuracy circuit
resources: 392 CNOTs and CNOT depth 384. The source audit passed all 17 checks.

| Series | Evidence status | Iter. | Error (Ha) | Parameters | CNOT | CNOT depth | Total depth |
|---|---|---:|---:|---:|---:|---:|---:|
| GSD-ADAPT | direct, accepted | 6 | 0.0006843315 | 6 | 392 | 384 | 500 |
| CEO* | direct, accepted | 5 | 0.0009334770 | 15 | 107 | 30 | 171 |
| V2 primary | direct, accepted after rollback | 5 | 0.0009334770 | 15 | 107 | 30 | 171 |
| V2 candidate | rejected counterfactual (KKT) | 5 | 0.0009334770 | 14 | 98 | 30 | 158 |

At the common first-chemical-accuracy endpoint, the directly reproduced CEO*
uses 72.7% fewer CNOTs, 92.2% less CNOT depth, and 65.8% less total depth than
the directly reproduced GSD comparator. CEO* uses more scalar parameters (15
versus 6), because parameter count and entangling-gate cost are not equivalent
for these different pools.

The official V2 result does **not** improve over CEO*: its selected compression
was rejected by the preregistered KKT gate and the transaction restored the
checkpoint exactly. The rejected candidate would have changed CEO* from
107/30/171 CNOT/CNOT-depth/total-depth and 15 parameters to 98/30/158 and 14
parameters. Its independently recomputed energy increase was only
`3.7792e-12` Ha, but it is counterfactual diagnostic evidence, not an accepted
performance result.

## Reproduction and fairness

- GSD-ADAPT and CEO* use the pinned official upstream commit
  `a3f89d03e6a03c89767d3cf8ee7657a57653dda0`, LiH at 3 Å, STO-3G,
  Jordan-Wigner, noiseless exact simulation, and the same upstream chemical
  accuracy constant (`0.0015936` Ha).
- GSD uses the paper's original-protocol contrast: GSD pool, one gradient-
  selected operator per iteration, no TETRIS, no Hessian recycling, and no OGM.
- CEO* uses DVG-CEO, TETRIS, OGM, and Hessian recycling. Therefore GSD versus
  CEO* is an algorithm-level comparison, not an ablation that isolates one
  enhancement.
- CEO* versus V2 is the paired causal comparison: both branches originate from
  the same iteration-5 checkpoint.
- The numerical process was fixed to one OMP/OpenBLAS/MKL thread before startup.
  This prevents near-degenerate gradient ordering from changing with BLAS
  scheduling.

## Work and measurement boundary

The direct GSD run recorded 51 optimizer energy evaluations, 211 gradient-
component equivalents, and 31.27 seconds. The CEO* checkpoint recorded 166,
1580, and 94.08 seconds. These values are implementation work counters from
different algorithmic paths and instrumented runs. They are not the paper's
Measurement Cost and the wall times are not used as a speedup claim.

The paper values GSD 50,468 and CEO* 560 are retained as cited references only.
The pinned code does not expose enough of the paper-era measurement-accounting
implementation to reproduce that definition. Accordingly the measurement-cost
panel is explicitly refused rather than filled with non-equivalent counters.
CEO* per-iteration work/time was not recorded in the canonical artifact and is
not inferred.

## Artifacts

- Direct GSD evidence: `artifacts/s11/gsd-lih-3a-first-accuracy-v1/`
- Audited comparison: `artifacts/s11/lih-3a-direct-comparison-v1-1/`
- Machine-readable table: `final-comparison.csv`
- Fig. 14-style plot: `fig14_style.svg` and `fig14_style.png`
- Fig. 15-style plot with measurement refusal: `fig15_style.svg` and
  `fig15_style.png`
- Source hashes and checks: `source-audit.json`

The v1 plot draft was rejected during visual QA because its title and legend
overlapped. Protocol v1.1 changes layout only; scientific inputs, checks, and
numeric outputs are unchanged.
