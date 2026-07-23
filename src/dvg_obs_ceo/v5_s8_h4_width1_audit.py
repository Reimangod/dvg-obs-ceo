"""Independent audit of the amended V5-S8 H4 width-one result."""

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
from .s8_probe import _algorithm, _state_vector
from .v4_lih import _energy, _gradient
from .v5_nested_transaction import PathCheckpointStore
from .v5_s8_h4_width1 import CASE_ID, _state_id


RESULT = ROOT / "artifacts/v5/s8/h4-width1-recycled-v1-1/summary.json"
PILOT = ROOT / "artifacts/v5/s8/h4-width1-recycled-pilot-v1/summary.json"
CODE_TAG = "dvg-obs-v5-s8-h4-width1-recycled-code-v1.1"


class V5S8H4WidthOneAuditError(RuntimeError):
    """Raised when amended H4 evidence fails independent audit."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _contains_forbidden_screening_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            "actual" in str(key).lower()
            or "fci" in str(key).lower()
            or _contains_forbidden_screening_key(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_screening_key(item) for item in value)
    return False


def _scientific_projection(summary: Mapping[str, Any]) -> dict[str, Any]:
    result = summary["result"]
    return {
        "source_energy_hartree": summary["source_energy_hartree"],
        "source_resources": summary["source_resources"],
        "final_energy_hartree": result["final_energy_hartree"],
        "actual_cumulative_energy_increase_hartree": result[
            "actual_cumulative_energy_increase_hartree"
        ],
        "accepted_rounds": result["accepted_rounds"],
        "exact_attempts": result["exact_attempts"],
        "trajectory": [
            {
                "round_index": row["round_index"],
                "accepted": row["accepted"],
                "actual_cumulative_energy_increase_hartree": row.get(
                    "actual_cumulative_energy_increase_hartree"
                ),
                "resources": row.get("resources"),
                "work_after_attempt": row.get("work_after_attempt"),
            }
            for row in result["trajectory"]
        ],
        "terminal_work": result["terminal_work"],
    }


def run_audit(*, recompute_quantum: bool = True) -> dict[str, Any]:
    summary = _load(RESULT)
    pilot = _load(PILOT)
    content = dict(summary)
    observed_digest = content.pop("result_digest")
    output_root = RESULT.parent
    round_zero = sorted((output_root / "path/rounds").glob("round-0000-*/checkpoint.json"))
    if len(round_zero) != 1:
        raise V5S8H4WidthOneAuditError("source checkpoint is absent or ambiguous")
    source_record = _load(round_zero[0])
    store = PathCheckpointStore(output_root / "path", source_record["path_id"])
    checkpoints = store.checkpoints()
    final = checkpoints[-1]
    attempts = summary["exact_attempt_records"]
    trajectory = summary["result"]["trajectory"]
    selection_evidence = summary["catalog_diagnostics_by_runtime"]

    checks = {
        "summary_digest": observed_digest == _digest(content),
        "code_tag_is_execution_ancestor": subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", CODE_TAG, "HEAD"],
            check=False,
        ).returncode == 0,
        "source_reconstruction": (
            summary["source_reconstruction"]["matches_checkpoint_statevector"] is True
            and summary["source_reconstruction"]["energy_difference_hartree"] <= 1e-10
        ),
        "checkpoint_chain": (
            len(checkpoints) == summary["result"]["accepted_rounds"] + 1
            and final.checkpoint_digest == summary["result"]["final_checkpoint_digest"]
        ),
        "attempt_evidence_complete": (
            len(attempts) == summary["result"]["exact_attempts"]
            == summary["result"]["terminal_work"]["exact_vqe_attempts"]
            and len(attempts) == len(trajectory)
        ),
        "all_adopted_acceptance_checks_pass": all(
            attempt["acceptance"]["accepted"] is row["accepted"]
            and all(attempt["acceptance"]["checks"].values())
            for attempt, row in zip(attempts, trajectory)
        ),
        "physical_structural_recounts_match": all(
            attempt["physical_resources"] == attempt["structural_resources"]
            for attempt in attempts
        ),
        "resource_trajectory_matches_checkpoints": all(
            row["resources"] == {
                key: checkpoint.resource_snapshot[key]
                for key in ("cnot_count", "cnot_depth", "total_depth", "parameter_count", "logical_block_count")
            }
            for row, checkpoint in zip(trajectory, checkpoints[1:])
        ),
        "source_relative_budget": (
            summary["result"]["actual_cumulative_energy_increase_hartree"] <= 1e-4
        ),
        "work_monotone_and_rejected_visible": all(
            all(
                later["work_after_attempt"][key] >= earlier["work_after_attempt"][key]
                for key in later["work_after_attempt"]
            )
            for earlier, later in zip(trajectory, trajectory[1:])
        ),
        "screening_information_firewall": not _contains_forbidden_screening_key(
            selection_evidence
        ),
        "no_hidden_catalog_failure": all(
            not record["numerical_failures"] for record in selection_evidence.values()
        ),
        "pilot_and_amended_scientific_results_match": (
            _scientific_projection(pilot) == _scientific_projection(summary)
        ),
        "paper_measurement_cost_undefined": summary["paper_measurement_cost"] is None,
    }

    recomputation: dict[str, Any] | None = None
    if recompute_quantum:
        algorithm, pool = _algorithm(CASE_ID)
        algorithm.initialize()
        snapshot = final.runtime()
        coefficients = np.asarray(snapshot.ansatz.coefficients, dtype=np.float64)
        energy = _energy(algorithm, coefficients, snapshot.ansatz.indices)
        gradient = _gradient(algorithm, coefficients, snapshot.ansatz.indices)
        state = _state_vector(algorithm, coefficients, snapshot.ansatz.indices)
        resources = evaluate_full_circuit_resources(
            pool, snapshot.ansatz, paper_era_backend()
        ).snapshot
        state_sha = hashlib.sha256(np.asarray(state, dtype=">c16").tobytes()).hexdigest()
        stored_state_sha = hashlib.sha256(
            np.asarray(snapshot.statevector, dtype=">c16").tobytes()
        ).hexdigest()
        recomputation = {
            "energy_hartree": energy,
            "energy_difference_hartree": abs(energy - snapshot.energy_hartree),
            "gradient_infinity": float(np.max(np.abs(gradient))) if gradient.size else 0.0,
            "gradient_stored_max_difference": float(np.max(np.abs(gradient - snapshot.gradient))) if gradient.size else 0.0,
            "statevector_sha256": state_sha,
            "stored_statevector_sha256": stored_state_sha,
            "resources": asdict(resources),
        }
        checks.update({
            "independent_final_energy": recomputation["energy_difference_hartree"] <= 1e-10,
            "independent_final_gradient": (
                recomputation["gradient_infinity"] <= 1e-8
                and recomputation["gradient_stored_max_difference"] <= 1e-10
            ),
            "independent_final_state": state_sha == stored_state_sha,
            "independent_final_resources": asdict(resources) == final.resource_snapshot,
            "final_state_identity": _state_id(snapshot) == final.state_preparation_id,
        })

    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s8-h4-width1-recycled-independent-audit",
        "passed": all(checks.values()),
        "checks": checks,
        "scientific_result": _scientific_projection(summary),
        "independent_final_recomputation": recomputation,
        "claim_boundary": [
            "Audited development H4 ablation C only.",
            "No fresh Hessian/HVP, larger-molecule, or measurement-cost claim.",
            "Pilot is retained solely to demonstrate that evidence-only amendment did not change scientific outputs."
        ],
        "paper_measurement_cost": None,
    }
    result["audit_digest"] = _digest(result)
    if not result["passed"]:
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise V5S8H4WidthOneAuditError("independent audit failed: " + ", ".join(failed))
    return result


if __name__ == "__main__":
    result = run_audit()
    path = ROOT / "artifacts/v5/s8/h4-width1-recycled-v1-1-audit.json"
    if path.exists():
        raise FileExistsError(f"refusing to overwrite audit: {path}")
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "checks": len(result["checks"])}, sort_keys=True))
