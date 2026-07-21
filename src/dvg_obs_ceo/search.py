"""Deterministic branch-and-bound over canonical Global OBS states."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Callable, Mapping, Sequence


SEARCH_VERSION = "global-obs-search-v1"


class SearchError(RuntimeError):
    """Raised when search inputs or evaluator invariants are unsafe."""


@dataclass(frozen=True)
class SearchCandidate:
    candidate_id: str
    group_id: str

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.group_id:
            raise SearchError("search candidates require stable candidate and group IDs")


@dataclass(frozen=True)
class SearchEvaluation:
    status: str
    constraint_semantic_id: str | None
    constraint_numerical_id: str | None
    predicted_loss_hartree: float | None
    resource_vector: tuple[int, ...] | None = None
    optimistic_endpoint_possible: bool = True
    reason: str | None = None

    def validate(self) -> None:
        allowed = {"valid", "candidate-numerical-failure", "semantic-infeasible"}
        if self.status not in allowed:
            raise SearchError(f"unregistered evaluation status: {self.status}")
        if self.status == "valid":
            if (
                not self.constraint_semantic_id
                or not self.constraint_numerical_id
                or self.predicted_loss_hartree is None
                or not math.isfinite(self.predicted_loss_hartree)
            ):
                raise SearchError("valid evaluation lacks finite canonical evidence")
            if self.resource_vector is not None and any(value < 0 for value in self.resource_vector):
                raise SearchError("resource vectors must be nonnegative")
        elif not self.reason:
            raise SearchError("failed evaluation requires an explicit reason")


@dataclass(frozen=True)
class SearchConfig:
    screening_budget_hartree: float
    maximum_expanded_nodes: int
    maximum_completed_states: int
    maximum_quadratic_solves: int

    def validate(self) -> None:
        if not math.isfinite(self.screening_budget_hartree):
            if self.screening_budget_hartree != math.inf:
                raise SearchError("screening budget must be finite or positive infinity")
        if self.screening_budget_hartree < 0:
            raise SearchError("screening budget must be nonnegative")
        budgets = (
            self.maximum_expanded_nodes,
            self.maximum_completed_states,
            self.maximum_quadratic_solves,
        )
        if any(not isinstance(value, int) or value <= 0 for value in budgets):
            raise SearchError("deterministic search budgets must be positive integers")


def deterministic_search(
    candidates: Sequence[SearchCandidate],
    evaluator: Callable[[tuple[str, ...]], SearchEvaluation],
    config: SearchConfig,
) -> dict[str, object]:
    """Explore at most one candidate per group with monotone fail-closed pruning."""

    config.validate()
    if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
        raise SearchError("candidate IDs are not unique")
    groups: dict[str, list[str]] = {}
    for candidate in sorted(candidates, key=lambda value: (value.group_id, value.candidate_id)):
        groups.setdefault(candidate.group_id, []).append(candidate.candidate_id)
    ordered_groups = tuple(sorted(groups))
    options = {group: (None, *tuple(groups[group])) for group in ordered_groups}
    # ``evaluate_current`` is true only when the transition added a candidate.
    # A run of ``None`` choices therefore cannot re-evaluate the same subset.
    stack: list[tuple[int, tuple[str, ...], bool]] = [(0, (), False)]
    records: list[dict[str, object]] = []
    semantic_seen: set[str] = set()
    counts = {
        "expanded": 0,
        "completed": 0,
        "quadratic_solves": 0,
        "deduplicated": 0,
        "pruned_predicted_loss": 0,
        "pruned_semantic_infeasible": 0,
        "pruned_resource_bound": 0,
        "candidate_numerical_failures": 0,
    }
    truncated_reason: str | None = None
    monotone_pruning_used = False

    while stack:
        if counts["expanded"] >= config.maximum_expanded_nodes:
            truncated_reason = "maximum-expanded-nodes"
            break
        depth, selected, evaluate_current = stack.pop()
        counts["expanded"] += 1
        prune_descendants = False
        if selected and evaluate_current:
            if counts["completed"] >= config.maximum_completed_states:
                truncated_reason = "maximum-completed-states"
                break
            if counts["quadratic_solves"] >= config.maximum_quadratic_solves:
                truncated_reason = "maximum-quadratic-solves"
                break
            try:
                evaluation = evaluator(selected)
                evaluation.validate()
            except Exception as error:
                raise SearchError("required search evaluator failed") from error
            counts["completed"] += 1
            counts["quadratic_solves"] += 1
            record = {
                "candidate_ids": list(selected),
                "depth": depth,
                "evaluation": asdict(evaluation),
                "eligible": False,
                "prune_descendants": False,
                "prune_reason": None,
            }
            if evaluation.status == "semantic-infeasible":
                prune_descendants = True
                monotone_pruning_used = True
                counts["pruned_semantic_infeasible"] += 1
                record["prune_descendants"] = True
                record["prune_reason"] = "semantic-infeasible"
            elif evaluation.status == "candidate-numerical-failure":
                counts["candidate_numerical_failures"] += 1
            else:
                semantic_id = str(evaluation.constraint_semantic_id)
                if semantic_id in semantic_seen:
                    counts["deduplicated"] += 1
                    record["prune_reason"] = "semantic-deduplication-current-node-only"
                else:
                    semantic_seen.add(semantic_id)
                    record["eligible"] = bool(
                        evaluation.predicted_loss_hartree <= config.screening_budget_hartree
                        and evaluation.optimistic_endpoint_possible
                    )
                if evaluation.predicted_loss_hartree > config.screening_budget_hartree:
                    prune_descendants = True
                    monotone_pruning_used = True
                    counts["pruned_predicted_loss"] += 1
                    record["prune_descendants"] = True
                    record["prune_reason"] = "fixed-surrogate-predicted-loss-bound"
                elif not evaluation.optimistic_endpoint_possible:
                    prune_descendants = True
                    monotone_pruning_used = True
                    counts["pruned_resource_bound"] += 1
                    record["prune_descendants"] = True
                    record["prune_reason"] = "proven-optimistic-resource-bound"
            records.append(record)
        if depth == len(ordered_groups) or prune_descendants:
            continue
        group = ordered_groups[depth]
        children: list[tuple[int, tuple[str, ...], bool]] = []
        for candidate_id in options[group]:
            next_selected = selected if candidate_id is None else tuple(sorted((*selected, candidate_id)))
            children.append((depth + 1, next_selected, candidate_id is not None))
        for child in reversed(children):
            stack.append(child)

    if truncated_reason is not None:
        status = "budget-truncated"
    elif monotone_pruning_used:
        status = "surrogate-complete"
    else:
        status = "exhaustive"
    eligible = [record for record in records if record["eligible"]]
    return {
        "version": SEARCH_VERSION,
        "status": status,
        "truncated_reason": truncated_reason,
        "group_order": list(ordered_groups),
        "candidate_order_by_group": {group: list(groups[group]) for group in ordered_groups},
        "counts": counts,
        "eligible_semantic_ids": sorted(
            str(record["evaluation"]["constraint_semantic_id"])
            for record in eligible
        ),
        "records": records,
    }


def pareto_records(
    records: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    valid = [
        record
        for record in records
        if record.get("eligible")
        and record["evaluation"].get("resource_vector") is not None  # type: ignore[union-attr]
    ]
    result: list[Mapping[str, object]] = []
    for record in valid:
        evaluation = record["evaluation"]  # type: ignore[assignment]
        vector = tuple(evaluation["resource_vector"]) + (evaluation["predicted_loss_hartree"],)  # type: ignore[index]
        dominated = False
        for other in valid:
            if other is record:
                continue
            other_evaluation = other["evaluation"]  # type: ignore[assignment]
            other_vector = tuple(other_evaluation["resource_vector"]) + (other_evaluation["predicted_loss_hartree"],)  # type: ignore[index]
            if all(left <= right for left, right in zip(other_vector, vector)) and any(
                left < right for left, right in zip(other_vector, vector)
            ):
                dominated = True
                break
        if not dominated:
            result.append(record)
    return sorted(
        result,
        key=lambda record: str(record["evaluation"]["constraint_semantic_id"]),  # type: ignore[index]
    )
