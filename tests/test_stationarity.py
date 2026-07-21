import numpy as np
import pytest
from scipy.linalg import expm, null_space

from dvg_obs_ceo.quadratic import ConstraintTargetIR
from dvg_obs_ceo.stationarity import (
    GradientAgreementPolicy,
    GradientAuditError,
    audit_gradient_paths,
)


def _transform(jacobian: np.ndarray, offset: np.ndarray | None = None) -> ConstraintTargetIR:
    source, target = jacobian.shape
    constraint = np.eye(source) if target == 0 else null_space(jacobian.T).T
    origin = np.zeros(source) if offset is None else offset
    return ConstraintTargetIR.create(
        constraint_matrix=constraint,
        constraint_rhs=constraint @ origin,
        offset=origin,
        jacobian=jacobian,
        source_slots=[f"s:{index}" for index in range(source)],
        target_slots=[f"t:{index}" for index in range(target)],
        generator_normalization="test",
        orientation="test",
    )


@pytest.mark.parametrize(
    "jacobian",
    [
        np.zeros((1, 0)),  # whole block deletion
        np.array([[1.0], [0.0]]),  # constituent deletion / single QE
        np.array([[0.0], [1.0]]),
        np.array([[1.0], [1.0]]),  # OVP sum
        np.array([[1.0], [-1.0]]),  # OVP difference
        np.array([[1.0, 0.0], [0.0, 0.0], [0.0, 1.0]]),
    ],
)
def test_chain_rule_for_supported_atomic_jacobians(jacobian: np.ndarray) -> None:
    transform = _transform(jacobian, np.linspace(-0.1, 0.1, jacobian.shape[0]))
    hessian = np.diag(np.arange(1, jacobian.shape[0] + 1, dtype=float))
    linear = np.linspace(0.2, -0.3, jacobian.shape[0])
    phi = np.linspace(-0.4, 0.3, jacobian.shape[1])

    def source_gradient(theta: np.ndarray) -> np.ndarray:
        return hessian @ theta + linear

    def target_gradient(coordinates: np.ndarray) -> np.ndarray:
        theta = transform.offset + transform.jacobian @ coordinates
        return transform.jacobian.T @ source_gradient(theta)

    result = audit_gradient_paths(phi, transform, target_gradient, source_gradient)
    assert result["passed"]
    assert result["difference_infinity"] <= 1e-15


def test_random_state_unitary_gradient_and_fidelity_agree() -> None:
    rng = np.random.default_rng(19)
    source_generators = (
        np.diag([1j, -1j, 2j, -2j]),
        np.diag([0.5j, -0.5j, -1.5j, 1.5j]),
    )
    jacobian = np.array([[1.0], [-1.0]])
    transform = _transform(jacobian)
    reference = rng.normal(size=4) + 1j * rng.normal(size=4)
    reference /= np.linalg.norm(reference)
    raw = rng.normal(size=(4, 4)) + 1j * rng.normal(size=(4, 4))
    hamiltonian = raw + raw.conj().T

    def source_state(theta: np.ndarray) -> np.ndarray:
        state = reference.copy()
        for parameter, generator in zip(theta, source_generators):
            state = expm(parameter * generator) @ state
        return state

    target_generator = source_generators[0] - source_generators[1]

    def target_state(phi: np.ndarray) -> np.ndarray:
        return expm(phi[0] * target_generator) @ reference

    def gradient(state: np.ndarray, generators: tuple[np.ndarray, ...]) -> np.ndarray:
        return np.asarray(
            [2.0 * np.real(np.vdot(generator @ state, hamiltonian @ state)) for generator in generators]
        )

    def source_gradient(theta: np.ndarray) -> np.ndarray:
        return gradient(source_state(theta), source_generators)

    def target_gradient(phi: np.ndarray) -> np.ndarray:
        return gradient(target_state(phi), (target_generator,))

    result = audit_gradient_paths(
        [0.37],
        transform,
        target_gradient,
        source_gradient,
        target_state=target_state,
        source_state=source_state,
    )
    assert result["passed"]
    assert result["source_target_state_fidelity"] >= 1.0 - 1e-14


def test_wrong_jacobian_and_wrong_source_point_fail() -> None:
    correct = np.array([[1.0], [1.0]])
    transform = _transform(correct)
    source_gradient = lambda theta: np.array([theta[0] + 0.2, 2.0 * theta[1] - 0.1])
    target_gradient = lambda phi: correct.T @ source_gradient(correct @ phi)
    assert audit_gradient_paths([0.4], transform, target_gradient, source_gradient)["passed"]

    wrong_transform = _transform(np.array([[1.0], [-1.0]]))
    wrong_j = audit_gradient_paths([0.4], wrong_transform, target_gradient, source_gradient)
    assert not wrong_j["passed"]

    wrong_point = audit_gradient_paths(
        [0.4], transform, target_gradient, lambda _theta: source_gradient(np.array([0.0, 0.0]))
    )
    assert not wrong_point["passed"]


def test_policy_and_nonfinite_values_fail_closed() -> None:
    transform = _transform(np.eye(1))
    with pytest.raises(GradientAuditError, match="bitwise"):
        audit_gradient_paths(
            [0.0], transform, lambda x: x, lambda x: x,
            policy=GradientAgreementPolicy(0.0, 0.0),
        )
    with pytest.raises(GradientAuditError, match="finite"):
        audit_gradient_paths([0.0], transform, lambda _x: [np.nan], lambda x: x)
