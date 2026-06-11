from pathlib import Path

import pandas as pd

from src.ingestion.evidence_pack_policy import (
    build_candidate_stage_assignments,
    build_evidence_collection_queue,
    load_evidence_pack_policy,
)
from src.screening.provisional_evidence_ranker import build_provisional_evidence_ranking


def test_evidence_policy_uses_legacy_ranking_input_not_template_only():
    ranking = _ranking_input(12)
    policy = load_evidence_pack_policy()

    assignments = build_candidate_stage_assignments(ranking, policy)
    queue = build_evidence_collection_queue(assignments, policy)

    assert assignments["template_only"].astype(bool).eq(False).all()
    assert "MISSING_RANKING_INPUT" not in set(assignments["stage_assignment_status"])
    assert not queue.empty


def _ranking_input(count: int) -> pd.DataFrame:
    finance_rows = []
    market_rows = []
    quality_rows = []
    crosscheck_rows = []
    for idx in range(count):
        ticker = f"L{idx:03d}"
        finance_rows.append(
            {
                "ticker": ticker,
                "revenue": 100,
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
        market_rows.append({"ticker": ticker, "last_close": 10, "avg_volume_60d": 1000, "missing_price_flag": False})
        quality_rows.append({"ticker": ticker, "finance_field_count": 8, "export_status": "OK_FOR_PROVISIONAL_SCREEN"})
        crosscheck_rows.append({"ticker": ticker, "source_count": 1, "field_name": "revenue", "period": "2025"})
    return build_provisional_evidence_ranking(
        pd.DataFrame(finance_rows),
        pd.DataFrame(market_rows),
        pd.DataFrame(quality_rows),
        pd.DataFrame(crosscheck_rows),
    )
