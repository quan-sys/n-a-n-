import pandas as pd

from src.screening.current_market_balanced_ranking import (
    build_current_market_balanced_ranking,
    build_current_market_balanced_summary,
)


POLICY = {
    "balance_policy": {
        "enabled": True,
        "top_stage_caps": {
            "stage_4_deep_dive_shortlist": {"max_total": 10, "max_per_sector": 2, "max_per_firm_type": 3},
            "stage_3_final_watchlist": {"max_total": 50, "max_per_sector": 8, "max_per_firm_type": 12},
            "stage_2_evidence_candidates": {"max_total": 200, "max_per_sector": 30, "max_per_firm_type": 50},
        },
        "firm_type_rules": {"securities": {"keywords": ["securities"]}, "non_financial": {"default": True}},
        "fallback": {"unknown_sector_bucket": "UNKNOWN", "unknown_firm_type": "unknown"},
    }
}


def test_fail_gate_does_not_appear_in_stage2_plus_after_ranking():
    ranking = _ranking()
    gate = _gate(["AAA"], "BLOCKED_MISSING_MARKET")

    result = build_current_market_balanced_ranking(ranking, gate, pd.DataFrame(), pd.DataFrame(), POLICY)
    aaa = result[result["ticker"].eq("AAA")].iloc[0]

    assert aaa["evidence_stage"] == "stage_1_provisional_shortlist"
    assert aaa["evidence_stage"] not in {"stage_2_evidence_candidates", "stage_3_final_watchlist", "stage_4_deep_dive_shortlist"}


def test_sector_cap_still_respected_for_eligible_pool():
    ranking = _ranking()
    gate = _gate(list(ranking["ticker"]), "STAGE2_ELIGIBLE")

    result = build_current_market_balanced_ranking(ranking, gate, pd.DataFrame(), pd.DataFrame(), POLICY)

    assert result.head(10)["sector_bucket"].value_counts().max() <= 2


def test_summary_contains_before_after_counts():
    ranking = _ranking()
    gate = _gate(["AAA"], "BLOCKED_STALE_MARKET")
    result = build_current_market_balanced_ranking(ranking, gate, pd.DataFrame(), pd.DataFrame(), POLICY)

    summary = build_current_market_balanced_summary(ranking, gate, result, previous_queue_rows=10, new_queue_rows=2)

    assert "Stage Distribution Before Gate" in summary
    assert "Stage Distribution After Gate" in summary
    assert "number_demoted_by_stale_market" in summary


def _ranking() -> pd.DataFrame:
    rows = []
    sectors = ["Sector A", "Sector A", "Sector B", "Sector C", "Sector D", "Sector E", "Sector F", "Sector G", "Sector H", "Sector I", "Sector J"]
    for index, sector in enumerate(sectors, start=1):
        rows.append(
            {
                "balanced_rank": index,
                "raw_rank": index,
                "ticker": "AAA" if index == 1 else f"T{index:03d}",
                "exchange": "HOSE",
                "sector_raw": sector,
                "sector_bucket": sector,
                "firm_type": "non_financial",
                "raw_evidence_priority_score": 100 - index,
                "balanced_evidence_priority_score": 100 - index,
                "evidence_stage": "stage_4_deep_dive_shortlist" if index <= 10 else "stage_3_final_watchlist",
            }
        )
    return pd.DataFrame(rows)


def _gate(tickers: list[str], status: str) -> pd.DataFrame:
    rows = []
    for ticker in tickers:
        rows.append(
            {
                "ticker": ticker,
                "original_stage": "stage_4_deep_dive_shortlist",
                "new_stage": "stage_4_deep_dive_shortlist" if status == "STAGE2_ELIGIBLE" else "stage_1_provisional_shortlist",
                "eligibility_status": status,
                "demotion_reason": "" if status == "STAGE2_ELIGIBLE" else status,
            }
        )
    return pd.DataFrame(rows)
