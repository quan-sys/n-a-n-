from pathlib import Path

import pandas as pd

import src.features.raw_to_clean as raw_to_clean
from src.features.raw_to_clean import (
    CLEAN_DATASET_COLUMNS,
    clean_company_profile_data,
    clean_disclosure_status_data,
    clean_financial_statement_data,
    clean_market_price_data,
    clean_universe_data,
    pivot_long_fetch_to_clean_wide,
    save_clean_dataset,
)


def _standard_rows(
    dataset_name,
    ticker,
    date,
    values,
    source="MOCK",
    source_url="mock://source",
    fetch_time="2026-01-01T00:00:00Z",
    confidence_raw="mock",
    notes="mock data only; not production data",
):
    return [
        {
            "dataset_name": dataset_name,
            "ticker": ticker,
            "date": date,
            "field": field,
            "value": value,
            "source": source,
            "source_url": source_url,
            "fetch_time": fetch_time,
            "confidence_raw": confidence_raw,
            "notes": notes,
        }
        for field, value in values.items()
    ]


def test_long_format_market_price_pivots_to_clean_wide_format():
    df = pd.DataFrame(
        _standard_rows(
            "market_price",
            "MOCK1",
            "2026-01-01",
            {"close": 1000, "volume": 100, "trading_value": 100000},
        )
    )

    clean = clean_market_price_data(df)

    assert list(clean.columns) == CLEAN_DATASET_COLUMNS["market_price"]
    assert len(clean) == 1
    assert clean.loc[0, "ticker"] == "MOCK1"
    assert clean.loc[0, "date"] == "2026-01-01"
    assert clean.loc[0, "close"] == 1000
    assert clean.loc[0, "volume"] == 100
    assert clean.loc[0, "trading_value"] == 100000
    assert clean.attrs["cleaning_result"]["is_valid"] is True


def test_long_format_universe_pivots_to_clean_wide_format():
    df = pd.DataFrame(
        _standard_rows(
            "universe",
            "MOCK1",
            "2026-01-01",
            {
                "exchange": "MOCK_EXCHANGE",
                "company_name": "Mock Company",
                "listing_status": "MOCK_LISTED",
                "data_source": "MOCK",
                "last_updated": "2026-01-01",
            },
        )
    )

    clean = clean_universe_data(df)

    assert list(clean.columns) == CLEAN_DATASET_COLUMNS["universe"]
    assert clean.loc[0, "ticker"] == "MOCK1"
    assert clean.loc[0, "exchange"] == "MOCK_EXCHANGE"
    assert clean.loc[0, "company_name"] == "Mock Company"
    assert clean.loc[0, "listing_status"] == "MOCK_LISTED"
    assert clean.loc[0, "data_source"] == "MOCK"
    assert clean.loc[0, "last_updated"] == "2026-01-01"


def test_long_format_company_profile_pivots_to_clean_wide_format():
    df = pd.DataFrame(
        _standard_rows(
            "company_profile",
            "MOCK1",
            "2026-01-01",
            {
                "company_name": "Mock Company",
                "exchange": "MOCK_EXCHANGE",
                "industry_raw": "MOCK_INDUSTRY",
                "business_description": "Mock company profile only",
                "last_updated": "2026-01-01",
            },
        )
    )

    clean = clean_company_profile_data(df)

    assert list(clean.columns) == CLEAN_DATASET_COLUMNS["company_profile"]
    assert clean.loc[0, "ticker"] == "MOCK1"
    assert clean.loc[0, "company_name"] == "Mock Company"
    assert clean.loc[0, "industry_raw"] == "MOCK_INDUSTRY"
    assert clean.loc[0, "business_description"] == "Mock company profile only"


def test_long_format_financial_statement_pivots_to_clean_wide_format():
    values = {
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
        "long_term_debt": 300,
        "operating_cash_flow": 150,
        "inventory": 250,
    }
    df = pd.DataFrame(
        _standard_rows("financial_statement_summary", "MOCK1", "2026Q1", values)
    )

    clean = clean_financial_statement_data(df)

    assert list(clean.columns) == CLEAN_DATASET_COLUMNS[
        "financial_statement_summary"
    ]
    assert clean.loc[0, "ticker"] == "MOCK1"
    assert clean.loc[0, "period"] == "2026Q1"
    assert clean.loc[0, "revenue"] == 1000
    assert clean.loc[0, "equity"] == 3000
    assert clean.attrs["cleaning_result"]["is_valid"] is True


def test_long_format_disclosure_status_pivots_to_clean_wide_format():
    df = pd.DataFrame(
        _standard_rows(
            "disclosure_status",
            "MOCK1",
            "2026-01-01",
            {
                "event_type": "AUDIT_WARNING",
                "severity": "HIGH",
                "source_url": "mock://disclosure",
                "notes": "mock disclosure status only",
            },
        )
    )

    clean = clean_disclosure_status_data(df)

    assert list(clean.columns) == CLEAN_DATASET_COLUMNS["disclosure_status"]
    assert clean.loc[0, "ticker"] == "MOCK1"
    assert clean.loc[0, "event_type"] == "AUDIT_WARNING"
    assert clean.loc[0, "severity"] == "HIGH"
    assert clean.loc[0, "source_url"] == "mock://disclosure"
    assert clean.loc[0, "notes"] == "mock disclosure status only"


def test_source_metadata_is_preserved():
    df = pd.DataFrame(
        _standard_rows(
            "market_price",
            "MOCK1",
            "2026-01-01",
            {"close": 1000, "volume": 100, "trading_value": 100000},
            source="MOCK_VENDOR",
            source_url="mock://market-price",
            fetch_time="2026-01-02T03:04:05Z",
            confidence_raw="medium",
            notes="mock vendor metadata",
        )
    )

    clean = pivot_long_fetch_to_clean_wide(df, "market_price")

    assert clean.loc[0, "source"] == "MOCK_VENDOR"
    assert clean.loc[0, "source_url"] == "mock://market-price"
    assert clean.loc[0, "fetch_time"] == "2026-01-02T03:04:05Z"
    assert clean.loc[0, "confidence_raw"] == "medium"
    assert clean.loc[0, "notes"] == "mock vendor metadata"


def test_missing_required_fields_generate_warnings_without_fake_values():
    df = pd.DataFrame(
        _standard_rows(
            "market_price",
            "MOCK1",
            "2026-01-01",
            {"close": 1000, "volume": 100},
        )
    )

    clean = clean_market_price_data(df)
    result = clean.attrs["cleaning_result"]

    assert "trading_value" in clean.columns
    assert pd.isna(clean.loc[0, "trading_value"])
    assert result["is_valid"] is False
    assert "trading_value" in result["missing_columns"]
    assert any("missing required clean field" in warning for warning in result["warnings"])


def test_duplicate_records_keep_latest_fetch_time_and_warn():
    rows = _standard_rows(
        "market_price",
        "MOCK1",
        "2026-01-01",
        {"close": 1000, "volume": 100, "trading_value": 100000},
        fetch_time="2026-01-01T00:00:00Z",
    )
    rows.append(
        {
            "dataset_name": "market_price",
            "ticker": "MOCK1",
            "date": "2026-01-01",
            "field": "close",
            "value": 1100,
            "source": "MOCK",
            "source_url": "mock://source",
            "fetch_time": "2026-01-02T00:00:00Z",
            "confidence_raw": "mock",
            "notes": "updated mock close",
        }
    )
    df = pd.DataFrame(rows)

    clean = clean_market_price_data(df)
    result = clean.attrs["cleaning_result"]

    assert clean.loc[0, "close"] == 1100
    assert clean.loc[0, "fetch_time"] == "2026-01-02T00:00:00Z"
    assert result["duplicate_records"] == 2
    assert any("Duplicate ticker/date/field/source" in warning for warning in result["warnings"])


def test_save_clean_dataset_writes_file_to_temporary_directory(tmp_path):
    df = pd.DataFrame(
        _standard_rows(
            "market_price",
            "MOCK1",
            "2026-01-01",
            {"close": 1000, "volume": 100, "trading_value": 100000},
        )
    )
    clean = clean_market_price_data(df)

    output_path = save_clean_dataset(
        clean, "market_price", output_dir=str(tmp_path)
    )

    assert Path(output_path).exists()
    assert Path(output_path).name == "market_price.csv"
    saved = pd.read_csv(output_path)
    assert list(saved.columns) == CLEAN_DATASET_COLUMNS["market_price"]


def test_no_l0_filtering_sector_classification_or_valuation_scoring_is_implemented():
    public_names = {
        name
        for name in dir(raw_to_clean)
        if not name.startswith("_") and callable(getattr(raw_to_clean, name))
    }

    assert not any(name.startswith("filter") for name in public_names)
    assert not any(name.startswith("classify") for name in public_names)
    assert not any(name.startswith("score") for name in public_names)
    assert not any(name.startswith("value") for name in public_names)
