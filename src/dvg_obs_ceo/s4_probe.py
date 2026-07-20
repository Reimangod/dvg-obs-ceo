"""Generate the registered pinned-upstream S4 semantic probe artifact."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from .baseline import _load_upstream, verify_upstream
from .block_ir import (
    BLOCK_IR_VERSION,
    CANDIDATE_CATALOG_VERSION,
    block_to_dict,
    candidate_to_dict,
    enumerate_candidates,
    recover_dvg_blocks,
    validate_candidate_semantics,
    validate_target_circuit_semantics,
)


def _write_once(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite S4 artifact: {path}")
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
    from openfermion import get_sparse_operator
    from qiskit.quantum_info import Operator

    pool = dvg_ceo(n=4)
    blocks = recover_dvg_blocks(
        pool,
        [4, 2, 3, 0],
        [0.2, 0.3, -0.1, 0.4],
        [3, 4],
    )
    candidates = enumerate_candidates(pool, blocks)
    validated: list[str] = []
    circuit_validated: list[str] = []
    circuit_global_phases: dict[str, list[list[float]]] = {}
    by_id = {block.block_id: block for block in blocks}
    for candidate in candidates:
        block = by_id[candidate.source_block_id]
        sources = [
            get_sparse_operator(pool.get_q_op(index), n_qubits=4).toarray()
            for index in block.pool_indices
        ]
        targets = [
            get_sparse_operator(pool.get_q_op(index), n_qubits=4).toarray()
            for index in candidate.target_pool_indices
        ]
        validate_candidate_semantics(candidate, sources, targets, samples=7, seed=41)
        validated.append(candidate.candidate_id)
        if targets:
            indices = list(candidate.target_pool_indices)
            phases = validate_target_circuit_semantics(
                targets,
                lambda coordinates, values=indices: Operator(
                    pool.get_circuit(values, list(coordinates))
                ).data,
                samples=7,
                seed=43,
            )
            circuit_validated.append(candidate.candidate_id)
            circuit_global_phases[candidate.candidate_id] = [
                [float(phase.real), float(phase.imag)] for phase in phases
            ]

    constrained_mvp_failure = None
    try:
        pool.get_circuit([2, 3], [0.3, 0.3])
    except ValueError as error:
        constrained_mvp_failure = str(error)
    if constrained_mvp_failure is None:
        raise RuntimeError("expected paper-era constrained MVP failure was not observed")

    artifact = {
        "schema_version": "1.0.0",
        "artifact_kind": "pinned-upstream-s4-semantic-probe",
        "upstream": provenance,
        "block_ir_version": BLOCK_IR_VERSION,
        "candidate_catalog_version": CANDIDATE_CATALOG_VERSION,
        "probe": {
            "qubits": 4,
            "ansatz_indices": [4, 2, 3, 0],
            "coefficients": [0.2, 0.3, -0.1, 0.4],
            "iteration_parameter_counts": [3, 4]
        },
        "blocks": [block_to_dict(block) for block in blocks],
        "candidates": [candidate_to_dict(candidate) for candidate in candidates],
        "validation": {
            "tolerance": 1e-10,
            "samples_per_candidate": 7,
            "semantic_seed": 41,
            "native_circuit_seed": 43,
            "generator_unitary_random_state_candidate_ids": validated,
            "native_circuit_candidate_ids": circuit_validated,
            "native_circuit_global_phases_real_imag": circuit_global_phases,
            "mvp_equal_coefficient_in_place_failure": constrained_mvp_failure,
            "native_target_rebuild_required": True
        },
        "claim_boundary": [
            "This probe validates exact small-pool block and transformation semantics.",
            "It makes no molecular-energy or circuit-resource performance claim.",
            "The constrained MVP failure proves native circuit rebuilding is required."
        ]
    }
    _write_once(path, artifact)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    arguments = parser.parse_args()
    sys.argv[:] = [sys.argv[0]]
    artifact = run_probe(arguments.artifact)
    print(json.dumps({"artifact": str(arguments.artifact), "blocks": len(artifact["blocks"]), "candidates": len(artifact["candidates"])}))


if __name__ == "__main__":
    main()
