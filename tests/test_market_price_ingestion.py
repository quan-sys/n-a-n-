import json
from pathlib import Path

import pandas as pd
import pytest

from src.ingestion.market_price_ingestion import (
    MARKET_PRICE_RAW_FILENAME,
    REAL_SOURCE_UNAVAILABLE,
    has_prohibited_recommendation_columns,
    ingest_market_price_data,
)


FETCH_TIME = "2026-01-01T00:00:00Z"


def _market_rows(*, duplicate: bool = False):
    rows = [
        {
            "ticker": "MOCK1",
            "date": "2026-01-01",
            "open": 99,
            "high": 102,
            "low": 98,
            "close": 101,
            "volume": 1000,
            "trading_value": 101000,
            "source": "manual_sample",
            "source_url": "mock://market_price/MOCK1",
            "fetch_time": FETCH_TIME,
            "confidence_raw": "sample",
            "notes": "mock/sample market row only",
        },
        {
            "ticker": "MOCK2",
            "date": "2026-01-01",
            "open": 199,
            "high": 202,
            "low": 198,
            "close": 201,
            "volume": 2000,
            "trading_value": 402000,
            "source": "manual_sample",
            "source_url": "mock://market_price/MOCK2",
            "fetch_time": FETCH_TIME,
            "confidence_raw": "sample",
            "notes": "mock/sample market row only",
        },
    ]
    if duplicate:
        rows.append(dict(rows[0]))
    return rows


def _write_market_csv(tmp_path, rows=None):
    path = tmp_path / "market_price.csv"
    pd.DataFrame(rows or _market_rows()).to_csv(path, index=False)
    return path


def _run_ingestion(
    tmp_path,
    mode,
    input_path=None,
    requested_tickers=None,
    stale_reference_date=None,
    run_id="run_market",
):
    return ingest_market_price_data(
        mode=mode,
        input_path=input_path,
        requested_tickers=requested_tickers,
        raw_output_dir=tmp_path / "raw",
        manifest_dir=tmp_path / "manifests",
        coverage_output_dir=tmp_path / "coverage",
        ticker_log_dir=tmp_path / "ticker_logs",
        run_id=run_id,
        fetch_time=FETCH_TIME,
        stale_reference_date=stale_reference_date,
        stale_after_days=10,
    )


def test_manual_csv_ingestion_writes_raw_output_and_coverage(tmp_path):
    csv_path = _write_market_csv(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )

    assert result["status"] == "SUCCESS"
    assert Path(result["raw_output_path"]).name == MARKET_PRICE_RAW_FILENAME
    assert Path(result["coverage_report_path"]).exists()
    assert result["coverage"]["ticker_count_requested"] == 2
    assert result["coverage"]["ticker_count_success"] == 2
    assert result["coverage"]["row_count"] == 2
    assert result["coverage"]["min_date"] == "2026-01-01"
    assert result["coverage"]["max_date"] == "2026-01-01"


def test_manual_xlsx_ingestion_works_when_dependency_available(tmp_path):
    pytest.importorskip("openpyxl")
    xlsx_path = tmp_path / "market_price.xlsx"
    pd.DataFrame(_market_rows()).to_excel(xlsx_path, index=False)

    result = _run_ingestion(
        tmp_path,
        "manual_xlsx",
        input_path=xlsx_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )

    assert result["status"] == "SUCCESS"
    assert Path(result["raw_output_path"]).exists()


def test_missing_required_columns_fail_validation(tmp_path):
    rows = _market_rows()
    for row in rows:
        row.pop("trading_value")
    csv_path = _write_market_csv(tmp_path, rows)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )

    assert result["status"] == "DATA_ERROR"
    assert result["raw_output_path"] == ""
    assert result["validation_result"]["missing_required_columns"] == [
        "trading_value"
    ]
    assert Path(result["manifest_path"]).exists()


def test_missing_close_and_volume_are_flagged_not_filled(tmp_path):
    rows = _market_rows()
    rows[0]["close"] = None
    rows[1]["volume"] = None
    csv_path = _write_market_csv(tmp_path, rows)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )
    raw = pd.read_csv(result["raw_output_path"])
    ticker_log = pd.read_csv(result["ticker_log_path"])

    assert result["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["coverage"]["missing_close_count"] == 1
    assert result["coverage"]["missing_volume_count"] == 1
    assert raw.loc[raw["ticker"] == "MOCK1", "close"].isna().all()
    assert raw.loc[raw["ticker"] == "MOCK2", "volume"].isna().all()
    assert set(ticker_log["status"]) == {"MANUAL_REVIEW"}


def test_negative_volume_is_flagged(tmp_path):
    rows = _market_rows()
    rows[0]["volume"] = -100
    csv_path = _write_market_csv(tmp_path, rows)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )

    assert result["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["coverage"]["negative_volume_count"] == 1
    assert "NEGATIVE_VOLUME" in result["coverage"]["warnings"]


def test_invalid_price_is_flagged(tmp_path):
    rows = _market_rows()
    rows[0]["close"] = 0
    csv_path = _write_market_csv(tmp_path, rows)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )

    assert result["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["coverage"]["invalid_price_count"] == 1
    assert "INVALID_PRICE" in result["coverage"]["warnings"]


def test_duplicate_ticker_date_rows_are_flagged(tmp_path):
    csv_path = _write_market_csv(tmp_path, _market_rows(duplicate=True))

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )

    assert result["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["coverage"]["duplicate_row_count"] == 2
    assert "DUPLICATE_TICKER_DATE" in result["coverage"]["warnings"]


def test_failed_requested_ticker_appears_in_failure_log(tmp_path):
    csv_path = _write_market_csv(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2", "MOCK3"],
    )
    ticker_log = pd.read_csv(result["ticker_log_path"])
    failed_row = ticker_log[ticker_log["ticker"] == "MOCK3"].iloc[0]

    assert result["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["coverage"]["ticker_count_failed"] == 1
    assert failed_row["status"] == "FAILED"
    assert failed_row["failure_reason"] == "NO_ROWS_FOR_REQUESTED_TICKER"


def test_stale_data_is_flagged(tmp_path):
    csv_path = _write_market_csv(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
        stale_reference_date="2026-02-01",
    )

    assert result["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["coverage"]["stale_ticker_count"] == 2
    assert "STALE_DATA" in result["coverage"]["warnings"]


def test_optional_open_high_low_missing_are_preserved(tmp_path):
    rows = _market_rows()
    for row in rows:
        row.pop("open")
        row.pop("high")
        row.pop("low")
    csv_path = _write_market_csv(tmp_path, rows)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )
    raw = pd.read_csv(result["raw_output_path"])

    assert result["status"] == "SUCCESS"
    assert raw["open"].isna().all()
    assert raw["high"].isna().all()
    assert raw["low"].isna().all()


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


def test_real_unavailable_returns_status_manifest_and_ticker_log(tmp_path):
    result = _run_ingestion(
        tmp_path,
        "real_vnstock_optional",
        requested_tickers=["MOCK1", "MOCK2"],
    )
    ticker_log = pd.read_csv(result["ticker_log_path"])

    assert result["status"] == REAL_SOURCE_UNAVAILABLE
    assert result["errors"] == [REAL_SOURCE_UNAVAILABLE]
    assert result["raw_output_path"] == ""
    assert Path(result["manifest_path"]).exists()
    assert set(ticker_log["failure_reason"]) == {REAL_SOURCE_UNAVAILABLE}


def test_manifest_and_coverage_report_are_written(tmp_path):
    csv_path = _write_market_csv(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
        run_id="run_market_manifest",
    )

    with open(result["manifest_path"], encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)
    with open(result["coverage_report_path"], encoding="utf-8") as coverage_file:
        coverage = json.load(coverage_file)

    assert manifest["run_id"] == "run_market_manifest"
    assert manifest["dataset_name"] == "market_price"
    assert manifest["row_count"] == 2
    assert coverage["ticker_count_requested"] == 2


def test_coverage_report_has_required_fields(tmp_path):
    csv_path = _write_market_csv(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )

    required_fields = {
        "ticker_count_requested",
        "ticker_count_success",
        "ticker_count_failed",
        "row_count",
        "min_date",
        "max_date",
        "missing_close_count",
        "missing_volume_count",
        "missing_trading_value_count",
        "stale_ticker_count",
        "duplicate_row_count",
        "warnings",
    }
    assert required_fields.issubset(result["coverage"])


def test_raw_outputs_have_no_buy_sell_or_target_price_fields(tmp_path):
    csv_path = _write_market_csv(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        input_path=csv_path,
        requested_tickers=["MOCK1", "MOCK2"],
    )
    raw = pd.read_csv(result["raw_output_path"])

    assert not has_prohibited_recommendation_columns(raw)

