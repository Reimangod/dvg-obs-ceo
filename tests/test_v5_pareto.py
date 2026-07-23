from dataclasses import asdict

import pytest

from dvg_obs_ceo.identity import sha256_hex
from dvg_obs_ceo.telemetry import ResourceSnapshot
from dvg_obs_ceo.v5_pareto import (
    RiskAwareCandidate,
    RiskDiagnostics,
    V5ParetoError,
    candidate_from_record,
    candidate_to_record,
    select_risk_aware_pareto,
)
from dvg_obs_ceo.v5_pareto_audit import run_audit


def resources(values, label):
    return ResourceSnapshot(*values, "test-counter-v1", sha256_hex({"label": label, "values": values}))


def candidate(label, values, loss, margin=0.0, *, quality=True):
    return RiskAwareCandidate(
        (f"candidate-v5:{sha256_hex(label)}",),
        f"constraint-semantic-v1:{sha256_hex({'semantic': label})}",
        f"constraint-numerical-v1:{sha256_hex({'numerical': label})}",
        loss,
        resources(values, label),
        RiskDiagnostics(quality, margin, "good" if quality else "poor", not quality, sha256_hex(label)),
    )


def test_dominance_and_separate_axes() -> None:
    source = resources((100, 50, 160, 12, 10), "source")
    dominating = candidate("dominating", (70, 40, 120, 8, 8), 1e-5)
    dominated = candidate("dominated", (80, 45, 130, 9, 9), 2e-5)
    result = select_risk_aware_pareto((dominated, dominating), source)
    assert result["pareto_semantic_ids"] == [dominating.constraint_semantic_id]
    assert result["unique_attempt_semantic_ids"] == [dominating.constraint_semantic_id]
    assert "scalar_score" not in result


def test_risk_margin_changes_dominance_without_changing_raw_prediction() -> None:
    source = resources((100, 50, 160, 12, 10), "source")
    safer = candidate("safer", (70, 40, 120, 8, 8), 2e-5, 0.0)
    uncertain = candidate("uncertain", (70, 40, 120, 8, 8), 1e-5, 3e-5)
    result = select_risk_aware_pareto((uncertain, safer), source)
    assert result["unique_attempt_semantic_ids"] == [safer.constraint_semantic_id]


def test_information_firewall_is_recursive_and_unknown_fields_fail_closed() -> None:
    item = candidate("safe", (70, 40, 120, 8, 8), 1e-5)
    record = candidate_to_record(item)
    assert candidate_from_record(record) == item
    with pytest.raises(V5ParetoError, match="forbidden screening field"):
        candidate_from_record({**record, "metadata": {"fci_energy": -1.0}})
    with pytest.raises(V5ParetoError, match="unregistered candidate fields"):
        candidate_from_record({**record, "harmless_but_unregistered": 1})


def test_one_structure_digest_cannot_have_conflicting_counts() -> None:
    source = resources((100, 50, 160, 12, 10), "source")
    first = candidate("first", (70, 40, 120, 8, 8), 1e-5)
    second = candidate("second", (71, 40, 120, 8, 8), 1e-5)
    second = RiskAwareCandidate(
        second.candidate_ids,
        second.constraint_semantic_id,
        second.constraint_numerical_id,
        second.predicted_loss_hartree,
        ResourceSnapshot(**{**asdict(second.resources), "structure_digest": first.resources.structure_digest}),
        second.diagnostics,
    )
    with pytest.raises(V5ParetoError, match="conflicting resource counts"):
        select_risk_aware_pareto((first, second), source)


def test_counter_version_and_boolean_strings_fail_closed() -> None:
    source = resources((100, 50, 160, 12, 10), "source")
    item = candidate("safe", (70, 40, 120, 8, 8), 1e-5)
    mismatched = RiskAwareCandidate(
        item.candidate_ids,
        item.constraint_semantic_id,
        item.constraint_numerical_id,
        item.predicted_loss_hartree,
        ResourceSnapshot(**{**asdict(item.resources), "counter_version": "different-counter-v1"}),
        item.diagnostics,
    )
    with pytest.raises(V5ParetoError, match="counter versions differ"):
        select_risk_aware_pareto((mismatched,), source)
    with pytest.raises(V5ParetoError, match="must be booleans"):
        candidate_from_record({**candidate_to_record(item), "semantics_validated": "false"})


def test_s4_independent_audit() -> None:
    result = run_audit()
    assert result["passed"]
    assert all(result["checks"].values())
