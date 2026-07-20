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
- S1 baseline parity: complete
- S2 telemetry and scientific identity: complete
- S3 constrained OBS mathematical kernel: complete
- S4 DVG block and candidate catalog: complete
- S5 evaluation-neutral Hessian capture: complete
- S6 paper-era full-circuit resource recount: complete
- S7 fail-closed transaction and rollback: complete
- S8 primary H2/H4 predictor calibration: complete; zero positive safe labels
- S8.1 later-checkpoint positive-class calibration: complete; S9 gate passed
- S9 conservative selector freeze: complete and immutable before LiH
- S10 paired LiH execution: next
