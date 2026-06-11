from pathlib import Path

import pandas as pd

from src.validation.current_market_pilot_audit_03a import (
    MISMATCH_COLUMNS,
    run_pilot_audit,
)


def test_missing_required_file_reports_fail(tmp_path: Path):
    paths = _write_valid_fixture(tmp_path)
    (paths["input"] / "current_market_snapshot.csv").unlink()

    result = _run(paths)

    row = _check_row(result.checks, "FILE_current_market_snapshot")
    assert row["status"] == "FAIL"
    assert "missing" in row["actual"]


def test_missing_required_column_reports_schema_fail(tmp_path: Path):
    paths = _write_valid_fixture(tmp_path)
    snapshot = pd.read_csv(paths["input"] / "current_market_snapshot.csv")
    snapshot = snapshot.drop(columns=["last_close"])
    snapshot.to_csv(paths["input"] / "current_market_snapshot.csv", index=False)

    result = _run(paths)

    row = _check_row(result.checks, "SCHEMA_current_market_snapshot")
    assert row["status"] == "FAIL"
    assert "last_close" in row["actual"]


def test_fetch_ok_without_snapshot_row_reports_fail(tmp_path: Path):
    paths = _write_valid_fixture(tmp_path)
    pd.DataFrame(columns=_snapshot_columns()).to_csv(paths["input"] / "current_market_snapshot.csv", index=False)

    result = _run(paths)

    row = _check_row(result.checks, "SNAPSHOT_FETCH_OK_ROWS")
    assert row["status"] == "FAIL"
    assert "AAA" in row["message"]


def test_stale_snapshot_reports_fail(tmp_path: Path):
    paths = _write_valid_fixture(tmp_path)
    snapshot = pd.read_csv(paths["input"] / "current_market_snapshot.csv")
    snapshot.loc[0, "stale_price_flag"] = True
    snapshot.to_csv(paths["input"] / "current_market_snapshot.csv", index=False)

    result = _run(paths)

    row = _check_row(result.checks, "SNAPSHOT_STALE_FLAGS")
    assert row["status"] == "FAIL"
    assert "AAA" in row["message"]


def test_blocked_missing_market_cannot_remain_stage2_plus(tmp_path: Path):
    paths = _write_valid_fixture(tmp_path)
    gate = pd.read_csv(paths["input"] / "stage2_eligibility_gate.csv", keep_default_na=False)
    gate.loc[0, "eligibility_status"] = "BLOCKED_MISSING_MARKET"
    gate.loc[0, "new_stage"] = "stage_2_evidence_candidates"
    gate.loc[0, "demotion_reason"] = "BLOCKED_MISSING_MARKET"
    gate.to_csv(paths["input"] / "stage2_eligibility_gate.csv", index=False)

    result = _run(paths)

    row = _check_row(result.checks, "GATE_BLOCKED_NOT_STAGE2_PLUS")
    assert row["status"] == "FAIL"
    assert row["severity"] == "BLOCKER"


def test_evidence_queue_cannot_contain_blocked_ticker(tmp_path: Path):
    paths = _write_valid_fixture(tmp_path)
    gate = pd.read_csv(paths["input"] / "stage2_eligibility_gate.csv", keep_default_na=False)
    gate.loc[0, "eligibility_status"] = "BLOCKED_MISSING_MARKET"
    gate.loc[0, "new_stage"] = "stage_1_provisional_shortlist"
    gate.loc[0, "demotion_reason"] = "BLOCKED_MISSING_MARKET"
    gate.to_csv(paths["input"] / "stage2_eligibility_gate.csv", index=False)
    ranking = pd.read_csv(paths["input"] / "current_market_balanced_ranked_shortlist.csv")
    ranking.loc[0, "evidence_stage"] = "stage_1_provisional_shortlist"
    ranking.to_csv(paths["input"] / "current_market_balanced_ranked_shortlist.csv", index=False)

    result = _run(paths)

    row = _check_row(result.checks, "EVIDENCE_QUEUE_GATE_ELIGIBLE")
    assert row["status"] == "FAIL"
    assert row["severity"] == "BLOCKER"


def test_raw_recompute_mismatch_is_reported(tmp_path: Path):
    paths = _write_valid_fixture(tmp_path)
    snapshot = pd.read_csv(paths["input"] / "current_market_snapshot.csv")
    snapshot.loc[0, "last_close"] = 99
    snapshot.to_csv(paths["input"] / "current_market_snapshot.csv", index=False)

    result = _run(paths)

    row = _check_row(result.checks, "RAW_RECOMPUTE_MATCH")
    assert row["status"] == "FAIL"
    assert "last_close" in set(result.mismatches["field"])


def test_no_target_price_policy_line_does_not_trigger_safety_fail(tmp_path: Path):
    paths = _write_valid_fixture(tmp_path)
    (paths["evidence"] / "run_summary.md").write_text("no_target_price: true\n", encoding="utf-8")

    result = _run(paths)

    row = _check_row(result.checks, "SAFETY_FORBIDDEN_OUTPUTS")
    assert row["status"] == "PASS"


def test_recommendation_column_triggers_safety_blocker(tmp_path: Path):
    paths = _write_valid_fixture(tmp_path)
    ranking = pd.read_csv(paths["input"] / "current_market_balanced_ranked_shortlist.csv")
    ranking["recommendation"] = "manual review only"
    ranking.to_csv(paths["input"] / "current_market_balanced_ranked_shortlist.csv", index=False)

    result = _run(paths)

    row = _check_row(result.checks, "SAFETY_FORBIDDEN_OUTPUTS")
    assert row["status"] == "FAIL"
    assert row["severity"] == "BLOCKER"
    assert "recommendation" in row["actual"]


def test_empty_mismatch_file_still_has_header(tmp_path: Path):
    paths = _write_valid_fixture(tmp_path)

    result = _run(paths)
    mismatch_path = paths["output"] / "pilot_audit_mismatch_cases.csv"

    assert result.mismatches.empty
    mismatch = pd.read_csv(mismatch_path)
    assert list(mismatch.columns) == MISMATCH_COLUMNS


def _run(paths: dict[str, Path]):
    return run_pilot_audit(
        input_dir=paths["input"],
        evidence_dir=paths["evidence"],
        output_dir=paths["output"],
        policy_path=paths["policy"],
        raw_dir=paths["raw"],
    )


def _write_valid_fixture(tmp_path: Path) -> dict[str, Path]:
    input_dir = tmp_path / "input"
    evidence_dir = tmp_path / "evidence"
    output_dir = tmp_path / "output"
    raw_dir = tmp_path / "raw"
    for path in [input_dir, evidence_dir, raw_dir]:
        path.mkdir(parents=True, exist_ok=True)
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        "\n".join(
            [
                "input_expectations:",
                "  expected_pilot_ticker_count: 1",
                "raw_recompute:",
                "  last_close_tolerance: 0.000001",
                "  avg_volume_abs_tolerance: 1",
                "  avg_volume_rel_tolerance_pct: 0.01",
                "  missing_raw_history_status: WARN",
                "  last_close_mismatch_status: FAIL",
                "  last_price_date_mismatch_status: FAIL",
                "  trading_days_60d_mismatch_status: FAIL",
                "  avg_volume_mismatch_status: WARN",
                "safety_keywords:",
                "  forbidden_columns:",
                "    - buy",
                "    - sell",
                "    - hold",
                "    - target_price",
                "    - fair_value",
                "    - margin_of_safety",
                "    - mos",
                "    - recommendation",
                "  allowed_negative_context:",
                "    - 'no '",
                "    - 'no_'",
                "    - 'not '",
                "    - 'forbidden'",
                "    - 'blocked'",
                "    - 'none'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "fetch_status": "FETCH_OK",
                "created_at": "2026-06-11T09:00:00+00:00",
            }
        ]
    ).to_csv(input_dir / "current_market_refresh_attempt_log.csv", index=False)
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "fetch_status": "FETCH_OK",
                "last_close": 12.0,
                "last_price_date": "2026-06-10",
                "avg_volume_20d": 200.0,
                "avg_volume_60d": 200.0,
                "trading_days_60d": 2,
                "missing_market_flag": False,
                "stale_price_flag": False,
            }
        ]
    ).to_csv(input_dir / "current_market_snapshot.csv", index=False)
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "original_stage": "stage_4_deep_dive_shortlist",
                "new_stage": "stage_4_deep_dive_shortlist",
                "eligibility_status": "STAGE2_ELIGIBLE",
                "demotion_reason": "",
                "finance_crosscheck_status": "ONE_SOURCE_ONLY",
                "finance_confidence": "PROVISIONAL_LOW",
            }
        ]
    ).to_csv(input_dir / "stage2_eligibility_gate.csv", index=False)
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "evidence_stage": "stage_4_deep_dive_shortlist",
                "sector_bucket": "Sector A",
                "firm_type": "non_financial",
            }
        ]
    ).to_csv(input_dir / "current_market_balanced_ranked_shortlist.csv", index=False)
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "stage": "stage_4_deep_dive_shortlist",
                "document_priority": "BCTN",
            }
        ]
    ).to_csv(evidence_dir / "evidence_collection_queue.csv", index=False)
    pd.DataFrame(
        [
            {"ticker": "AAA", "date": "2026-06-09", "close": 10.0, "volume": 100},
            {"ticker": "AAA", "date": "2026-06-10", "close": 12.0, "volume": 300},
        ]
    ).to_csv(raw_dir / "AAA_history.csv", index=False)
    for filename in [
        "current_market_refresh_summary.md",
        "stage2_eligibility_summary.md",
        "current_market_balanced_ranking_summary.md",
    ]:
        (input_dir / filename).write_text("pilot summary\n", encoding="utf-8")
    (evidence_dir / "run_summary.md").write_text("pilot run summary\n", encoding="utf-8")
    return {
        "input": input_dir,
        "evidence": evidence_dir,
        "output": output_dir,
        "raw": raw_dir,
        "policy": policy_path,
    }


def _snapshot_columns() -> list[str]:
    return [
        "ticker",
        "fetch_status",
        "last_close",
        "last_price_date",
        "avg_volume_20d",
        "avg_volume_60d",
        "trading_days_60d",
        "missing_market_flag",
        "stale_price_flag",
    ]


def _check_row(checks: pd.DataFrame, check_id: str) -> pd.Series:
    rows = checks[checks["check_id"].eq(check_id)]
    assert not rows.empty, f"missing check {check_id}"
    return rows.iloc[0]
