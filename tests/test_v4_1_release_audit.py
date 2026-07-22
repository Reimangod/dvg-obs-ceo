from __future__ import annotations

from dvg_obs_ceo.v4_1_release_audit import (
    _maximum_cardinality,
    _resource_delta,
    _resource_projection,
)


def test_resource_projection_and_reduction_sign() -> None:
    source = {
        "parameter_count": 9, "logical_block_count": 8, "cnot_count": 100,
        "cnot_depth": 30, "total_depth": 150, "structure_digest": "ignored",
    }
    final = {**source, "parameter_count": 7, "cnot_count": 80, "total_depth": 120}
    assert _resource_projection(source)["cnot_count"] == 100
    assert _resource_delta(source, final) == {
        "parameter_count": 2,
        "logical_block_count": 0,
        "cnot_count": 20,
        "cnot_depth": 0,
        "total_depth": 30,
    }


def test_maximum_search_cardinality_is_reported() -> None:
    search = {"records": [{"candidate_ids": ["a"]}, {"candidate_ids": ["a", "b", "c"]}]}
    assert _maximum_cardinality(search) == 3
    assert _maximum_cardinality({"records": []}) == 0
