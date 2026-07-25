"""Synthetic stage-complete rollback audit for the V6-S9 transaction boundary."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from dvg_obs_ceo.identity import sha256_hex
from dvg_obs_ceo.resources import AnsatzStructure
from dvg_obs_ceo.telemetry import WorkCounters
from dvg_obs_ceo.transaction import (
    CompressionRuntime,
    CompressionTransaction,
    TransactionDeadlineExceeded,
)


FAULT_AUDIT_VERSION = "v6-s9-transaction-fault-audit-v1"
SCENARIOS = (
    "optimizer-exception",
    "optimizer-timeout",
    "nan-or-inf",
    "energy-mismatch",
    "gradient-mismatch",
    "malformed-circuit",
    "counter-mismatch",
    "serialization-partial-write",
    "signal-interrupt",
)


class InjectedS9Fault(RuntimeError):
    """An intentional S9 transaction-stage failure."""


def _runtime() -> CompressionRuntime:
    return CompressionRuntime.create(
        ansatz=AnsatzStructure.create([4, 5], [0.2, -0.1], [2]),
        energy_hartree=-1.0,
        gradient=[1e-9, -1e-9],
        inverse_hessian=np.eye(2),
        statevector=[1.0, 0.0, 0.0, 0.0],
        work=WorkCounters(
            energy_evaluations=3,
            gradient_vector_evaluations=2,
        ),
        adapt_iteration=1,
        metadata={
            "run_id": FAULT_AUDIT_VERSION,
            "resource_structure_digest": "a" * 64,
            "budget_reference_energy_hartree": -1.0,
        },
    )


def _mutate(runtime: CompressionRuntime) -> None:
    runtime.ansatz = AnsatzStructure.create([4], [0.15], [1])
    runtime.energy_hartree = -0.999
    runtime.gradient = np.asarray([1e-3], dtype=np.float64)
    runtime.inverse_hessian = np.asarray([[0.7]], dtype=np.float64)
    runtime.work = WorkCounters(
        energy_evaluations=8,
        gradient_vector_evaluations=5,
    )
    runtime.metadata["resource_structure_digest"] = "b" * 64


def _inject(
    scenario: str,
    transaction: CompressionTransaction,
    runtime: CompressionRuntime,
) -> None:
    _mutate(runtime)
    if scenario == "optimizer-timeout":
        transaction.started -= 61.0
        transaction.check_deadline()
    if scenario == "nan-or-inf":
        runtime.gradient = np.asarray([float("nan")])
        runtime.validate()
    if scenario == "serialization-partial-write":
        (transaction.staging / "partial.bin").write_bytes(b"incomplete")
        raise InjectedS9Fault("injected serialization failure")
    if scenario == "signal-interrupt":
        raise KeyboardInterrupt("injected interrupt")
    raise InjectedS9Fault(f"injected {scenario}")


def run_fault_audit() -> dict[str, Any]:
    records = []
    with tempfile.TemporaryDirectory(
        prefix="dvg-obs-v6-s9-fault-audit-"
    ) as temporary:
        root = Path(temporary)
        for scenario in SCENARIOS:
            runtime = _runtime()
            before = runtime.snapshot().snapshot_digest
            caught = None
            try:
                with CompressionTransaction(
                    runtime,
                    root,
                    transaction_id=scenario,
                    timeout_seconds=60.0,
                ) as transaction:
                    _inject(scenario, transaction, runtime)
            except BaseException as error:
                caught = type(error).__name__
            after = runtime.snapshot().snapshot_digest
            failed = root / "failed" / scenario
            record = {
                "scenario": scenario,
                "exception_type": caught,
                "snapshot_before": before,
                "snapshot_after": after,
                "rollback_exact": before == after,
                "failed_artifact_exists": failed.is_dir(),
                "rollback_record_exists": (
                    (failed / "rollback.json").is_file()
                    or (failed / "rollback-fallback.json").is_file()
                ),
                "committed_artifact_absent": not (
                    root / "committed" / scenario
                ).exists(),
            }
            record["passed"] = bool(
                caught
                and record["rollback_exact"]
                and record["failed_artifact_exists"]
                and record["rollback_record_exists"]
                and record["committed_artifact_absent"]
            )
            records.append(record)
    report = {
        "version": FAULT_AUDIT_VERSION,
        "scenarios": records,
        "all_passed": all(item["passed"] for item in records),
        "scientific_scope": (
            "Synthetic transaction lifecycle only; does not certify quantum "
            "energy, gradient, circuit, or resource numerical correctness."
        ),
    }
    report["audit_digest"] = sha256_hex(report)
    if not report["all_passed"]:
        failed = [
            item for item in records if not item["passed"]
        ]
        raise InjectedS9Fault(
            f"S9 rollback fault audit failed: {failed}"
        )
    return report
