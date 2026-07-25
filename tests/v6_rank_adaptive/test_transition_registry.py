import hashlib

import pytest

from dvg_obs_ceo.v6_rank_adaptive.evidence import (
    NativeSynthesisScope,
    SemanticScope,
)
from dvg_obs_ceo.v6_rank_adaptive.transition_registry import (
    ParameterMapKind,
    TransitionDefinition,
    TransitionRegistry,
    TransitionRegistryError,
    TransitionStatus,
)


EVIDENCE_ID = "v6-evidence-v1:" + hashlib.sha256(b"evidence").hexdigest()


def definition(
    *,
    transition_id="v6-transition:mvp3-to-native-rank2-v1",
    target_family="NATIVE_RANK2",
    status=TransitionStatus.VERIFIED,
    evidence_ids=(EVIDENCE_ID,),
):
    return TransitionDefinition(
        transition_id=transition_id,
        source_family="MVP",
        target_family=target_family,
        allowed_constituent_counts=(3,),
        target_rank=2,
        parameter_map_kind=ParameterMapKind.AFFINE_EXACT,
        parameter_map_id="mvp3-rank2-map-v1",
        generator_relation_id="mvp3-rank2-generator-v1",
        native_synthesis_id="mvp3-rank2-native-v1",
        native_synthesis_scope=NativeSynthesisScope.FAMILYWISE,
        semantic_scope=SemanticScope.FAMILYWISE_UNITARY,
        status=status,
        evidence_ids=evidence_ids,
    )


def test_frozen_verified_registry_is_deterministic_and_executable():
    first = TransitionRegistry.from_definitions([definition()])
    second = TransitionRegistry.from_definitions([definition()])
    assert first.registry_digest == second.registry_digest
    assert first.require_executable(definition().transition_id) == definition()


def test_unknown_and_unverified_transition_fail_closed():
    proposed = definition(
        status=TransitionStatus.PROPOSED,
        evidence_ids=(),
    )
    registry = TransitionRegistry.from_definitions([proposed])
    with pytest.raises(TransitionRegistryError, match="verified"):
        registry.require_executable(proposed.transition_id)
    with pytest.raises(TransitionRegistryError, match="unknown"):
        registry.require_executable("v6-transition:unknown")


def test_registry_must_be_frozen_before_candidate_use():
    registry = TransitionRegistry.from_definitions([definition()], freeze=False)
    with pytest.raises(TransitionRegistryError, match="frozen"):
        registry.require_executable(definition().transition_id)


def test_duplicate_id_and_semantics_are_rejected():
    registry = TransitionRegistry()
    registry.register(definition())
    with pytest.raises(TransitionRegistryError, match="duplicate transition ID"):
        registry.register(definition())
    with pytest.raises(TransitionRegistryError, match="duplicate transition semantics"):
        registry.register(
            definition(
                transition_id="v6-transition:alias",
            )
        )


def test_frozen_registry_rejects_mutation():
    registry = TransitionRegistry.from_definitions([definition()])
    with pytest.raises(TransitionRegistryError, match="frozen"):
        registry.register(
            definition(
                transition_id="v6-transition:other",
                target_family="OTHER_RANK2",
            )
        )


def test_verified_transition_requires_evidence():
    with pytest.raises(TransitionRegistryError, match="requires evidence"):
        definition(evidence_ids=())


def test_rank_must_strictly_decrease():
    value = definition()
    with pytest.raises(TransitionRegistryError, match="strictly lower"):
        TransitionDefinition(
            **{
                **value.__dict__,
                "target_rank": 3,
            }
        )
