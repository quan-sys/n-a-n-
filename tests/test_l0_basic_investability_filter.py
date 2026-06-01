import pandas as pd

import src.scoring.l0_basic_investability_filter as basic_filter
from src.scoring.l0_basic_investability_filter import (
    BASIC_INVESTABILITY_OUTPUT_COLUMNS,
    load_l0_basic_investability_rules,
    run_l0_basic_investability_filter,
    serialize_list_columns,
)


RULES_PATH = "config/l0_basic_investability_rules.yaml"


def _rules():
    return load_l0_basic_investability_rules(RULES_PATH)


def _universe_df(ticker="MOCK1", **overrides):
    row = {
        "ticker": ticker,
        "exchange": "HOSE",
        "company_name": "Mock Company",
        "listing_status": "ACTIVE",
        "is_active": True,
        "has_basic_profile": True,
        "has_market_data": True,
        "has_financial_data": True,
        "has_disclosure_data": True,
        "universe_status": "PASS_UNIVERSE",
        "universe_warnings": [],
        "data_sanity_status": "VALID_DATA",
        "manual_review_required": False,
        "market_cap": 2_000_000_000_000,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _l0_df(ticker="MOCK1", **overrides):
    row = {
        "ticker": ticker,
        "l0_status": "L0_PASS",
        "l0_score": 100,
        "l0_reject_reasons": [],
        "l0_warning_flags": [],
        "evidence_fields": [],
        "confidence": "high",
        "manual_review_required": False,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _market_df(ticker="MOCK1", **overrides):
    row = {
        "ticker": ticker,
        "date": "2026-05-25",
        "close": 1000,
        "volume": 60000,
        "trading_value": 6_000_000_000,
        "source": "MOCK",
        "fetch_time": "2026-05-25T00:00:00Z",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _profile_df(ticker="MOCK1", **overrides):
    row = {
        "ticker": ticker,
        "company_name": "Mock Company",
        "exchange": "HOSE",
        "industry_raw": "MOCK_INDUSTRY",
        "business_description": "Mock company profile only",
        "source": "MOCK",
        "last_updated": "2026-05-25",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _financial_df(ticker="MOCK1", **overrides):
    row = {
        "ticker": ticker,
        "period": "2026Q1",
        "revenue": 1000,
        "gross_profit": 300,
        "operating_profit": 200,
        "net_profit": 100,
        "total_assets": 5000,
        "total_liabilities": 1500,
        "equity": 3500,
        "cash": 500,
        "short_term_debt": 100,
        "long_term_debt": 300,
        "operating_cash_flow": 150,
        "inventory": 250,
        "source": "MOCK",
        "fetch_time": "2026-05-25T00:00:00Z",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _disclosure_df(ticker="MOCK1", **overrides):
    row = {
        "ticker": ticker,
        "date": "2026-05-25",
        "event_type": "CONFIRMED_CLEAN",
        "severity": "LOW",
        "source": "MOCK",
        "source_url": "",
        "notes": "mock confirmed-clean disclosure status only",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _run(**overrides):
    params = {
        "universe_df": _universe_df(),
        "l0_trash_df": _l0_df(),
        "market_price_df": _market_df(),
        "company_profile_df": _profile_df(),
        "financial_statement_df": _financial_df(),
        "disclosure_df": _disclosure_df(),
        "rules": _rules(),
    }
    params.update(overrides)
    return run_l0_basic_investability_filter(**params)


def test_clean_ticker_passes_as_l0_investable():
    result = _run()
    row = result.iloc[0]

    assert list(result.columns) == BASIC_INVESTABILITY_OUTPUT_COLUMNS
    assert row["l0_basic_status"] == "L0_INVESTABLE"
    assert row["basic_investability_score"] == 100
    assert row["confidence"] == "high"
    assert bool(row["manual_review_required"]) is False


def test_medium_concerns_become_l0_watch_only():
    result = _run(
        universe_df=_universe_df(market_cap=250_000_000_000),
        market_price_df=_market_df(volume=15000, trading_value=500_000_000),
        financial_statement_df=_financial_df(
            total_liabilities=2500,
            equity=1000,
            net_profit=20,
            operating_cash_flow=10,
        ),
        disclosure_df=_disclosure_df(event_type="OTHER", severity="MEDIUM"),
    )
    row = result.iloc[0]

    assert row["l0_basic_status"] == "L0_WATCH_ONLY"
    assert "LOW_LIQUIDITY" in row["warning_flags"]
    assert row["confidence"] == "medium"


def test_ticker_rejected_by_l0_trash_filter_stays_rejected():
    result = _run(
        l0_trash_df=_l0_df(
            l0_status="L0_REJECT",
            l0_reject_reasons=["NEGATIVE_EQUITY"],
            confidence="low",
        )
    )
    row = result.iloc[0]

    assert row["l0_basic_status"] == "L0_REJECT"
    assert row["basic_investability_score"] == 0
    assert row["reject_reasons"] == ["FAILED_L0_TRASH_FILTER"]
    assert row["confidence"] == "low"


def test_missing_market_or_financial_data_is_insufficient_and_low_confidence():
    result = _run(
        market_price_df=None,
        financial_statement_df=None,
        disclosure_df=_disclosure_df(),
    )
    row = result.iloc[0]

    assert row["l0_basic_status"] == "INSUFFICIENT_DATA_FOR_BASIC_INVESTABILITY"
    assert "INSUFFICIENT_MARKET_DATA" in row["reject_reasons"]
    assert "INSUFFICIENT_FINANCIAL_DATA" in row["reject_reasons"]
    assert row["confidence"] == "low"


def test_critical_disclosure_risk_rejects_or_manual_reviews_from_config():
    result = _run(
        disclosure_df=_disclosure_df(
            event_type="TRADING_RESTRICTION", severity="CRITICAL"
        )
    )
    row = result.iloc[0]

    assert row["l0_basic_status"] in {"L0_REJECT", "L0_MANUAL_REVIEW"}
    assert "CRITICAL_DISCLOSURE_RISK" in row["reject_reasons"]
    assert bool(row["manual_review_required"]) is True


def test_unknown_disclosure_status_creates_manual_review_not_silent_pass():
    result = _run(disclosure_df=None)
    row = result.iloc[0]

    assert row["l0_basic_status"] == "L0_MANUAL_REVIEW"
    assert "UNKNOWN_DISCLOSURE_STATUS" in row["warning_flags"]
    assert row["confidence"] == "low"


def test_negative_equity_creates_reject_or_severe_warning():
    result = _run(financial_statement_df=_financial_df(equity=-10))
    row = result.iloc[0]

    assert row["l0_basic_status"] == "L0_REJECT"
    assert "NEGATIVE_EQUITY" in row["reject_reasons"]
    assert row["financial_viability_score"] == 0


def test_weighted_score_calculation_is_deterministic():
    result = _run()
    row = result.iloc[0]

    assert row["liquidity_score"] == 100
    assert row["market_cap_score"] == 100
    assert row["data_coverage_score"] == 100
    assert row["disclosure_risk_score"] == 100
    assert row["financial_viability_score"] == 100
    assert row["basic_investability_score"] == 100


def test_config_loading_works():
    rules = _rules()

    assert rules["component_weights"]["liquidity_score"] == 0.25
    assert rules["score_thresholds"]["investable_min_score"] == 75


def test_no_real_financial_data_is_required():
    result = _run()

    assert set(result["ticker"]) == {"MOCK1"}
    assert result["ticker"].str.startswith("MOCK").all()


def test_safe_serialization_helper_converts_list_columns():
    result = _run(disclosure_df=None)
    serialized = serialize_list_columns(result)

    assert isinstance(serialized.loc[0, "warning_flags"], str)
    assert "UNKNOWN_DISCLOSURE_STATUS" in serialized.loc[0, "warning_flags"]


def test_no_sector_classification_peer_comparison_or_buy_sell_logic():
    public_names = {
        name
        for name in dir(basic_filter)
        if not name.startswith("_") and callable(getattr(basic_filter, name))
    }

    assert not any(name.startswith("classify") for name in public_names)
    assert not any(name.startswith("sector") for name in public_names)
    assert not any(name.startswith("peer") for name in public_names)

    output_text = _run().to_string().upper()
    assert "BUY" not in output_text
    assert "SELL" not in output_text
