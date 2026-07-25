"""Execute the frozen V5-S9 protocol on existing multisystem checkpoints."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from .baseline import ROOT
from .multisystem_checkpoint import _algorithm
from .v5_s8_lih_multitrajectory import run


MANIFEST = ROOT / "manifests/v5-s9-frozen-development-v1.json"
CODE_TAG = "dvg-obs-v5-s9-frozen-code-v1"
OUTPUT_ROOT = ROOT / "artifacts/v5/s9"


class V5S9FrozenError(RuntimeError):
    pass


def _git(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *arguments], text=True
    ).strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _case(case_id: str) -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    try:
        return next(item for item in manifest["cases"] if item["case_id"] == case_id)
    except StopIteration as error:
        raise V5S9FrozenError(f"unregistered S9 case: {case_id}") from error


def verify_freeze(case_id: str) -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    case = _case(case_id)
    head = _git("rev-parse", "HEAD")
    tag_commit = _git("rev-parse", f"{CODE_TAG}^{{}}")
    if subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", tag_commit, head],
        check=False,
    ).returncode != 0:
        raise V5S9FrozenError("S9 code tag is not an ancestor")
    changed = _git("diff", "--name-only", tag_commit, head).splitlines()
    scientific = [
        path for path in changed
        if path.startswith(("src/", "tests/", "manifests/", "vendor/"))
        or path in ("pyproject.toml", "uv.lock")
    ]
    if scientific:
        raise V5S9FrozenError(
            "scientific files changed after S9 freeze: " + ", ".join(scientific)
        )
    checkpoint = ROOT / case["checkpoint_path"]
    checks = {
        "manifest_s8_hash": (
            _sha256(ROOT / manifest["s8_freeze"]["manifest_path"])
            == manifest["s8_freeze"]["manifest_sha256"]
        ),
        "checkpoint_hash": _sha256(checkpoint) == case["checkpoint_sha256"],
        "output_absent": not (OUTPUT_ROOT / f"{case_id}-v1").exists(),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise V5S9FrozenError("S9 freeze failed: " + ", ".join(failed))
    return {
        "head": head,
        "code_tag": CODE_TAG,
        "code_commit": tag_commit,
        "checks": checks,
    }


def execute(case_id: str):
    freeze = verify_freeze(case_id)
    case = _case(case_id)
    output = OUTPUT_ROOT / f"{case_id}-v1"
    result = run(
        output,
        runner_version=f"v5-s9-{case_id}-frozen-v1",
        beam_dominance="resources-plus-energy",
        artifact_kind="v5-s9-frozen-development-result",
        width=2,
        top_k_per_parent=2,
        maximum_rounds=3,
        maximum_exact_attempts=6,
        checkpoint_path=ROOT / case["checkpoint_path"],
        algorithm_factory=_algorithm,
        case_id=case_id,
        hamiltonian_context=(
            "pinned-multisystem-checkpoint:"
            + case["checkpoint_sha256"]
        ),
        enforce_chemical_accuracy=False,
        execution_freeze=freeze,
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id", choices=("h6-1.5", "h6-3.0", "beh2-3.0"))
    arguments = parser.parse_args()
    result = execute(arguments.case_id)
    print(
        json.dumps(
            {
                "case_id": arguments.case_id,
                "winner_resources": result["result"]["winner_resources"],
                "winner_energy_increase": result["result"][
                    "winner_cumulative_energy_increase_hartree"
                ],
                "exact_attempts": result["result"]["exact_attempts"],
                "stop_reason": result["result"]["stop_reason"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
