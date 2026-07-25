from pathlib import Path

import numpy as np
import pytest

from dvg_obs_ceo.resources import AnsatzStructure
from dvg_obs_ceo.telemetry import ResourceSnapshot, WorkCounters
from dvg_obs_ceo.transaction import CompressionRuntime
from dvg_obs_ceo.v5_ledger import V5WorkCounters, versioned_id
from dvg_obs_ceo.v5_nested_transaction import (
    NestedRoundTransaction,
    PathCheckpointStore,
    V5NestedTransactionError,
    recover_orphaned_round,
)
from dvg_obs_ceo.v5_nested_audit import run_audit
from test_transaction import accepted_decision, mutate_to_accepted, runtime


def resource(character: str, parameters: int = 2) -> ResourceSnapshot:
    return ResourceSnapshot(20 if parameters == 2 else 11, 10 if parameters == 2 else 7, 30 if parameters == 2 else 20, parameters, parameters, "test-v1", character * 64)


def initialized(tmp_path: Path):
    state = runtime()
    path_id = versioned_id("path-v5", "nested-test")
    store = PathCheckpointStore(tmp_path / "path", path_id)
    source = store.initialize(
        state,
        work=V5WorkCounters(energy_evaluations=2),
        state_preparation_id="state-v1:" + "1" * 64,
        problem_id="problem-v1:" + "2" * 64,
        measurement_context_id="measurement-v1:" + "3" * 64,
        catalog_digest="4" * 64,
        resource_snapshot=resource("a"),
    )
    return state, store, source


def commit_round_one(state, store):
    with NestedRoundTransaction(state, store, 1, transaction_id="round-one") as transaction:
        mutate_to_accepted(state)
        return transaction.commit(
            accepted_decision(),
            work=V5WorkCounters(energy_evaluations=5, exact_vqe_attempts=1, attempted_rounds=1, accepted_rounds=1),
            state_preparation_id="state-v1:" + "5" * 64,
            problem_id="problem-v1:" + "2" * 64,
            measurement_context_id="measurement-v1:" + "6" * 64,
            catalog_digest="7" * 64,
            resource_snapshot=resource("b", 1),
        )


def test_nested_round_commit_builds_immutable_chain(tmp_path: Path) -> None:
    state, store, source = initialized(tmp_path)
    committed = commit_round_one(state, store)
    checkpoints = store.checkpoints()
    assert len(checkpoints) == 2
    assert committed.parent_checkpoint_digest == source.checkpoint_digest
    assert committed.parent_runtime_snapshot_digest == source.runtime().snapshot_digest
    assert store.latest().runtime().snapshot_digest == state.snapshot().snapshot_digest


def test_failed_later_round_restores_last_commit_not_source(tmp_path: Path) -> None:
    state, store, source = initialized(tmp_path)
    first = commit_round_one(state, store)
    first_runtime = state.snapshot().snapshot_digest
    with pytest.raises(RuntimeError, match="injected"):
        with NestedRoundTransaction(state, store, 2, transaction_id="round-two-fail"):
            state.energy_hartree = -0.5
            state.metadata["candidate"] = "bad"
            raise RuntimeError("injected")
    assert state.snapshot().snapshot_digest == first_runtime
    assert store.latest().checkpoint_digest == first.checkpoint_digest
    assert store.latest().checkpoint_digest != source.checkpoint_digest
    assert (store.failed / "round-two-fail" / "rollback.json").is_file()


def test_checkpoint_tampering_and_chain_break_are_detected(tmp_path: Path) -> None:
    state, store, _ = initialized(tmp_path)
    commit_round_one(state, store)
    latest_dir = store._round_directories()[-1]
    checkpoint = latest_dir / "checkpoint.json"
    data = checkpoint.read_text(encoding="utf-8")
    checkpoint.write_text(data.replace('"round_index":1', '"round_index":9'), encoding="utf-8")
    with pytest.raises(V5NestedTransactionError, match="digest mismatch"):
        store.checkpoints()


def test_wrong_runtime_cannot_start_next_round(tmp_path: Path) -> None:
    state, store, _ = initialized(tmp_path)
    commit_round_one(state, store)
    wrong = runtime()
    with pytest.raises(V5NestedTransactionError, match="runtime does not match"):
        with NestedRoundTransaction(wrong, store, 2, transaction_id="wrong-runtime"):
            pass


def test_concurrent_nested_round_is_rejected(tmp_path: Path) -> None:
    state, store, _ = initialized(tmp_path)
    with NestedRoundTransaction(state, store, 1, transaction_id="outer"):
        with pytest.raises(V5NestedTransactionError, match="another"):
            with NestedRoundTransaction(state, store, 1, transaction_id="inner"):
                pass


def test_orphaned_round_recovers_parent_checkpoint(tmp_path: Path) -> None:
    state, store, source = initialized(tmp_path)
    transaction = NestedRoundTransaction(state, store, 1, transaction_id="orphan")
    transaction.__enter__()
    mutate_to_accepted(state)
    transaction._release_locks()
    recovered = recover_orphaned_round(state, store, "orphan")
    assert state.snapshot().snapshot_digest == source.runtime().snapshot_digest
    assert (recovered / "recovery-rollback.json").is_file()
    assert store.latest().checkpoint_digest == source.checkpoint_digest


def test_work_budget_and_problem_id_cannot_regress_or_change(tmp_path: Path) -> None:
    state, store, _ = initialized(tmp_path)
    with pytest.raises(V5NestedTransactionError, match="ProblemID"):
        with NestedRoundTransaction(state, store, 1, transaction_id="problem-change") as transaction:
            mutate_to_accepted(state)
            transaction.commit(
                accepted_decision(),
                work=V5WorkCounters(attempted_rounds=1, accepted_rounds=1),
                state_preparation_id="state-v1:" + "5" * 64,
                problem_id="problem-v1:" + "9" * 64,
                measurement_context_id="measurement-v1:" + "6" * 64,
                catalog_digest="7" * 64,
                resource_snapshot=resource("b", 1),
            )
    assert store.latest().round_index == 0

    with pytest.raises(V5NestedTransactionError, match="work counter regressed"):
        with NestedRoundTransaction(state, store, 1, transaction_id="work-regression") as transaction:
            mutate_to_accepted(state)
            transaction.commit(
                accepted_decision(),
                work=V5WorkCounters(energy_evaluations=0, attempted_rounds=1, accepted_rounds=1),
                state_preparation_id="state-v1:" + "5" * 64,
                problem_id="problem-v1:" + "2" * 64,
                measurement_context_id="measurement-v1:" + "6" * 64,
                catalog_digest="7" * 64,
                resource_snapshot=resource("b", 1),
            )


def test_v5_s2_independent_nested_transaction_audit() -> None:
    result = run_audit()
    assert result["passed"]
    assert all(result["checks"].values())
