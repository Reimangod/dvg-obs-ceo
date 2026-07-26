# V6 release provenance correction

Status: closed release-engineering correction; no scientific-result change

The original V6 NS8--NS10 completion tag remains immutable. A Linux CI run
revealed that the diagnostic state-equivalence routine could return
non-finite JSON when two finite, normalized states were exactly orthogonal.
The numerical evidence now uses a deterministic phase and the finite
Euclidean residual in that case.

The defect, affected scope, reproducer, and regression test are recorded in
`docs/incidents/V6_RELEASE_LINUX_ORTHOGONAL_STATE_CI_FAILURE.md`. No NS7--NS10
scientific artifact used the failing path. Energies, gradients, fidelities,
resource counts, decisions, and claim boundaries are unchanged.

Machine-readable provenance is stored in
`artifacts/v6/release/provenance-supplement-v1.json`. It binds the scientific
content commit, original manifest commit and annotated tag, correction commit,
vendored CEO* commit, artifact hashes, and successful GitHub Actions run.

Verification completed:

- 471 local tests passed;
- 471 GitHub Actions tests passed on correction commit `ed01390`;
- isolation, warning-as-error compilation, and the V5 release audit passed;
- GitHub Actions run:
  <https://github.com/Reimangod/dvg-obs-ceo/actions/runs/30189248114>.

This correction supports a portability and reproducibility claim only. It is
not evidence that V6 outperforms CEO*, generalizes across molecular systems,
or meets a PRA performance threshold.
