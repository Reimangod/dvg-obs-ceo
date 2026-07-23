import json
from pathlib import Path

import pytest

from dvg_obs_ceo.v5_protocol import DEFAULT_MANIFEST, V5ProtocolError, audit_manifest


def _tampered_manifest(tmp_path: Path, mutator) -> Path:
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    mutator(manifest)
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_v5_parent_release_and_protocol_are_frozen() -> None:
    result = audit_manifest()
    assert result["passed"]
    assert len(result["checks"]) >= 30
    assert result["claim_boundary"].startswith("Preregistration")


def test_v5_rejects_parent_release_drift(tmp_path: Path) -> None:
    path = _tampered_manifest(
        tmp_path,
        lambda manifest: manifest["parent"].__setitem__("release_bundle_digest", "0" * 64),
    )
    with pytest.raises(V5ProtocolError, match="release_bundle_digest"):
        audit_manifest(path)


def test_v5_rejects_checkpoint_drift(tmp_path: Path) -> None:
    path = _tampered_manifest(
        tmp_path,
        lambda manifest: manifest["source_checkpoints"][0].__setitem__("sha256", "0" * 64),
    )
    with pytest.raises(V5ProtocolError, match="checkpoint_sha256:lih-3.0"):
        audit_manifest(path)


def test_v5_rejects_fci_ranking_leak(tmp_path: Path) -> None:
    path = _tampered_manifest(
        tmp_path,
        lambda manifest: manifest["scientific_invariants"].__setitem__(
            "fci_or_actual_candidate_energy_used_in_screening_or_ranking", True
        ),
    )
    with pytest.raises(V5ProtocolError, match="scientific_invariants"):
        audit_manifest(path)


def test_v5_rejects_claiming_observed_case_as_confirmatory(tmp_path: Path) -> None:
    path = _tampered_manifest(
        tmp_path,
        lambda manifest: manifest.__setitem__("confirmatory_cases", ["h6-1.5"]),
    )
    with pytest.raises(V5ProtocolError, match="no_confirmatory_case_predeclared"):
        audit_manifest(path)


def test_v5_rejects_relaxed_stationarity(tmp_path: Path) -> None:
    path = _tampered_manifest(
        tmp_path,
        lambda manifest: manifest["scientific_invariants"].__setitem__(
            "target_gradient_infinity_norm_max", 5e-8
        ),
    )
    with pytest.raises(V5ProtocolError, match="scientific_invariants"):
        audit_manifest(path)


def test_v5_rejects_parameter_only_resource_claim(tmp_path: Path) -> None:
    path = _tampered_manifest(
        tmp_path,
        lambda manifest: manifest["scientific_invariants"].__setitem__(
            "parameter_removal_requires_physical_circuit_removal", False
        ),
    )
    with pytest.raises(V5ProtocolError, match="scientific_invariants"):
        audit_manifest(path)


def test_v5_rejects_out_of_order_feature_activation(tmp_path: Path) -> None:
    def reverse_features(manifest: dict) -> None:
        manifest["core_feature_order"].reverse()

    path = _tampered_manifest(tmp_path, reverse_features)
    with pytest.raises(V5ProtocolError, match="core_order"):
        audit_manifest(path)
