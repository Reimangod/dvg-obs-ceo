"""PRA S3 finite normal-registry scope audit."""

from __future__ import annotations

import itertools
import json
from pathlib import Path
import subprocess
from typing import Any

import numpy as np

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.identity import sha256_hex
from dvg_obs_ceo.v6_rank_adaptive.native_synthesis_pipeline import NS1_OUTPUT


OUTPUT = ROOT / "artifacts/pra_path/s3/normal-registry-audit-v1.json"
S2_OUTPUT = ROOT / "artifacts/pra_path/s2/source-protocol-v1.json"


class S3RegistryAuditError(RuntimeError):
    """Raised when the finite rank-two registry is incomplete or ambiguous."""


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def canonical_normals() -> tuple[tuple[int, int, int], ...]:
    values = []
    for normal in itertools.product((-1, 0, 1), repeat=3):
        if normal == (0, 0, 0):
            continue
        first = next(value for value in normal if value)
        if first == 1:
            values.append(normal)
    return tuple(sorted(values))


def build_report() -> dict[str, Any]:
    source_protocol = json.loads(S2_OUTPUT.read_text(encoding="utf-8"))
    if source_protocol["authorization"]["s3"] is not True:
        raise S3RegistryAuditError("S2 did not authorize S3")
    registry = json.loads(NS1_OUTPUT.read_text(encoding="utf-8"))
    families = registry["families"]
    expected = canonical_normals()
    observed = tuple(
        sorted(tuple(int(item) for item in family["normal"])
               for family in families)
    )
    records = []
    for family in sorted(families, key=lambda item: tuple(item["normal"])):
        normal = np.asarray(family["normal"], dtype=np.int64)
        parameter_map = np.asarray(
            family["parameter_map"], dtype=np.int64
        )
        checks = {
            "coefficient_alphabet": set(normal).issubset({-1, 0, 1}),
            "nonzero": bool(np.any(normal)),
            "global_sign_canonical": int(normal[np.flatnonzero(normal)[0]]) == 1,
            "map_shape": parameter_map.shape == (3, 2),
            "exact_constraint": bool(np.array_equal(normal @ parameter_map, [0, 0])),
            "exact_rank_two": int(np.linalg.matrix_rank(parameter_map)) == 2,
            "declared_rank_two": family["declared_rank"] == 2,
            "hamiltonian_or_energy_unused": (
                family["hamiltonian_or_energy_used"] is False
            ),
        }
        records.append(
            {
                "family_id": family["family_id"],
                "normal": family["normal"],
                "family_kind": family["family_kind"],
                "checks": checks,
                "valid": all(checks.values()),
            }
        )
    complete = observed == expected and len(observed) == len(set(observed))
    decision = (
        "GO_S4_FINITE_REGISTRY_COMPLETE"
        if complete and all(item["valid"] for item in records)
        else "NO_GO_REGISTRY_INCOMPLETE"
    )
    report: dict[str, Any] = {
        "schema": "dvg-obs-ceo.pra-path.s3-normal-registry-audit.v1",
        "decision": decision,
        "scope": {
            "coefficient_alphabet": [-1, 0, 1],
            "zero_normal_excluded": True,
            "global_sign_equivalence": True,
            "slot_permutation_equivalence": False,
            "general_integer_normals_in_scope": False,
            "all_rank_two_subspaces_in_scope": False,
            "precise_claim": (
                "complete enumeration of primitive canonical normals in "
                "{-1,0,1}^3 modulo global sign"
            ),
        },
        "expected_normal_count": len(expected),
        "observed_normal_count": len(observed),
        "expected_normals": [list(item) for item in expected],
        "observed_normals": [list(item) for item in observed],
        "registry_complete": complete,
        "families": records,
        "prospective_queue_policy": {
            "include_every_structurally_resource_eligible_family": True,
            "deduplicate_by_global_sign_only": True,
            "deduplicate_by_slot_permutation": False,
            "energy_or_gradient_used_for_filtering": False,
            "outcomes_may_change_registry": False,
        },
        "authorization": {
            "s4": decision == "GO_S4_FINITE_REGISTRY_COMPLETE",
            "performance_execution": False,
        },
        "execution": {"git_commit": _git("rev-parse", "HEAD")},
        "claim_boundary": (
            "Finite registered-family completeness only; no completeness over "
            "general rank-two subspaces and no performance claim."
        ),
    }
    report["report_digest"] = sha256_hex(report)
    return report


def audit_report(report: dict[str, Any]) -> None:
    content = dict(report)
    digest = content.pop("report_digest", None)
    if digest != sha256_hex(content):
        raise S3RegistryAuditError("S3 report digest mismatch")
    if report["scope"]["slot_permutation_equivalence"]:
        raise S3RegistryAuditError("slot permutation was not proved")
    if not report["registry_complete"]:
        raise S3RegistryAuditError("finite registry is incomplete")
    if not all(item["valid"] for item in report["families"]):
        raise S3RegistryAuditError("one registered family is invalid")


def main() -> None:
    if OUTPUT.exists():
        raise S3RegistryAuditError("refusing to overwrite S3 audit")
    if _git("status", "--porcelain"):
        raise S3RegistryAuditError("S3 requires a clean worktree")
    report = build_report()
    audit_report(report)
    atomic_write_new_json(OUTPUT, report)


if __name__ == "__main__":
    main()
