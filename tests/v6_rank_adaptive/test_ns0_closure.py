import json

from dvg_obs_ceo.identity import sha256_hex
from dvg_obs_ceo.v6_rank_adaptive.ns0_closure import (
    DEFAULT_OUTPUT,
    S9_COMMIT,
    build_manifest,
)


def test_ns0_closes_old_queue_and_forbids_energy_until_resource_gate():
    manifest = build_manifest()
    assert manifest["s9_commit"] == S9_COMMIT
    assert manifest["closed_state"]["status"] == "STOPPED_NOT_CERTIFIED"
    assert manifest["closed_state"]["s10_authorized"] is False
    assert (
        manifest["closed_state"]["third_candidate_addition_allowed"]
        is False
    )
    assert "NS6" in manifest["new_namespace_contract"][
        "energy_evaluation_forbidden_until"
    ]


def test_committed_ns0_manifest_digest():
    manifest = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    digest = manifest.pop("closure_digest")
    assert digest == sha256_hex(manifest)
