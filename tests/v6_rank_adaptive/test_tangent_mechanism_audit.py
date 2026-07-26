from __future__ import annotations

import numpy as np
import struct

from dvg_obs_ceo.v6_rank_adaptive.tangent_mechanism_audit import _float64_hex


def test_float64_hex_round_trip_matches_project_convention() -> None:
    values = np.asarray([-1.25, 0.0, 3.5], dtype=np.float64)
    encoded = [struct.pack(">d", float(value)).hex() for value in values]
    assert np.array_equal(_float64_hex(encoded), values)
