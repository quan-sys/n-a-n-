from pathlib import Path

import pandas as pd
import pytest

from src.monitoring.step23_backtest_monitoring_module import (
    FINAL_DECISIONS,
    Step23SafeRunBlocked,
    run_step23_backtest_monitoring_module,
    scan_forbidden_terms,
)


REQUIRED_EXPORTS = {
    "monitoring_dashboard.csv",
    "watchlist_history.csv",
    "watchlist_change_log.csv",
    "score_change_log.csv",
    "reject_reason_trend.csv",
    "manual_review_trend.csv",
    "data_coverage_trend.csv",
    "source_conflict_trend.csv",
    "sector_signal_drift.csv",
    "company_score_drift.csv",
    "backtest_summary.md",
    "monitoring_summary.json",
    "run_manifest.json",
}


def test_required_output_files_exist(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    _run(paths)

    assert REQUIRED_EXPORTS.issubset({path.name for path in paths["output"].iterdir()})


def test_snapshot_is_created(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert result.summary["snapshot_created"] is True
    assert list(paths["snapshots"].glob("snapshot_*.csv"))


def test_previous_snapshot_comparison_works(tmp_path: Path):
    paths = _write_fixture(tmp_path, with_previous=True)

    result = _run(paths)

    assert result.summary["previous_snapshot_found"] is True
    assert result.summary["watchlist_change_count"] >= 1
    assert "STATUS_CHANGED" in set(result.watchlist_change_log["change_type"])


def test_no_forbidden_terms_appear(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    _run(paths)

    assert scan_forbidden_terms(paths["output"]) == []


def test_no_strategy_outperformance_claim_appears(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    _run(paths)
    text = (paths["output"] / "backtest_summary.md").read_text(encoding="utf-8").lower()

    assert "strategy beats market" not in text
    assert "guaranteed alpha" not in text


def test_missing_history_reports_insufficient_history(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert result.summary["previous_snapshot_found"] is False
    assert "insufficient_history" in set(result.monitoring_dashboard["trend_direction"])


def test_data_coverage_trend_uses_available_fields(tmp_path: Path):
    paths = _write_fixture(tmp_path, with_previous=True, current_missing_fields='["net_income","equity"]')

    result = _run(paths)
    row = result.data_coverage_trend[result.data_coverage_trend["metric_name"].eq("unresolved_field_count")].iloc[0]

    assert int(row["current_value"]) == 2
    assert row["trend_direction"] in {"increased", "decreased", "unchanged"}


def test_missing_score_is_not_zero_filled(tmp_path: Path):
    paths = _write_fixture(tmp_path, blank_score_ticker="T002")

    result = _run(paths)
    row = result.company_score_drift[result.company_score_drift["ticker"].eq("T002")].iloc[0]

    assert row["current_confidence_score"] == "UNKNOWN"
    assert row["current_confidence_score"] != 0
    assert row["score_change"] == "INSUFFICIENT_HISTORY"


def test_full_universe_blocked_by_default(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    with pytest.raises(Step23SafeRunBlocked):
        _run(paths, request_full_universe=True)


def test_final_decision_is_allowed(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert result.summary["final_decision"] in FINAL_DECISIONS


def _run(paths: dict[str, Path], **kwargs):
    return run_step23_backtest_monitoring_module(
        config_path=paths["config"],
        output_dir=paths["output"],
        limit=kwargs.pop("limit", 100),
        allow_partial=True,
        command_used="pytest step23",
        **kwargs,
    )


def _write_fixture(
    tmp_path: Path,
    *,
    with_previous: bool = False,
    current_missing_fields: str = "[]",
    blank_score_ticker: str = "",
) -> dict[str, Path]:
    output = tmp_path / "out"
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    watchlist = tmp_path / "watchlist.csv"
    manual = tmp_path / "manual.csv"
    reject = tmp_path / "reject.csv"
    data_quality = tmp_path / "quality.csv"
    step21 = tmp_path / "step21.csv"
    step20 = tmp_path / "step20.csv"
    step19 = tmp_path / "step19.csv"
    market = tmp_path / "market.csv"
    config = tmp_path / "config.yaml"
    tickers = ["T001", "T002", "T003"]
    pd.DataFrame([_watchlist_row(ticker, current_missing_fields=current_missing_fields if ticker == "T001" else "[]", blank_score=(ticker == blank_score_ticker)) for ticker in tickers]).to_csv(watchlist, index=False)
    pd.DataFrame([_manual_row(ticker) for ticker in tickers]).to_csv(manual, index=False)
    pd.DataFrame(columns=["ticker", "reject_reason"]).to_csv(reject, index=False)
    pd.DataFrame([{"metric": "unresolved_field_count", "value": 2 if current_missing_fields != "[]" else 0}]).to_csv(data_quality, index=False)
    pd.DataFrame([{"ticker": ticker, "timing_risk_bucket": "TIMING_RISK_MODERATE", "liquidity_risk_bucket": "LIQUIDITY_RISK_LOW"} for ticker in tickers]).to_csv(step21, index=False)
    pd.DataFrame([{"ticker": ticker} for ticker in tickers]).to_csv(step20, index=False)
    pd.DataFrame([{"ticker": ticker} for ticker in tickers]).to_csv(step19, index=False)
    pd.DataFrame([{"ticker": ticker} for ticker in tickers]).to_csv(market, index=False)
    if with_previous:
        pd.DataFrame(
            [
                {
                    "snapshot_id": "snapshot_20000101_000000Z",
                    "snapshot_created_at": "2000-01-01T00:00:00+00:00",
                    "ticker": "T001",
                    "company_name": "T001 Corp",
                    "micro_sector": "TEST",
                    "watchlist_status": "MANUAL_REVIEW",
                    "confidence_score": 30,
                    "manual_review_required": True,
                    "missing_fields": "[]",
                    "source_conflicts": "[]",
                    "reject_reason": "",
                    "cycle_status": "INSUFFICIENT_DATA",
                    "survival_status": "UNKNOWN",
                    "valuation_context": "INSUFFICIENT_DATA",
                    "timing_liquidity_status": "TIMING_RISK_MODERATE|LIQUIDITY_RISK_LOW",
                    "market_source_confidence": "PROVISIONAL_PRIMARY_ONLY",
                    "finance_source_confidence": "PROVISIONAL_LOW",
                    "crosscheck_status": "NOT_AVAILABLE",
                    "verification_status": "NEEDS_MANUAL_BCTC_REVIEW",
                }
            ]
        ).to_csv(snapshots / "snapshot_20000101_000000Z.csv", index=False)
    _write_config(
        config,
        watchlist=watchlist,
        manual=manual,
        reject=reject,
        data_quality=data_quality,
        step21=step21,
        step20=step20,
        step19=step19,
        market=market,
        snapshots=snapshots,
        output=output,
    )
    return {"config": config, "output": output, "snapshots": snapshots}


def _watchlist_row(ticker: str, *, current_missing_fields: str, blank_score: bool) -> dict:
    return {
        "ticker": ticker,
        "company_name": f"{ticker} Corp",
        "micro_sector": "TEST",
        "watchlist_status": "WATCH_ONLY",
        "confidence_score": "" if blank_score else 45,
        "manual_review_required": True,
        "missing_fields": current_missing_fields,
        "source_conflicts": "[]",
        "cycle_status": "INSUFFICIENT_DATA",
        "survival_status": "UNKNOWN",
        "valuation_context": "INSUFFICIENT_DATA",
        "timing_liquidity_status": "TIMING_RISK_MODERATE|LIQUIDITY_RISK_LOW",
    }


def _manual_row(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "company_name": f"{ticker} Corp",
        "watchlist_status": "WATCH_ONLY",
        "manual_review_required": True,
        "missing_fields": "[]",
        "source_conflicts": "[]",
    }


def _write_config(
    path: Path,
    *,
    watchlist: Path,
    manual: Path,
    reject: Path,
    data_quality: Path,
    step21: Path,
    step20: Path,
    step19: Path,
    market: Path,
    snapshots: Path,
    output: Path,
) -> None:
    def q(value: Path) -> str:
        return '"' + value.as_posix() + '"'

    path.write_text(
        "\n".join(
            [
                "step_id: STEP23-BACKTEST-MONITORING-MODULE",
                "mode: monitoring_filter_stability_only",
                "run:",
                "  sandbox_only: true",
                "  allow_partial: true",
                "limits:",
                "  max_tickers: 100",
                "  full_universe_allowed: false",
                "  allow_limit_override: true",
                "source_confidence:",
                "  market_source_confidence: PROVISIONAL_PRIMARY_ONLY",
                "  finance_source_confidence_default: PROVISIONAL_LOW",
                "  crosscheck_status: NOT_AVAILABLE",
                "  verification_status: NEEDS_MANUAL_BCTC_REVIEW",
                "safety:",
                "  no_recommendation: true",
                "  no_buy_sell_hold: true",
                "  no_strategy_claim: true",
                "  no_alpha_claim: true",
                "  no_expected_profit: true",
                "  no_expected_return: true",
                "  no_target_price: true",
                "  no_fair_value: true",
                "  no_margin_of_safety: true",
                "  no_entry_exit_price: true",
                "  no_portfolio_recommendation: true",
                "  no_zero_fill: true",
                "  no_core_output_mutation: true",
                "monitoring:",
                "  initialize_snapshot_if_missing: true",
                "  compare_to_previous_snapshot_if_available: true",
                "inputs:",
                f"  step22_watchlist: {q(watchlist)}",
                f"  step22_manual_review_queue: {q(manual)}",
                f"  step22_reject_log: {q(reject)}",
                f"  step22_data_quality_summary: {q(data_quality)}",
                f"  step21_rows: {q(step21)}",
                f"  step20_rows: {q(step20)}",
                f"  step19_rows: {q(step19)}",
                f"  market_snapshot: {q(market)}",
                f"  monitoring_snapshots_dir: {q(snapshots)}",
                "exports:",
                f"  output_dir: {q(output)}",
                "",
            ]
        ),
        encoding="utf-8",
    )
