"""V5-S8 width-two molecular multi-trajectory calibration on LiH."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .baseline import ROOT
from .identity import canonical_json_bytes
from .polishing import TrustNCGConfig
from .resources import AnsatzStructure, evaluate_full_circuit_resources, paper_era_backend
from .s8_probe import _state_vector
from .s10_lih import _algorithm as _lih_algorithm
from .telemetry import WorkCounters
from .transaction import CompressionRuntime, RuntimeSnapshot
from .v4_lih import _energy
from .v5_conditional_polishing import ConditionalPolishingConfig
from .v5_ledger import V5WorkCounters, versioned_id
from .v5_multitrajectory import (
    ENDPOINTS,
    ExpansionOutcome,
    ExpansionProposal,
    MultiTrajectoryConfig,
    TrajectoryState,
    run_multitrajectory,
)
from .v5_s8_h4_width1 import MolecularWidthOneAdapter, _measurement_id, _state_id
from .v5_s8_lih_width1 import CHECKPOINT, _load_checkpoint


RUNNER_VERSION = "v5-s8-lih-width2-multitrajectory-v1"
OUTPUT = ROOT / "artifacts/v5/s8/lih-width2-multitrajectory-v1"
REQUIRED_THREADS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


class V5S8LiHMultiTrajectoryError(RuntimeError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _clone(snapshot: RuntimeSnapshot) -> CompressionRuntime:
    return CompressionRuntime.create(
        ansatz=snapshot.ansatz,
        energy_hartree=snapshot.energy_hartree,
        gradient=snapshot.gradient,
        inverse_hessian=snapshot.inverse_hessian,
        statevector=snapshot.statevector,
        work=snapshot.work,
        adapt_iteration=snapshot.adapt_iteration,
        metadata=snapshot.metadata,
    )


def _work_delta(after: V5WorkCounters, before: V5WorkCounters) -> dict[str, int]:
    a, b = after.to_dict(), before.to_dict()
    result = {key: a[key] - b[key] for key in a}
    if any(value < 0 for value in result.values()):
        raise V5S8LiHMultiTrajectoryError("branch work counter regressed")
    result["exact_vqe_attempts"] = 1
    return result


def _sum_work(*items: dict[str, int]) -> dict[str, int]:
    names = set().union(*(item.keys() for item in items))
    return {
        name: sum(int(item.get(name, 0)) for item in items)
        for name in sorted(names)
    }


def _load_checkpoint_path(path: Path) -> dict[str, Any]:
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    observed = checkpoint.pop("checkpoint_digest")
    if _digest(checkpoint) != observed:
        raise V5S8LiHMultiTrajectoryError(
            f"checkpoint digest mismatch: {path}"
        )
    checkpoint["checkpoint_digest"] = observed
    return checkpoint


def _effective_energy_budget(
    checkpoint: dict[str, Any],
    *,
    enforce_chemical_accuracy: bool,
) -> tuple[float, float | None]:
    algorithmic_energy_budget = 1e-4
    if not enforce_chemical_accuracy:
        return algorithmic_energy_budget, None
    chemical_accuracy_margin = (
        float(checkpoint["exact_energy_hartree"])
        + float(checkpoint["chemical_accuracy_hartree"])
        - float(checkpoint["energy_hartree"])
    )
    if not np.isfinite(chemical_accuracy_margin) or chemical_accuracy_margin <= 0:
        raise V5S8LiHMultiTrajectoryError(
            "source checkpoint is not strictly inside chemical accuracy"
        )
    return min(
        algorithmic_energy_budget,
        float(np.nextafter(chemical_accuracy_margin, -np.inf)),
    ), chemical_accuracy_margin


def run(
    output: Path = OUTPUT,
    *,
    runner_version: str = RUNNER_VERSION,
    beam_dominance: str = "resources-only",
    artifact_kind: str = "v5-s8-lih-width2-multitrajectory",
    width: int = 2,
    top_k_per_parent: int = 2,
    maximum_rounds: int = 2,
    maximum_exact_attempts: int = 4,
    checkpoint_path: Path | None = None,
    algorithm_factory: Callable[[dict[str, Any]], tuple[Any, Any]] | None = None,
    case_id: str = "lih-3.0",
    hamiltonian_context: str = "stored-pinned-lih-3.0-angstrom-sto-3g",
    enforce_chemical_accuracy: bool = False,
    execution_freeze: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if output.exists():
        raise V5S8LiHMultiTrajectoryError("refusing to overwrite width-two output")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if threads != REQUIRED_THREADS:
        raise V5S8LiHMultiTrajectoryError(f"single-thread freeze missing: {threads}")
    if checkpoint_path is None:
        checkpoint = _load_checkpoint()
        algorithm, pool, _ = _lih_algorithm()
    else:
        checkpoint = _load_checkpoint_path(checkpoint_path)
        if algorithm_factory is None:
            raise V5S8LiHMultiTrajectoryError(
                "external checkpoint requires an algorithm factory"
            )
        algorithm, pool = algorithm_factory(checkpoint["case"])
    algorithm.initialize()
    source_ansatz = AnsatzStructure.create(
        checkpoint["ansatz_indices"], checkpoint["ansatz_coefficients"], checkpoint["iteration_counts"]
    )
    source_statevector = _state_vector(
        algorithm, source_ansatz.coefficients, source_ansatz.indices
    )
    source_energy = _energy(
        algorithm, np.asarray(source_ansatz.coefficients), source_ansatz.indices
    )
    source_resources = evaluate_full_circuit_resources(
        pool, source_ansatz, paper_era_backend()
    ).snapshot
    if (
        abs(source_energy - checkpoint["energy_hartree"]) > 1e-10
        or asdict(source_resources) != checkpoint["resources"]["snapshot"]
    ):
        raise V5S8LiHMultiTrajectoryError("LiH source reconstruction drift")
    source_runtime = CompressionRuntime.create(
        ansatz=source_ansatz,
        energy_hartree=checkpoint["energy_hartree"],
        gradient=checkpoint["gradient"],
        inverse_hessian=checkpoint["recycled_inverse_hessian"],
        statevector=source_statevector,
        work=WorkCounters(),
        adapt_iteration=checkpoint["adapt_iteration"],
        metadata={
            "run_id": runner_version,
            "resource_structure_digest": source_resources.structure_digest,
            "budget_reference_energy_hartree": checkpoint["energy_hartree"],
            "checkpoint_digest": checkpoint["checkpoint_digest"],
        },
    )
    algorithmic_energy_budget = 1e-4
    effective_energy_budget, chemical_accuracy_margin = (
        _effective_energy_budget(
            checkpoint,
            enforce_chemical_accuracy=enforce_chemical_accuracy,
        )
    )
    problem_id = versioned_id("problem-v1", {
        "case_id": case_id,
        "checkpoint_digest": checkpoint["checkpoint_digest"],
        "hamiltonian_context": hamiltonian_context,
    })
    source_state_id = _state_id(source_runtime)
    source_path_id = versioned_id("path-v5", {
        "runner_version": runner_version,
        "execution_freeze": execution_freeze,
        "checkpoint_digest": checkpoint["checkpoint_digest"],
        "role": "source",
    })
    source_snapshot = source_runtime.snapshot()
    source_trajectory = TrajectoryState(
        path_id=source_path_id,
        state_preparation_id=source_state_id,
        problem_id=problem_id,
        checkpoint_digest=source_snapshot.snapshot_digest,
        cumulative_energy_increase_hartree=0.0,
        resources=source_resources,
        candidate_history=(),
        diversity_key="source",
    )
    runtimes: dict[str, CompressionRuntime] = {source_path_id: source_runtime}
    adapters: dict[str, MolecularWidthOneAdapter] = {}
    candidates_by_path: dict[str, dict[str, Any]] = {}
    catalog_work: dict[str, V5WorkCounters] = {}
    branch_records: list[dict[str, Any]] = []

    def adapter_for(path_id: str) -> MolecularWidthOneAdapter:
        if path_id not in adapters:
            adapter = MolecularWidthOneAdapter(
                algorithm,
                pool,
                problem_id=problem_id,
                screening_budget_hartree=effective_energy_budget,
                enable_conditional_polishing=True,
                polishing_config=ConditionalPolishingConfig(
                    polisher=TrustNCGConfig(gradient_l2_tolerance=1e-8)
                ),
                enable_joint_search=True,
            )
            catalog = adapter.catalog_builder(runtimes[path_id])
            adapters[path_id] = adapter
            candidates_by_path[path_id] = {
                item.candidate_id: item for item in catalog.candidates
            }
            catalog_work[path_id] = adapter.work
        return adapters[path_id]

    def catalog_builder(parent: TrajectoryState):
        adapter_for(parent.path_id)
        candidates = candidates_by_path[parent.path_id]
        proposals = []
        for rank, candidate in enumerate(candidates.values()):
            proposals.append(ExpansionProposal.create(
                parent_path_id=parent.path_id,
                candidate_id=candidate.candidate_id,
                exact_task_payload={
                    "parent_checkpoint_digest": parent.checkpoint_digest,
                    "candidate_id": candidate.candidate_id,
                    "evidence": candidate.evidence,
                },
                proposed_state_preparation_id=versioned_id("state-v1", {
                    "parent_state": parent.state_preparation_id,
                    "candidate_id": candidate.candidate_id,
                    "role": "structural-proposal-before-exact-coefficients",
                }),
                endpoint=ENDPOINTS[rank % len(ENDPOINTS)],
                screening_rank=rank,
                predicted_loss_hartree=candidate.predicted_loss_hartree,
            ))
        return proposals

    def exact_executor(
        proposal: ExpansionProposal,
        parent: TrajectoryState,
        exact_attempt: int,
    ) -> ExpansionOutcome:
        adapter = adapter_for(parent.path_id)
        adapter.work = catalog_work[parent.path_id]
        candidate = candidates_by_path[parent.path_id][proposal.candidate_id]
        trial = _clone(runtimes[parent.path_id].snapshot())
        parent_digest_before = runtimes[parent.path_id].snapshot().snapshot_digest
        execution = adapter.candidate_executor(
            trial, candidate, parent_round(parent) + 1, exact_attempt
        )
        work = _work_delta(execution.work, catalog_work[parent.path_id])
        parent_unchanged = (
            runtimes[parent.path_id].snapshot().snapshot_digest == parent_digest_before
        )
        record = {
            "proposal_id": proposal.proposal_id,
            "parent_path_id": parent.path_id,
            "candidate_id": candidate.candidate_id,
            "candidate_evidence": candidate.evidence,
            "decision": asdict(execution.decision),
            "work": work,
            "parent_runtime_unchanged": parent_unchanged,
            "attempt_record": adapter.attempt_records[-1],
        }
        branch_records.append(record)
        if not parent_unchanged:
            raise V5S8LiHMultiTrajectoryError("branch executor mutated parent runtime")
        if not execution.decision.accepted:
            return ExpansionOutcome(
                proposal.proposal_id, False, None, None, None, None, None,
                work, tuple(execution.decision.rejection_reasons),
            )
        child_path_id = versioned_id("path-v5", {
            "parent_path_id": parent.path_id,
            "candidate_id": proposal.candidate_id,
            "final_state_preparation_id": execution.state_preparation_id,
        })
        runtimes[child_path_id] = trial
        return ExpansionOutcome(
            proposal.proposal_id,
            True,
            execution.state_preparation_id,
            trial.snapshot().snapshot_digest,
            trial.energy_hartree - checkpoint["energy_hartree"],
            execution.resource_snapshot,
            _digest({
                "atomic_candidate_ids": candidate.evidence["atomic_candidate_ids"],
                "parent_history": list(parent.candidate_history),
            }),
            work,
        )

    def parent_round(parent: TrajectoryState) -> int:
        return len(parent.candidate_history)

    result = run_multitrajectory(
        source_trajectory,
        catalog_builder=catalog_builder,
        exact_executor=exact_executor,
        config=MultiTrajectoryConfig(
            width=width,
            top_k_per_parent=top_k_per_parent,
            maximum_rounds=maximum_rounds,
            maximum_exact_attempts=maximum_exact_attempts,
            endpoint_quota=1,
            cumulative_energy_budget_hartree=effective_energy_budget,
            beam_dominance=beam_dominance,
        ),
    )
    exact_attempt_work = dict(result["aggregate_work"])
    catalog_work_by_path = {
        path_id: work.to_dict() for path_id, work in sorted(catalog_work.items())
    }
    all_catalog_work = _sum_work(*catalog_work_by_path.values())
    result["exact_attempt_work"] = exact_attempt_work
    result["catalog_work_by_path"] = catalog_work_by_path
    result["catalog_work"] = all_catalog_work
    result["aggregate_work"] = _sum_work(exact_attempt_work, all_catalog_work)
    result["work_accounting_rule"] = (
        "every parent catalog once, including zero-candidate terminal catalogs; "
        "every exact attempt once"
    )
    result.pop("result_digest")
    result["result_digest"] = _digest(result)
    payload = {
        "schema_version": "1.0.0",
        "artifact_kind": artifact_kind,
        "runner_version": runner_version,
        "source_energy_hartree": checkpoint["energy_hartree"],
        "case_id": case_id,
        "source_resources": asdict(source_resources),
        "energy_guard": {
            "algorithmic_source_relative_budget_hartree": (
                algorithmic_energy_budget
            ),
            "chemical_accuracy_margin_hartree": chemical_accuracy_margin,
            "effective_source_relative_budget_hartree": effective_energy_budget,
            "chemical_accuracy_enforced": enforce_chemical_accuracy,
        },
        "result": result,
        "branch_records": branch_records,
        "catalog_diagnostics_by_path": {
            path_id: adapter._selection_cache for path_id, adapter in adapters.items()
        },
        "source_runtime_unchanged": source_runtime.snapshot().snapshot_digest == source_snapshot.snapshot_digest,
        "claim_boundary": [
            "Known LiH width calibration only; not confirmatory.",
            "All branches use isolated runtimes and exact acceptance.",
            "Work counters are not paper Measurement Cost."
        ],
        "paper_measurement_cost": None,
    }
    payload["result_digest"] = _digest(payload)
    output.mkdir(parents=True)
    (output / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "winner_resources": result["result"]["winner_resources"],
        "winner_energy_increase": result["result"]["winner_cumulative_energy_increase_hartree"],
        "exact_attempts": result["result"]["exact_attempts"],
    }, sort_keys=True))
