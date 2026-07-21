# V4-S5 full-resource Pareto selector

V4-S5 reconstructs complete target ansatz circuits with the pinned paper-era
counter. Resource counting uses deterministic nonzero structural coefficients,
so accidental zero-angle simplification cannot create a false circuit saving.
There is no barrier removal or global transpiler optimization.

Formal eligibility requires predicted cumulative loss at most `1e-4` Hartree,
componentwise nonworse parameter count, CNOT count, CNOT depth, and total depth,
and at least one strict resource improvement. Circuit-primary and
parameter-primary rankings follow the immutable V4-S0 order.

Identical structure digests are executed once, but every semantic constraint ID
is retained as an alias. The representative is selected by predicted loss then
semantic ID; actual energy and FCI energy are forbidden selector inputs.

Because V4-S4 found no eligible H2/H4 state, S5's formal H2/H4 Pareto sets are
expected to be empty. S5 nevertheless recounts the complete tractable catalog
to validate multi-block circuit reconstruction, resource guards, deduplication,
and deterministic selector replay. This is infrastructure evidence, not a
performance claim.
