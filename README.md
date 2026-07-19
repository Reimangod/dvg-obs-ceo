# DVG-OBS-CEO

Independent research implementation of inverse-Hessian-guided structural
compression for the paper-era DVG_CEO implementation of CEO-ADAPT-VQE*.

## Scientific boundary

This repository is a clean implementation. It does not import or copy the
legacy `v2-implementation` extension. The legacy results are exploratory
evidence only and are not validation data for this project.

The unmodified upstream implementation is pinned as a Git submodule at commit
`a3f89d03e6a03c89767d3cf8ee7657a57653dda0`. All modifications live outside
`vendor/ceo-adapt-vqe`.

No performance claim is permitted until the stage gates in
[`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) and
[`PREREGISTRATION.md`](PREREGISTRATION.md) pass.

## Current status

- S0 repository isolation: complete
- S1 baseline parity: not started
- Molecular compression experiments: forbidden until S3 and S7 gates pass
