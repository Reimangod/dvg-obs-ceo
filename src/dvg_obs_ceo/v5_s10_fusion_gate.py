"""Execute the frozen V5-S10 exact cross-iteration fusion gate."""

from __future__ import annotations

from dataclasses import asdict
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from .baseline import ROOT
from .block_ir import recover_dvg_blocks
from .identity import canonical_json_bytes
from .multisystem_checkpoint import _algorithm as multisystem_algorithm
from .resources import (
    AnsatzStructure,
    evaluate_full_circuit_resources,
    paper_era_backend,
)
from .s10_lih import _algorithm as lih_algorithm
from .s8_probe import _state_vector
from .v5_1_exact_fusion import apply_exact_fusion, enumerate_exact_fusions


MANIFEST = ROOT / "manifests/v5-s10-exact-fusion-gate-v1.json"
OUTPUT = ROOT / "artifacts/v5/s10/exact-fusion-gate-v1.json"


class V5S10FusionGateError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _operator_residual(operator: Any) -> float:
    return float(sum(abs(complex(value)) ** 2 for value in operator.terms.values()) ** 0.5)


def _compressed(operator: Any, tolerance: float = 1e-14) -> Any:
    result = operator
    result.compress(abs_tol=tolerance)
    return result


def _operator_audit(pool: Any, candidate: Any, blocks_by_id: dict[str, Any]) -> dict[str, Any]:
    ovp_block = blocks_by_id[candidate.ovp_block_id]
    mvp_block = blocks_by_id[candidate.mvp_block_id]
    ovp = pool.get_q_op(ovp_block.pool_indices[0])
    parents = [pool.get_q_op(index) for index in mvp_block.pool_indices]
    reconstructed = sum(
        (
            weight * operator
            for weight, operator in zip(candidate.exact_signed_relation, parents)
        ),
        0 * ovp,
    )
    identity_residual = _operator_residual(_compressed(ovp - reconstructed))
    commutators: list[dict[str, Any]] = []
    relevant = [*parents]
    for block_id in candidate.intervening_block_ids:
        relevant.extend(
            pool.get_q_op(index) for index in blocks_by_id[block_id].pool_indices
        )
    for number, operator in enumerate(relevant):
        residual = _operator_residual(
            _compressed(ovp * operator - operator * ovp)
        )
        commutators.append({"operator_number": number, "residual": residual})
    for left in range(len(parents)):
        for right in range(left + 1, len(parents)):
            residual = _operator_residual(
                _compressed(
                    parents[left] * parents[right]
                    - parents[right] * parents[left]
                )
            )
            commutators.append(
                {
                    "operator_number": f"parent-{left}-parent-{right}",
                    "residual": residual,
                }
            )
    return {
        "generator_identity_residual": identity_residual,
        "commutators": commutators,
        "maximum_commutator_residual": max(
            (item["residual"] for item in commutators), default=0.0
        ),
    }


def _case_algorithm(case_id: str, checkpoint: dict[str, Any]) -> tuple[Any, Any]:
    if case_id == "lih-3.0":
        algorithm, pool, _ = lih_algorithm()
        return algorithm, pool
    return multisystem_algorithm(checkpoint["case"])


def _resource_record(resources: Any) -> dict[str, Any]:
    return asdict(resources.snapshot)


def execute(output: Path = OUTPUT) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(output)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tolerance = manifest["acceptance"]
    cases: list[dict[str, Any]] = []
    certified_total = 0
    for registered in manifest["inputs"]:
        checkpoint_path = ROOT / registered["checkpoint_path"]
        if _sha256(checkpoint_path) != registered["checkpoint_sha256"]:
            raise V5S10FusionGateError(
                f"checkpoint hash mismatch: {registered['case_id']}"
            )
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        algorithm, pool = _case_algorithm(registered["case_id"], checkpoint)
        algorithm.initialize()
        source = AnsatzStructure.create(
            checkpoint["ansatz_indices"],
            checkpoint["ansatz_coefficients"],
            checkpoint["iteration_counts"],
        )
        source_state = _state_vector(algorithm, source.coefficients, source.indices)
        source_energy = float(
            algorithm.evaluate_energy(list(source.coefficients), list(source.indices))
        )
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
            abs(source_energy - float(checkpoint["energy_hartree"])) > 1e-10
            or _resource_record(source_physical) != checkpoint["resources"]["snapshot"]
            or source_physical.snapshot != source_structural.snapshot
        ):
            raise V5S10FusionGateError(
                f"source reconstruction failed: {registered['case_id']}"
            )
        blocks = recover_dvg_blocks(
            pool,
            source.indices,
            source.coefficients,
            source.cumulative_parameter_counts,
        )
        blocks_by_id = {block.block_id: block for block in blocks}
        candidates = enumerate_exact_fusions(pool, blocks)
        records: list[dict[str, Any]] = []
        for candidate in candidates:
            operator_audit = _operator_audit(pool, candidate, blocks_by_id)
            target = apply_exact_fusion(pool, source, candidate)
            target_state = _state_vector(
                algorithm, target.coefficients, target.indices
            )
            target_energy = float(
                algorithm.evaluate_energy(
                    list(target.coefficients), list(target.indices)
                )
            )
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
            source_resource = _resource_record(source_physical)
            target_resource = _resource_record(target_physical)
            checks = {
                "generator_identity": operator_audit[
                    "generator_identity_residual"
                ]
                <= tolerance["maximum_operator_identity_residual"],
                "commutators": operator_audit["maximum_commutator_residual"]
                <= tolerance["maximum_commutator_residual"],
                "energy": abs(target_energy - source_energy)
                <= tolerance["maximum_absolute_energy_drift_hartree"],
                "state": fidelity >= tolerance["minimum_state_fidelity"],
                "physical_structural_resources": (
                    target_physical.snapshot == target_structural.snapshot
                ),
                "parameter_reduction": (
                    target_resource["parameter_count"]
                    < source_resource["parameter_count"]
                ),
                "cnot_reduction": (
                    target_resource["cnot_count"] < source_resource["cnot_count"]
                ),
                "guarded_nonincrease": all(
                    target_resource[field] <= source_resource[field]
                    for field in (
                        "cnot_depth",
                        "total_depth",
                        "logical_block_count",
                    )
                ),
            }
            certified = all(checks.values())
            certified_total += int(certified)
            records.append(
                {
                    "candidate": candidate.to_dict(),
                    "operator_audit": operator_audit,
                    "source_energy_hartree": source_energy,
                    "target_energy_hartree": target_energy,
                    "absolute_energy_drift_hartree": abs(
                        target_energy - source_energy
                    ),
                    "state_fidelity": fidelity,
                    "source_resources": source_resource,
                    "target_resources": target_resource,
                    "checks": checks,
                    "certified": certified,
                }
            )
        cases.append(
            {
                "case_id": registered["case_id"],
                "checkpoint_path": registered["checkpoint_path"],
                "checkpoint_sha256": registered["checkpoint_sha256"],
                "block_count": len(blocks),
                "candidate_count": len(candidates),
                "certified_count": sum(
                    int(record["certified"]) for record in records
                ),
                "candidates": records,
                "work": {
                    "energy_evaluations": 1 + len(candidates),
                    "statevector_evaluations": 1 + len(candidates),
                    "full_resource_recounts": 2 * (1 + len(candidates)),
                    "optimizer_starts": 0,
                    "optimizer_iterations": 0,
                    "paper_measurement_cost": None,
                },
            }
        )
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s10-exact-fusion-gate-result",
        "manifest_path": str(MANIFEST.relative_to(ROOT)),
        "manifest_sha256": _sha256(MANIFEST),
        "cases": cases,
        "certified_candidate_count": certified_total,
        "adoption_gate_passed": certified_total > 0,
        "authorized_next_stage": "V5.1-S11" if certified_total > 0 else None,
        "paper_measurement_cost": None,
        "claim_boundary": manifest["claim_boundary"],
    }
    result["result_digest"] = _digest(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    arguments = parser.parse_args()
    result = execute(arguments.output)
    print(
        json.dumps(
            {
                "certified_candidate_count": result[
                    "certified_candidate_count"
                ],
                "adoption_gate_passed": result["adoption_gate_passed"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
