import copy
import json

import pytest

from dvg_obs_ceo.v6_rank_adaptive import s0_preflight


def _manifest():
    return json.loads(s0_preflight.MANIFEST.read_text(encoding="utf-8"))


def _valid_observations(manifest):
    return {
        "parent_commit": manifest["parent"]["commit"],
        "tag_type": "tag",
        "submodule_commit": manifest["parent"]["submodule_commit"],
        "artifact_inventory_sha256": manifest["artifact_inventory"]["sha256"],
        "dependency_sha256": manifest["dependencies"],
        "python": manifest["environment"]["python"],
        "thread_environment": manifest["environment"]["thread_environment"],
        "clean_check_required": True,
        "working_tree_clean": True,
        "working_tree_status": "",
        "v5_release_passed": True,
    }


def test_s0_frozen_observations_pass():
    manifest = _manifest()
    result = s0_preflight.validate(
        manifest,
        _valid_observations(manifest),
    )
    assert result["passed"] is True
    assert all(result["checks"].values())
    assert result["paper_measurement_cost"] is None


@pytest.mark.parametrize(
    ("field", "bad_value", "failed_check"),
    [
        ("parent_commit", "0" * 40, "parent_commit"),
        ("tag_type", "commit", "annotated_tag"),
        ("submodule_commit", "1" * 40, "submodule_commit"),
        ("artifact_inventory_sha256", "2" * 64, "artifact_inventory"),
        ("python", "3.14.2", "python"),
        ("working_tree_clean", False, "clean_working_tree"),
        ("v5_release_passed", False, "v5_release_audit"),
    ],
)
def test_s0_preflight_fails_closed(field, bad_value, failed_check):
    manifest = _manifest()
    observations = _valid_observations(manifest)
    observations[field] = bad_value
    with pytest.raises(s0_preflight.V6S0PreflightError, match=failed_check):
        s0_preflight.validate(manifest, observations)


def test_s0_preflight_rejects_dependency_drift():
    manifest = _manifest()
    observations = _valid_observations(manifest)
    observations["dependency_sha256"] = copy.deepcopy(
        observations["dependency_sha256"]
    )
    observations["dependency_sha256"]["uv.lock"] = "3" * 64
    with pytest.raises(s0_preflight.V6S0PreflightError, match="dependencies"):
        s0_preflight.validate(manifest, observations)


def test_s0_preflight_rejects_unpinned_thread_configuration():
    manifest = _manifest()
    observations = _valid_observations(manifest)
    observations["thread_environment"] = dict(
        observations["thread_environment"]
    )
    observations["thread_environment"]["OMP_NUM_THREADS"] = None
    with pytest.raises(
        s0_preflight.V6S0PreflightError,
        match="thread_environment",
    ):
        s0_preflight.validate(manifest, observations)
