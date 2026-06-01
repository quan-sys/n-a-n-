import pandas as pd

import src.universe.build_universe as build_universe_module
from src.universe.build_universe import (
    OUTPUT_COLUMNS,
    build_clean_universe,
    load_universe_rules,
)


RULES_PATH = "config/universe_rules.yaml"


def _universe_df(**overrides):
    row = {
        "ticker": "MOCK1",
        "exchange": "HOSE",
        "company_name": "Mock One",
        "listing_status": "ACTIVE",
        "data_source": "MOCK",
        "last_updated": "2026-01-01",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _profile_df(ticker="MOCK1"):
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "company_name": "Mock One",
                "exchange": "HOSE",
                "industry_raw": "MOCK_INDUSTRY",
                "business_description": "Mock profile only",
                "source": "MOCK",
                "last_updated": "2026-01-01",
            }
        ]
    )


def _market_df(ticker="MOCK1"):
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "date": "2026-01-01",
                "close": 1000,
                "volume": 100,
                "trading_value": 100000,
                "source": "MOCK",
                "fetch_time": "2026-01-01T00:00:00Z",
            }
        ]
    )


def _financial_df(ticker="MOCK1"):
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "period": "2026Q1",
                "revenue": 1000,
                "gross_profit": 100,
                "operating_profit": 80,
                "net_profit": 50,
                "total_assets": 5000,
                "total_liabilities": 2000,
                "equity": 3000,
                "cash": 500,
                "short_term_debt": 100,
                "long_term_debt": 200,
                "operating_cash_flow": 75,
                "inventory": 250,
                "source": "MOCK",
                "fetch_time": "2026-01-01T00:00:00Z",
            }
        ]
    )


def _disclosure_df(ticker="MOCK1"):
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "date": "2026-01-01",
                "event_type": "MOCK_DISCLOSURE",
                "severity": "mock_low",
                "source": "MOCK",
                "source_url": "",
                "notes": "mock disclosure only",
            }
        ]
    )


def _build(**overrides):
    rules = load_universe_rules(RULES_PATH)
    params = {
        "universe_df": _universe_df(),
        "company_profile_df": _profile_df(),
        "market_price_df": _market_df(),
        "financial_statement_df": _financial_df(),
        "disclosure_df": None,
        "rules": rules,
    }
    params.update(overrides)
    return build_clean_universe(**params)


def test_valid_mock_stock_gets_pass_universe():
    result = _build()
    row = result.iloc[0]

    assert row["ticker"] == "MOCK1"
    assert row["universe_status"] == "PASS_UNIVERSE"
    assert row["data_sanity_status"] == "VALID_DATA"
    assert row["universe_warnings"] == []
    assert bool(row["is_active"]) is True


def test_missing_company_profile_creates_manual_review_warning():
    result = _build(company_profile_df=None)
    row = result.iloc[0]

    assert row["universe_status"] == "MANUAL_REVIEW"
    assert row["data_sanity_status"] == "MISSING_DATA"
    assert "MISSING_PROFILE" in row["universe_warnings"]
    assert bool(row["manual_review_required"]) is True


def test_missing_market_data_creates_manual_review_warning():
    result = _build(market_price_df=None)
    row = result.iloc[0]

    assert row["universe_status"] == "MANUAL_REVIEW"
    assert row["data_sanity_status"] == "MISSING_DATA"
    assert "MISSING_MARKET_DATA" in row["universe_warnings"]


def test_missing_financial_data_creates_manual_review_warning():
    result = _build(financial_statement_df=None)
    row = result.iloc[0]

    assert row["universe_status"] == "MANUAL_REVIEW"
    assert row["data_sanity_status"] == "MISSING_DATA"
    assert "MISSING_FINANCIAL_DATA" in row["universe_warnings"]


def test_exchange_outside_allowed_exchanges_rejects_universe():
    result = _build(universe_df=_universe_df(exchange="MOCK_EXCHANGE"))
    row = result.iloc[0]

    assert row["universe_status"] == "REJECT_UNIVERSE"
    assert row["data_sanity_status"] == "DATA_ERROR"
    assert "EXCHANGE_NOT_ALLOWED" in row["universe_warnings"]


def test_unknown_listing_status_creates_warning():
    result = _build(universe_df=_universe_df(listing_status="UNKNOWN"))
    row = result.iloc[0]

    assert row["universe_status"] == "WATCH_UNIVERSE"
    assert row["data_sanity_status"] == "MANUAL_REVIEW"
    assert "UNKNOWN_LISTING_STATUS" in row["universe_warnings"]


def test_missing_ticker_rejects_universe():
    result = _build(universe_df=_universe_df(ticker=""))
    row = result.iloc[0]

    assert row["universe_status"] == "REJECT_UNIVERSE"
    assert "MISSING_TICKER" in row["universe_warnings"]
    assert bool(row["manual_review_required"]) is True


def test_disclosure_records_create_warning_without_rejecting():
    result = _build(disclosure_df=_disclosure_df())
    row = result.iloc[0]

    assert row["universe_status"] == "PASS_UNIVERSE"
    assert "HAS_DISCLOSURE_RECORDS" in row["universe_warnings"]
    assert bool(row["has_disclosure_data"]) is True


def test_quality_output_creates_manual_review_without_l0_rejecting():
    market_df = _market_df()
    market_df["quality_status"] = ["STALE_DATA"]
    market_df["quality_warnings"] = [["STALE_DATA"]]
    market_df["quality_errors"] = [[]]
    market_df["final_confidence"] = ["low"]
    market_df["manual_review_required"] = [True]

    result = _build(market_price_df=market_df)
    row = result.iloc[0]

    assert row["universe_status"] == "MANUAL_REVIEW"
    assert row["data_sanity_status"] == "MANUAL_REVIEW"
    assert "MARKET_DATA_QUALITY_REVIEW" in row["universe_warnings"]


def test_output_contains_all_required_columns():
    result = _build()

    assert list(result.columns) == OUTPUT_COLUMNS


def test_no_buy_sell_recommendation_is_generated():
    result = _build()
    output_text = result.to_string().upper()

    assert "BUY" not in output_text
    assert "SELL" not in output_text


def test_no_l0_filtering_sector_classification_or_valuation_scoring_is_implemented():
    public_names = {
        name
        for name in dir(build_universe_module)
        if not name.startswith("_") and callable(getattr(build_universe_module, name))
    }

    assert not any(name.startswith("filter") for name in public_names)
    assert not any(name.startswith("classify") for name in public_names)
    assert not any(name.startswith("score") for name in public_names)
    assert not any(name.startswith("value") for name in public_names)


def test_mock_data_uses_fake_tickers():
    result = _build(
        universe_df=pd.concat(
            [
                _universe_df(ticker="MOCK1"),
                _universe_df(ticker="MOCK2"),
                _universe_df(ticker="MOCK3"),
            ],
            ignore_index=True,
        ),
        company_profile_df=pd.concat(
            [_profile_df("MOCK1"), _profile_df("MOCK2"), _profile_df("MOCK3")],
            ignore_index=True,
        ),
        market_price_df=pd.concat(
            [_market_df("MOCK1"), _market_df("MOCK2"), _market_df("MOCK3")],
            ignore_index=True,
        ),
        financial_statement_df=pd.concat(
            [
                _financial_df("MOCK1"),
                _financial_df("MOCK2"),
                _financial_df("MOCK3"),
            ],
            ignore_index=True,
        ),
    )

    assert set(result["ticker"]) == {"MOCK1", "MOCK2", "MOCK3"}
    assert result["ticker"].str.startswith("MOCK").all()
