from pathlib import Path

import pandas as pd

from src.ingestion.pipeline_dry_run import (
    DRY_RUN_STAGES,
    DRY_RUN_SUMMARY_FIELDS,
    has_prohibited_recommendation_columns,
    run_pipeline_dry_run,
)


FETCH_TIME = "2026-01-01T00:00:00Z"


def _sample_raw_datasets(*, disclosure_rows=None, include_financial=True):
    rows = {
        "universe": pd.DataFrame(
            [
                {
                    "ticker": "MOCK1",
                    "exchange": "HOSE",
                    "company_name": "Mock Steel One",
                    "listing_status": "LISTED",
                    "data_source": "manual_sample",
                    "last_updated": "2026-01-01",
                    "source": "manual_sample",
                    "source_url": "mock://universe/MOCK1",
                    "fetch_time": FETCH_TIME,
                    "confidence_raw": "sample",
                    "notes": "mock/sample universe row only",
                },
                {
                    "ticker": "MOCK2",
                    "exchange": "HNX",
                    "company_name": "Mock Steel Two",
                    "listing_status": "LISTED",
                    "data_source": "manual_sample",
                    "last_updated": "2026-01-01",
                    "source": "manual_sample",
                    "source_url": "mock://universe/MOCK2",
                    "fetch_time": FETCH_TIME,
                    "confidence_raw": "sample",
                    "notes": "mock/sample universe row only",
                },
            ]
        ),
        "company_profile": pd.DataFrame(
            [
                {
                    "ticker": "MOCK1",
                    "company_name": "Mock Steel One",
                    "exchange": "HOSE",
                    "industry_raw": "Mock integrated steel",
                    "business_description": "Mock/sample integrated steel business only",
                    "source": "manual_sample",
                    "source_url": "mock://company_profile/MOCK1",
                    "last_updated": "2026-01-01",
                    "fetch_time": FETCH_TIME,
                    "confidence_raw": "sample",
                    "notes": "mock/sample profile row only",
                },
                {
                    "ticker": "MOCK2",
                    "company_name": "Mock Steel Two",
                    "exchange": "HNX",
                    "industry_raw": "Mock steel",
                    "business_description": "Mock/sample steel sheet business only",
                    "source": "manual_sample",
                    "source_url": "mock://company_profile/MOCK2",
                    "last_updated": "2026-01-01",
                    "fetch_time": FETCH_TIME,
                    "confidence_raw": "sample",
                    "notes": "mock/sample profile row only",
                },
            ]
        ),
        "market_price": pd.DataFrame(
            [
                {
                    "ticker": "MOCK1",
                    "date": "2026-01-01",
                    "close": 100,
                    "volume": 100000,
                    "trading_value": 5000000000,
                    "source": "manual_sample",
                    "source_url": "mock://market_price/MOCK1",
                    "fetch_time": FETCH_TIME,
                    "confidence_raw": "sample",
                    "notes": "mock/sample market row only",
                },
                {
                    "ticker": "MOCK2",
                    "date": "2026-01-01",
                    "close": 200,
                    "volume": 120000,
                    "trading_value": 6000000000,
                    "source": "manual_sample",
                    "source_url": "mock://market_price/MOCK2",
                    "fetch_time": FETCH_TIME,
                    "confidence_raw": "sample",
                    "notes": "mock/sample market row only",
                },
            ]
        ),
        "disclosure_status": pd.DataFrame(
            disclosure_rows
            if disclosure_rows is not None
            else [
                {
                    "ticker": "MOCK1",
                    "event_date": "2026-01-01",
                    "event_type": "OTHER",
                    "severity": "LOW",
                    "title": "Mock disclosure event",
                    "description": "Mock/sample disclosure row only",
                    "source": "manual_sample",
                    "source_url": "mock://disclosure_status/MOCK1",
                    "fetch_time": FETCH_TIME,
                    "confidence_raw": "sample",
                    "notes": "mock/sample disclosure row only",
                }
            ]
        ),
    }
    if include_financial:
        rows["financial_statement_summary"] = pd.DataFrame(
            [
                {
                    "ticker": "MOCK1",
                    "period": "2026Q1",
                    "revenue": 1000,
                    "gross_profit": 300,
                    "operating_profit": 200,
                    "net_profit": 100,
                    "total_assets": 5000,
                    "total_liabilities": 2000,
                    "equity": 3000,
                    "cash": 500,
                    "short_term_debt": 100,
                    "long_term_debt": 200,
                    "operating_cash_flow": 150,
                    "inventory": 250,
                    "source": "manual_sample",
                    "source_url": "mock://financial_statement/MOCK1",
                    "fetch_time": FETCH_TIME,
                    "confidence_raw": "sample",
                    "notes": "mock/sample financial row only",
                },
                {
                    "ticker": "MOCK2",
                    "period": "2026Q1",
                    "revenue": 2000,
                    "gross_profit": 600,
                    "operating_profit": 400,
                    "net_profit": 200,
                    "total_assets": 10000,
                    "total_liabilities": 4000,
                    "equity": 6000,
                    "cash": 1000,
                    "short_term_debt": 200,
                    "long_term_debt": 400,
                    "operating_cash_flow": 300,
                    "inventory": 500,
                    "source": "manual_sample",
                    "source_url": "mock://financial_statement/MOCK2",
                    "fetch_time": FETCH_TIME,
                    "confidence_raw": "sample",
                    "notes": "mock/sample financial row only",
                },
            ]
        )
    return rows


def _run(tmp_path, raw_datasets):
    return run_pipeline_dry_run(
        raw_datasets=raw_datasets,
        reports_dir=tmp_path / "reports",
        run_size="mini",
        run_id="run_pipeline_test",
        reference_date="2026-01-02",
    )


def test_mini_run_works_with_mock_sample_data(tmp_path):
    result = _run(tmp_path, _sample_raw_datasets())

    assert set(DRY_RUN_STAGES).issubset(result["summary"]["module_statuses"])
    assert result["summary"]["run_size"] == "mini"
    assert result["summary"]["input_ticker_count"] == 2
    assert result["summary"]["next_action_recommendation"] == (
        "FIX_INGESTION_BEFORE_STEP_19"
    )
    assert Path(result["report_paths"]["coverage_report"]).exists()
    assert Path(result["report_paths"]["pipeline_dry_run_summary"]).exists()
    assert Path(result["report_paths"]["pipeline_dry_run_errors"]).exists()


def test_dry_run_handles_missing_dataset_gracefully(tmp_path):
    raw_datasets = _sample_raw_datasets(include_financial=False)

    result = _run(tmp_path, raw_datasets)
    financial_row = result["coverage_report"][
        result["coverage_report"]["dataset_name"] == "financial_statement_summary"
    ].iloc[0]

    assert financial_row["coverage_status"] == "MISSING_DATASET"
    assert "MISSING_RAW_DATASET" in set(result["errors"]["error_code"])
    assert result["summary"]["error_count"] >= 1


def test_dry_run_records_module_failure_instead_of_crashing_silently(tmp_path):
    raw_datasets = _sample_raw_datasets()
    raw_datasets["market_price"] = "not a dataframe"

    result = _run(tmp_path, raw_datasets)

    assert "RAW_TO_CLEAN_FAILED" in set(result["errors"]["error_code"])
    assert result["summary"]["module_statuses"]["raw_to_clean"] == "DATA_ERROR"
    assert result["summary"]["error_count"] >= 1


def test_missing_financial_data_creates_insufficient_or_manual_review(tmp_path):
    result = _run(tmp_path, _sample_raw_datasets(include_financial=False))
    issues = set(result["manual_review_queue"]["issue"])

    assert result["summary"]["insufficient_data_count"] > 0
    assert {
        "MISSING_FINANCIAL_DATA",
        "INSUFFICIENT_FINANCIAL_DATA",
    }.intersection(issues)


def test_missing_disclosure_data_is_treated_as_unknown(tmp_path):
    empty_disclosure = [
        {
            "ticker": "",
            "event_date": "",
            "event_type": "",
            "severity": "",
            "title": "",
            "description": "",
            "source": "",
            "source_url": "",
            "fetch_time": "",
            "confidence_raw": "",
            "notes": "",
        }
    ]
    result = _run(
        tmp_path,
        _sample_raw_datasets(disclosure_rows=empty_disclosure),
    )

    disclosure_rows = result["manual_review_queue"][
        result["manual_review_queue"]["module"] == "disclosure_status"
    ]

    assert not disclosure_rows.empty
    assert set(disclosure_rows["issue"]) == {"DISCLOSURE_DATA_UNAVAILABLE"}
    assert set(disclosure_rows["confidence"]) == {"low"}


def test_output_reports_contain_required_summary_fields(tmp_path):
    result = _run(tmp_path, _sample_raw_datasets())

    assert set(DRY_RUN_SUMMARY_FIELDS).issubset(result["summary"])
    summary_text = Path(result["report_paths"]["pipeline_dry_run_summary"]).read_text(
        encoding="utf-8"
    )
    for field in DRY_RUN_SUMMARY_FIELDS:
        assert field in summary_text


def test_no_output_contains_buy_sell_or_target_price_fields(tmp_path):
    result = _run(tmp_path, _sample_raw_datasets())
    output_frames = [
        result["coverage_report"],
        result["manual_review_queue"],
        result["errors"],
        result["sector_cycle"],
        result["indicator_registry"],
    ]

    for frame in output_frames:
        assert not has_prohibited_recommendation_columns(frame)


def test_tests_use_only_mock_tickers_and_sample_financial_values(tmp_path):
    raw_datasets = _sample_raw_datasets()
    result = _run(tmp_path, raw_datasets)

    for dataset in raw_datasets.values():
        if isinstance(dataset, pd.DataFrame) and "ticker" in dataset.columns:
            tickers = {
                ticker
                for ticker in dataset["ticker"].astype(str).str.upper()
                if ticker.strip()
            }
            assert all(ticker.startswith("MOCK") for ticker in tickers)
    assert set(result["selected_tickers"]) == {"MOCK1", "MOCK2"}
