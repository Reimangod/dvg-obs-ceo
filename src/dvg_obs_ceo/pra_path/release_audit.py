"""Build and audit the immutable S11 negative-result release package."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Iterable
import uuid

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.identity import sha256_hex


PRA_ROOT = ROOT / "artifacts/pra_path"
RELEASE_ROOT = PRA_ROOT / "release"
MANIFEST = RELEASE_ROOT / "negative-result-release-manifest-v1.json"
CASE_CSV = RELEASE_ROOT / "s6-case-summary.csv"
ATTEMPT_CSV = RELEASE_ROOT / "s6-attempts.csv"
S6_RESULT = PRA_ROOT / "s6/independent-development-evaluation-v1.json"
S6_AUDIT = PRA_ROOT / "s6/result-audit-v1.json"
S10_GATE = PRA_ROOT / "s10/scientific-editorial-gate-v1.json"

DIGEST_FIELDS = (
    "ledger_digest",
    "report_digest",
    "freeze_digest",
    "audit_digest",
)


class ReleaseAuditError(RuntimeError):
    """Raised when release construction or verification fails closed."""


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_json(
    path: Path, *, internal_digest_required: bool = True
) -> tuple[dict[str, Any], str | None, str | None]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    matches: list[tuple[str, str]] = []
    for field in DIGEST_FIELDS:
        stored = payload.get(field)
        if stored is None:
            continue
        content = dict(payload)
        content.pop(field)
        if stored == sha256_hex(content):
            matches.append((field, stored))
    if len(matches) > 1 or (internal_digest_required and len(matches) != 1):
        raise ReleaseAuditError(
            f"invalid internal digest count in {path}: {matches}"
        )
    if not matches:
        return payload, None, None
    field, digest = matches[0]
    return payload, field, digest


def _atomic_write_new_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ReleaseAuditError(f"refusing to overwrite release artifact: {path}")
    temporary = path.parent / f".{path.name}.staging-{uuid.uuid4().hex}"
    try:
        descriptor = os.open(
            temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644
        )
        try:
            payload = text.encode("utf-8")
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                if written <= 0:
                    raise ReleaseAuditError(
                        "release artifact write made no progress"
                    )
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if path.exists():
            raise ReleaseAuditError(f"artifact appeared during write: {path}")
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        if temporary.exists():
            temporary.unlink()
        raise


def _csv_text(fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output, fieldnames=fieldnames, lineterminator="\n", extrasaction="raise"
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def case_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "case_id": item["case_id"],
            "attempted": item["attempted"],
            "accepted": item["accepted"],
            "rejected": item["rejected"],
            "new_energy_resource_nondominated_point": item[
                "new_energy_resource_nondominated_point"
            ],
            "best_accepted_cnot_reduction": item[
                "best_accepted_cnot_reduction"
            ],
            "best_accepted_cnot_depth_reduction": item[
                "best_accepted_cnot_depth_reduction"
            ],
            "best_accepted_total_depth_reduction": item[
                "best_accepted_total_depth_reduction"
            ],
            "best_accepted_parameter_reduction": item[
                "best_accepted_parameter_reduction"
            ],
        }
        for item in result["case_summaries"]
    ]


def attempt_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in result["attempts"]:
        resources = item["resources"]
        certification = item["certification"]
        optimizer = item["optimizer"]
        rows.append(
            {
                "attempt_id": item["attempt_id"],
                "case_id": item["case"]["case_id"],
                "queue_id": item["queue_item"]["queue_id"],
                "source_block_id": item["queue_item"]["source_block_id"],
                "family_id": item["queue_item"]["family_id"],
                "normal": json.dumps(
                    item["queue_item"]["normal"], separators=(",", ":")
                ),
                "accepted": item["acceptance"]["accepted"],
                "classification": item["classification"],
                "rejection_reasons": "|".join(
                    item["acceptance"]["rejection_reasons"]
                ),
                "source_relative_loss_hartree": certification[
                    "source_relative_loss_hartree"
                ],
                "orthonormal_tangent_gradient_infinity": certification[
                    "candidate_orthonormal_tangent_gradient_infinity"
                ],
                "optimizer_success": optimizer["success"],
                "optimizer_iterations": optimizer["iterations"],
                "energy_evaluations": optimizer["energy_evaluations"],
                "gradient_vector_evaluations": optimizer[
                    "gradient_vector_evaluations"
                ],
                "cnot_delta": resources["delta"]["cnot_count"],
                "cnot_depth_delta": resources["delta"]["cnot_depth"],
                "total_depth_delta": resources["delta"]["total_depth"],
                "parameter_delta": resources["delta"]["parameter_count"],
                "paper_measurement_cost": item["paper_measurement_cost"],
            }
        )
    return rows


CASE_FIELDS = [
    "case_id",
    "attempted",
    "accepted",
    "rejected",
    "new_energy_resource_nondominated_point",
    "best_accepted_cnot_reduction",
    "best_accepted_cnot_depth_reduction",
    "best_accepted_total_depth_reduction",
    "best_accepted_parameter_reduction",
]

ATTEMPT_FIELDS = [
    "attempt_id",
    "case_id",
    "queue_id",
    "source_block_id",
    "family_id",
    "normal",
    "accepted",
    "classification",
    "rejection_reasons",
    "source_relative_loss_hartree",
    "orthonormal_tangent_gradient_infinity",
    "optimizer_success",
    "optimizer_iterations",
    "energy_evaluations",
    "gradient_vector_evaluations",
    "cnot_delta",
    "cnot_depth_delta",
    "total_depth_delta",
    "parameter_delta",
    "paper_measurement_cost",
]


def _upstream_artifacts() -> list[Path]:
    return sorted(
        path
        for path in PRA_ROOT.rglob("*.json")
        if RELEASE_ROOT not in path.parents
    )


def build_release() -> dict[str, Any]:
    if _git("status", "--porcelain"):
        raise ReleaseAuditError("release build requires a clean worktree")
    s6, _, _ = _verified_json(S6_RESULT)
    s6_audit, _, _ = _verified_json(S6_AUDIT)
    s10, _, _ = _verified_json(S10_GATE)
    if s6["summary"]["decision"] != (
        "NO_GO_S6_REQUIRED_CROSS_SYSTEM_EVIDENCE_ABSENT"
    ):
        raise ReleaseAuditError("unexpected S6 decision")
    if s6_audit["authorization"]["s11_negative_result_release"] is not True:
        raise ReleaseAuditError("S6 audit does not authorize S11")
    if s10["authorization"]["s11_negative_result_release"] is not True:
        raise ReleaseAuditError("S10 does not authorize S11")
    if s10["authorization"]["pra_performance_manuscript"] is not False:
        raise ReleaseAuditError("positive performance manuscript is authorized")

    case_text = _csv_text(CASE_FIELDS, case_rows(s6))
    attempt_text = _csv_text(ATTEMPT_FIELDS, attempt_rows(s6))
    _atomic_write_new_text(CASE_CSV, case_text)
    _atomic_write_new_text(ATTEMPT_CSV, attempt_text)

    artifact_inventory = []
    for path in _upstream_artifacts():
        _, digest_field, internal_digest = _verified_json(
            path, internal_digest_required=False
        )
        artifact_inventory.append(
            {
                "path": str(path.relative_to(ROOT)),
                "sha256": _file_sha256(path),
                "internal_digest_field": digest_field,
                "internal_digest": internal_digest,
            }
        )
    release_tables = [
        {
            "path": str(path.relative_to(ROOT)),
            "sha256": _file_sha256(path),
        }
        for path in (CASE_CSV, ATTEMPT_CSV)
    ]
    manifest: dict[str, Any] = {
        "schema": "dvg-obs-ceo.pra-path.s11-negative-release.v1",
        "stage": "S11",
        "status": "COMPLETE",
        "decision": "RELEASE_NEGATIVE_RESULT_PACKAGE",
        "execution": {
            "builder_git_commit": _git("rev-parse", "HEAD"),
            "python_constraint": ">=3.10,<3.11",
            "dependency_lock": {
                "path": "uv.lock",
                "sha256": _file_sha256(ROOT / "uv.lock"),
            },
            "project_definition": {
                "path": "pyproject.toml",
                "sha256": _file_sha256(ROOT / "pyproject.toml"),
            },
            "container_image": None,
            "container_claim": False,
        },
        "artifact_inventory": artifact_inventory,
        "release_tables": release_tables,
        "result_summary": s6["summary"],
        "case_summaries": s6["case_summaries"],
        "closure": {
            "s7_scientific_execution": False,
            "s8_prospective_protocol_activated": False,
            "s9_prospective_execution": False,
            "s10_decision": s10["decision"],
        },
        "availability": {
            "source_repository": "https://github.com/Reimangod/dvg-obs-ceo",
            "release_tag": "pra-critical-path-negative-result-v1",
            "zenodo_doi": None,
            "zenodo_claim": False,
        },
        "reproduction": [
            "uv sync --extra baseline --extra test",
            (
                "OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 "
                "uv run pytest -q tests/pra_path"
            ),
            "uv run python -m dvg_obs_ceo.pra_path.release_audit audit",
        ],
        "claim_boundary": (
            "This package supports certified native resource reductions at "
            "two H4 development geometries and a frozen H5 non-certification. "
            "It contains no matched-work result, prospective validation, "
            "paper-equivalent Measurement Cost, general molecular "
            "superiority claim, or PRA acceptance claim."
        ),
    }
    manifest["report_digest"] = sha256_hex(manifest)
    atomic_write_new_json(MANIFEST, manifest)
    return manifest


def audit_release() -> dict[str, Any]:
    manifest, _, _ = _verified_json(MANIFEST)
    checks: dict[str, bool] = {}
    inventory = manifest["artifact_inventory"]
    checks["inventory_nonempty"] = bool(inventory)
    checks["inventory_paths_unique"] = len(
        {item["path"] for item in inventory}
    ) == len(inventory)
    checks["inventory_is_complete"] = {
        item["path"] for item in inventory
    } == {str(path.relative_to(ROOT)) for path in _upstream_artifacts()}
    for item in inventory:
        path = ROOT / item["path"]
        _, field, digest = _verified_json(
            path, internal_digest_required=False
        )
        checks[f"artifact:{item['path']}"] = (
            _file_sha256(path) == item["sha256"]
            and field == item["internal_digest_field"]
            and digest == item["internal_digest"]
        )
    for item in manifest["release_tables"]:
        path = ROOT / item["path"]
        checks[f"table:{item['path']}"] = _file_sha256(path) == item["sha256"]
    with CASE_CSV.open(newline="", encoding="utf-8") as stream:
        cases = list(csv.DictReader(stream))
    with ATTEMPT_CSV.open(newline="", encoding="utf-8") as stream:
        attempts = list(csv.DictReader(stream))
    s6, _, _ = _verified_json(S6_RESULT)
    checks["case_table_exactly_regenerated"] = CASE_CSV.read_text(
        encoding="utf-8"
    ) == _csv_text(CASE_FIELDS, case_rows(s6))
    checks["attempt_table_exactly_regenerated"] = ATTEMPT_CSV.read_text(
        encoding="utf-8"
    ) == _csv_text(ATTEMPT_FIELDS, attempt_rows(s6))
    checks["three_case_rows"] = len(cases) == 3
    checks["twenty_four_attempt_rows"] = len(attempts) == 24
    checks["attempt_ids_unique"] = len(
        {row["attempt_id"] for row in attempts}
    ) == len(attempts)
    checks["accepted_count_fourteen"] = sum(
        row["accepted"] == "True" for row in attempts
    ) == 14
    checks["h5_acceptance_zero"] = not any(
        row["accepted"] == "True"
        for row in attempts
        if row["case_id"] == "h5-1.5"
    )
    checks["measurement_cost_unavailable"] = all(
        row["paper_measurement_cost"] == "" for row in attempts
    )
    checks["closure_is_fail_closed"] = manifest["closure"] == {
        "s7_scientific_execution": False,
        "s8_prospective_protocol_activated": False,
        "s9_prospective_execution": False,
        "s10_decision": "NO_GO_PRA_PERFORMANCE_SUBMISSION_PACKAGE",
    }
    s7, _, _ = _verified_json(PRA_ROOT / "s7/not-authorized-v1.json")
    s8, _, _ = _verified_json(PRA_ROOT / "s8/not-authorized-v1.json")
    s9, _, _ = _verified_json(PRA_ROOT / "s9/not-authorized-v1.json")
    checks["closure_artifacts_prohibit_execution"] = (
        s7["scientific_actions_executed"] is False
        and s7["matched_work_executed"] is False
        and s8["scientific_actions_executed"] is False
        and s8["prospective_manifest_frozen"] is False
        and s9["scientific_actions_executed"] is False
        and s9["prospective_result_exists"] is False
    )
    checks["environment_lock_unchanged"] = (
        _file_sha256(ROOT / "uv.lock")
        == manifest["execution"]["dependency_lock"]["sha256"]
    )
    checks["project_definition_unchanged"] = (
        _file_sha256(ROOT / "pyproject.toml")
        == manifest["execution"]["project_definition"]["sha256"]
    )
    if not all(checks.values()):
        raise ReleaseAuditError(
            "release audit failed: "
            + ", ".join(name for name, passed in checks.items() if not passed)
        )
    return {
        "decision": "S11_RELEASE_AUDIT_PASS",
        "checks_passed": len(checks),
        "checks_total": len(checks),
        "manifest_digest": manifest["report_digest"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "audit"))
    arguments = parser.parse_args()
    result = build_release() if arguments.action == "build" else audit_release()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
