import csv

from dvg_obs_ceo.multisystem_paper_comparison import _write_csv, direct_comparison, load_data


def test_stored_checkpoints_and_direct_comparison() -> None:
    data = load_data()
    assert set(data) == {"h6-1.5", "h6-3.0", "beh2-3.0"}
    comparison = direct_comparison(data)
    assert comparison["paper"]["cnot_count"] == 812
    assert comparison["paper"]["cnot_depth"] == 282
    assert comparison["local"]["cnot_count"] == 879
    assert comparison["local"]["cnot_depth"] == 306
    assert comparison["local"]["measurement_cost"] is None
    assert comparison["delta_percent"]["cnot_count"] > 0
    assert comparison["delta_percent"]["cnot_depth"] > 0


def test_csv_writer_projects_ledger_rows_to_declared_schema(tmp_path) -> None:
    data = load_data()
    output = tmp_path / "figure-data.csv"
    _write_csv(output, data)
    with output.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 64
    assert "finished" not in rows[0]
    assert rows[-1]["case"] == "beh2-3.0"
