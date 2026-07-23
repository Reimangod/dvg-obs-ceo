from dvg_obs_ceo.v5_s8_lih_joint_audit import run_audit


def test_joint_static_audit():
    result = run_audit(recompute_quantum=False)
    assert result["passed"]
    assert result["checks"]["known_joint_endpoint_reproduced"]
    assert result["checks"]["postcommit_catalog_rebuilt"]
