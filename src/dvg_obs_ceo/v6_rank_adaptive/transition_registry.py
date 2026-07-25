"""Fail-closed registry for V6 CEO rank transitions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Iterable

from dvg_obs_ceo.identity import sha256_hex

from .evidence import NativeSynthesisScope, SemanticScope


class TransitionRegistryError(ValueError):
    """Raised for unknown, ambiguous, unverified, or mutated transitions."""


class ParameterMapKind(str, Enum):
    AFFINE_EXACT = "AFFINE_EXACT"
    PERIODIC_AFFINE_EXACT = "PERIODIC_AFFINE_EXACT"
    REGISTERED_ANALYTIC_MAP = "REGISTERED_ANALYTIC_MAP"


class TransitionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class TransitionDefinition:
    transition_id: str
    source_family: str
    target_family: str
    allowed_constituent_counts: tuple[int, ...]
    target_rank: int
    parameter_map_kind: ParameterMapKind
    parameter_map_id: str
    generator_relation_id: str
    native_synthesis_id: str
    native_synthesis_scope: NativeSynthesisScope
    semantic_scope: SemanticScope
    status: TransitionStatus
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.transition_id.startswith("v6-transition:"):
            raise TransitionRegistryError("transition_id must be versioned")
        if not all(
            (
                self.source_family,
                self.target_family,
                self.parameter_map_id,
                self.generator_relation_id,
                self.native_synthesis_id,
            )
        ):
            raise TransitionRegistryError(
                "transition semantics and synthesis IDs must be explicit"
            )
        counts = self.allowed_constituent_counts
        if not counts or tuple(sorted(set(counts))) != counts:
            raise TransitionRegistryError(
                "constituent counts must be a sorted unique tuple"
            )
        if any(count not in (1, 2, 3) for count in counts):
            raise TransitionRegistryError("CEO constituent count must be 1, 2, or 3")
        if self.target_rank < 0 or any(
            self.target_rank >= count for count in counts
        ):
            raise TransitionRegistryError(
                "a rank transition must strictly lower every allowed source rank"
            )
        if self.status is TransitionStatus.VERIFIED and not self.evidence_ids:
            raise TransitionRegistryError(
                "verified transition requires evidence IDs"
            )
        if self.status is not TransitionStatus.VERIFIED and self.evidence_ids:
            raise TransitionRegistryError(
                "only verified transitions may bind executable evidence IDs"
            )
        if any(
            not evidence_id.startswith("v6-evidence-v1:")
            for evidence_id in self.evidence_ids
        ):
            raise TransitionRegistryError("transition has an invalid evidence ID")

    @property
    def semantic_key(self) -> tuple[Any, ...]:
        return (
            self.source_family,
            self.target_family,
            self.allowed_constituent_counts,
            self.target_rank,
            self.parameter_map_kind.value,
            self.parameter_map_id,
            self.native_synthesis_id,
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["parameter_map_kind"] = self.parameter_map_kind.value
        value["native_synthesis_scope"] = self.native_synthesis_scope.value
        value["semantic_scope"] = self.semantic_scope.value
        value["status"] = self.status.value
        value["allowed_constituent_counts"] = list(
            self.allowed_constituent_counts
        )
        value["evidence_ids"] = list(self.evidence_ids)
        return value


class TransitionRegistry:
    """Mutable only during construction; frozen before candidate generation."""

    def __init__(self) -> None:
        self._definitions: dict[str, TransitionDefinition] = {}
        self._semantic_keys: set[tuple[Any, ...]] = set()
        self._frozen = False

    def register(self, definition: TransitionDefinition) -> None:
        if self._frozen:
            raise TransitionRegistryError("transition registry is frozen")
        if definition.transition_id in self._definitions:
            raise TransitionRegistryError("duplicate transition ID")
        if definition.semantic_key in self._semantic_keys:
            raise TransitionRegistryError("duplicate transition semantics")
        self._definitions[definition.transition_id] = definition
        self._semantic_keys.add(definition.semantic_key)

    def freeze(self) -> str:
        self._frozen = True
        return self.registry_digest

    @property
    def registry_digest(self) -> str:
        return sha256_hex(
            [
                self._definitions[key].to_dict()
                for key in sorted(self._definitions)
            ]
        )

    def require_executable(self, transition_id: str) -> TransitionDefinition:
        if not self._frozen:
            raise TransitionRegistryError(
                "candidate generation requires a frozen transition registry"
            )
        try:
            definition = self._definitions[transition_id]
        except KeyError as error:
            raise TransitionRegistryError("unknown transition ID") from error
        if definition.status is not TransitionStatus.VERIFIED:
            raise TransitionRegistryError(
                "candidate generation requires a verified transition"
            )
        return definition

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "artifact_kind": "v6-transition-registry",
            "frozen": self._frozen,
            "registry_digest": self.registry_digest,
            "transitions": [
                self._definitions[key].to_dict()
                for key in sorted(self._definitions)
            ],
        }

    @classmethod
    def from_definitions(
        cls,
        definitions: Iterable[TransitionDefinition],
        *,
        freeze: bool = True,
    ) -> "TransitionRegistry":
        registry = cls()
        for definition in definitions:
            registry.register(definition)
        if freeze:
            registry.freeze()
        return registry
