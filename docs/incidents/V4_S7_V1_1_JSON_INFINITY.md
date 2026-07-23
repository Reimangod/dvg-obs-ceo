# V4-S7 v1.1 incident: non-finite audit serialization

The slot-order-corrected v1.1 execution completed search and two exact
transactions, but the final strict JSON write rejected an internal `Infinity`
sentinel in the diagnostic quality-policy payload. The sentinel represented an
inapplicable held-out residual threshold because held-out evidence was not
required; it was not a molecular numerical result.

The staging directory, including one committed and one rolled-back transaction,
is retained unchanged at
`artifacts/v4/s7-lih-development-v1-1-failed-serialization-staging`. Because no
atomic top-level summary was published, v1.1 is infrastructure-invalid and its
partial outcomes are not the formal V4 result.

The correction serializes this inapplicable threshold as JSON `null`, matching
the frozen S6 manifest. It does not alter search, quality checks, optimization,
acceptance, candidate order, budgets, or thresholds. A new v1.2 tag and clean
rerun are required.
