from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from dvg_obs_ceo.identity import sha256_hex
from dvg_obs_ceo.resources import AnsatzStructure
from dvg_obs_ceo.telemetry import ResourceSnapshot, WorkCounters
from dvg_obs_ceo.transaction import AcceptanceEvidence, CompressionRuntime, OptimizerOutcome, evaluate_acceptance
from dvg_obs_ceo.v5_ledger import V5WorkCounters, versioned_id
from dvg_obs_ceo.v5_nested_transaction import PathCheckpointStore
from dvg_obs_ceo.v5_sequential import CatalogSnapshot, SequentialCandidate, SequentialExecution, WidthOneConfig, run_width_one
from dvg_obs_ceo.v5_sequential_audit import run_audit


def resources(parameters: int) -> ResourceSnapshot:
    return ResourceSnapshot(parameters * 10, parameters * 3, parameters * 15, parameters, parameters, "s3-test-v1", sha256_hex({"parameters": parameters}))


def make_runtime() -> CompressionRuntime:
    return CompressionRuntime.create(
        ansatz=AnsatzStructure.create([1, 2, 3], [0.1, 0.2, 0.3], [3]),
        energy_hartree=-1.0,
        gradient=[0.0, 0.0, 0.0],
        inverse_hessian=np.eye(3),
        statevector=[1.0, 0.0],
        work=WorkCounters(),
        adapt_iteration=1,
        metadata={"resource_structure_digest": resources(3).structure_digest, "budget_reference_energy_hartree": -1.0},
    )


def builder(runtime: CompressionRuntime) -> CatalogSnapshot:
    dimension = len(runtime.ansatz.indices)
    candidates = () if dimension <= 1 else (
        SequentialCandidate(versioned_id("candidate-v5", {"dimension": dimension}), 3e-5, {"dimension": dimension}),
    )
    return CatalogSnapshot.create(runtime.snapshot().snapshot_digest, candidates)


def executor(runtime: CompressionRuntime, candidate: SequentialCandidate, round_index: int, exact_attempt: int) -> SequentialExecution:
    before = resources(len(runtime.ansatz.indices))
    source_energy = runtime.energy_hartree
    new_dimension = len(runtime.ansatz.indices) - 1
    runtime.ansatz = AnsatzStructure.create(runtime.ansatz.indices[:new_dimension], runtime.ansatz.coefficients[:new_dimension], [new_dimension])
    runtime.energy_hartree = -1.0 + round_index * 3e-5
    runtime.gradient = np.zeros(new_dimension)
    runtime.inverse_hessian = np.eye(new_dimension)
    runtime.metadata["resource_structure_digest"] = resources(new_dimension).structure_digest
    after = resources(new_dimension)
    decision = evaluate_acceptance(AcceptanceEvidence(
        source_energy_hartree=source_energy,
        budget_reference_energy_hartree=-1.0,
        candidate_energy_hartree=runtime.energy_hartree,
        independent_energy_hartree=runtime.energy_hartree,
        independent_state_fidelity=1.0,
        constraint_residual=0.0,
        kkt_residual=0.0,
        before_resources=before,
        after_resources=after,
        full_resource_recount_succeeded=True,
        transformation_semantics_validated=True,
        primary_optimizer=OptimizerOutcome(True, "0", "ok", True),
        fallback_optimizer=None,
    ))
    digest = runtime.snapshot().snapshot_digest
    return SequentialExecution(
        candidate.candidate_id,
        decision,
        V5WorkCounters(energy_evaluations=exact_attempt, exact_vqe_attempts=exact_attempt, attempted_rounds=round_index, accepted_rounds=round_index),
        "state-v1:" + digest,
        "problem-v1:" + "2" * 64,
        "measurement-v1:" + sha256_hex({"state": digest}),
        after,
    )


def initialized(tmp_path: Path):
    runtime = make_runtime()
    source_catalog = builder(runtime)
    store = PathCheckpointStore(tmp_path / "path", versioned_id("path-v5", "s3"))
    store.initialize(
        runtime,
        work=V5WorkCounters(),
        state_preparation_id="state-v1:" + runtime.snapshot().snapshot_digest,
        problem_id="problem-v1:" + "2" * 64,
        measurement_context_id="measurement-v1:" + "3" * 64,
        catalog_digest=source_catalog.catalog_digest,
        resource_snapshot=resources(3),
    )
    return runtime, store


def test_width_one_commits_two_rounds_and_rebuilds_catalog(tmp_path: Path) -> None:
    runtime, store = initialized(tmp_path)
    result = run_width_one(runtime, store, catalog_builder=builder, candidate_executor=executor, config=WidthOneConfig(3, 3))
    assert result["accepted_rounds"] == 2
    assert result["stop_reason"] == "no-eligible-candidate"
    assert len(store.checkpoints()) == 3
    assert all(item["catalog_digest_before"] != item["catalog_digest_after"] for item in result["trajectory"])
    assert result["actual_cumulative_energy_increase_hartree"] == pytest.approx(6e-5, abs=1e-15)


def test_width_one_rejected_second_round_keeps_first_commit(tmp_path: Path) -> None:
    runtime, store = initialized(tmp_path)

    def reject_second(state, candidate, round_index, exact_attempt):
        execution = executor(state, candidate, round_index, exact_attempt)
        if round_index == 2:
            decision = replace(execution.decision, accepted=False, rejection_reasons=("injected",), checks={**execution.decision.checks, "injected": False})
            return replace(execution, decision=decision, work=replace(execution.work, accepted_rounds=1))
        return execution

    result = run_width_one(runtime, store, catalog_builder=builder, candidate_executor=reject_second, config=WidthOneConfig(3, 3))
    assert result["accepted_rounds"] == 1
    assert result["stop_reason"] == "width-one-candidate-rejected"
    assert len(store.checkpoints()) == 2
    assert len(runtime.ansatz.indices) == 2


def test_width_one_energy_cap_stops_before_execution(tmp_path: Path) -> None:
    runtime, store = initialized(tmp_path)
    result = run_width_one(runtime, store, catalog_builder=builder, candidate_executor=executor, config=WidthOneConfig(3, 3, 1e-5))
    assert result["stop_reason"] == "predicted-cumulative-energy-budget"
    assert result["exact_attempts"] == 0
    assert store.latest().round_index == 0


def test_v5_s3_independent_replay_audit() -> None:
    result = run_audit()
    assert result["passed"]
    assert all(result["checks"].values())
