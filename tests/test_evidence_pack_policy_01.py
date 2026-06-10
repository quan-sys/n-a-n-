import pandas as pd

from src.ingestion.evidence_pack_policy import (
    STAGE_0,
    STAGE_1,
    STAGE_2,
    STAGE_3,
    STAGE_4,
    STAGE_5,
    assign_evidence_stage,
    load_evidence_pack_policy,
    required_documents_for_stage,
    validate_evidence_scope,
)


def test_stage_0_and_stage_1_require_no_official_files():
    policy = load_evidence_pack_policy()

    assert required_documents_for_stage(STAGE_0, policy) == []
    assert required_documents_for_stage(STAGE_1, policy) == []
    assert policy["stages"][STAGE_0]["official_files_per_ticker_max"] == 0
    assert policy["stages"][STAGE_1]["official_files_per_ticker_max"] == 0


def test_stage_required_document_priorities_are_capped():
    policy = load_evidence_pack_policy()

    stage_2_docs = [doc["document_priority"] for doc in required_documents_for_stage(STAGE_2, policy)]
    stage_3_docs = [doc["document_priority"] for doc in required_documents_for_stage(STAGE_3, policy)]
    stage_4_docs = [doc["document_priority"] for doc in required_documents_for_stage(STAGE_4, policy)]
    stage_5_docs = [doc["document_priority"] for doc in required_documents_for_stage(STAGE_5, policy)]

    assert stage_2_docs == [
        "P0_latest_consolidated_financial_statement",
        "P1_latest_audited_annual_financial_statement",
    ]
    assert "P2_latest_annual_report" in stage_3_docs
    assert "P3_same_period_previous_year_financial_statement" in stage_4_docs
    assert "P4_three_year_audited_annual_statements" in stage_4_docs
    assert "P5_full_history" in stage_5_docs
    assert policy["stages"][STAGE_2]["official_files_per_ticker_max"] == 2
    assert policy["stages"][STAGE_3]["official_files_per_ticker_max"] == 3
    assert policy["stages"][STAGE_4]["official_files_per_ticker_max"] == 8
    assert policy["stages"][STAGE_5]["official_files_per_ticker_max"] == 15


def test_rank_assigns_stage_without_investment_recommendation_meaning():
    assert assign_evidence_stage({"rank": 8}) == STAGE_4
    assert assign_evidence_stage({"rank": 40}) == STAGE_3
    assert assign_evidence_stage({"rank": 150}) == STAGE_2
    assert assign_evidence_stage({"rank": 400}) == STAGE_1
    assert assign_evidence_stage({"rank": 800}) == STAGE_0
    assert assign_evidence_stage({}) == STAGE_0


def test_policy_validation_rejects_too_many_files_before_stage_5():
    policy = load_evidence_pack_policy()
    assignments = pd.DataFrame(
        [
            {"ticker": f"S{i:03d}", "stage": STAGE_3, "requested_files_per_ticker": 10}
            for i in range(50)
        ]
    )

    issues = validate_evidence_scope(assignments, policy)

    assert any(issue["issue_code"] == "REQUESTED_FILES_EXCEED_STAGE_CAP" for issue in issues)


def test_policy_validation_allows_stage_5_full_history_for_tiny_list():
    policy = load_evidence_pack_policy()
    assignments = pd.DataFrame(
        [
            {"ticker": "AAA", "stage": STAGE_5, "requested_files_per_ticker": 15},
            {"ticker": "BBB", "stage": STAGE_5, "requested_files_per_ticker": 15},
            {"ticker": "CCC", "stage": STAGE_5, "requested_files_per_ticker": 15},
        ]
    )

    assert validate_evidence_scope(assignments, policy) == []
