# ADR-0002: Remove FCI from runtime acceptance

Status: accepted correction before S9 selector freeze  
Date: 2026-07-20

## Context

The preregistration states that FCI energy is evaluation-only and must not be
used by runtime pruning acceptance. S7 v1 nevertheless included
`fci_energy_hartree` and a chemical-accuracy check in `evaluate_acceptance`.
It also compared each candidate to the immediately preceding runtime energy.
Repeated accepted rounds could therefore each spend the full local budget and
silently exceed the total registered loss allowance.

S7's crash recovery and artifact durability tests remain valid, but its v1
acceptance semantics are not permitted for S9 or later molecular execution.

## Decision

Version 2 makes the runtime boundary explicit:

- `AcceptanceEvidence` has no FCI field.
- The runtime decision contains no chemical-accuracy check.
- FCI and chemical accuracy are computed only in offline result labeling.
- Every runtime stores an immutable `budget_reference_energy_hartree` copied
  from the original compression checkpoint.
- Acceptance checks candidate energy against that immutable reference, not the
  previous compression round.
- A decision is bound independently to source energy, candidate energy, budget
  reference, parameter counts, and before/after circuit structure digests.

The cumulative inequality is

`E_candidate - E_budget_reference <= 1e-4 Ha`.

## Consequences

Sequential compression cannot reset its energy budget. Runtime acceptance can
be executed without knowing FCI. Chemical-accuracy preservation is still
reported after the run for scientific evaluation, but cannot influence a
commit. Historical S7 v1 artifacts are retained unchanged and labeled as
superseded acceptance semantics rather than deleted.
