import json
import math

import pytest

from dvg_obs_ceo.v4_lih import _strict_json_quality


def test_inapplicable_unbounded_held_out_policy_has_explicit_json_boundary() -> None:
    quality = {
        "passed": True,
        "checks": {},
        "policy": {"maximum_held_out_projected_residual": math.inf},
    }
    payload = _strict_json_quality(quality, held_out_required=False)
    assert payload["policy"]["maximum_held_out_projected_residual"] is None
    assert json.loads(json.dumps(payload, allow_nan=False))["passed"] is True
    with pytest.raises(ValueError, match="Out of range"):
        _strict_json_quality(quality, held_out_required=True)
