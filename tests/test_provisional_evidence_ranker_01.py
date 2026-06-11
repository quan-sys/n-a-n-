from pathlib import Path

import pandas as pd

from src.screening.provisional_evidence_ranker import build_provisional_evidence_ranking


def test_provisional_ranker_creates_evidence_priority_not_investment_score():
    finance, market, quality, crosscheck = _frames(12)

    ranking = build_provisional_evidence_ranking(finance, market, quality, crosscheck)

    assert "evidence_priority_score" in ranking.columns
    assert "investment_score" not in ranking.columns
    assert "target_price" not in ranking.columns
    assert ranking["confidence_level"].ne("HIGH").all()
    assert ranking.iloc[0]["evidence_stage"] == "stage_4_deep_dive_shortlist"


def test_ranking_generates_stage_2_stage_3_and_stage_4_assignments():
    finance, market, quality, crosscheck = _frames(55)

    ranking = build_provisional_evidence_ranking(finance, market, quality, crosscheck)

    assert "stage_4_deep_dive_shortlist" in set(ranking["evidence_stage"])
    assert "stage_3_final_watchlist" in set(ranking["evidence_stage"])
    assert "stage_2_evidence_candidates" in set(ranking["evidence_stage"])


def test_forbidden_fields_do_not_enter_provisional_ranked_shortlist():
    finance, market, quality, crosscheck = _frames(3)
    finance["fair_value"] = 999
    market["timing_score"] = 10

    ranking = build_provisional_evidence_ranking(finance, market, quality, crosscheck)

    assert "fair_value" not in ranking.columns
    assert "timing_score" not in ranking.columns


def _frames(count: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    finance_rows = []
    market_rows = []
    quality_rows = []
    crosscheck_rows = []
    for idx in range(count):
        ticker = f"T{idx:03d}"
        finance_rows.append(
            {
                "ticker": ticker,
                "exchange": "HOSE",
                "company_name": ticker,
                "sector_raw": "Sector",
                "industry_raw": "Industry",
                "revenue": 100 + idx,
                "gross_profit": 20,
                "net_income": 5,
                "total_assets": 200,
                "total_liabilities": 80,
                "equity": 120,
                "cfo": 8,
                "capex": -2,
                "finance_completeness_score": 1,
                "missing_fields": "",
                "source_count": 1,
            }
        )
        market_rows.append(
            {
                "ticker": ticker,
                "last_close": 10 + idx,
                "avg_volume_60d": 1000 + idx,
                "stale_price_flag": False,
                "missing_price_flag": False,
            }
        )
        quality_rows.append(
            {
                "ticker": ticker,
                "finance_field_count": 8,
                "missing_required_fields": "",
                "export_status": "OK_FOR_PROVISIONAL_SCREEN",
            }
        )
        crosscheck_rows.append(
            {
                "ticker": ticker,
                "period": "2025",
                "field_name": "revenue",
                "source_count": 1,
                "crosscheck_status": "ONE_SOURCE_ONLY",
            }
        )
    return pd.DataFrame(finance_rows), pd.DataFrame(market_rows), pd.DataFrame(quality_rows), pd.DataFrame(crosscheck_rows)
