"""Audit the LiH joint-catalog sequential calibration result."""

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


RESULT = ROOT / "artifacts/v5/s8/lih-joint-sequential-v1/summary.json"
CODE_TAG = "dvg-obs-v5-s8-lih-joint-sequential-code-v1"


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
    checkpoints = PathCheckpointStore(
        RESULT.parent / "path", source_record["path_id"]
    ).checkpoints()
    attempt = summary["exact_attempt_records"][0]
    trajectory = summary["result"]["trajectory"][0]
    catalogs = list(summary["catalog_diagnostics_by_runtime"].values())
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
        "one_joint_commit": (
            len(checkpoints) == 2
            and len(attempt["atomic_candidate_ids"]) == 7
            and summary["result"]["accepted_rounds"] == 1
            and summary["result"]["stop_reason"] == "no-eligible-candidate"
        ),
        "all_acceptance_checks_pass": (
            attempt["acceptance"]["accepted"] is True
            and all(attempt["acceptance"]["checks"].values())
            and trajectory["accepted"] is True
        ),
        "known_joint_endpoint_reproduced": trajectory["resources"] == {
            "cnot_count": 58,
            "cnot_depth": 30,
            "total_depth": 92,
            "parameter_count": 8,
            "logical_block_count": 8,
        },
        "energy_budget": summary["result"]["actual_cumulative_energy_increase_hartree"] <= 1e-4,
        "physical_structural_recount": attempt["physical_resources"] == attempt["structural_resources"],
        "joint_search_executed": (
            catalogs[0]["joint_search"]["counts"]["expanded"] == 337
            and catalogs[0]["candidate_batch_count"] == 127
            and catalogs[0]["selection"]["eligible_count"] == 127
        ),
        "postcommit_catalog_rebuilt": len(catalogs) == 2,
        "no_hidden_catalog_failure": all(not item["numerical_failures"] for item in catalogs),
        "screening_information_firewall": not _forbidden(summary["catalog_diagnostics_by_runtime"]),
        "paper_measurement_cost_undefined": summary["paper_measurement_cost"] is None,
    }
    recomputation = None
    if recompute_quantum:
        algorithm, pool, _ = _lih_algorithm()
        algorithm.initialize()
        snapshot = checkpoints[-1].runtime()
        coordinates = np.asarray(snapshot.ansatz.coefficients, dtype=np.float64)
        energy = _energy(algorithm, coordinates, snapshot.ansatz.indices)
        gradient = _gradient(algorithm, coordinates, snapshot.ansatz.indices)
        state = _state_vector(algorithm, coordinates, snapshot.ansatz.indices)
        resources = evaluate_full_circuit_resources(pool, snapshot.ansatz, paper_era_backend()).snapshot
        recomputation = {
            "energy_difference_hartree": abs(energy - snapshot.energy_hartree),
            "gradient_infinity": float(np.max(np.abs(gradient))),
            "statevector_stored_max_difference": float(np.max(np.abs(state - snapshot.statevector))),
            "resources": asdict(resources),
        }
        checks.update({
            "independent_final_energy": recomputation["energy_difference_hartree"] <= 1e-10,
            "independent_final_gradient": recomputation["gradient_infinity"] <= 1e-8,
            "independent_final_state": recomputation["statevector_stored_max_difference"] <= 1e-12,
            "independent_final_resources": asdict(resources) == checkpoints[-1].resource_snapshot,
        })
    audit = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s8-lih-joint-sequential-independent-audit",
        "passed": all(checks.values()),
        "checks": checks,
        "independent_final_recomputation": recomputation,
        "scientific_result": {
            "status": "joint-catalog-reproduces-one-shot-endpoint-no-sequential-extension",
            "energy_increase_hartree": summary["result"]["actual_cumulative_energy_increase_hartree"],
            "source_resources": summary["source_resources"],
            "final_resources": trajectory["resources"],
        },
        "claim_boundary": "Known LiH calibration; reproduces the joint endpoint but does not exceed it.",
        "paper_measurement_cost": None,
    }
    audit["audit_digest"] = _digest(audit)
    if not audit["passed"]:
        raise RuntimeError(
            "joint audit failed: "
            + ", ".join(key for key, passed in checks.items() if not passed)
        )
    return audit


if __name__ == "__main__":
    audit = run_audit()
    output = ROOT / "artifacts/v5/s8/lih-joint-sequential-v1-audit.json"
    if output.exists():
        raise FileExistsError(output)
    output.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": audit["passed"], "checks": len(audit["checks"])}, sort_keys=True))
