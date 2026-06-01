from pathlib import Path

import pandas as pd

import src.scoring.l0_trash_filter as l0_trash_filter
from src.scoring.l0_trash_filter import (
    L0_OUTPUT_COLUMNS,
    build_l0_reject_log,
    load_l0_rules,
    run_l0_trash_filter,
    save_l0_reject_log,
)


RULES_PATH = "config/l0_trash_filter_rules.yaml"


def _rules():
    return load_l0_rules(RULES_PATH)


def _universe_df(**overrides):
    row = {
        "ticker": "MOCK1",
        "exchange": "HOSE",
        "company_name": "Mock One",
        "listing_status": "ACTIVE",
        "is_active": True,
        "has_basic_profile": True,
        "has_market_data": True,
        "has_financial_data": True,
        "has_disclosure_data": False,
        "universe_status": "PASS_UNIVERSE",
        "universe_warnings": [],
        "data_sanity_status": "VALID_DATA",
        "manual_review_required": False,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _market_df(ticker="MOCK1", **overrides):
    row = {
        "ticker": ticker,
        "date": "2026-05-25",
        "close": 1000,
        "volume": 50000,
        "trading_value": 5000000000,
        "source": "MOCK",
        "fetch_time": "2026-05-25T00:00:00Z",
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
        "total_liabilities": 2000,
        "equity": 3000,
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
        "event_type": "OTHER",
        "severity": "LOW",
        "source": "MOCK",
        "source_url": "",
        "notes": "mock disclosure only",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _run(**overrides):
    params = {
        "universe_df": _universe_df(),
        "market_price_df": _market_df(),
        "financial_statement_df": _financial_df(),
        "disclosure_df": None,
        "rules": _rules(),
    }
    params.update(overrides)
    return run_l0_trash_filter(**params)


def test_valid_mock_stock_passes_l0():
    result = _run()
    row = result.iloc[0]

    assert list(result.columns) == L0_OUTPUT_COLUMNS
    assert row["ticker"] == "MOCK1"
    assert row["l0_status"] == "L0_PASS"
    assert row["l0_score"] == 100
    assert row["confidence"] == "high"
    assert bool(row["manual_review_required"]) is False


def test_missing_market_data_creates_insufficient_data_for_l0():
    result = _run(
        universe_df=_universe_df(has_market_data=False),
        market_price_df=None,
    )
    row = result.iloc[0]

    assert row["l0_status"] == "INSUFFICIENT_DATA_FOR_L0"
    assert "MISSING_MARKET_DATA" in row["l0_reject_reasons"]
    assert bool(row["manual_review_required"]) is True


def test_missing_financial_data_creates_insufficient_data_for_l0():
    result = _run(
        universe_df=_universe_df(has_financial_data=False),
        financial_statement_df=None,
    )
    row = result.iloc[0]

    assert row["l0_status"] == "INSUFFICIENT_DATA_FOR_L0"
    assert "MISSING_FINANCIAL_DATA" in row["l0_reject_reasons"]
    assert bool(row["manual_review_required"]) is True


def test_negative_equity_creates_reject_or_manual_review_from_config():
    result = _run(financial_statement_df=_financial_df(equity=-10))
    row = result.iloc[0]

    assert row["l0_status"] == "L0_REJECT"
    assert "NEGATIVE_EQUITY" in row["l0_reject_reasons"]
    assert bool(row["manual_review_required"]) is True


def test_very_low_liquidity_creates_reject_or_watch_only():
    result = _run(market_price_df=_market_df(volume=10, trading_value=1000))
    row = result.iloc[0]

    assert row["l0_status"] in {"L0_REJECT", "L0_WATCH_ONLY"}
    assert (
        "VERY_LOW_LIQUIDITY" in row["l0_reject_reasons"]
        or "LOW_LIQUIDITY" in row["l0_warning_flags"]
    )


def test_critical_disclosure_event_creates_reject_or_manual_review():
    result = _run(
        disclosure_df=_disclosure_df(
            event_type="TRADING_RESTRICTION", severity="CRITICAL"
        )
    )
    row = result.iloc[0]

    assert row["l0_status"] in {"L0_REJECT", "L0_MANUAL_REVIEW"}
    assert "CRITICAL_DISCLOSURE_EVENT" in row["l0_reject_reasons"]
    assert bool(row["manual_review_required"]) is True


def test_stale_data_creates_warning_or_manual_review():
    market_df = _market_df()
    market_df["quality_status"] = ["STALE_DATA"]
    market_df["quality_warnings"] = [["STALE_DATA"]]
    market_df["quality_errors"] = [[]]
    market_df["final_confidence"] = ["low"]
    market_df["manual_review_required"] = [True]

    result = _run(market_price_df=market_df)
    row = result.iloc[0]

    assert row["l0_status"] == "L0_MANUAL_REVIEW"
    assert "MARKET_STALE_DATA" in row["l0_warning_flags"]
    assert row["confidence"] == "low"


def test_every_rejected_stock_has_reject_reason():
    result = _run(financial_statement_df=_financial_df(equity=-10))
    rejected = result[result["l0_status"] == "L0_REJECT"]

    assert not rejected.empty
    assert rejected["l0_reject_reasons"].map(bool).all()


def test_reject_log_is_generated_and_saved(tmp_path):
    result = _run(financial_statement_df=_financial_df(equity=-10))
    reject_log = build_l0_reject_log(result)
    output_path = save_l0_reject_log(
        reject_log, output_path=str(tmp_path / "l0_reject_log.csv")
    )

    assert not reject_log.empty
    assert set(reject_log["reject_layer"]) == {"L0_TRASH_FILTER"}
    assert reject_log["reject_reason"].map(bool).all()
    assert Path(output_path).exists()


def test_no_sector_classification_or_l1_l2_l3_logic_is_implemented():
    public_names = {
        name
        for name in dir(l0_trash_filter)
        if not name.startswith("_") and callable(getattr(l0_trash_filter, name))
    }

    assert not any(name.startswith("classify") for name in public_names)
    assert not any(name.startswith("sector") for name in public_names)
    assert not any(name.startswith("cycle") for name in public_names)
    assert not any(name.startswith("value") for name in public_names)


def test_no_buy_sell_recommendation_is_generated():
    result = _run()
    output_text = result.to_string().upper()

    assert "BUY" not in output_text
    assert "SELL" not in output_text
