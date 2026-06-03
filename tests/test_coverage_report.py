from pathlib import Path

import pandas as pd

from src.ingestion.coverage_report import (
    COVERAGE_REPORT_COLUMNS,
    build_data_coverage_report,
    has_prohibited_recommendation_columns,
    save_data_coverage_report,
)


def test_coverage_report_generation_from_sample_data(tmp_path):
    datasets = {
        "market_price": pd.DataFrame(
            [
                {
                    "ticker": "MOCK1",
                    "date": "2026-01-01",
                    "close": 100,
                    "volume": 1000,
                    "trading_value": 100000,
                    "quality_status": "VALID_DATA",
                    "final_confidence": "high",
                    "manual_review_required": False,
                },
                {
                    "ticker": "MOCK2",
                    "date": "2026-01-02",
                    "close": None,
                    "volume": 2000,
                    "trading_value": 200000,
                    "quality_status": "MISSING_DATA",
                    "quality_warnings": ["MISSING_CLOSE"],
                    "final_confidence": "low",
                    "manual_review_required": True,
                },
            ]
        )
    }

    report = build_data_coverage_report(datasets)
    row = report.iloc[0]

    assert list(report.columns) == COVERAGE_REPORT_COLUMNS
    assert row["dataset_name"] == "market_price"
    assert row["row_count"] == 2
    assert row["ticker_count"] == 2
    assert row["period_count"] == 2
    assert row["min_date"] == "2026-01-01"
    assert row["max_date"] == "2026-01-02"
    assert row["missing_required_field_count"] == 1
    assert row["low_confidence_count"] == 1
    assert row["manual_review_count"] == 1
    assert row["coverage_status"] == "MISSING_DATA"


def test_coverage_report_records_missing_dataset():
    report = build_data_coverage_report(
        {"universe": None},
        dataset_order=["universe"],
    )
    row = report.iloc[0]

    assert row["dataset_name"] == "universe"
    assert row["coverage_status"] == "MISSING_DATASET"
    assert "not treated as clean" in row["notes"]


def test_coverage_report_output_can_be_saved(tmp_path):
    report = build_data_coverage_report(
        {
            "company_profile": pd.DataFrame(
                [
                    {
                        "ticker": "MOCK1",
                        "company_name": "Mock Company",
                        "exchange": "HOSE",
                        "industry_raw": "Mock steel industry",
                        "business_description": "Mock/sample steel profile only",
                        "last_updated": "2026-01-01",
                    }
                ]
            )
        }
    )

    path = save_data_coverage_report(report, tmp_path)

    assert Path(path).name == "data_coverage_report.csv"
    assert Path(path).exists()


def test_coverage_report_has_no_buy_sell_or_target_price_fields():
    report = build_data_coverage_report(
        {
            "universe": pd.DataFrame(
                [
                    {
                        "ticker": "MOCK1",
                        "exchange": "HOSE",
                        "company_name": "Mock Company",
                        "listing_status": "LISTED",
                    }
                ]
            )
        }
    )

    assert not has_prohibited_recommendation_columns(report)
