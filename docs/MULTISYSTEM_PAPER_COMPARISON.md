# Multisystem paper comparison

This bundle compares the frozen local CEO-ADAPT-VQE* checkpoints with
Ramôa et al., *Reducing the resources required by ADAPT-VQE using coupled
exchange operators and improved subroutines* (2025), DOI
`10.1038/s41534-025-01039-4`.

## Direct comparison

Only linear H6 at 1.5 A matches the paper's CEO-ADAPT-VQE* algorithm,
molecule, distance, noiseless setting, and first-chemical-accuracy objective.
Paper Table 1 reports CNOT count 812 and CNOT depth 282. The frozen local
rerun reports 879 and 306. Measurement Cost remains unavailable locally and
is not replaced with optimizer calls, gradient components, or wall time.

## Figure boundaries

- The H6 3 A and BeH2 3 A plots use the same axes and molecular geometries as
  paper Fig. 11. The paper curves use non-star CEO-ADAPT-VQE and terminate by
  the energy-change rule; the local curves use CEO-ADAPT-VQE* and stop at the
  first strict chemical-accuracy checkpoint. They are not direct performance
  reproductions.
- Paper Figs. 14 and 15 use CEO-ADAPT-VQE*, but use H6 at 1.5 A and BeH2 at
  2 A. Only the stored H6 1.5 A case is directly aligned.
- The local runs are noiseless exact-statevector simulations.

The generator fails closed on checkpoint digest mismatch, progress-ledger
mismatch, non-first-accuracy checkpoints, a dirty worktree, or an untagged
protocol revision.
