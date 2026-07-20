# S9: Conservative selector freeze

## Frozen behavior

The selector digest is
`09823d0d82b3029ff7f25eeb2d5e22a6208e4029cdcf6ba28365339cf0a62216`.
It was produced before any DVG-OBS-CEO LiH execution.

A candidate is eligible only when:

- the recycled inverse Hessian passes the S5 quality gate;
- S4 transformation semantics are valid;
- the full candidate circuit was recounted successfully;
- no CNOT, CNOT depth, parameter, logical-block, or total-depth regression occurs;
- at least one resource strictly improves;
- predicted cumulative energy change from the immutable original compression
  checkpoint is at most `1e-4 Ha`.

Eligible candidates are ordered lexicographically by CNOT count reduction,
CNOT-depth reduction, parameter reduction, logical-block reduction, total-depth
reduction, predicted cumulative energy change, and stable candidate ID. One
candidate is attempted per round.

The primary first-accuracy comparison permits one accepted round. A separately
labeled post-hoc greedy ablation permits at most four accepted rounds. Each
round recomputes the Hessian diagnostics, candidate universe, prediction, and
full resources. The energy allowance never resets. A rejected candidate stops
the regime; the selector does not search subsequent candidates after observing
the failed outcome.

Projection-ON is the primary warm start. If its optimizer status is false, one
projection-OFF fallback is allowed, followed by the same independent KKT,
energy, state, constraint, and resource checks. There is no candidate fallback.

## FCI separation

S7.1 removed FCI from runtime evidence and decision APIs. The selector input has
no FCI field. Chemical accuracy is evaluated only after execution and cannot
cause a transaction commit. Cumulative runtime acceptance is anchored to the
original checkpoint energy.

## Calibration replay

Without using actual candidate outcomes as inputs, the frozen selector replayed:

- H2 iteration 1: no eligible candidate;
- H4 first chemical accuracy: no eligible candidate;
- H4 terminal iteration 7: 30 eligible candidates, choosing the preregistered
  lexicographic MVP whole-block deletion.

The terminal choice was independently labeled safe and reduced CNOT by 13,
parameters by 3, total depth by 24, and logical blocks by 1. This offline label
is a replay audit only, not an input to selection.

## LiH interpretation

Selecting no candidate at LiH first accuracy is a valid result and will not
trigger a threshold change. The primary and four-round post-hoc modes are
different experiments and cannot be pooled. S9 freezes behavior; it does not
claim LiH improvement or out-of-sample generalization.
