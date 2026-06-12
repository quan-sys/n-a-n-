from pathlib import Path

import pandas as pd
import pytest

from src.scale.step25_full_universe_1743_primary_only_scale import (
    FINAL_DECISIONS,
    Step25SafeRunBlocked,
    run_step25_full_universe_1743_primary_only_scale,
    scan_forbidden_terms,
)


REQUIRED_EXPORTS = {
    "full_universe_scale_summary.json",
    "full_universe_screening_rows.csv",
    "watchlist_candidates.csv",
    "manual_bctc_review_queue.csv",
    "blocked_tickers.csv",
    "failed_tickers.csv",
    "data_coverage_report.csv",
    "evidence_debt_report.json",
    "batch_run_manifest.csv",
    "source_confidence_summary.csv",
    "unresolved_fields_report.csv",
    "run_manifest.json",
}


def test_full_universe_run_requires_explicit_permission(tmp_path: Path):
    paths = _write_fixture(tmp_path, full_universe_allowed=False)

    with pytest.raises(Step25SafeRunBlocked):
        _run(paths)


def test_max_tickers_1743_is_respected(tmp_path: Path):
    paths = _write_fixture(tmp_path, ticker_count=1750)

    result = _run(paths, max_tickers=1743, batch_size=200)

    assert result.summary["actual_universe_count"] == 1750
    assert result.summary["processed_ticker_count"] == 1743


def test_batch_splitting_works(tmp_path: Path):
    paths = _write_fixture(tmp_path, ticker_count=5)

    result = _run(paths, max_tickers=5, batch_size=2)

    assert result.summary["batch_count"] == 3
    assert set(result.batch_run_manifest["batch_id"]) == {"batch_0001", "batch_0002", "batch_0003"}


def test_failed_ticker_is_logged_not_hidden(tmp_path: Path):
    paths = _write_fixture(tmp_path, ticker_count=3, force_failed_tickers=["T002"])

    result = _run(paths, max_tickers=3, batch_size=2)

    assert result.summary["failed_ticker_count"] == 1
    assert "T002" in set(result.failed_tickers["ticker"])


def test_resume_from_cache_works(tmp_path: Path):
    paths = _write_fixture(tmp_path, ticker_count=4)

    _run(paths, max_tickers=4, batch_size=2, resume_from_cache=False)
    result = _run(paths, max_tickers=4, batch_size=2, resume_from_cache=True)

    assert result.batch_run_manifest["cache_used"].map(str).str.lower().eq("true").all()


def test_missing_data_is_not_zero_filled(tmp_path: Path):
    paths = _write_fixture(tmp_path, ticker_count=2, missing_market_ticker="T002")

    result = _run(paths, max_tickers=2, batch_size=2)
    row = result.rows[result.rows["ticker"].eq("T002")].iloc[0]

    assert row["last_close"] == ""
    assert row["screening_status"] == "BLOCKED_INSUFFICIENT_MARKET_DATA"
    assert "last_close" in row["missing_fields"]


def test_confidence_labels_remain_provisional(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert set(result.rows["market_source_confidence"]) == {"PROVISIONAL_PRIMARY_ONLY"}
    assert set(result.rows["finance_source_confidence"]) == {"PROVISIONAL_LOW"}


def test_crosscheck_remains_not_available(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert set(result.rows["crosscheck_status"]) == {"NOT_AVAILABLE"}


def test_surviving_candidates_require_manual_bctc_review(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)
    survivors = result.rows[result.rows["screening_status"].eq("WATCHLIST_CANDIDATE")]

    assert not survivors.empty
    assert survivors["manual_bctc_required"].map(bool).all()


def test_forbidden_terms_do_not_appear(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    _run(paths)

    assert scan_forbidden_terms(paths["output"], extra_dirs=[paths["batches"]]) == []


def test_previous_step_outputs_are_not_mutated(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    previous = tmp_path / "previous.json"
    previous.write_text('{"ok": true}\n', encoding="utf-8")
    before = previous.read_text(encoding="utf-8")

    result = _run(paths, core_output_paths=[previous])

    assert previous.read_text(encoding="utf-8") == before
    assert result.run_manifest["previous_step_outputs_mutated"] is False


def test_final_decision_is_allowed_and_exports_exist(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert result.summary["final_decision"] in FINAL_DECISIONS
    assert REQUIRED_EXPORTS.issubset({path.name for path in paths["output"].iterdir()})


def _run(paths: dict[str, Path], **kwargs):
    return run_step25_full_universe_1743_primary_only_scale(
        config_path=paths["config"],
        output_dir=paths["output"],
        max_tickers=kwargs.pop("max_tickers", 10),
        batch_size=kwargs.pop("batch_size", 5),
        allow_partial=True,
        resume_from_cache=kwargs.pop("resume_from_cache", False),
        command_used="pytest step25",
        **kwargs,
    )


def _write_fixture(
    tmp_path: Path,
    *,
    ticker_count: int = 6,
    full_universe_allowed: bool = True,
    missing_market_ticker: str = "",
    force_failed_tickers: list[str] | None = None,
) -> dict[str, Path]:
    output = tmp_path / "out"
    raw = tmp_path / "raw"
    batches = output / "batches"
    universe = tmp_path / "universe.csv"
    market = tmp_path / "market.csv"
    finance = tmp_path / "finance.csv"
    quality = tmp_path / "quality.csv"
    config = tmp_path / "config.yaml"
    tickers = [f"T{index:03d}" for index in range(1, ticker_count + 1)]
    pd.DataFrame([_universe_row(ticker) for ticker in tickers]).to_csv(universe, index=False)
    pd.DataFrame([_market_row(ticker, missing=(ticker == missing_market_ticker)) for ticker in tickers]).to_csv(market, index=False)
    pd.DataFrame([_finance_row(ticker) for ticker in tickers]).to_csv(finance, index=False)
    pd.DataFrame([_quality_row(ticker) for ticker in tickers]).to_csv(quality, index=False)
    _write_config(
        config,
        universe=universe,
        market=market,
        finance=finance,
        quality=quality,
        output=output,
        raw=raw,
        batches=batches,
        full_universe_allowed=full_universe_allowed,
        force_failed_tickers=force_failed_tickers or [],
    )
    return {"config": config, "output": output, "raw": raw, "batches": batches}


def _universe_row(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "exchange": "HOSE",
        "company_name": f"{ticker} Corp",
        "source_name": "fixture_universe",
        "fetched_at": "2026-06-12T00:00:00+00:00",
    }


def _market_row(ticker: str, *, missing: bool) -> dict:
    return {
        "ticker": ticker,
        "exchange": "HOSE",
        "company_name": f"{ticker} Corp",
        "fetch_status": "" if missing else "FETCH_OK",
        "last_close": "" if missing else 10,
        "last_price_date": "" if missing else "2026-06-11",
        "avg_volume_20d": "" if missing else 1000,
        "avg_volume_60d": "" if missing else 1200,
        "last_volume": "" if missing else 900,
        "stale_days": "" if missing else 0,
        "trading_days_60d": "" if missing else 60,
        "missing_market_flag": missing,
        "stale_price_flag": False,
    }


def _finance_row(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "exchange": "HOSE",
        "company_name": f"{ticker} Corp",
        "revenue": "",
        "gross_profit": "",
        "net_income": "",
        "total_assets": "",
        "total_liabilities": "",
        "equity": "",
        "cfo": "",
        "capex": "",
        "source_confidence": "provisional_structured",
        "source_layer": "provisional_structured",
        "missing_fields": "revenue;gross_profit;net_income;total_assets;total_liabilities;equity;cfo;capex",
    }


def _quality_row(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "missing_required_fields": "revenue;gross_profit;net_income;total_assets;total_liabilities;equity;cfo;capex",
        "export_status": "PARTIAL_PROVISIONAL_DATA",
        "source_layer": "provisional_structured",
    }


def _write_config(
    path: Path,
    *,
    universe: Path,
    market: Path,
    finance: Path,
    quality: Path,
    output: Path,
    raw: Path,
    batches: Path,
    full_universe_allowed: bool,
    force_failed_tickers: list[str],
) -> None:
    def q(value: Path) -> str:
        return '"' + value.as_posix() + '"'

    forced = "[" + ", ".join(force_failed_tickers) + "]"
    path.write_text(
        "\n".join(
            [
                "step_id: STEP25-FULL-UNIVERSE-1743-PRIMARY-ONLY-SCALE",
                "mode: full_universe_primary_only_scale",
                "run:",
                "  sandbox_only: false",
                "  allow_partial: true",
                "  resume_from_cache: true",
                "limits:",
                "  max_tickers: 1743",
                "  batch_size: 100",
                f"  full_universe_allowed: {str(full_universe_allowed).lower()}",
                "  allow_limit_override: true",
                "source_confidence:",
                "  market_source_confidence: PROVISIONAL_PRIMARY_ONLY",
                "  finance_source_confidence_default: PROVISIONAL_LOW",
                "  crosscheck_status: NOT_AVAILABLE",
                "  verification_status: NEEDS_MANUAL_BCTC_REVIEW",
                "primary_sources:",
                "  independent_crosscheck_required: false",
                "  independent_crosscheck_status: NOT_AVAILABLE",
                "safety:",
                "  no_recommendation: true",
                "  no_buy_sell_hold: true",
                "  no_target_price: true",
                "  no_fair_value: true",
                "  no_intrinsic_value: true",
                "  no_margin_of_safety: true",
                "  no_expected_return: true",
                "  no_entry_exit_price: true",
                "  no_portfolio_recommendation: true",
                "  no_strategy_claim: true",
                "  no_pdf_ocr: true",
                "  no_official_bctc_scrape: true",
                "  no_zero_fill: true",
                "  no_previous_report_mutation: true",
                "  no_stage_promotion_to_investment_ready: true",
                "batching:",
                "  batch_size: 100",
                "  resume_from_cache: true",
                "  failed_ticker_policy: LOG_AND_CONTINUE",
                "filters:",
                "  stale_price_max_days: 10",
                "  min_recent_volume: 1",
                "  min_recent_trading_value: 1",
                "  require_minimum_finance_presence: false",
                "inputs:",
                "  universe_candidates:",
                f"    - {q(universe)}",
                "  market_primary:",
                f"    - {q(market)}",
                f"  market_fallback: {q(market)}",
                f"  finance_latest_wide: {q(finance)}",
                f"  finance_quality_flags: {q(quality)}",
                "outputs:",
                f"  output_dir: {q(output)}",
                f"  raw_cache_dir: {q(raw)}",
                f"  batch_manifest_dir: {q(batches)}",
                "testing:",
                f"  force_failed_tickers: {forced}",
                "",
            ]
        ),
        encoding="utf-8",
    )
