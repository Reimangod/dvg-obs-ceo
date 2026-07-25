"""V5-S4 risk-aware, energy-blind Pareto selection.

Risk diagnostics affect ordering and refinement requests only.  Independent
VQE acceptance remains the sole authority for committing a candidate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
from typing import Any, Mapping, Sequence

from .identity import canonical_json_bytes
from .telemetry import ResourceSnapshot


SELECTOR_VERSION = "v5-risk-aware-pareto-selector-v1"
SENTINEL_VERSION = "v5-quality-stratified-sentinel-selector-v1"
RESOURCE_FIELDS = (
    "cnot_count",
    "cnot_depth",
    "total_depth",
    "parameter_count",
    "logical_block_count",
)
QUALITY_STRATA = ("good", "boundary", "poor")
FORBIDDEN_SCREENING_KEY_FRAGMENTS = ("actual", "fci")


class V5ParetoError(ValueError):
    """Raised when candidate selection would be ambiguous or unsafe."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _assert_information_firewall(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in FORBIDDEN_SCREENING_KEY_FRAGMENTS):
                raise V5ParetoError(f"forbidden screening field at {path}.{key}")
            _assert_information_firewall(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_information_firewall(item, f"{path}[{index}]")


@dataclass(frozen=True)
class RiskDiagnostics:
    quality_gate_passed: bool
    uncertainty_margin_hartree: float
    quality_stratum: str
    refinement_required: bool
    evidence_digest: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.quality_gate_passed, bool)
            or not isinstance(self.refinement_required, bool)
            or not math.isfinite(self.uncertainty_margin_hartree)
            or self.uncertainty_margin_hartree < 0
            or self.quality_stratum not in QUALITY_STRATA
            or len(self.evidence_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.evidence_digest)
        ):
            raise V5ParetoError("risk diagnostics are invalid")


@dataclass(frozen=True)
class RiskAwareCandidate:
    candidate_ids: tuple[str, ...]
    constraint_semantic_id: str
    constraint_numerical_id: str
    predicted_loss_hartree: float
    resources: ResourceSnapshot
    diagnostics: RiskDiagnostics
    full_resource_recount_succeeded: bool = True
    semantics_validated: bool = True

    def __post_init__(self) -> None:
        if (
            not self.candidate_ids
            or len(set(self.candidate_ids)) != len(self.candidate_ids)
            or not self.constraint_semantic_id.startswith("constraint-semantic-")
            or not self.constraint_numerical_id.startswith("constraint-numerical-")
            or not math.isfinite(self.predicted_loss_hartree)
            or self.predicted_loss_hartree < -1e-12
            or not isinstance(self.full_resource_recount_succeeded, bool)
            or not isinstance(self.semantics_validated, bool)
            or not math.isfinite(
                max(0.0, self.predicted_loss_hartree)
                + self.diagnostics.uncertainty_margin_hartree
            )
        ):
            raise V5ParetoError("risk-aware candidate is invalid")

    @property
    def risk_adjusted_loss_hartree(self) -> float:
        return max(0.0, self.predicted_loss_hartree) + self.diagnostics.uncertainty_margin_hartree


def candidate_from_record(record: Mapping[str, Any]) -> RiskAwareCandidate:
    """Parse an energy-blind record and reject forbidden evidence recursively."""

    _assert_information_firewall(record)
    allowed = {
        "candidate_ids", "constraint_semantic_id", "constraint_numerical_id",
        "predicted_loss_hartree", "resources", "diagnostics",
        "full_resource_recount_succeeded", "semantics_validated",
    }
    unknown = set(record) - allowed
    if unknown:
        raise V5ParetoError(f"unregistered candidate fields: {sorted(unknown)}")
    required = allowed - {"full_resource_recount_succeeded", "semantics_validated"}
    missing = required - set(record)
    if missing:
        raise V5ParetoError(f"missing candidate fields: {sorted(missing)}")
    predicted = record["predicted_loss_hartree"]
    if isinstance(predicted, bool) or not isinstance(predicted, (int, float)):
        raise V5ParetoError("predicted loss must be a JSON number")
    recount = record.get("full_resource_recount_succeeded", True)
    semantics = record.get("semantics_validated", True)
    if not isinstance(recount, bool) or not isinstance(semantics, bool):
        raise V5ParetoError("candidate validation flags must be booleans")
    return RiskAwareCandidate(
        candidate_ids=tuple(record["candidate_ids"]),
        constraint_semantic_id=str(record["constraint_semantic_id"]),
        constraint_numerical_id=str(record["constraint_numerical_id"]),
        predicted_loss_hartree=float(predicted),
        resources=ResourceSnapshot(**record["resources"]),
        diagnostics=RiskDiagnostics(**record["diagnostics"]),
        full_resource_recount_succeeded=recount,
        semantics_validated=semantics,
    )


def _resource_tuple(candidate: RiskAwareCandidate) -> tuple[int, ...]:
    return tuple(int(getattr(candidate.resources, field)) for field in RESOURCE_FIELDS)


def _deduplicate(
    candidates: Sequence[RiskAwareCandidate],
) -> tuple[list[RiskAwareCandidate], dict[str, list[str]]]:
    semantic_ids: set[str] = set()
    by_structure: dict[str, list[RiskAwareCandidate]] = {}
    for candidate in candidates:
        if candidate.constraint_semantic_id in semantic_ids:
            raise V5ParetoError("constraint semantic IDs must be unique")
        semantic_ids.add(candidate.constraint_semantic_id)
        by_structure.setdefault(candidate.resources.structure_digest, []).append(candidate)
    representatives: list[RiskAwareCandidate] = []
    aliases: dict[str, list[str]] = {}
    for digest, group in sorted(by_structure.items()):
        if len({_resource_tuple(candidate) for candidate in group}) != 1:
            raise V5ParetoError("one structure digest has conflicting resource counts")
        representative = min(
            group,
            key=lambda candidate: (
                candidate.risk_adjusted_loss_hartree,
                candidate.predicted_loss_hartree,
                candidate.constraint_semantic_id,
            ),
        )
        representatives.append(representative)
        aliases[digest] = sorted(candidate.constraint_semantic_id for candidate in group)
    return representatives, aliases


def _resource_deltas(candidate: RiskAwareCandidate, source: ResourceSnapshot) -> dict[str, int]:
    return {
        field: int(getattr(candidate.resources, field) - getattr(source, field))
        for field in RESOURCE_FIELDS
    }


def _base_rejection_reasons(
    candidate: RiskAwareCandidate,
    source: ResourceSnapshot,
    screening_budget_hartree: float,
    *,
    require_no_component_regression: bool,
) -> list[str]:
    reasons: list[str] = []
    if not candidate.semantics_validated:
        reasons.append("semantic-validation-failed")
    if not candidate.full_resource_recount_succeeded:
        reasons.append("full-resource-recount-failed")
    if candidate.predicted_loss_hartree > screening_budget_hartree:
        reasons.append("predicted-energy-budget")
    deltas = _resource_deltas(candidate, source)
    if require_no_component_regression and any(value > 0 for value in deltas.values()):
        reasons.append("componentwise-resource-regression")
    if not any(value < 0 for value in deltas.values()):
        reasons.append("no-physical-resource-benefit")
    return reasons


def _dominates(left: RiskAwareCandidate, right: RiskAwareCandidate) -> bool:
    left_values = (*_resource_tuple(left), left.risk_adjusted_loss_hartree)
    right_values = (*_resource_tuple(right), right.risk_adjusted_loss_hartree)
    return all(a <= b for a, b in zip(left_values, right_values)) and any(
        a < b for a, b in zip(left_values, right_values)
    )


def _endpoint_key(candidate: RiskAwareCandidate, primary: str) -> tuple[Any, ...]:
    remaining = tuple(field for field in RESOURCE_FIELDS if field != primary)
    return (
        getattr(candidate.resources, primary),
        candidate.risk_adjusted_loss_hartree,
        *(getattr(candidate.resources, field) for field in remaining),
        candidate.predicted_loss_hartree,
        candidate.constraint_semantic_id,
    )


def select_risk_aware_pareto(
    candidates: Sequence[RiskAwareCandidate],
    source: ResourceSnapshot,
    *,
    screening_budget_hartree: float = 1e-4,
    top_k_per_endpoint: int = 2,
    maximum_unique_attempts: int = 4,
    require_no_component_regression: bool = True,
) -> dict[str, Any]:
    """Return a deterministic Pareto queue without using exact/FCI outcomes."""

    if (
        not math.isfinite(screening_budget_hartree)
        or screening_budget_hartree < 0
        or top_k_per_endpoint <= 0
        or maximum_unique_attempts <= 0
        or not isinstance(require_no_component_regression, bool)
    ):
        raise V5ParetoError("risk-aware selector limits are invalid")
    representatives, aliases = _deduplicate(candidates)
    incompatible_counters = sorted({
        candidate.resources.counter_version for candidate in representatives
        if candidate.resources.counter_version != source.counter_version
    })
    if incompatible_counters:
        raise V5ParetoError(
            "candidate and source resource counter versions differ: "
            + ",".join(incompatible_counters)
        )
    eligible: list[RiskAwareCandidate] = []
    assessments: list[dict[str, Any]] = []
    for candidate in sorted(representatives, key=lambda item: item.constraint_semantic_id):
        reasons = _base_rejection_reasons(
            candidate,
            source,
            screening_budget_hartree,
            require_no_component_regression=require_no_component_regression,
        )
        if not candidate.diagnostics.quality_gate_passed:
            reasons.append("predictor-quality-gate")
        assessments.append({
            "constraint_semantic_id": candidate.constraint_semantic_id,
            "structure_digest": candidate.resources.structure_digest,
            "eligible": not reasons,
            "rejection_reasons": reasons,
            "quality_stratum": candidate.diagnostics.quality_stratum,
            "refinement_required": candidate.diagnostics.refinement_required,
            "risk_adjusted_loss_hartree": candidate.risk_adjusted_loss_hartree,
        })
        if not reasons:
            eligible.append(candidate)
    pareto = [
        candidate for candidate in eligible
        if not any(_dominates(other, candidate) for other in eligible if other is not candidate)
    ]
    endpoints = {
        field: sorted(pareto, key=lambda candidate, primary=field: _endpoint_key(candidate, primary))[
            :top_k_per_endpoint
        ]
        for field in RESOURCE_FIELDS
    }
    queue: list[RiskAwareCandidate] = []
    queue_endpoints: list[str] = []
    seen: set[str] = set()
    for rank in range(top_k_per_endpoint):
        for field in RESOURCE_FIELDS:
            ranked = endpoints[field]
            if rank >= len(ranked):
                continue
            candidate = ranked[rank]
            if candidate.resources.structure_digest not in seen and len(queue) < maximum_unique_attempts:
                seen.add(candidate.resources.structure_digest)
                queue.append(candidate)
                queue_endpoints.append(field)
    payload: dict[str, Any] = {
        "version": SELECTOR_VERSION,
        "screening_budget_hartree": screening_budget_hartree,
        "top_k_per_endpoint": top_k_per_endpoint,
        "maximum_unique_attempts": maximum_unique_attempts,
        "require_no_component_regression": require_no_component_regression,
        "pareto_axes": [*RESOURCE_FIELDS, "risk_adjusted_loss_hartree"],
        "source_structure_digest": source.structure_digest,
        "input_count": len(candidates),
        "deduplicated_structure_count": len(representatives),
        "eligible_count": len(eligible),
        "pareto_semantic_ids": sorted(candidate.constraint_semantic_id for candidate in pareto),
        "endpoint_semantic_ids": {
            field: [candidate.constraint_semantic_id for candidate in ranked]
            for field, ranked in endpoints.items()
        },
        "unique_attempt_semantic_ids": [candidate.constraint_semantic_id for candidate in queue],
        "unique_attempt_endpoints": queue_endpoints,
        "refinement_semantic_ids": sorted(
            candidate.constraint_semantic_id for candidate in eligible
            if candidate.diagnostics.refinement_required
        ),
        "structure_aliases": aliases,
        "assessments": assessments,
        "scientific_boundary": (
            "Risk diagnostics rank or request refinement; exact independent acceptance "
            "alone authorizes a committed state."
        ),
    }
    payload["selection_digest"] = _digest(payload)
    return payload


def select_quality_sentinels(
    candidates: Sequence[RiskAwareCandidate],
    source: ResourceSnapshot,
    *,
    screening_budget_hartree: float,
    maximum_sentinels: int = 3,
    require_no_component_regression: bool = True,
) -> dict[str, Any]:
    """Select calibration-only exact attempts across frozen quality strata."""

    if maximum_sentinels <= 0:
        raise V5ParetoError("sentinel cap must be positive")
    representatives, _ = _deduplicate(candidates)
    if any(
        candidate.resources.counter_version != source.counter_version
        for candidate in representatives
    ):
        raise V5ParetoError("candidate and source resource counter versions differ")
    selected: list[RiskAwareCandidate] = []
    for stratum in QUALITY_STRATA:
        eligible = [
            candidate for candidate in representatives
            if candidate.diagnostics.quality_stratum == stratum
            and not _base_rejection_reasons(
                candidate,
                source,
                screening_budget_hartree,
                require_no_component_regression=require_no_component_regression,
            )
        ]
        if eligible and len(selected) < maximum_sentinels:
            selected.append(min(eligible, key=lambda candidate: (
                candidate.risk_adjusted_loss_hartree,
                _resource_tuple(candidate),
                candidate.constraint_semantic_id,
            )))
    payload: dict[str, Any] = {
        "version": SENTINEL_VERSION,
        "quality_strata": list(QUALITY_STRATA),
        "maximum_sentinels": maximum_sentinels,
        "sentinel_semantic_ids": [candidate.constraint_semantic_id for candidate in selected],
        "sentinel_strata": [candidate.diagnostics.quality_stratum for candidate in selected],
        "usage_boundary": "Calibration-only false-exclusion audit; never production ranking or acceptance.",
    }
    payload["selection_digest"] = _digest(payload)
    return payload


def candidate_to_record(candidate: RiskAwareCandidate) -> dict[str, Any]:
    return {
        "candidate_ids": list(candidate.candidate_ids),
        "constraint_semantic_id": candidate.constraint_semantic_id,
        "constraint_numerical_id": candidate.constraint_numerical_id,
        "predicted_loss_hartree": candidate.predicted_loss_hartree,
        "resources": asdict(candidate.resources),
        "diagnostics": asdict(candidate.diagnostics),
        "full_resource_recount_succeeded": candidate.full_resource_recount_succeeded,
        "semantics_validated": candidate.semantics_validated,
    }
