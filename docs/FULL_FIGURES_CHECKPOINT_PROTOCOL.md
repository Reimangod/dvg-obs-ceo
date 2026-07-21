# Full-figure CEO* checkpoint protocol

Protocol v1.2 preserves the v1.1 scientific algorithm and registered cases.
It changes only result-path governance so multiple long-running cases can be
executed without weakening the clean-code freeze.

- Tracked source and configuration changes remain forbidden during execution.
- Untracked files are permitted only at the exact registered checkpoint and
  progress-ledger paths for the four preregistered cases.
- Every invocation must use its canonical case-specific output path.
- Existing result files remain write-once and cannot be overwritten.
- Each checkpoint records the tagged execution commit, upstream commit/tree,
  package environment, thread controls, and its own content digest.

The H6 1.5 Angstrom result was produced under protocol v1.1. Protocol v1.2 was
introduced after that result solely because the v1.1 clean-tree rule prevented
the next registered case from starting while the prior immutable result was
present. No CEO* setting, molecular case, stopping rule, random seed, resource
counter, or numerical threshold changed.
