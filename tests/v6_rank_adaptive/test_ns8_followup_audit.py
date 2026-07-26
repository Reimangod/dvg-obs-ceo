from dvg_obs_ceo.v6_rank_adaptive.ns8_followup_audit import _dominates


def _point(identifier, energy, cnot, cnot_depth, depth, parameters):
    return {
        "point_id": identifier,
        "energy_loss_hartree": energy,
        "resources": {
            "cnot_count": cnot,
            "cnot_depth": cnot_depth,
            "total_depth": depth,
            "parameter_count": parameters,
        },
    }


def test_dominance_treats_numerical_energy_noise_as_equal():
    ns7 = _point("ns7", -8e-16, 156, 73, 266, 23)
    v5 = _point("v5", 4e-16, 145, 73, 246, 21)
    assert _dominates(v5, ns7)
    assert not _dominates(ns7, v5)


def test_energy_tradeoff_prevents_false_dominance():
    low_energy = _point("a", 0.0, 156, 73, 266, 23)
    low_resource = _point("b", 5e-5, 132, 60, 222, 18)
    assert not _dominates(low_energy, low_resource)
    assert not _dominates(low_resource, low_energy)
