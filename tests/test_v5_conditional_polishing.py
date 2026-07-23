import numpy as np
import pytest

from dvg_obs_ceo.identity import sha256_hex
from dvg_obs_ceo.polishing import TrustNCGConfig
from dvg_obs_ceo.quadratic import ConstraintTargetIR
from dvg_obs_ceo.resources import AnsatzStructure
from dvg_obs_ceo.telemetry import WorkCounters
from dvg_obs_ceo.transaction import CompressionRuntime
from dvg_obs_ceo.v5_conditional_polishing import (
    SECOND_START_TRIGGER,
    ConditionalPolishingConfig,
    PolishingEligibility,
    V5PolishingError,
    polish_target_native_conditionally,
)


def transformation():
    return ConstraintTargetIR.create(
        constraint_matrix=[[1.0, 1.0]],
        constraint_rhs=[0.0],
        offset=[0.0, 0.0],
        jacobian=[[1.0], [-1.0]],
        source_slots=("a", "b"),
        target_slots=("z",),
        generator_normalization="test",
        orientation="test",
    )


def eligible(refinement=True):
    return PolishingEligibility(True, True, True, refinement)


def objective(center):
    def energy(source):
        return float((source[0] - center) ** 2 + (source[1] + center) ** 2)

    def gradient(source):
        return np.asarray([2.0 * (source[0] - center), 2.0 * (source[1] + center)])

    return energy, gradient


def runtime():
    return CompressionRuntime.create(
        ansatz=AnsatzStructure.create([1, 2], [0.2, -0.2], [2]),
        energy_hartree=-1.0,
        gradient=[0.0, 0.0],
        inverse_hessian=np.eye(2),
        statevector=[1.0, 0.0],
        work=WorkCounters(),
        adapt_iteration=1,
        metadata={
            "resource_structure_digest": sha256_hex("runtime"),
            "budget_reference_energy_hartree": -1.0,
        },
    )


def test_primary_target_native_polishing_preserves_exact_constraint() -> None:
    energy, gradient = objective(0.3)
    result = polish_target_native_conditionally(
        transformation(), [0.8, -0.8], [0.8, -0.8], energy, gradient, eligible()
    )
    assert result["success"]
    assert result["selected_start"] == "obs-hvp-projection"
    np.testing.assert_allclose(result["source_theta"], [0.3, -0.3], atol=1e-8)
    assert result["constraint_residual_infinity"] <= 1e-10
    assert result["gradient_infinity"] <= 1e-8
    assert result["paper_measurement_cost"] is None


def test_ineligible_candidate_never_calls_energy_or_gradient() -> None:
    def forbidden(_):
        raise AssertionError("blocked candidate callback must not run")

    result = polish_target_native_conditionally(
        transformation(), [0.2, -0.2], [0.2, -0.2], forbidden, forbidden,
        PolishingEligibility(False, True, True, True),
    )
    assert not result["performed"]
    assert result["blocked_reasons"] == ["semantic-validation-failed"]
    assert result["work"]["energy_evaluations"] == 0


def test_second_start_requires_frozen_trigger_and_remaining_budget() -> None:
    energy, gradient = objective(0.2)
    config = ConditionalPolishingConfig(
        polisher=TrustNCGConfig(maximum_gradient_vector_evaluations=1),
        enable_second_least_squares_start=True,
        second_start_trigger=SECOND_START_TRIGGER,
        maximum_total_energy_evaluations=4,
        maximum_total_gradient_vector_evaluations=2,
        maximum_total_hessian_vector_products=4,
    )
    result = polish_target_native_conditionally(
        transformation(), [1.0, -1.0], [0.2, -0.2], energy, gradient, eligible(), config=config
    )
    assert result["success"]
    assert result["selected_start"] == "registered-least-squares-reference"
    assert len(result["attempts"]) == 2
    assert result["work"]["gradient_vector_evaluations"] == 2
    with pytest.raises(V5PolishingError, match="frozen trigger"):
        ConditionalPolishingConfig(
            enable_second_least_squares_start=True,
            second_start_trigger="ad-hoc",
        ).validate()


def test_callback_runtime_mutation_is_detected_and_fully_restored() -> None:
    guarded = runtime()
    before = guarded.snapshot().snapshot_digest
    _, gradient = objective(0.3)

    def mutating_energy(source):
        guarded.energy_hartree += 0.1
        return float(source @ source)

    with pytest.raises(V5PolishingError, match="runtime-mutation-incident"):
        polish_target_native_conditionally(
            transformation(), [0.8, -0.8], [0.8, -0.8], mutating_energy, gradient,
            eligible(), runtime_guard=guarded,
        )
    assert guarded.snapshot().snapshot_digest == before


def test_frozen_gradient_certificate_cannot_be_relaxed() -> None:
    with pytest.raises(V5PolishingError, match="retain the frozen"):
        ConditionalPolishingConfig(required_gradient_infinity=1e-6).validate()
