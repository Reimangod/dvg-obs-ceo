import hashlib
from types import MappingProxyType

import pytest

from dvg_obs_ceo.v6_rank_adaptive.evidence import (
    ContextScope,
    EvidenceError,
    EvidenceRecord,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    ResourceDeltaEvidence,
    ResourceEffect,
    ResourceVector,
    SemanticScope,
    require_algebraic_exact_claim,
)


DIGEST_A = hashlib.sha256(b"a").hexdigest()
DIGEST_B = hashlib.sha256(b"b").hexdigest()


def record(
    evidence_type=EvidenceType.TARGET_EMBEDDING,
    *,
    status=EvidenceStatus.PASSED,
    strength=EvidenceStrength.ALGEBRAICALLY_PROVEN,
    semantic_scope=SemanticScope.FAMILYWISE_UNITARY,
    context_scope=ContextScope.LOCAL_BLOCK,
    tolerance=None,
):
    return EvidenceRecord(
        evidence_type=evidence_type,
        status=status,
        strength=strength,
        semantic_scope=semantic_scope,
        context_scope=context_scope,
        method_id="registered-proof-v1",
        source_semantic_id="source:block-a",
        target_semantic_id="target:block-b",
        input_digest=DIGEST_A,
        output_digest=DIGEST_B,
        tolerance=tolerance,
        details={"claim": "test"},
    )


def test_evidence_round_trip_has_stable_canonical_id():
    original = record()
    restored = EvidenceRecord.from_dict(original.to_dict())
    assert restored == original
    assert restored.evidence_id == original.evidence_id


def test_evidence_details_are_deeply_immutable():
    original = EvidenceRecord(
        **{
            **record().__dict__,
            "details": {"nested": {"values": [1, 2]}},
        }
    )
    assert isinstance(original.details, MappingProxyType)
    with pytest.raises(TypeError):
        original.details["nested"] = {}
    with pytest.raises(TypeError):
        original.details["nested"]["values"] = ()
    assert EvidenceRecord.from_dict(original.to_dict()) == original


def test_evidence_id_detects_payload_tampering():
    value = record().to_dict()
    value["method_id"] = "different-proof"
    with pytest.raises(EvidenceError, match="evidence_id"):
        EvidenceRecord.from_dict(value)


def test_numerical_evidence_requires_tolerance_and_is_not_algebraic():
    with pytest.raises(EvidenceError, match="tolerance"):
        record(strength=EvidenceStrength.NUMERICALLY_VALIDATED)
    numerical = record(
        strength=EvidenceStrength.NUMERICALLY_VALIDATED,
        tolerance=1e-10,
    )
    records = {
        item: record(
            item,
            strength=EvidenceStrength.NUMERICALLY_VALIDATED,
            tolerance=1e-10,
        )
        for item in (
            EvidenceType.TARGET_EMBEDDING,
            EvidenceType.SOURCE_UNITARY_EQUIVALENCE,
            EvidenceType.NATIVE_SYNTHESIS,
            EvidenceType.CONTEXTUAL_REWRITE,
        )
    }
    assert numerical.to_dict()["tolerance"] == 1e-10
    with pytest.raises(EvidenceError, match="non-proven"):
        require_algebraic_exact_claim(records)


def test_not_established_strength_and_status_cannot_disagree():
    with pytest.raises(EvidenceError, match="NOT_ESTABLISHED"):
        record(strength=EvidenceStrength.NOT_ESTABLISHED)
    with pytest.raises(EvidenceError, match="NOT_ESTABLISHED"):
        record(status=EvidenceStatus.NOT_ESTABLISHED)


def test_state_evidence_cannot_be_labeled_as_familywise_unitary():
    with pytest.raises(EvidenceError, match="pointwise-state"):
        record(
            EvidenceType.SOURCE_STATE_EQUIVALENCE,
            semantic_scope=SemanticScope.FAMILYWISE_UNITARY,
        )


def test_algebraic_exact_claim_requires_all_strong_axes():
    required = (
        EvidenceType.TARGET_EMBEDDING,
        EvidenceType.SOURCE_UNITARY_EQUIVALENCE,
        EvidenceType.NATIVE_SYNTHESIS,
        EvidenceType.CONTEXTUAL_REWRITE,
    )
    records = {item: record(item) for item in required}
    require_algebraic_exact_claim(records)
    del records[EvidenceType.CONTEXTUAL_REWRITE]
    with pytest.raises(EvidenceError, match="lacks evidence"):
        require_algebraic_exact_claim(records)


def test_resource_evidence_separates_parameter_and_physical_gain():
    before = ResourceVector(3, 1, 13, 11, 20)
    parameter_only = ResourceDeltaEvidence(
        before=before,
        after=ResourceVector(2, 1, 13, 11, 20),
        resource_counter_version="paper-era-v1",
        native_synthesizer_version="mvp-v1",
        compiler_configuration="no-global-compilation",
        qubit_order=(0, 1, 2, 3),
        before_digest=DIGEST_A,
        after_digest=DIGEST_B,
    )
    assert parameter_only.strict_gain is True
    assert parameter_only.physical_circuit_gain is False
    assert parameter_only.effect is ResourceEffect.VERIFIED_GAIN
    assert parameter_only.to_dict()["after"]["cnot_count"] == 13


def test_primary_resource_regression_is_explicit():
    evidence = ResourceDeltaEvidence(
        before=ResourceVector(3, 1, 13, 11, 20),
        after=ResourceVector(2, 1, 14, 10, 19),
        resource_counter_version="paper-era-v1",
        native_synthesizer_version="rank2-v1",
        compiler_configuration="no-global-compilation",
        qubit_order=(0, 1, 2, 3),
        before_digest=DIGEST_A,
        after_digest=DIGEST_B,
    )
    assert evidence.strict_gain is True
    assert evidence.effect is ResourceEffect.REGRESSION
