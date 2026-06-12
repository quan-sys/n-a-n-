from pathlib import Path

import pandas as pd
import pytest

from src.screening.step20_l5_valuation_risk_context import (
    FINAL_DECISIONS,
    FORBIDDEN_FINAL_DECISIONS,
    Step20SafeRunBlocked,
    run_step20_l5_valuation_risk_context,
    scan_forbidden_terms,
)


REQUIRED_EXPORTS = {
    "step20_valuation_risk_summary.json",
    "step20_valuation_risk_rows.csv",
    "valuation_context_by_ticker.csv",
    "risk_flags_by_ticker.csv",
    "manual_review_queue_step20.csv",
    "peer_context_summary.csv",
    "evidence_debt_step20.json",
    "run_manifest.json",
}


def test_no_forbidden_terms_in_output_files(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    _run(paths)

    assert scan_forbidden_terms(paths["output"]) == []


def test_no_action_or_price_objective_terms(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    _run(paths)
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths["output"].iterdir() if path.suffix in {".csv", ".json"})
    lowered = text.lower()

    for term in ["target price", "fair value", "intrinsic value", "margin of safety"]:
        assert term not in lowered


def test_no_buy_sell_hold_labels(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    _run(paths)
    assert scan_forbidden_terms(paths["output"]) == []


def test_missing_finance_fields_are_not_zero_filled(tmp_path: Path):
    paths = _write_fixture(tmp_path, missing_finance_ticker="T001")

    result = _run(paths)
    row = result.rows[result.rows["ticker"].eq("T001")].iloc[0]

    assert "net_income" in row["missing_fields"]
    assert row["missing_fields"] != "0"


def test_missing_inputs_are_reported_not_silently_ignored(tmp_path: Path):
    paths = _write_fixture(tmp_path, step19_exists=False)

    result = _run(paths)

    assert "step19_rows" in result.summary["missing_input_files"]
    assert "input:step19_rows" in result.rows.iloc[0]["missing_fields"]


def test_source_confidence_fields_on_every_row(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    for column in ["market_source_confidence", "finance_source_confidence", "crosscheck_status", "verification_status"]:
        assert column in result.rows.columns
        assert not result.rows[column].astype(str).eq("").any()


def test_verification_status_remains_manual_bctc_review(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert set(result.rows["verification_status"]) == {"NEEDS_MANUAL_BCTC_REVIEW"}


def test_no_cross_sector_peer_comparison(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    grouped = result.rows.groupby("peer_group_id")["primary_micro_sector"].nunique()
    assert int(grouped.max()) == 1


def test_peer_group_too_small_requires_manual_review(tmp_path: Path):
    paths = _write_fixture(tmp_path, ticker_count=2)

    result = _run(paths)

    assert set(result.rows["valuation_relative_to_peer"]) == {"PEER_GROUP_TOO_SMALL"}
    assert result.rows["manual_review_required"].map(bool).all()


def test_full_universe_blocked_by_default(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    with pytest.raises(Step20SafeRunBlocked):
        _run(paths, request_full_universe=True)


def test_previous_step_outputs_are_not_mutated(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    core = tmp_path / "previous_step.csv"
    core.write_text("ticker,value\nT001,1\n", encoding="utf-8")
    before = core.read_text(encoding="utf-8")

    result = _run(paths, core_output_paths=[core])

    assert core.read_text(encoding="utf-8") == before
    assert result.run_manifest["core_outputs_modified"] is False


def test_final_decision_allowed_list_and_exports_exist(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert result.summary["final_decision"] in FINAL_DECISIONS
    assert result.summary["final_decision"] not in FORBIDDEN_FINAL_DECISIONS
    assert REQUIRED_EXPORTS.issubset({path.name for path in paths["output"].iterdir()})


def _run(paths: dict[str, Path], **kwargs):
    return run_step20_l5_valuation_risk_context(
        config_path=paths["config"],
        output_dir=paths["output"],
        limit=kwargs.pop("limit", 100),
        allow_partial=True,
        command_used="pytest step20",
        **kwargs,
    )


def _write_fixture(
    tmp_path: Path,
    *,
    ticker_count: int = 4,
    missing_finance_ticker: str = "T003",
    step19_exists: bool = True,
) -> dict[str, Path]:
    tickers = [f"T{index:03d}" for index in range(1, ticker_count + 1)]
    step05a = tmp_path / "step05a.csv"
    finance = tmp_path / "finance.csv"
    quality = tmp_path / "quality.csv"
    market = tmp_path / "market.csv"
    ranking = tmp_path / "ranking.csv"
    step19 = tmp_path / "step19.csv"
    config = tmp_path / "config.yaml"
    output = tmp_path / "out"

    pd.DataFrame([_step05a_row(ticker) for ticker in tickers]).to_csv(step05a, index=False)
    pd.DataFrame([_finance_row(ticker, missing=(ticker == missing_finance_ticker)) for ticker in tickers]).to_csv(finance, index=False)
    pd.DataFrame([{"ticker": ticker, "export_status": "PARTIAL_PROVISIONAL_DATA"} for ticker in tickers]).to_csv(quality, index=False)
    pd.DataFrame([_market_row(ticker) for ticker in tickers]).to_csv(market, index=False)
    pd.DataFrame([_ranking_row(ticker, index) for index, ticker in enumerate(tickers, start=1)]).to_csv(ranking, index=False)
    if step19_exists:
        pd.DataFrame([{"ticker": ticker, "shadow_status": "SHADOW_CONDITIONAL_DIAGNOSTIC_ONLY"} for ticker in tickers]).to_csv(step19, index=False)
    _write_config(config, step05a=step05a, finance=finance, quality=quality, market=market, ranking=ranking, step19=step19)
    return {"config": config, "output": output}


def _step05a_row(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "screening_status": "WATCHLIST_CANDIDATE",
        "market_source_confidence": "PROVISIONAL_PRIMARY_ONLY",
        "finance_source_confidence": "PROVISIONAL_LOW",
        "crosscheck_status": "NOT_AVAILABLE",
        "verification_status": "NEEDS_MANUAL_BCTC_REVIEW",
        "manual_bctc_required": True,
        "missing_fields": "[]",
    }


def _finance_row(ticker: str, *, missing: bool) -> dict:
    return {
        "ticker": ticker,
        "company_name": f"{ticker} Holdings",
        "sector_raw": "Financials" if ticker in {"T001", "T002"} else "Materials",
        "industry_raw": "Brokerage" if ticker in {"T001", "T002"} else "Steel",
        "revenue": 100,
        "gross_profit": 20,
        "net_income": "" if missing else 5,
        "total_assets": 200,
        "total_liabilities": 100,
        "equity": 100,
        "cfo": 10,
        "capex": "",
        "missing_fields": "net_income;capex" if missing else "capex",
    }


def _market_row(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "last_close": 10,
        "last_price_date": "2026-06-11",
        "avg_volume_20d": 1000,
    }


def _ranking_row(ticker: str, index: int) -> dict:
    if ticker in {"T001", "T002"}:
        return {"ticker": ticker, "sector_bucket": "Financials", "firm_type": "securities", "balanced_rank": index}
    return {"ticker": ticker, "sector_bucket": "Materials", "firm_type": "steel", "balanced_rank": index}


def _write_config(path: Path, *, step05a: Path, finance: Path, quality: Path, market: Path, ranking: Path, step19: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "step_id: STEP20-L5-VALUATION-RISK-CONTEXT",
                "mode: valuation_risk_context_only",
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
                "  no_portfolio_recommendation: true",
                "  no_zero_fill: true",
                "  no_missing_finance_inference: true",
                "  no_pdf_ocr: true",
                "  no_official_bctc_scrape: true",
                "  no_core_output_mutation: true",
                "  no_stage_promotion_to_investment_ready: true",
                "  no_cross_sector_comparison: true",
                "inputs:",
                f"  step19_rows: {step19.as_posix()}",
                f"  step05a_rows: {step05a.as_posix()}",
                f"  watchlist_candidates: {step05a.as_posix()}",
                f"  manual_bctc_queue: {step05a.as_posix()}",
                f"  finance_latest_wide: {finance.as_posix()}",
                f"  finance_quality_flags: {quality.as_posix()}",
                f"  market_snapshot: {market.as_posix()}",
                f"  ranking_metadata: {ranking.as_posix()}",
                "outputs:",
                "  output_dir: ignored_in_test",
                "peer_context:",
                "  min_peer_group_size: 3",
                "",
            ]
        ),
        encoding="utf-8",
    )
