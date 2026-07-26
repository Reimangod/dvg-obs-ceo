# V6.1 tangent-certified rank-adaptation plan

Status: frozen mechanism study; no selector or performance claim  
Parent release: `v6-ns8-ns10-followup-complete-v1.1`  
Branch: `v6.1-tangent-certified-rank-adaptation`  
Study regime: noiseless exact statevectors; existing development checkpoints  

## Research question and boundary

V6.1 asks whether the success and failure of the already executed native
rank-two demotions can be explained by local variational geometry. It does not
relabel the outcome-aware diagnostic as prospective selection evidence.
QFI/tangent evidence does not replace energy, stationarity, native-synthesis,
or full-circuit resource certification.

The convention is the projective pure-state tangent metric

\[
t_i=(I-|\psi\rangle\langle\psi|)\partial_i|\psi\rangle,\qquad
G_{ij}=\operatorname{Re}\langle t_i|t_j\rangle .
\]

Some literature calls `4G` the QFI. V6.1 stores `G` and states this convention
explicitly. Parameters are real and retain the paper-era generator
normalization and canonical ansatz order. Projection onto compensating
directions is real-linear, implemented by stacking real and imaginary parts.

For a candidate block `b`, V6.1 reports both:

- local block Gram `G_b`, which ignores other ansatz parameters;
- conditional Gram `G_{b|rest}=R_b^T R_b`, where
  `R_b=(I-P_rest)T_b`.

The conditional metric is primary because remaining parameters may compensate
for removal. A local 3-by-3 block metric alone cannot certify redundancy.

## Frozen stages and gates

### T0 — isolation and preregistration

- freeze parent tag, commit, vendored CEO* commit, input hashes, coordinate
  convention, numerical tolerances, work cap, and claim boundary;
- keep all V6 artifacts immutable;
- use only already observed H4 and H6 contexts as development diagnostics;
- prohibit exact/FCI energy from ranking, thresholds, or decisions.

Exit: committed protocol and annotated T0 tag before computing results.

### T1 — mathematical and engineering kernel

- deterministic central finite-difference projective tangents;
- finite normalized states only;
- real-linear least-squares conditioning with explicit rank tolerance;
- symmetric finite Gram matrices, ordered eigensystems, Rayleigh scores, and
  principal alignment with the numerical null space;
- analytic toy-state, reparameterization, orthogonal-state, rank-deficient,
  determinism, and fail-closed tests.

Primary finite-difference step: `1e-6`. Block-column sensitivity steps:
`5e-7` and `2e-6`. SVD relative cutoff: `1e-10`.

### T2 — outcome-aware mechanism diagnostic

Fixed records:

- original H4 late checkpoint rank-two attempts;
- H4 second-round attempts evaluated in their constrained parent coordinate
  space;
- H6 1.5 Å and 3.0 Å failed rank-two attempts.

For every recorded normal `n`, report

\[
\rho(n)=\frac{n^T G_{b|rest}n}
{\|n\|^2\max(\lambda_{\max}(G_{b|rest}),\epsilon)}.
\]

Also report local/conditional spectra, numerical ranks, null-space alignment,
finite-difference sensitivity, state and input digests, and work counts.

The preregistered Go gate is intentionally strict:

1. all values are finite and sensitivity classifications are stable;
2. every previously accepted direction has `rho <= 1e-8`;
3. every previously rejected direction has `rho >= 1e-5`;
4. `min(rejected rho) / max(accepted rho) >= 1000`.

Any violation is `NO_GO_MECHANISM_NOT_SEPARATED`. This threshold is not tuned
after outcomes. Passing establishes only a development-set mechanism signal.

### T3 — prospective selector protocol (conditional on T2 Go)

Freeze a selector, tie rules, budgets, calibration-independent thresholds,
failure behavior, and untouched evaluation contexts. No computation starts
before the T3 tag.

### T4 — prospective selector validation

Compare the frozen selector with exhaustive registered candidate evaluation
under matched work. A Go requires no false rejection of a certified
nondominated move, reduced attempted optimization work, and no integrity
failure. Otherwise stop.

### T5 — sequential compression (conditional on T4 Go)

Run transactional sequential compression with complete rollback. Energy,
stationarity, state semantics, native synthesis, and full-circuit recount
remain mandatory.

### T6 — final audit and release

Publish immutable manifests, hashes, environment, work ledgers, accepted and
rejected records, negative results, and the narrowest supported claim. A
No-Go at T2 or T4 is a valid completed V6.1 result; later stages are recorded
as `NOT_AUTHORIZED`, not silently omitted.

## System safety

- atomic write-new artifacts; never overwrite;
- clean committed worktree and single-thread numerical environment for
  outcome-producing runs;
- canonical finite JSON only;
- fail closed on shape, normalization, digest, rank, or coordinate mismatch;
- deterministic sorting and explicit tie rules;
- local full tests and GitHub CI before release;
- original input/output digests and negative results retained.

## Publication boundary

V6.1 T2 can support a mechanistic retrospective statement only. PRA-level
method or performance claims require prospective T3--T5 evidence on
preregistered, independent conditions and matched computational work. If the
gate stops the study, the publishable result is a transparent negative
mechanism test and the verified boundary of tangent-based certification.
