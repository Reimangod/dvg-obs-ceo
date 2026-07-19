"""Registered transaction and hard-crash recovery probe for S7."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time
from typing import Any

import numpy as np

from .resources import AnsatzStructure
from .telemetry import ResourceSnapshot, WorkCounters
from .transaction import (
    AcceptanceEvidence,
    CompressionRuntime,
    CompressionTransaction,
    OptimizerOutcome,
    TransactionDeadlineExceeded,
    TransactionError,
    evaluate_acceptance,
    recover_orphaned_transaction,
)


def _resource(
    cnot: int,
    cnot_depth: int,
    total_depth: int,
    parameters: int,
    blocks: int,
    digest_character: str,
) -> ResourceSnapshot:
    return ResourceSnapshot(
        cnot,
        cnot_depth,
        total_depth,
        parameters,
        blocks,
        "s7-probe-counter-v1",
        digest_character * 64,
    )


def _runtime() -> CompressionRuntime:
    random.seed(703)
    np.random.seed(703)
    return CompressionRuntime.create(
        ansatz=AnsatzStructure.create([4, 5], [0.2, -0.1], [2]),
        energy_hartree=-1.0,
        gradient=[1e-9, -1e-9],
        inverse_hessian=np.eye(2),
        statevector=[1.0, 0.0, 0.0, 0.0],
        work=WorkCounters(energy_evaluations=3, gradient_vector_evaluations=2),
        adapt_iteration=1,
        metadata={
            "run_id": "s7-probe",
            "resource_structure_digest": "a" * 64,
        },
    )


def _mutate(runtime: CompressionRuntime) -> None:
    runtime.ansatz = AnsatzStructure.create([4], [0.15], [1])
    runtime.energy_hartree = -0.99995
    runtime.gradient = np.asarray([1e-10], dtype=np.float64)
    runtime.inverse_hessian = np.asarray([[0.7]], dtype=np.float64)
    runtime.statevector = np.asarray([1.0, 0.0, 0.0, 0.0], dtype=np.complex128)
    runtime.work = WorkCounters(energy_evaluations=8, gradient_vector_evaluations=5)
    runtime.metadata["candidate"] = "accepted"
    runtime.metadata["resource_structure_digest"] = "b" * 64


def _decision(*, safe: bool = True):
    after = _resource(11, 7, 20, 1, 1, "b") if safe else _resource(21, 11, 31, 3, 3, "b")
    return evaluate_acceptance(
        AcceptanceEvidence(
            baseline_energy_hartree=-1.0,
            candidate_energy_hartree=-0.99995 if safe else -0.9,
            independent_energy_hartree=-0.99995 if safe else -0.9,
            fci_energy_hartree=-1.0,
            independent_state_fidelity=1.0 if safe else 0.8,
            constraint_residual=1e-12 if safe else 1e-2,
            kkt_residual=1e-10 if safe else 1e-2,
            before_resources=_resource(20, 10, 30, 2, 2, "a"),
            after_resources=after,
            full_resource_recount_succeeded=True,
            transformation_semantics_validated=True,
            primary_optimizer=OptimizerOutcome(safe, "0" if safe else "2", "probe", True),
            fallback_optimizer=None,
        )
    )


def _hard_crash_worker(root: Path) -> None:
    runtime = _runtime()
    transaction = CompressionTransaction(runtime, root, transaction_id="hard-crash")
    transaction.__enter__()
    transaction.stage_json("worker-ready.json", {"ready": True})
    _mutate(runtime)
    # Deliberately bypass __exit__, finally blocks, and in-memory rollback.
    os._exit(17)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_probe(artifact_path: Path) -> dict[str, Any]:
    if artifact_path.exists():
        raise FileExistsError(f"refusing to overwrite S7 artifact: {artifact_path}")
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dvg-obs-s7-") as temporary:
        root = Path(temporary)

        hard = subprocess.run(
            [sys.executable, "-m", "dvg_obs_ceo.s7_probe", "--hard-crash-worker", str(root)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if hard.returncode != 17:
            raise RuntimeError(f"hard-crash worker returned {hard.returncode}: {hard.stderr}")
        orphan_snapshot = root / ".staging" / "hard-crash" / "snapshot.json"
        if not orphan_snapshot.is_file():
            raise RuntimeError("hard-crash worker did not durably stage its snapshot")
        expected_digest = json.loads(orphan_snapshot.read_text(encoding="utf-8"))["snapshot_digest"]
        recovered_runtime = _runtime()
        _mutate(recovered_runtime)
        recovered_path = recover_orphaned_transaction(recovered_runtime, root, "hard-crash")
        recovery_digest = recovered_runtime.snapshot().snapshot_digest
        if recovery_digest != expected_digest:
            raise RuntimeError("hard-crash recovery was not bitwise-equivalent")

        committed_runtime = _runtime()
        with CompressionTransaction(
            committed_runtime, root, transaction_id="accepted"
        ) as transaction:
            _mutate(committed_runtime)
            committed_path = transaction.commit(_decision())

        failures: dict[str, dict[str, Any]] = {}
        for name in ("exception", "nan", "partial-write"):
            runtime = _runtime()
            before = runtime.snapshot().snapshot_digest
            try:
                with CompressionTransaction(runtime, root, transaction_id=name) as transaction:
                    _mutate(runtime)
                    random.random()
                    np.random.random()
                    if name == "exception":
                        raise RuntimeError("injected exception")
                    if name == "nan":
                        runtime.gradient = np.asarray([float("nan")])
                        transaction.commit(_decision())
                    (transaction.staging / "partial.bin").write_bytes(b"incomplete")
                    raise RuntimeError("injected partial write")
            except (RuntimeError, TransactionError) as error:
                after = runtime.snapshot().snapshot_digest
                failures[name] = {
                    "restored": before == after,
                    "exception_type": type(error).__name__,
                    "failed_artifact_retained": (root / "failed" / name).is_dir(),
                }
            if not all(
                (failures[name]["restored"], failures[name]["failed_artifact_retained"])
            ):
                raise RuntimeError(f"failure injection did not restore {name}")

        timeout_runtime = _runtime()
        timeout_before = timeout_runtime.snapshot().snapshot_digest
        try:
            with CompressionTransaction(
                timeout_runtime,
                root,
                transaction_id="timeout",
                timeout_seconds=1e-6,
            ) as transaction:
                _mutate(timeout_runtime)
                time.sleep(0.001)
                transaction.check_deadline()
        except TransactionDeadlineExceeded:
            pass
        timeout_restored = timeout_runtime.snapshot().snapshot_digest == timeout_before
        if not timeout_restored:
            raise RuntimeError("deadline injection did not restore runtime")

        rejected_runtime = _runtime()
        rejected_before = rejected_runtime.snapshot().snapshot_digest
        rejected = _decision(safe=False)
        try:
            with CompressionTransaction(
                rejected_runtime, root, transaction_id="rejected"
            ) as transaction:
                _mutate(rejected_runtime)
                transaction.commit(rejected)
        except TransactionError:
            pass
        rejection_restored = rejected_runtime.snapshot().snapshot_digest == rejected_before
        if not rejection_restored or rejected.accepted:
            raise RuntimeError("rejected decision was not safely rolled back")

        artifact = {
            "schema_version": "1.0.0",
            "artifact_kind": "s7-transaction-hard-crash-probe",
            "hard_crash": {
                "exit_code": hard.returncode,
                "durable_snapshot_sha256": _digest(recovered_path / "snapshot.json"),
                "expected_snapshot_digest": expected_digest,
                "recovered_snapshot_digest": recovery_digest,
                "bitwise_equivalent_recovery": recovery_digest == expected_digest,
                "failed_artifact_retained": recovered_path.is_dir(),
            },
            "accepted_commit": {
                "committed": committed_path.is_dir(),
                "commit_record_sha256": _digest(committed_path / "commit.json"),
            },
            "failure_injections": failures,
            "deadline": {"restored": timeout_restored},
            "rejected_acceptance": {
                "restored": rejection_restored,
                "rejection_reasons": list(rejected.rejection_reasons),
            },
            "acceptance_checks": list(_decision().checks),
            "claim_boundary": [
                "S7 establishes transaction durability and independent acceptance plumbing only.",
                "Synthetic energies and resources in this probe are not molecular performance results.",
                "Hard-crash recovery is fail-closed: an orphan staging directory is never committed.",
            ],
        }
    temporary_output = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    temporary_output.write_text(
        json.dumps(artifact, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_output, artifact_path)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--hard-crash-worker", type=Path)
    arguments = parser.parse_args()
    if arguments.hard_crash_worker is not None:
        _hard_crash_worker(arguments.hard_crash_worker)
    if arguments.artifact is None:
        parser.error("--artifact is required outside hard-crash worker mode")
    result = run_probe(arguments.artifact)
    print(json.dumps({"artifact": str(arguments.artifact), "hard_crash": result["hard_crash"]}))


if __name__ == "__main__":
    main()
