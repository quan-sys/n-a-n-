import pandas as pd
import pytest

from src.fetchers.base import REQUIRED_FETCH_COLUMNS
from src.fetchers.mock_fetcher import MockFetcher
from src.quality.schema_validation import load_schema


BASE_SCHEMA_PATH = "config/base_data_schema.yaml"


def test_mock_fetcher_returns_dataframe():
    df = MockFetcher("universe").fetch()

    assert isinstance(df, pd.DataFrame)


def test_mock_fetcher_output_contains_all_required_fetch_columns():
    df = MockFetcher("universe").fetch()

    assert list(df.columns) == REQUIRED_FETCH_COLUMNS


def test_validate_output_returns_valid_for_valid_mock_output():
    fetcher = MockFetcher("market_price")
    df = fetcher.fetch()

    result = fetcher.validate_output(df)

    assert result["is_valid"] is True
    assert result["missing_columns"] == []
    assert result["warnings"] == []
    assert result["errors"] == []


def test_missing_required_fetch_column_returns_invalid_result():
    fetcher = MockFetcher("universe")
    df = fetcher.fetch().drop(columns=["source_url"])

    result = fetcher.validate_output(df)

    assert result["is_valid"] is False
    assert result["missing_columns"] == ["source_url"]
    assert result["warnings"] == ["Missing required fetch columns: source_url"]
    assert result["errors"] == []


def test_mock_fetcher_supports_all_base_schema_datasets():
    schema = load_schema(BASE_SCHEMA_PATH)

    for dataset_name in schema["datasets"]:
        df = MockFetcher(dataset_name).fetch()
        assert isinstance(df, pd.DataFrame)
        assert set(df["dataset_name"]) == {dataset_name}


def test_unknown_dataset_name_raises_clear_error():
    with pytest.raises(ValueError, match="Unsupported mock dataset"):
        MockFetcher("unknown_dataset")


def test_mock_data_uses_mock_source():
    df = MockFetcher("financial_statement_summary").fetch()

    assert set(df["source"]) == {"MOCK"}
    assert df["notes"].str.contains("mock data only", case=False).all()
