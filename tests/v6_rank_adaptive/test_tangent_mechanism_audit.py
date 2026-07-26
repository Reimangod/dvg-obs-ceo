from __future__ import annotations

import numpy as np
import struct

from dvg_obs_ceo.v6_rank_adaptive.tangent_mechanism_audit import (
    _float64_hex,
    _stage_authorization,
)


def test_float64_hex_round_trip_matches_project_convention() -> None:
    values = np.asarray([-1.25, 0.0, 3.5], dtype=np.float64)
    encoded = [struct.pack(">d", float(value)).hex() for value in values]
    assert np.array_equal(_float64_hex(encoded), values)


def test_t2_never_authorizes_performance_stages_directly() -> None:
    assert _stage_authorization("GO_DEVELOPMENT_MECHANISM_SEPARATED") == {
        "t3_t4": True,
        "t5_t6_performance": False,
    }
    assert _stage_authorization("NO_GO_MECHANISM_NOT_SEPARATED") == {
        "t3_t4": False,
        "t5_t6_performance": False,
    }
