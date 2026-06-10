import pandas as pd

from src.ingestion.evidence_pack_policy import (
    STAGE_0,
    STAGE_2,
    STAGE_3,
    STAGE_5,
    build_workload_budget_estimate,
    estimate_document_workload,
    load_evidence_pack_policy,
)


def test_workload_budget_uses_stage_caps_and_manual_time_range():
    policy = load_evidence_pack_policy()
    budget = build_workload_budget_estimate(policy)

    stage_0 = budget[budget["stage"].eq(STAGE_0)].iloc[0]
    stage_3 = budget[budget["stage"].eq(STAGE_3)].iloc[0]
    stage_5 = budget[budget["stage"].eq(STAGE_5)].iloc[0]

    assert stage_0["estimated_files_max"] == 0
    assert stage_3["target_tickers"] == 50
    assert stage_3["estimated_files_min"] == 100
    assert stage_3["estimated_files_max"] == 150
    assert stage_5["target_tickers"] == 3
    assert stage_5["estimated_files_max"] == 45
    assert stage_5["manual_minutes_per_file_assumption"] == "2-5"
    assert stage_5["paid_data_recommended"] == "Yes, if manual collection blocks progress"


def test_assignment_workload_estimate_counts_only_assigned_rows():
    policy = load_evidence_pack_policy()
    assignments = pd.DataFrame(
        [
            {"ticker": "AAA", "stage": STAGE_2},
            {"ticker": "BBB", "stage": STAGE_2},
            {"ticker": "CCC", "stage": STAGE_3},
        ]
    )

    workload = estimate_document_workload(assignments, policy)

    assert workload["by_stage"][STAGE_2]["estimated_files_min"] == 2
    assert workload["by_stage"][STAGE_2]["estimated_files_max"] == 4
    assert workload["by_stage"][STAGE_3]["estimated_files_min"] == 2
    assert workload["by_stage"][STAGE_3]["estimated_files_max"] == 3
    assert workload["total_estimated_files_min"] == 4
    assert workload["total_estimated_files_max"] == 7
