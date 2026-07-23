"""Independent width/dedup/determinism audit for V5-S7."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import numpy as np

from .identity import sha256_hex
from .resources import AnsatzStructure
from .telemetry import ResourceSnapshot, WorkCounters
from .transaction import AcceptanceEvidence, CompressionRuntime, OptimizerOutcome, evaluate_acceptance
from .v3_protocol import _write_exclusive
from .v5_ledger import V5WorkCounters, versioned_id
from .v5_multitrajectory import ExpansionOutcome, ExpansionProposal, MultiTrajectoryConfig, TrajectoryState, run_multitrajectory
from .v5_nested_transaction import PathCheckpointStore
from .v5_sequential import CatalogSnapshot, SequentialCandidate, SequentialExecution, WidthOneConfig, run_width_one


def _resources(dimension: int) -> ResourceSnapshot:
    return ResourceSnapshot(
        dimension * 10,
        dimension * 3,
        dimension * 15,
        dimension,
        dimension,
        "v5-s7-audit-counter-v1",
        sha256_hex({"dimension": dimension}),
    )


def _runtime() -> CompressionRuntime:
    return CompressionRuntime.create(
        ansatz=AnsatzStructure.create([1, 2, 3], [0.1, 0.2, 0.3], [3]),
        energy_hartree=-1.0,
        gradient=[0.0, 0.0, 0.0],
        inverse_hessian=np.eye(3),
        statevector=[1.0, 0.0],
        work=WorkCounters(),
        adapt_iteration=1,
        metadata={
            "resource_structure_digest": _resources(3).structure_digest,
            "budget_reference_energy_hartree": -1.0,
        },
    )


def _candidate_id(dimension: int) -> str:
    return versioned_id("candidate-v5", {"dimension": dimension})


def _run_s3_width_one() -> dict[str, Any]:
    runtime = _runtime()

    def builder(state):
        dimension = len(state.ansatz.indices)
        candidates = () if dimension <= 1 else (
            SequentialCandidate(_candidate_id(dimension), 3e-5, {"dimension": dimension}),
        )
        return CatalogSnapshot.create(state.snapshot().snapshot_digest, candidates)

    def executor(state, candidate, round_index, exact_attempt):
        source_energy = state.energy_hartree
        before = _resources(len(state.ansatz.indices))
        dimension = len(state.ansatz.indices) - 1
        state.ansatz = AnsatzStructure.create(state.ansatz.indices[:dimension], state.ansatz.coefficients[:dimension], [dimension])
        state.energy_hartree = -1.0 + round_index * 3e-5
        state.gradient = np.zeros(dimension)
        state.inverse_hessian = np.eye(dimension)
        after = _resources(dimension)
        state.metadata["resource_structure_digest"] = after.structure_digest
        decision = evaluate_acceptance(AcceptanceEvidence(
            source_energy_hartree=source_energy,
            budget_reference_energy_hartree=-1.0,
            candidate_energy_hartree=state.energy_hartree,
            independent_energy_hartree=state.energy_hartree,
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
        digest = state.snapshot().snapshot_digest
        return SequentialExecution(
            candidate.candidate_id,
            decision,
            V5WorkCounters(energy_evaluations=exact_attempt, exact_vqe_attempts=exact_attempt, attempted_rounds=round_index, accepted_rounds=round_index),
            "state-v1:" + digest,
            "problem-v1:" + sha256_hex("problem"),
            "measurement-v1:" + sha256_hex({"state": digest}),
            after,
        )

    with TemporaryDirectory() as directory:
        catalog = builder(runtime)
        store = PathCheckpointStore(Path(directory) / "path", versioned_id("path-v5", "s7-audit"))
        store.initialize(
            runtime,
            work=V5WorkCounters(),
            state_preparation_id="state-v1:" + runtime.snapshot().snapshot_digest,
            problem_id="problem-v1:" + sha256_hex("problem"),
            measurement_context_id="measurement-v1:" + sha256_hex("measurement"),
            catalog_digest=catalog.catalog_digest,
            resource_snapshot=_resources(3),
        )
        return run_width_one(runtime, store, catalog_builder=builder, candidate_executor=executor, config=WidthOneConfig(3, 3))


def _run_s7(width: int, reverse: bool = False) -> dict[str, Any]:
    problem = "problem-v1:" + sha256_hex("problem")
    source = TrajectoryState(
        versioned_id("path-v5", "s7-source"),
        "state-v1:" + sha256_hex({"dimension": 3, "source": True}),
        problem,
        sha256_hex("checkpoint-source"),
        0.0,
        _resources(3),
        (),
        "dimension-3",
    )

    def builder(parent):
        dimension = 3 - len(parent.candidate_history)
        if dimension <= 1:
            return ()
        primary = ExpansionProposal.create(
            parent_path_id=parent.path_id,
            candidate_id=_candidate_id(dimension),
            exact_task_payload={"parent": parent.state_preparation_id, "dimension": dimension - 1},
            proposed_state_preparation_id="state-v1:" + sha256_hex({"parent": parent.state_preparation_id, "dimension": dimension - 1}),
            endpoint="cnot_count",
            screening_rank=0,
            predicted_loss_hartree=3e-5,
        )
        duplicate = ExpansionProposal.create(
            parent_path_id=parent.path_id,
            candidate_id=versioned_id("candidate-v5", {"duplicate": dimension}),
            exact_task_payload={"different-task": dimension},
            proposed_state_preparation_id=primary.proposed_state_preparation_id,
            endpoint="parameter_count",
            screening_rank=1,
            predicted_loss_hartree=3e-5,
        )
        values = (primary, duplicate)
        return tuple(reversed(values)) if reverse else values

    def executor(proposal, parent, attempt):
        dimension = 3 - len(parent.candidate_history) - 1
        return ExpansionOutcome(
            proposal.proposal_id,
            True,
            "state-v1:" + sha256_hex({"dimension": dimension, "history": parent.candidate_history}),
            sha256_hex({"checkpoint": dimension, "attempt": attempt}),
            attempt * 3e-5,
            _resources(dimension),
            f"dimension-{dimension}",
            {"energy_evaluations": 1, "exact_vqe_attempts": 1},
        )

    return run_multitrajectory(
        source,
        catalog_builder=builder,
        exact_executor=executor,
        config=MultiTrajectoryConfig(width, 2, 3, 3),
    )


def run_audit() -> dict[str, Any]:
    s3 = _run_s3_width_one()
    width1 = _run_s7(1)
    forward = _run_s7(2)
    reverse = _run_s7(2, reverse=True)
    s3_history = [item["candidate_id"] for item in s3["trajectory"] if item["accepted"]]
    checks = {
        "width1_candidate_history_matches_s3": width1["winner_candidate_history"] == s3_history,
        "width1_resources_match_s3": all(
            width1["winner_resources"][field] == s3["trajectory"][-1]["resources"][field]
            for field in (
                "cnot_count", "cnot_depth", "total_depth", "parameter_count",
                "logical_block_count",
            )
        ),
        "width1_energy_matches_s3": abs(width1["winner_cumulative_energy_increase_hartree"] - s3["actual_cumulative_energy_increase_hartree"]) <= 1e-15,
        "width1_exact_attempts_match_s3": width1["exact_attempts"] == s3["exact_attempts"],
        "catalog_order_invariant": forward == reverse,
        "known_duplicate_states_not_evaluated_twice": all(item["duplicate_exact_tasks_skipped"] == 1 for item in forward["trajectory"]),
        "exact_attempt_work_matches_calls": forward["aggregate_work"]["exact_vqe_attempts"] == forward["exact_attempts"],
        "measurement_cost_not_relabelled": forward["paper_measurement_cost"] is None,
    }
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s7-multitrajectory-independent-audit",
        "passed": all(checks.values()),
        "checks": checks,
        "s3_width1_reference": s3,
        "s7_width1": width1,
        "s7_width2": forward,
        "claim_boundary": "Synthetic state-identity and search audit only; no molecular VQE performance claim.",
    }
    if not result["passed"]:
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise RuntimeError(f"V5-S7 audit failed: {failed}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-path", type=Path)
    arguments = parser.parse_args()
    result = run_audit()
    if arguments.artifact_path is not None:
        _write_exclusive(arguments.artifact_path, result)
    print(json.dumps({"passed": result["passed"], "checks": len(result["checks"])}, sort_keys=True))


if __name__ == "__main__":
    main()
