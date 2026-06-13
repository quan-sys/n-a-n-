import json
from pathlib import Path

import pandas as pd

from src.diagnostics.step27_data_coverage_repair_probe import (
    FINAL_DECISIONS,
    run_step27_data_coverage_repair_probe,
    scan_forbidden_terms,
)


REQUIRED_OUTPUTS = {
    "step27_coverage_probe_summary.json",
    "step27_probe_summary.json",
    "step27_probe_rows.csv",
    "direct_fetch_probe_results.csv",
    "raw_observation_manifest.csv",
    "fetch_success_examples.csv",
    "fetch_failure_examples.csv",
    "fetch_recovered_tickers.csv",
    "fetch_failed_tickers.csv",
    "repair_queue.csv",
    "source_limitation_queue.csv",
    "schema_bug_candidates.csv",
    "pipeline_vs_direct_fetch_gap.csv",
    "input_resolution_report.json",
    "run_manifest.json",
}


def test_step27_does_not_mutate_step25_or_step26_inputs(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path)
    before_step25 = paths["step25_rows"].read_text(encoding="utf-8")
    before_step26 = paths["step26_rows"].read_text(encoding="utf-8")

    result = _run(paths, fetcher=_fetcher_ok)

    assert paths["step25_rows"].read_text(encoding="utf-8") == before_step25
    assert paths["step26_rows"].read_text(encoding="utf-8") == before_step26
    assert result.run_manifest["previous_step_outputs_mutated"] is False


def test_missing_step26_files_block_safely(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "config.yaml"
    output = tmp_path / "out"
    _write_config(
        config,
        step25_rows=tmp_path / "missing_step25.csv",
        step26_rows=tmp_path / "missing_step26.csv",
        shortlist=tmp_path / "missing_shortlist.csv",
        manual=tmp_path / "missing_manual.csv",
        output=output,
        max_total=10,
    )

    result = run_step27_data_coverage_repair_probe(
        config_path=config,
        output_dir=output,
        allow_partial=True,
        command_used="pytest step27 missing",
        fetcher=_fetcher_ok,
    )

    assert result.summary["final_decision"] == "BLOCKED_MISSING_STEP26_INPUTS"
    assert result.summary["total_probe_tickers"] == 0


def test_fetch_ok_for_previously_blocked_ticker_creates_repair_queue(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path)

    result = _run(paths, fetcher=_mixed_fetcher)

    assert "AAA" in set(result.repair_queue["ticker"])
    row = result.repair_queue[result.repair_queue["ticker"].eq("AAA")].iloc[0]
    assert row["coverage_issue_class"] == "FETCH_OK_PIPELINE_MISSED"


def test_raw_price_columns_with_missing_normalized_fields_create_schema_candidate(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path)

    result = _run(paths, fetcher=_mixed_fetcher)

    assert "EEE" in set(result.schema_bug_candidates["ticker"])
    row = result.schema_bug_candidates[result.schema_bug_candidates["ticker"].eq("EEE")].iloc[0]
    assert row["recommended_repair_action"] == "FIX_NORMALIZATION_SCHEMA_MAP"


def test_empty_fetch_creates_source_limitation_queue(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path)

    result = _run(paths, fetcher=_mixed_fetcher)

    assert "BBB" in set(result.source_limitation_queue["ticker"])
    assert result.source_limitation_queue["coverage_issue_class"].eq("FETCH_EMPTY_SOURCE_LIMITATION").all()


def test_forbidden_terms_scanner_blocks_unsafe_output(tmp_path: Path):
    output = tmp_path / "scan"
    output.mkdir()
    (output / "bad.txt").write_text(
        "buy sell hold target price fair value intrinsic value margin of safety expected return upside downside entry price exit price stoploss take profit portfolio recommendation",
        encoding="utf-8",
    )

    hits = scan_forbidden_terms(output)

    for term in [
        "buy",
        "sell",
        "hold",
        "target price",
        "fair value",
        "intrinsic value",
        "margin of safety",
        "expected return",
        "upside",
        "downside",
        "entry price",
        "exit price",
        "stoploss",
        "take profit",
        "portfolio",
        "recommendation",
    ]:
        assert any(hit.endswith(f":{term}") for hit in hits)


def test_no_zero_fill_is_applied_to_missing_price_or_volume(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path)

    result = _run(paths, fetcher=_mixed_fetcher)
    row = result.probe_rows[result.probe_rows["ticker"].eq("BBB")].iloc[0]

    assert row["last_available_date"] == ""
    assert bool(row["last_close_available"]) is False
    assert bool(row["last_volume_available"]) is False
    assert int(row["normalized_row_count"]) == 0


def test_max_total_probe_tickers_is_respected(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path, max_total=2)

    result = _run(paths, fetcher=_fetcher_ok)

    assert result.summary["total_probe_tickers"] == 2


def test_output_files_are_created(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path)

    _run(paths, fetcher=_mixed_fetcher)

    assert REQUIRED_OUTPUTS.issubset({path.name for path in paths["output"].iterdir()})


def test_final_decision_is_restricted_to_allowed_list(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path)

    result = _run(paths, fetcher=_mixed_fetcher)

    assert result.summary["final_decision"] in FINAL_DECISIONS


def _run(paths: dict[str, Path], *, fetcher):
    return run_step27_data_coverage_repair_probe(
        config_path=paths["config"],
        output_dir=paths["output"],
        allow_partial=True,
        command_used="pytest step27",
        fetcher=fetcher,
    )


def _write_fixture(tmp_path: Path, *, max_total: int = 10) -> dict[str, Path]:
    data_dir = tmp_path / "data" / "reports"
    step25_dir = data_dir / "step25_full_universe_1743_primary_only_scale"
    step26_dir = data_dir / "step26_full_universe_output_audit_first_shortlist"
    step25_dir.mkdir(parents=True)
    step26_dir.mkdir(parents=True)
    config = tmp_path / "config.yaml"
    output = tmp_path / "out"
    step25_rows = step25_dir / "full_universe_screening_rows.csv"
    step26_rows = step26_dir / "normalized_universe_rows.csv"
    shortlist = step26_dir / "first_review_shortlist_50.csv"
    manual = step26_dir / "manual_bctc_priority_queue_100.csv"
    blocked = step26_dir / "data_repair_priority_queue.csv"

    rows = pd.DataFrame(
        [
            _row("AAA", "BLOCKED_INSUFFICIENT_MARKET_DATA"),
            _row("BBB", "BLOCKED_INSUFFICIENT_MARKET_DATA"),
            _row("CCC", "WATCHLIST_CANDIDATE"),
            _row("DDD", "BLOCKED_INSUFFICIENT_MARKET_DATA"),
            _row("EEE", "BLOCKED_INSUFFICIENT_MARKET_DATA"),
            _row("FFF", "BLOCKED_INSUFFICIENT_MARKET_DATA"),
        ]
    )
    rows.to_csv(step25_rows, index=False)
    rows.to_csv(step26_rows, index=False)
    rows[rows["screening_status"].eq("WATCHLIST_CANDIDATE")].to_csv(shortlist, index=False)
    rows[rows["screening_status"].eq("WATCHLIST_CANDIDATE")].to_csv(manual, index=False)
    rows[rows["screening_status"].str.startswith("BLOCKED_")].to_csv(blocked, index=False)
    _write_config(
        config,
        step25_rows=step25_rows,
        step26_rows=step26_rows,
        shortlist=shortlist,
        manual=manual,
        output=output,
        max_total=max_total,
    )
    return {
        "config": config,
        "output": output,
        "step25_rows": step25_rows,
        "step26_rows": step26_rows,
        "shortlist": shortlist,
        "manual": manual,
        "blocked": blocked,
    }


def _write_config(
    path: Path,
    *,
    step25_rows: Path,
    step26_rows: Path,
    shortlist: Path,
    manual: Path,
    output: Path,
    max_total: int,
) -> None:
    path.write_text(
        f"""
step_id: STEP27-DATA-COVERAGE-REPAIR-PROBE
mode: data_coverage_repair_probe
run:
  sandbox_only: true
  allow_partial: true
  allow_network: true
limits:
  sample_blocked_tickers: 5
  sample_watchlist_control_tickers: 2
  sample_random_universe_tickers: 2
  max_total_probe_tickers: {max_total}
  max_requests: 20
  timeout_seconds: 25
  full_universe_probe_allowed: false
source_policy:
  provider: vnstock
  market_source: VCI
  allowed_sources:
    - VCI
  allow_fallback_sources: false
  crosscheck_status: NOT_AVAILABLE
  market_source_confidence: PROVISIONAL_PRIMARY_ONLY
  finance_source_confidence_default: PROVISIONAL_LOW
  verification_status: NEEDS_MANUAL_BCTC_REVIEW
history_probe:
  lookback_days: 120
  min_rows_for_fetch_ok: 1
  required_normalized_fields:
    - ticker
    - date
    - close
    - volume
inputs:
  step25_rows: {step25_rows.as_posix()}
  step26_audit_rows: {step26_rows.as_posix()}
  step26_blocked_rows: {(step26_rows.parent / "data_repair_priority_queue.csv").as_posix()}
  step26_shortlist: {shortlist.as_posix()}
  step26_manual_bctc_queue: {manual.as_posix()}
exports:
  output_dir: {output.as_posix()}
safety:
  no_recommendation: true
  no_buy_sell_hold: true
  no_valuation: true
  no_target_price: true
  no_fair_value: true
  no_intrinsic_value: true
  no_margin_of_safety: true
  no_expected_return: true
  no_zero_fill: true
  no_missing_data_inference: true
  no_pdf_ocr: true
  no_official_bctc_scrape: true
  no_core_output_mutation: true
  no_stage_promotion_to_investment_ready: true
""".strip(),
        encoding="utf-8",
    )


def _row(ticker: str, status: str) -> dict:
    blocked = status.startswith("BLOCKED_")
    return {
        "ticker": ticker,
        "company_name": f"{ticker} Corp",
        "screening_status": status,
        "missing_fields": json.dumps(["last_close", "last_price_date"] if blocked else []),
        "block_reasons": json.dumps(["Primary market data missing or incomplete."] if blocked else []),
        "reason_to_review": "Primary market data missing or incomplete." if blocked else "Manual BCTC review remains required.",
        "last_price_date": "",
        "last_close": "",
        "market_source_confidence": "PROVISIONAL_PRIMARY_ONLY",
        "finance_source_confidence": "PROVISIONAL_LOW",
        "crosscheck_status": "NOT_AVAILABLE",
        "verification_status": "NEEDS_MANUAL_BCTC_REVIEW",
    }


def _fetcher_ok(ticker, start, end, policy):
    return pd.DataFrame([{"time": "2026-06-10", "close": 10.5, "volume": 1000}])


def _mixed_fetcher(ticker, start, end, policy):
    if ticker == "AAA":
        return pd.DataFrame([{"time": "2026-06-10", "close": 10.5, "volume": 1000}])
    if ticker == "BBB":
        return pd.DataFrame()
    if ticker == "EEE":
        return pd.DataFrame([{"date": "2026-06-10", "price": 10.5, "qty": 1000}])
    if ticker == "DDD":
        raise RuntimeError("ticker not found")
    return pd.DataFrame([{"time": "2026-06-10", "close": 11.5, "volume": 900}])
