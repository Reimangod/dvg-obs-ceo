# V6 S3 differential replay

Status: implementation and static replay step; no new performance result

## Purpose

S3 normalizes V4.1, V5, and V5.1 historical evidence without rewriting it or
pretending that fields absent from old artifacts were originally recorded.

Every replay record stores:

```text
original_artifact_digest
normalized_ir_digest
reconstructible_fields
unavailable_fields
derived_fields
replay_strength
```

The two digests have different meanings and are not expected to match.

## Replay levels

| Level | Name | Meaning |
|---:|---|---|
| L0 | `ARTIFACT_ONLY` | original bytes verified |
| L1 | `SEMANTIC_NORMALIZED` | key semantics normalized |
| L2 | `SOURCE_STATE_RECONSTRUCTED` | source ansatz/state/resource evidence available |
| L3 | `CANDIDATE_RANKING_REPLAYED` | catalog and ranking replayed |
| L4 | `DECISION_REPLAYED` | attempts and accept/reject/rollback replayed |
| L5 | `FULL_WORK_REPLAYED` | trajectory and work counters reconciled |

## Conservative classification

- V4.1 H6/BeH2 records are capped at L4 because source checkpoint, frozen
  selection, attempts, rollback, and endpoints are replayed, but their work
  counters are not independently reconstructed from a lower-level ledger.
- V5 records reach L5 because exact-attempt work, catalog work, aggregate work,
  branch decisions, and trajectory are independently reconciled.
- V5.1 exact-fusion records are capped at L4 because they do not contain the
  complete pre-fusion catalog and ranking.
- V4.1 LiH is capped at L1 because its V4.1 record is a regression-equivalence
  audit rather than a separate V4.1 search trajectory.

## Integrity checks

Historical bytes are compared with the blobs in
`stable-v5-correctness-audit-v1`. Internal result/summary digests are checked
independently. Source checkpoint bytes, ansatz shape, statevector digest
presence, and resource evidence are checked where registered.

V5 work is reconstructed as:

```text
aggregate work = exact branch work + catalog work
```

Accepted branches must pass every stored gate, and rejected branches must have
explicit reasons.

## Limitations

- Old artifacts do not contain complete V6 three-layer identities and proof
  objects.
- Missing fields are not inferred.
- Replay does not convert development data into prospective validation.
- Replay confirms recorded behavior; it does not establish matched-work
  superiority beyond the original claim boundaries.
