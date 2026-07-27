from __future__ import annotations

from dvg_obs_ceo.pra_path.s3_registry_audit import canonical_normals


def test_canonical_normal_registry_has_13_global_sign_classes() -> None:
    normals = canonical_normals()
    assert len(normals) == 13
    assert len(set(normals)) == 13
    for normal in normals:
        assert next(value for value in normal if value) == 1
        assert normal != (0, 0, 0)


def test_inequivalent_slot_patterns_are_not_collapsed() -> None:
    normals = set(canonical_normals())
    assert (1, 1, -1) in normals
    assert (1, -1, 1) in normals
    assert (1, -1, -1) in normals
