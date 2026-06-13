from datetime import UTC, datetime
from pathlib import Path
import time

import pandas as pd

from src.ingestion.step28_full_universe_market_snapshot_refresh_vnstock import (
    classify_fetch_error,
    configure_utf8_logging,
    normalize_history_frame,
    run_step28_full_universe_market_snapshot_refresh_vnstock,
)


REQUIRED_SUMMARY_KEYS = {
    "step_id",
    "run_timestamp",
    "source_family",
    "market_source",
    "expected_universe_size",
    "total_tickers_attempted",
    "fetch_ok_count",
    "fetch_failed_count",
    "empty_history_count",
    "encoding_error_count",
    "ticker_mapping_error_count",
    "normalization_error_count",
    "step26_blocked_count_input",
    "step26_blocked_recovered_count",
    "step26_blocked_still_failed_count",
    "step27_repair_queue_count_input",
    "step27_repair_queue_recovered_count",
    "market_coverage_before_step28_if_known",
    "market_coverage_after_step28",
    "coverage_improvement_count",
    "coverage_improvement_pct_points",
    "alternative_paid_data_needed_for_market",
    "final_decision",
    "guardrails",
    "forbidden_terms_found",
    "core_outputs_modified",
}


def test_utf8_safe_logging_does_not_raise_unicode_error():
    configure_utf8_logging()
    print("ASCII only log after utf8 setup")


def test_error_classifier_maps_charmap_unicode_to_env_encoding():
    assert classify_fetch_error(UnicodeEncodeError("cp1252", "á", 0, 1, "boom")) == "ENV_ENCODING_ERROR"
    assert classify_fetch_error("'charmap' codec can't encode characters") == "ENV_ENCODING_ERROR"
    assert classify_fetch_error(SystemExit(1)) == "SOURCE_RATE_LIMIT_OR_TIMEOUT"


def test_normalizer_maps_common_ohlcv_variants():
    raw = pd.DataFrame(
        [
            {
                "Date": "2026-06-10",
                "Close": "10.5",
                "Volume": "1000",
                "turnover": "10500",
                "Open": "10",
                "High": "11",
                "Low": "9.5",
            }
        ]
    )

    normalized = normalize_history_frame(raw, "AAA")

    assert list(normalized.columns) == ["ticker", "date", "open", "high", "low", "close", "volume", "value"]
    assert normalized.loc[0, "ticker"] == "AAA"
    assert float(normalized.loc[0, "close"]) == 10.5
    assert float(normalized.loc[0, "volume"]) == 1000
    assert float(normalized.loc[0, "value"]) == 10500


def test_empty_dataframe_becomes_empty_history(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path, tickers=["AAA"])

    result = run_step28_full_universe_market_snapshot_refresh_vnstock(
        config_path=paths["config"],
        output_dir=paths["output"],
        fetcher=lambda ticker, start, end, source: pd.DataFrame(),
        command_used="pytest step28",
        request_pause_seconds=0,
    )

    row = result.market_snapshot_rows.iloc[0]
    assert row["fetch_error_type"] == "EMPTY_HISTORY"
    assert row["fetch_status"] == "FAILED"


def test_valid_dataframe_becomes_ok_with_last_price_and_avg_volume(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path, tickers=["AAA"])

    result = run_step28_full_universe_market_snapshot_refresh_vnstock(
        config_path=paths["config"],
        output_dir=paths["output"],
        fetcher=_valid_fetcher,
        command_used="pytest step28",
        request_pause_seconds=0,
    )

    row = result.market_snapshot_rows.iloc[0]
    assert row["fetch_error_type"] == "OK"
    assert row["last_price_date"] == "2026-06-10"
    assert float(row["last_close"]) == 12
    assert float(row["avg_volume_20d"]) == 200


def test_recovery_comparison_labels_step26_blocked_ok_as_recovered(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path, tickers=["AAA"])

    result = run_step28_full_universe_market_snapshot_refresh_vnstock(
        config_path=paths["config"],
        output_dir=paths["output"],
        fetcher=_valid_fetcher,
        command_used="pytest step28",
        request_pause_seconds=0,
    )

    assert result.pipeline_vs_step26_repair_impact.iloc[0]["recovery_label"] == "RECOVERED_FROM_STEP26_BLOCKED"
    assert result.summary["step26_blocked_recovered_count"] == 1


def test_summary_schema_contains_required_keys_and_guardrails(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path, tickers=["AAA", "BBB"], watchlist_tickers=["BBB"])

    result = run_step28_full_universe_market_snapshot_refresh_vnstock(
        config_path=paths["config"],
        output_dir=paths["output"],
        fetcher=_valid_fetcher,
        command_used="pytest step28",
        request_pause_seconds=0,
    )

    assert REQUIRED_SUMMARY_KEYS.issubset(result.summary.keys())
    assert result.summary["guardrails"]["no_zero_fill"] is True
    assert result.summary["guardrails"]["no_financial_statement_collection"] is True
    assert result.summary["forbidden_terms_found"] == []


def test_limit_start_end_controls_ticker_window(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path, tickers=["AAA", "BBB", "CCC", "DDD"])

    result = run_step28_full_universe_market_snapshot_refresh_vnstock(
        config_path=paths["config"],
        output_dir=paths["output"],
        fetcher=_valid_fetcher,
        command_used="pytest step28",
        request_pause_seconds=0,
        start_index=2,
        end_index=4,
        limit=1,
    )

    assert result.summary["total_tickers_attempted"] == 1
    assert list(result.market_snapshot_rows["ticker"]) == ["BBB"]


def test_checkpoint_files_are_written_after_each_ticker(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path, tickers=["AAA", "BBB"])

    run_step28_full_universe_market_snapshot_refresh_vnstock(
        config_path=paths["config"],
        output_dir=paths["output"],
        fetcher=_mixed_fetcher,
        command_used="pytest step28",
        request_pause_seconds=0,
    )

    assert (paths["output"] / "market_snapshot_success.csv").exists()
    assert (paths["output"] / "market_snapshot_failed.csv").exists()
    assert (paths["output"] / "batch_fetch_manifest.csv").exists()
    assert len(pd.read_csv(paths["output"] / "batch_fetch_manifest.csv")) == 2


def test_resume_skips_existing_success_and_failed_rows(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path, tickers=["AAA"])

    run_step28_full_universe_market_snapshot_refresh_vnstock(
        config_path=paths["config"],
        output_dir=paths["output"],
        fetcher=_valid_fetcher,
        command_used="pytest step28",
        request_pause_seconds=0,
    )
    calls = {"count": 0}

    def failing_fetcher(ticker, start, end, source):
        calls["count"] += 1
        raise RuntimeError("should be skipped")

    result = run_step28_full_universe_market_snapshot_refresh_vnstock(
        config_path=paths["config"],
        output_dir=paths["output"],
        fetcher=failing_fetcher,
        command_used="pytest step28",
        request_pause_seconds=0,
    )

    assert calls["count"] == 0
    assert result.summary["fetch_ok_count"] == 1


def test_per_ticker_timeout_classifies_slow_fetcher(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path, tickers=["AAA"])

    def slow_fetcher(ticker, start, end, source):
        time.sleep(0.2)
        return pd.DataFrame([{"time": "2026-06-10", "close": 10, "volume": 100}])

    result = run_step28_full_universe_market_snapshot_refresh_vnstock(
        config_path=paths["config"],
        output_dir=paths["output"],
        fetcher=slow_fetcher,
        command_used="pytest step28",
        request_pause_seconds=0,
    )

    row = result.market_snapshot_rows.iloc[0]
    assert row["fetch_error_type"] == "SOURCE_RATE_LIMIT_OR_TIMEOUT"


def _valid_fetcher(ticker, start, end, source):
    return pd.DataFrame(
        [
            {"time": "2026-06-09", "close": 10, "volume": 100},
            {"time": "2026-06-10", "close": 12, "volume": 300},
        ]
    )


def _mixed_fetcher(ticker, start, end, source):
    if ticker == "BBB":
        return pd.DataFrame()
    return _valid_fetcher(ticker, start, end, source)


def _write_fixture(tmp_path: Path, *, tickers: list[str], watchlist_tickers: list[str] | None = None) -> dict[str, Path]:
    data_dir = tmp_path / "data" / "reports"
    step25_dir = data_dir / "step25_full_universe_1743_primary_only_scale"
    step26_dir = data_dir / "step26_full_universe_output_audit_first_shortlist"
    step27_dir = data_dir / "step27_data_coverage_repair_probe"
    output = tmp_path / "out"
    raw = tmp_path / "raw"
    config = tmp_path / "config.yaml"
    step25_dir.mkdir(parents=True)
    step26_dir.mkdir(parents=True)
    step27_dir.mkdir(parents=True)
    watchlist = set(watchlist_tickers or [])
    step25_rows = step25_dir / "full_universe_screening_rows.csv"
    step26_rows = step26_dir / "normalized_universe_rows.csv"
    step27_rows = step27_dir / "fetch_recovered_tickers.csv"

    pd.DataFrame([{"ticker": ticker, "exchange": "HOSE"} for ticker in tickers]).to_csv(step25_rows, index=False)
    pd.DataFrame(
        [
            {
                "ticker": ticker,
                "screening_status": "WATCHLIST_CANDIDATE" if ticker in watchlist else "BLOCKED_INSUFFICIENT_MARKET_DATA",
                "missing_fields": '["last_close","last_price_date"]',
                "block_reasons": '["Primary market data missing or incomplete."]',
            }
            for ticker in tickers
        ]
    ).to_csv(step26_rows, index=False)
    pd.DataFrame([{"ticker": tickers[0]}]).to_csv(step27_rows, index=False)
    _write_config(config, step25_rows, step26_rows, step27_rows, output, raw, len(tickers))
    return {"config": config, "output": output}


def _write_config(config: Path, step25: Path, step26: Path, step27: Path, output: Path, raw: Path, count: int) -> None:
    config.write_text(
        f"""
step_id: STEP28-FULL-UNIVERSE-MARKET-SNAPSHOT-REFRESH-VNSTOCK
source_family: vnstock
market_source: VCI
expected_universe_size: {count}
batch_size: 2
max_tickers: {count}
full_universe_allowed: true
resume_from_cache: true
force_refresh: false
retry_count: 1
retry_backoff_seconds: 0
request_pause_seconds: 0
per_ticker_timeout_seconds: 0.05
progress_log_every_tickers: 10
history_start: "2024-01-01"
history_end: "2026-06-11"
recent_trading_day_stale_threshold_calendar_days: 14
min_history_rows_for_valid_market_data: 1
commit_large_raw_history: false
inputs:
  step25_universe_rows: {step25.as_posix()}
  step26_audit_rows: {step26.as_posix()}
  step27_repair_queue: {step27.as_posix()}
exports:
  output_dir: {output.as_posix()}
  raw_cache_root: {raw.as_posix()}
guardrails:
  no_recommendation: true
  no_buy_sell_hold: true
  no_target_price: true
  no_fair_value: true
  no_margin_of_safety: true
  no_expected_return: true
  no_financial_statement_collection: true
  no_pdf_ocr: true
  no_mock_data: true
  no_zero_fill: true
""".strip(),
        encoding="utf-8",
    )
