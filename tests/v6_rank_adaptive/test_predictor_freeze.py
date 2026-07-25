import json
from pathlib import Path

import numpy as np
import pytest

from dvg_obs_ceo.identity import sha256_hex
from dvg_obs_ceo.quadratic import QuadraticModel
from dvg_obs_ceo.v5_pareto import V5ParetoError, candidate_from_record
from dvg_obs_ceo.telemetry import ResourceSnapshot
from dvg_obs_ceo.v6_rank_adaptive.predictor_freeze import (
    DEFAULT_OUTPUT,
    PredictorFreezeError,
    S8Config,
    _constraint_parameterization,
    _extract_recycled_model,
    build_prediction_records,
    build_pulled_back_model,
    select_frozen_candidates,
)


class PoisonedPrimary(dict):
    def __getitem__(self, key):
        if key in {"energy_hartree", "fci_energy_hartree"}:
            raise AssertionError("forbidden outcome field was accessed")
        return super().__getitem__(key)


def test_model_extractor_reads_only_registered_predictor_fields():
    primary = PoisonedPrimary(
        coordinates=[0.2, -0.1],
        gradient=[0.03, -0.04],
        final_inverse_hessian=[[1.0, 0.0], [0.0, 2.0]],
        energy_hartree=-5.0,
        fci_energy_hartree=-6.0,
    )
    model = _extract_recycled_model(primary)
    assert isinstance(model, QuadraticModel)
    assert np.array_equal(model.gradient, [0.03, -0.04])


def test_nonzero_gradient_pulled_back_constraint_is_analytic():
    row = np.asarray([1.0, -1.0, 0.0])
    transform = _constraint_parameterization(row, candidate_id="candidate")
    model = QuadraticModel.create(
        [0.2, -0.1, 0.3],
        [0.03, -0.08, 0.02],
        np.linalg.inv(
            np.asarray(
                [[5.0, 1.0, 0.2], [1.0, 4.0, 0.5], [0.2, 0.5, 3.0]]
            )
        ),
    )
    from dvg_obs_ceo.quadratic import predict_constrained_optimum

    result = predict_constrained_optimum(model, transform)
    assert result.constraint_residual_infinity <= 1e-10
    assert np.isfinite(result.predicted_change_from_current)


def test_predictor_call_cap_fails_before_partial_screening():
    from dvg_obs_ceo.baseline import _load_upstream

    _, DVG_CEO, _, _ = _load_upstream()
    s6 = json.loads(
        Path("artifacts/v6/s6/exact-rewrite-trace-v1.json").read_text(
            encoding="utf-8"
        )
    )
    s7 = json.loads(
        Path("artifacts/v6/s7/rank-candidate-catalog-v1.json").read_text(
            encoding="utf-8"
        )
    )
    legacy = json.loads(
        Path(
            "artifacts/v4.1/multisystem/h6-1.5/summary.json"
        ).read_text(encoding="utf-8")
    )
    pulled = build_pulled_back_model(
        DVG_CEO(n=12),
        s6,
        legacy["attempts"][0]["primary"],
    )
    with pytest.raises(PredictorFreezeError, match="cap"):
        build_prediction_records(
            pulled,
            s7,
            S8Config(maximum_predictor_calls=2),
        )


def test_screening_record_rejects_nested_actual_and_fci_poison():
    base = {
        "candidate_ids": ["candidate-v6:test"],
        "constraint_semantic_id": "constraint-semantic-v6:" + "0" * 64,
        "constraint_numerical_id": "constraint-numerical-v6:" + "1" * 64,
        "predicted_loss_hartree": 1e-6,
        "resources": {
            "cnot_count": 10,
            "cnot_depth": 5,
            "total_depth": 20,
            "parameter_count": 3,
            "logical_block_count": 2,
            "counter_version": "counter",
            "structure_digest": "2" * 64,
        },
        "diagnostics": {
            "quality_gate_passed": True,
            "uncertainty_margin_hartree": 0.0,
            "quality_stratum": "boundary",
            "refinement_required": True,
            "evidence_digest": "3" * 64,
        },
        "full_resource_recount_succeeded": True,
        "semantics_validated": True,
    }
    for poisoned in (
        {**base, "actual_energy_hartree": -1.0},
        {
            **base,
            "diagnostics": {
                **base["diagnostics"],
                "nested_fci_reference": -1.1,
            },
        },
    ):
        with pytest.raises(V5ParetoError, match="forbidden"):
            candidate_from_record(poisoned)


def test_committed_s8_freeze_is_self_consistent_and_outcome_blind():
    report = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    digest = report.pop("report_digest")
    assert digest == sha256_hex(report)
    assert report["frozen_candidate_count"] == 1
    assert report["information_firewall"] == {
        "actual_candidate_energy_available": False,
        "candidate_outcomes_can_change_current_freeze": False,
        "fci_reference_available": False,
        "legacy_energy_field_read": False,
        "poisoning_contract": (
            "Only coordinates, gradient, and final_inverse_hessian are read "
            "from the legacy primary record; screening records recursively "
            "reject actual and FCI fields."
        ),
    }
    assert report["work"]["energy_evaluations"] == 0
    assert report["paper_measurement_cost"] is None
    predictions = report["prediction_records"]
    assert len(predictions) == 3
    assert all(
        row["actual_or_fci_energy_used"] is False for row in predictions
    )
    assert (
        report["model_adapter"]["rejected_direct_transport_diagnostic"][
            "ranking_influence"
        ]
        is False
    )
    risk = [
        candidate_from_record(item["risk_record"])
        for item in predictions
    ]
    s7 = json.loads(
        Path("artifacts/v6/s7/rank-candidate-catalog-v1.json").read_text(
            encoding="utf-8"
        )
    )
    source_value = s7["source_recount"]
    source = ResourceSnapshot(
        cnot_count=source_value["cnot_count"],
        cnot_depth=source_value["cnot_depth"],
        total_depth=source_value["total_depth"],
        parameter_count=source_value["parameter_count"],
        logical_block_count=source_value["logical_block_count"],
        counter_version=source_value["counter_version"],
        structure_digest=source_value["circuit_qasm_digest"],
    )
    replay = select_frozen_candidates(
        tuple(reversed(risk)),
        source,
        S8Config(**report["config"]),
    )
    assert replay["freeze_digest"] == report["freeze_digest"]
    assert replay["frozen_candidate_ids"] == report["frozen_candidate_ids"]
