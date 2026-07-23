import numpy as np
import pytest

from dvg_obs_ceo.block_ir import recover_dvg_blocks
from dvg_obs_ceo.resources import AnsatzStructure
from dvg_obs_ceo.v5_1_exact_fusion import (
    ExactFusionError,
    apply_exact_fusion,
    enumerate_exact_fusions,
    validate_exact_fusion_generators,
)
from test_block_ir import FakePool


def test_registered_ovp_commutes_across_disjoint_block_and_fuses_into_mvp():
    pool = FakePool()
    # Add a disjoint registered single-QE operator between the OVP and MVP.
    disjoint = type(pool.operators[0])(
        type(pool.get_q_op(0))({((1, "X"), (3, "Y")): 0.5j}),
        {1, 3},
        [3],
        [1],
    )
    pool.operators.append(disjoint)
    source = AnsatzStructure.create(
        [2, 4, 0, 1],
        [0.2, 0.4, 0.3, -0.1],
        [1, 2, 4],
    )
    blocks = recover_dvg_blocks(
        pool, source.indices, source.coefficients, source.cumulative_parameter_counts
    )
    candidates = enumerate_exact_fusions(pool, blocks)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.exact_signed_relation == (1, 1)
    target = apply_exact_fusion(pool, source, candidate)
    assert target.indices == (4, 0, 1)
    assert target.coefficients == pytest.approx((0.4, 0.5, 0.1))
    assert target.cumulative_parameter_counts == (0, 1, 3)


def test_overlapping_intervening_block_and_stale_numeric_context_fail_closed():
    pool = FakePool()
    source = AnsatzStructure.create([2, 0, 0, 1], [0.2, 0.4, 0.3, -0.1], [1, 2, 4])
    blocks = recover_dvg_blocks(
        pool, source.indices, source.coefficients, source.cumulative_parameter_counts
    )
    assert enumerate_exact_fusions(pool, blocks) == ()

    safe = AnsatzStructure.create([2, 0, 1], [0.2, 0.3, -0.1], [1, 3])
    candidate = enumerate_exact_fusions(
        pool,
        recover_dvg_blocks(
            pool, safe.indices, safe.coefficients, safe.cumulative_parameter_counts
        ),
    )[0]
    changed = AnsatzStructure.create([2, 0, 1], [0.25, 0.3, -0.1], [1, 3])
    with pytest.raises(ExactFusionError, match="stale"):
        apply_exact_fusion(pool, changed, candidate)


def test_generator_and_unitary_identity_is_independently_checked():
    pool = FakePool()
    source = AnsatzStructure.create([2, 0, 1], [0.2, 0.3, -0.1], [1, 3])
    candidate = enumerate_exact_fusions(
        pool,
        recover_dvg_blocks(
            pool, source.indices, source.coefficients, source.cumulative_parameter_counts
        ),
    )[0]
    first = np.diag([1j, -1j])
    second = np.diag([2j, -2j])
    validate_exact_fusion_generators(candidate, first + second, [first, second])
    with pytest.raises(ExactFusionError, match="identity failed"):
        validate_exact_fusion_generators(candidate, first - second, [first, second])

