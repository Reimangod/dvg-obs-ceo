# S6 full-circuit paper-era resource evaluator

## Counter definition

S6 reconstructs every ADAPT iteration segment with the pinned pool's native
`get_circuit`, preserves its block and iteration barriers, composes the complete
ansatz, and calls the exact paper-era QASM `cnot_count` and `cnot_depth`
functions. It additionally records Qiskit total depth, native parameter count,
and recovered logical block count. No barrier removal, transpilation, routing,
or global compiler pass is applied.

Candidate deltas are never computed by subtracting a memorized per-operator
cost. The transformed native ansatz is built and the full circuit is recounted.
Iteration history is retained; if pruning removes the only block selected in an
iteration, its empty circuit segment remains in the trajectory.

Two coefficient policies are explicit:

- `physical`: use the actual optimized coefficients;
- `deterministic-structural`: use distinct nonzero values to prevent the
  paper-era MVP helper from dropping canceled Pauli terms during structural
  counting.

The canonical source circuits produced identical snapshots under both policies.
Their QASM digests differ, as expected, because rotation angles differ.

## Exact parity

The evaluator matches the official `AdaptData.acc_cnot_counts`,
`acc_cnot_depths`, and `acc_depths` trajectories exactly on a multisegment
four-qubit DVG ansatz. It also reproduces H2 at 9 CNOTs and CNOT depth 7.

Creating the full official 12-qubit pool exceeded the execution process limit,
so S6 includes a memory-bounded resource-only pool. It reproduces the official
enumeration order and native circuits but exposes no state or energy method.
Validation includes:

- exact known pool sizes/parent ranges at 4 and 10 qubits;
- all 510 ten-qubit operator metadata entries equal to pinned upstream;
- sampled parent/OVP generators equal to pinned upstream;
- canonical LiH resource trajectories equal to S1.

LiH parity is exact:

- CNOT count: `[0, 18, 45, 72, 99, 107]`;
- CNOT depth: `[0, 7, 14, 21, 28, 30]`;
- terminal parameters/blocks: `15/15`;
- independently reported total depth: `171`.

## Structural candidate probe

The registered four-qubit source has 24 CNOTs, CNOT depth 22, total depth 44,
4 parameters, and 3 blocks. Full recount produced:

| Transformation | ΔCNOT | ΔCNOT depth | Δtotal depth | Δparameters | Δblocks |
|---|---:|---:|---:|---:|---:|
| OVP deletion | -9 | -7 | -13 | -1 | -1 |
| MVP whole deletion | -13 | -13 | -24 | -2 | -1 |
| MVP constituent deletion | 0 | -2 | -3 | -1 | 0 |
| MVP to single QE | 0 | -2 | -3 | -1 | 0 |
| MVP to OVP± | -4 | -6 | -11 | -1 | 0 |
| single-QE deletion | -2 | -2 | -7 | -1 | -1 |

This directly demonstrates why deleting an MVP parameter need not reduce CNOT
count: a remaining single double-QE still costs 13 CNOTs. Native MVP-to-OVP is
the tested reparameterization that reduces CNOT, depth, and parameter count
without deleting the whole block.

## Claim boundary

Probe target coordinates are deterministic structural values, not optimized
solutions. The table proves circuit-resource consequences only; it makes no
energy, chemical-accuracy, acceptance-rate, runtime, or measurement-cost claim.
Those require S7-S10.
