# V6 S7 rank-candidate catalog and native recount

Status: complete deterministic development catalog; no energy evaluation

## Frozen parent and executable transition

S7 starts from the complete, saturated S6 H6 1.5 Å target. Its independent
source recount exactly reproduces:

| Metric | S6 target | S7 recount |
|---|---:|---:|
| Parameters | 129 | 129 |
| Logical blocks | 76 | 76 |
| CNOT | 840 | 840 |
| CNOT depth | 300 | 300 |
| Total depth | 1520 | 1520 |

The S6 and S7 wrapper labels differ, but both pin the underlying
`paper-era-qasm-counter-a3f89d0` implementation. This distinction is retained
in the artifact instead of being normalized away.

Only the S5-verified `MVP3 -> SPARSE_UCRY_RANK2` transition is executable.
No rank-2 to rank-1 native transition has passed S1-S5 evidence gates, so S7
does not invent or enumerate that edge.

## Candidate coverage

The saturated S6 parent contains one eligible rank-three MVP block. All three
ordered two-generator subsets are synthesized and recounted:

| Candidates | Parameters Δ | CNOT Δ | CNOT depth Δ | Total depth Δ |
|---:|---:|---:|---:|---:|
| 3 | -1 | +1 | +1 | -2 |

All three pass the S7 requirement of a strict physical gain because total
depth decreases. They are depth/parameter trade-off points, not CNOT or CNOT
depth improvements.

S5 had two eligible rank-three blocks before S6 exact rewriting. The smaller
S7 catalog is therefore a real parent-state change, not a dropped candidate.

## Identity and symmetry handling

Candidate IDs bind:

- the frozen transition-registry digest;
- the S6 source-state digest;
- the exact block locus and ansatz positions;
- the omitted source slot and retained generator digests;
- the native synthesis ID.

Enumeration output is sorted by canonical candidate ID and is invariant to
block and omitted-slot traversal order. Exact duplicate enumeration is
deduplicated and conflicting ID collisions fail closed.

The three candidates share one native-resource orbit. This does **not** prove
Hamiltonian, checkpoint-state, or energy equivalence. They remain three
separate scientific candidates and later receive independent prediction and
optimization records.

## Evidence and claim boundary

Every candidate binds:

- its ordered-subset target-embedding proof;
- the familywise native-synthesis proof;
- arbitrary-context substitution evidence;
- before/after QASM digests;
- the pinned resource counter, native synthesizer, compiler configuration,
  and qubit ordering.

Dropping a nonzero coordinate does not establish source parameter membership
in the lower-rank family. Every S7 candidate is consequently labeled
`APPROXIMATE_RANK_DEMOTION`, with source state equivalence
`NOT_ESTABLISHED` and `FULL_REOPTIMIZATION` required.

S7 performs four full resource recounts and zero energy, gradient, or
optimizer evaluations. It makes no accuracy, matched-work, generalization, or
paper Measurement Cost claim.
