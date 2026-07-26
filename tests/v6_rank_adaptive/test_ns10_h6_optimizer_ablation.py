from dvg_obs_ceo.v6_rank_adaptive.ns10_h6_optimizer_ablation import (
    WORK_CAP,
)


def test_ns10_work_cap_is_complete_and_bounded():
    assert WORK_CAP == {
        "optimizer_starts": 6,
        "optimizer_iterations": 1200,
        "energy_evaluations": 1500,
        "gradient_vector_evaluations": 1500,
        "finite_difference_energy_evaluations": 60,
        "full_resource_recounts": 4,
    }
