# Paper Fig. 11, 14, and 15 equivalents for V4

These figures use only previously frozen LiH 3 A evidence. No ordinary
GSD-ADAPT, CEO-ADAPT-VQE*, or V4 molecular calculation was rerun.

## Correspondence

- Fig. 11-equivalent: absolute FCI error against ADAPT iteration, parameter
  count, and CNOT count. The original paper compares CEO-, QEB-, and
  qubit-ADAPT. The locally available audited comparators are GSD-ADAPT and
  CEO-ADAPT-VQE*. V4 is one accepted compression point from CEO* iteration 5,
  not an additional ADAPT trajectory.
- Fig. 14-equivalent: absolute FCI error against ADAPT iteration, ansatz CNOT
  count, and ansatz CNOT depth. This matches the three axis definitions in the
  paper caption for the available LiH 3 A system.
- Fig. 15-equivalent: absolute FCI error against parameter count. The paper's
  Measurement Cost trajectory cannot be reproduced from the available
  paper-era code and is deliberately not replaced by optimizer evaluations,
  gradient calls, wall time, or Pauli-kernel counters.

The Fig. 15 panel lists the paper endpoint references GSD 50,468 and CEO* 560
only as cited reference values. V4 remains `N/A` for paper-equivalent
Measurement Cost.

## Scientific boundary

The original figures contain three molecules and, for Fig. 11, QEB/qubit
trajectories. The current output is therefore an axis- and metric-equivalent
LiH 3 A development comparison, not a pixel-level or full-dataset reproduction
of the paper figures.

All plotted GSD and CEO* trajectory points come from the independently audited
S11 comparison. The V4 diamond comes from the accepted S7 transaction and S9
report. FCI is used only to calculate post-result reporting error and was not a
V4 selection or acceptance input.

## Outputs

The directory `output/pdf/v4-paper-equivalent-v1/` contains:

- separate PNG, SVG, and PDF versions of all three figures;
- `paper-fig11-14-15-equivalents.pdf`, a three-page combined PDF;
- `figure-data.csv`, containing every plotted value and evidence status;
- `manifest.json`, containing source and output SHA-256 hashes, source checks,
  and claim boundaries.
