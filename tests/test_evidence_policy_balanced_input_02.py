import pandas as pd

from src.ingestion.evidence_pack_policy import build_candidate_stage_assignments, build_evidence_collection_queue, load_evidence_pack_policy
from src.screening.sector_balanced_evidence_ranker import create_balanced_ranking


def test_evidence_policy_balanced_input_is_not_template_only():
    balanced = create_balanced_ranking(_raw_ranking(), pd.DataFrame(), pd.DataFrame(), POLICY)
    policy = load_evidence_pack_policy()

    assignments = build_candidate_stage_assignments(balanced, policy)
    queue = build_evidence_collection_queue(assignments, policy)

    assert assignments["template_only"].astype(bool).eq(False).all()
    assert "MISSING_RANKING_INPUT" not in set(assignments["stage_assignment_status"])
    assert not queue.empty


POLICY = {
    "balance_policy": {
        "enabled": True,
        "top_stage_caps": {
            "stage_4_deep_dive_shortlist": {"max_total": 10, "max_per_sector": 2, "max_per_firm_type": 3},
            "stage_3_final_watchlist": {"max_total": 50, "max_per_sector": 8, "max_per_firm_type": 12},
            "stage_2_evidence_candidates": {"max_total": 200, "max_per_sector": 30, "max_per_firm_type": 50},
        },
        "firm_type_rules": {
            "bank": {"keywords": ["bank", "ngan hang"]},
            "securities": {"keywords": ["chung khoan", "securities"]},
            "non_financial": {"default": True},
        },
        "fallback": {"unknown_sector_bucket": "UNKNOWN", "unknown_firm_type": "unknown"},
    }
}


def _raw_ranking() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "rank": index,
                "ticker": f"T{index:03d}",
                "sector_raw": "Tai chinh / Chung khoan" if index <= 5 else f"Sector {index}",
                "industry_raw": "",
                "evidence_priority_score": 100 - index,
            }
            for index in range(1, 21)
        ]
    )
