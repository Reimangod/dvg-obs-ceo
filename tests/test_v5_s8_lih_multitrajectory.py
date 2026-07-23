import hashlib
import json
from dataclasses import replace
from pathlib import Path

from dvg_obs_ceo.v5_ledger import V5WorkCounters
from dvg_obs_ceo.v5_s8_lih_multitrajectory import _sum_work, _work_delta


ROOT = Path(__file__).resolve().parents[1]


def test_branch_work_delta_counts_one_exact_attempt():
    before = V5WorkCounters(full_resource_recounts=3, expanded_search_states=10)
    after = replace(
        before,
        energy_evaluations=5,
        exact_vqe_attempts=4,
        full_resource_recounts=5,
    )
    delta = _work_delta(after, before)
    assert delta["energy_evaluations"] == 5
    assert delta["full_resource_recounts"] == 2
    assert delta["exact_vqe_attempts"] == 1


def test_work_sum_retains_zero_attempt_terminal_catalog():
    exact = {"energy_evaluations": 7, "exact_vqe_attempts": 2}
    productive_catalog = {"full_resource_recounts": 5, "expanded_search_states": 20}
    terminal_catalog = {"full_resource_recounts": 1, "expanded_search_states": 4}
    assert _sum_work(exact, productive_catalog, terminal_catalog) == {
        "energy_evaluations": 7,
        "exact_vqe_attempts": 2,
        "expanded_search_states": 24,
        "full_resource_recounts": 6,
    }


def test_width_two_manifest_binds_inputs_and_budgets():
    manifest = json.loads(
        (ROOT / "manifests/v5-s8-lih-width2-multitrajectory-v1.json").read_text(
            encoding="utf-8"
        )
    )
    for path_key, digest_key in (
        ("joint_result_path", "joint_result_sha256"),
        ("joint_audit_path", "joint_audit_sha256"),
    ):
        source = ROOT / manifest["entry_gate"][path_key]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == (
            manifest["entry_gate"][digest_key]
        )
    algorithm = manifest["algorithm"]
    assert algorithm["width"] == 2
    assert algorithm["top_k_per_parent"] == 2
    assert algorithm["maximum_rounds"] == 2
    assert algorithm["maximum_exact_attempts"] == 4
    assert algorithm["source_relative_energy_budget_hartree"] == 1e-4
