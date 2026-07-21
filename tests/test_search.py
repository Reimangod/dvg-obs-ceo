import math

from dvg_obs_ceo.search import (
    SearchCandidate,
    SearchConfig,
    SearchEvaluation,
    deterministic_search,
    pareto_records,
)


def _evaluation(selected):
    loss = 0.04 * len(selected)
    resource = (10 - len(selected), 20 - 2 * len(selected))
    identity = "semantic:" + "+".join(selected)
    return SearchEvaluation("valid", identity, "numerical:" + identity, loss, resource)


def test_branch_bound_matches_exhaustive_eligible_set() -> None:
    candidates = [
        SearchCandidate("a", "g1"), SearchCandidate("b", "g1"),
        SearchCandidate("c", "g2"), SearchCandidate("d", "g3"),
    ]
    exhaustive = deterministic_search(
        candidates, _evaluation, SearchConfig(math.inf, 100, 100, 100)
    )
    bounded = deterministic_search(
        candidates, _evaluation, SearchConfig(0.08, 100, 100, 100)
    )
    expected = {
        record["evaluation"]["constraint_semantic_id"]
        for record in exhaustive["records"]
        if record["evaluation"]["predicted_loss_hartree"] <= 0.08
    }
    assert set(bounded["eligible_semantic_ids"]) == expected
    assert bounded["status"] == "surrogate-complete"
    evaluated = [tuple(record["candidate_ids"]) for record in exhaustive["records"]]
    assert len(evaluated) == len(set(evaluated))


def test_candidate_numerical_failure_does_not_prune_descendants() -> None:
    candidates = [SearchCandidate("a", "g1"), SearchCandidate("b", "g2")]

    def evaluator(selected):
        if selected == ("a",):
            return SearchEvaluation(
                "candidate-numerical-failure", None, None, None, reason="coverage"
            )
        return _evaluation(selected)

    result = deterministic_search(
        candidates, evaluator, SearchConfig(1.0, 100, 100, 100)
    )
    assert "semantic:a+b" in result["eligible_semantic_ids"]
    failed = next(record for record in result["records"] if record["candidate_ids"] == ["a"])
    assert not failed["prune_descendants"]


def test_semantic_infeasibility_prunes_descendants() -> None:
    candidates = [SearchCandidate("a", "g1"), SearchCandidate("b", "g2")]

    def evaluator(selected):
        if selected == ("a",):
            return SearchEvaluation(
                "semantic-infeasible", None, None, None, reason="exact conflict"
            )
        return _evaluation(selected)

    result = deterministic_search(
        candidates, evaluator, SearchConfig(1.0, 100, 100, 100)
    )
    assert not any(record["candidate_ids"] == ["a", "b"] for record in result["records"])
    assert result["counts"]["pruned_semantic_infeasible"] == 1


def test_deterministic_budget_truncation_replays_exactly() -> None:
    candidates = [SearchCandidate(str(index), f"g{index}") for index in range(5)]
    config = SearchConfig(1.0, 7, 100, 100)
    first = deterministic_search(candidates, _evaluation, config)
    second = deterministic_search(list(reversed(candidates)), _evaluation, config)
    assert first == second
    assert first["status"] == "budget-truncated"
    assert first["truncated_reason"] == "maximum-expanded-nodes"


def test_pareto_records_use_resources_and_predicted_loss() -> None:
    records = [
        {"eligible": True, "evaluation": {"constraint_semantic_id": "a", "resource_vector": [5, 8], "predicted_loss_hartree": 0.1}},
        {"eligible": True, "evaluation": {"constraint_semantic_id": "b", "resource_vector": [4, 7], "predicted_loss_hartree": 0.09}},
        {"eligible": True, "evaluation": {"constraint_semantic_id": "c", "resource_vector": [3, 9], "predicted_loss_hartree": 0.08}},
    ]
    assert [record["evaluation"]["constraint_semantic_id"] for record in pareto_records(records)] == ["b", "c"]
