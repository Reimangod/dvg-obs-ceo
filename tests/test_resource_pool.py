import pytest

from dvg_obs_ceo.resource_pool import ResourceOnlyDVGPool


def test_resource_only_pool_known_sizes_and_parent_ranges() -> None:
    pool4 = ResourceOnlyDVGPool(4)
    assert pool4.size == 6
    assert (pool4.parent_range.start, pool4.parent_range.stop) == (2, 4)
    pool10 = ResourceOnlyDVGPool(10)
    assert pool10.size == 510
    assert (pool10.parent_range.start, pool10.parent_range.stop) == (20, 250)
    pool12 = ResourceOnlyDVGPool(12)
    assert pool12.size > 1182


def test_resource_only_pool_matches_pinned_upstream_metadata_and_generators() -> None:
    try:
        from dvg_obs_ceo.baseline import _load_upstream

        _, dvg_ceo, _, _ = _load_upstream()
        official = dvg_ceo(n=10)
    except (ImportError, ModuleNotFoundError):
        pytest.skip("baseline scientific dependencies are not installed")
    lightweight = ResourceOnlyDVGPool(10)
    assert lightweight.size == official.size
    assert lightweight.parent_range == official.parent_range
    for index, (left, right) in enumerate(zip(lightweight.operators, official.operators)):
        assert left.source_orbs == right.source_orbs
        assert left.target_orbs == right.target_orbs
        assert left.ceo_type == right.ceo_type
        assert left.parents == right.parents
        assert left.qubits == right.qubits
    sampled = [0, 19, 20, 100, 249, 250, 300, 400, 509]
    for index in sampled:
        assert lightweight.get_q_op(index) == official.get_q_op(index)
