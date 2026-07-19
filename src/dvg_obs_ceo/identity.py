"""Separated scientific identities for state, problem, and measurement context."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import struct
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "scientific-identity-v1.schema.json"
SCHEMA_VERSION = "1.0.0"


class IdentityError(ValueError):
    """Raised when an identity is ambiguous, noncanonical, or incompatible."""


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise IdentityError(f"value is not canonical JSON: {error}") from error


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _require_digest(name: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise IdentityError(f"{name} must be a lowercase SHA-256 digest")


def canonical_float64_hex(values: Iterable[float]) -> tuple[str, ...]:
    result: list[str] = []
    for raw in values:
        value = float(raw)
        if not math.isfinite(value):
            raise IdentityError("identity coefficients must be finite")
        if value == 0.0:
            value = 0.0  # Canonicalize negative zero.
        result.append(struct.pack(">d", value).hex())
    return tuple(result)


@dataclass(frozen=True)
class StatePreparationSpec:
    reference_state: tuple[int, ...]
    generator_definition_digest: str
    ansatz_block_structure: tuple[tuple[str, tuple[int, ...]], ...]
    ansatz_indices: tuple[int, ...]
    coefficient_bytes_hex: tuple[str, ...]
    orbital_parameter_bytes_hex: tuple[str, ...]
    qubit_mapping: str
    qubit_ordering: tuple[int, ...]

    def __post_init__(self) -> None:
        _require_digest("generator_definition_digest", self.generator_definition_digest)
        if any(value not in (0, 1) for value in self.reference_state):
            raise IdentityError("reference state must be a computational-basis bit string")
        if not self.qubit_mapping or sorted(self.qubit_ordering) != list(range(len(self.qubit_ordering))):
            raise IdentityError("qubit mapping and ordering must be explicit and canonical")
        if any(index < 0 for index in self.ansatz_indices):
            raise IdentityError("ansatz indices must be non-negative")
        if len(self.ansatz_indices) != len(self.coefficient_bytes_hex):
            raise IdentityError("ansatz indices and coefficients must have equal length")
        flattened_indices = tuple(
            index for _, indices in self.ansatz_block_structure for index in indices
        )
        if flattened_indices != self.ansatz_indices:
            raise IdentityError(
                "ordered block structure must exactly match the ordered ansatz indices"
            )
        for value in (*self.coefficient_bytes_hex, *self.orbital_parameter_bytes_hex):
            if len(value) != 16 or any(character not in "0123456789abcdef" for character in value):
                raise IdentityError("float64 identity bytes must be 16 lowercase hexadecimal characters")

    @classmethod
    def create(
        cls,
        *,
        reference_state: Iterable[int],
        generator_definition_digest: str,
        ansatz_block_structure: Iterable[tuple[str, Iterable[int]]],
        ansatz_indices: Iterable[int],
        coefficients: Iterable[float],
        orbital_parameters: Iterable[float] = (),
        qubit_mapping: str,
        qubit_ordering: Iterable[int],
    ) -> "StatePreparationSpec":
        return cls(
            tuple(int(value) for value in reference_state),
            generator_definition_digest,
            tuple((str(family), tuple(int(index) for index in indices)) for family, indices in ansatz_block_structure),
            tuple(int(index) for index in ansatz_indices),
            canonical_float64_hex(coefficients),
            canonical_float64_hex(orbital_parameters),
            qubit_mapping,
            tuple(int(index) for index in qubit_ordering),
        )

    def payload(self) -> dict[str, Any]:
        return {
            "reference_state": list(self.reference_state),
            "generator_definition_digest": self.generator_definition_digest,
            "ansatz_block_structure": [
                {"generator_family": family, "indices": list(indices)}
                for family, indices in self.ansatz_block_structure
            ],
            "ansatz_indices": list(self.ansatz_indices),
            "coefficient_bytes_hex": list(self.coefficient_bytes_hex),
            "orbital_parameter_bytes_hex": list(self.orbital_parameter_bytes_hex),
            "qubit_mapping": self.qubit_mapping,
            "qubit_ordering": list(self.qubit_ordering),
        }

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "StatePreparationSpec":
        return cls(
            reference_state=tuple(value["reference_state"]),
            generator_definition_digest=value["generator_definition_digest"],
            ansatz_block_structure=tuple(
                (block["generator_family"], tuple(block["indices"]))
                for block in value["ansatz_block_structure"]
            ),
            ansatz_indices=tuple(value["ansatz_indices"]),
            coefficient_bytes_hex=tuple(value["coefficient_bytes_hex"]),
            orbital_parameter_bytes_hex=tuple(value["orbital_parameter_bytes_hex"]),
            qubit_mapping=value["qubit_mapping"],
            qubit_ordering=tuple(value["qubit_ordering"]),
        )

    @property
    def state_preparation_id(self) -> str:
        return "state-v1:" + sha256_hex(self.payload())


@dataclass(frozen=True)
class ProblemSpec:
    hamiltonian_digest: str
    molecule: str
    geometry_angstrom: tuple[tuple[str, tuple[float, float, float]], ...]
    basis_set: str
    active_space: tuple[int, ...]
    frozen_orbitals: tuple[int, ...]
    fermion_to_qubit_mapping_convention: str

    def __post_init__(self) -> None:
        _require_digest("hamiltonian_digest", self.hamiltonian_digest)
        if not self.molecule or not self.basis_set or not self.fermion_to_qubit_mapping_convention:
            raise IdentityError("problem chemistry and mapping fields must be explicit")
        coordinates = [coordinate for _, point in self.geometry_angstrom for coordinate in point]
        if not coordinates or not all(math.isfinite(float(value)) for value in coordinates):
            raise IdentityError("geometry must contain finite Cartesian coordinates")
        if any(not atom or len(point) != 3 for atom, point in self.geometry_angstrom):
            raise IdentityError("geometry entries require an atom label and three coordinates")
        if any(index < 0 for index in (*self.active_space, *self.frozen_orbitals)):
            raise IdentityError("orbital indices must be non-negative")

    def payload(self) -> dict[str, Any]:
        return {
            "hamiltonian_digest": self.hamiltonian_digest,
            "molecule": self.molecule,
            "geometry_angstrom": [[atom, list(point)] for atom, point in self.geometry_angstrom],
            "basis_set": self.basis_set,
            "active_space": list(self.active_space),
            "frozen_orbitals": list(self.frozen_orbitals),
            "fermion_to_qubit_mapping_convention": self.fermion_to_qubit_mapping_convention,
        }

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "ProblemSpec":
        return cls(
            hamiltonian_digest=value["hamiltonian_digest"],
            molecule=value["molecule"],
            geometry_angstrom=tuple(
                (entry[0], tuple(float(coordinate) for coordinate in entry[1]))
                for entry in value["geometry_angstrom"]
            ),
            basis_set=value["basis_set"],
            active_space=tuple(value["active_space"]),
            frozen_orbitals=tuple(value["frozen_orbitals"]),
            fermion_to_qubit_mapping_convention=value[
                "fermion_to_qubit_mapping_convention"
            ],
        )

    @property
    def problem_id(self) -> str:
        return "problem-v1:" + sha256_hex(self.payload())


@dataclass(frozen=True)
class MeasurementContextSpec:
    state_preparation_id: str
    problem_id: str
    observable_set_digest: str
    measurement_plan_version: str
    grouping_strategy: str
    estimator_version: str
    backend_context_digest: str

    def __post_init__(self) -> None:
        if not self.state_preparation_id.startswith("state-v1:"):
            raise IdentityError("measurement context requires a versioned state ID")
        if not self.problem_id.startswith("problem-v1:"):
            raise IdentityError("measurement context requires a versioned problem ID")
        _require_digest("observable_set_digest", self.observable_set_digest)
        _require_digest("backend_context_digest", self.backend_context_digest)
        if not all((self.measurement_plan_version, self.grouping_strategy, self.estimator_version)):
            raise IdentityError("measurement processing fields must be explicit")

    def payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "MeasurementContextSpec":
        return cls(**dict(value))

    @property
    def measurement_context_id(self) -> str:
        return "measurement-v1:" + sha256_hex(self.payload())


@dataclass(frozen=True)
class ScientificIdentityBundle:
    state: StatePreparationSpec
    problem: ProblemSpec
    measurement: MeasurementContextSpec

    def __post_init__(self) -> None:
        if self.measurement.state_preparation_id != self.state.state_preparation_id:
            raise IdentityError("measurement context is bound to a different state")
        if self.measurement.problem_id != self.problem.problem_id:
            raise IdentityError("measurement context is bound to a different problem")

    def to_dict(self) -> dict[str, Any]:
        value = {
            "schema_version": SCHEMA_VERSION,
            "state_preparation_id": self.state.state_preparation_id,
            "problem_id": self.problem.problem_id,
            "measurement_context_id": self.measurement.measurement_context_id,
            "state": self.state.payload(),
            "problem": self.problem.payload(),
            "measurement": self.measurement.payload(),
        }
        validate_identity_artifact(value)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ScientificIdentityBundle":
        validate_identity_artifact(value)
        return cls(
            StatePreparationSpec.from_payload(value["state"]),
            ProblemSpec.from_payload(value["problem"]),
            MeasurementContextSpec.from_payload(value["measurement"]),
        )


def validate_identity_artifact(value: Mapping[str, Any]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(dict(value)),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        details = "; ".join(
            f"{'/'.join(str(item) for item in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise IdentityError(f"identity schema validation failed: {details}")
    try:
        state = StatePreparationSpec.from_payload(value["state"])
        problem = ProblemSpec.from_payload(value["problem"])
        measurement = MeasurementContextSpec.from_payload(value["measurement"])
    except (KeyError, TypeError, ValueError) as error:
        raise IdentityError(f"identity semantic validation failed: {error}") from error
    expected = {
        "state_preparation_id": state.state_preparation_id,
        "problem_id": problem.problem_id,
        "measurement_context_id": measurement.measurement_context_id,
    }
    for field, expected_id in expected.items():
        if value[field] != expected_id:
            raise IdentityError(f"{field} does not match its canonical payload")
    ScientificIdentityBundle(state, problem, measurement)


def require_measurement_reuse_compatible(
    stored: MeasurementContextSpec, requested: MeasurementContextSpec
) -> None:
    if stored.measurement_context_id != requested.measurement_context_id:
        raise IdentityError(
            "measurement reuse rejected: state, problem, observable, plan, estimator, or backend context differs"
        )
