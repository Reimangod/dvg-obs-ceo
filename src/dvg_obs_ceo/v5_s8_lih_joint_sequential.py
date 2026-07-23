"""LiH calibration run with joint global catalogs rebuilt sequentially."""

from __future__ import annotations

import json

from .baseline import ROOT
from .polishing import TrustNCGConfig
from .v5_conditional_polishing import ConditionalPolishingConfig
from .v5_s8_lih_width1 import run


OUTPUT = ROOT / "artifacts/v5/s8/lih-joint-sequential-v1"
RUNNER_VERSION = "v5-s8-lih-joint-sequential-v1"


if __name__ == "__main__":
    result = run(
        OUTPUT,
        runner_version=RUNNER_VERSION,
        enable_conditional_polishing=True,
        polishing_config=ConditionalPolishingConfig(
            polisher=TrustNCGConfig(gradient_l2_tolerance=1e-8)
        ),
        enable_joint_search=True,
    )
    print(json.dumps({
        "accepted_rounds": result["result"]["accepted_rounds"],
        "stop_reason": result["result"]["stop_reason"],
    }, sort_keys=True))
