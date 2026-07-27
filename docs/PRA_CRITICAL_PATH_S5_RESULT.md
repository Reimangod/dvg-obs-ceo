# PRA critical path S5 result

Decision: `GO_S6_STRUCTURAL_QUEUES_FROZEN`

S5 generated three stationarity-normalized CEO* development sources under one
frozen protocol. No post-demotion energy, fidelity, optimizer outcome, exact
reference, or Pareto result was used to select a case or transition.

| Case | Source gradient infinity norm | Rank-3 MVP blocks | Native transitions | Primary resource-eligible |
|---|---:|---:|---:|---:|
| H4 1.0 Å | 7.9350e-9 | 2 | 8 | 8 |
| H4 2.0 Å | 5.4416e-9 | 2 | 8 | 8 |
| H5 1.5 Å | 8.1571e-9 | 2 | 8 | 8 |

Every source passes the frozen `1e-8` source-parameter stationarity threshold
and an independent source-energy consistency check. Each has two rank-3
MVP-CEO blocks. Four previously familywise-certified native target families
per block give eight structural transitions, all of which satisfy the frozen
componentwise primary-resource gate before any candidate optimization.

The upstream molecule factories compute FCI as a side effect. S5 neither reads
nor stores that value and excludes it from all selection logic. This fact is
explicit in every source artifact instead of being hidden.

## Frozen order

S6 development execution order is:

1. H4 1.0 Å;
2. H4 2.0 Å;
3. H5 1.5 Å.

The prospective molecule fallback order is H7 and then H3, each at 1.5 Å and
3.0 Å. S8 may choose only the first molecule for which both geometries pass
the frozen feasibility, source-generation, and structural-applicability
requirements. Every screened-out molecule and reason must remain public.

This defines a conditional applicability population. Future claims must report
its screen-out rate and cannot be generalized to arbitrary molecules.
