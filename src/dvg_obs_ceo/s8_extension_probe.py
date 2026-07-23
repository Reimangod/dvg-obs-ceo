"""Outcome-disclosed S8.1 later-checkpoint calibration extension."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .s8_probe import run_cases


def run_probe(bundle: Path, *, resume: bool = False):
    return run_cases(
        bundle,
        cases=(
            "h4-1.5-iteration-8",
            "h4-1.5-iteration-12-or-convergence",
        ),
        artifact_kind="s8-1-h4-later-checkpoint-calibration",
        protocol_tag="dvg-obs-s8-1-later-checkpoint-protocol-v1",
        protocol_amendment_tag=None,
        claim_boundary=(
            "S8.1 is outcome-informed development calibration, not confirmatory evidence.",
            "Later checkpoints are separate from the primary first-accuracy regime.",
            "Failed candidates and optimizer failures are retained and counted.",
            "nfev/njev and statevector work are not paper-equivalent measurement cost.",
        ),
        allow_registered_checkpoint_failures=True,
        resume=resume,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    arguments = parser.parse_args()
    sys.argv[:] = [sys.argv[0]]
    result = run_probe(arguments.bundle, resume=arguments.resume)
    print(json.dumps({
        "bundle": str(arguments.bundle),
        "executed": result["executed_equivalence_classes"],
        "safe": result["primary_safe_candidates"],
        "failed": result["failed_candidate_evaluations"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
