import json
from pathlib import Path
import random
import time

import numpy as np
import pytest

from dvg_obs_ceo.resources import AnsatzStructure
from dvg_obs_ceo.telemetry import ResourceSnapshot, WorkCounters
from dvg_obs_ceo.transaction import (
    AcceptanceCriteria,
    AcceptanceEvidence,
    CompressionRuntime,
    CompressionTransaction,
    OptimizerOutcome,
    TransactionDeadlineExceeded,
    TransactionError,
    evaluate_acceptance,
    recover_orphaned_transaction,
)
from dvg_obs_ceo.s7_probe import run_probe


def resource(cnot, depth, total, parameters, blocks, digest_character):
    return ResourceSnapshot(cnot, depth, total, parameters, blocks, "test-v1", digest_character * 64)


def accepted_decision(primary_success=True, fallback=None):
    evidence = AcceptanceEvidence(
        baseline_energy_hartree=-1.0,
        candidate_energy_hartree=-0.99995,
        independent_energy_hartree=-0.99995,
        fci_energy_hartree=-1.0,
        independent_state_fidelity=1.0,
        constraint_residual=1e-12,
        kkt_residual=1e-10,
        before_resources=resource(20, 10, 30, 2, 2, "a"),
        after_resources=resource(11, 7, 20, 1, 1, "b"),
        full_resource_recount_succeeded=True,
        transformation_semantics_validated=True,
        primary_optimizer=OptimizerOutcome(primary_success, "0" if primary_success else "2", "status", True),
        fallback_optimizer=fallback,
    )
    return evaluate_acceptance(evidence)


def runtime():
    random.seed(19)
    np.random.seed(19)
    return CompressionRuntime.create(
        ansatz=AnsatzStructure.create([4, 5], [0.2, -0.1], [2]),
        energy_hartree=-1.0,
        gradient=[1e-9, -1e-9],
        inverse_hessian=np.eye(2),
        statevector=[1.0, 0.0, 0.0, 0.0],
        work=WorkCounters(energy_evaluations=3, gradient_vector_evaluations=2),
        adapt_iteration=1,
        metadata={"run_id": "test", "resource_structure_digest": "a" * 64},
    )


def mutate_to_accepted(state):
    state.ansatz = AnsatzStructure.create([4], [0.15], [1])
    state.energy_hartree = -0.99995
    state.gradient = np.array([1e-10])
    state.inverse_hessian = np.array([[0.7]])
    state.statevector = np.array([1.0, 0.0, 0.0, 0.0], dtype=complex)
    state.work = WorkCounters(energy_evaluations=8, gradient_vector_evaluations=5)
    state.metadata["candidate"] = "accepted"
    state.metadata["resource_structure_digest"] = "b" * 64


def test_accepted_transaction_commits_atomic_directory(tmp_path: Path) -> None:
    state = runtime()
    before = state.snapshot().snapshot_digest
    with CompressionTransaction(state, tmp_path, transaction_id="tx-accepted") as transaction:
        mutate_to_accepted(state)
        transaction.stage_json("evidence/result.json", {"energy": state.energy_hartree})
        committed = transaction.commit(accepted_decision())
    assert committed == tmp_path / "committed" / "tx-accepted"
    assert (committed / "attempt.json").exists()
    assert (committed / "commit.json").exists()
    assert json.loads((committed / "commit.json").read_text())["acceptance"]["accepted"]
    assert state.snapshot().snapshot_digest != before
    assert not (tmp_path / ".staging" / "tx-accepted").exists()


@pytest.mark.parametrize("failure", ["exception", "nan", "partial-write"])
def test_failure_injection_restores_every_runtime_and_rng_field(tmp_path: Path, failure: str) -> None:
    state = runtime()
    before = state.snapshot()
    with pytest.raises((RuntimeError, TransactionError)):
        with CompressionTransaction(state, tmp_path, transaction_id=f"tx-{failure}") as transaction:
            mutate_to_accepted(state)
            random.random()
            np.random.random()
            if failure == "exception":
                raise RuntimeError("injected crash")
            if failure == "nan":
                state.gradient = np.array([float("nan")])
                transaction.commit(accepted_decision())
            partial = transaction.staging / "partial.bin"
            partial.write_bytes(b"incomplete")
            raise RuntimeError("injected partial artifact write")
    assert state.snapshot().snapshot_digest == before.snapshot_digest
    failed = tmp_path / "failed" / f"tx-{failure}"
    assert failed.exists()
    assert (failed / "rollback.json").exists()
    if failure == "partial-write":
        assert (failed / "partial.bin").read_bytes() == b"incomplete"
    assert not (tmp_path / "committed" / f"tx-{failure}").exists()


def test_rejected_decision_cannot_commit_and_rolls_back(tmp_path: Path) -> None:
    state = runtime()
    before = state.snapshot().snapshot_digest
    evidence = AcceptanceEvidence(
        baseline_energy_hartree=-1.0,
        candidate_energy_hartree=-0.9,
        independent_energy_hartree=-0.9,
        fci_energy_hartree=-1.0,
        independent_state_fidelity=0.8,
        constraint_residual=1e-2,
        kkt_residual=1e-2,
        before_resources=resource(20, 10, 30, 2, 2, "a"),
        after_resources=resource(21, 11, 31, 3, 3, "b"),
        full_resource_recount_succeeded=True,
        transformation_semantics_validated=True,
        primary_optimizer=OptimizerOutcome(False, "2", "failed", True),
        fallback_optimizer=None,
    )
    decision = evaluate_acceptance(evidence)
    assert not decision.accepted
    assert {"local_energy_budget", "chemical_accuracy", "pareto_nonworse", "optimizer_path_reviewed"} <= set(decision.rejection_reasons)
    with pytest.raises(TransactionError, match="rejected"):
        with CompressionTransaction(state, tmp_path, transaction_id="tx-rejected") as transaction:
            mutate_to_accepted(state)
            transaction.commit(decision)
    assert state.snapshot().snapshot_digest == before


def test_acceptance_decision_is_bound_to_runtime_energy_and_parameter_count(tmp_path: Path) -> None:
    state = runtime()
    decision = accepted_decision()
    with pytest.raises(TransactionError, match="energies"):
        with CompressionTransaction(state, tmp_path, transaction_id="tx-unbound-energy") as transaction:
            mutate_to_accepted(state)
            state.energy_hartree = -0.99994
            transaction.commit(decision)
    assert state.energy_hartree == pytest.approx(-1.0)


def test_failed_primary_requires_completed_fallback_and_independent_kkt() -> None:
    without_fallback = accepted_decision(primary_success=False)
    assert not without_fallback.accepted
    assert not without_fallback.checks["optimizer_path_reviewed"]
    completed_fallback = OptimizerOutcome(False, "2", "precision loss but completed", True)
    with_fallback = accepted_decision(primary_success=False, fallback=completed_fallback)
    assert with_fallback.accepted
    assert with_fallback.checks["optimizer_path_reviewed"]


def test_nonphysical_fidelity_and_negative_residuals_are_rejected() -> None:
    base = AcceptanceEvidence(
        baseline_energy_hartree=-1.0,
        candidate_energy_hartree=-1.0,
        independent_energy_hartree=-1.0,
        fci_energy_hartree=-1.0,
        independent_state_fidelity=1.01,
        constraint_residual=-1e-9,
        kkt_residual=0.0,
        before_resources=resource(20, 10, 30, 2, 2, "a"),
        after_resources=resource(11, 7, 20, 1, 1, "b"),
        full_resource_recount_succeeded=True,
        transformation_semantics_validated=True,
        primary_optimizer=OptimizerOutcome(True, "0", "ok", True),
        fallback_optimizer=None,
    )
    decision = evaluate_acceptance(base)
    assert not decision.accepted
    assert not decision.checks["physical_scalar_domain"]


def test_deadline_and_path_escape_roll_back(tmp_path: Path) -> None:
    state = runtime()
    before = state.snapshot().snapshot_digest
    with pytest.raises(TransactionDeadlineExceeded):
        with CompressionTransaction(
            state,
            tmp_path,
            transaction_id="tx-timeout",
            timeout_seconds=1e-6,
        ) as transaction:
            time.sleep(0.001)
            transaction.check_deadline()
    assert state.snapshot().snapshot_digest == before
    with pytest.raises(TransactionError, match="escapes"):
        with CompressionTransaction(state, tmp_path, transaction_id="tx-path") as transaction:
            transaction.stage_json("../escape.json", {"bad": True})
    assert not (tmp_path / "escape.json").exists()


def test_nested_runtime_transaction_is_rejected(tmp_path: Path) -> None:
    state = runtime()
    with CompressionTransaction(state, tmp_path, transaction_id="tx-outer"):
        with pytest.raises(TransactionError, match="another"):
            with CompressionTransaction(state, tmp_path, transaction_id="tx-inner"):
                pass


def test_process_global_rng_makes_different_runtime_transactions_exclusive(tmp_path: Path) -> None:
    first = runtime()
    second = runtime()
    with CompressionTransaction(first, tmp_path, transaction_id="tx-first"):
        with pytest.raises(TransactionError, match="another"):
            with CompressionTransaction(second, tmp_path, transaction_id="tx-second"):
                pass


def test_durable_snapshot_round_trip_and_orphan_recovery(tmp_path: Path) -> None:
    source = runtime()
    transaction = CompressionTransaction(source, tmp_path, transaction_id="tx-orphan")
    transaction.__enter__()
    expected = transaction.snapshot.snapshot_digest
    mutate_to_accepted(source)
    # Model the vanished process by releasing its process-local lock; the
    # registered subprocess probe below exercises a real os._exit boundary.
    transaction._lock.release()
    recovery_runtime = runtime()
    recovery_runtime.energy_hartree = -0.5
    failed = recover_orphaned_transaction(
        recovery_runtime, tmp_path, "tx-orphan"
    )
    assert recovery_runtime.snapshot().snapshot_digest == expected
    assert (failed / "snapshot.json").exists()
    assert (failed / "recovery-rollback.json").exists()


def test_registered_probe_exercises_real_process_loss(tmp_path: Path) -> None:
    artifact = run_probe(tmp_path / "probe.json")
    assert artifact["hard_crash"]["exit_code"] == 17
    assert artifact["hard_crash"]["bitwise_equivalent_recovery"]
    assert artifact["accepted_commit"]["committed"]
    assert all(value["restored"] for value in artifact["failure_injections"].values())
