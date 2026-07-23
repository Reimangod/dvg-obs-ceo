"""One-round extension of the audited LiH energy-aware width-two calibration."""

from __future__ import annotations

import json

from .baseline import ROOT
from .v5_s8_lih_multitrajectory import run


RUNNER_VERSION = "v5-s8-lih-energy-aware-width2-round3-v1"
OUTPUT = ROOT / "artifacts/v5/s8/lih-energy-aware-width2-round3-v1"


if __name__ == "__main__":
    result = run(
        OUTPUT,
        runner_version=RUNNER_VERSION,
        beam_dominance="resources-plus-energy",
        artifact_kind="v5-s8-lih-energy-aware-width2-round3",
        maximum_rounds=3,
        maximum_exact_attempts=6,
    )
    print(
        json.dumps(
            {
                "winner_resources": result["result"]["winner_resources"],
                "winner_energy_increase": result["result"][
                    "winner_cumulative_energy_increase_hartree"
                ],
                "exact_attempts": result["result"]["exact_attempts"],
                "stop_reason": result["result"]["stop_reason"],
                "aggregate_work": result["result"]["aggregate_work"],
            },
            sort_keys=True,
        )
    )
