import json
from pathlib import Path

import pandas as pd
import pytest

from src.ingestion.disclosure_warning_ingestion import (
    DISCLOSURE_STATUS_RAW_FILENAME,
    REAL_SOURCE_UNAVAILABLE,
    has_prohibited_recommendation_columns,
    ingest_disclosure_warning_data,
)


FETCH_TIME = "2026-01-01T00:00:00Z"


def _disclosure_rows():
    return [
        {
            "ticker": "MOCK1",
            "event_date": "2026-01-01",
            "event_type": "OTHER",
            "severity": "LOW",
            "title": "Mock disclosure event one",
            "description": "Mock/sample disclosure row only",
            "source": "manual_sample",
            "source_url": "mock://disclosure_status/MOCK1",
            "fetch_time": FETCH_TIME,
            "confidence_raw": "sample",
            "notes": "mock/sample disclosure data only",
        },
        {
            "ticker": "MOCK2",
            "event_date": "2026-01-01",
            "event_type": "DISCLOSURE_VIOLATION",
            "severity": "MEDIUM",
            "title": "Mock disclosure event two",
            "description": "Mock/sample disclosure row only",
            "source": "manual_sample",
            "source_url": "mock://disclosure_status/MOCK2",
            "fetch_time": FETCH_TIME,
            "confidence_raw": "sample",
            "notes": "mock/sample disclosure data only",
        },
    ]


def _write_disclosure_csv(tmp_path, rows=None):
    path = tmp_path / "disclosure_status.csv"
    pd.DataFrame(rows or _disclosure_rows()).to_csv(path, index=False)
    return path


def _run_ingestion(
    tmp_path,
    mode,
    input_path=None,
    requested_tickers=None,
    run_id="run_disclosure",
):
    return ingest_disclosure_warning_data(
        mode=mode,
        input_path=input_path,
        requested_tickers=requested_tickers,
        raw_output_dir=tmp_path / "raw",
        manifest_dir=tmp_path / "manifests",
        coverage_output_dir=tmp_path / "coverage",
        manual_review_dir=tmp_path / "manual_review",
        run_id=run_id,
        fetch_time=FETCH_TIME,
    )


def test_manual_csv_ingestion_writes_raw_output_and_reports(tmp_path):
    csv_path = _write_disclosure_csv(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )

    assert result["status"] == "SUCCESS"
    assert Path(result["raw_output_path"]).name == DISCLOSURE_STATUS_RAW_FILENAME
    assert Path(result["coverage_report_path"]).exists()
    assert Path(result["manual_review_candidate_path"]).exists()
    assert result["coverage"]["ticker_count_requested"] == 2
    assert result["coverage"]["ticker_count_with_disclosure_rows"] == 2
    assert result["coverage"]["ticker_count_without_disclosure_rows"] == 0
    assert result["coverage"]["event_type_counts"]["OTHER"] == 1
    assert result["coverage"]["event_type_counts"]["DISCLOSURE_VIOLATION"] == 1


def test_manual_xlsx_ingestion_works_when_dependency_available(tmp_path):
    pytest.importorskip("openpyxl")
    xlsx_path = tmp_path / "disclosure_status.xlsx"
    pd.DataFrame(_disclosure_rows()).to_excel(xlsx_path, index=False)

    result = _run_ingestion(
        tmp_path,
        "manual_xlsx",
        input_path=xlsx_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )

    assert result["status"] == "SUCCESS"
    assert Path(result["raw_output_path"]).exists()


def test_external_vendor_optional_file_mode_uses_contract_validation(tmp_path):
    csv_path = _write_disclosure_csv(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "external_vendor_optional",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )

    assert result["status"] == "SUCCESS"
    raw = pd.read_csv(result["raw_output_path"])
    assert set(raw["source_url"]) == {
        "mock://disclosure_status/MOCK1",
        "mock://disclosure_status/MOCK2",
    }


def test_missing_required_columns_fail_validation(tmp_path):
    rows = _disclosure_rows()
    for row in rows:
        row.pop("title")
    csv_path = _write_disclosure_csv(tmp_path, rows)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )

    assert result["status"] == "DATA_ERROR"
    assert result["raw_output_path"] == ""
    assert result["validation_result"]["missing_required_columns"] == ["title"]
    assert Path(result["manifest_path"]).exists()


def test_unknown_event_type_is_preserved_and_flagged(tmp_path):
    rows = _disclosure_rows()
    rows[0]["event_type"] = "mystery event"
    csv_path = _write_disclosure_csv(tmp_path, rows)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )
    raw = pd.read_csv(result["raw_output_path"])
    manual_review = pd.read_csv(result["manual_review_candidate_path"])

    assert result["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["coverage"]["unknown_event_type_count"] == 1
    assert "UNKNOWN_EVENT_TYPE" in result["coverage"]["warnings"]
    assert "MYSTERY_EVENT" in set(raw["event_type"])
    assert "UNKNOWN_EVENT_TYPE" in set(manual_review["review_reason"])


def test_unknown_severity_is_preserved_and_flagged(tmp_path):
    rows = _disclosure_rows()
    rows[0]["severity"] = "mystery severity"
    csv_path = _write_disclosure_csv(tmp_path, rows)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )
    raw = pd.read_csv(result["raw_output_path"])
    manual_review = pd.read_csv(result["manual_review_candidate_path"])

    assert result["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["coverage"]["unknown_severity_count"] == 1
    assert "UNKNOWN_SEVERITY" in result["coverage"]["warnings"]
    assert "MYSTERY_SEVERITY" in set(raw["severity"])
    assert "UNKNOWN_SEVERITY" in set(manual_review["review_reason"])


def test_high_critical_severity_enters_manual_review_candidates(tmp_path):
    rows = _disclosure_rows()
    rows[0]["severity"] = "HIGH"
    rows[1]["severity"] = "CRITICAL"
    csv_path = _write_disclosure_csv(tmp_path, rows)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )
    manual_review = pd.read_csv(result["manual_review_candidate_path"])

    assert result["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["coverage"]["high_severity_count"] == 1
    assert result["coverage"]["critical_severity_count"] == 1
    assert "HIGH_SEVERITY_DISCLOSURE" in set(manual_review["review_reason"])
    assert "CRITICAL_SEVERITY_DISCLOSURE" in set(manual_review["review_reason"])


def test_no_disclosure_row_is_unknown_not_clean(tmp_path):
    csv_path = _write_disclosure_csv(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2", "MOCK3"],
    )
    manual_review = pd.read_csv(result["manual_review_candidate_path"])
    missing_row = manual_review[manual_review["ticker"] == "MOCK3"].iloc[0]

    assert result["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["coverage"]["ticker_count_without_disclosure_rows"] == 1
    assert result["coverage"]["tickers_without_disclosure_rows"] == ["MOCK3"]
    assert "DISCLOSURE_DATA_UNAVAILABLE_FOR_REQUESTED_TICKER" in result["coverage"][
        "warnings"
    ]
    assert missing_row["review_reason"] == "DISCLOSURE_DATA_UNAVAILABLE"
    assert missing_row["event_type"] == "UNKNOWN"
    assert missing_row["severity"] == "UNKNOWN"


def test_real_unavailable_returns_status_manifest_and_manual_review_file(tmp_path):
    result = _run_ingestion(
        tmp_path,
        "real_exchange_optional",
        requested_tickers=["MOCK1", "MOCK2"],
    )
    manual_review = pd.read_csv(result["manual_review_candidate_path"])

    assert result["status"] == REAL_SOURCE_UNAVAILABLE
    assert result["errors"] == [REAL_SOURCE_UNAVAILABLE]
    assert result["raw_output_path"] == ""
    assert Path(result["manifest_path"]).exists()
    assert set(manual_review["review_reason"]) == {REAL_SOURCE_UNAVAILABLE}


def test_manifest_and_coverage_reports_are_written(tmp_path):
    csv_path = _write_disclosure_csv(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
        run_id="run_disclosure_manifest",
    )

    with open(result["manifest_path"], encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)
    with open(result["coverage_report_path"], encoding="utf-8") as coverage_file:
        coverage = json.load(coverage_file)

    assert manifest["run_id"] == "run_disclosure_manifest"
    assert manifest["dataset_name"] == "disclosure_status"
    assert manifest["row_count"] == 2
    assert coverage["ticker_count_requested"] == 2


def test_coverage_report_has_required_fields(tmp_path):
    csv_path = _write_disclosure_csv(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )

    required_fields = {
        "ticker_count_requested",
        "ticker_count_with_disclosure_rows",
        "ticker_count_without_disclosure_rows",
        "high_severity_count",
        "critical_severity_count",
        "unknown_severity_count",
        "missing_source_url_count",
        "event_type_counts",
        "warnings",
    }
    assert required_fields.issubset(result["coverage"])


def test_missing_source_url_is_flagged(tmp_path):
    rows = _disclosure_rows()
    rows[0]["source_url"] = ""
    csv_path = _write_disclosure_csv(tmp_path, rows)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )
    manual_review = pd.read_csv(result["manual_review_candidate_path"])

    assert result["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["coverage"]["missing_source_url_count"] == 1
    assert "MISSING_SOURCE_URL" in result["coverage"]["warnings"]
    assert "MISSING_SOURCE_URL" in set(manual_review["review_reason"])


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


def test_raw_outputs_have_no_buy_sell_or_target_price_fields(tmp_path):
    csv_path = _write_disclosure_csv(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )
    raw = pd.read_csv(result["raw_output_path"])

    assert not has_prohibited_recommendation_columns(raw)


def test_disclosure_tests_use_only_mock_tickers_and_no_financial_fields(tmp_path):
    csv_path = _write_disclosure_csv(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )
    raw = pd.read_csv(result["raw_output_path"])

    prohibited_financial_fields = {
        "revenue",
        "gross_profit",
        "operating_profit",
        "net_profit",
        "total_assets",
        "total_liabilities",
        "equity",
        "cash",
        "inventory",
    }
    assert set(raw["ticker"]) == {"MOCK1", "MOCK2"}
    assert prohibited_financial_fields.isdisjoint(set(raw.columns))
