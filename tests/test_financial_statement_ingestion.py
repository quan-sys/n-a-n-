import json
from pathlib import Path

import pandas as pd
import pytest

from src.ingestion.financial_statement_ingestion import (
    FINANCIAL_STATEMENT_RAW_FILENAME,
    REAL_SOURCE_UNAVAILABLE,
    has_prohibited_recommendation_columns,
    ingest_financial_statement_data,
)


FETCH_TIME = "2026-01-01T00:00:00Z"


def _financial_rows(*, duplicate: bool = False):
    rows = [
        {
            "ticker": "MOCK1",
            "period": "2026Q1",
            "period_type": "quarter",
            "statement_type": "summary",
            "fiscal_year": "2026",
            "quarter": "Q1",
            "currency": "MOCK_CURRENCY",
            "unit_scale": "mock_unit",
            "revenue": 1000,
            "gross_profit": 300,
            "operating_profit": 200,
            "net_profit": 100,
            "total_assets": 5000,
            "total_liabilities": 2000,
            "equity": 3000,
            "cash": 500,
            "short_term_debt": 200,
            "long_term_debt": 400,
            "operating_cash_flow": 150,
            "inventory": 250,
            "source": "manual_sample_a",
            "source_url": "mock://financial_statement/MOCK1/2026Q1",
            "fetch_time": FETCH_TIME,
            "confidence_raw": "sample",
            "notes": "mock/sample financial row only",
        },
        {
            "ticker": "MOCK2",
            "period": "2026Q1",
            "period_type": "quarter",
            "statement_type": "summary",
            "fiscal_year": "2026",
            "quarter": "Q1",
            "currency": "MOCK_CURRENCY",
            "unit_scale": "mock_unit",
            "revenue": 2000,
            "gross_profit": 600,
            "operating_profit": 400,
            "net_profit": 200,
            "total_assets": 10000,
            "total_liabilities": 4000,
            "equity": 6000,
            "cash": 1000,
            "short_term_debt": 400,
            "long_term_debt": 800,
            "operating_cash_flow": 300,
            "inventory": 500,
            "source": "manual_sample_a",
            "source_url": "mock://financial_statement/MOCK2/2026Q1",
            "fetch_time": FETCH_TIME,
            "confidence_raw": "sample",
            "notes": "mock/sample financial row only",
        },
    ]
    if duplicate:
        rows.append(dict(rows[0]))
    return rows


def _write_financial_csv(tmp_path, rows=None):
    path = tmp_path / "financial_statement.csv"
    pd.DataFrame(rows or _financial_rows()).to_csv(path, index=False)
    return path


def _run_ingestion(
    tmp_path,
    mode,
    input_path=None,
    requested_tickers=None,
    run_id="run_financial",
):
    return ingest_financial_statement_data(
        mode=mode,
        input_path=input_path,
        requested_tickers=requested_tickers,
        raw_output_dir=tmp_path / "raw",
        manifest_dir=tmp_path / "manifests",
        coverage_output_dir=tmp_path / "coverage",
        missing_report_dir=tmp_path / "missing",
        run_id=run_id,
        fetch_time=FETCH_TIME,
    )


def test_manual_csv_ingestion_writes_raw_output_and_reports(tmp_path):
    csv_path = _write_financial_csv(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )

    assert result["status"] == "SUCCESS"
    assert Path(result["raw_output_path"]).name == FINANCIAL_STATEMENT_RAW_FILENAME
    assert Path(result["coverage_report_path"]).exists()
    assert Path(result["missing_data_report_path"]).exists()
    assert result["coverage"]["ticker_count_requested"] == 2
    assert result["coverage"]["ticker_count_with_financials"] == 2
    assert result["coverage"]["period_count"] == 1
    assert result["coverage"]["min_period"] == "2026Q1"
    assert result["coverage"]["max_period"] == "2026Q1"


def test_manual_xlsx_ingestion_works_when_dependency_available(tmp_path):
    pytest.importorskip("openpyxl")
    xlsx_path = tmp_path / "financial_statement.xlsx"
    pd.DataFrame(_financial_rows()).to_excel(xlsx_path, index=False)

    result = _run_ingestion(
        tmp_path,
        "manual_xlsx",
        input_path=xlsx_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )

    assert result["status"] == "SUCCESS"
    assert Path(result["raw_output_path"]).exists()


def test_external_vendor_optional_file_mode_uses_contract_validation(tmp_path):
    csv_path = _write_financial_csv(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "external_vendor_optional",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )

    assert result["status"] == "SUCCESS"
    raw = pd.read_csv(result["raw_output_path"])
    assert set(raw["unit_scale"]) == {"mock_unit"}


def test_missing_required_columns_fail_validation(tmp_path):
    rows = _financial_rows()
    for row in rows:
        row.pop("period_type")
    csv_path = _write_financial_csv(tmp_path, rows)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )

    assert result["status"] == "DATA_ERROR"
    assert result["raw_output_path"] == ""
    assert result["validation_result"]["missing_required_columns"] == ["period_type"]
    assert Path(result["manifest_path"]).exists()


def test_missing_financial_fields_remain_missing_and_are_reported(tmp_path):
    rows = _financial_rows()
    rows[0]["revenue"] = None
    rows[0]["net_profit"] = None
    rows[1]["equity"] = None
    rows[1]["operating_cash_flow"] = None
    csv_path = _write_financial_csv(tmp_path, rows)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )
    raw = pd.read_csv(result["raw_output_path"])
    missing_report = pd.read_csv(result["missing_data_report_path"])

    assert result["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["coverage"]["missing_revenue_count"] == 1
    assert result["coverage"]["missing_net_profit_count"] == 1
    assert result["coverage"]["missing_equity_count"] == 1
    assert result["coverage"]["missing_cfo_count"] == 1
    assert raw.loc[raw["ticker"] == "MOCK1", "revenue"].isna().all()
    assert "MISSING_REVENUE" in set(missing_report["issue"])
    assert "MISSING_OPERATING_CASH_FLOW" in set(missing_report["issue"])


def test_negative_equity_is_flagged_not_corrected(tmp_path):
    rows = _financial_rows()
    rows[0]["equity"] = -100
    csv_path = _write_financial_csv(tmp_path, rows)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )
    raw = pd.read_csv(result["raw_output_path"])
    missing_report = pd.read_csv(result["missing_data_report_path"])

    assert result["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["coverage"]["negative_equity_count"] == 1
    assert "NEGATIVE_EQUITY" in result["coverage"]["warnings"]
    assert raw.loc[raw["ticker"] == "MOCK1", "equity"].iloc[0] == -100
    assert "NEGATIVE_EQUITY" in set(missing_report["issue"])


def test_duplicate_ticker_period_is_flagged(tmp_path):
    csv_path = _write_financial_csv(tmp_path, _financial_rows(duplicate=True))

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )

    assert result["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["coverage"]["duplicate_ticker_period_count"] == 2
    assert "DUPLICATE_TICKER_PERIOD" in result["coverage"]["warnings"]


def test_source_conflict_is_flagged_if_represented(tmp_path):
    rows = _financial_rows()
    conflicting_row = dict(rows[0])
    conflicting_row["source"] = "manual_sample_b"
    conflicting_row["source_url"] = "mock://financial_statement/MOCK1/2026Q1/source_b"
    conflicting_row["revenue"] = 9999
    rows.append(conflicting_row)
    csv_path = _write_financial_csv(tmp_path, rows)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )
    missing_report = pd.read_csv(result["missing_data_report_path"])

    assert result["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["coverage"]["source_conflict_count"] >= 1
    assert "DATA_CONFLICT" in result["coverage"]["warnings"]
    assert "DATA_CONFLICT" in set(missing_report["issue"])


def test_requested_ticker_without_financials_is_reported(tmp_path):
    csv_path = _write_financial_csv(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2", "MOCK3"],
    )
    missing_report = pd.read_csv(result["missing_data_report_path"])

    assert result["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["coverage"]["ticker_count_missing_financials"] == 1
    assert result["coverage"]["missing_financial_tickers"] == ["MOCK3"]
    assert "MISSING_FINANCIALS_FOR_REQUESTED_TICKER" in set(missing_report["issue"])


def test_mock_mode_labels_data_as_mock_sample(tmp_path):
    result = _run_ingestion(
        tmp_path,
        "mock",
        requested_tickers=["MOCK1", "MOCK2"],
    )
    raw = pd.read_csv(result["raw_output_path"])

    assert result["status"] == "SUCCESS"
    assert set(raw["confidence_raw"]) == {"mock"}
    assert raw["notes"].str.contains("mock/sample").all()
    assert set(raw["ticker"]) == {"MOCK1", "MOCK2"}


def test_real_unavailable_returns_status_and_manifest(tmp_path):
    result = _run_ingestion(
        tmp_path,
        "real_vnstock_optional",
        requested_tickers=["MOCK1", "MOCK2"],
    )

    assert result["status"] == REAL_SOURCE_UNAVAILABLE
    assert result["errors"] == [REAL_SOURCE_UNAVAILABLE]
    assert result["raw_output_path"] == ""
    assert Path(result["manifest_path"]).exists()


def test_manifest_and_coverage_reports_are_written(tmp_path):
    csv_path = _write_financial_csv(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
        run_id="run_financial_manifest",
    )

    with open(result["manifest_path"], encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)
    with open(result["coverage_report_path"], encoding="utf-8") as coverage_file:
        coverage = json.load(coverage_file)

    assert manifest["run_id"] == "run_financial_manifest"
    assert manifest["dataset_name"] == "financial_statement_summary"
    assert manifest["row_count"] == 2
    assert coverage["ticker_count_requested"] == 2


def test_coverage_report_has_required_fields(tmp_path):
    csv_path = _write_financial_csv(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )

    required_fields = {
        "ticker_count_requested",
        "ticker_count_with_financials",
        "ticker_count_missing_financials",
        "period_count",
        "min_period",
        "max_period",
        "missing_revenue_count",
        "missing_net_profit_count",
        "missing_equity_count",
        "missing_cfo_count",
        "negative_equity_count",
        "duplicate_ticker_period_count",
        "source_count",
        "warnings",
    }
    assert required_fields.issubset(result["coverage"])


def test_raw_outputs_have_no_buy_sell_or_target_price_fields(tmp_path):
    csv_path = _write_financial_csv(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )
    raw = pd.read_csv(result["raw_output_path"])

    assert not has_prohibited_recommendation_columns(raw)

