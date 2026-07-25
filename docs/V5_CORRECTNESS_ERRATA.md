# V5 historical correctness errata

The immutable V4/V4.1/V5/V5.1 result artifacts are preserved. The
machine-readable correction record is
`artifacts/v5/release/correctness-errata-v1.json`.

Three interpretation corrections apply:

1. The multisystem V4/V4.1 and V5 S9 runtime acceptance budgets used an
   exact/FCI-derived chemical-accuracy margin. Those results remain valid
   development observations, but their runtime policy is oracle-assisted and
   is not deployable to a problem with unknown ground-state energy.
2. `summary-v1.json` and `resource-priority-amendment-v1.json` are different
   release policies. The latter changes a post-outcome application choice; it
   does not overwrite the original strict-comparison result.
3. H6 and BeH2 S9 artifacts inherited one LiH-specific claim-boundary sentence.
   Their explicit `case_id` and artifact kind remain authoritative.

Forward execution is FCI-free: only the frozen source-relative algorithmic
energy budget may affect screening, ranking, or acceptance. Chemical accuracy
is an offline reporting audit.
