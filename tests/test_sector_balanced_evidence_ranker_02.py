import pandas as pd

from src.screening.sector_balanced_evidence_ranker import (
    create_balanced_ranking,
    infer_firm_type,
    load_balance_policy,
)


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
            "insurance": {"keywords": ["bao hiem", "insurance"]},
            "real_estate": {"keywords": ["bat dong san", "real estate"]},
            "non_financial": {"default": True},
        },
        "fallback": {"unknown_sector_bucket": "UNKNOWN", "unknown_firm_type": "unknown"},
    }
}


def test_firm_type_inference_identifies_expected_types():
    assert infer_firm_type({"sector_raw": "Tai chinh / Chung khoan"}, POLICY) == "securities"
    assert infer_firm_type({"sector_raw": "Ngan hang"}, POLICY) == "bank"
    assert infer_firm_type({"sector_raw": "Bao hiem"}, POLICY) == "insurance"
    assert infer_firm_type({"sector_raw": "Bat dong san"}, POLICY) == "real_estate"
    assert infer_firm_type({"sector_raw": "Thuc pham"}, POLICY) == "non_financial"


def test_sector_cap_demotes_excess_securities_from_top_10():
    raw = _raw_ranking()

    balanced = create_balanced_ranking(raw, pd.DataFrame(), pd.DataFrame(), POLICY)

    top10 = balanced.head(10)
    assert (top10["firm_type"] == "securities").sum() <= 2
    assert "DEMOTED_SECTOR_CAP" in set(balanced["balance_action"])
    assert "raw_rank" in balanced.columns
    assert "raw_evidence_priority_score" in balanced.columns


def test_balanced_ranking_has_no_forbidden_fields():
    raw = _raw_ranking()
    raw["fair_value"] = 123
    raw["target_price"] = 456

    balanced = create_balanced_ranking(raw, pd.DataFrame(), pd.DataFrame(), POLICY)

    forbidden = {"fair_value", "mos", "margin_of_safety", "target_price", "upside", "buy_candidate", "watch_candidate", "investment_score"}
    assert forbidden.isdisjoint(set(balanced.columns))


def _raw_ranking() -> pd.DataFrame:
    rows = []
    for index in range(1, 21):
        is_sec = index <= 8
        sector = _sector_for_index(index)
        rows.append(
            {
                "rank": index,
                "ticker": f"T{index:03d}",
                "exchange": "HOSE",
                "sector_raw": "Tai chinh / Chung khoan" if is_sec else sector,
                "industry_raw": "Chung khoan" if is_sec else sector,
                "evidence_priority_score": 100 - index,
                "liquidity_score": 50,
                "data_completeness_score": 50,
                "finance_sanity_score": 50,
                "source_coverage_score": 10,
                "manual_review_required": True,
            }
        )
    return pd.DataFrame(rows)


def _sector_for_index(index: int) -> str:
    sectors = [
        "Ngan hang",
        "Bao hiem",
        "Bat dong san",
        "Hang tieu dung",
        "Cong nghe",
        "Dau khi",
        "Tien ich",
        "Y te",
    ]
    return sectors[(index - 9) % len(sectors)]
