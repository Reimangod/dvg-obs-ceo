# V6.1 tangent-mechanism audit: final result

Status: completed negative result; T3--T6 not authorized  
Decision: `NO_GO_MECHANISM_NOT_SEPARATED`

## Result

V6.1 tested whether the conditional projective tangent Gram matrix could
separate already observed successful and failed native rank-two demotions.
The test included both original H4/H6 checkpoints and the changed coordinate
space after H4's first accepted demotion.

| Stage/context | Outcome count | Conditional rho |
|---|---:|---:|
| H4 original | 2 accepted | `2.77e-15`, `6.14e-15` |
| H6 1.5 Å original | 2 rejected | `0.396`, `0.426` |
| H6 3.0 Å original | 2 rejected | `0.642`, `0.685` |
| H4 after first demotion | 3 accepted, 1 rejected | `1.95e-15`--`2.24e-15` |

All five accepted directions satisfied the preregistered `rho <= 1e-8`
condition. However, the rejected second-round H4 direction also had
`rho = 2.11e-15` and unit alignment with the conditional null space. Therefore
not all rejected directions satisfied `rho >= 1e-5`. The separation ratio was
`0.344`, below the frozen minimum of `1000`, and the sensitivity
classification gate failed.

## Interpretation

The metric explains the coarse H4-versus-H6 contrast at the original
checkpoints: the registered H4 normals are conditionally redundant to
numerical precision, while the H6 normals are not. It does **not** explain
which second-round H4 normal will survive energy/stationarity certification.
After the first H4 demotion, both accepted and rejected child directions lie
in the same numerical conditional-null regime.

Consequently, tangent/QFI redundancy is at most a necessary screening signal
for this data; it is not a sufficient selector. The rejected H4 case shows
that nonlinear finite displacement, optimizer behavior, stationarity, and the
transactional energy guard still matter. Building a prospective selector from
this diagnostic would overstate the evidence.

## Stage closure

- T0: complete and preregistered.
- T1: complete; fail-closed mathematical kernel tested.
- T2: complete; negative mechanism-separation result.
- T3/T4: `NOT_AUTHORIZED_BY_T2_GATE`.
- T5/T6 performance execution: `NOT_AUTHORIZED`.
- Final audit/release: complete as a negative result.

No thresholds were changed, no failed record was removed, no FCI energy was
used, and no V6 artifact was overwritten. T2 used 1,532 exact statevector
evaluations in 73.59 seconds under fixed single-thread settings.

## Engineering incidents

Three runner-boundary defects were found before any partial artifact was
written: a Python/JSON boolean literal mismatch and two standard-JSON scalar
boundary issues. They are recorded in
`docs/incidents/V6_1_T2_AUTHORIZATION_LITERAL_FAILURE.md`. Atomic write-new
semantics worked as intended. The corrected run is bound to commit
`9a7215541291002424c89ca193c1715cf1006d7f`.

## Claim boundary

This is retrospective development evidence. It does not establish a
prospective selector, matched-work improvement, molecular generalization,
CEO* superiority, or PRA-level performance. Its positive scientific value is
the falsification of a stronger claim: conditional local tangent redundancy
alone cannot certify successful sequential CEO block demotion.
