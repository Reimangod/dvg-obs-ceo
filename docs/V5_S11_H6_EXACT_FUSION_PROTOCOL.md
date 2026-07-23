# V5.1-S11 H6 exact-fusion protocol

S11 applies both S10-certified fusion candidates jointly to the immutable
V4.1 H6 1.5 Å minimum-CNOT comparison point. The source point, candidate IDs,
code, thresholds, and all input hashes are frozen before execution.

The joint map is evaluated without optimization. Therefore any energy change
is numerical error or a failed semantic assumption, not an optimizer effect.
The run fails closed unless:

- both candidates remain present with identical symbolic and numeric context;
- generator identities and all required commutators pass;
- independently generated state and energy agree;
- physical and deterministic-structural resource counts agree;
- CNOT and parameter counts decrease and no guarded depth/block metric rises.

The source V4.1 artifact is not modified. The output is a new V5.1 artifact.
The S9 V5 point is bound only for transparent comparison; it is not used to
select or tune the fusion.
