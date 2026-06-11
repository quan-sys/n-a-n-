import pandas as pd

from src.screening.stage2_eligibility_gate import build_stage2_eligibility_gate


POLICY = {
    "market_refresh": {"min_trading_days_60d_for_stage2": 30},
    "minimum_finance_required": {
        "min_years_any_core_metric": 2,
        "core_metrics": ["revenue", "net_income", "total_assets", "equity", "cfo"],
        "min_core_metrics_present": 3,
        "allow_financial_income_for_financial_firms": True,
    },
}


def test_eligible_with_market_and_finance_minimum():
    gate = _gate_for("AAA")

    row = gate.iloc[0]
    assert row["eligibility_status"] == "STAGE2_ELIGIBLE"
    assert row["finance_confidence"] == "PROVISIONAL_LOW"


def test_missing_last_close_blocks_market():
    gate = _gate_for("AAA", market_overrides={"missing_market_flag": True, "last_close": ""})

    assert gate.iloc[0]["eligibility_status"] == "BLOCKED_MISSING_MARKET"


def test_stale_price_blocks_market():
    gate = _gate_for("AAA", market_overrides={"stale_price_flag": True})

    assert gate.iloc[0]["eligibility_status"] == "BLOCKED_STALE_MARKET"


def test_low_trading_days_blocks_stage2():
    gate = _gate_for("AAA", market_overrides={"trading_days_60d": 10})

    assert gate.iloc[0]["eligibility_status"] == "BLOCKED_INSUFFICIENT_TRADING_DAYS"


def test_insufficient_finance_blocks_stage2():
    gate = _gate_for("AAA", quality_status="INSUFFICIENT_DATA", finance_long=pd.DataFrame())

    assert gate.iloc[0]["eligibility_status"] == "BLOCKED_MISSING_MIN_FINANCE"


def test_stage3_fail_gate_demotes_to_stage1():
    gate = _gate_for("AAA", stage="stage_3_final_watchlist", market_overrides={"missing_market_flag": True})

    assert gate.iloc[0]["new_stage"] == "stage_1_provisional_shortlist"
    assert gate.iloc[0]["demotion_reason"] == "BLOCKED_MISSING_MARKET"


def test_one_source_only_does_not_block_if_finance_minimum_passes():
    gate = _gate_for("AAA", crosscheck_status="ONE_SOURCE_ONLY")

    assert gate.iloc[0]["eligibility_status"] == "STAGE2_ELIGIBLE"
    assert gate.iloc[0]["finance_confidence"] == "PROVISIONAL_LOW"


def _gate_for(
    ticker: str,
    *,
    stage: str = "stage_2_evidence_candidates",
    market_overrides: dict | None = None,
    quality_status: str = "PARTIAL_PROVISIONAL_DATA",
    finance_long: pd.DataFrame | None = None,
    crosscheck_status: str = "ONE_SOURCE_ONLY",
) -> pd.DataFrame:
    ranking = pd.DataFrame([{"ticker": ticker, "balanced_rank": 1, "exchange": "HOSE", "evidence_stage": stage}])
    market = {
        "ticker": ticker,
        "missing_market_flag": False,
        "stale_price_flag": False,
        "trading_days_60d": 60,
        "avg_volume_60d": 1000,
    }
    market.update(market_overrides or {})
    quality = pd.DataFrame([{"ticker": ticker, "export_status": quality_status}])
    if finance_long is None:
        finance_long = pd.DataFrame(
            [
                {"ticker": ticker, "period": "2024", "field_name": "revenue", "value": 1},
                {"ticker": ticker, "period": "2024", "field_name": "net_income", "value": 1},
                {"ticker": ticker, "period": "2025", "field_name": "equity", "value": 1},
            ]
        )
    crosscheck = pd.DataFrame([{"ticker": ticker, "finance_crosscheck_status": crosscheck_status}])
    return build_stage2_eligibility_gate(ranking, pd.DataFrame([market]), quality, finance_long, crosscheck, POLICY)
