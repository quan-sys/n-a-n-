import pandas as pd
import pytest

import src.fetchers.market_price_fetcher as market_price_fetcher
from src.fetchers.base import REQUIRED_FETCH_COLUMNS
from src.fetchers.market_price_fetcher import (
    REAL_SOURCE_UNAVAILABLE_MESSAGE,
    MarketPriceFetcher,
    RealSourceUnavailableError,
    validate_market_price_output,
)


def test_mock_mode_returns_dataframe():
    df = MarketPriceFetcher().fetch(["MOCK1"], mode="mock")

    assert isinstance(df, pd.DataFrame)


def test_mock_mode_output_has_standardized_fetcher_columns():
    df = MarketPriceFetcher().fetch(["MOCK1"], mode="mock")

    assert list(df.columns) == REQUIRED_FETCH_COLUMNS


def test_mock_mode_includes_required_market_price_fields():
    df = MarketPriceFetcher().fetch(["MOCK1"], mode="mock")

    assert {"close", "volume", "trading_value"}.issubset(set(df["field"]))


def test_mock_mode_uses_mock_source():
    df = MarketPriceFetcher().fetch(["MOCK1", "MOCK2"], mode="mock")

    assert set(df["source"]) == {"MOCK"}


def test_mock_mode_does_not_pretend_to_be_real_data():
    df = MarketPriceFetcher().fetch(["MOCK1"], mode="mock")

    assert set(df["confidence_raw"]) == {"mock"}
    assert df["notes"].str.contains("mock data only", case=False).all()
    assert df["notes"].str.contains("not real", case=False).all()


def test_output_validates_successfully_through_fetcher_validation():
    fetcher = MarketPriceFetcher()
    df = fetcher.fetch(["MOCK1"], mode="mock")

    result = fetcher.validate_output(df)

    assert result["is_valid"] is True
    assert result["missing_columns"] == []
    assert result["warnings"] == []
    assert result["errors"] == []


def test_invalid_mode_raises_clear_error():
    with pytest.raises(ValueError, match="Invalid mode"):
        MarketPriceFetcher().fetch(["MOCK1"], mode="paper")


def test_real_mode_unavailable_raises_clear_error():
    with pytest.raises(RealSourceUnavailableError, match="REAL_SOURCE_UNAVAILABLE"):
        MarketPriceFetcher().fetch(["MOCK1"], mode="real")


def test_real_mode_does_not_generate_fake_values_when_unavailable():
    with pytest.raises(RealSourceUnavailableError) as error_info:
        MarketPriceFetcher().fetch(["MOCK1"], mode="real")

    assert str(error_info.value) == REAL_SOURCE_UNAVAILABLE_MESSAGE


def test_no_buy_sell_recommendation_is_generated():
    df = MarketPriceFetcher().fetch(["MOCK1"], mode="mock")
    output_text = df.to_string().upper()

    assert "BUY" not in output_text
    assert "SELL" not in output_text


def test_no_l0_filtering_or_scoring_is_implemented():
    public_names = {
        name
        for name in dir(market_price_fetcher)
        if not name.startswith("_") and callable(getattr(market_price_fetcher, name))
    }

    assert not any(name.startswith("filter") for name in public_names)
    assert not any(name.startswith("score") for name in public_names)


def test_market_price_validation_rejects_invalid_values():
    df = MarketPriceFetcher().fetch(["MOCK1"], mode="mock")
    invalid_df = df.copy()
    invalid_df.loc[invalid_df["field"] == "close", "value"] = -1

    result = validate_market_price_output(invalid_df)

    assert result["is_valid"] is False
    assert any("close must be positive" in error for error in result["errors"])


def test_market_price_validation_rejects_missing_ticker_or_date():
    df = MarketPriceFetcher().fetch(["MOCK1"], mode="mock")
    invalid_df = df.copy()
    invalid_df.loc[0, "ticker"] = ""
    invalid_df.loc[1, "date"] = None

    result = validate_market_price_output(invalid_df)

    assert result["is_valid"] is False
    assert any("missing ticker" in error for error in result["errors"])
    assert any("missing date" in error for error in result["errors"])


def test_mock_mode_rejects_non_mock_tickers():
    with pytest.raises(ValueError, match="MOCK tickers"):
        MarketPriceFetcher().fetch(["REAL1"], mode="mock")
