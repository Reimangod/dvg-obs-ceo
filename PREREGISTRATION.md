# DVG-OBS-CEO preregistration

Version: 0.1.0  
Registered: 2026-07-20  
Scope: exact-statevector, noiseless research development

## Research question

Can inverse-Hessian information already produced by Hessian recycling safely
identify DVG_CEO structural transformations that Pareto-improve the circuit at
matched energy accuracy?

## Canonical causal baseline

- Official upstream repository: `mafaldaramoa/ceo-adapt-vqe`
- Commit: `a3f89d03e6a03c89767d3cf8ee7657a57653dda0`
- Pool: `DVG_CEO`
- TETRIS: enabled
- Hessian recycling: enabled
- Primary checkpoint: first strict crossing below 1 kcal/mol FCI error
- No noise and no finite shots

## Primary evaluation

The proposal starts from an exact clone of the canonical CEO* checkpoint.
Acceptance requires chemical accuracy, finite and independently verified
energy, KKT/projected-gradient validity, and a strict improvement in at least
one primary resource without regression in another primary resource.

Primary resources are CNOT depth, CNOT count, parameter count, and logical CEO
block count. Full-ansatz resources are recounted using the same paper-era
circuit semantics; arbitrary global Qiskit compilation is excluded.

## Development and validation status

H2, H4, and LiH have all been observed in earlier exploratory work and are not
blind holdouts. H2/H4 may be used for low-cost method calibration. LiH is a
non-blind paired benchmark. A later generalization claim requires a separately
frozen, previously unopened molecular holdout.

## Required ablations

No pruning; magnitude; magnitude plus ansatz position; diagonal-Hessian
saliency; single-coordinate OBS; general-constraint OBS; projection off/on;
and exact-Hessian oracle for small systems.

## Forbidden practices

- No legacy V2 imports, copied source, schemas, thresholds, or result IDs.
- No tuning to reproduce 107 CNOT, depth 30, or 15 parameters.
- No threshold changes after inspecting a validation result without creating a
  new protocol and rerunning every affected comparison.
- No use of FCI energy in runtime pruning acceptance.
- No calling statevector kernel counts or `nfev+ngev` paper measurement cost.
- No hiding rejected attempts, retries, optimizer failures, or compression work.

## Claim ladder

Analytic correctness, implementation correctness, molecular calibration,
superiority to pruning baselines, CEO* circuit improvement, and total-work
improvement are distinct claims. Passing one does not imply the next.

