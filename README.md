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
- S10 paired LiH execution: complete (promising candidate rejected by frozen KKT gate and fully rolled back)
- S11 direct normal ADAPT / CEO* / V2 comparison: complete; GSD paper CNOT/depth parity reproduced, V2 primary unchanged after rollback
- S12 exact OGM-aware term reuse: calibrated; correct but not adopted by default (LiH fresh exact-Pauli kernels reduced only 0.07125%)
- V3 bounded stationarity certification: closed at H2/H4 calibration; no LiH run and no threshold relaxation
- V4 S0-S7 Global OBS: complete; one LiH development candidate accepted with 15 to 8 parameters, 107 to 58 CNOTs, and total depth 171 to 92
- V4 S8 validation: deliberately deferred, not passed; no unseen matched CEO* checkpoint is available in the approved scope
- V4 S9 reporting: complete with source-hashed CSV, JSON, figures, and explicit negative results
- V4 S10 local release gate: passed (162 tests; evidence, tags, submodule, rollback, staging, and raw-artifact checks all passed)
- Paper Fig. 11/14/15 equivalents: generated for LiH 3 A from frozen GSD/CEO*/V4 evidence; Measurement Cost remains explicitly unavailable for V4
- V5 S0-S9 risk-aware sequential compression: complete and independently
  audited; strict improvement occurred on H6 3.0 A only, so core-V5 strong
  development success was not met
- V5.1 S10 exact transformation gate: complete; two registered
  cross-iteration OVP-to-MVP fusions were certified on H6 1.5 A and no
  candidate existed on LiH 3.0 A, H6 3.0 A, or BeH2 3.0 A
- V5.1 S11: complete; the H6 1.5 A V4.1 point was reduced losslessly from
  858 to 840 CNOTs, 131 to 129 parameters, and total depth 1546 to 1520
- V5.1 S11b: complete as outcome-informed exploratory integration; the
  lower-energy S9 point was reduced losslessly to 840 CNOTs and 130 parameters
- V5/V5.1 S12 release audit: passed (337 tests before final release assembly);
  see [`docs/V5_V5_1_RELEASE_RESULT.md`](docs/V5_V5_1_RELEASE_RESULT.md)

The V4, V5, and V5.1 outcomes are **development results**, not blind
validation or a general superiority claim. V5.1 meets the two-case strong
development threshold only when the explicitly outcome-informed H6 1.5 A
extension is included. Paper-equivalent Measurement Cost remains unavailable.
