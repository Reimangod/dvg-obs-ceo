import numpy as np

from dvg_obs_ceo.resources import AnsatzStructure
from dvg_obs_ceo.transaction import AcceptanceCriteria
from dvg_obs_ceo.v6_rank_adaptive.s9_certification import (
    _choose_path,
    _prediction_diagnostics,
    _target_structure,
)


def test_target_structure_removes_exactly_the_frozen_coordinate():
    source = AnsatzStructure.create(
        [10, 11, 12, 13],
        [0.1, 0.2, 0.3, 0.4],
        [1, 3, 4],
    )
    candidate = {
        "source_ansatz_positions": [1, 2, 3],
        "omitted_source_slot": 1,
    }
    target, omitted = _target_structure(
        source, candidate, [0.1, 0.2, 0.4]
    )
    assert omitted == 2
    assert target.indices == (10, 11, 13)
    assert target.cumulative_parameter_counts == (1, 2, 3)


def test_fallback_selection_is_preregistered_stationarity_then_energy():
    primary = {
        "gradient_infinity": 1e-7,
        "independent_energy_hartree": -1.0,
    }
    fallback = {
        "gradient_infinity": 1e-9,
        "independent_energy_hartree": -0.999,
    }
    assert _choose_path(primary, fallback)[0] == "fallback"
    assert _choose_path(primary, None)[0] == "primary"


def test_prediction_diagnostic_does_not_recalibrate_queue():
    value = _prediction_diagnostics(1e-6, 3e-6)
    assert value["direction"] == "underestimate"
    assert np.isclose(value["absolute_error_hartree"], 2e-6)
    assert value["used_to_reorder_current_queue"] is False
    assert value["used_to_recalibrate_current_queue"] is False


def test_s9_resource_policies_are_explicit_and_distinct():
    exploratory = AcceptanceCriteria(
        resource_policy="exploratory-depth-parameter-v1"
    )
    primary = AcceptanceCriteria(
        resource_policy="circuit-primary-v1"
    )
    assert exploratory.resource_policy != primary.resource_policy
    assert np.isclose(
        exploratory.maximum_kkt_residual,
        primary.maximum_kkt_residual,
    )
