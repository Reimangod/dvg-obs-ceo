import json

import pytest

from dvg_obs_ceo import artifact_io
from dvg_obs_ceo.artifact_io import (
    ArtifactPublicationError,
    atomic_publish_json_directory,
    atomic_write_new_json,
)


def test_atomic_json_file_is_complete_and_immutable(tmp_path):
    target = tmp_path / "result.json"
    atomic_write_new_json(target, {"value": 1})
    assert json.loads(target.read_text()) == {"value": 1}
    with pytest.raises(ArtifactPublicationError, match="overwrite"):
        atomic_write_new_json(target, {"value": 2})
    assert json.loads(target.read_text()) == {"value": 1}


def test_atomic_directory_publication_is_complete_and_immutable(tmp_path):
    target = tmp_path / "run"
    atomic_publish_json_directory(target, {"passed": True})
    assert json.loads((target / "summary.json").read_text())["passed"] is True
    with pytest.raises(ArtifactPublicationError, match="overwrite"):
        atomic_publish_json_directory(target, {"passed": False})


def test_failed_atomic_file_promotion_leaves_no_partial_canonical_file(
    tmp_path, monkeypatch
):
    target = tmp_path / "result.json"

    def fail_replace(source, destination):
        raise OSError("injected promotion failure")

    monkeypatch.setattr(artifact_io.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected"):
        atomic_write_new_json(target, {"value": 1})
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_failed_atomic_directory_promotion_leaves_no_partial_bundle(
    tmp_path, monkeypatch
):
    target = tmp_path / "run"

    def fail_replace(source, destination):
        raise OSError("injected promotion failure")

    monkeypatch.setattr(artifact_io.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected"):
        atomic_publish_json_directory(target, {"value": 1})
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []
