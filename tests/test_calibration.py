import numpy as np
import pytest

from dvg_obs_ceo.block_ir import enumerate_candidates, recover_dvg_blocks
from dvg_obs_ceo.calibration import (
    calibration_metrics,
    embed_block_transformation,
    least_squares_native_coordinates,
    predictor_values,
)
from test_block_ir import FakePool


def test_local_candidate_embedding_preserves_order_and_feasible_map() -> None:
    pool = FakePool()
    blocks = recover_dvg_blocks(pool, [2, 0, 1, 3], [0.2, 0.3, -0.1, 0.4], [3, 4])
    block = blocks[1]
    candidate = next(
        value
        for value in enumerate_candidates(pool, [block])
        if value.kind == "mvp-to-ovp-sum"
    )
    embedded = embed_block_transformation(4, block, candidate)
    ir = embedded.transformation
    assert ir.jacobian.shape == (4, 3)
    coordinates = np.array([0.2, 0.7, 0.4])
    source = ir.offset + ir.jacobian @ coordinates
    np.testing.assert_allclose(source[[0, 3]], [0.2, 0.4])
    np.testing.assert_allclose(ir.constraint_matrix @ source, ir.constraint_rhs)
    assert coordinates[embedded.local_target_slice] == pytest.approx([0.7])


def test_projection_off_is_closest_native_point() -> None:
    pool = FakePool()
    block = recover_dvg_blocks(pool, [0, 1], [0.3, -0.1], [2])[0]
    candidate = next(
        value
        for value in enumerate_candidates(pool, [block])
        if value.kind == "mvp-to-ovp-sum"
    )
    ir = embed_block_transformation(2, block, candidate).transformation
    coordinates = least_squares_native_coordinates([0.3, -0.1], ir)
    np.testing.assert_allclose(coordinates, np.linalg.lstsq(ir.jacobian, [0.3, -0.1], rcond=None)[0])


def test_predictors_are_explicit_about_units_and_missing_single_coordinate() -> None:
    pool = FakePool()
    block = recover_dvg_blocks(pool, [0, 1], [0.3, -0.1], [2])[0]
    relation = next(
        value
        for value in enumerate_candidates(pool, [block])
        if value.kind == "mvp-to-ovp-sum"
    )
    ir = embed_block_transformation(2, block, relation).transformation
    values = predictor_values([0.3, -0.1], [0.0, 0.0], np.eye(2), ir, exact_hessian=np.eye(2))
    assert values["magnitude"] >= 0.0
    assert values["single_coordinate_obs"] is None
    assert values["general_constraint_obs"] == pytest.approx(values["exact_hessian_oracle"])


def test_metrics_do_not_invent_classification_threshold_for_heuristics() -> None:
    rows = [
        {"predictors": {"magnitude": 0.1, "general_constraint_obs": 5e-5}, "actual_change_hartree": 8e-5, "safe": True},
        {"predictors": {"magnitude": 0.2, "general_constraint_obs": 2e-4}, "actual_change_hartree": 3e-4, "safe": False},
    ]
    heuristic = calibration_metrics(rows, "magnitude")
    assert not heuristic["classification"]["applicable"]
    physical = calibration_metrics(rows, "general_constraint_obs")
    assert physical["classification"]["true_positive"] == 1
    assert physical["classification"]["true_negative"] == 1
