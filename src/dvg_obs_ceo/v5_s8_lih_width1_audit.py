"""Independent audit of the frozen LiH ablation-C transfer."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping

import numpy as np

from .baseline import ROOT
from .identity import canonical_json_bytes
from .resources import evaluate_full_circuit_resources, paper_era_backend
from .s8_probe import _state_vector
from .s10_lih import _algorithm as _lih_algorithm
from .v4_lih import _energy, _gradient
from .v5_nested_transaction import PathCheckpointStore


RESULT = ROOT / "artifacts/v5/s8/lih-width1-transfer-v1/summary.json"
CODE_TAG = "dvg-obs-v5-s8-lih-width1-transfer-code-v1"


class V5S8LiHAuditError(RuntimeError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _forbidden(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            "actual" in str(key).lower() or "fci" in str(key).lower() or _forbidden(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_forbidden(item) for item in value)
    return False


def run_audit(*, recompute_quantum: bool = True) -> dict[str, Any]:
    summary = json.loads(RESULT.read_text(encoding="utf-8"))
    content = dict(summary)
    observed = content.pop("result_digest")
    round_zero = list((RESULT.parent / "path/rounds").glob("round-0000-*/checkpoint.json"))
    if len(round_zero) != 1:
        raise V5S8LiHAuditError("LiH source checkpoint is absent or ambiguous")
    source_record = json.loads(round_zero[0].read_text(encoding="utf-8"))
    store = PathCheckpointStore(RESULT.parent / "path", source_record["path_id"])
    checkpoints = store.checkpoints()
    attempt = summary["exact_attempt_records"][0]
    trajectory = summary["result"]["trajectory"][0]
    failed_checks = sorted(
        key for key, passed in attempt["acceptance"]["checks"].items() if not passed
    )
    checks = {
        "summary_digest": observed == _digest(content),
        "code_tag_is_ancestor": subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", CODE_TAG, "HEAD"],
            check=False,
        ).returncode == 0,
        "source_reconstruction": (
            summary["source_reconstruction"]["matches_checkpoint_statevector"] is True
            and summary["source_reconstruction"]["energy_difference_hartree"] <= 1e-10
        ),
        "exact_attempt_evidence_complete": (
            len(summary["exact_attempt_records"]) == 1
            and summary["result"]["exact_attempts"] == 1
            and summary["result"]["terminal_work"]["exact_vqe_attempts"] == 1
        ),
        "rejection_is_only_frozen_kkt_gate": (
            attempt["acceptance"]["accepted"] is False
            and trajectory["accepted"] is False
            and failed_checks == ["kkt"]
            and trajectory["rejection_reasons"] == ["kkt"]
        ),
        "kkt_threshold_not_relaxed": (
            attempt["acceptance"]["checks"]["kkt"] is False
            and attempt["fallback"]["gradient_infinity"] > 1e-8
        ),
        "rollback_kept_only_source_checkpoint": (
            len(checkpoints) == 1
            and summary["result"]["accepted_rounds"] == 0
            and summary["result"]["final_energy_hartree"] == summary["source_energy_hartree"]
            and summary["result"]["final_checkpoint_digest"] == checkpoints[0].checkpoint_digest
        ),
        "rejected_work_not_erased": (
            summary["result"]["terminal_work"]["optimizer_starts"] == 2
            and summary["result"]["terminal_work"]["energy_evaluations"] > 0
            and checkpoints[0].work["exact_vqe_attempts"] == 0
        ),
        "candidate_had_real_resource_benefit": all(
            attempt["physical_resources"][key] <= attempt["before_resources"][key]
            for key in ("cnot_count", "cnot_depth", "total_depth", "parameter_count", "logical_block_count")
        ) and any(
            attempt["physical_resources"][key] < attempt["before_resources"][key]
            for key in ("cnot_count", "cnot_depth", "total_depth", "parameter_count", "logical_block_count")
        ),
        "screening_information_firewall": not _forbidden(summary["catalog_diagnostics_by_runtime"]),
        "no_hidden_catalog_failure": all(
            not record["numerical_failures"]
            for record in summary["catalog_diagnostics_by_runtime"].values()
        ),
        "paper_measurement_cost_undefined": summary["paper_measurement_cost"] is None,
    }
    recomputation = None
    if recompute_quantum:
        algorithm, pool, _ = _lih_algorithm()
        algorithm.initialize()
        snapshot = checkpoints[0].runtime()
        coefficients = np.asarray(snapshot.ansatz.coefficients, dtype=np.float64)
        energy = _energy(algorithm, coefficients, snapshot.ansatz.indices)
        gradient = _gradient(algorithm, coefficients, snapshot.ansatz.indices)
        state = _state_vector(algorithm, coefficients, snapshot.ansatz.indices)
        resources = evaluate_full_circuit_resources(pool, snapshot.ansatz, paper_era_backend()).snapshot
        recomputation = {
            "energy_difference_hartree": abs(energy - snapshot.energy_hartree),
            "gradient_stored_max_difference": float(np.max(np.abs(gradient - snapshot.gradient))),
            "statevector_stored_max_difference": float(np.max(np.abs(state - snapshot.statevector))),
            "resources": asdict(resources),
        }
        checks.update({
            "independent_rollback_energy": recomputation["energy_difference_hartree"] <= 1e-10,
            "independent_rollback_gradient": recomputation["gradient_stored_max_difference"] <= 1e-10,
            "independent_rollback_state": recomputation["statevector_stored_max_difference"] <= 1e-12,
            "independent_rollback_resources": asdict(resources) == checkpoints[0].resource_snapshot,
        })
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s8-lih-width1-transfer-independent-audit",
        "passed": all(checks.values()),
        "checks": checks,
        "failed_acceptance_checks": failed_checks,
        "independent_rollback_recomputation": recomputation,
        "scientific_result": {
            "status": "valid-negative-ablation-C-triggering-conditional-polishing",
            "accepted_rounds": 0,
            "exact_attempts": 1,
            "failed_gate": "kkt",
            "observed_gradient_infinity": attempt["fallback"]["gradient_infinity"],
            "required_gradient_infinity": 1e-8,
        },
        "claim_boundary": "Valid LiH development-transfer negative result; no threshold relaxation or superiority claim.",
        "paper_measurement_cost": None,
    }
    result["audit_digest"] = _digest(result)
    if not result["passed"]:
        raise V5S8LiHAuditError(
            "LiH audit failed: " + ", ".join(key for key, value in checks.items() if not value)
        )
    return result


if __name__ == "__main__":
    result = run_audit()
    output = ROOT / "artifacts/v5/s8/lih-width1-transfer-v1-audit.json"
    if output.exists():
        raise FileExistsError(output)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "checks": len(result["checks"])}, sort_keys=True))
