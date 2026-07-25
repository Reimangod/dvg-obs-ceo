"""Frozen V5.1-S11 joint exact-fusion execution on H6 1.5 Å."""

from __future__ import annotations

from dataclasses import asdict
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import numpy as np

from .baseline import ROOT
from .artifact_io import atomic_write_new_json
from .block_ir import recover_dvg_blocks
from .identity import canonical_json_bytes
from .multisystem_checkpoint import _algorithm
from .resources import (
    AnsatzStructure,
    evaluate_full_circuit_resources,
    paper_era_backend,
)
from .s8_probe import _state_vector
from .v5_1_exact_fusion import apply_exact_fusions, enumerate_exact_fusions
from .v5_s10_fusion_gate import _operator_audit


MANIFEST = ROOT / "manifests/v5-s11-h6-exact-fusion-v1.json"
OUTPUT = ROOT / "artifacts/v5/s11/h6-1.5-exact-fusion-v1.json"
CODE_TAG = "dvg-obs-v5-s11-h6-fusion-code-v1"


class V5S11FusionError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _verify_freeze(output: Path) -> dict[str, Any]:
    head = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    tag = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", f"{CODE_TAG}^{{}}"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(ROOT), "status", "--porcelain"], text=True
    ).strip()
    if head != tag or dirty or output.exists():
        raise V5S11FusionError(
            "S11 requires clean frozen code and an absent canonical output"
        )
    return {"head": head, "code_tag": CODE_TAG, "output_absent": True}


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    atomic_write_new_json(path, value)


def _snapshot(resources: Any) -> dict[str, Any]:
    return asdict(resources.snapshot)


def execute(output: Path = OUTPUT) -> dict[str, Any]:
    freeze = _verify_freeze(output)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    loaded: dict[str, dict[str, Any]] = {}
    for name, record in manifest["inputs"].items():
        path = ROOT / record["path"]
        if _sha256(path) != record["sha256"]:
            raise V5S11FusionError(f"frozen input hash mismatch: {name}")
        loaded[name] = json.loads(path.read_text(encoding="utf-8"))
    checkpoint = loaded["checkpoint"]
    v4 = loaded["v4_1_result"]
    attempt_number = manifest["inputs"]["v4_1_result"]["attempt_number"]
    attempt = next(
        item for item in v4["attempts"] if item["attempt_number"] == attempt_number
    )
    if attempt["transaction_status"] != "accepted" or attempt["fallback"] is not None:
        raise V5S11FusionError("frozen V4.1 source attempt is not the registered primary")
    source = AnsatzStructure.create(
        attempt["frozen_sentinel"]["target_indices"],
        attempt["primary"]["coordinates"],
        attempt["frozen_sentinel"]["target_iteration_counts"],
    )
    algorithm, pool = _algorithm(checkpoint["case"])
    algorithm.initialize()
    source_energy = float(
        algorithm.evaluate_energy(list(source.coefficients), list(source.indices))
    )
    source_state = _state_vector(algorithm, source.coefficients, source.indices)
    source_physical = evaluate_full_circuit_resources(
        pool, source, paper_era_backend()
    )
    source_structural = evaluate_full_circuit_resources(
        pool,
        source,
        paper_era_backend(),
        coefficient_policy="deterministic-structural",
    )
    if (
        abs(source_energy - attempt["primary"]["energy_hartree"]) > 1e-10
        or _snapshot(source_physical) != attempt["physical_resources"]["snapshot"]
        or source_physical.snapshot != source_structural.snapshot
    ):
        raise V5S11FusionError("V4.1 source reconstruction failed")

    blocks = recover_dvg_blocks(
        pool,
        source.indices,
        source.coefficients,
        source.cumulative_parameter_counts,
    )
    catalog = {
        candidate.candidate_id: candidate
        for candidate in enumerate_exact_fusions(pool, blocks)
    }
    expected_ids = manifest["frozen_candidate_ids"]
    if sorted(catalog) != sorted(expected_ids):
        raise V5S11FusionError("S11 fusion catalog differs from the frozen IDs")
    candidates = tuple(catalog[candidate_id] for candidate_id in expected_ids)
    blocks_by_id = {block.block_id: block for block in blocks}
    operator_audits = [
        _operator_audit(pool, candidate, blocks_by_id)
        for candidate in candidates
    ]
    target = apply_exact_fusions(pool, source, candidates)
    target_energy = float(
        algorithm.evaluate_energy(list(target.coefficients), list(target.indices))
    )
    target_state = _state_vector(algorithm, target.coefficients, target.indices)
    target_physical = evaluate_full_circuit_resources(
        pool, target, paper_era_backend()
    )
    target_structural = evaluate_full_circuit_resources(
        pool,
        target,
        paper_era_backend(),
        coefficient_policy="deterministic-structural",
    )
    fidelity = float(abs(np.vdot(source_state, target_state)) ** 2)
    energy_drift = abs(target_energy - source_energy)
    source_resources = _snapshot(source_physical)
    target_resources = _snapshot(target_physical)
    limits = manifest["acceptance"]
    checks = {
        "candidate_count": len(candidates) == 2,
        "generator_identities": all(
            audit["generator_identity_residual"]
            <= limits["maximum_operator_identity_residual"]
            for audit in operator_audits
        ),
        "commutators": all(
            audit["maximum_commutator_residual"]
            <= limits["maximum_commutator_residual"]
            for audit in operator_audits
        ),
        "energy": energy_drift
        <= limits["maximum_absolute_energy_drift_hartree"],
        "state": fidelity >= limits["minimum_state_fidelity"],
        "physical_structural_resources": (
            target_physical.snapshot == target_structural.snapshot
        ),
        "cnot_reduction": (
            target_resources["cnot_count"] < source_resources["cnot_count"]
        ),
        "parameter_reduction": (
            target_resources["parameter_count"]
            < source_resources["parameter_count"]
        ),
        "cnot_depth_nonincrease": (
            target_resources["cnot_depth"] <= source_resources["cnot_depth"]
        ),
        "total_depth_nonincrease": (
            target_resources["total_depth"] <= source_resources["total_depth"]
        ),
        "block_nonincrease": (
            target_resources["logical_block_count"]
            <= source_resources["logical_block_count"]
        ),
    }
    passed = all(checks.values())
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5.1-s11-h6-joint-exact-fusion-result",
        "execution_freeze": freeze,
        "manifest_path": str(MANIFEST.relative_to(ROOT)),
        "manifest_sha256": _sha256(MANIFEST),
        "case_id": "h6-1.5",
        "source": {
            "kind": "frozen-v4.1-attempt-1",
            "energy_hartree": source_energy,
            "energy_increase_from_ceo_source_hartree": (
                source_energy - float(checkpoint["energy_hartree"])
            ),
            "resources": source_resources,
        },
        "target": {
            "kind": "v5.1-joint-exact-fusion",
            "energy_hartree": target_energy,
            "energy_increase_from_ceo_source_hartree": (
                target_energy - float(checkpoint["energy_hartree"])
            ),
            "resources": target_resources,
        },
        "candidate_ids": expected_ids,
        "operator_audits": operator_audits,
        "absolute_energy_drift_hartree": energy_drift,
        "state_fidelity": fidelity,
        "checks": checks,
        "passed": passed,
        "comparison_context": {
            "v5_s9_raw_winner_resources": loaded["v5_s9_result"]["result"][
                "winner_resources"
            ],
            "v5_s9_raw_winner_energy_increase_hartree": loaded["v5_s9_result"][
                "result"
            ]["winner_cumulative_energy_increase_hartree"],
            "selection_used_v5_s9_outcome": False,
        },
        "work": {
            "energy_evaluations": 2,
            "statevector_evaluations": 2,
            "full_resource_recounts": 4,
            "optimizer_starts": 0,
            "optimizer_iterations": 0,
            "paper_measurement_cost": None,
        },
        "claim_boundary": manifest["claim_boundary"],
    }
    result["result_digest"] = _digest(result)
    if not passed:
        raise V5S11FusionError(
            "S11 acceptance failed: "
            + ", ".join(name for name, value in checks.items() if not value)
        )
    _write_exclusive(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    arguments = parser.parse_args()
    result = execute(arguments.output)
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "source_resources": result["source"]["resources"],
                "target_resources": result["target"]["resources"],
                "energy_drift": result["absolute_energy_drift_hartree"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
