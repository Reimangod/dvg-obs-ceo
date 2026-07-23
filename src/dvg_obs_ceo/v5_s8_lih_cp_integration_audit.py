"""Independent audit of the fresh LiH C-plus-polishing integration."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
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


RESULT = ROOT / "artifacts/v5/s8/lih-cp-integration-v1/summary.json"
CODE_TAG = "dvg-obs-v5-s8-lih-cp-integration-code-v1"


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


def run_audit(*, recompute_quantum: bool = True) -> dict:
    summary = json.loads(RESULT.read_text(encoding="utf-8"))
    content = dict(summary)
    observed = content.pop("result_digest")
    round_zero = list((RESULT.parent / "path/rounds").glob("round-0000-*/checkpoint.json"))
    source_record = json.loads(round_zero[0].read_text(encoding="utf-8"))
    store = PathCheckpointStore(RESULT.parent / "path", source_record["path_id"])
    checkpoints = store.checkpoints()
    attempts = summary["exact_attempt_records"]
    trajectory = summary["result"]["trajectory"]
    first_polishing = attempts[0]["conditional_polishing"]
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
        "checkpoint_chain": (
            len(round_zero) == 1 and len(checkpoints) == 3
            and checkpoints[-1].checkpoint_digest == summary["result"]["final_checkpoint_digest"]
        ),
        "two_fresh_exact_attempts": (
            len(attempts) == len(trajectory) == 2
            and summary["result"]["exact_attempts"] == 2
            and summary["result"]["terminal_work"]["exact_vqe_attempts"] == 2
        ),
        "all_acceptance_checks_pass": all(
            attempt["acceptance"]["accepted"] is True
            and all(attempt["acceptance"]["checks"].values())
            and row["accepted"] is True
            for attempt, row in zip(attempts, trajectory)
        ),
        "polishing_only_when_triggered": (
            attempts[0]["selected_optimizer_path"] == "conditional-target-native-polishing"
            and first_polishing["success"] is True
            and first_polishing["gradient_infinity"] <= 1e-8
            and attempts[1]["conditional_polishing"] is None
            and attempts[1]["selected_optimizer_path"] == "recycled-obs"
        ),
        "finite_difference_hvp_work_counted": (
            first_polishing["work"]["hessian_vector_products"] == 25
            and summary["result"]["terminal_work"]["finite_difference_hvp_calls"] == 25
        ),
        "resource_recounts_match": all(
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
        "source_relative_energy_budget": summary["result"]["actual_cumulative_energy_increase_hartree"] <= 1e-4,
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
        snapshot = checkpoints[-1].runtime()
        coefficients = np.asarray(snapshot.ansatz.coefficients, dtype=np.float64)
        energy = _energy(algorithm, coefficients, snapshot.ansatz.indices)
        gradient = _gradient(algorithm, coefficients, snapshot.ansatz.indices)
        state = _state_vector(algorithm, coefficients, snapshot.ansatz.indices)
        resources = evaluate_full_circuit_resources(pool, snapshot.ansatz, paper_era_backend()).snapshot
        recomputation = {
            "energy_difference_hartree": abs(energy - snapshot.energy_hartree),
            "gradient_infinity": float(np.max(np.abs(gradient))),
            "gradient_stored_max_difference": float(np.max(np.abs(gradient - snapshot.gradient))),
            "statevector_stored_max_difference": float(np.max(np.abs(state - snapshot.statevector))),
            "resources": asdict(resources),
        }
        checks.update({
            "independent_final_energy": recomputation["energy_difference_hartree"] <= 1e-10,
            "independent_final_gradient": (
                recomputation["gradient_infinity"] <= 1e-8
                and recomputation["gradient_stored_max_difference"] <= 1e-10
            ),
            "independent_final_state": recomputation["statevector_stored_max_difference"] <= 1e-12,
            "independent_final_resources": asdict(resources) == checkpoints[-1].resource_snapshot,
        })
    audit = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s8-lih-cp-integration-independent-audit",
        "passed": all(checks.values()),
        "checks": checks,
        "independent_final_recomputation": recomputation,
        "scientific_result": {
            "status": "successful-calibration-integration-not-final-V5",
            "energy_increase_hartree": summary["result"]["actual_cumulative_energy_increase_hartree"],
            "source_resources": summary["source_resources"],
            "final_resources": trajectory[-1]["resources"],
            "accepted_rounds": 2,
        },
        "claim_boundary": "Successful known-LiH calibration integration; joint-catalog V5 and frozen S9 remain pending.",
        "paper_measurement_cost": None,
    }
    audit["audit_digest"] = _digest(audit)
    if not audit["passed"]:
        raise RuntimeError(
            "LiH CP audit failed: "
            + ", ".join(key for key, passed in checks.items() if not passed)
        )
    return audit


if __name__ == "__main__":
    audit = run_audit()
    output = ROOT / "artifacts/v5/s8/lih-cp-integration-v1-audit.json"
    if output.exists():
        raise FileExistsError(output)
    output.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": audit["passed"], "checks": len(audit["checks"])}, sort_keys=True))
