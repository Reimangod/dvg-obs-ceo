"""Orthogonal V6 transformation and physical-resource evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.identity import canonical_json_bytes, sha256_hex


SCHEMA_VERSION = "1.0.0"
SCHEMA_PATH = ROOT / "schemas/v6-transformation-evidence-v1.schema.json"


class EvidenceError(ValueError):
    """Raised when an evidence record overstates or ambiguously scopes a claim."""


class EvidenceType(str, Enum):
    TARGET_EMBEDDING = "TARGET_EMBEDDING"
    SOURCE_PARAMETER_MEMBERSHIP = "SOURCE_PARAMETER_MEMBERSHIP"
    SOURCE_STATE_EQUIVALENCE = "SOURCE_STATE_EQUIVALENCE"
    SOURCE_UNITARY_EQUIVALENCE = "SOURCE_UNITARY_EQUIVALENCE"
    NATIVE_SYNTHESIS = "NATIVE_SYNTHESIS"
    CONTEXTUAL_REWRITE = "CONTEXTUAL_REWRITE"


class EvidenceStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_ESTABLISHED = "NOT_ESTABLISHED"


class EvidenceStrength(str, Enum):
    ALGEBRAICALLY_PROVEN = "ALGEBRAICALLY_PROVEN"
    SYMBOLICALLY_PROVEN = "SYMBOLICALLY_PROVEN"
    PROVENANCE_DERIVED = "PROVENANCE_DERIVED"
    NUMERICALLY_VALIDATED = "NUMERICALLY_VALIDATED"
    NOT_ESTABLISHED = "NOT_ESTABLISHED"


class SemanticScope(str, Enum):
    PARAMETER_MAP = "PARAMETER_MAP"
    POINTWISE_STATE = "POINTWISE_STATE"
    POINTWISE_UNITARY = "POINTWISE_UNITARY"
    FAMILYWISE_UNITARY = "FAMILYWISE_UNITARY"


class ContextScope(str, Enum):
    CHECKPOINT_FULL_STATE = "CHECKPOINT_FULL_STATE"
    PREFIX_STATE = "PREFIX_STATE"
    LOCAL_BLOCK = "LOCAL_BLOCK"
    ARBITRARY_CIRCUIT_CONTEXT = "ARBITRARY_CIRCUIT_CONTEXT"


class NativeSynthesisScope(str, Enum):
    POINTWISE = "POINTWISE"
    FAMILYWISE = "FAMILYWISE"


class OptimizationRequirement(str, Enum):
    NONE = "NONE"
    POLISHING = "POLISHING"
    FULL_REOPTIMIZATION = "FULL_REOPTIMIZATION"


class ResourceEffect(str, Enum):
    VERIFIED_GAIN = "VERIFIED_GAIN"
    NO_GAIN = "NO_GAIN"
    REGRESSION = "REGRESSION"
    NOT_EVALUATED = "NOT_EVALUATED"


class HumanClassification(str, Enum):
    ALGEBRAIC_EXACT_FAMILY_REWRITE = "ALGEBRAIC_EXACT_FAMILY_REWRITE"
    POINTWISE_UNITARY_EXACT_REWRITE = "POINTWISE_UNITARY_EXACT_REWRITE"
    POINTWISE_STATE_PRESERVING_REWRITE = "POINTWISE_STATE_PRESERVING_REWRITE"
    NUMERICALLY_VALIDATED_LOSSLESS_REWRITE = (
        "NUMERICALLY_VALIDATED_LOSSLESS_REWRITE"
    )
    EXACT_SUBFAMILY_APPROXIMATE_COMPRESSION = (
        "EXACT_SUBFAMILY_APPROXIMATE_COMPRESSION"
    )
    APPROXIMATE_RANK_DEMOTION = "APPROXIMATE_RANK_DEMOTION"
    PURE_REPARAMETERIZATION_NO_RESOURCE_GAIN = (
        "PURE_REPARAMETERIZATION_NO_RESOURCE_GAIN"
    )


def _require_digest(name: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise EvidenceError(f"{name} must be a lowercase SHA-256 digest")


def _schema() -> Mapping[str, Any]:
    value = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(value)
    return value


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): _freeze_json(item)
                for key, item in sorted(value.items())
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_type: EvidenceType
    status: EvidenceStatus
    strength: EvidenceStrength
    semantic_scope: SemanticScope
    context_scope: ContextScope
    method_id: str
    source_semantic_id: str
    target_semantic_id: str
    input_digest: str
    output_digest: str
    tolerance: float | None = None
    details: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not all(
            (self.method_id, self.source_semantic_id, self.target_semantic_id)
        ):
            raise EvidenceError("evidence method and semantic IDs must be explicit")
        _require_digest("input_digest", self.input_digest)
        _require_digest("output_digest", self.output_digest)
        if self.strength is EvidenceStrength.NOT_ESTABLISHED:
            if self.status is not EvidenceStatus.NOT_ESTABLISHED:
                raise EvidenceError(
                    "NOT_ESTABLISHED strength requires NOT_ESTABLISHED status"
                )
        elif self.status is EvidenceStatus.NOT_ESTABLISHED:
            raise EvidenceError(
                "NOT_ESTABLISHED status requires NOT_ESTABLISHED strength"
            )
        if self.strength is EvidenceStrength.NUMERICALLY_VALIDATED:
            if (
                self.tolerance is None
                or not math.isfinite(self.tolerance)
                or self.tolerance <= 0.0
            ):
                raise EvidenceError(
                    "numerically validated evidence requires a positive finite tolerance"
                )
        elif self.tolerance is not None:
            raise EvidenceError(
                "only numerically validated evidence may carry a tolerance"
            )
        if (
            self.evidence_type is EvidenceType.SOURCE_STATE_EQUIVALENCE
            and self.semantic_scope is not SemanticScope.POINTWISE_STATE
        ):
            raise EvidenceError(
                "state equivalence is pointwise-state evidence, not unitary evidence"
            )
        if (
            self.semantic_scope is SemanticScope.POINTWISE_STATE
            and self.context_scope
            not in {
                ContextScope.CHECKPOINT_FULL_STATE,
                ContextScope.PREFIX_STATE,
            }
        ):
            raise EvidenceError(
                "pointwise state evidence must name a state-bearing context"
            )
        canonical_details = json.loads(
            canonical_json_bytes(dict(self.details or {})).decode("utf-8")
        )
        object.__setattr__(self, "details", _freeze_json(canonical_details))

    def _payload_without_id(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "evidence_type": self.evidence_type.value,
            "status": self.status.value,
            "strength": self.strength.value,
            "semantic_scope": self.semantic_scope.value,
            "context_scope": self.context_scope.value,
            "method_id": self.method_id,
            "source_semantic_id": self.source_semantic_id,
            "target_semantic_id": self.target_semantic_id,
            "input_digest": self.input_digest,
            "output_digest": self.output_digest,
            "tolerance": self.tolerance,
            "details": _thaw_json(self.details or {}),
        }

    @property
    def evidence_id(self) -> str:
        return "v6-evidence-v1:" + sha256_hex(self._payload_without_id())

    def to_dict(self) -> dict[str, Any]:
        value = {
            **self._payload_without_id(),
            "evidence_id": self.evidence_id,
        }
        errors = sorted(
            Draft202012Validator(_schema()).iter_errors(value),
            key=lambda error: tuple(str(item) for item in error.absolute_path),
        )
        if errors:
            raise EvidenceError(
                "evidence schema validation failed: "
                + "; ".join(error.message for error in errors)
            )
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceRecord":
        errors = sorted(
            Draft202012Validator(_schema()).iter_errors(dict(value)),
            key=lambda error: tuple(str(item) for item in error.absolute_path),
        )
        if errors:
            raise EvidenceError(
                "evidence schema validation failed: "
                + "; ".join(error.message for error in errors)
            )
        record = cls(
            evidence_type=EvidenceType(value["evidence_type"]),
            status=EvidenceStatus(value["status"]),
            strength=EvidenceStrength(value["strength"]),
            semantic_scope=SemanticScope(value["semantic_scope"]),
            context_scope=ContextScope(value["context_scope"]),
            method_id=value["method_id"],
            source_semantic_id=value["source_semantic_id"],
            target_semantic_id=value["target_semantic_id"],
            input_digest=value["input_digest"],
            output_digest=value["output_digest"],
            tolerance=value["tolerance"],
            details=value["details"],
        )
        if value["evidence_id"] != record.evidence_id:
            raise EvidenceError("evidence_id does not match canonical evidence")
        return record


@dataclass(frozen=True)
class ResourceVector:
    parameter_count: int
    logical_block_count: int
    cnot_count: int
    cnot_depth: int
    total_depth: int

    def __post_init__(self) -> None:
        if any(value < 0 for value in asdict(self).values()):
            raise EvidenceError("resource values must be non-negative")

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class ResourceDeltaEvidence:
    before: ResourceVector
    after: ResourceVector
    resource_counter_version: str
    native_synthesizer_version: str
    compiler_configuration: str
    qubit_order: tuple[int, ...]
    before_digest: str
    after_digest: str
    primary_resource: str = "cnot_count"

    def __post_init__(self) -> None:
        if not all(
            (
                self.resource_counter_version,
                self.native_synthesizer_version,
                self.compiler_configuration,
            )
        ):
            raise EvidenceError("resource provenance must be explicit")
        if sorted(self.qubit_order) != list(range(len(self.qubit_order))):
            raise EvidenceError("qubit order must be a canonical permutation")
        _require_digest("before_digest", self.before_digest)
        _require_digest("after_digest", self.after_digest)
        if self.primary_resource not in asdict(self.before):
            raise EvidenceError("unknown primary resource")

    @property
    def strict_gain(self) -> bool:
        return any(
            after < before
            for before, after in zip(
                asdict(self.before).values(),
                asdict(self.after).values(),
            )
        )

    @property
    def primary_nonregression(self) -> bool:
        return getattr(self.after, self.primary_resource) <= getattr(
            self.before,
            self.primary_resource,
        )

    @property
    def physical_circuit_gain(self) -> bool:
        return any(
            getattr(self.after, field) < getattr(self.before, field)
            for field in (
                "logical_block_count",
                "cnot_count",
                "cnot_depth",
                "total_depth",
            )
        )

    @property
    def effect(self) -> ResourceEffect:
        if not self.primary_nonregression:
            return ResourceEffect.REGRESSION
        if self.strict_gain:
            return ResourceEffect.VERIFIED_GAIN
        return ResourceEffect.NO_GAIN

    def to_dict(self) -> dict[str, Any]:
        return {
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "resource_counter_version": self.resource_counter_version,
            "native_synthesizer_version": self.native_synthesizer_version,
            "compiler_configuration": self.compiler_configuration,
            "qubit_order": list(self.qubit_order),
            "before_digest": self.before_digest,
            "after_digest": self.after_digest,
            "primary_resource": self.primary_resource,
            "strict_gain": self.strict_gain,
            "physical_circuit_gain": self.physical_circuit_gain,
            "primary_nonregression": self.primary_nonregression,
            "effect": self.effect.value,
        }


ALGEBRAIC_STRENGTHS = {
    EvidenceStrength.ALGEBRAICALLY_PROVEN,
    EvidenceStrength.SYMBOLICALLY_PROVEN,
}


def require_algebraic_exact_claim(records: Mapping[EvidenceType, EvidenceRecord]) -> None:
    """Reject an exact claim unless every required axis is strongly established."""
    required = (
        EvidenceType.TARGET_EMBEDDING,
        EvidenceType.SOURCE_UNITARY_EQUIVALENCE,
        EvidenceType.NATIVE_SYNTHESIS,
        EvidenceType.CONTEXTUAL_REWRITE,
    )
    missing = [item.value for item in required if item not in records]
    if missing:
        raise EvidenceError(
            "algebraic exact claim lacks evidence: " + ", ".join(missing)
        )
    weak = [
        item.value
        for item in required
        if records[item].status is not EvidenceStatus.PASSED
        or records[item].strength not in ALGEBRAIC_STRENGTHS
    ]
    if weak:
        raise EvidenceError(
            "algebraic exact claim has non-proven axes: " + ", ".join(weak)
        )
