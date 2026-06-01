from pathlib import Path

import pandas as pd

from src.quality.schema_validation import load_schema, validate_dataframe


SCHEMA_PATH = Path("config/base_data_schema.yaml")


def test_valid_mock_universe_data_passes():
    schema = load_schema(SCHEMA_PATH)
    df = pd.DataFrame(
        [
            {
                "ticker": "MOCK1",
                "exchange": "MOCK_EXCHANGE",
                "company_name": "Mock Company",
                "listing_status": "LISTED",
                "data_source": "mock_fixture",
                "last_updated": "2026-01-01",
            }
        ]
    )

    result = validate_dataframe(df, "universe", schema)

    assert result["is_valid"] is True
    assert result["missing_columns"] == []
    assert result["warnings"] == []
    assert result["errors"] == []


def test_missing_required_column_generates_warning_and_invalid_result():
    schema = load_schema(SCHEMA_PATH)
    df = pd.DataFrame(
        [
            {
                "ticker": "MOCK1",
                "company_name": "Mock Company",
                "listing_status": "LISTED",
                "data_source": "mock_fixture",
                "last_updated": "2026-01-01",
            }
        ]
    )

    result = validate_dataframe(df, "universe", schema)

    assert result["is_valid"] is False
    assert result["missing_columns"] == ["exchange"]
    assert result["warnings"] == ["Missing required columns: exchange"]
    assert result["errors"] == []


def test_unknown_dataset_name_generates_error():
    schema = load_schema(SCHEMA_PATH)
    df = pd.DataFrame([{"ticker": "MOCK1"}])

    result = validate_dataframe(df, "unknown_dataset", schema)

    assert result["is_valid"] is False
    assert result["missing_columns"] == []
    assert result["extra_columns"] == []
    assert result["warnings"] == []
    assert result["errors"] == ["Unknown dataset: unknown_dataset"]


def test_extra_columns_are_allowed_and_listed():
    schema = load_schema(SCHEMA_PATH)
    df = pd.DataFrame(
        [
            {
                "ticker": "MOCK1",
                "exchange": "MOCK_EXCHANGE",
                "company_name": "Mock Company",
                "listing_status": "LISTED",
                "data_source": "mock_fixture",
                "last_updated": "2026-01-01",
                "temporary_note": "allowed mock-only extra field",
            }
        ]
    )

    result = validate_dataframe(df, "universe", schema)

    assert result["is_valid"] is True
    assert result["missing_columns"] == []
    assert result["extra_columns"] == ["temporary_note"]
    assert result["warnings"] == []
    assert result["errors"] == []


def test_all_base_datasets_exist_in_schema():
    schema = load_schema(SCHEMA_PATH)

    assert set(schema["datasets"]) == {
        "universe",
        "market_price",
        "company_profile",
        "financial_statement_summary",
        "disclosure_status",
    }
