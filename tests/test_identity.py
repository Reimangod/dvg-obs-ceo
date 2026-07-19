import hashlib

import pytest

from dvg_obs_ceo.identity import (
    IdentityError,
    MeasurementContextSpec,
    ProblemSpec,
    ScientificIdentityBundle,
    StatePreparationSpec,
    canonical_float64_hex,
    require_measurement_reuse_compatible,
)


DIGEST_A = hashlib.sha256(b"a").hexdigest()
DIGEST_B = hashlib.sha256(b"b").hexdigest()


def state(coefficients=(0.1, -0.0)) -> StatePreparationSpec:
    return StatePreparationSpec.create(
        reference_state=(1, 1, 0, 0),
        generator_definition_digest=DIGEST_A,
        ansatz_block_structure=(("OVP", (4,)), ("MVP", (10,))),
        ansatz_indices=(4, 10),
        coefficients=coefficients,
        qubit_mapping="jordan-wigner",
        qubit_ordering=(0, 1, 2, 3),
    )


def problem(hamiltonian=DIGEST_A) -> ProblemSpec:
    return ProblemSpec(
        hamiltonian,
        "H2",
        (("H", (0.0, 0.0, 0.0)), ("H", (0.0, 0.0, 1.5))),
        "sto-3g",
        (0, 1),
        (),
        "jordan-wigner-v1",
    )


def measurement(state_id: str, problem_id: str, *, plan="ogm-v1") -> MeasurementContextSpec:
    return MeasurementContextSpec(
        state_id,
        problem_id,
        DIGEST_A,
        plan,
        "qwc",
        "exact-statevector-v1",
        DIGEST_B,
    )


def test_three_level_identity_round_trip_schema() -> None:
    prepared = state()
    physical = problem()
    context = measurement(prepared.state_preparation_id, physical.problem_id)
    value = ScientificIdentityBundle(prepared, physical, context).to_dict()
    assert value["state_preparation_id"].startswith("state-v1:")
    assert value["problem_id"].startswith("problem-v1:")
    assert value["measurement_context_id"].startswith("measurement-v1:")
    assert ScientificIdentityBundle.from_dict(value).to_dict() == value


def test_measurement_plan_does_not_change_state_identity() -> None:
    prepared = state()
    physical = problem()
    first = measurement(prepared.state_preparation_id, physical.problem_id, plan="ogm-v1")
    second = measurement(prepared.state_preparation_id, physical.problem_id, plan="ogm-v2")
    equivalent_state = state()
    assert prepared.state_preparation_id == equivalent_state.state_preparation_id
    assert first.measurement_context_id != second.measurement_context_id


def test_payload_tampering_without_id_update_is_rejected() -> None:
    prepared = state()
    physical = problem()
    context = measurement(prepared.state_preparation_id, physical.problem_id)
    value = ScientificIdentityBundle(prepared, physical, context).to_dict()
    value["state"]["coefficient_bytes_hex"][0] = canonical_float64_hex((0.2,))[0]
    with pytest.raises(IdentityError, match="does not match"):
        ScientificIdentityBundle.from_dict(value)


def test_block_structure_order_must_match_ansatz_order() -> None:
    with pytest.raises(IdentityError, match="ordered block structure"):
        StatePreparationSpec.create(
            reference_state=(1, 1, 0, 0),
            generator_definition_digest=DIGEST_A,
            ansatz_block_structure=(("OVP", (10,)), ("MVP", (4,))),
            ansatz_indices=(4, 10),
            coefficients=(0.1, 0.2),
            qubit_mapping="jordan-wigner",
            qubit_ordering=(0, 1, 2, 3),
        )


def test_same_state_different_hamiltonian_rejects_measurement_reuse() -> None:
    prepared = state()
    first_problem = problem(DIGEST_A)
    second_problem = problem(DIGEST_B)
    first = measurement(prepared.state_preparation_id, first_problem.problem_id)
    second = measurement(prepared.state_preparation_id, second_problem.problem_id)
    with pytest.raises(IdentityError):
        require_measurement_reuse_compatible(first, second)


def test_coefficient_bytes_are_canonical_and_sensitive() -> None:
    assert canonical_float64_hex((0.0,)) == canonical_float64_hex((-0.0,))
    assert state((0.1, 0.0)).state_preparation_id != state((0.2, 0.0)).state_preparation_id
    with pytest.raises(IdentityError):
        canonical_float64_hex((float("nan"),))


def test_bundle_rejects_cross_bound_context() -> None:
    prepared = state()
    physical = problem()
    alien = state((0.3, 0.0))
    context = measurement(alien.state_preparation_id, physical.problem_id)
    with pytest.raises(IdentityError):
        ScientificIdentityBundle(prepared, physical, context)
