from __future__ import annotations

import json

from dvg_obs_ceo.pra_path.release_audit import (
    ATTEMPT_FIELDS,
    CASE_FIELDS,
    PRA_ROOT,
    S6_RESULT,
    _verified_json,
    attempt_rows,
    case_rows,
)


def _result() -> dict:
    return json.loads(S6_RESULT.read_text(encoding="utf-8"))


def test_release_case_table_retains_every_development_condition() -> None:
    rows = case_rows(_result())
    assert len(rows) == 3
    assert set(rows[0]) == set(CASE_FIELDS)
    assert {row["case_id"] for row in rows} == {
        "h4-1.0",
        "h4-2.0",
        "h5-1.5",
    }
    h5 = next(row for row in rows if row["case_id"] == "h5-1.5")
    assert h5["accepted"] == 0


def test_release_attempt_table_retains_rejections_and_missing_cost() -> None:
    rows = attempt_rows(_result())
    assert len(rows) == 24
    assert set(rows[0]) == set(ATTEMPT_FIELDS)
    assert sum(row["accepted"] for row in rows) == 14
    assert all(row["paper_measurement_cost"] is None for row in rows)
    assert all(
        not row["accepted"] for row in rows if row["case_id"] == "h5-1.5"
    )


def test_release_inventory_does_not_invent_s2_internal_digest() -> None:
    _, field, digest = _verified_json(
        PRA_ROOT / "s2/source-protocol-v1.json",
        internal_digest_required=False,
    )
    assert field is None
    assert digest is None
