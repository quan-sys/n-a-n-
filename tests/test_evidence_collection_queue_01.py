import pandas as pd

from src.ingestion.evidence_pack_policy import (
    CANDIDATE_STAGE_ASSIGNMENT_COLUMNS,
    EVIDENCE_COLLECTION_QUEUE_COLUMNS,
    STAGE_0,
    STAGE_1,
    STAGE_2,
    STAGE_3,
    build_candidate_stage_assignments,
    build_evidence_collection_queue,
    build_evidence_pack_status,
    forbidden_policy_output_columns,
    load_evidence_pack_policy,
)


def test_queue_defers_collection_for_stage_0_and_stage_1():
    policy = load_evidence_pack_policy()
    assignments = pd.DataFrame(
        [
            _assignment("AAA", STAGE_0),
            _assignment("BBB", STAGE_1),
            _assignment("CCC", STAGE_2),
        ],
        columns=CANDIDATE_STAGE_ASSIGNMENT_COLUMNS,
    )

    queue = build_evidence_collection_queue(assignments, policy)

    assert list(queue["ticker"].unique()) == ["CCC"]
    assert set(queue["document_priority"]) == {
        "P0_latest_consolidated_financial_statement",
        "P1_latest_audited_annual_financial_statement",
    }
    assert len(queue) == 2


def test_stage_3_queue_adds_latest_annual_report_but_no_deep_history():
    policy = load_evidence_pack_policy()
    assignments = pd.DataFrame([_assignment("AAA", STAGE_3)], columns=CANDIDATE_STAGE_ASSIGNMENT_COLUMNS)

    queue = build_evidence_collection_queue(assignments, policy)

    assert set(queue["document_priority"]) == {
        "P0_latest_consolidated_financial_statement",
        "P1_latest_audited_annual_financial_statement",
        "P2_latest_annual_report",
    }
    assert "P4_three_year_audited_annual_statements" not in set(queue["document_priority"])


def test_missing_ranking_input_creates_template_only_no_real_queue():
    policy = load_evidence_pack_policy()

    assignments = build_candidate_stage_assignments(None, policy)
    queue = build_evidence_collection_queue(assignments, policy)

    assert assignments["stage_assignment_status"].eq("MISSING_RANKING_INPUT").all()
    assert assignments["template_only"].astype(bool).all()
    assert queue.empty
    assert list(queue.columns) == EVIDENCE_COLLECTION_QUEUE_COLUMNS


def test_evidence_status_marks_stage_0_as_no_official_evidence_needed():
    policy = load_evidence_pack_policy()
    assignments = pd.DataFrame([_assignment("AAA", STAGE_0)], columns=CANDIDATE_STAGE_ASSIGNMENT_COLUMNS)

    status = build_evidence_pack_status(assignments, policy)

    assert status.iloc[0]["evidence_pack_status"] == "NO_OFFICIAL_EVIDENCE_NEEDED_YET"
    assert status.iloc[0]["required_slots"] == 0


def test_no_buy_sell_or_target_price_fields_are_created():
    assert forbidden_policy_output_columns() == []


def _assignment(ticker: str, stage: str) -> dict:
    return {
        "ticker": ticker,
        "input_rank": "",
        "rank_source": "",
        "stage": stage,
        "stage_assignment_status": "ASSIGNED_FROM_RANK",
        "assignment_reason": "test",
        "official_files_per_ticker_min": 0,
        "official_files_per_ticker_max": 0,
        "target_max_tickers_for_stage": 0,
        "template_only": False,
        "manual_review_required": False,
        "no_financial_claim": True,
    }
