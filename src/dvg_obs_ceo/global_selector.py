"""Full-resource Pareto and co-primary endpoint selection for Global OBS."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
from typing import Any, Sequence

from .identity import canonical_json_bytes
from .telemetry import ResourceSnapshot


GLOBAL_SELECTOR_VERSION = "global-obs-full-resource-selector-v1"
GUARD_FIELDS = ("parameter_count", "cnot_count", "cnot_depth", "total_depth")
CIRCUIT_ORDER = (
    "cnot_count", "cnot_depth", "total_depth", "parameter_count",
    "predicted_loss_hartree", "constraint_semantic_id",
)
PARAMETER_ORDER = (
    "parameter_count", "cnot_depth", "cnot_count", "total_depth",
    "predicted_loss_hartree", "constraint_semantic_id",
)


class GlobalSelectorError(ValueError):
    """Raised when Global OBS selection inputs are ambiguous or unsafe."""


@dataclass(frozen=True)
class GlobalResourceCandidate:
    candidate_ids: tuple[str, ...]
    constraint_semantic_id: str
    constraint_numerical_id: str
    predicted_loss_hartree: float
    resources: ResourceSnapshot
    full_resource_recount_succeeded: bool = True

    def __post_init__(self) -> None:
        if (
            not self.candidate_ids
            or len(set(self.candidate_ids)) != len(self.candidate_ids)
            or not self.constraint_semantic_id
            or not self.constraint_numerical_id
            or not math.isfinite(self.predicted_loss_hartree)
            or self.predicted_loss_hartree < -1e-12
        ):
            raise GlobalSelectorError("Global resource candidate is invalid")


def _resource_values(snapshot: ResourceSnapshot) -> tuple[int, ...]:
    return tuple(int(getattr(snapshot, field)) for field in GUARD_FIELDS)


def _deduplicate_structure(
    candidates: Sequence[GlobalResourceCandidate],
) -> tuple[list[GlobalResourceCandidate], dict[str, list[str]]]:
    by_digest: dict[str, list[GlobalResourceCandidate]] = {}
    semantic_ids: set[str] = set()
    for candidate in candidates:
        if candidate.constraint_semantic_id in semantic_ids:
            raise GlobalSelectorError("constraint semantic IDs must be unique before selection")
        semantic_ids.add(candidate.constraint_semantic_id)
        by_digest.setdefault(candidate.resources.structure_digest, []).append(candidate)
    representatives: list[GlobalResourceCandidate] = []
    aliases: dict[str, list[str]] = {}
    for digest, group in sorted(by_digest.items()):
        if len({_resource_values(candidate.resources) for candidate in group}) != 1:
            raise GlobalSelectorError("one structure digest has conflicting resource counts")
        representative = min(
            group,
            key=lambda candidate: (
                candidate.predicted_loss_hartree,
                candidate.constraint_semantic_id,
            ),
        )
        representatives.append(representative)
        aliases[digest] = sorted(candidate.constraint_semantic_id for candidate in group)
    return representatives, aliases


def _eligible(
    candidate: GlobalResourceCandidate,
    source: ResourceSnapshot,
    screening_budget_hartree: float,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not candidate.full_resource_recount_succeeded:
        reasons.append("full-resource-recount-failed")
    if candidate.predicted_loss_hartree > screening_budget_hartree:
        reasons.append("predicted-energy-budget")
    deltas = {
        field: int(getattr(candidate.resources, field) - getattr(source, field))
        for field in GUARD_FIELDS
    }
    if not all(value <= 0 for value in deltas.values()):
        reasons.append("componentwise-resource-regression")
    if not any(value < 0 for value in deltas.values()):
        reasons.append("no-strict-resource-improvement")
    return not reasons, reasons


def _dominates(left: GlobalResourceCandidate, right: GlobalResourceCandidate) -> bool:
    fields = (*GUARD_FIELDS, "predicted_loss_hartree")
    left_values = tuple(getattr(left.resources, field) if field in GUARD_FIELDS else getattr(left, field) for field in fields)
    right_values = tuple(getattr(right.resources, field) if field in GUARD_FIELDS else getattr(right, field) for field in fields)
    return all(a <= b for a, b in zip(left_values, right_values)) and any(
        a < b for a, b in zip(left_values, right_values)
    )


def _rank_key(candidate: GlobalResourceCandidate, order: tuple[str, ...]) -> tuple[Any, ...]:
    result: list[Any] = []
    for field in order:
        if field == "predicted_loss_hartree":
            result.append(candidate.predicted_loss_hartree)
        elif field == "constraint_semantic_id":
            result.append(candidate.constraint_semantic_id)
        else:
            result.append(getattr(candidate.resources, field))
    return tuple(result)


def select_global_candidates(
    candidates: Sequence[GlobalResourceCandidate],
    source: ResourceSnapshot,
    *,
    screening_budget_hartree: float = 1e-4,
    top_k_per_endpoint: int = 2,
    maximum_unique_attempts: int = 4,
) -> dict[str, Any]:
    if (
        not math.isfinite(screening_budget_hartree)
        or screening_budget_hartree < 0
        or top_k_per_endpoint <= 0
        or maximum_unique_attempts <= 0
    ):
        raise GlobalSelectorError("Global selector limits are invalid")
    representatives, aliases = _deduplicate_structure(candidates)
    assessments: list[dict[str, Any]] = []
    eligible: list[GlobalResourceCandidate] = []
    for candidate in sorted(representatives, key=lambda value: value.constraint_semantic_id):
        passed, reasons = _eligible(candidate, source, screening_budget_hartree)
        assessments.append({
            "constraint_semantic_id": candidate.constraint_semantic_id,
            "structure_digest": candidate.resources.structure_digest,
            "eligible": passed,
            "rejection_reasons": reasons,
        })
        if passed:
            eligible.append(candidate)
    pareto = [
        candidate for candidate in eligible
        if not any(_dominates(other, candidate) for other in eligible if other is not candidate)
    ]
    circuit = sorted(pareto, key=lambda value: _rank_key(value, CIRCUIT_ORDER))[:top_k_per_endpoint]
    parameter = sorted(pareto, key=lambda value: _rank_key(value, PARAMETER_ORDER))[:top_k_per_endpoint]
    unique_attempts: list[GlobalResourceCandidate] = []
    seen_structures: set[str] = set()
    for rank in range(top_k_per_endpoint):
        for ranked in (circuit, parameter):
            if rank >= len(ranked):
                continue
            candidate = ranked[rank]
            digest = candidate.resources.structure_digest
            if digest not in seen_structures and len(unique_attempts) < maximum_unique_attempts:
                seen_structures.add(digest)
                unique_attempts.append(candidate)
    payload = {
        "version": GLOBAL_SELECTOR_VERSION,
        "screening_budget_hartree": screening_budget_hartree,
        "top_k_per_endpoint": top_k_per_endpoint,
        "maximum_unique_attempts": maximum_unique_attempts,
        "circuit_order": list(CIRCUIT_ORDER),
        "parameter_order": list(PARAMETER_ORDER),
        "source_structure_digest": source.structure_digest,
        "input_count": len(candidates),
        "deduplicated_structure_count": len(representatives),
        "eligible_count": len(eligible),
        "pareto_semantic_ids": sorted(value.constraint_semantic_id for value in pareto),
        "circuit_primary": [value.constraint_semantic_id for value in circuit],
        "parameter_primary": [value.constraint_semantic_id for value in parameter],
        "unique_attempt_semantic_ids": [value.constraint_semantic_id for value in unique_attempts],
        "structure_aliases": aliases,
        "assessments": assessments,
    }
    payload["selection_digest"] = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return payload
