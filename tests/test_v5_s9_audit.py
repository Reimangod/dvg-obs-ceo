import pytest

from dvg_obs_ceo.v5_s9_audit import run_audit


@pytest.mark.parametrize(
    ("case_id", "strict_success"),
    (
        ("h6-1.5", False),
        ("h6-3.0", True),
        ("beh2-3.0", False),
    ),
)
def test_s9_nonquantum_audits_pass(case_id, strict_success):
    audit = run_audit(case_id, recompute_quantum=False)
    assert audit["passed"] is True
    assert audit["strict_primary_success"] is strict_success
