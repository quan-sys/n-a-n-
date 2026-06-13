import json
from pathlib import Path

import pandas as pd

from src.audit.step29_full_universe_audit_after_market_refresh import (
    FINAL_DECISIONS,
    build_step29_audit,
    run_step29_full_universe_audit_after_market_refresh,
    scan_forbidden_terms,
)


REQUIRED_OUTPUTS = {
    "step29_audit_summary.json",
    "step29_full_universe_audit.csv",
    "step29_shortlist.csv",
    "step29_step26_comparison.json",
    "step29_guardrail_report.json",
    "README.md",
}


def test_step29_recovered_market_data_does_not_hide_finance_gaps(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path)

    result = run_step29_full_universe_audit_after_market_refresh(
        config_path=paths["config"],
        output_dir=paths["output"],
        pytest_result="related=PASS",
    )

    bbb = result.audit[result.audit["ticker"].eq("BBB")].iloc[0]
    assert bbb["step29_market_recovery_status"] == "RECOVERED_FROM_STEP26_BLOCKED"
    assert bbb["step29_screening_status"] == "MANUAL_REVIEW"
    assert "revenue" in bbb["remaining_missing_fields"]
    assert bool(bbb["market_data_available_after_step28"]) is True


def test_step29_can_shortlist_recovered_rows_only_when_gaps_are_clear(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path)

    result = run_step29_full_universe_audit_after_market_refresh(
        config_path=paths["config"],
        output_dir=paths["output"],
        pytest_result="related=PASS",
    )

    assert set(result.shortlist["ticker"]) == {"AAA", "CCC"}
    ccc = result.audit[result.audit["ticker"].eq("CCC")].iloc[0]
    assert ccc["step29_screening_status"] == "WATCHLIST_CANDIDATE"
    assert bool(ccc["shortlist_eligible"]) is True


def test_step29_summary_comparison_and_guardrails(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path)

    result = run_step29_full_universe_audit_after_market_refresh(
        config_path=paths["config"],
        output_dir=paths["output"],
        pytest_result="related=PASS; full=PASS",
    )

    summary = result.summary
    assert summary["total_universe"] == 6
    assert summary["market_data_available_after_step28"] == 4
    assert summary["still_blocked_insufficient_market_data"] == 2
    assert summary["recovered_from_step26_blocked"] == 3
    assert summary["watchlist_candidate_count"] == 2
    assert summary["manual_review_count"] == 4
    assert summary["failed_count"] == 1
    assert summary["insufficient_data_count"] == 1
    assert summary["final_decision"] in FINAL_DECISIONS
    assert summary["pytest_result"] == "related=PASS; full=PASS"
    assert result.comparison["step26_blocked_insufficient_market_data"] == 5
    assert result.comparison["watchlist_candidate_delta"] == 1
    assert result.guardrail_report["no_guardrail_violations"] is True
    assert result.guardrail_report["data_fetch_performed"] is False
    assert REQUIRED_OUTPUTS.issubset({path.name for path in paths["output"].iterdir()})
    assert scan_forbidden_terms(paths["output"]) == []


def test_build_step29_audit_handles_missing_snapshot_without_zero_fill():
    baseline = pd.DataFrame([_row("AAA", status="BLOCKED_INSUFFICIENT_MARKET_DATA", missing='["last_close"]')])
    audit = build_step29_audit(_config_dict(), baseline, pd.DataFrame())

    row = audit.iloc[0]
    assert row["step29_market_recovery_status"] == "STEP28_NOT_ATTEMPTED"
    assert row["last_close"] == ""
    assert row["step29_screening_status"] == "BLOCKED_INSUFFICIENT_MARKET_DATA"


def _write_fixture(tmp_path: Path) -> dict[str, Path]:
    data_root = tmp_path / "data" / "reports"
    step25_dir = data_root / "step25_full_universe_1743_primary_only_scale"
    step26_dir = data_root / "step26_full_universe_output_audit_first_shortlist"
    step28_dir = data_root / "step28_full_universe_market_snapshot_refresh_vnstock"
    output = tmp_path / "out"
    config = tmp_path / "config.yaml"
    step25_dir.mkdir(parents=True)
    step26_dir.mkdir(parents=True)
    step28_dir.mkdir(parents=True)

    rows = pd.DataFrame(
        [
            _row("AAA", status="WATCHLIST_CANDIDATE", missing="[]", block="[]", last_close=10, last_price_date="2026-06-11"),
            _row("BBB", missing='["last_close", "last_price_date", "revenue"]', finance="PARTIAL_PROVISIONAL_DATA"),
            _row("CCC", missing='["last_close", "last_price_date"]', finance="OK_FOR_PROVISIONAL_SCREEN"),
            _row("DDD", finance="PARTIAL_PROVISIONAL_DATA"),
            _row("EEE", finance="PARTIAL_PROVISIONAL_DATA"),
            _row("FFF", missing='["last_close", "last_price_date", "net_income"]', finance="INSUFFICIENT_DATA"),
        ]
    )
    step25_rows = step25_dir / "full_universe_screening_rows.csv"
    step26_rows = step26_dir / "normalized_universe_rows.csv"
    step26_summary = step26_dir / "step26_audit_summary.json"
    step28_rows = step28_dir / "market_snapshot_rows.csv"
    step28_summary = step28_dir / "step28_market_refresh_summary.json"

    rows.to_csv(step25_rows, index=False)
    rows.to_csv(step26_rows, index=False)
    step26_summary.write_text(
        json.dumps(
            {
                "total_universe_rows_read": 6,
                "status_distribution": {"BLOCKED_INSUFFICIENT_MARKET_DATA": 5, "WATCHLIST_CANDIDATE": 1},
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            _snapshot("BBB", close=20),
            _snapshot("CCC", close=30),
            _snapshot("EEE", error="SOURCE_RATE_LIMIT_OR_TIMEOUT"),
            _snapshot("FFF", close=40),
        ]
    ).to_csv(step28_rows, index=False)
    step28_summary.write_text(
        json.dumps({"total_tickers_attempted": 4, "fetch_ok_count": 3, "fetch_failed_count": 1}),
        encoding="utf-8",
    )
    _write_config(config, step25_rows, step26_rows, step26_summary, step28_rows, step28_summary, output)
    return {"config": config, "output": output}


def _row(
    ticker: str,
    *,
    status: str = "BLOCKED_INSUFFICIENT_MARKET_DATA",
    missing: str = '["last_close", "last_price_date"]',
    block: str = '["Primary market data missing or incomplete."]',
    finance: str = "PARTIAL_PROVISIONAL_DATA",
    last_close: str | int = "",
    last_price_date: str = "",
) -> dict:
    return {
        "ticker": ticker,
        "company_name": f"{ticker} Corp",
        "screening_status": status,
        "watchlist_status": "WATCH_ONLY" if status == "WATCHLIST_CANDIDATE" else "REJECTED",
        "manual_review_required": True,
        "manual_bctc_required": status == "WATCHLIST_CANDIDATE",
        "market_source_confidence": "PROVISIONAL_PRIMARY_ONLY",
        "finance_source_confidence": "PROVISIONAL_LOW",
        "crosscheck_status": "NOT_AVAILABLE",
        "verification_status": "NEEDS_MANUAL_BCTC_REVIEW",
        "missing_fields": missing,
        "block_reasons": block,
        "reason_to_review": "Primary market data missing or incomplete.",
        "last_price_date": last_price_date,
        "last_close": last_close,
        "avg_volume_20d": 100 if status == "WATCHLIST_CANDIDATE" else "",
        "avg_volume_60d": 100 if status == "WATCHLIST_CANDIDATE" else "",
        "last_volume": 100 if status == "WATCHLIST_CANDIDATE" else "",
        "recent_trading_value": 1000 if status == "WATCHLIST_CANDIDATE" else "",
        "stale_days": 0 if status == "WATCHLIST_CANDIDATE" else "",
        "market_fetch_status": "FETCH_OK" if status == "WATCHLIST_CANDIDATE" else "",
        "finance_quality_status": finance,
        "finance_source_layer": "provisional_structured",
    }


def _snapshot(ticker: str, *, close: int | None = None, error: str = "OK") -> dict:
    ok = error == "OK"
    return {
        "ticker": ticker,
        "exchange_if_available": "HOSE",
        "market_source": "vnstock:VCI",
        "fetch_status": "OK" if ok else "FAILED",
        "fetch_error_type": error,
        "fetch_error_message": "",
        "history_row_count": 10 if ok else 0,
        "first_price_date": "2026-01-01" if ok else "",
        "last_price_date": "2026-06-12" if ok else "",
        "last_close": close if ok else "",
        "last_volume": 500 if ok else "",
        "last_value_if_available": "",
        "avg_volume_20d": 600 if ok else "",
        "avg_volume_60d": 700 if ok else "",
        "avg_value_20d_if_available": "",
        "avg_value_60d_if_available": "",
        "recent_price_available": ok,
        "market_data_available": ok,
        "liquidity_data_available": ok,
        "stale_market_data": not ok,
        "calendar_days_since_last_price": 1 if ok else "",
        "missing_market_fields": "[]" if ok else '["last_price_date", "last_close"]',
        "cache_used": True,
        "attempt_count": 1,
        "batch_id": "batch_0001",
        "created_at": "2026-06-13T00:00:00+00:00",
    }


def _write_config(
    path: Path,
    step25_rows: Path,
    step26_rows: Path,
    step26_summary: Path,
    step28_rows: Path,
    step28_summary: Path,
    output: Path,
) -> None:
    path.write_text(
        f"""
step_id: STEP29-FULL-UNIVERSE-AUDIT-AFTER-MARKET-REFRESH
mode: rerun_audit_after_market_refresh
limits:
  expected_universe_size: 6
  shortlist_size: 50
safety:
  no_recommendation: true
  no_buy_sell_hold: true
  no_target_price: true
  no_fair_value: true
  no_intrinsic_value: true
  no_margin_of_safety: true
  no_expected_return: true
  no_zero_fill: true
  no_mock_sample_data: true
  no_new_data_fetch: true
  no_missing_finance_inference: true
inputs:
  step25_universe_rows: {step25_rows.as_posix()}
  step26_audit_rows: {step26_rows.as_posix()}
  step26_summary: {step26_summary.as_posix()}
  step28_market_snapshot_rows: {step28_rows.as_posix()}
  step28_summary: {step28_summary.as_posix()}
exports:
  output_dir: {output.as_posix()}
core_output_watchlist:
  - {step25_rows.as_posix()}
  - {step26_rows.as_posix()}
  - {step26_summary.as_posix()}
  - {step28_rows.as_posix()}
  - {step28_summary.as_posix()}
""".strip(),
        encoding="utf-8",
    )


def _config_dict() -> dict:
    return {
        "limits": {"expected_universe_size": 1, "shortlist_size": 50},
    }
