from pathlib import Path

import pandas as pd
import pytest

from src.screening.step05a_primary_only_screening import (
    FINAL_DECISIONS,
    FORBIDDEN_FINAL_DECISIONS,
    Step05ASafeRunBlocked,
    run_step05a_primary_only_screening,
    scan_forbidden_terms,
)


REQUIRED_EXPORTS = {
    "primary_only_screening_summary.json",
    "primary_only_screening_rows.csv",
    "watchlist_candidates.csv",
    "manual_bctc_review_queue.csv",
    "blocked_tickers.csv",
    "evidence_debt_report.json",
    "run_manifest.json",
}


def test_forbidden_terms_do_not_appear_in_outputs(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    _run(paths)

    assert scan_forbidden_terms(paths["output"]) == []


def test_source_confidence_fields_present_on_every_row(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    for column in ["market_source_confidence", "finance_source_confidence", "crosscheck_status", "verification_status"]:
        assert column in result.rows.columns
        assert not result.rows[column].astype(str).eq("").any()


def test_crosscheck_is_not_falsely_passed(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert set(result.rows["crosscheck_status"]) == {"NOT_AVAILABLE"}
    assert "PASSED" not in set(result.rows.get("independent_crosscheck_status", pd.Series(dtype=str)).astype(str))
    assert "VERIFIED" not in set(result.rows["market_source_confidence"].astype(str))


def test_watchlist_candidates_require_manual_bctc(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)
    candidates = result.rows[result.rows["screening_status"].eq("WATCHLIST_CANDIDATE")]

    assert not candidates.empty
    assert candidates["manual_review_required"].map(bool).all()
    assert candidates["manual_bctc_required"].map(bool).all()
    assert set(candidates["verification_status"]) == {"NEEDS_MANUAL_BCTC_REVIEW"}
    assert candidates["finance_crosscheck_required_later"].map(bool).all()


def test_missing_finance_is_not_zero_filled(tmp_path: Path):
    paths = _write_fixture(tmp_path, missing_finance_ticker="T001")

    result = _run(paths)
    row = result.rows[result.rows["ticker"].eq("T001")].iloc[0]

    assert "net_income" in row["finance_missing_fields"]
    assert '"net_income"' in row["missing_fields"]
    assert row["finance_missing_fields"] != "0"


def test_max_tickers_is_respected(tmp_path: Path):
    paths = _write_fixture(tmp_path, ticker_count=9, max_tickers=5)

    result = _run(paths, limit=9)

    assert result.summary["processed_ticker_count"] == 5
    assert len(result.rows) == 5


def test_full_universe_blocked_by_default(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    with pytest.raises(Step05ASafeRunBlocked):
        _run(paths, request_full_universe=True)


def test_previous_report_paths_are_not_mutated(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    core = tmp_path / "previous_report.csv"
    core.write_text("ticker,value\nT001,1\n", encoding="utf-8")
    before = core.read_text(encoding="utf-8")

    result = _run(paths, core_output_paths=[core])

    assert core.read_text(encoding="utf-8") == before
    assert result.summary["final_decision"] in FINAL_DECISIONS
    assert result.run_manifest["core_outputs_modified"] is False


def test_required_export_files_exist(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    _run(paths)

    assert REQUIRED_EXPORTS.issubset({path.name for path in paths["output"].iterdir()})


def test_final_decision_allowed_list(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert result.summary["final_decision"] in FINAL_DECISIONS
    assert result.summary["final_decision"] not in FORBIDDEN_FINAL_DECISIONS


def _run(paths: dict[str, Path], **kwargs):
    return run_step05a_primary_only_screening(
        config_path=paths["config"],
        output_dir=paths["output"],
        limit=kwargs.pop("limit", 100),
        allow_partial=True,
        command_used="pytest step05a",
        **kwargs,
    )


def _write_fixture(
    tmp_path: Path,
    *,
    ticker_count: int = 7,
    max_tickers: int = 100,
    missing_finance_ticker: str = "T003",
) -> dict[str, Path]:
    market = tmp_path / "market.csv"
    finance = tmp_path / "finance.csv"
    quality = tmp_path / "quality.csv"
    config = tmp_path / "config.yaml"
    output = tmp_path / "out"
    tickers = [f"T{index:03d}" for index in range(1, ticker_count + 1)]
    pd.DataFrame(
        [
            {
                "ticker": ticker,
                "fetch_status": "FETCH_OK",
                "last_close": 10.0 + index,
                "last_price_date": "2026-06-11",
                "last_volume": 1000,
                "avg_volume_20d": 1000,
                "avg_volume_60d": 1000,
                "trading_days_60d": 60,
                "missing_market_flag": False,
                "stale_price_flag": False,
                "stale_days": 0,
            }
            for index, ticker in enumerate(tickers)
        ]
    ).to_csv(market, index=False)
    finance_rows = []
    for ticker in tickers:
        missing_fields = ["net_income"] if ticker == missing_finance_ticker else []
        finance_rows.append(
            {
                "ticker": ticker,
                "period": "2025",
                "period_type": "year",
                "fiscal_year": 2025,
                "revenue": 100,
                "gross_profit": 20,
                "net_income": "" if ticker == missing_finance_ticker else 5,
                "total_assets": 200,
                "total_liabilities": 100,
                "equity": 100,
                "cfo": 10,
                "capex": "",
                "source_confidence": "provisional_structured",
                "source_layer": "provisional_structured",
                "missing_fields": ";".join(missing_fields + ["capex"]),
            }
        )
    pd.DataFrame(finance_rows).to_csv(finance, index=False)
    pd.DataFrame([{"ticker": ticker, "export_status": "PARTIAL_PROVISIONAL_DATA"} for ticker in tickers]).to_csv(quality, index=False)
    _write_config(config, market=market, finance=finance, quality=quality, max_tickers=max_tickers)
    return {"market": market, "finance": finance, "quality": quality, "config": config, "output": output}


def _write_config(path: Path, *, market: Path, finance: Path, quality: Path, max_tickers: int) -> None:
    path.write_text(
        "\n".join(
            [
                "step_id: STEP05A-PRIMARY-ONLY-SCREENING-MODE",
                "mode: primary_only_screening",
                "run:",
                "  sandbox_only: true",
                "  allow_partial: true",
                "limits:",
                f"  max_tickers: {max_tickers}",
                "  full_universe_allowed: false",
                "  top500_allowed: false",
                "  allow_limit_override: true",
                "source_confidence:",
                "  market_source_confidence: PROVISIONAL_PRIMARY_ONLY",
                "  finance_source_confidence_default: PROVISIONAL_LOW",
                "  crosscheck_status: NOT_AVAILABLE",
                "  verification_status: NEEDS_MANUAL_BCTC_REVIEW",
                "safety:",
                "  no_recommendation: true",
                "  no_valuation: true",
                "  no_target_price: true",
                "  no_fair_value: true",
                "  no_margin_of_safety: true",
                "  no_zero_fill: true",
                "  no_missing_finance_inference: true",
                "  no_pdf_ocr: true",
                "  no_official_bctc_scrape: true",
                "  no_core_output_mutation: true",
                "  no_stage_promotion_to_investment_ready: true",
                "filters:",
                "  stale_price_max_days: 10",
                "  min_market_rows: 1",
                "  min_recent_volume: 1",
                "  min_recent_trading_value: 1",
                "  require_minimum_finance_presence: false",
                "inputs:",
                f"  market_snapshot: {market.as_posix()}",
                f"  finance_latest_wide: {finance.as_posix()}",
                f"  finance_quality_flags: {quality.as_posix()}",
                "exports:",
                "  output_dir: ignored_in_test",
                "",
            ]
        ),
        encoding="utf-8",
    )
