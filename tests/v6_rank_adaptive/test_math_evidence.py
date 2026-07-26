from fractions import Fraction
from types import MappingProxyType

import numpy as np
import pytest

from dvg_obs_ceo.v6_rank_adaptive.architecture_state import (
    ArchitectureStateError,
    ParameterMapIR,
    ParameterMapRepresentation,
)
from dvg_obs_ceo.v6_rank_adaptive.evidence import (
    ContextScope,
    EvidenceError,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    NativeSynthesisScope,
    SemanticScope,
)
from dvg_obs_ceo.v6_rank_adaptive.math_evidence import (
    ExactPauliOperator,
    MathematicalEvidenceError,
    native_synthesis_evidence,
    parameter_membership_evidence,
    prove_generator_relation_and_commutation,
    require_context_scope,
    source_parameter_membership,
    validate_pointwise_state,
    validate_pointwise_unitary,
)


SOURCE = "source:mvp"
TARGET = "target:rank-reduced"


def affine_map(
    *,
    source_dimension=2,
    target_dimension=1,
    offset=("0", "0"),
    jacobian=(("1",), ("1",)),
    representation=ParameterMapRepresentation.AFFINE_EXACT,
    periodicity=None,
    declared_rank=1,
):
    return ParameterMapIR(
        representation=representation,
        source_dimension=source_dimension,
        target_dimension=target_dimension,
        offset=offset,
        jacobian=jacobian,
        periodicity=periodicity,
        analytic_map_id=None,
        declared_rank=declared_rank,
    )


def pauli(word, real=0, imag=1):
    return ExactPauliOperator.create({tuple(word): (real, imag)})


def test_exact_affine_membership_and_nonmembership_are_independent_evidence():
    parameter_map = affine_map()
    member = parameter_membership_evidence(
        parameter_map,
        ("1/3", "1/3"),
        source_semantic_id=SOURCE,
        target_semantic_id=TARGET,
    )
    nonmember = parameter_membership_evidence(
        parameter_map,
        ("1/3", "1/2"),
        source_semantic_id=SOURCE,
        target_semantic_id=TARGET,
    )
    assert member.status is EvidenceStatus.PASSED
    assert member.semantic_scope is SemanticScope.PARAMETER_MAP
    assert member.details["target_coordinates"] == ("1/3",)
    assert nonmember.status is EvidenceStatus.FAILED


def test_periodic_membership_requires_and_checks_explicit_winding_witness():
    fixed_zero = affine_map(
        source_dimension=1,
        target_dimension=0,
        offset=("0",),
        jacobian=((),),
        representation=ParameterMapRepresentation.PERIODIC_AFFINE_EXACT,
        periodicity=("2",),
        declared_rank=0,
    )
    with pytest.raises(MathematicalEvidenceError, match="winding witness"):
        source_parameter_membership(fixed_zero, ("2",))
    equivalent = source_parameter_membership(
        fixed_zero,
        ("2",),
        periodic_windings=(-1,),
    )
    wrong = source_parameter_membership(
        fixed_zero,
        ("2",),
        periodic_windings=(0,),
    )
    assert equivalent.member is True
    assert wrong.member is False


def test_noninjective_affine_map_reports_nonunique_witness():
    noninjective = affine_map(
        source_dimension=1,
        target_dimension=2,
        offset=("0",),
        jacobian=(("1", "1"),),
        declared_rank=1,
    )
    result = source_parameter_membership(noninjective, ("3",))
    assert result.member is True
    assert result.unique is False
    assert tuple(Fraction(value) for value in result.target_coordinates) == (
        Fraction(3),
        Fraction(0),
    )


def test_declared_affine_rank_is_verified_exactly():
    with pytest.raises(ArchitectureStateError, match="declared rank"):
        affine_map(declared_rank=0)


def test_exact_generator_relation_and_commutation_produce_algebraic_records():
    z0 = pauli(((0, "Z"),))
    z1 = pauli(((1, "Z"),))
    target = z0 + z1
    relation, commutation = prove_generator_relation_and_commutation(
        affine_map(),
        (z0, z1),
        (target,),
        source_semantic_id=SOURCE,
        target_semantic_id=TARGET,
    )
    assert relation.evidence_type is EvidenceType.TARGET_EMBEDDING
    assert relation.strength is EvidenceStrength.ALGEBRAICALLY_PROVEN
    assert relation.semantic_scope is SemanticScope.FAMILYWISE_UNITARY
    assert commutation.proof_type == "PAIRWISE_SOURCE_GENERATOR_COMMUTATION"
    assert commutation.proof_id.startswith("v6-proof-v1:")
    assert isinstance(commutation.details, MappingProxyType)
    with pytest.raises(TypeError):
        commutation.details["pair_count"] = 99


@pytest.mark.parametrize(
    "sources,target",
    [
        (
            (pauli(((0, "Z"),)), pauli(((1, "Z"),))),
            pauli(((0, "Z"),)) + pauli(((1, "Z"),), imag=-1),
        ),
        (
            (pauli(((0, "Z"),)), pauli(((1, "Z"),))),
            pauli(((0, "Z"),)) + pauli(((2, "Z"),)),
        ),
        (
            (pauli(((0, "Z"),)), pauli(((1, "Z"),))),
            pauli(((1, "Z"),)) + pauli(((0, "Z"),), imag=2),
        ),
    ],
)
def test_wrong_sign_support_and_target_order_fail_exact_relation(
    sources,
    target,
):
    with pytest.raises(MathematicalEvidenceError, match="relation mismatch"):
        prove_generator_relation_and_commutation(
            affine_map(),
            sources,
            (target,),
            source_semantic_id=SOURCE,
            target_semantic_id=TARGET,
        )


def test_wrong_target_order_fails_exact_relation():
    z0 = pauli(((0, "Z"),))
    z1 = pauli(((1, "Z"),))
    identity_map = affine_map(
        source_dimension=2,
        target_dimension=2,
        offset=("0", "0"),
        jacobian=(("1", "0"), ("0", "1")),
        declared_rank=2,
    )
    with pytest.raises(MathematicalEvidenceError, match="relation mismatch"):
        prove_generator_relation_and_commutation(
            identity_map,
            (z0, z1),
            (z1, z0),
            source_semantic_id=SOURCE,
            target_semantic_id=TARGET,
        )


def test_noncommuting_generators_fail_before_familywise_claim():
    x = pauli(((0, "X"),))
    z = pauli(((0, "Z"),))
    with pytest.raises(MathematicalEvidenceError, match="do not commute"):
        prove_generator_relation_and_commutation(
            affine_map(),
            (x, z),
            (x + z,),
            source_semantic_id=SOURCE,
            target_semantic_id=TARGET,
        )


def test_global_phase_unitary_equivalence_is_only_numerical_and_pointwise():
    source = np.eye(2, dtype=complex)
    target = np.exp(0.37j) * source
    evidence = validate_pointwise_unitary(
        source,
        target,
        source_semantic_id=SOURCE,
        target_semantic_id=TARGET,
    )
    assert evidence.status is EvidenceStatus.PASSED
    assert evidence.strength is EvidenceStrength.NUMERICALLY_VALIDATED
    assert evidence.semantic_scope is SemanticScope.POINTWISE_UNITARY


def test_state_equivalence_is_bound_to_the_recorded_reference():
    identity = np.eye(2, dtype=complex)
    z = np.diag([1, -1]).astype(complex)
    zero = np.array([1, 0], dtype=complex)
    plus = np.array([1, 1], dtype=complex) / np.sqrt(2)
    accepted = validate_pointwise_state(
        identity,
        z,
        zero,
        source_semantic_id=SOURCE,
        target_semantic_id=TARGET,
        reference_state_id="reference:zero",
    )
    rejected = validate_pointwise_state(
        identity,
        z,
        plus,
        source_semantic_id=SOURCE,
        target_semantic_id=TARGET,
        reference_state_id="reference:plus",
    )
    assert accepted.status is EvidenceStatus.PASSED
    assert rejected.status is EvidenceStatus.FAILED
    assert accepted.context_scope is ContextScope.CHECKPOINT_FULL_STATE
    assert np.isfinite(rejected.details["residual_l2"])
    assert np.isclose(rejected.details["residual_l2"], np.sqrt(2.0))
    assert rejected.details["global_phase_real"] == 1.0
    assert rejected.details["global_phase_imag"] == 0.0


def test_context_scope_cannot_be_silently_broadened():
    evidence = validate_pointwise_unitary(
        np.eye(2),
        np.eye(2),
        source_semantic_id=SOURCE,
        target_semantic_id=TARGET,
    )
    require_context_scope(evidence, ContextScope.LOCAL_BLOCK)
    with pytest.raises(EvidenceError, match="does not establish"):
        require_context_scope(evidence, ContextScope.ARBITRARY_CIRCUIT_CONTEXT)


def test_finite_samples_cannot_be_promoted_to_familywise_native_synthesis():
    digest = "0" * 64
    with pytest.raises(MathematicalEvidenceError, match="familywise"):
        native_synthesis_evidence(
            source_semantic_id=SOURCE,
            target_semantic_id=TARGET,
            native_synthesis_scope=NativeSynthesisScope.FAMILYWISE,
            strength=EvidenceStrength.NUMERICALLY_VALIDATED,
            method_id="sampled-native-check-v1",
            proof_input_digest=digest,
            proof_output_digest=digest,
            tolerance=1e-10,
        )
    pointwise = native_synthesis_evidence(
        source_semantic_id=SOURCE,
        target_semantic_id=TARGET,
        native_synthesis_scope=NativeSynthesisScope.POINTWISE,
        strength=EvidenceStrength.NUMERICALLY_VALIDATED,
        method_id="sampled-native-check-v1",
        proof_input_digest=digest,
        proof_output_digest=digest,
        tolerance=1e-10,
    )
    assert pointwise.semantic_scope is SemanticScope.POINTWISE_UNITARY
