# V4-S7 v1 incident: lexicographic source-slot order

The first frozen V4-S7 execution completed with `budget-truncated`, 9,994
candidate numerical failures, and no exact VQE attempt. This is not a molecular
null result.

The exact constraint representation canonicalizes source slots
lexicographically. For a 15-parameter LiH ansatz, `ansatz-position:10` sorts
before `ansatz-position:2`. The composition engine then copied the canonical
matrix into a numerical transformation whose columns remained in numeric
ansatz order. This made valid constraints fail `A @ J = 0`. H2/H4 did not expose
the defect because their relevant indices did not cross the two-digit boundary.

The complete v1 bundle is retained unchanged at
`artifacts/v4/s7-lih-development-v1`. It is classified as an infrastructure-
invalid execution and must not be interpreted as V4 performance evidence.

The correction must reorder exact matrix columns explicitly by source-slot ID,
add a dimension-greater-than-ten regression test, use a new protocol tag, and
rerun from the unchanged S6 configuration and unchanged stored checkpoint.
