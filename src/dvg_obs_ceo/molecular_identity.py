"""Canonical three-layer identities for molecular V5 runtime states."""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np

from .block_ir import canonical_operator_payload, recover_dvg_blocks
from .identity import (
    MeasurementContextSpec,
    ProblemSpec,
    StatePreparationSpec,
    canonical_float64_hex,
    canonical_json_bytes,
    sha256_hex,
)
from .transaction import CompressionRuntime


def _hamiltonian_payload(matrix: Any) -> dict[str, Any]:
    canonical = matrix.tocoo(copy=True)
    order = np.lexsort((canonical.col, canonical.row))
    return {
        "shape": [int(value) for value in canonical.shape],
        "row": [int(canonical.row[index]) for index in order],
        "column": [int(canonical.col[index]) for index in order],
        "real_float64_hex": canonical_float64_hex(
            float(np.real(canonical.data[index])) for index in order
        ),
        "imag_float64_hex": canonical_float64_hex(
            float(np.imag(canonical.data[index])) for index in order
        ),
    }


def generator_definition_digest(pool: Any) -> str:
    return sha256_hex(
        [
            canonical_operator_payload(pool.get_q_op(index))
            for index in range(pool.size)
        ]
    )


def state_preparation_spec(
    runtime: CompressionRuntime,
    *,
    algorithm: Any,
    pool: Any,
) -> StatePreparationSpec:
    blocks = recover_dvg_blocks(
        pool,
        runtime.ansatz.indices,
        runtime.ansatz.coefficients,
        runtime.ansatz.cumulative_parameter_counts,
    )
    return StatePreparationSpec.create(
        reference_state=tuple(int(value) for value in algorithm.ref_det),
        generator_definition_digest=generator_definition_digest(pool),
        ansatz_block_structure=tuple(
            (block.family, block.pool_indices) for block in blocks
        ),
        ansatz_indices=runtime.ansatz.indices,
        coefficients=runtime.ansatz.coefficients,
        orbital_parameters=(),
        qubit_mapping="openfermion-jordan-wigner-v1",
        qubit_ordering=range(int(algorithm.n)),
    )


def problem_spec(*, algorithm: Any, case_id: str) -> ProblemSpec:
    molecule = algorithm.molecule
    geometry = tuple(
        (str(atom), tuple(float(coordinate) for coordinate in point))
        for atom, point in molecule.geometry
    )
    return ProblemSpec(
        hamiltonian_digest=hashlib.sha256(
            canonical_json_bytes(_hamiltonian_payload(algorithm.hamiltonian))
        ).hexdigest(),
        molecule=str(getattr(molecule, "name", None) or case_id.split("-", 1)[0]),
        geometry_angstrom=geometry,
        basis_set=str(molecule.basis),
        active_space=tuple(range(int(algorithm.n) // 2)),
        frozen_orbitals=(),
        fermion_to_qubit_mapping_convention="openfermion-jordan-wigner-v1",
    )


def measurement_context(
    *,
    state_preparation_id: str,
    problem_id: str,
) -> MeasurementContextSpec:
    return MeasurementContextSpec(
        state_preparation_id=state_preparation_id,
        problem_id=problem_id,
        observable_set_digest=sha256_hex(
            {"observables": ["energy", "analytic-gradient"]}
        ),
        measurement_plan_version="exact-statevector-v1",
        grouping_strategy="not-applicable-exact-statevector",
        estimator_version="pinned-upstream-exact-v1",
        backend_context_digest=sha256_hex(
            {
                "backend": "noise-free-statevector",
                "threads": {
                    "OMP_NUM_THREADS": "1",
                    "OPENBLAS_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1",
                },
            }
        ),
    )
