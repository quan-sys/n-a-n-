from pathlib import Path

import pandas as pd
import pytest

from src.reporting.step22_l7_weekly_report_manual_review import (
    FINAL_DECISIONS,
    WATCHLIST_STATUSES,
    Step22SafeRunBlocked,
    run_step22_l7_weekly_report_manual_review,
    scan_forbidden_terms,
)


REQUIRED_EXPORTS = {
    "weekly_report.md",
    "watchlist_candidates.csv",
    "manual_review_queue.csv",
    "reject_log.csv",
    "evidence_summary.csv",
    "data_quality_summary.csv",
    "sector_cycle_summary.csv",
    "company_engine_summary.csv",
    "risk_warning_summary.csv",
    "source_conflict_report.csv",
    "unresolved_fields_report.csv",
    "weekly_report_summary.json",
    "run_manifest.json",
}


def test_required_output_files_exist(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    _run(paths)

    assert REQUIRED_EXPORTS.issubset({path.name for path in paths["output"].iterdir()})


def test_forbidden_terms_do_not_appear(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    _run(paths)

    assert scan_forbidden_terms(paths["output"]) == []


def test_watchlist_statuses_are_allowed(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert set(result.rows["watchlist_status"]).issubset(WATCHLIST_STATUSES)


def test_high_confidence_watchlist_keeps_provisional_warnings(tmp_path: Path):
    paths = _write_fixture(tmp_path, step20_status="STEP20_CONTEXT_READY", shadow_status="SHADOW_READY_DIAGNOSTIC_ONLY", liquidity_bucket="LIQUIDITY_RISK_LOW")

    result = _run(paths)
    row = result.rows[result.rows["ticker"].eq("T001")].iloc[0]

    assert row["watchlist_status"] == "HIGH_CONFIDENCE_WATCHLIST"
    assert bool(row["manual_review_required"]) is True
    assert row["finance_source_confidence"] == "PROVISIONAL_LOW"
    assert row["verification_status"] == "NEEDS_MANUAL_BCTC_REVIEW"


def test_missing_inputs_are_reported_not_hidden(tmp_path: Path):
    paths = _write_fixture(tmp_path, omit_step19=True)

    result = _run(paths)

    assert result.summary["missing_input_files"]
    assert "step19_rows" in result.summary["missing_input_files"][0]
    data_quality = (paths["output"] / "data_quality_summary.csv").read_text(encoding="utf-8")
    assert "missing_input_files" in data_quality


def test_missing_fields_are_not_zero_filled(tmp_path: Path):
    paths = _write_fixture(tmp_path, missing_market_ticker="T002")

    result = _run(paths)
    row = result.rows[result.rows["ticker"].eq("T002")].iloc[0]

    assert "last_close" in row["missing_fields"]
    assert row["watchlist_status"] == "INSUFFICIENT_DATA"
    unresolved = (paths["output"] / "unresolved_fields_report.csv").read_text(encoding="utf-8")
    assert "last_close" in unresolved


def test_source_confidence_fields_present_on_every_row(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    for column in ["market_source_confidence", "finance_source_confidence", "crosscheck_status", "verification_status"]:
        assert column in result.rows.columns
        assert not result.rows[column].astype(str).eq("").any()


def test_previous_outputs_are_not_mutated(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    previous = tmp_path / "previous.csv"
    previous.write_text("ticker,value\nT001,1\n", encoding="utf-8")
    before = previous.read_text(encoding="utf-8")

    result = _run(paths, core_output_paths=[previous])

    assert previous.read_text(encoding="utf-8") == before
    assert result.run_manifest["previous_step_outputs_mutated"] is False


def test_full_universe_blocked_by_default(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    with pytest.raises(Step22SafeRunBlocked):
        _run(paths, request_full_universe=True)


def test_final_decision_is_allowed(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert result.summary["final_decision"] in FINAL_DECISIONS


def _run(paths: dict[str, Path], **kwargs):
    return run_step22_l7_weekly_report_manual_review(
        config_path=paths["config"],
        output_dir=paths["output"],
        limit=kwargs.pop("limit", 100),
        allow_partial=True,
        command_used="pytest step22",
        **kwargs,
    )


def _write_fixture(
    tmp_path: Path,
    *,
    ticker_count: int = 3,
    step20_status: str = "STEP20_INSUFFICIENT_DATA",
    shadow_status: str = "SHADOW_CONDITIONAL_DIAGNOSTIC_ONLY",
    liquidity_bucket: str = "LIQUIDITY_RISK_MODERATE",
    missing_market_ticker: str = "",
    omit_step19: bool = False,
) -> dict[str, Path]:
    tickers = [f"T{index:03d}" for index in range(1, ticker_count + 1)]
    step21 = tmp_path / "step21.csv"
    step20 = tmp_path / "step20.csv"
    step19 = tmp_path / "step19.csv"
    step05a = tmp_path / "step05a.csv"
    manual05a = tmp_path / "manual05a.csv"
    quality = tmp_path / "quality.csv"
    market = tmp_path / "market.csv"
    config = tmp_path / "config.yaml"
    output = tmp_path / "out"

    pd.DataFrame([_step21_row(ticker, missing=(ticker == missing_market_ticker), liquidity_bucket=liquidity_bucket) for ticker in tickers]).to_csv(step21, index=False)
    pd.DataFrame([_step20_row(ticker, step20_status=step20_status) for ticker in tickers]).to_csv(step20, index=False)
    if not omit_step19:
        pd.DataFrame([_step19_row(ticker, shadow_status=shadow_status) for ticker in tickers]).to_csv(step19, index=False)
    pd.DataFrame([_step05a_row(ticker) for ticker in tickers]).to_csv(step05a, index=False)
    pd.DataFrame([_step05a_row(ticker) for ticker in tickers]).to_csv(manual05a, index=False)
    pd.DataFrame([_quality_row(ticker) for ticker in tickers]).to_csv(quality, index=False)
    pd.DataFrame([_market_row(ticker) for ticker in tickers]).to_csv(market, index=False)
    _write_config(config, step21=step21, step20=step20, step19=step19, step05a=step05a, manual05a=manual05a, quality=quality, market=market, output=output)
    return {"config": config, "output": output}


def _step21_row(ticker: str, *, missing: bool, liquidity_bucket: str) -> dict:
    return {
        "ticker": ticker,
        "timing_risk_bucket": "TIMING_INSUFFICIENT_DATA" if missing else "TIMING_RISK_MODERATE",
        "liquidity_risk_bucket": "LIQUIDITY_INSUFFICIENT_DATA" if missing else liquidity_bucket,
        "technical_warning_flags": '["PRIMARY_ONLY_MARKET_DATA"]',
        "liquidity_warning_flags": '["PRIMARY_ONLY_LIQUIDITY_DATA"]',
        "manual_review_required": True,
        "missing_fields": '["last_close"]' if missing else "[]",
    }


def _step20_row(ticker: str, *, step20_status: str) -> dict:
    return {
        "ticker": ticker,
        "company_name": f"{ticker} Corp",
        "primary_micro_sector": "TEST_SECTOR::TEST_TYPE",
        "archetype": "TEST_TYPE",
        "valuation_context": "VALUATION_CONTEXT_INSUFFICIENT_DATA",
        "step20_status": step20_status,
        "risk_flags": '["OFFICIAL_BCTC_NOT_VERIFIED"]',
        "manual_review_required": True,
        "missing_fields": "[]",
        "source_conflicts": "[]",
    }


def _step19_row(ticker: str, *, shadow_status: str) -> dict:
    return {
        "ticker": ticker,
        "shadow_status": shadow_status,
        "missing_required_fields": "",
    }


def _step05a_row(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "screening_status": "WATCHLIST_CANDIDATE",
        "manual_review_required": True,
        "manual_bctc_required": True,
        "missing_fields": "[]",
        "block_reasons": "[]",
    }


def _quality_row(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "missing_required_fields": "",
        "export_status": "PARTIAL_PROVISIONAL_DATA",
    }


def _market_row(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "last_close": 10,
        "last_price_date": "2026-06-11",
    }


def _write_config(
    path: Path,
    *,
    step21: Path,
    step20: Path,
    step19: Path,
    step05a: Path,
    manual05a: Path,
    quality: Path,
    market: Path,
    output: Path,
) -> None:
    def q(value: Path) -> str:
        return '"' + value.as_posix() + '"'

    path.write_text(
        "\n".join(
            [
                "step_id: STEP22-L7-WEEKLY-REPORT-MANUAL-REVIEW",
                "mode: weekly_report_manual_review_only",
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
                "  no_target_price: true",
                "  no_fair_value: true",
                "  no_intrinsic_value: true",
                "  no_margin_of_safety: true",
                "  no_expected_return: true",
                "  no_entry_exit_price: true",
                "  no_stoploss_takeprofit: true",
                "  no_portfolio_recommendation: true",
                "  no_pdf_ocr: true",
                "  no_official_bctc_scrape: true",
                "  no_zero_fill: true",
                "  no_core_output_mutation: true",
                "  no_stage_promotion_to_investment_ready: true",
                "inputs:",
                f"  step21_rows: {q(step21)}",
                f"  step21_manual_queue: {q(step21)}",
                f"  step20_rows: {q(step20)}",
                f"  step19_rows: {q(step19)}",
                f"  step05a_rows: {q(step05a)}",
                f"  step05a_manual_queue: {q(manual05a)}",
                f"  provisional_data_quality_flags: {q(quality)}",
                f"  market_snapshot: {q(market)}",
                "exports:",
                f"  output_dir: {q(output)}",
                "",
            ]
        ),
        encoding="utf-8",
    )
