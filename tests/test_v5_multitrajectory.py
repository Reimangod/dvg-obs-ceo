from dataclasses import replace

from dvg_obs_ceo.identity import sha256_hex
from dvg_obs_ceo.telemetry import ResourceSnapshot
from dvg_obs_ceo.v5_multitrajectory import (
    ExpansionOutcome,
    ExpansionProposal,
    MultiTrajectoryConfig,
    TrajectoryState,
    run_multitrajectory,
)
from dvg_obs_ceo.v5_multitrajectory_audit import run_audit


def resources(cnot, parameters, label):
    return ResourceSnapshot(cnot, cnot // 3, cnot + 40, parameters, parameters, "s7-test-counter-v1", sha256_hex(label))


SOURCE = TrajectoryState(
    "path-v5:" + sha256_hex("source-path"),
    "state-v1:" + sha256_hex("source-state"),
    "problem-v1:" + sha256_hex("problem"),
    sha256_hex("source-checkpoint"),
    0.0,
    resources(100, 10, "source-resources"),
    (),
    "source",
)


def proposal(parent, label, rank, endpoint, proposed=None):
    return ExpansionProposal.create(
        parent_path_id=parent.path_id,
        candidate_id="candidate-v5:" + sha256_hex(label),
        exact_task_payload={"parent": parent.state_preparation_id, "label": label},
        proposed_state_preparation_id="state-v1:" + sha256_hex(proposed or ("proposed-" + label)),
        endpoint=endpoint,
        screening_rank=rank,
        predicted_loss_hartree=1e-5,
    )


def catalog(parent):
    if not parent.candidate_history:
        return (
            proposal(parent, "b", 1, "parameter_count"),
            proposal(parent, "a-duplicate", 2, "cnot_count", proposed="proposed-a"),
            proposal(parent, "a", 0, "cnot_count", proposed="proposed-a"),
        )
    if parent.candidate_history[-1].endswith(sha256_hex("a")):
        return (proposal(parent, "c", 0, "cnot_count"),)
    if parent.candidate_history[-1].endswith(sha256_hex("b")):
        return (proposal(parent, "d", 0, "parameter_count"),)
    return ()


RESOURCE_BY_LABEL = {
    "a": (80, 9), "b": (85, 7), "c": (70, 8), "d": (75, 6),
}


def executor(item, parent, attempt):
    label = next(label for label in RESOURCE_BY_LABEL if item.candidate_id.endswith(sha256_hex(label)))
    cnot, parameters = RESOURCE_BY_LABEL[label]
    return ExpansionOutcome(
        item.proposal_id,
        True,
        "state-v1:" + sha256_hex({"final": label, "parent": parent.state_preparation_id}),
        sha256_hex({"checkpoint": label, "attempt": attempt}),
        attempt * 1e-5,
        resources(cnot, parameters, "result-" + label),
        label,
        {"energy_evaluations": 1, "exact_vqe_attempts": 1},
    )


def test_multitrajectory_is_order_invariant_and_deduplicates_before_exact() -> None:
    config = MultiTrajectoryConfig(2, 3, 2, 4)
    forward = run_multitrajectory(SOURCE, catalog_builder=catalog, exact_executor=executor, config=config)
    reverse = run_multitrajectory(SOURCE, catalog_builder=lambda state: tuple(reversed(catalog(state))), exact_executor=executor, config=config)
    assert forward == reverse
    assert forward["exact_attempts"] == 4
    assert forward["trajectory"][0]["duplicate_exact_tasks_skipped"] == 1
    assert forward["aggregate_work"]["exact_vqe_attempts"] == 4
    assert forward["winner_resources"]["cnot_count"] == 70


def test_width_one_uses_one_active_path_per_round() -> None:
    result = run_multitrajectory(
        SOURCE,
        catalog_builder=catalog,
        exact_executor=executor,
        config=MultiTrajectoryConfig(1, 1, 2, 2),
    )
    assert all(len(round_record["active_path_ids_after"]) <= 1 for round_record in result["trajectory"])
    assert result["winner_resources"]["cnot_count"] == 70
    assert result["exact_attempts"] == 2


def test_executor_cannot_accept_outside_cumulative_budget() -> None:
    def unsafe(item, parent, attempt):
        return replace(executor(item, parent, attempt), cumulative_energy_increase_hartree=2e-4)

    import pytest
    from dvg_obs_ceo.v5_multitrajectory import V5MultiTrajectoryError

    with pytest.raises(V5MultiTrajectoryError, match="outside the cumulative energy budget"):
        run_multitrajectory(
            SOURCE,
            catalog_builder=catalog,
            exact_executor=unsafe,
            config=MultiTrajectoryConfig(1, 1, 1, 1),
        )


def test_resource_counter_drift_fails_closed() -> None:
    def mismatched(item, parent, attempt):
        outcome = executor(item, parent, attempt)
        return replace(
            outcome,
            resources=ResourceSnapshot(
                outcome.resources.cnot_count,
                outcome.resources.cnot_depth,
                outcome.resources.total_depth,
                outcome.resources.parameter_count,
                outcome.resources.logical_block_count,
                "different-counter-v1",
                outcome.resources.structure_digest,
            ),
        )

    import pytest
    from dvg_obs_ceo.v5_multitrajectory import V5MultiTrajectoryError

    with pytest.raises(V5MultiTrajectoryError, match="counter version changed"):
        run_multitrajectory(
            SOURCE,
            catalog_builder=catalog,
            exact_executor=mismatched,
            config=MultiTrajectoryConfig(1, 1, 1, 1),
        )


def test_s7_independent_audit() -> None:
    result = run_audit()
    assert result["passed"]
    assert all(result["checks"].values())
