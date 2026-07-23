"""Run the preregistered L2/L-infinity polishing-stop alignment probe."""

from __future__ import annotations

import json

from .baseline import ROOT
from .polishing import TrustNCGConfig
from .v5_conditional_polishing import ConditionalPolishingConfig
from .v5_s8_lih_polishing_probe import run


OUTPUT = ROOT / "artifacts/v5/s8/lih-polishing-l2-alignment-probe-v1.json"
RUNNER_VERSION = "v5-s8-lih-polishing-l2-alignment-probe-v1"


if __name__ == "__main__":
    result = run(
        OUTPUT,
        polishing_config=ConditionalPolishingConfig(
            polisher=TrustNCGConfig(gradient_l2_tolerance=1e-8)
        ),
        runner_version=RUNNER_VERSION,
    )
    print(json.dumps({
        "polishing_success": result["polishing"]["success"],
        "acceptance": None if result["acceptance"] is None else result["acceptance"]["accepted"],
    }, sort_keys=True))
