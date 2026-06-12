from pathlib import Path

import pandas as pd
import pytest

from src.screening.step21_l6_timing_liquidity_context import (
    FINAL_DECISIONS,
    FORBIDDEN_FINAL_DECISIONS,
    Step21SafeRunBlocked,
    run_step21_l6_timing_liquidity_context,
    scan_forbidden_terms,
)


REQUIRED_EXPORTS = {
    "timing_liquidity_context_summary.json",
    "timing_liquidity_context_rows.csv",
    "timing_warning_flags.csv",
    "liquidity_warning_flags.csv",
    "manual_review_queue.csv",
    "evidence_debt_report.json",
    "run_manifest.json",
}


def test_forbidden_terms_do_not_appear_in_outputs(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    _run(paths)

    assert scan_forbidden_terms(paths["output"]) == []


def test_missing_market_fields_are_not_zero_filled(tmp_path: Path):
    paths = _write_fixture(tmp_path, missing_market_ticker="T001")

    result = _run(paths)
    row = result.rows[result.rows["ticker"].eq("T001")].iloc[0]

    assert row["last_close"] == ""
    assert "last_close" in row["missing_fields"]
    assert row["timing_risk_bucket"] == "TIMING_INSUFFICIENT_DATA"
    assert row["liquidity_risk_bucket"] == "LIQUIDITY_INSUFFICIENT_DATA"


def test_every_row_has_source_confidence_fields(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    for column in ["market_source_confidence", "finance_source_confidence", "crosscheck_status", "verification_status"]:
        assert column in result.rows.columns
        assert not result.rows[column].astype(str).eq("").any()


def test_crosscheck_status_remains_not_available(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert set(result.rows["crosscheck_status"]) == {"NOT_AVAILABLE"}


def test_no_ticker_is_promoted_to_investment_ready(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    _run(paths)
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths["output"].iterdir() if path.suffix in {".csv", ".json"})

    assert "investment-ready" not in text.lower()


def test_full_universe_blocked_by_default(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    with pytest.raises(Step21SafeRunBlocked):
        _run(paths, request_full_universe=True)


def test_max_tickers_respected(tmp_path: Path):
    paths = _write_fixture(tmp_path, ticker_count=8, max_tickers=5)

    result = _run(paths, limit=8)

    assert result.summary["processed_ticker_count"] == 5
    assert len(result.rows) == 5


def test_previous_outputs_are_not_mutated(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    core = tmp_path / "previous.csv"
    core.write_text("ticker,value\nT001,1\n", encoding="utf-8")
    before = core.read_text(encoding="utf-8")

    result = _run(paths, core_output_paths=[core])

    assert core.read_text(encoding="utf-8") == before
    assert result.run_manifest["core_outputs_modified"] is False


def test_manual_review_triggered_when_timing_liquidity_insufficient(tmp_path: Path):
    paths = _write_fixture(tmp_path, missing_market_ticker="T002")

    result = _run(paths)
    row = result.rows[result.rows["ticker"].eq("T002")].iloc[0]

    assert bool(row["manual_review_required"]) is True
    assert bool(row["timing_manual_review_required"]) is True
    assert bool(row["liquidity_manual_review_required"]) is True


def test_final_decision_allowed_and_exports_exist(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert result.summary["final_decision"] in FINAL_DECISIONS
    assert result.summary["final_decision"] not in FORBIDDEN_FINAL_DECISIONS
    assert REQUIRED_EXPORTS.issubset({path.name for path in paths["output"].iterdir()})


def _run(paths: dict[str, Path], **kwargs):
    return run_step21_l6_timing_liquidity_context(
        config_path=paths["config"],
        output_dir=paths["output"],
        limit=kwargs.pop("limit", 100),
        allow_partial=True,
        command_used="pytest step21",
        **kwargs,
    )


def _write_fixture(tmp_path: Path, *, ticker_count: int = 6, max_tickers: int = 100, missing_market_ticker: str = "") -> dict[str, Path]:
    tickers = [f"T{index:03d}" for index in range(1, ticker_count + 1)]
    step20 = tmp_path / "step20.csv"
    step05a = tmp_path / "step05a.csv"
    market = tmp_path / "market.csv"
    config = tmp_path / "config.yaml"
    output = tmp_path / "out"
    pd.DataFrame([_step20_row(ticker) for ticker in tickers]).to_csv(step20, index=False)
    pd.DataFrame([_step05a_row(ticker, missing=(ticker == missing_market_ticker)) for ticker in tickers]).to_csv(step05a, index=False)
    pd.DataFrame([_market_row(ticker, missing=(ticker == missing_market_ticker)) for ticker in tickers]).to_csv(market, index=False)
    _write_config(config, step20=step20, step05a=step05a, market=market, max_tickers=max_tickers)
    return {"config": config, "output": output}


def _step20_row(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "market_source_confidence": "PROVISIONAL_PRIMARY_ONLY",
        "finance_source_confidence": "PROVISIONAL_LOW",
        "crosscheck_status": "NOT_AVAILABLE",
        "verification_status": "NEEDS_MANUAL_BCTC_REVIEW",
        "manual_review_required": True,
    }


def _step05a_row(ticker: str, *, missing: bool) -> dict:
    return {
        "ticker": ticker,
        "market_source_confidence": "PROVISIONAL_PRIMARY_ONLY",
        "finance_source_confidence": "PROVISIONAL_LOW",
        "crosscheck_status": "NOT_AVAILABLE",
        "verification_status": "NEEDS_MANUAL_BCTC_REVIEW",
        "last_close": "" if missing else 10,
        "last_price_date": "" if missing else "2026-06-11",
        "avg_volume_20d": "" if missing else 1000,
        "avg_volume_60d": 1000,
        "last_volume": 1100,
        "stale_days": 0,
        "trading_days_60d": 60,
        "recent_trading_value": "" if missing else 10000,
    }


def _market_row(ticker: str, *, missing: bool) -> dict:
    return {
        "ticker": ticker,
        "last_close": "" if missing else 10,
        "last_price_date": "" if missing else "2026-06-11",
        "avg_volume_20d": "" if missing else 1000,
        "avg_volume_60d": 1000,
        "last_volume": 1100,
        "stale_days": 0,
        "trading_days_60d": 60,
    }


def _write_config(path: Path, *, step20: Path, step05a: Path, market: Path, max_tickers: int) -> None:
    path.write_text(
        "\n".join(
            [
                "step_id: STEP21-L6-TIMING-LIQUIDITY-CONTEXT",
                "mode: timing_liquidity_context_only",
                "run:",
                "  sandbox_only: true",
                "  allow_partial: true",
                "limits:",
                f"  max_tickers: {max_tickers}",
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
                "  no_entry_exit_price: true",
                "  no_stoploss_takeprofit: true",
                "  no_target_price: true",
                "  no_fair_value: true",
                "  no_expected_return: true",
                "  no_portfolio_recommendation: true",
                "  no_pdf_ocr: true",
                "  no_official_bctc_scrape: true",
                "  no_zero_fill: true",
                "  no_core_output_mutation: true",
                "  no_stage_promotion_to_investment_ready: true",
                "thresholds:",
                "  min_avg_volume_20d: 1",
                "  min_recent_trading_value: 1",
                "  stale_price_max_days: 10",
                "  abnormal_volume_warning_ratio: 2.0",
                "inputs:",
                f"  step20_rows: {step20.as_posix()}",
                f"  step05a_rows: {step05a.as_posix()}",
                f"  watchlist_candidates: {step05a.as_posix()}",
                f"  market_snapshot: {market.as_posix()}",
                "exports:",
                "  output_dir: ignored_in_test",
                "",
            ]
        ),
        encoding="utf-8",
    )
