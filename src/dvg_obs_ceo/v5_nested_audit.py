"""Independent V5-S2 nested transaction and rollback audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import tempfile
from typing import Any

import numpy as np

from .resources import AnsatzStructure
from .telemetry import ResourceSnapshot, WorkCounters
from .transaction import (
    AcceptanceEvidence,
    CompressionRuntime,
    OptimizerOutcome,
    evaluate_acceptance,
)
from .v3_protocol import _write_exclusive
from .v5_ledger import V5WorkCounters, versioned_id
from .v5_nested_transaction import (
    NestedRoundTransaction,
    PathCheckpointStore,
    V5NestedTransactionError,
    recover_orphaned_round,
)


def _resource(character: str, parameters: int) -> ResourceSnapshot:
    return ResourceSnapshot(
        20 if parameters == 2 else 11,
        10 if parameters == 2 else 7,
        30 if parameters == 2 else 20,
        parameters,
        parameters,
        "v5-s2-synthetic-v1",
        character * 64,
    )


def _runtime() -> CompressionRuntime:
    random.seed(23)
    np.random.seed(23)
    return CompressionRuntime.create(
        ansatz=AnsatzStructure.create([4, 5], [0.2, -0.1], [2]),
        energy_hartree=-1.0,
        gradient=[1e-9, -1e-9],
        inverse_hessian=np.eye(2),
        statevector=[1.0, 0.0, 0.0, 0.0],
        work=WorkCounters(energy_evaluations=3, gradient_vector_evaluations=2),
        adapt_iteration=1,
        metadata={
            "resource_structure_digest": "a" * 64,
            "budget_reference_energy_hartree": -1.0,
        },
    )


def _mutate(runtime: CompressionRuntime) -> None:
    runtime.ansatz = AnsatzStructure.create([4], [0.15], [1])
    runtime.energy_hartree = -0.99995
    runtime.gradient = np.array([1e-10])
    runtime.inverse_hessian = np.array([[0.7]])
    runtime.statevector = np.array([1.0, 0.0, 0.0, 0.0], dtype=complex)
    runtime.work = WorkCounters(energy_evaluations=8, gradient_vector_evaluations=5)
    runtime.metadata["resource_structure_digest"] = "b" * 64


def _decision():
    return evaluate_acceptance(
        AcceptanceEvidence(
            source_energy_hartree=-1.0,
            budget_reference_energy_hartree=-1.0,
            candidate_energy_hartree=-0.99995,
            independent_energy_hartree=-0.99995,
            independent_state_fidelity=1.0,
            constraint_residual=1e-12,
            kkt_residual=1e-10,
            before_resources=_resource("a", 2),
            after_resources=_resource("b", 1),
            full_resource_recount_succeeded=True,
            transformation_semantics_validated=True,
            primary_optimizer=OptimizerOutcome(True, "0", "converged", True),
            fallback_optimizer=None,
        )
    )


def _initialized(root: Path):
    runtime = _runtime()
    store = PathCheckpointStore(root, versioned_id("path-v5", "s2-audit"))
    source = store.initialize(
        runtime,
        work=V5WorkCounters(energy_evaluations=2),
        state_preparation_id="state-v1:" + "1" * 64,
        problem_id="problem-v1:" + "2" * 64,
        measurement_context_id="measurement-v1:" + "3" * 64,
        catalog_digest="4" * 64,
        resource_snapshot=_resource("a", 2),
    )
    return runtime, store, source


def _commit_first(runtime: CompressionRuntime, store: PathCheckpointStore):
    with NestedRoundTransaction(runtime, store, 1, transaction_id="accepted-round") as transaction:
        _mutate(runtime)
        return transaction.commit(
            _decision(),
            work=V5WorkCounters(
                energy_evaluations=5,
                exact_vqe_attempts=1,
                attempted_rounds=1,
                accepted_rounds=1,
            ),
            state_preparation_id="state-v1:" + "5" * 64,
            problem_id="problem-v1:" + "2" * 64,
            measurement_context_id="measurement-v1:" + "6" * 64,
            catalog_digest="7" * 64,
            resource_snapshot=_resource("b", 1),
        )


def run_audit() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    evidence: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="v5-s2-audit-") as directory:
        root = Path(directory)

        runtime, store, source = _initialized(root / "rollback")
        first = _commit_first(runtime, store)
        committed_runtime = runtime.snapshot().snapshot_digest
        partial_preserved = False
        try:
            with NestedRoundTransaction(runtime, store, 2, transaction_id="failed-round") as transaction:
                runtime.energy_hartree = -0.4
                (transaction.staging / "partial.bin").write_bytes(b"partial-evidence")
                raise RuntimeError("injected later-round failure")
        except RuntimeError:
            partial_preserved = (store.failed / "failed-round" / "partial.bin").read_bytes() == b"partial-evidence"
        checks["later_failure_restores_last_commit"] = runtime.snapshot().snapshot_digest == committed_runtime
        checks["later_failure_does_not_erase_prior_commit"] = store.latest().checkpoint_digest == first.checkpoint_digest != source.checkpoint_digest
        checks["partial_failure_evidence_preserved"] = partial_preserved
        evidence["committed_chain_length"] = len(store.checkpoints())

        orphan_runtime, orphan_store, orphan_source = _initialized(root / "orphan")
        orphan = NestedRoundTransaction(orphan_runtime, orphan_store, 1, transaction_id="orphan-round")
        orphan.__enter__()
        _mutate(orphan_runtime)
        orphan._release_locks()
        recovered = recover_orphaned_round(orphan_runtime, orphan_store, "orphan-round")
        checks["orphan_restores_durable_parent"] = orphan_runtime.snapshot().snapshot_digest == orphan_source.runtime().snapshot_digest
        checks["orphan_recovery_is_auditable"] = (recovered / "recovery-rollback.json").is_file()

        concurrent_runtime, concurrent_store, _ = _initialized(root / "concurrent")
        concurrent_detected = False
        with NestedRoundTransaction(concurrent_runtime, concurrent_store, 1, transaction_id="outer"):
            try:
                with NestedRoundTransaction(concurrent_runtime, concurrent_store, 1, transaction_id="inner"):
                    pass
            except V5NestedTransactionError:
                concurrent_detected = True
        checks["concurrent_writer_rejected"] = concurrent_detected

        tamper_runtime, tamper_store, _ = _initialized(root / "tamper")
        _commit_first(tamper_runtime, tamper_store)
        checkpoint_path = tamper_store._round_directories()[-1] / "checkpoint.json"
        value = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        value["round_index"] = 99
        checkpoint_path.write_text(json.dumps(value), encoding="utf-8")
        tamper_detected = False
        try:
            tamper_store.checkpoints()
        except V5NestedTransactionError:
            tamper_detected = True
        checks["committed_checkpoint_tamper_detected"] = tamper_detected

    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s2-nested-transaction-independent-audit",
        "passed": all(checks.values()),
        "checks": checks,
        "evidence": evidence,
        "claim_boundary": "Synthetic nested-transaction durability and rollback evidence only; no molecular performance claim.",
    }
    if not result["passed"]:
        raise V5NestedTransactionError("V5-S2 independent audit failed")
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
