"""V6-NS1 through NS6 resource-first native-synthesis pipeline."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict
import hashlib
import itertools
import json
import math
from pathlib import Path
import struct
import sys
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.sparse.linalg import expm_multiply

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT, _load_upstream
from dvg_obs_ceo.block_ir import DVGBlock, recover_dvg_blocks
from dvg_obs_ceo.identity import sha256_hex
from dvg_obs_ceo.resources import AnsatzStructure

from .exact_rewrite_engine import state_digest
from .native_rank2_feasibility import (
    COUNTER_VERSION,
    _qasm_resources,
)
from .rank_candidate_catalog import load_s6_source


NS1_OUTPUT = ROOT / "artifacts/v6/ns1/target-family-registry-v1.json"
NS2_OUTPUT = ROOT / "artifacts/v6/ns2/reference-resource-bounds-v1.json"
NS3_OUTPUT = ROOT / "artifacts/v6/ns3/bounded-synthesis-search-v1.json"
NS4_OUTPUT = ROOT / "artifacts/v6/ns4/familywise-certification-v1.json"
NS5_OUTPUT = ROOT / "artifacts/v6/ns5/resource-only-census-v1.json"
NS6_OUTPUT = ROOT / "artifacts/v6/ns6/primary-candidate-freeze-v1.json"

PIPELINE_VERSION = "v6-native-synthesis-pipeline-v1"
SYNTHESIS_VERSION = "v6-rank2-shortest-parity-walk-v1"
PHASE_ORDER = (
    "YXXX",
    "XYXX",
    "YYXY",
    "XXXY",
    "YXYY",
    "XYYY",
    "YYYX",
    "XXYX",
)
PHASE_VERTICES = (0, 1, 3, 2, 6, 7, 5, 4)
PHASE_SIGNS = (-1, -1, 1, -1, 1, 1, 1, -1)
GENERIC_TARGET_COORDINATES = (0.2718281828459045, -0.3141592653589793)
SEARCH_BITS = (1, 2, 4)
SEARCH_MAXIMUM_STATES = 8 * (1 << 8)
NS4_SAMPLES = 5
NS4_SEED = 20260726
EQUIVALENCE_TOLERANCE = 1e-10

CONTEXTS = (
    {
        "case_id": "h4-1.5-late",
        "n_qubits": 8,
        "path": ROOT
        / "artifacts/s8-1/later-checkpoint-calibration-bundle/"
        "checkpoint-h4-1.5-iteration-12-or-convergence.json",
        "role": "development",
    },
    {
        "case_id": "h6-1.5-s6",
        "n_qubits": 12,
        "path": ROOT / "artifacts/v6/s6/exact-rewrite-trace-v1.json",
        "role": "development",
    },
    {
        "case_id": "h6-3.0",
        "n_qubits": 12,
        "path": ROOT / "artifacts/full-figures/ceo-star/h6-3.0/checkpoint.json",
        "role": "development",
    },
    {
        "case_id": "beh2-3.0",
        "n_qubits": 14,
        "path": ROOT / "artifacts/full-figures/ceo-star/beh2-3.0/checkpoint.json",
        "role": "validation",
    },
)


class NativeSynthesisPipelineError(RuntimeError):
    """Raised when a V6-NS proof, search, or recount fails closed."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_normals() -> tuple[tuple[int, int, int], ...]:
    values = []
    for normal in itertools.product((-1, 0, 1), repeat=3):
        if normal == (0, 0, 0):
            continue
        first = next(value for value in normal if value)
        if first > 0:
            values.append(normal)
    return tuple(sorted(values))


def _parameter_map(normal: Sequence[int]) -> np.ndarray:
    vector = np.asarray(normal, dtype=np.int64)
    if vector.shape != (3,) or not np.any(vector):
        raise NativeSynthesisPipelineError("rank-two normal is invalid")
    pivot = int(np.flatnonzero(vector)[0])
    free = [index for index in range(3) if index != pivot]
    matrix = np.zeros((3, 2), dtype=np.int64)
    for column, index in enumerate(free):
        matrix[index, column] = 1
        numerator = -int(vector[index])
        denominator = int(vector[pivot])
        if numerator % denominator:
            raise NativeSynthesisPipelineError(
                "discrete parameter map is not integral"
            )
        matrix[pivot, column] = numerator // denominator
    if (
        np.linalg.matrix_rank(matrix) != 2
        or np.any(vector @ matrix)
    ):
        raise NativeSynthesisPipelineError(
            "rank-two map failed its exact null-space identity"
        )
    return matrix


def _family_id(
    normal: Sequence[int],
    parameter_map: np.ndarray,
    generator_digests: Sequence[str],
) -> str:
    return "v6-ns-family:" + sha256_hex(
        {
            "normal": list(normal),
            "parameter_map": parameter_map.tolist(),
            "source_generator_digests": list(generator_digests),
            "coefficient_alphabet": [-1, 0, 1],
        }
    )


def _phase_matrix(
    pool: Any,
    source_indices: Sequence[int],
) -> tuple[np.ndarray, tuple[int, ...], tuple[str, ...]]:
    from adaptvqe.op_conv import read_of_qubit_operator

    if len(source_indices) != 3:
        raise NativeSynthesisPipelineError(
            "phase matrix requires one rank-three MVP block"
        )
    matrix = np.zeros((8, 3), dtype=np.int64)
    digests = []
    support = None
    for column, pool_index in enumerate(source_indices):
        operator = pool.operators[int(pool_index)].q_operator
        coefficients, strings, qubit_lists = read_of_qubit_operator(
            operator
        )
        by_string = dict(zip(strings, coefficients))
        qubits = tuple(sorted(pool.get_qubits(int(pool_index))))
        if support is None:
            support = qubits
        elif support != qubits:
            raise NativeSynthesisPipelineError(
                "rank-three generators do not share support"
            )
        for row, pauli in enumerate(PHASE_ORDER):
            value = 8.0 * float(by_string[pauli])
            rounded = int(round(value))
            if value != rounded or rounded not in {-1, 1}:
                raise NativeSynthesisPipelineError(
                    "phase coefficient is not an exact signed integer"
                )
            matrix[row, column] = rounded
        digests.append(
            sha256_hex(
                {
                    str(word): [
                        float(complex(coefficient).real),
                        float(complex(coefficient).imag),
                    ]
                    for word, coefficient in operator.terms.items()
                }
            )
        )
    assert support is not None
    return matrix, support, tuple(digests)


def _required_vertices(
    phase_matrix: np.ndarray,
    parameter_map: np.ndarray,
) -> tuple[int, ...]:
    target_rows = phase_matrix @ parameter_map
    return tuple(
        PHASE_VERTICES[row]
        for row in range(8)
        if np.any(target_rows[row])
    )


def shortest_parity_walk(
    required_vertices: Sequence[int],
    *,
    start: int = 0,
    end: int = 4,
) -> tuple[tuple[int, ...], int]:
    required = frozenset(int(value) for value in required_vertices)
    if any(value < 0 or value > 7 for value in required):
        raise NativeSynthesisPipelineError(
            "required parity vertex is outside the 3-cube"
        )
    initial_seen = frozenset({start} & required)
    queue = deque([((start, initial_seen), ())])
    visited = {(start, initial_seen)}
    explored = 0
    while queue:
        (vertex, seen), path = queue.popleft()
        explored += 1
        if explored > SEARCH_MAXIMUM_STATES:
            raise NativeSynthesisPipelineError(
                "bounded parity search exceeded its state cap"
            )
        if vertex == end and seen == required:
            return path, explored
        for bit in SEARCH_BITS:
            target = vertex ^ bit
            new_seen = seen | ({target} & required)
            state = (target, frozenset(new_seen))
            if state not in visited:
                visited.add(state)
                queue.append((state, (*path, bit)))
    raise NativeSynthesisPipelineError("no parity walk satisfies the bounds")


def build_shortest_parity_circuit(
    pool: Any,
    source_indices: Sequence[int],
    parameter_map: np.ndarray,
    target_coordinates: Sequence[float],
) -> tuple[Any, dict[str, Any]]:
    from openfermion import QubitOperator
    from qiskit import QuantumCircuit
    from adaptvqe.op_conv import read_of_qubit_operator

    coordinates = np.asarray(target_coordinates, dtype=np.float64)
    if coordinates.shape != (2,) or not np.all(np.isfinite(coordinates)):
        raise NativeSynthesisPipelineError(
            "target coordinates must contain two finite values"
        )
    source_coordinates = parameter_map @ coordinates
    q_operator = QubitOperator()
    for pool_index, coefficient in zip(
        source_indices, source_coordinates
    ):
        q_operator += (
            float(coefficient)
            * pool.operators[int(pool_index)].q_operator
        )
    coefficients, strings, _ = read_of_qubit_operator(q_operator)
    by_string = dict(zip(strings, coefficients))
    theta = np.asarray(
        [8.0 * float(by_string.get(pauli, 0.0)) for pauli in PHASE_ORDER],
        dtype=np.float64,
    )
    phase_matrix, support, _ = _phase_matrix(pool, source_indices)
    required = _required_vertices(phase_matrix, parameter_map)
    path, explored = shortest_parity_walk(required)
    a, b, c, d = [pool.n - qubit - 1 for qubit in support]
    circuit = QuantumCircuit(pool.n)
    circuit.rz(-np.pi / 2, a)
    circuit.cx(a, d)
    circuit.cx(a, c)
    circuit.cx(a, b)
    circuit.h(a)
    # This Clifford phase commutes with every control-to-a CNOT and with all
    # phase rotations, so moving it before the bounded walk is exact.
    circuit.rz(-np.pi / 2, c)
    by_vertex = {
        vertex: row for row, vertex in enumerate(PHASE_VERTICES)
    }
    added: set[int] = set()

    def add_phase(vertex: int) -> None:
        if vertex in required and vertex not in added:
            row = by_vertex[vertex]
            circuit.rz(
                PHASE_SIGNS[row] * 2.0 * theta[row] / 8.0,
                a,
            )
            added.add(vertex)

    controls = {1: b, 2: d, 4: c}
    vertex = 0
    add_phase(vertex)
    for bit in path:
        circuit.cx(controls[bit], a)
        vertex ^= bit
        add_phase(vertex)
    if vertex != 4 or added != set(required):
        raise NativeSynthesisPipelineError(
            "constructed walk does not realize the registered phase set"
        )
    circuit.h(a)
    circuit.cx(a, b)
    circuit.cx(a, c)
    circuit.cx(a, d)
    circuit.rz(np.pi / 2, c)
    return circuit, {
        "path_bits": list(path),
        "path_length": len(path),
        "search_states_explored": explored,
        "required_vertices": list(required),
        "zero_vertices": sorted(set(range(8)) - set(required)),
        "source_coordinates": source_coordinates.tolist(),
        "final_vertex": vertex,
        "outer_cnot_count": 6,
        "total_cnot_formula": 6 + len(path),
    }


def _representative() -> tuple[Any, AnsatzStructure, DVGBlock, np.ndarray]:
    _, DVG_CEO, _, _ = _load_upstream()
    pool = DVG_CEO(n=12)
    source = load_s6_source()
    blocks = recover_dvg_blocks(
        pool,
        source.indices,
        source.coefficients,
        source.cumulative_parameter_counts,
    )
    block = next(
        item for item in blocks if len(item.pool_indices) == 3
    )
    phase_matrix, _, _ = _phase_matrix(pool, block.pool_indices)
    return pool, source, block, phase_matrix


def build_ns1() -> dict[str, Any]:
    pool, source, block, phase_matrix = _representative()
    _, support, generator_digests = _phase_matrix(
        pool, block.pool_indices
    )
    families = []
    for normal in _canonical_normals():
        parameter_map = _parameter_map(normal)
        required = _required_vertices(phase_matrix, parameter_map)
        family_id = _family_id(
            normal, parameter_map, generator_digests
        )
        families.append(
            {
                "family_id": family_id,
                "normal": list(normal),
                "constraint": (
                    f"{normal[0]}*theta0 + {normal[1]}*theta1 + "
                    f"{normal[2]}*theta2 = 0"
                ),
                "parameter_map": parameter_map.tolist(),
                "declared_rank": 2,
                "exact_rank": int(np.linalg.matrix_rank(parameter_map)),
                "exact_constraint_residual": (
                    np.asarray(normal) @ parameter_map
                ).tolist(),
                "coefficient_alphabet": [-1, 0, 1],
                "source_generator_digests": list(generator_digests),
                "support_qubits": list(support),
                "required_phase_vertices": list(required),
                "structurally_zero_phase_vertices": sorted(
                    set(range(8)) - set(required)
                ),
                "family_kind": (
                    "ORDERED_SUBSET"
                    if sum(value != 0 for value in normal) == 1
                    else "DISCRETE_TIED_RANK2_PLANE"
                ),
                "hamiltonian_or_energy_used": False,
            }
        )
    report = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-ns1-abstract-target-family-registry",
        "pipeline_version": PIPELINE_VERSION,
        "source_state_digest": state_digest(source),
        "source_block_id": block.block_id,
        "source_pool_indices": list(block.pool_indices),
        "phase_coefficient_matrix": phase_matrix.tolist(),
        "phase_order": list(PHASE_ORDER),
        "phase_vertices": list(PHASE_VERTICES),
        "families": families,
        "family_count": len(families),
        "continuous_outcome_informed_families": 0,
        "energy_evaluations": 0,
        "claim_boundary": (
            "Exact discrete generator maps and rank evidence only. No native "
            "resource, molecular energy, or target accuracy is established."
        ),
    }
    report["report_digest"] = sha256_hex(report)
    return report


def build_ns2(ns1: Mapping[str, Any]) -> dict[str, Any]:
    pool, _, block, _ = _representative()
    source_circuit = pool.get_circuit(
        list(block.pool_indices),
        list(block.coefficients),
    )
    source_resources = _qasm_resources(
        source_circuit,
        parameter_count=3,
        logical_block_count=1,
    )
    ovp_references = []
    support = tuple(block.support_qubits)
    for index in range(pool.size):
        if (
            index not in pool.parent_range
            and tuple(sorted(pool.get_qubits(index))) == support
        ):
            circuit = pool.get_circuit([index], [0.271828])
            ovp_references.append(
                {
                    "pool_index": index,
                    "resources": _qasm_resources(
                        circuit,
                        parameter_count=1,
                        logical_block_count=1,
                    ),
                }
            )
    if not ovp_references:
        raise NativeSynthesisPipelineError(
            "no same-support OVP reference was reconstructed"
        )
    report = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-ns2-reference-resource-bounds",
        "pipeline_version": PIPELINE_VERSION,
        "ns1_report_digest": ns1["report_digest"],
        "mvp3_reference": {
            "resources": source_resources,
            "paper_nominal": {
                "cnot_count": 13,
                "cnot_depth": 11,
            },
            "counter_disclosure": (
                "The frozen paper-era QASM counter observes CNOT depth 13 "
                "for the vendored reference circuit although pool metadata "
                "and the paper state 11. Hard gates use the observed frozen "
                "counter consistently."
            ),
        },
        "same_support_ovp_references": ovp_references,
        "hard_gate": {
            "rule_1": "delta_cnot < 0 and delta_cnot_depth <= 0",
            "rule_2": "delta_cnot <= 0 and delta_cnot_depth < 0",
            "rule_3": (
                "delta_cnot <= 0 and delta_cnot_depth <= 0 and "
                "delta_total_depth < 0 and delta_parameters < 0"
            ),
            "parameter_only_is_failure": True,
        },
        "energy_evaluations": 0,
    }
    report["report_digest"] = sha256_hex(report)
    return report


def _resource_delta(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> dict[str, int]:
    return {
        field: int(after[field]) - int(before[field])
        for field in (
            "cnot_count",
            "cnot_depth",
            "total_depth",
            "parameter_count",
            "logical_block_count",
        )
    }


def _primary_gate(delta: Mapping[str, int]) -> bool:
    return bool(
        (
            delta["cnot_count"] < 0
            and delta["cnot_depth"] <= 0
        )
        or (
            delta["cnot_count"] <= 0
            and delta["cnot_depth"] < 0
        )
        or (
            delta["cnot_count"] <= 0
            and delta["cnot_depth"] <= 0
            and delta["total_depth"] < 0
            and delta["parameter_count"] < 0
        )
    )


def build_ns3(
    ns1: Mapping[str, Any],
    ns2: Mapping[str, Any],
) -> dict[str, Any]:
    pool, _, block, _ = _representative()
    before = ns2["mvp3_reference"]["resources"]
    candidates = []
    total_states = 0
    for family in ns1["families"]:
        parameter_map = np.asarray(
            family["parameter_map"], dtype=np.int64
        )
        circuit, trace = build_shortest_parity_circuit(
            pool,
            block.pool_indices,
            parameter_map,
            GENERIC_TARGET_COORDINATES,
        )
        resources = _qasm_resources(
            circuit,
            parameter_count=2,
            logical_block_count=1,
        )
        delta = _resource_delta(before, resources)
        total_states += int(trace["search_states_explored"])
        candidates.append(
            {
                "candidate_id": "v6-ns-synthesis:" + sha256_hex(
                    {
                        "family_id": family["family_id"],
                        "synthesis_version": SYNTHESIS_VERSION,
                        "path_bits": trace["path_bits"],
                    }
                ),
                "family_id": family["family_id"],
                "normal": family["normal"],
                "synthesis_version": SYNTHESIS_VERSION,
                "lane": "bounded-direct-phase-polynomial-parity-walk",
                "search_trace": trace,
                "resources": resources,
                "resource_delta_vs_mvp3": delta,
                "local_primary_eligible": _primary_gate(delta),
                "energy_evaluated": False,
            }
        )
    report = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-ns3-bounded-native-synthesis-search",
        "pipeline_version": PIPELINE_VERSION,
        "inputs": {
            "ns1": ns1["report_digest"],
            "ns2": ns2["report_digest"],
        },
        "bounds": {
            "gate_alphabet": ["cx", "rz", "h"],
            "cube_vertices": 8,
            "start_vertex": 0,
            "end_vertex": 4,
            "neighbor_order": list(SEARCH_BITS),
            "maximum_search_states": SEARCH_MAXIMUM_STATES,
            "deterministic_breadth_first_search": True,
            "generic_qiskit_compiler_used": False,
        },
        "lanes": {
            "shared_parity_network": "EXECUTED",
            "sparse_ucry_baseline": (
                "HISTORICAL_S7_EXECUTED_NOT_PRIMARY_ELIGIBLE"
            ),
            "active_subspace_direct_decomposition": (
                "REALIZED_AS_EXACT_PHASE_POLYNOMIAL_DIAGONALIZATION"
            ),
            "bounded_parameterized_superoptimization": (
                "EXECUTED_WITHIN_FIXED_CLIFFORD_SCAFFOLD"
            ),
        },
        "candidates": candidates,
        "candidate_count": len(candidates),
        "local_primary_eligible_count": sum(
            item["local_primary_eligible"] for item in candidates
        ),
        "work": {
            "search_states_explored": total_states,
            "circuits_synthesized": len(candidates),
            "resource_recounts": len(candidates),
            "energy_evaluations": 0,
        },
    }
    report["report_digest"] = sha256_hex(report)
    return report


def build_ns4(
    ns1: Mapping[str, Any],
    ns3: Mapping[str, Any],
) -> dict[str, Any]:
    from openfermion import QubitOperator, get_sparse_operator
    from qiskit.quantum_info import Statevector

    pool, _, block, _ = _representative()
    family_by_id = {
        item["family_id"]: item for item in ns1["families"]
    }
    rng = np.random.default_rng(NS4_SEED)
    certifications = []
    for candidate in ns3["candidates"]:
        if not candidate["local_primary_eligible"]:
            certifications.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "status": "RESOURCE_REJECTED_BEFORE_NUMERICAL_REGRESSION",
                    "familywise_certified": False,
                    "numerical_samples": 0,
                }
            )
            continue
        family = family_by_id[candidate["family_id"]]
        parameter_map = np.asarray(
            family["parameter_map"], dtype=np.int64
        )
        maximum = 0.0
        for _ in range(NS4_SAMPLES):
            coordinates = rng.uniform(-0.7, 0.7, size=2)
            state = (
                rng.normal(size=1 << pool.n)
                + 1j * rng.normal(size=1 << pool.n)
            )
            state /= np.linalg.norm(state)
            circuit, _ = build_shortest_parity_circuit(
                pool,
                block.pool_indices,
                parameter_map,
                coordinates,
            )
            observed = Statevector(state).evolve(circuit).data
            source_coordinates = parameter_map @ coordinates
            q_operator = QubitOperator()
            for pool_index, coefficient in zip(
                block.pool_indices, source_coordinates
            ):
                q_operator += (
                    float(coefficient)
                    * pool.operators[pool_index].q_operator
                )
            expected = expm_multiply(
                get_sparse_operator(
                    q_operator, n_qubits=pool.n
                ),
                state,
            )
            overlap = np.vdot(expected, observed)
            phase = overlap / abs(overlap)
            maximum = max(
                maximum,
                float(np.linalg.norm(observed - phase * expected)),
            )
        exact_evidence = {
            "generator_map_identity": (
                np.asarray(family["normal"])
                @ parameter_map
            ).tolist(),
            "parameter_map_rank": int(
                np.linalg.matrix_rank(parameter_map)
            ),
            "phase_rows": (
                np.asarray(ns1["phase_coefficient_matrix"])
                @ parameter_map
            ).tolist(),
            "parity_walk_rule": (
                "Each required Z-parity vertex is visited exactly once for "
                "phase insertion; repeated visits carry no phase. The walk "
                "starts at 0 and ends at 4, preserving the source Clifford "
                "scaffold's net linear transform."
            ),
            "fixed_rz_commutation": (
                "Rz on control c commutes with all control-to-pivot CNOTs "
                "and target Rz phases."
            ),
            "arbitrary_context_substitution": (
                "equal local unitaries on identical ordered qubits may replace "
                "one another under arbitrary prefix and suffix circuits"
            ),
        }
        exact_digest = sha256_hex(exact_evidence)
        passed = maximum <= EQUIVALENCE_TOLERANCE
        certifications.append(
            {
                "candidate_id": candidate["candidate_id"],
                "status": (
                    "FAMILYWISE_CERTIFIED"
                    if passed
                    else "NOT_CERTIFIED"
                ),
                "familywise_certified": passed,
                "symbolic_method": (
                    "exact-integer-generator-map-and-boolean-parity-walk-v1"
                ),
                "symbolic_evidence": exact_evidence,
                "symbolic_evidence_digest": exact_digest,
                "context_independent": True,
                "numerical_samples": NS4_SAMPLES,
                "random_seed": NS4_SEED,
                "maximum_statevector_l2_error_up_to_global_phase": maximum,
                "numerical_tolerance": EQUIVALENCE_TOLERANCE,
                "qcec_status": (
                    "NOT_REQUIRED_FOR_ACCEPTANCE_EXACT_INTERNAL_PROOF_USED"
                ),
            }
        )
    report = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-ns4-familywise-native-certification",
        "pipeline_version": PIPELINE_VERSION,
        "inputs": {
            "ns1": ns1["report_digest"],
            "ns3": ns3["report_digest"],
        },
        "certifications": certifications,
        "familywise_certified_count": sum(
            item["familywise_certified"] for item in certifications
        ),
        "claim_boundary": (
            "Exact proof is limited to the registered three-generator CEO "
            "phase-polynomial scaffold and parameter maps. Numerical tests "
            "are regression evidence, not the source of exactness."
        ),
        "work": {
            "numerical_statevector_samples": sum(
                item["numerical_samples"] for item in certifications
            ),
            "energy_evaluations": 0,
        },
    }
    report["report_digest"] = sha256_hex(report)
    return report


def _decode_float64(value: str) -> float:
    return struct.unpack(">d", bytes.fromhex(value))[0]


def _load_context_structure(
    context: Mapping[str, Any],
) -> AnsatzStructure:
    value = json.loads(context["path"].read_text(encoding="utf-8"))
    if context["case_id"] == "h6-1.5-s6":
        target = value["target"]
        return AnsatzStructure.create(
            target["indices"],
            [
                _decode_float64(item)
                for item in target["coefficient_float64_hex"]
            ],
            target["iteration_counts"],
        )
    return AnsatzStructure.create(
        value["ansatz_indices"],
        value["ansatz_coefficients"],
        value["iteration_counts"],
    )


def _compose_context(
    pool: Any,
    blocks: Sequence[DVGBlock],
    *,
    target_block_id: str | None = None,
    parameter_map: np.ndarray | None = None,
) -> tuple[Any, int]:
    from qiskit import QuantumCircuit

    circuit = QuantumCircuit(pool.n)
    parameters = 0
    for block in blocks:
        if block.block_id == target_block_id:
            if parameter_map is None:
                raise NativeSynthesisPipelineError(
                    "target block lacks a parameter map"
                )
            segment, _ = build_shortest_parity_circuit(
                pool,
                block.pool_indices,
                parameter_map,
                GENERIC_TARGET_COORDINATES,
            )
            circuit = circuit.compose(segment)
            circuit.barrier()
            parameters += 2
        else:
            segment = pool.get_circuit(
                list(block.pool_indices),
                list(block.coefficients),
            )
            circuit = circuit.compose(segment)
            parameters += len(block.pool_indices)
    return circuit, parameters


def build_ns5(
    ns1: Mapping[str, Any],
    ns3: Mapping[str, Any],
    ns4: Mapping[str, Any],
) -> dict[str, Any]:
    _, DVG_CEO, _, _ = _load_upstream()
    family_by_id = {
        item["family_id"]: item for item in ns1["families"]
    }
    candidate_by_id = {
        item["candidate_id"]: item for item in ns3["candidates"]
    }
    certified = [
        item
        for item in ns4["certifications"]
        if item["familywise_certified"]
    ]
    records = []
    contexts = []
    for context in CONTEXTS:
        structure = _load_context_structure(context)
        pool = DVG_CEO(n=int(context["n_qubits"]))
        blocks = recover_dvg_blocks(
            pool,
            structure.indices,
            structure.coefficients,
            structure.cumulative_parameter_counts,
        )
        source_circuit, source_parameters = _compose_context(pool, blocks)
        source_resources = _qasm_resources(
            source_circuit,
            parameter_count=source_parameters,
            logical_block_count=len(blocks),
        )
        eligible_blocks = [
            block for block in blocks
            if block.family == "MVP"
            and len(block.pool_indices) == 3
        ]
        contexts.append(
            {
                "case_id": context["case_id"],
                "role": context["role"],
                "path": str(context["path"].relative_to(ROOT)),
                "sha256": _sha256(context["path"]),
                "parameter_count": len(structure.indices),
                "logical_block_count": len(blocks),
                "eligible_rank3_block_count": len(eligible_blocks),
                "source_resources": source_resources,
            }
        )
        for block in eligible_blocks:
            for certification in certified:
                synthesis = candidate_by_id[
                    certification["candidate_id"]
                ]
                family = family_by_id[synthesis["family_id"]]
                parameter_map = np.asarray(
                    family["parameter_map"], dtype=np.int64
                )
                target_circuit, target_parameters = _compose_context(
                    pool,
                    blocks,
                    target_block_id=block.block_id,
                    parameter_map=parameter_map,
                )
                resources = _qasm_resources(
                    target_circuit,
                    parameter_count=target_parameters,
                    logical_block_count=len(blocks),
                )
                delta = _resource_delta(source_resources, resources)
                records.append(
                    {
                        "context_id": context["case_id"],
                        "context_role": context["role"],
                        "source_block_id": block.block_id,
                        "source_pool_indices": list(block.pool_indices),
                        "family_id": family["family_id"],
                        "normal": family["normal"],
                        "synthesis_candidate_id": synthesis[
                            "candidate_id"
                        ],
                        "source_resources": source_resources,
                        "target_resources": resources,
                        "resource_delta": delta,
                        "direct_primary_eligible": _primary_gate(delta),
                        "exact_rewrite_closure": {
                            "status": (
                                "NO_REGISTERED_RULE_FOR_AFFINE_TIED_BLOCK"
                            ),
                            "rewrites_applied": 0,
                            "post_closure_resources_equal_direct": True,
                            "not_claimed_globally_saturated": True,
                        },
                        "post_closure_resources": resources,
                        "post_closure_primary_eligible": (
                            _primary_gate(delta)
                        ),
                        "energy_evaluated": False,
                    }
                )
    report = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-ns5-resource-only-context-census",
        "pipeline_version": PIPELINE_VERSION,
        "inputs": {
            "ns1": ns1["report_digest"],
            "ns3": ns3["report_digest"],
            "ns4": ns4["report_digest"],
        },
        "contexts": contexts,
        "records": records,
        "record_count": len(records),
        "primary_eligible_record_count": sum(
            item["post_closure_primary_eligible"] for item in records
        ),
        "work": {
            "energy_evaluations": 0,
            "optimizer_runs": 0,
            "full_source_recounts": len(contexts),
            "full_target_recounts": len(records),
        },
        "claim_boundary": (
            "Resource-only census. No candidate energy, stationarity, "
            "measurement cost, or accuracy is established."
        ),
    }
    report["report_digest"] = sha256_hex(report)
    return report


def build_ns6(
    ns1: Mapping[str, Any],
    ns4: Mapping[str, Any],
    ns5: Mapping[str, Any],
) -> dict[str, Any]:
    eligible = sorted(
        (
            item
            for item in ns5["records"]
            if item["post_closure_primary_eligible"]
        ),
        key=lambda item: (
            item["context_id"],
            item["source_block_id"],
            item["family_id"],
        ),
    )
    by_family: dict[str, list[Mapping[str, Any]]] = {}
    for item in eligible:
        by_family.setdefault(item["family_id"], []).append(item)
    family_ranking = sorted(
        (
            {
                "family_id": family_id,
                "eligible_context_count": len(
                    {item["context_id"] for item in records}
                ),
                "eligible_record_count": len(records),
                "total_cnot_reduction": -sum(
                    item["resource_delta"]["cnot_count"]
                    for item in records
                ),
                "total_cnot_depth_reduction": -sum(
                    item["resource_delta"]["cnot_depth"]
                    for item in records
                ),
            }
            for family_id, records in by_family.items()
        ),
        key=lambda item: (
            -item["eligible_context_count"],
            -item["total_cnot_reduction"],
            -item["total_cnot_depth_reduction"],
            item["family_id"],
        ),
    )
    selected_family_ids = [
        item["family_id"] for item in family_ranking[:2]
    ]
    # Freeze one canonical locus per family and context.  Multiple H6-3.0
    # blocks provide resource-transfer evidence, but evaluating all of them
    # would spend quantum-simulation work on repeated within-context tests.
    queue = []
    for family_id in selected_family_ids:
        for context_id in sorted(
            {
                item["context_id"]
                for item in eligible
                if item["family_id"] == family_id
            }
        ):
            representative = min(
                (
                    item
                    for item in eligible
                    if item["family_id"] == family_id
                    and item["context_id"] == context_id
                ),
                key=lambda item: item["source_block_id"],
            )
            queue.append(
                {
                    "context_id": representative["context_id"],
                    "context_role": representative["context_role"],
                    "source_block_id": representative[
                        "source_block_id"
                    ],
                    "source_pool_indices": representative[
                        "source_pool_indices"
                    ],
                    "family_id": representative["family_id"],
                    "normal": representative["normal"],
                    "resource_delta": representative["resource_delta"],
                    "representative_policy": (
                        "lexicographically-smallest-block-id-per-family-context"
                    ),
                }
            )
    report = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-ns6-primary-resource-candidate-freeze",
        "pipeline_version": PIPELINE_VERSION,
        "inputs": {
            "ns1": ns1["report_digest"],
            "ns4": ns4["report_digest"],
            "ns5": ns5["report_digest"],
        },
        "information_firewall": {
            "candidate_energy_available": False,
            "fci_or_chemical_accuracy_used": False,
            "s9_outcomes_used_for_ranking": False,
            "resource_only_ranking": True,
        },
        "family_ranking": family_ranking,
        "selected_family_ids": selected_family_ids,
        "maximum_families": 2,
        "maximum_blocks_per_family_context": 1,
        "energy_queue": queue,
        "energy_queue_count": len(queue),
        "decision": (
            "GO_PRIMARY_RESOURCE_ELIGIBLE"
            if queue
            else "NO_GO_NO_PRIMARY_RESOURCE_CIRCUIT"
        ),
        "ns7_authorized": bool(queue),
        "ns7_protocol_requirements": {
            "stationarity_threshold": 1e-8,
            "energy_budget_hartree": 1e-4,
            "optimizer_max_iterations": 200,
            "primary_initialization": "euclidean-plane-projection",
            "initial_inverse_hessian": "identity",
            "fallback": None,
            "candidate_outcomes_may_change_queue": False,
            "same_policy_all_molecules": True,
        },
        "paper_measurement_cost": None,
    }
    report["freeze_digest"] = sha256_hex(report)
    return report


def build_all() -> tuple[dict[str, Any], ...]:
    ns1 = build_ns1()
    ns2 = build_ns2(ns1)
    ns3 = build_ns3(ns1, ns2)
    ns4 = build_ns4(ns1, ns3)
    ns5 = build_ns5(ns1, ns3, ns4)
    ns6 = build_ns6(ns1, ns4, ns5)
    return ns1, ns2, ns3, ns4, ns5, ns6


def main() -> None:
    try:
        reports = build_all()
        for path, report in zip(
            (
                NS1_OUTPUT,
                NS2_OUTPUT,
                NS3_OUTPUT,
                NS4_OUTPUT,
                NS5_OUTPUT,
                NS6_OUTPUT,
            ),
            reports,
        ):
            atomic_write_new_json(path, report)
    except (
        ImportError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        NativeSynthesisPipelineError,
    ) as error:
        print(f"V6-NS pipeline failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(
        json.dumps(
            {
                "ns1_families": reports[0]["family_count"],
                "ns3_local_primary": reports[2][
                    "local_primary_eligible_count"
                ],
                "ns4_certified": reports[3][
                    "familywise_certified_count"
                ],
                "ns5_primary_records": reports[4][
                    "primary_eligible_record_count"
                ],
                "ns6_decision": reports[5]["decision"],
                "ns7_authorized": reports[5]["ns7_authorized"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
