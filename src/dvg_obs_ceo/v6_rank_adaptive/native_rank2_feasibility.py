"""S5 feasibility study for a native three-QE to rank-two CEO transition."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import platform
import sys
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.linalg import expm

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT, _load_upstream
from dvg_obs_ceo.block_ir import DVGBlock, recover_dvg_blocks
from dvg_obs_ceo.identity import canonical_json_bytes, sha256_hex

from .architecture_state import ParameterMapIR, ParameterMapRepresentation
from .evidence import (
    ContextScope,
    EvidenceRecord,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    NativeSynthesisScope,
    ResourceVector,
    SemanticScope,
)
from .math_evidence import (
    ExactComplex,
    ExactPauliOperator,
    native_synthesis_evidence,
    prove_generator_relation_and_commutation,
)
from .transition_registry import (
    ParameterMapKind,
    TransitionDefinition,
    TransitionRegistry,
    TransitionStatus,
)


DEFAULT_CHECKPOINT = (
    ROOT / "artifacts/full-figures/ceo-star/h6-1.5/checkpoint.json"
)
DEFAULT_OUTPUT = ROOT / "artifacts/v6/s5/native-rank2-feasibility-v1.json"
COUNTER_VERSION = (
    "v6-s5-full-circuit-qasm-v1:"
    "paper-era-qasm-counter-a3f89d0"
)
NATIVE_SYNTHESIS_ID = "v6-mvp3-rank2-sparse-ucry-v1"
TRANSITION_ID = "v6-transition:mvp3-to-sparse-ucry-rank2-v1"
SOURCE_SEMANTIC_ID = "v6-family:MVP3-independent-qe-v1"
TARGET_SEMANTIC_ID = "v6-family:rank2-sparse-ucry-v1"
V41_CATALOG_PATH = (
    ROOT
    / "artifacts/v4.1/s5-sentinels-rerun-v5/h6-1.5/summary.json"
)


class NativeRank2FeasibilityError(RuntimeError):
    """Raised when the native feasibility study cannot establish its gates."""


@dataclass(frozen=True)
class ConditionalRotation:
    pool_index: int
    control_label: int
    angle_scale: str
    support_qubits: tuple[int, ...]
    generator_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "support_qubits": list(self.support_qubits),
        }


def _exact_float(value: float) -> Fraction:
    if not math.isfinite(value):
        raise NativeRank2FeasibilityError(
            "pool generator coefficient is not finite"
        )
    candidate = Fraction(value).limit_denominator(1 << 20)
    if float(candidate) != value:
        raise NativeRank2FeasibilityError(
            "pool coefficient is not an exactly recoverable small rational"
        )
    return candidate


def _local_exact_operator(
    pool: Any,
    pool_index: int,
    support: tuple[int, ...],
) -> ExactPauliOperator:
    if len(support) != 4:
        raise NativeRank2FeasibilityError(
            "rank-two native synthesis requires four-qubit support"
        )
    positions = {qubit: position for position, qubit in enumerate(support)}
    terms: dict[
        tuple[tuple[int, str], ...],
        tuple[Fraction, Fraction],
    ] = {}
    for word, raw_coefficient in pool.get_q_op(pool_index).terms.items():
        if any(int(qubit) not in positions for qubit, _ in word):
            raise NativeRank2FeasibilityError(
                "generator acts outside its declared support"
            )
        local_word = tuple(
            sorted(
                (positions[int(qubit)], str(pauli))
                for qubit, pauli in word
            )
        )
        coefficient = complex(raw_coefficient)
        terms[local_word] = (
            _exact_float(coefficient.real),
            _exact_float(coefficient.imag),
        )
    return ExactPauliOperator.create(terms)


def _apply_word(
    word: tuple[tuple[int, str], ...],
    basis: int,
) -> tuple[int, ExactComplex]:
    output = basis
    coefficient = ExactComplex.create(real=1)
    for qubit, pauli in word:
        mask = 1 << (3 - qubit)
        occupied = bool(basis & mask)
        if pauli == "X":
            output ^= mask
        elif pauli == "Y":
            output ^= mask
            coefficient = coefficient * ExactComplex.create(
                imag=-1 if occupied else 1
            )
        elif pauli == "Z" and occupied:
            coefficient = coefficient * ExactComplex.create(real=-1)
    return output, coefficient


def _exact_matrix_entries(
    operator: ExactPauliOperator,
) -> dict[tuple[int, int], ExactComplex]:
    entries: dict[tuple[int, int], ExactComplex] = {}
    for column in range(16):
        for word, term_coefficient in operator.terms:
            row, pauli_coefficient = _apply_word(word, column)
            entries[(row, column)] = entries.get(
                (row, column),
                ExactComplex(),
            ) + term_coefficient * pauli_coefficient
    return {
        key: value
        for key, value in entries.items()
        if not value.is_zero
    }


def _fanout_basis(value: int) -> int:
    bits = [(value >> (3 - index)) & 1 for index in range(4)]
    transformed = [bits[0]] + [
        bits[index] ^ bits[0] for index in range(1, 4)
    ]
    return sum(bit << (3 - index) for index, bit in enumerate(transformed))


def derive_conditional_rotation(
    pool: Any,
    pool_index: int,
    support: Sequence[int],
) -> tuple[ConditionalRotation, ExactPauliOperator]:
    canonical_support = tuple(sorted(int(value) for value in support))
    if tuple(sorted(pool.get_qubits(pool_index))) != canonical_support:
        raise NativeRank2FeasibilityError(
            "pool support and registered block support disagree"
        )
    operator = _local_exact_operator(pool, pool_index, canonical_support)
    transformed: dict[tuple[int, int], ExactComplex] = {}
    for (row, column), coefficient in _exact_matrix_entries(operator).items():
        transformed[(_fanout_basis(row), _fanout_basis(column))] = coefficient
    if len(transformed) != 2:
        raise NativeRank2FeasibilityError(
            "QE is not one isolated conditional two-level rotation"
        )
    pairs = sorted(transformed)
    row, column = min(pairs)
    if row > column:
        row, column = column, row
    if column - row != 8 or (row & 0b111) != (column & 0b111):
        raise NativeRank2FeasibilityError(
            "fanout did not reduce the QE to one pivot-qubit rotation"
        )
    upper = transformed[(row, column)]
    lower = transformed.get((column, row))
    if (
        upper.imag != 0
        or upper.real not in {Fraction(-1), Fraction(1)}
        or lower != ExactComplex(-upper.real, Fraction(0))
    ):
        raise NativeRank2FeasibilityError(
            "conditional rotation has an unsupported exact amplitude"
        )
    mapping = ConditionalRotation(
        pool_index=int(pool_index),
        control_label=row & 0b111,
        angle_scale=str(-2 * upper.real),
        support_qubits=canonical_support,
        generator_digest=sha256_hex(operator.to_dict()),
    )
    return mapping, operator


def rank2_parameter_map(kept_slots: Sequence[int]) -> ParameterMapIR:
    kept = tuple(int(value) for value in kept_slots)
    if len(kept) != 2 or len(set(kept)) != 2 or any(
        value not in {0, 1, 2} for value in kept
    ):
        raise NativeRank2FeasibilityError(
            "rank-two map must retain two distinct MVP3 slots"
        )
    return ParameterMapIR(
        representation=ParameterMapRepresentation.AFFINE_EXACT,
        source_dimension=3,
        target_dimension=2,
        offset=("0", "0", "0"),
        jacobian=tuple(
            tuple(
                "1" if source_slot == target_slot else "0"
                for target_slot in kept
            )
            for source_slot in range(3)
        ),
        periodicity=None,
        analytic_map_id=None,
        declared_rank=2,
    )


def build_native_rank2_circuit(
    pool: Any,
    kept_indices: Sequence[int],
    coefficients: Sequence[float],
) -> tuple[Any, tuple[ConditionalRotation, ...]]:
    if len(kept_indices) != 2 or len(coefficients) != 2:
        raise NativeRank2FeasibilityError(
            "native rank-two circuit requires two generators and coefficients"
        )
    support_sets = {
        tuple(sorted(int(value) for value in pool.get_qubits(index)))
        for index in kept_indices
    }
    if len(support_sets) != 1:
        raise NativeRank2FeasibilityError(
            "native rank-two generators require one shared support"
        )
    support = next(iter(support_sets))
    mappings = tuple(
        derive_conditional_rotation(pool, int(index), support)[0]
        for index in kept_indices
    )
    if len({item.control_label for item in mappings}) != 2:
        raise NativeRank2FeasibilityError(
            "rank-two generators map to an ambiguous control sector"
        )
    try:
        from qiskit import QuantumCircuit
    except ImportError as error:
        raise NativeRank2FeasibilityError(
            "Qiskit is required for native circuit construction"
        ) from error
    pivot = pool.n - support[0] - 1
    controls = tuple(
        pool.n - support[index] - 1 for index in (3, 2, 1)
    )
    angles = [0.0] * 8
    for mapping, coefficient in zip(mappings, coefficients):
        if not math.isfinite(float(coefficient)):
            raise NativeRank2FeasibilityError(
                "native circuit coefficient is not finite"
            )
        angles[mapping.control_label] = float(
            Fraction(mapping.angle_scale)
        ) * float(coefficient)
    circuit = QuantumCircuit(pool.n)
    for control in reversed(controls):
        circuit.cx(pivot, control)
    circuit.ucry(angles, list(controls), pivot)
    for control in controls:
        circuit.cx(pivot, control)
    return circuit.decompose(reps=10), mappings


def _qasm_resources(
    circuit: Any,
    *,
    parameter_count: int,
    logical_block_count: int,
) -> dict[str, Any]:
    try:
        from adaptvqe.circuits import cnot_count, cnot_depth
        from adaptvqe.op_conv import get_qasm
    except ImportError as error:
        raise NativeRank2FeasibilityError(
            "paper-era QASM counters are unavailable"
        ) from error
    qasm = get_qasm(circuit)
    result = ResourceVector(
        parameter_count=parameter_count,
        logical_block_count=logical_block_count,
        cnot_count=int(cnot_count(qasm)),
        cnot_depth=int(cnot_depth(qasm, circuit.num_qubits)),
        total_depth=int(circuit.depth()),
    )
    return {
        **result.to_dict(),
        "counter_version": COUNTER_VERSION,
        "circuit_qasm_digest": hashlib.sha256(qasm.encode("utf-8")).hexdigest(),
    }


def _compose_checkpoint_circuit(
    pool: Any,
    blocks: Sequence[DVGBlock],
    *,
    target_block_id: str | None = None,
    omitted_pool_index: int | None = None,
) -> tuple[Any, int]:
    try:
        from qiskit import QuantumCircuit
    except ImportError as error:
        raise NativeRank2FeasibilityError(
            "Qiskit is required for full-ansatz reconstruction"
        ) from error
    circuit = QuantumCircuit(pool.n)
    parameter_count = 0
    for block in blocks:
        if block.block_id == target_block_id:
            kept = [
                (index, coefficient)
                for index, coefficient in zip(
                    block.pool_indices,
                    block.coefficients,
                )
                if index != omitted_pool_index
            ]
            if len(kept) != 2:
                raise NativeRank2FeasibilityError(
                    "target block did not yield exactly two kept generators"
                )
            segment, _ = build_native_rank2_circuit(
                pool,
                [item[0] for item in kept],
                [item[1] for item in kept],
            )
            circuit = circuit.compose(segment)
            circuit.barrier()
            parameter_count += 2
        else:
            segment = pool.get_circuit(
                list(block.pool_indices),
                list(block.coefficients),
            )
            circuit = circuit.compose(segment)
            parameter_count += len(block.pool_indices)
    return circuit, parameter_count


def _validate_native_family(
    pool: Any,
    indices: Sequence[int],
    *,
    samples: int = 7,
    seed: int = 6711,
) -> float:
    try:
        from openfermion import get_sparse_operator
        from qiskit.quantum_info import Operator
    except ImportError as error:
        raise NativeRank2FeasibilityError(
            "scientific validation dependencies are unavailable"
        ) from error
    rng = np.random.default_rng(seed)
    maximum = 0.0
    for _ in range(samples):
        coefficients = rng.uniform(-0.7, 0.7, size=2)
        circuit, _ = build_native_rank2_circuit(
            pool,
            indices,
            coefficients,
        )
        observed = np.asarray(Operator(circuit).data, dtype=np.complex128)
        generator = sum(
            (
                coefficient
                * get_sparse_operator(
                    pool.get_q_op(index),
                    n_qubits=pool.n,
                ).toarray()
                for index, coefficient in zip(indices, coefficients)
            ),
            np.zeros_like(observed),
        )
        expected = expm(generator)
        overlap = np.vdot(expected.reshape(-1), observed.reshape(-1))
        phase = overlap / abs(overlap)
        maximum = max(
            maximum,
            float(np.linalg.norm(observed - phase * expected)),
        )
    return maximum


def _mathematical_evidence(pool: Any) -> tuple[list[EvidenceRecord], dict[str, Any]]:
    support = tuple(sorted(pool.get_qubits(6)))
    source_operators = tuple(
        derive_conditional_rotation(pool, index, support)[1]
        for index in (6, 7, 8)
    )
    relations: list[EvidenceRecord] = []
    parameter_maps = []
    commutation_proofs = []
    for kept_slots in ((0, 1), (0, 2), (1, 2)):
        parameter_map = rank2_parameter_map(kept_slots)
        relation, commutation = prove_generator_relation_and_commutation(
            parameter_map,
            source_operators,
            tuple(source_operators[index] for index in kept_slots),
            source_semantic_id=SOURCE_SEMANTIC_ID,
            target_semantic_id=TARGET_SEMANTIC_ID,
        )
        relations.append(relation)
        parameter_maps.append(
            {
                "kept_slots": list(kept_slots),
                "map": parameter_map.to_dict(),
                "target_embedding_evidence_id": relation.evidence_id,
            }
        )
        commutation_proofs.append(commutation)
    if not commutation_proofs:
        raise NativeRank2FeasibilityError(
            "no ordered-subset relation proofs were generated"
        )
    if len({item.output_digest for item in commutation_proofs}) != 1:
        raise NativeRank2FeasibilityError(
            "commutation result changed across ordered-subset maps"
        )
    mappings = tuple(
        derive_conditional_rotation(pool, index, support)[0]
        for index in (6, 7, 8)
    )
    derivation = {
        "basis_map": "y0=x0; yi=xi xor x0 for i=1,2,3",
        "conditional_rotations": [item.to_dict() for item in mappings],
        "angle_rule": "Ry(-2*g_upper*theta)",
        "theorem": (
            "The fanout maps each complementary-basis QE pair to one "
            "distinct control sector and a pivot-bit flip. The direct-sum "
            "UCRY therefore equals exp(sum_i theta_i G_i) for all retained "
            "coordinates."
        ),
        "qiskit_decomposition_reference": (
            "Shende-Bullock-Markov uniformly controlled rotation"
        ),
        "commutation_proof_ids": [
            item.proof_id for item in commutation_proofs
        ],
        "covered_kept_slot_pairs": [[0, 1], [0, 2], [1, 2]],
    }
    native = native_synthesis_evidence(
        source_semantic_id=SOURCE_SEMANTIC_ID,
        target_semantic_id=TARGET_SEMANTIC_ID,
        native_synthesis_scope=NativeSynthesisScope.FAMILYWISE,
        strength=EvidenceStrength.SYMBOLICALLY_PROVEN,
        method_id="v6-complement-pair-to-ucry-derivation-v1",
        proof_input_digest=sha256_hex(
            {
                "parameter_maps": parameter_maps,
                "operators": [item.to_dict() for item in source_operators],
            }
        ),
        proof_output_digest=sha256_hex(derivation),
    )
    context_details = {
        "rule": (
            "equal local unitaries may replace one another in the same ordered "
            "block location without changing prefix or suffix operations"
        ),
        "native_evidence_id": native.evidence_id,
        "target_embedding_evidence_ids": [
            item.evidence_id for item in relations
        ],
        "scope": "ARBITRARY_CIRCUIT_CONTEXT",
    }
    context = EvidenceRecord(
        evidence_type=EvidenceType.CONTEXTUAL_REWRITE,
        status=EvidenceStatus.PASSED,
        strength=EvidenceStrength.SYMBOLICALLY_PROVEN,
        semantic_scope=SemanticScope.FAMILYWISE_UNITARY,
        context_scope=ContextScope.ARBITRARY_CIRCUIT_CONTEXT,
        method_id="v6-equal-local-unitary-substitution-v1",
        source_semantic_id=SOURCE_SEMANTIC_ID,
        target_semantic_id=TARGET_SEMANTIC_ID,
        input_digest=sha256_hex(
            [
                *[item.evidence_id for item in relations],
                native.evidence_id,
            ]
        ),
        output_digest=sha256_hex(context_details),
        details=context_details,
    )
    return [*relations, native, context], {
        "parameter_maps": parameter_maps,
        "commutation_proofs": [
            item.to_dict() for item in commutation_proofs
        ],
        "native_derivation": derivation,
    }


def _collect_key_values(value: Any, key: str) -> set[str]:
    result: set[str] = set()
    if isinstance(value, Mapping):
        if key in value and isinstance(value[key], str):
            result.add(value[key])
        for item in value.values():
            result.update(_collect_key_values(item, key))
    elif isinstance(value, list):
        for item in value:
            result.update(_collect_key_values(item, key))
    return result


def _v41_native_comparison() -> dict[str, Any]:
    catalog = json.loads(V41_CATALOG_PATH.read_text(encoding="utf-8"))
    target_families = sorted(_collect_key_values(catalog, "target_family"))
    candidate_kinds = sorted(_collect_key_values(catalog, "kind"))
    implementation_paths = (
        ROOT / "src/dvg_obs_ceo/block_ir.py",
        ROOT / "src/dvg_obs_ceo/resources.py",
    )
    implementation_text = "\n".join(
        path.read_text(encoding="utf-8") for path in implementation_paths
    )
    sparse_native_absent = (
        "SPARSE_UCRY_RANK2" not in target_families
        and NATIVE_SYNTHESIS_ID
        not in V41_CATALOG_PATH.read_text(encoding="utf-8")
        and NATIVE_SYNTHESIS_ID not in implementation_text
    )
    parameter_only_rank2_present = (
        "MVP" in target_families
        and "mvp-constituent-deletion" in candidate_kinds
        and "paper-era-mvp-ceo-circuit-v1" in implementation_text
    )
    return {
        "catalog_path": str(V41_CATALOG_PATH.relative_to(ROOT)),
        "catalog_sha256": hashlib.sha256(
            V41_CATALOG_PATH.read_bytes()
        ).hexdigest(),
        "observed_target_families": target_families,
        "observed_candidate_kinds": candidate_kinds,
        "implementation_files": [
            {
                "path": str(path.relative_to(ROOT)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in implementation_paths
        ],
        "v4_1_parameter_only_rank2_present": parameter_only_rank2_present,
        "v4_1_sparse_ucry_native_synthesis_absent": sparse_native_absent,
        "interpretation": (
            "V4.1 already generated a rank-two MVP parameter subfamily by "
            "constituent deletion, but retained the paper-era MVP native "
            "circuit. S5 contributes a distinct native synthesis, not a new "
            "mathematical ordered-subset target family."
        ),
    }


def build_report(
    checkpoint_path: Path = DEFAULT_CHECKPOINT,
) -> dict[str, Any]:
    _, DVG_CEO, _, _ = _load_upstream()
    try:
        from adaptvqe.pools import QE_All
    except ImportError as error:
        raise NativeRank2FeasibilityError(
            "pinned upstream QE_All pool is unavailable"
        ) from error
    canonical_pool = QE_All(n=4, couple_exchanges=True)
    canonical_indices = (6, 7, 8)
    evidence, proof_bundle = _mathematical_evidence(canonical_pool)
    relation_evidence = [
        item
        for item in evidence
        if item.evidence_type is EvidenceType.TARGET_EMBEDDING
    ]
    native_evidence = next(
        item
        for item in evidence
        if item.evidence_type is EvidenceType.NATIVE_SYNTHESIS
    )
    context_evidence = next(
        item
        for item in evidence
        if item.evidence_type is EvidenceType.CONTEXTUAL_REWRITE
    )
    v41_comparison = _v41_native_comparison()
    numerical_checks = []
    for omitted in canonical_indices:
        kept = tuple(index for index in canonical_indices if index != omitted)
        residual = _validate_native_family(canonical_pool, kept)
        numerical_checks.append(
            {
                "omitted_pool_index": omitted,
                "kept_pool_indices": list(kept),
                "sample_count": 7,
                "seed": 6711,
                "maximum_unitary_residual_l2": residual,
                "tolerance": 1e-10,
                "passed": residual <= 1e-10,
            }
        )
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    pool = DVG_CEO(n=12)
    blocks = recover_dvg_blocks(
        pool,
        checkpoint["ansatz_indices"],
        checkpoint["ansatz_coefficients"],
        checkpoint["iteration_counts"],
    )
    rank3_blocks = [
        block
        for block in blocks
        if block.family == "MVP" and len(block.pool_indices) == 3
    ]
    source_circuit, source_parameter_count = _compose_checkpoint_circuit(
        pool,
        blocks,
    )
    source_resources = _qasm_resources(
        source_circuit,
        parameter_count=source_parameter_count,
        logical_block_count=len(blocks),
    )
    historical = checkpoint["resources"]["snapshot"]
    source_checks = {
        "parameter_count_matches_checkpoint": (
            source_resources["parameter_count"]
            == historical["parameter_count"]
        ),
        "logical_block_count_matches_checkpoint": (
            source_resources["logical_block_count"]
            == historical["logical_block_count"]
        ),
        "cnot_count_matches_checkpoint": (
            source_resources["cnot_count"] == historical["cnot_count"]
        ),
        "cnot_depth_matches_checkpoint": (
            source_resources["cnot_depth"] == historical["cnot_depth"]
        ),
        "total_depth_matches_checkpoint": (
            source_resources["total_depth"] == historical["total_depth"]
        ),
    }
    if not all(source_checks.values()):
        raise NativeRank2FeasibilityError(
            "S5 source reconstruction disagrees with the frozen H6 checkpoint"
        )
    candidates = []
    for block in rank3_blocks:
        for omitted in block.pool_indices:
            target_circuit, target_parameter_count = (
                _compose_checkpoint_circuit(
                    pool,
                    blocks,
                    target_block_id=block.block_id,
                    omitted_pool_index=omitted,
                )
            )
            target_resources = _qasm_resources(
                target_circuit,
                parameter_count=target_parameter_count,
                logical_block_count=len(blocks),
            )
            delta = {
                field: target_resources[field] - source_resources[field]
                for field in (
                    "parameter_count",
                    "logical_block_count",
                    "cnot_count",
                    "cnot_depth",
                    "total_depth",
                )
            }
            candidates.append(
                {
                    "source_block_id": block.block_id,
                    "source_pool_indices": list(block.pool_indices),
                    "source_ansatz_positions": list(block.ansatz_positions),
                    "omitted_pool_index": omitted,
                    "target_pool_indices": [
                        index
                        for index in block.pool_indices
                        if index != omitted
                    ],
                    "native_conditional_rotations": [
                        derive_conditional_rotation(
                            pool,
                            index,
                            block.support_qubits,
                        )[0].to_dict()
                        for index in block.pool_indices
                        if index != omitted
                    ],
                    "source_resources": source_resources,
                    "target_resources": target_resources,
                    "delta_target_minus_source": delta,
                    "strict_cnot_gain": delta["cnot_count"] < 0,
                    "strict_cnot_depth_gain": delta["cnot_depth"] < 0,
                    "strict_total_depth_gain": delta["total_depth"] < 0,
                    "physical_pareto_nondominated": (
                        delta["parameter_count"] < 0
                        and delta["total_depth"] < 0
                    ),
                    "energy_evaluated": False,
                    "paper_measurement_cost": None,
                }
            )
    go_checks = {
        "native_rank2_synthesis_absent_from_v4_1": (
            v41_comparison[
                "v4_1_parameter_only_rank2_present"
            ]
            and v41_comparison[
                "v4_1_sparse_ucry_native_synthesis_absent"
            ]
        ),
        "target_embedding_registered": (
            len(relation_evidence) == 3
            and all(
                item.status is EvidenceStatus.PASSED
                for item in relation_evidence
            )
        ),
        "familywise_native_synthesis_verified": (
            native_evidence.status is EvidenceStatus.PASSED
            and native_evidence.semantic_scope
            is SemanticScope.FAMILYWISE_UNITARY
        ),
        "context_substitution_verified": (
            context_evidence.status is EvidenceStatus.PASSED
            and context_evidence.context_scope
            is ContextScope.ARBITRARY_CIRCUIT_CONTEXT
        ),
        "all_numerical_unitary_checks_pass": all(
            item["passed"] for item in numerical_checks
        ),
        "representative_full_ansatz_has_depth_gain": any(
            item["strict_cnot_depth_gain"]
            or item["strict_total_depth_gain"]
            for item in candidates
        ),
        "source_reconstruction_exact": all(source_checks.values()),
    }
    go = all(go_checks.values())
    registry = TransitionRegistry.from_definitions(
        [
            TransitionDefinition(
                transition_id=TRANSITION_ID,
                source_family="MVP",
                target_family="SPARSE_UCRY_RANK2",
                allowed_constituent_counts=(3,),
                target_rank=2,
                parameter_map_kind=ParameterMapKind.AFFINE_EXACT,
                parameter_map_id="v6-mvp3-ordered-subset-rank2-map-v1",
                generator_relation_id=(
                    "v6-exact-ordered-qe-subset-relation-v1"
                ),
                native_synthesis_id=NATIVE_SYNTHESIS_ID,
                native_synthesis_scope=NativeSynthesisScope.FAMILYWISE,
                semantic_scope=SemanticScope.FAMILYWISE_UNITARY,
                status=(
                    TransitionStatus.VERIFIED
                    if go
                    else TransitionStatus.PROPOSED
                ),
                evidence_ids=(
                    tuple(item.evidence_id for item in evidence)
                    if go
                    else ()
                ),
            )
        ]
    )
    report = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-s5-native-rank2-feasibility",
        "decision": "GO" if go else "NO_GO",
        "go_checks": go_checks,
        "claim_boundary": (
            "H6 1.5 A development feasibility and circuit semantics only. "
            "No energy, accuracy, optimizer, matched-work, generalization, "
            "or paper Measurement Cost claim."
        ),
        "environment": {
            "python": platform.python_version(),
            "packages": {
                name: version(name)
                for name in (
                    "numpy",
                    "scipy",
                    "qiskit-terra",
                    "openfermion",
                )
            },
            "thread_settings": {
                name: os.environ.get(name)
                for name in (
                    "OMP_NUM_THREADS",
                    "OPENBLAS_NUM_THREADS",
                    "MKL_NUM_THREADS",
                    "VECLIB_MAXIMUM_THREADS",
                    "NUMEXPR_NUM_THREADS",
                )
            },
            "pinned_upstream_commit": (
                "a3f89d03e6a03c89767d3cf8ee7657a57653dda0"
            ),
        },
        "source_move_status": (
            "APPROXIMATE_UNLESS_SOURCE_PARAMETER_MEMBERSHIP_IS_PROVEN"
        ),
        "canonical_model": {
            "pool": "pinned-upstream QE_All(n=4,couple_exchanges=True)",
            "pool_indices": list(canonical_indices),
            **proof_bundle,
        },
        "v4_1_comparison": v41_comparison,
        "evidence": [item.to_dict() for item in evidence],
        "transition_registry": registry.to_dict(),
        "numerical_family_checks": numerical_checks,
        "representative_case": {
            "case_id": checkpoint["case"]["case_id"],
            "checkpoint_path": str(checkpoint_path.relative_to(ROOT)),
            "checkpoint_digest": checkpoint["checkpoint_digest"],
            "rank3_block_count": len(rank3_blocks),
            "source_reconstruction_checks": source_checks,
            "source_resources": source_resources,
            "candidates": candidates,
        },
        "tradeoff": {
            "cnot": (
                "The sparse-UCRY circuit adds one CNOT relative to the "
                "paper-era MVP implementation."
            ),
            "depth": (
                "The candidate reduces total gate depth in the frozen H6 "
                "full ansatz under the same uncompiled QASM counter."
            ),
            "selection_rule": (
                "This transition is a depth/parameter endpoint only and must "
                "not be presented as CNOT compression."
            ),
        },
        "work": {
            "energy_evaluations": 0,
            "gradient_vector_evaluations": 0,
            "gradient_component_equivalents": 0,
            "hvp_evaluations": 0,
            "exact_vqe_attempts": 0,
            "full_resource_recounts": 1 + len(candidates),
            "native_unitary_sample_evaluations": (
                sum(item["sample_count"] for item in numerical_checks)
            ),
            "paper_measurement_cost": None,
        },
        "paper_measurement_cost": None,
    }
    report["report_digest"] = sha256_hex(report)
    return report


def main() -> None:
    try:
        report = build_report()
        atomic_write_new_json(DEFAULT_OUTPUT, report)
    except (
        ImportError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        NativeRank2FeasibilityError,
    ) as error:
        print(f"V6 S5 feasibility failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "report_digest": report["report_digest"],
                "go_checks": report["go_checks"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
