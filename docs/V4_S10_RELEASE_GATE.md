# V4-S10 release gate

S10 independently reopens the frozen S7-S9 evidence and fails closed on source
hash, report hash, result arithmetic, submodule, protocol-tag, raw-artifact,
staging, baseline-reexecution, or test-suite discrepancies.

The local audit deliberately does not infer GitHub repository visibility or CI
state from local configuration. Those two remote properties are queried from
GitHub after the local audit artifact is committed and the branch is pushed.

Large raw request ledgers under `artifacts/raw/` remain ignored and are
represented by manifests. Large tracked JSON files in V4 are retained result or
failed-run evidence rather than unreferenced raw ledgers; their presence and
hashes preserve the preregistered failure trail. No history rewriting is used.

Passing S10 certifies repository integrity and the stated development evidence.
It does not turn the deferred V4-S8 validation gate into a pass.
