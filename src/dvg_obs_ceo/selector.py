"""Immutable S9 candidate selector with cumulative energy and Pareto guards."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
from typing import Any, Sequence

from .identity import canonical_json_bytes
from .telemetry import ResourceSnapshot


SELECTOR_VERSION = "dvg-obs-selector-v1"
RESOURCE_FIELDS = (
    "cnot_count",
    "cnot_depth",
    "parameter_count",
    "logical_block_count",
    "total_depth",
)


class SelectorError(ValueError):
    """Raised when candidate selection would be ambiguous or unsafe."""


@dataclass(frozen=True)
class SelectorConfig:
    version: str = SELECTOR_VERSION
    predictor: str = "general_constraint_obs"
    cumulative_energy_budget_hartree: float = 1e-4
    resource_lexicographic_order: tuple[str, ...] = RESOURCE_FIELDS
    candidates_per_round: int = 1
    primary_max_accepted_rounds: int = 1
    secondary_greedy_max_accepted_rounds: int = 4
    optimizer_warm_start: str = "projection-on-target-native-obs"
    optimizer_fallback: str = "projection-off-once-if-primary-status-false"
    maximum_optimizer_fallbacks: int = 1
    stop_regime_after_rejected_candidate: bool = True
    require_hessian_quality_gate: bool = True
    require_full_resource_recount: bool = True
    require_semantic_validation: bool = True
    evaluation_oracle_runtime_fields_forbidden: bool = True

    def __post_init__(self) -> None:
        if self.version != SELECTOR_VERSION or self.predictor != "general_constraint_obs":
            raise SelectorError("selector version or predictor is not registered")
        if (
            not math.isfinite(self.cumulative_energy_budget_hartree)
            or self.cumulative_energy_budget_hartree <= 0.0
        ):
            raise SelectorError("selector energy budget must be finite and positive")
        if self.resource_lexicographic_order != RESOURCE_FIELDS:
            raise SelectorError("selector resource priority differs from the frozen order")
        if (
            self.candidates_per_round != 1
            or self.primary_max_accepted_rounds != 1
            or self.secondary_greedy_max_accepted_rounds != 4
            or self.maximum_optimizer_fallbacks != 1
        ):
            raise SelectorError("selector attempt and round limits differ from the frozen protocol")
        if not all(
            (
                self.stop_regime_after_rejected_candidate,
                self.require_hessian_quality_gate,
                self.require_full_resource_recount,
                self.require_semantic_validation,
                self.evaluation_oracle_runtime_fields_forbidden,
            )
        ):
            raise SelectorError("a frozen fail-closed selector gate was disabled")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.to_dict())).hexdigest()


@dataclass(frozen=True)
class CandidateScore:
    candidate_id: str
    equivalence_class_id: str
    kind: str
    target_family: str
    predicted_change_from_source_hartree: float
    source_energy_hartree: float
    budget_reference_energy_hartree: float
    before_resources: ResourceSnapshot
    after_resources: ResourceSnapshot
    hessian_quality_usable: bool
    full_resource_recount_succeeded: bool
    transformation_semantics_validated: bool

    def __post_init__(self) -> None:
        if not all((self.candidate_id, self.equivalence_class_id, self.kind, self.target_family)):
            raise SelectorError("candidate identity and semantics must be explicit")
        values = (
            self.predicted_change_from_source_hartree,
            self.source_energy_hartree,
            self.budget_reference_energy_hartree,
        )
        if any(not math.isfinite(value) for value in values):
            raise SelectorError("candidate energy prediction is non-finite")

    @property
    def predicted_cumulative_change_hartree(self) -> float:
        return (
            self.source_energy_hartree
            - self.budget_reference_energy_hartree
            + self.predicted_change_from_source_hartree
        )

    def resource_delta(self, field: str) -> int:
        return int(getattr(self.after_resources, field) - getattr(self.before_resources, field))


@dataclass(frozen=True)
class CandidateAssessment:
    candidate_id: str
    eligible: bool
    rejection_reasons: tuple[str, ...]
    predicted_cumulative_change_hartree: float
    resource_delta: dict[str, int]


@dataclass(frozen=True)
class SelectionDecision:
    selector_version: str
    selector_digest: str
    chosen_candidate_id: str | None
    assessments: tuple[CandidateAssessment, ...]


def assess_candidate(
    candidate: CandidateScore,
    config: SelectorConfig,
) -> CandidateAssessment:
    reasons: list[str] = []
    if config.require_hessian_quality_gate and not candidate.hessian_quality_usable:
        reasons.append("hessian-quality")
    if config.require_full_resource_recount and not candidate.full_resource_recount_succeeded:
        reasons.append("resource-recount")
    if config.require_semantic_validation and not candidate.transformation_semantics_validated:
        reasons.append("transformation-semantics")
    if (
        candidate.predicted_cumulative_change_hartree
        > config.cumulative_energy_budget_hartree
    ):
        reasons.append("predicted-cumulative-energy-budget")
    deltas = {field: candidate.resource_delta(field) for field in RESOURCE_FIELDS}
    if not all(value <= 0 for value in deltas.values()):
        reasons.append("resource-pareto-regression")
    if not any(value < 0 for value in deltas.values()):
        reasons.append("no-resource-improvement")
    return CandidateAssessment(
        candidate.candidate_id,
        not reasons,
        tuple(reasons),
        candidate.predicted_cumulative_change_hartree,
        deltas,
    )


def select_candidate(
    candidates: Sequence[CandidateScore],
    config: SelectorConfig = SelectorConfig(),
) -> SelectionDecision:
    identifiers = [candidate.candidate_id for candidate in candidates]
    equivalence = [candidate.equivalence_class_id for candidate in candidates]
    if len(identifiers) != len(set(identifiers)):
        raise SelectorError("candidate IDs are not unique")
    if len(equivalence) != len(set(equivalence)):
        raise SelectorError("candidate equivalence classes must be deduplicated before selection")
    assessments = tuple(assess_candidate(candidate, config) for candidate in candidates)
    assessment_by_id = {assessment.candidate_id: assessment for assessment in assessments}
    eligible = [candidate for candidate in candidates if assessment_by_id[candidate.candidate_id].eligible]

    def selection_key(candidate: CandidateScore) -> tuple[Any, ...]:
        return (
            *(candidate.resource_delta(field) for field in config.resource_lexicographic_order),
            candidate.predicted_cumulative_change_hartree,
            candidate.candidate_id,
        )

    chosen = min(eligible, key=selection_key).candidate_id if eligible else None
    return SelectionDecision(
        config.version,
        config.digest,
        chosen,
        assessments,
    )
