# V6 S6 bounded exact-rewrite engine

Status: complete deterministic development replay; no optimizer or comparative
performance claim

## Registered rules

The frozen S6 registry contains four rule classes:

1. exact-zero whole-block deletion;
2. identical commuting-block fusion;
3. identical inverse-block cancellation;
4. registered OVP-to-MVP absorption from V5.1.

Every rule has a symbolic theorem record and explicit runtime premises.
Near-zero coefficients are not zero. Repeated multigenerator blocks are fused
only after exact rational-Pauli commutation succeeds. A corridor is eligible
only when every intervening block has disjoint qubit support and its length is
inside the frozen bound.

## Engine safety

For every state, the engine:

- enumerates only rules in a frozen verified registry;
- derives canonical proposal IDs;
- sorts proposals independently of registry/enumerator order;
- validates freshness before application;
- deduplicates canonical target states;
- recounts physical and deterministic-structural full circuits;
- rejects coefficient-dependent counts, circuit-resource regressions, and
  parameter-only changes;
- selects one resource-ordered winner;
- terminates on saturation or an explicit step/state/candidate cap.

An exceeded cap sets `complete: false`. Unsupported rules and unverified
registry entries fail closed.

## H6 1.5 Å development replay

The source is the frozen accepted V4.1 attempt:

| Metric | Source | S6 target | Delta |
|---|---:|---:|---:|
| Parameters | 131 | 129 | -2 |
| Logical blocks | 78 | 76 | -2 |
| CNOT | 858 | 840 | -18 |
| CNOT depth | 300 | 300 | 0 |
| Total depth | 1546 | 1520 | -26 |

The deterministic engine accepted the same two exact OVP-to-MVP absorptions
previously audited in V5.1, one per sequential state. It reached
`SATURATED` with `complete: true`.

Here, `complete` means complete under the frozen greedy,
resource-ordered deterministic policy without hitting a cap. It does not
establish exploration of every rewrite order or a globally optimal exact
normal form:

```text
complete_under_frozen_deterministic_policy: true
global_exact_rewrite_optimum: NOT_ESTABLISHED
```

The complete work trace records:

```text
rewrite states                 3
proposals generated            3
proposals verified             3
proposals accepted             2
proposals rejected             1
full resource recounts         8
energy evaluations             0
statevector evaluations        0
optimizer starts               0
```

The rejected record was an eligible second fusion at step 1 that was not the
canonical winner; it was regenerated and accepted from the next committed
state. Its repeated verification work remains counted.

## Claim boundary

Zero energy evaluations mean the registered rewrites preserve the represented
unitary by construction; they do not mean zero computational work. S6 makes
no claim about paper Measurement Cost, optimizer efficiency, matched-work
superiority, or a new molecular result. The H6 outcome is development replay
of a known V5.1 exact-fusion opportunity through the safer V6 engine.
