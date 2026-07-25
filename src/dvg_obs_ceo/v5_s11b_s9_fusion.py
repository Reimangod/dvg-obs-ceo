"""Outcome-informed but frozen V5.1 fusion integration with the S9 H6 winner."""

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
from .block_ir import enumerate_candidates, recover_dvg_blocks
from .composition import compose_registered_candidates
from .identity import canonical_json_bytes
from .multisystem_checkpoint import _algorithm
from .resources import AnsatzStructure, evaluate_full_circuit_resources, paper_era_backend
from .s8_probe import _state_vector
from .v5_1_exact_fusion import apply_exact_fusions, enumerate_exact_fusions
from .v5_s10_fusion_gate import _operator_audit


MANIFEST = ROOT / "manifests/v5-s11b-s9-fusion-integration-v1.json"
OUTPUT = ROOT / "artifacts/v5/s11/h6-1.5-s9-fusion-integration-v1.json"
CODE_TAG = "dvg-obs-v5-s11b-s9-fusion-code-v1"


class V5S11BError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _verify(output: Path) -> dict[str, Any]:
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
        raise V5S11BError("S11b requires clean frozen code and absent output")
    return {"head": head, "code_tag": CODE_TAG, "output_absent": True}


def _write(path: Path, value: dict[str, Any]) -> None:
    atomic_write_new_json(path, value)


def _snapshot(resources: Any) -> dict[str, Any]:
    return asdict(resources.snapshot)


def execute(output: Path = OUTPUT) -> dict[str, Any]:
    freeze = _verify(output)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    loaded: dict[str, dict[str, Any]] = {}
    for name, item in manifest["inputs"].items():
        path = ROOT / item["path"]
        if _sha256(path) != item["sha256"]:
            raise V5S11BError(f"frozen input hash mismatch: {name}")
        loaded[name] = json.loads(path.read_text(encoding="utf-8"))
    checkpoint = loaded["checkpoint"]
    s9 = loaded["v5_s9_result"]
    accepted = [
        branch for branch in s9["branch_records"] if branch["decision"]["accepted"]
    ]
    if len(accepted) != manifest["execution"]["s9_accepted_branch_count_must_equal"]:
        raise V5S11BError("frozen S9 accepted branch count changed")
    branch = accepted[0]

    algorithm, pool = _algorithm(checkpoint["case"])
    algorithm.initialize()
    ceo_source = AnsatzStructure.create(
        checkpoint["ansatz_indices"],
        checkpoint["ansatz_coefficients"],
        checkpoint["iteration_counts"],
    )
    ceo_blocks = recover_dvg_blocks(
        pool,
        ceo_source.indices,
        ceo_source.coefficients,
        ceo_source.cumulative_parameter_counts,
    )
    atomic = {
        candidate.candidate_id: candidate
        for candidate in enumerate_candidates(pool, ceo_blocks)
    }
    try:
        plan = compose_registered_candidates(
            ceo_source,
            ceo_blocks,
            tuple(
                atomic[candidate_id]
                for candidate_id in branch["attempt_record"]["atomic_candidate_ids"]
            ),
        )
    except KeyError as error:
        raise V5S11BError("S9 atomic candidate is absent") from error
    source = AnsatzStructure.create(
        plan.target_indices,
        branch["attempt_record"]["primary"]["coordinates"],
        plan.target_iteration_counts,
    )
    source_energy = float(
        algorithm.evaluate_energy(list(source.coefficients), list(source.indices))
    )
    source_state = _state_vector(algorithm, source.coefficients, source.indices)
    source_physical = evaluate_full_circuit_resources(pool, source, paper_era_backend())
    source_structural = evaluate_full_circuit_resources(
        pool, source, paper_era_backend(), coefficient_policy="deterministic-structural"
    )
    if (
        abs(source_energy - branch["decision"]["candidate_energy_hartree"]) > 1e-10
        or _snapshot(source_physical) != s9["result"]["winner_resources"]
        or source_physical.snapshot != source_structural.snapshot
    ):
        raise V5S11BError("S9 winner reconstruction failed")

    blocks = recover_dvg_blocks(
        pool, source.indices, source.coefficients, source.cumulative_parameter_counts
    )
    catalog = {
        candidate.candidate_id: candidate
        for candidate in enumerate_exact_fusions(pool, blocks)
    }
    expected = manifest["frozen_candidate_ids"]
    if sorted(catalog) != sorted(expected):
        raise V5S11BError("S9 winner fusion catalog drifted")
    candidates = tuple(catalog[candidate_id] for candidate_id in expected)
    blocks_by_id = {block.block_id: block for block in blocks}
    operator_audits = [
        _operator_audit(pool, candidate, blocks_by_id) for candidate in candidates
    ]
    target = apply_exact_fusions(pool, source, candidates)
    target_energy = float(
        algorithm.evaluate_energy(list(target.coefficients), list(target.indices))
    )
    target_state = _state_vector(algorithm, target.coefficients, target.indices)
    target_physical = evaluate_full_circuit_resources(pool, target, paper_era_backend())
    target_structural = evaluate_full_circuit_resources(
        pool, target, paper_era_backend(), coefficient_policy="deterministic-structural"
    )
    source_resources = _snapshot(source_physical)
    target_resources = _snapshot(target_physical)
    drift = abs(target_energy - source_energy)
    fidelity = float(abs(np.vdot(source_state, target_state)) ** 2)
    limits = manifest["acceptance"]
    guarded = (
        "cnot_count",
        "cnot_depth",
        "total_depth",
        "parameter_count",
        "logical_block_count",
    )
    checks = {
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
        "energy": drift <= limits["maximum_absolute_energy_drift_hartree"],
        "state": fidelity >= limits["minimum_state_fidelity"],
        "physical_structural_resources": target_physical.snapshot == target_structural.snapshot,
        "all_resources_nonincrease": all(
            target_resources[field] <= source_resources[field] for field in guarded
        ),
        "cnot_reduction": target_resources["cnot_count"] < source_resources["cnot_count"],
        "parameter_reduction": (
            target_resources["parameter_count"] < source_resources["parameter_count"]
        ),
    }
    s11_v4 = loaded["s11_result"]
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5.1-s11b-s9-fusion-integration-result",
        "classification": manifest["classification"],
        "execution_freeze": freeze,
        "manifest_path": str(MANIFEST.relative_to(ROOT)),
        "manifest_sha256": _sha256(MANIFEST),
        "case_id": "h6-1.5",
        "source": {
            "kind": "frozen-s9-v5-winner",
            "energy_hartree": source_energy,
            "energy_increase_from_ceo_source_hartree": (
                source_energy - float(checkpoint["energy_hartree"])
            ),
            "resources": source_resources,
        },
        "target": {
            "kind": "v5.1-s9-winner-plus-joint-exact-fusion",
            "energy_hartree": target_energy,
            "energy_increase_from_ceo_source_hartree": (
                target_energy - float(checkpoint["energy_hartree"])
            ),
            "resources": target_resources,
        },
        "candidate_ids": expected,
        "operator_audits": operator_audits,
        "absolute_energy_drift_hartree": drift,
        "state_fidelity": fidelity,
        "checks": checks,
        "passed": all(checks.values()),
        "v5_1_pareto_context": {
            "lossless_v4_1_fusion_point": s11_v4["target"],
            "neither_point_dominates_the_other": True,
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
    if not result["passed"]:
        raise V5S11BError(
            "S11b failed: "
            + ", ".join(name for name, passed in checks.items() if not passed)
        )
    _write(output, result)
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
                "energy_drift": result["absolute_energy_drift_hartree"],
                "source_resources": result["source"]["resources"],
                "target_resources": result["target"]["resources"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
