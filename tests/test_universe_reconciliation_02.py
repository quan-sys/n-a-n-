import pandas as pd

from src.ingestion.universe_reconciliation import build_universe_reconciliation


def test_universe_reconciliation_detects_missing_market_and_finance_data():
    quality = pd.DataFrame(
        [
            {"ticker": "AAA", "finance_field_count": 8, "export_status": "OK_FOR_PROVISIONAL_SCREEN"},
            {"ticker": "BBB", "finance_field_count": 0, "export_status": "INSUFFICIENT_DATA"},
        ]
    )
    ranking = pd.DataFrame([{"ticker": "AAA", "exchange": "HOSE"}, {"ticker": "BBB", "exchange": "HNX"}])
    market = pd.DataFrame([{"ticker": "AAA", "last_close": 10}, {"ticker": "BBB", "last_close": ""}])

    result = build_universe_reconciliation(quality, ranking, market)
    issues = dict(zip(result["ticker"], result["possible_issue"]))

    assert issues["AAA"] == "OK"
    assert issues["BBB"] == "MISSING_MARKET_DATA"


def test_universe_reconciliation_detects_cache_only_extra_ticker():
    quality = pd.DataFrame([{"ticker": "ZZZ", "finance_field_count": 1, "export_status": "PARTIAL_PROVISIONAL_DATA"}])
    ranking = pd.DataFrame(columns=["ticker"])
    market = pd.DataFrame([{"ticker": "ZZZ", "exchange": "UPCoM", "last_close": 1}])

    result = build_universe_reconciliation(quality, ranking, market)

    assert result.iloc[0]["possible_issue"] == "CACHE_ONLY_EXTRA_TICKER"
