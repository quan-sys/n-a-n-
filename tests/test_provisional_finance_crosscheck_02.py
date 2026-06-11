from pathlib import Path

import pandas as pd

from src.ingestion.provisional_finance_crosscheck import (
    build_finance_crosscheck_matrix,
    load_finance_sources,
    missing_optional_sources_markdown,
)


def test_finance_crosscheck_remains_one_source_only_with_single_source():
    finance = pd.DataFrame([{"ticker": "AAA", "period": "2025", "field_name": "revenue", "value": 100, "source_name": "legacy"}])

    matrix = build_finance_crosscheck_matrix(finance)

    assert matrix.iloc[0]["finance_crosscheck_status"] == "ONE_SOURCE_ONLY"
    assert matrix.iloc[0]["confidence_level"] == "PROVISIONAL_LOW"


def test_missing_optional_source_dir_is_reported(tmp_path: Path):
    primary = tmp_path / "primary.csv"
    primary.write_text("ticker,period,field_name,value,source_name\nAAA,2025,revenue,100,legacy\n", encoding="utf-8")

    _, present, missing = load_finance_sources(primary, tmp_path / "missing_optional")
    report = missing_optional_sources_markdown(missing)

    assert present == []
    assert "cafef_structured_finance" in report


def test_missing_values_are_not_zero_filled_in_finance_crosscheck():
    finance = pd.DataFrame([{"ticker": "AAA", "period": "2025", "field_name": "net_income", "value": "", "source_name": "legacy"}])

    matrix = build_finance_crosscheck_matrix(finance)

    assert matrix.iloc[0]["value_count"] == 0
    assert matrix.iloc[0]["min_value"] == ""
    assert "0" not in {str(matrix.iloc[0]["min_value"]), str(matrix.iloc[0]["max_value"])}
