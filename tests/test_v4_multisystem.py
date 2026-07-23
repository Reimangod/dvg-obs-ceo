from dataclasses import asdict

from dvg_obs_ceo.transaction import AcceptanceCriteria
from dvg_obs_ceo.v4_multisystem import (
    _acceptance_configuration_matches,
    canonical_bundle,
    protocol,
    registered_cases,
)


def test_registered_multisystem_cases_and_canonical_outputs() -> None:
    assert set(registered_cases()) == {"h6-1.5", "h6-3.0", "beh2-3.0"}
    assert canonical_bundle("h6-1.5").as_posix().endswith("artifacts/v4/multisystem/h6-1.5")


def test_frozen_acceptance_matches_runtime_gate() -> None:
    configuration = protocol()
    assert configuration["scientific_freeze"]["threshold_changes"] is False
    from dvg_obs_ceo.v4_multisystem import CONFIG_PATH
    import json

    frozen = json.loads(CONFIG_PATH.read_text())["configuration"]
    assert _acceptance_configuration_matches(frozen)
    assert asdict(AcceptanceCriteria(guard_logical_block_count=False))["cumulative_energy_budget_hartree"] == 1e-4


def test_protocol_adds_only_a_stricter_accuracy_retention_guard() -> None:
    manifest = protocol()
    guard = manifest["scientific_freeze"]["accuracy_retention_guard"]
    assert guard["molecule_independent_rule"]
    assert guard["never_relaxes_frozen_energy_budget"]
    assert not guard["used_for_screening_or_ranking"]
