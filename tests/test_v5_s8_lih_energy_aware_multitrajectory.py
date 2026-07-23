import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_energy_aware_manifest_binds_negative_result_and_freezes_policy():
    manifest = json.loads(
        (
            ROOT / "manifests/v5-s8-lih-energy-aware-width2-v1.json"
        ).read_text(encoding="utf-8")
    )
    entry = manifest["entry_gate"]
    for path_key, digest_key in (
        ("resource_only_result_path", "resource_only_result_sha256"),
        ("resource_only_audit_path", "resource_only_audit_sha256"),
    ):
        assert hashlib.sha256((ROOT / entry[path_key]).read_bytes()).hexdigest() == (
            entry[digest_key]
        )
    algorithm = manifest["algorithm"]
    assert algorithm["beam_dominance"] == "resources-plus-energy"
    assert algorithm["winner_rule_changed"] is False
    assert algorithm["acceptance_gates_changed"] is False
    assert algorithm["threshold_relaxation"] is False


def test_accounting_corrected_manifest_binds_incomplete_result_and_finding():
    manifest = json.loads(
        (
            ROOT / "manifests/v5-s8-lih-energy-aware-width2-v2.json"
        ).read_text(encoding="utf-8")
    )
    entry = manifest["entry_gate"]
    for path_key, digest_key in (
        ("incomplete_result_path", "incomplete_result_sha256"),
        ("accounting_finding_path", "accounting_finding_sha256"),
    ):
        assert hashlib.sha256((ROOT / entry[path_key]).read_bytes()).hexdigest() == (
            entry[digest_key]
        )
    assert manifest["protocol"]["scientific_search_configuration_changed"] is False
    assert manifest["accounting_correction"][
        "zero_candidate_terminal_catalog_charged"
    ] is True
