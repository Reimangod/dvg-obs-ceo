# V5-S10 exact transformation-family gate

S9 established strict V5 improvement only for H6 3.0 Å. LiH and H6 1.5 Å
reached terminal catalogs under the registered single-block family. S10
therefore evaluates one separately versioned V5.1 hypothesis; it does not
silently change V5.

## Candidate

An OVP and an MVP may be fused only when:

- the OVP identifies its parent QEs through registered pool metadata;
- the MVP contains those same parents;
- every intervening block is disjoint in registered orbital support;
- direct qubit-operator commutators independently vanish;
- the OVP generator equals the exact signed sum/difference of its parents.

For OVP coordinate `a`, MVP coordinates `b_i`, and registered signs `s_i`,
the exact old-to-new map is

`b'_i = b_i + s_i a`.

The OVP block is then physically removed. This is a lossless removal of a
redundant parameterization, not magnitude pruning and not generic Qiskit
compilation.

## Fail-closed audit

Every real candidate must independently preserve state fidelity and energy,
reduce both parameter count and physical CNOT count, avoid increases in guarded
depth/block metrics, and agree under physical and deterministic-structural
resource recounts. A candidate inferred from optimized floating coefficients
is forbidden.

Passing S10 only authorizes an S11 V5.1 implementation and ablation. It is not
a performance claim.
