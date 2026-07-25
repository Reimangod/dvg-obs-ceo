# V6 S0 parent freeze and claim audit

Status: completed locally on 2026-07-26  
Parent: `6e0984c5e8b779c060b4be9936555d761bdaebd8`  
Annotated tag: `stable-v5-correctness-audit-v1`  
V6 branch: `v6-certified-rank-adaptive`

## Outcome

The audited V5/V5.1 parent was frozen before V6 implementation. The tag
records the parent commit, submodule, CI run, test count, artifact inventory
digest, and scientific claim boundary.

The parent passed:

- 351 local tests under Python 3.10.19;
- the independent V5/V5.1 release audit;
- GitHub Actions run `30157575752`;
- submodule verification at
  `a3f89d03e6a03c89767d3cf8ee7657a57653dda0`;
- deterministic tracked-artifact inventory SHA-256
  `39966839954c779a8bc1c5a270c8fa96af8b45a642e72d84815fc40ecc65a25e`.

The repository was observed as public. Publication visibility is repository
wide and is not interpreted as scientific release readiness.

## Environment finding

The host system Python was 3.14.2, while the project contract is Python
3.10.x and CI uses Python 3.10.19. The V6 preflight therefore requires the
locked Python 3.10.19 environment and rejects the system Python.

The host thread variables were initially unset. All scientific checks were
rerun with:

```text
OMP_NUM_THREADS=1
OPENBLAS_NUM_THREADS=1
MKL_NUM_THREADS=1
VECLIB_MAXIMUM_THREADS=1
NUMEXPR_NUM_THREADS=1
```

The preflight rejects an unset or different thread configuration. This is an
environment-control correction, not a change to historical numerical results.

`uv sync` emitted warnings while scanning obsolete setuptools distributions.
The locked environment still built successfully, and all 351 tests passed.
The warnings are retained as an environment observation and are not described
as a scientific-code failure.

## Primary-source claim audit

The CEO paper was checked in both HTML and the supplied PDF.

Verified claims:

- a double qubit-excitation circuit uses 13 CNOTs;
- an MVP-CEO containing up to three QEs uses the same 13-CNOT construction;
- OVP-CEO circuits have CNOT count 9 and CNOT depth 7;
- the corresponding double-QE values are CNOT count 13 and CNOT depth 11;
- the paper's Measurement Cost is not adopted as the V6 computational-work
  ledger.

The ExcitationSolve paper was checked for the statement that the method applies
to generators satisfying \(G^3=G\), including the paper's registered
two-excitation OVP-CEO construction. V6 does not generalize this claim to
arbitrary MVP or fused generators without an operator-family proof.

APS policy was checked for:

- PRA scope and significant-contribution criteria;
- mandatory Data Availability information;
- the requirement to retain information needed to verify reported results;
- the impropriety of omitting data because it conflicts with the desired
  conclusion;
- disclosure of substantive AI use in research, including materially
  influential code generation or debugging.

## Scientific boundary

The frozen parent supports audited, exact-statevector, noiseless,
post-checkpoint development claims only. It does not establish:

- unseen validation;
- universal or global superiority;
- paper Measurement Cost reduction;
- noisy-backend or hardware advantage.

FCI/reference energy remains offline reporting information and is prohibited
from V6 runtime ranking, selection, optimization, and acceptance.

## New preflight

`dvg_obs_ceo.v6_rank_adaptive.s0_preflight` verifies:

- the parent tag is annotated and points to the expected commit;
- the pinned CEO submodule commit;
- the parent tracked-artifact inventory;
- `uv.lock`, `pyproject.toml`, CI workflow, and `.gitmodules` digests;
- Python 3.10.19;
- all five single-thread environment variables;
- clean worktree;
- the independent V5/V5.1 release audit.

Every mismatch fails closed. The manifest is
`manifests/v6-s0-parent-freeze-v1.json`.

## S0 completion decision

S0 is complete locally when:

1. the new tests pass;
2. the full historical suite still passes;
3. the V6 files are committed;
4. the clean-tree preflight passes from that commit.

No V6 performance calculation was performed in S0.
