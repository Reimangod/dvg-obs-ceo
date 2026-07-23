# V5-S9 frozen development result

All three new S9 cases and the LiH calibration carry-forward passed independent
audits. The multisystem audits contain 25 checks per case and independently
recompute every attempted branch, including rejected branches.

## Strict result

| Case | Strict success | V4.1 comparison point | V5 comparison point | Decision |
|---|---|---|---|---|
| LiH 3.0 Å | No | 58 CNOT, 8 parameters, ΔE 8.690e-5 | identical | V4.1-equivalent |
| H6 1.5 Å | No | 858 CNOT, 131 parameters, ΔE 8.821e-5 | 858 CNOT, 132 parameters, ΔE 8.464e-5 | V4.1 |
| H6 3.0 Å | **Yes** | 768 CNOT, 144 parameters, ΔE 7.134e-5 | 758 CNOT, 142 parameters, ΔE 6.915e-5 | V5 |
| BeH2 3.0 Å | No | 239 CNOT, 33 parameters, ΔE 9.662e-5 | 221 CNOT, 31 parameters, ΔE 9.852e-5 | V4.1 |

The H6 3.0 Å V5 point has a smaller actual energy increase and improves every
guarded circuit resource:

- CNOT: 768 to 758;
- parameters: 144 to 142;
- total depth: 1455 to 1426;
- CNOT depth: 293 to 283;
- logical blocks: 94 to 93.

The raw minimum-CNOT H6 3.0 Å point reaches 741 CNOT and 138 parameters, but
its energy increase is larger than the matched V4.1 comparison point.
Therefore the conservative 758-CNOT point is the release comparison point.

BeH2 has a large circuit reduction relative to its V4.1 minimum-CNOT point,
but its energy increase is 1.9033e-6 Ha larger. The preregistered
same-or-lower-energy condition is not relaxed, so it is not counted as strict
success.

## Gate decision

Primary success is observed in one of four development cases. Strong
development success required at least two cases including one H6 case and is
not met. Global V5 superiority is therefore not established.

The non-regression release policy selects V4.1 except for the audited H6
3.0 Å strict-success point. S10 may open a separately versioned V5.1
transformation-family study because the current family is safe but reaches
known structural endpoints on LiH and H6 1.5 Å.

All results remain development-only. Paper Measurement Cost is undefined.
