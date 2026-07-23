"""Registered full-circuit resource reconstruction probe."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from .baseline import _load_upstream, verify_upstream
from .block_ir import block_to_dict, candidate_to_dict, enumerate_candidates, recover_dvg_blocks
from .resources import (
    RESOURCE_EVALUATOR_VERSION,
    AnsatzStructure,
    apply_candidate_structure,
    evaluate_full_circuit_resources,
    paper_era_backend,
    resources_to_dict,
)
from .resource_pool import ResourceOnlyDVGPool


ROOT = Path(__file__).resolve().parents[2]


def _write_once(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite S6 artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def run_probe(path: Path) -> dict[str, Any]:
    provenance = verify_upstream()
    _, dvg_ceo, _, _ = _load_upstream()
    pool = dvg_ceo(n=4)
    backend = paper_era_backend()
    source = AnsatzStructure.create(
        [4, 2, 3, 0],
        [0.2, 0.3, -0.1, 0.4],
        [3, 4],
    )
    physical = evaluate_full_circuit_resources(pool, source, backend)
    structural = evaluate_full_circuit_resources(
        pool,
        source,
        backend,
        coefficient_policy="deterministic-structural",
    )
    if physical.snapshot != structural.snapshot:
        raise RuntimeError("physical and deterministic structural counter results differ")
    blocks = recover_dvg_blocks(
        pool,
        source.indices,
        source.coefficients,
        source.cumulative_parameter_counts,
    )
    candidates = enumerate_candidates(pool, blocks)
    candidate_results: list[dict[str, Any]] = []
    before = physical.snapshot
    for candidate in candidates:
        target_dimension = candidate.transformation.jacobian.shape[1]
        coordinates = [0.123 + 0.071 * index for index in range(target_dimension)]
        transformed = apply_candidate_structure(pool, source, candidate, coordinates)
        result = evaluate_full_circuit_resources(pool, transformed, backend)
        after = result.snapshot
        candidate_results.append(
            {
                "candidate": candidate_to_dict(candidate),
                "target_coordinates_for_resource_probe_only": coordinates,
                "transformed_indices": list(transformed.indices),
                "transformed_iteration_counts": list(transformed.cumulative_parameter_counts),
                "resources": resources_to_dict(result),
                "delta": {
                    "cnot_count": after.cnot_count - before.cnot_count,
                    "cnot_depth": after.cnot_depth - before.cnot_depth,
                    "total_depth": after.total_depth - before.total_depth,
                    "parameter_count": after.parameter_count - before.parameter_count,
                    "logical_block_count": after.logical_block_count - before.logical_block_count,
                },
            }
        )

    h2 = AnsatzStructure.create([4], [-0.18820719206269798], [1])
    h2_resources = evaluate_full_circuit_resources(pool, h2, backend)
    if (
        h2_resources.snapshot.cnot_count != 9
        or h2_resources.snapshot.cnot_depth != 7
    ):
        raise RuntimeError("paper-era H2 counter parity failed")
    lih_reference_path = ROOT / "artifacts" / "s1" / "lih-3a-baseline-rerun.json"
    lih_reference = json.loads(lih_reference_path.read_text(encoding="utf-8"))
    lih_structure = AnsatzStructure.create(
        lih_reference["ansatz_indices"],
        lih_reference["ansatz_coefficients"],
        [row["parameter_count"] for row in lih_reference["trajectory"]],
    )
    lih_pool = ResourceOnlyDVGPool(12)
    lih_resources = evaluate_full_circuit_resources(lih_pool, lih_structure, backend)
    lih_structural_resources = evaluate_full_circuit_resources(
        lih_pool,
        lih_structure,
        backend,
        coefficient_policy="deterministic-structural",
    )
    lih_parity = {
        "cnot_count_by_iteration": list(lih_resources.cnot_count_by_iteration)
        == lih_reference["cnot_counts_by_iteration"],
        "cnot_depth_by_iteration": list(lih_resources.cnot_depth_by_iteration)
        == lih_reference["cnot_depths_by_iteration"],
        "parameter_count": lih_resources.snapshot.parameter_count
        == lih_reference["parameter_count"],
        "physical_structural_snapshot_equal": lih_resources.snapshot
        == lih_structural_resources.snapshot,
    }
    if not all(lih_parity.values()):
        raise RuntimeError("canonical LiH resource trajectory parity failed")
    artifact = {
        "schema_version": "1.0.0",
        "artifact_kind": "pinned-upstream-full-circuit-resource-probe",
        "upstream": provenance,
        "evaluator_version": RESOURCE_EVALUATOR_VERSION,
        "backend_version": backend.version,
        "barrier_policy": "preserve-paper-era-block-and-iteration-barriers",
        "global_transpilation": False,
        "source": {
            "indices": list(source.indices),
            "coefficients": list(source.coefficients),
            "iteration_counts": list(source.cumulative_parameter_counts),
            "blocks": [block_to_dict(block) for block in blocks],
            "physical_resources": resources_to_dict(physical),
            "deterministic_structural_resources": resources_to_dict(structural),
            "physical_structural_snapshot_equal": True,
        },
        "h2_parity": resources_to_dict(h2_resources),
        "lih_canonical_parity": {
            "reference_artifact": str(lih_reference_path),
            "checks": lih_parity,
            "resources": resources_to_dict(lih_resources),
            "resource_only_pool_scope": "circuit reconstruction only; never energy or state preparation",
        },
        "candidate_results": candidate_results,
        "claim_boundary": [
            "Probe coordinates are structural test values, not optimized energies.",
            "Resource reductions are full-circuit counts but are not accuracy-accepted results.",
            "No barrier removal, transpilation, or measurement-cost claim is included."
        ],
    }
    _write_once(path, artifact)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    arguments = parser.parse_args()
    sys.argv[:] = [sys.argv[0]]
    artifact = run_probe(arguments.artifact)
    print(json.dumps({"artifact": str(arguments.artifact), "candidates": len(artifact["candidate_results"])}))


if __name__ == "__main__":
    main()
