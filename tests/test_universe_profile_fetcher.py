import pandas as pd
import pytest

import src.fetchers.universe_profile_fetcher as universe_profile_fetcher
from src.fetchers.base import REQUIRED_FETCH_COLUMNS
from src.fetchers.universe_profile_fetcher import (
    REAL_SOURCE_UNAVAILABLE_MESSAGE,
    UniverseProfileFetcher,
    RealSourceUnavailableError,
    validate_universe_profile_output,
)


def test_mock_universe_fetch_returns_dataframe():
    df = UniverseProfileFetcher().fetch_universe(mode="mock")

    assert isinstance(df, pd.DataFrame)


def test_mock_company_profile_fetch_returns_dataframe():
    df = UniverseProfileFetcher().fetch_company_profile(mode="mock")

    assert isinstance(df, pd.DataFrame)


def test_mock_output_has_standardized_fetcher_columns():
    df = UniverseProfileFetcher().fetch_universe(mode="mock")

    assert list(df.columns) == REQUIRED_FETCH_COLUMNS


def test_mock_universe_includes_required_fields():
    df = UniverseProfileFetcher().fetch_universe(mode="mock")

    assert {"ticker", "exchange", "company_name", "listing_status"}.issubset(
        set(df["field"])
    )


def test_mock_company_profile_includes_required_fields():
    df = UniverseProfileFetcher().fetch_company_profile(mode="mock")

    assert {
        "ticker",
        "company_name",
        "exchange",
        "industry_raw",
        "business_description",
    }.issubset(set(df["field"]))


def test_mock_mode_uses_mock_source():
    fetcher = UniverseProfileFetcher()
    universe = fetcher.fetch_universe(mode="mock")
    profile = fetcher.fetch_company_profile(mode="mock")

    assert set(universe["source"]) == {"MOCK"}
    assert set(profile["source"]) == {"MOCK"}


def test_manual_csv_universe_mode_normalizes_wide_csv(tmp_path):
    csv_path = tmp_path / "manual_universe.csv"
    pd.DataFrame(
        [
            {
                "ticker": "MANUAL1",
                "exchange": "HOSE",
                "company_name": "Manual One",
                "listing_status": "LISTED",
                "data_source": "USER_FILE",
                "last_updated": "2026-01-01",
            }
        ]
    ).to_csv(csv_path, index=False)

    df = UniverseProfileFetcher().fetch_universe(
        mode="manual_csv", manual_file_path=str(csv_path)
    )

    assert list(df.columns) == REQUIRED_FETCH_COLUMNS
    assert set(df["dataset_name"]) == {"universe"}
    assert {"ticker", "exchange", "company_name", "listing_status"}.issubset(
        set(df["field"])
    )
    assert set(df["source"]) == {"USER_FILE"}


def test_manual_csv_company_profile_mode_normalizes_wide_csv(tmp_path):
    csv_path = tmp_path / "manual_profile.csv"
    pd.DataFrame(
        [
            {
                "ticker": "MANUAL1",
                "company_name": "Manual One",
                "exchange": "HOSE",
                "industry_raw": "Manual Industry",
                "business_description": "Manual user-provided description",
                "source": "USER_FILE",
                "last_updated": "2026-01-01",
            }
        ]
    ).to_csv(csv_path, index=False)

    df = UniverseProfileFetcher().fetch_company_profile(
        mode="manual_csv", manual_file_path=str(csv_path)
    )

    assert list(df.columns) == REQUIRED_FETCH_COLUMNS
    assert set(df["dataset_name"]) == {"company_profile"}
    assert {
        "ticker",
        "company_name",
        "exchange",
        "industry_raw",
        "business_description",
    }.issubset(set(df["field"]))
    assert set(df["source"]) == {"USER_FILE"}


def test_manual_csv_missing_expected_columns_creates_validation_warnings(tmp_path):
    csv_path = tmp_path / "manual_universe_missing.csv"
    pd.DataFrame(
        [
            {
                "ticker": "MANUAL1",
                "company_name": "Manual One",
                "data_source": "USER_FILE",
            }
        ]
    ).to_csv(csv_path, index=False)

    df = UniverseProfileFetcher().fetch_universe(
        mode="manual_csv", manual_file_path=str(csv_path)
    )
    result = validate_universe_profile_output(df)

    assert result["is_valid"] is True
    assert any("missing expected fields" in warning for warning in result["warnings"])


def test_manual_csv_missing_source_uses_unknown_source(tmp_path):
    csv_path = tmp_path / "manual_profile_unknown_source.csv"
    pd.DataFrame(
        [
            {
                "ticker": "MANUAL1",
                "company_name": "Manual One",
                "exchange": "HOSE",
                "industry_raw": "Manual Industry",
                "business_description": "Manual description",
                "last_updated": "2026-01-01",
            }
        ]
    ).to_csv(csv_path, index=False)

    df = UniverseProfileFetcher().fetch_company_profile(
        mode="manual_csv", manual_file_path=str(csv_path)
    )

    assert set(df["source"]) == {"MANUAL_CSV_UNKNOWN_SOURCE"}
    assert set(df["confidence_raw"]) == {"medium"}


def test_real_mode_unavailable_raises_clear_error():
    with pytest.raises(RealSourceUnavailableError, match="REAL_SOURCE_UNAVAILABLE"):
        UniverseProfileFetcher().fetch_universe(mode="real")


def test_real_mode_does_not_generate_fake_values_when_unavailable():
    with pytest.raises(RealSourceUnavailableError) as error_info:
        UniverseProfileFetcher().fetch_company_profile(mode="real")

    assert str(error_info.value) == REAL_SOURCE_UNAVAILABLE_MESSAGE


def test_invalid_mode_raises_clear_error():
    with pytest.raises(ValueError, match="Invalid mode"):
        UniverseProfileFetcher().fetch_universe(mode="paper")


def test_output_validates_successfully_through_fetcher_validation():
    fetcher = UniverseProfileFetcher()
    df = fetcher.fetch_company_profile(mode="mock")

    result = fetcher.validate_output(df)

    assert result["is_valid"] is True
    assert result["missing_columns"] == []
    assert result["warnings"] == []
    assert result["errors"] == []


def test_base_dispatch_fetches_known_datasets():
    fetcher = UniverseProfileFetcher()

    universe = fetcher.fetch(dataset_name="universe", mode="mock")
    profile = fetcher.fetch(dataset_name="company_profile", mode="mock")

    assert set(universe["dataset_name"]) == {"universe"}
    assert set(profile["dataset_name"]) == {"company_profile"}


def test_validation_rejects_missing_ticker_field_source_or_fetch_time():
    df = UniverseProfileFetcher().fetch_universe(mode="mock")
    invalid_df = df.copy()
    invalid_df.loc[0, "ticker"] = ""
    invalid_df.loc[1, "field"] = ""
    invalid_df.loc[2, "source"] = ""
    invalid_df.loc[3, "fetch_time"] = ""

    result = validate_universe_profile_output(invalid_df)

    assert result["is_valid"] is False
    assert any("missing ticker" in error for error in result["errors"])
    assert any("missing field" in error for error in result["errors"])
    assert any("missing source" in error for error in result["errors"])
    assert any("missing fetch_time" in error for error in result["errors"])


def test_no_l0_filtering_or_sector_classification_is_implemented():
    public_names = {
        name
        for name in dir(universe_profile_fetcher)
        if not name.startswith("_") and callable(getattr(universe_profile_fetcher, name))
    }

    assert not any(name.startswith("filter") for name in public_names)
    assert not any(name.startswith("classify") for name in public_names)
    assert not any(name.startswith("score") for name in public_names)


def test_no_buy_sell_recommendation_is_generated():
    df = UniverseProfileFetcher().fetch_company_profile(mode="mock")
    output_text = df.to_string().upper()

    assert "BUY" not in output_text
    assert "SELL" not in output_text
