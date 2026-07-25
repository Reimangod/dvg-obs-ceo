"""Immutable, identity-bound ArchitectureState for V6."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from fractions import Fraction
import json
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator

from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.identity import (
    ScientificIdentityBundle,
    canonical_json_bytes,
    sha256_hex,
)

from .evidence import ResourceVector


SCHEMA_VERSION = "1.0.0"
SCHEMA_PATH = ROOT / "schemas/v6-architecture-state-v1.schema.json"


class ArchitectureStateError(ValueError):
    """Raised when a V6 state is noncanonical or semantically inconsistent."""


class ParameterMapRepresentation(str, Enum):
    IDENTITY = "IDENTITY"
    AFFINE_EXACT = "AFFINE_EXACT"
    PERIODIC_AFFINE_EXACT = "PERIODIC_AFFINE_EXACT"
    REGISTERED_ANALYTIC_MAP = "REGISTERED_ANALYTIC_MAP"


def _require_digest(name: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ArchitectureStateError(
            f"{name} must be a lowercase SHA-256 digest"
        )


def _require_float64_hex(name: str, value: str) -> None:
    if len(value) != 16 or any(character not in "0123456789abcdef" for character in value):
        raise ArchitectureStateError(
            f"{name} must be canonical float64 hexadecimal bytes"
        )


def _canonical_rational(value: str) -> str:
    try:
        fraction = Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ArchitectureStateError(
            f"invalid rational coefficient: {value}"
        ) from error
    canonical = str(fraction)
    if value != canonical:
        raise ArchitectureStateError(
            f"rational coefficient is not canonical: {value} != {canonical}"
        )
    return canonical


def _exact_rank(rows: tuple[tuple[str, ...], ...]) -> int:
    """Return matrix rank using exact rational arithmetic."""
    matrix = [[Fraction(value) for value in row] for row in rows]
    if not matrix:
        return 0
    row_count = len(matrix)
    column_count = len(matrix[0])
    pivot_row = 0
    for column in range(column_count):
        pivot = next(
            (
                row
                for row in range(pivot_row, row_count)
                if matrix[row][column] != 0
            ),
            None,
        )
        if pivot is None:
            continue
        matrix[pivot_row], matrix[pivot] = matrix[pivot], matrix[pivot_row]
        scale = matrix[pivot_row][column]
        matrix[pivot_row] = [value / scale for value in matrix[pivot_row]]
        for row in range(row_count):
            if row == pivot_row:
                continue
            factor = matrix[row][column]
            if factor:
                matrix[row] = [
                    left - factor * right
                    for left, right in zip(
                        matrix[row],
                        matrix[pivot_row],
                    )
                ]
        pivot_row += 1
        if pivot_row == row_count:
            break
    return pivot_row


@dataclass(frozen=True)
class GeneratorSemantic:
    generator_id: str
    operator_digest: str
    support_qubits: tuple[int, ...]
    normalization: str
    orientation: str
    symmetry_quantum_numbers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.generator_id.startswith("generator-v1:"):
            raise ArchitectureStateError("generator ID must be versioned")
        _require_digest("operator_digest", self.operator_digest)
        if (
            not self.support_qubits
            or tuple(sorted(set(self.support_qubits))) != self.support_qubits
            or any(qubit < 0 for qubit in self.support_qubits)
        ):
            raise ArchitectureStateError(
                "generator support must be a sorted unique non-negative tuple"
            )
        if not self.normalization or not self.orientation:
            raise ArchitectureStateError(
                "generator normalization and orientation must be explicit"
            )
        if tuple(sorted(set(self.symmetry_quantum_numbers))) != (
            self.symmetry_quantum_numbers
        ):
            raise ArchitectureStateError(
                "generator symmetry labels must be sorted and unique"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "generator_id": self.generator_id,
            "operator_digest": self.operator_digest,
            "support_qubits": list(self.support_qubits),
            "normalization": self.normalization,
            "orientation": self.orientation,
            "symmetry_quantum_numbers": list(
                self.symmetry_quantum_numbers
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GeneratorSemantic":
        return cls(
            generator_id=value["generator_id"],
            operator_digest=value["operator_digest"],
            support_qubits=tuple(value["support_qubits"]),
            normalization=value["normalization"],
            orientation=value["orientation"],
            symmetry_quantum_numbers=tuple(
                value["symmetry_quantum_numbers"]
            ),
        )


@dataclass(frozen=True)
class ParameterMapIR:
    representation: ParameterMapRepresentation
    source_dimension: int
    target_dimension: int
    offset: tuple[str, ...]
    jacobian: tuple[tuple[str, ...], ...]
    periodicity: tuple[str, ...] | None
    analytic_map_id: str | None
    declared_rank: int

    def __post_init__(self) -> None:
        if self.source_dimension < 1 or self.target_dimension < 0:
            raise ArchitectureStateError(
                "parameter-map dimensions must be non-negative and source nonzero"
            )
        analytic = (
            self.representation
            is ParameterMapRepresentation.REGISTERED_ANALYTIC_MAP
        )
        if analytic:
            if self.offset or self.jacobian:
                raise ArchitectureStateError(
                    "registered analytic map cannot masquerade as an affine map"
                )
        else:
            if len(self.offset) != self.source_dimension:
                raise ArchitectureStateError(
                    "parameter-map offset has the wrong source dimension"
                )
            if len(self.jacobian) != self.source_dimension or any(
                len(row) != self.target_dimension for row in self.jacobian
            ):
                raise ArchitectureStateError(
                    "parameter-map Jacobian shape does not match its dimensions"
                )
            for value in self.offset:
                _canonical_rational(value)
            for row in self.jacobian:
                for value in row:
                    _canonical_rational(value)
            actual_rank = _exact_rank(self.jacobian)
            if self.declared_rank != actual_rank:
                raise ArchitectureStateError(
                    "declared rank does not match the exact affine Jacobian rank"
                )
        if self.periodicity is not None:
            if len(self.periodicity) != self.source_dimension:
                raise ArchitectureStateError(
                    "periodicity has the wrong source dimension"
                )
            for value in self.periodicity:
                if Fraction(_canonical_rational(value)) <= 0:
                    raise ArchitectureStateError(
                        "periodicity values must be positive"
                    )
        if not 0 <= self.declared_rank <= min(
            self.source_dimension,
            self.target_dimension,
        ):
            raise ArchitectureStateError("declared rank is outside map dimensions")
        if self.representation is ParameterMapRepresentation.IDENTITY:
            expected = tuple(
                tuple("1" if row == column else "0" for column in range(self.target_dimension))
                for row in range(self.source_dimension)
            )
            if (
                self.source_dimension != self.target_dimension
                or self.offset != ("0",) * self.source_dimension
                or self.jacobian != expected
                or self.periodicity is not None
                or self.analytic_map_id is not None
                or self.declared_rank != self.source_dimension
            ):
                raise ArchitectureStateError("identity parameter map is not canonical")
        elif self.representation is ParameterMapRepresentation.AFFINE_EXACT:
            if self.periodicity is not None or self.analytic_map_id is not None:
                raise ArchitectureStateError(
                    "affine map cannot carry periodic or analytic metadata"
                )
        elif (
            self.representation
            is ParameterMapRepresentation.PERIODIC_AFFINE_EXACT
        ):
            if self.periodicity is None or self.analytic_map_id is not None:
                raise ArchitectureStateError(
                    "periodic affine map requires only periodicity metadata"
                )
        elif (
            self.representation
            is ParameterMapRepresentation.REGISTERED_ANALYTIC_MAP
        ):
            if not self.analytic_map_id:
                raise ArchitectureStateError(
                    "registered analytic map requires an implementation ID"
                )

    @classmethod
    def identity(cls, dimension: int) -> "ParameterMapIR":
        return cls(
            ParameterMapRepresentation.IDENTITY,
            dimension,
            dimension,
            ("0",) * dimension,
            tuple(
                tuple("1" if row == column else "0" for column in range(dimension))
                for row in range(dimension)
            ),
            None,
            None,
            dimension,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "representation": self.representation.value,
            "source_dimension": self.source_dimension,
            "target_dimension": self.target_dimension,
            "offset": list(self.offset),
            "jacobian": [list(row) for row in self.jacobian],
            "periodicity": (
                None if self.periodicity is None else list(self.periodicity)
            ),
            "analytic_map_id": self.analytic_map_id,
            "declared_rank": self.declared_rank,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ParameterMapIR":
        return cls(
            representation=ParameterMapRepresentation(value["representation"]),
            source_dimension=int(value["source_dimension"]),
            target_dimension=int(value["target_dimension"]),
            offset=tuple(value["offset"]),
            jacobian=tuple(tuple(row) for row in value["jacobian"]),
            periodicity=(
                None
                if value["periodicity"] is None
                else tuple(value["periodicity"])
            ),
            analytic_map_id=value["analytic_map_id"],
            declared_rank=int(value["declared_rank"]),
        )


@dataclass(frozen=True)
class ArchitectureBlock:
    block_id: str
    family: str
    ansatz_positions: tuple[int, ...]
    ansatz_indices: tuple[int, ...]
    coefficient_bytes_hex: tuple[str, ...]
    selection_iteration: int
    generators: tuple[GeneratorSemantic, ...]
    parameter_map: ParameterMapIR
    circuit_implementation_id: str
    native_synthesis_id: str

    def __post_init__(self) -> None:
        if self.block_id != "v6-block-v1:" + sha256_hex(
            self._semantic_payload()
        ):
            raise ArchitectureStateError(
                "block ID does not match canonical block semantics"
            )
        if not self.family or not all(
            (self.circuit_implementation_id, self.native_synthesis_id)
        ):
            raise ArchitectureStateError(
                "block family and synthesis provenance must be explicit"
            )
        if (
            not self.ansatz_positions
            or len(self.ansatz_positions) != len(self.ansatz_indices)
            or len(self.ansatz_indices) != len(self.coefficient_bytes_hex)
        ):
            raise ArchitectureStateError(
                "block positions, indices, and coefficients must align"
            )
        if tuple(sorted(set(self.ansatz_positions))) != self.ansatz_positions:
            raise ArchitectureStateError(
                "block ansatz positions must be sorted and unique"
            )
        if any(index < 0 for index in self.ansatz_indices):
            raise ArchitectureStateError("ansatz indices must be non-negative")
        for value in self.coefficient_bytes_hex:
            _require_float64_hex("coefficient", value)
        if self.selection_iteration < 0:
            raise ArchitectureStateError(
                "selection iteration must be non-negative"
            )
        if not self.generators:
            raise ArchitectureStateError("block requires generator semantics")
        if self.parameter_map.source_dimension != len(self.generators):
            raise ArchitectureStateError(
                "parameter-map source dimension must match generators"
            )
        if self.parameter_map.target_dimension != len(
            self.coefficient_bytes_hex
        ):
            raise ArchitectureStateError(
                "parameter-map target dimension must match coefficients"
            )

    def _semantic_payload(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "ansatz_positions": list(self.ansatz_positions),
            "ansatz_indices": list(self.ansatz_indices),
            "selection_iteration": self.selection_iteration,
            "generators": [item.to_dict() for item in self.generators],
            "parameter_map": self.parameter_map.to_dict(),
            "circuit_implementation_id": self.circuit_implementation_id,
            "native_synthesis_id": self.native_synthesis_id,
        }

    @classmethod
    def create(
        cls,
        *,
        family: str,
        ansatz_positions: tuple[int, ...],
        ansatz_indices: tuple[int, ...],
        coefficient_bytes_hex: tuple[str, ...],
        selection_iteration: int,
        generators: tuple[GeneratorSemantic, ...],
        parameter_map: ParameterMapIR,
        circuit_implementation_id: str,
        native_synthesis_id: str,
    ) -> "ArchitectureBlock":
        temporary = object.__new__(cls)
        fields = {
            "family": family,
            "ansatz_positions": ansatz_positions,
            "ansatz_indices": ansatz_indices,
            "coefficient_bytes_hex": coefficient_bytes_hex,
            "selection_iteration": selection_iteration,
            "generators": generators,
            "parameter_map": parameter_map,
            "circuit_implementation_id": circuit_implementation_id,
            "native_synthesis_id": native_synthesis_id,
        }
        for name, value in fields.items():
            object.__setattr__(temporary, name, value)
        block_id = "v6-block-v1:" + sha256_hex(
            temporary._semantic_payload()
        )
        return cls(block_id=block_id, **fields)

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "family": self.family,
            "ansatz_positions": list(self.ansatz_positions),
            "ansatz_indices": list(self.ansatz_indices),
            "coefficient_bytes_hex": list(self.coefficient_bytes_hex),
            "selection_iteration": self.selection_iteration,
            "generators": [item.to_dict() for item in self.generators],
            "parameter_map": self.parameter_map.to_dict(),
            "circuit_implementation_id": self.circuit_implementation_id,
            "native_synthesis_id": self.native_synthesis_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArchitectureBlock":
        return cls(
            block_id=value["block_id"],
            family=value["family"],
            ansatz_positions=tuple(value["ansatz_positions"]),
            ansatz_indices=tuple(value["ansatz_indices"]),
            coefficient_bytes_hex=tuple(value["coefficient_bytes_hex"]),
            selection_iteration=int(value["selection_iteration"]),
            generators=tuple(
                GeneratorSemantic.from_dict(item)
                for item in value["generators"]
            ),
            parameter_map=ParameterMapIR.from_dict(value["parameter_map"]),
            circuit_implementation_id=value["circuit_implementation_id"],
            native_synthesis_id=value["native_synthesis_id"],
        )


@dataclass(frozen=True)
class ArchitectureResources:
    vector: ResourceVector
    resource_counter_version: str
    native_synthesizer_version: str
    compiler_configuration: str
    qubit_order: tuple[int, ...]
    circuit_digest: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.resource_counter_version,
                self.native_synthesizer_version,
                self.compiler_configuration,
            )
        ):
            raise ArchitectureStateError("resource provenance must be explicit")
        if sorted(self.qubit_order) != list(range(len(self.qubit_order))):
            raise ArchitectureStateError(
                "resource qubit order must be a canonical permutation"
            )
        _require_digest("circuit_digest", self.circuit_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "vector": self.vector.to_dict(),
            "resource_counter_version": self.resource_counter_version,
            "native_synthesizer_version": self.native_synthesizer_version,
            "compiler_configuration": self.compiler_configuration,
            "qubit_order": list(self.qubit_order),
            "circuit_digest": self.circuit_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArchitectureResources":
        return cls(
            vector=ResourceVector(**value["vector"]),
            resource_counter_version=value["resource_counter_version"],
            native_synthesizer_version=value["native_synthesizer_version"],
            compiler_configuration=value["compiler_configuration"],
            qubit_order=tuple(value["qubit_order"]),
            circuit_digest=value["circuit_digest"],
        )


@dataclass(frozen=True)
class WorkLedger:
    energy_evaluations: int = 0
    gradient_vector_evaluations: int = 0
    gradient_component_equivalents: int = 0
    hvp_evaluations: int = 0
    exact_vqe_attempts: int = 0
    full_resource_recounts: int = 0
    rewrite_verifications: int = 0
    optimizer_iterations: int = 0
    search_states: int = 0

    def __post_init__(self) -> None:
        if any(value < 0 for value in asdict(self).values()):
            raise ArchitectureStateError("work counters must be non-negative")

    def to_dict(self) -> dict[str, int | None]:
        return {
            **asdict(self),
            "paper_measurement_cost": None,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkLedger":
        if value.get("paper_measurement_cost") is not None:
            raise ArchitectureStateError(
                "paper Measurement Cost is undefined for V6 work"
            )
        return cls(
            **{
                field: int(value[field])
                for field in cls.__dataclass_fields__
            }
        )


def generator_definition_digest(
    blocks: Iterable[ArchitectureBlock],
) -> str:
    return sha256_hex(
        [
            {
                "block_family": block.family,
                "generators": [
                    generator.to_dict() for generator in block.generators
                ],
            }
            for block in blocks
        ]
    )


@dataclass(frozen=True)
class ArchitectureState:
    identity: ScientificIdentityBundle
    blocks: tuple[ArchitectureBlock, ...]
    resources: ArchitectureResources
    work_ledger: WorkLedger
    evidence_ids: tuple[str, ...]
    transition_registry_digest: str
    protocol_digest: str
    environment_digest: str
    parent_checkpoint_id: str
    parent_checkpoint_digest: str
    original_artifact_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.blocks:
            raise ArchitectureStateError(
                "ArchitectureState requires at least one block"
            )
        flattened_positions = tuple(
            position for block in self.blocks for position in block.ansatz_positions
        )
        if flattened_positions != tuple(range(len(flattened_positions))):
            raise ArchitectureStateError(
                "ordered block positions must exactly cover the ansatz"
            )
        flattened_indices = tuple(
            index for block in self.blocks for index in block.ansatz_indices
        )
        flattened_coefficients = tuple(
            value
            for block in self.blocks
            for value in block.coefficient_bytes_hex
        )
        state = self.identity.state
        if flattened_indices != state.ansatz_indices:
            raise ArchitectureStateError(
                "ArchitectureState indices do not match StatePreparationID"
            )
        if flattened_coefficients != state.coefficient_bytes_hex:
            raise ArchitectureStateError(
                "ArchitectureState coefficients do not match StatePreparationID"
            )
        expected_structure = tuple(
            (block.family, block.ansatz_indices) for block in self.blocks
        )
        if expected_structure != state.ansatz_block_structure:
            raise ArchitectureStateError(
                "ArchitectureState block structure does not match StatePreparationID"
            )
        if generator_definition_digest(self.blocks) != (
            state.generator_definition_digest
        ):
            raise ArchitectureStateError(
                "generator semantics do not match StatePreparationID"
            )
        if self.resources.vector.parameter_count != len(flattened_indices):
            raise ArchitectureStateError(
                "resource parameter count does not match the ansatz"
            )
        if self.resources.vector.logical_block_count != len(self.blocks):
            raise ArchitectureStateError(
                "resource logical-block count does not match the IR"
            )
        if self.resources.qubit_order != state.qubit_ordering:
            raise ArchitectureStateError(
                "resource qubit order does not match StatePreparationID"
            )
        if tuple(sorted(set(self.evidence_ids))) != self.evidence_ids:
            raise ArchitectureStateError(
                "evidence IDs must be sorted and unique"
            )
        if any(
            not item.startswith("v6-evidence-v1:")
            for item in self.evidence_ids
        ):
            raise ArchitectureStateError("invalid evidence ID")
        for name, value in (
            ("transition_registry_digest", self.transition_registry_digest),
            ("protocol_digest", self.protocol_digest),
            ("environment_digest", self.environment_digest),
            ("parent_checkpoint_digest", self.parent_checkpoint_digest),
        ):
            _require_digest(name, value)
        if self.original_artifact_digest is not None:
            _require_digest(
                "original_artifact_digest",
                self.original_artifact_digest,
            )
        if not self.parent_checkpoint_id:
            raise ArchitectureStateError("parent checkpoint ID is required")

    def _payload_without_ids(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "identity": self.identity.to_dict(),
            "blocks": [block.to_dict() for block in self.blocks],
            "resources": self.resources.to_dict(),
            "work_ledger": self.work_ledger.to_dict(),
            "evidence_ids": list(self.evidence_ids),
            "transition_registry_digest": self.transition_registry_digest,
            "protocol_digest": self.protocol_digest,
            "environment_digest": self.environment_digest,
            "parent_checkpoint_id": self.parent_checkpoint_id,
            "parent_checkpoint_digest": self.parent_checkpoint_digest,
            "original_artifact_digest": self.original_artifact_digest,
        }

    @property
    def normalized_ir_digest(self) -> str:
        return sha256_hex(self._payload_without_ids())

    @property
    def architecture_state_id(self) -> str:
        return "architecture-v1:" + self.normalized_ir_digest

    def to_dict(self) -> dict[str, Any]:
        value = {
            **self._payload_without_ids(),
            "architecture_state_id": self.architecture_state_id,
            "normalized_ir_digest": self.normalized_ir_digest,
        }
        errors = sorted(
            Draft202012Validator(
                json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            ).iter_errors(value),
            key=lambda error: tuple(str(item) for item in error.absolute_path),
        )
        if errors:
            raise ArchitectureStateError(
                "ArchitectureState schema validation failed: "
                + "; ".join(error.message for error in errors)
            )
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArchitectureState":
        errors = sorted(
            Draft202012Validator(
                json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            ).iter_errors(dict(value)),
            key=lambda error: tuple(str(item) for item in error.absolute_path),
        )
        if errors:
            raise ArchitectureStateError(
                "ArchitectureState schema validation failed: "
                + "; ".join(error.message for error in errors)
            )
        result = cls(
            identity=ScientificIdentityBundle.from_dict(value["identity"]),
            blocks=tuple(
                ArchitectureBlock.from_dict(item) for item in value["blocks"]
            ),
            resources=ArchitectureResources.from_dict(value["resources"]),
            work_ledger=WorkLedger.from_dict(value["work_ledger"]),
            evidence_ids=tuple(value["evidence_ids"]),
            transition_registry_digest=value["transition_registry_digest"],
            protocol_digest=value["protocol_digest"],
            environment_digest=value["environment_digest"],
            parent_checkpoint_id=value["parent_checkpoint_id"],
            parent_checkpoint_digest=value["parent_checkpoint_digest"],
            original_artifact_digest=value["original_artifact_digest"],
        )
        if value["normalized_ir_digest"] != result.normalized_ir_digest:
            raise ArchitectureStateError(
                "normalized_ir_digest does not match the canonical IR"
            )
        if value["architecture_state_id"] != result.architecture_state_id:
            raise ArchitectureStateError(
                "architecture_state_id does not match the canonical IR"
            )
        canonical_json_bytes(result.to_dict())
        return result
