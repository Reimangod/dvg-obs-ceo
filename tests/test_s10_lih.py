from dataclasses import asdict
import json
from pathlib import Path

import pytest

from dvg_obs_ceo.s10_lih import (
    PROTOCOL_ID,
    SELECTOR_DIGEST,
    _work_for_paths,
    validate_summary,
)
from dvg_obs_ceo.telemetry import WorkCounters


def optimizer_path(*, nfev=4, njev=3, nit=2):
    return {
        "optimizer": {
            "function_evaluations": nfev,
            "gradient_vector_evaluations": njev,
            "iterations": nit,
        }
    }


def test_selected_candidate_work_counts_primary_and_fallback() -> None:
    base = WorkCounters(
        energy_evaluations=10,
        gradient_component_evaluations=20,
        statevector_kernels=1,
        screening_rounds=1,
    )
    result = _work_for_paths(
        base,
        [optimizer_path(nfev=4, njev=3, nit=2), optimizer_path(nfev=5, njev=2, nit=1)],
        [14, 14],
    )
    assert result.energy_evaluations == 21  # base + both nfev + two independent checks
    assert result.gradient_vector_evaluations == 7
    assert result.gradient_component_evaluations == 20 + 4 * 14 + 3 * 14
    assert result.optimizer_iterations == 3
    assert result.statevector_kernels == 6  # source checkpoint + 2 per path + final runtime
    assert result.screening_rounds == 1
    assert result.compression_attempts == 1


def test_s10_protocol_forbids_fci_in_runtime_acceptance() -> None:
    protocol = json.loads(
        Path("manifests/s10-lih-paired-protocol-v1.2.json").read_text(
            encoding="utf-8"
        )
    )
    assert protocol["protocol_id"] == PROTOCOL_ID
    assert protocol["selector"]["digest"] == SELECTOR_DIGEST
    assert protocol["acceptance"]["fci_is_pruning_selector_or_acceptance_input"] is False
    assert protocol["work_accounting"]["paper_measurement_cost"] is None
    assert set(protocol["numerical_environment_preflight"].values()) >= {"1", True}


def test_s10_summary_schema_accepts_no_selection() -> None:
    resources = {"snapshot": {"cnot_count": 107}}
    summary = {
        "schema_version": "1.0.0",
        "artifact_kind": "s10-lih-first-accuracy-paired-comparison",
        "run_id": "synthetic-no-selection",
        "protocol_id": PROTOCOL_ID,
        "selector_digest": SELECTOR_DIGEST,
        "checkpoint": {"adapt_iteration": 5, "energy_hartree": -7.7, "parameter_count": 15, "resources": resources},
        "clone_audit": {
            "exact": True,
            "source_snapshot_digest": "a" * 64,
            "no_pruning_snapshot_digest": "a" * 64,
            "v2_snapshot_digest": "a" * 64,
        },
        "selection": {"candidate_count": 3, "eligible_count": 0, "chosen_candidate_id": None, "decision": {}},
        "no_pruning": {"energy_hartree": -7.7, "resources": resources},
        "dvg_obs_ceo": {"status": "no-selection", "accepted": False, "energy_hartree": -7.7, "resources": resources},
        "work": {},
        "offline_evaluation": {"used_by_runtime_selector_or_acceptance": False},
        "paper_measurement_cost": None,
        "claim_boundary": ["a", "b", "c", "d"],
    }
    validate_summary(summary)
    broken = dict(summary)
    broken["checkpoint"] = dict(summary["checkpoint"], adapt_iteration=4)
    with pytest.raises(Exception, match="schema"):
        validate_summary(broken)
