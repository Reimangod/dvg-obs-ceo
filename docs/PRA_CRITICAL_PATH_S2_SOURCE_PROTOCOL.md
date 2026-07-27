# PRA critical path S2 source protocol

Decision: `GO_S3`

Two source roles are frozen:

1. `historical_paper_endpoint_source` preserves prior paper-era comparisons.
2. `stationarity_normalized_source` is the byte-identical common source for
   new causal, matched-work, and prospective comparisons.

The roles may refer to the same artifact when the historical checkpoint
already passes the normalized requirements. S1 established this for H6 1.5 Å
and H6 3.0 Å, so neither source is reoptimized.

ADAPT pool-gradient convergence and fixed-ansatz parameter stationarity remain
separate fields. New sources must satisfy parameter-gradient infinity norm
`<= 1e-8`, independent gradient checks, identity checks, and a full resource
recount. Exact/FCI energy and chemical accuracy are unavailable to source
stopping logic.

Common source polishing is shown separately in post-checkpoint comparisons
and included in end-to-end comparisons. It is never silently omitted.

S3 may formalize the normal registry. No new performance run is yet
authorized.
