# V6 S4 mathematical evidence kernels

Status: mathematical infrastructure; no molecular performance result and no
executable rank transition

## Outcome

S4 separates three statements that older exploratory code could accidentally
blend:

1. a target family is embedded in a source family;
2. the current source point belongs to that target family;
3. a native circuit implements the target at a stated scope.

None implies either of the others.

## Exact affine membership

`ParameterMapIR` affine ranks are recomputed with exact
`fractions.Fraction` arithmetic. Source membership solves

```text
theta + winding * period = offset + jacobian * phi
```

exactly. A periodic map requires an explicit integer winding witness. V6 does
not search a bounded winding range and mislabel failure to find a witness as
mathematical nonmembership. Noninjective maps return one canonical witness
with free coordinates fixed to zero and record `unique: false`.

## Algebraic generator evidence

Family-level generator relations and pairwise commutation are checked in exact
rational Pauli algebra. The relation kernel proves

```text
target_generators = source_generators * jacobian
```

for zero-offset affine maps. Wrong sign, support, ordering, coefficient, or
commutation fails closed.

The relation becomes `TARGET_EMBEDDING` evidence. Pairwise commutation is a
separate `AlgebraicProofRecord`; it is deliberately **not**
`CONTEXTUAL_REWRITE` evidence. Commutation alone does not authorize an
arbitrary-context rewrite.

## Numerical validators

Unitary and state comparisons:

- validate finite arrays and dimensions;
- require unitary matrices and a normalized reference state;
- align a global phase;
- record the residual and tolerance;
- always emit `NUMERICALLY_VALIDATED` pointwise evidence.

A state result is bound to its explicit reference-state ID and checkpoint
context. Reusing local or checkpoint evidence in a broader context fails.

Finite circuit samples cannot create familywise native-synthesis evidence.
Familywise scope requires algebraic or symbolic proof; pointwise numerical
native evidence requires an explicit positive tolerance.

## Claim boundary

S4 establishes proof machinery, not the existence of a useful V6 transition.
It does not show:

- a native rank-2 CEO circuit exists;
- a circuit resource is reduced;
- an energy or accuracy budget is satisfied;
- V6 outperforms CEO*, V4.1, V5, or V5.1.

Those questions begin at the S5 feasibility gate.
