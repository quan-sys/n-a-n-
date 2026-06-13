"""STEP28 full-universe market snapshot refresh from vnstock/VCI.

Market data only. This step refreshes price/liquidity coverage for the
full STEP25 universe and compares recovery against STEP26/STEP27 outputs.
"""

from __future__ import annotations

import contextlib
import concurrent.futures
import hashlib
import io
import json
import multiprocessing as mp
import os
import queue
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yaml


STEP_ID = "STEP28-FULL-UNIVERSE-MARKET-SNAPSHOT-REFRESH-VNSTOCK"

ERROR_TYPES = {
    "OK",
    "EMPTY_HISTORY",
    "SOURCE_NO_DATA",
    "SOURCE_RATE_LIMIT_OR_TIMEOUT",
    "SOURCE_REQUEST_ERROR",
    "VNSTOCK_API_ERROR",
    "TICKER_MAPPING_ERROR",
    "ENV_ENCODING_ERROR",
    "NORMALIZATION_ERROR",
    "CACHE_INVALID",
    "UNKNOWN_ERROR",
}

FINAL_DECISIONS = {
    "PASS_MARKET_REFRESH_WITH_MAJOR_RECOVERY",
    "PASS_MARKET_REFRESH_WITH_PARTIAL_RECOVERY",
    "PASS_MARKET_REFRESH_NO_MEANINGFUL_RECOVERY",
    "FAIL_MARKET_REFRESH_ENVIRONMENT_BLOCKED",
    "FAIL_MARKET_REFRESH_INPUT_MISSING",
}

RECOVERY_LABELS = {
    "RECOVERED_FROM_STEP26_BLOCKED",
    "STILL_BLOCKED_AFTER_REFRESH",
    "ALREADY_VALID_IN_STEP26",
    "NEWLY_VALID_MARKET_DATA",
    "FETCH_FAILED_NEEDS_RETRY_OR_MAPPING_FIX",
}

SNAPSHOT_COLUMNS = [
    "ticker",
    "exchange_if_available",
    "market_source",
    "fetch_status",
    "fetch_error_type",
    "fetch_error_message",
    "history_row_count",
    "first_price_date",
    "last_price_date",
    "last_close",
    "last_volume",
    "last_value_if_available",
    "avg_volume_20d",
    "avg_volume_60d",
    "avg_value_20d_if_available",
    "avg_value_60d_if_available",
    "recent_price_available",
    "market_data_available",
    "liquidity_data_available",
    "stale_market_data",
    "calendar_days_since_last_price",
    "missing_market_fields",
    "cache_used",
    "attempt_count",
    "batch_id",
    "created_at",
]

BATCH_COLUMNS = [
    "batch_id",
    "batch_index",
    "ticker",
    "ticker_index",
    "fetch_status",
    "fetch_error_type",
    "attempt_count",
    "cache_used",
    "history_row_count",
    "started_at",
    "finished_at",
    "duration_ms",
]

FORBIDDEN_TERMS = [
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
]

GUARDRAILS = {
    "no_recommendation": True,
    "no_buy_sell_hold": True,
    "no_target_price": True,
    "no_fair_value": True,
    "no_margin_of_safety": True,
    "no_expected_return": True,
    "no_financial_statement_collection": True,
    "no_pdf_ocr": True,
    "no_mock_data": True,
    "no_zero_fill": True,
}


class Step28SafeRunBlocked(RuntimeError):
    """Raised when STEP28 cannot safely proceed."""


@dataclass
class Step28InputResolution:
    step25_universe_rows_path: Path | None
    step26_audit_rows_path: Path | None
    step27_repair_queue_path: Path | None
    missing_input_files: list[str]
    duplicate_tickers: list[str]
    notes: list[dict[str, str]]


@dataclass
class Step28Result:
    summary: dict[str, Any]
    market_snapshot_rows: pd.DataFrame
    market_snapshot_success: pd.DataFrame
    market_snapshot_failed: pd.DataFrame
    step26_blocked_recovered: pd.DataFrame
    step26_blocked_still_failed: pd.DataFrame
    step27_repair_queue_recheck: pd.DataFrame
    ticker_fetch_error_summary: pd.DataFrame
    missing_market_field_summary: pd.DataFrame
    batch_fetch_manifest: pd.DataFrame
    pipeline_vs_step26_repair_impact: pd.DataFrame
    run_manifest: dict[str, Any]


HistoryFetcher = Callable[[str, datetime, datetime, str], pd.DataFrame]


def load_step28_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("STEP28 config must be a mapping.")
    return data


def configure_utf8_logging() -> None:
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def validate_step28_config(config: dict[str, Any]) -> None:
    if config.get("step_id") != STEP_ID:
        raise ValueError(f"STEP28 step_id must be {STEP_ID}.")
    if str(config.get("source_family", "")) != "vnstock":
        raise ValueError("STEP28 requires source_family=vnstock.")
    if str(config.get("market_source", "")) != "VCI":
        raise ValueError("STEP28 requires market_source=VCI.")
    if bool(config.get("full_universe_allowed")) is not True:
        raise ValueError("STEP28 full_universe_allowed must be true.")
    guardrails = dict(config.get("guardrails") or {})
    missing = [key for key, expected in GUARDRAILS.items() if guardrails.get(key) is not expected]
    if missing:
        raise ValueError(f"STEP28 guardrails must be true: {','.join(missing)}")


def run_step28_full_universe_market_snapshot_refresh_vnstock(
    *,
    config_path: str | Path,
    output_dir: str | Path | None = None,
    fetcher: HistoryFetcher | None = None,
    command_used: str = "",
    max_tickers: int | None = None,
    request_pause_seconds: float | None = None,
    force_refresh: bool | None = None,
    core_output_paths: list[str | Path] | None = None,
    limit: int | None = None,
    start_index: int | None = None,
    end_index: int | None = None,
) -> Step28Result:
    configure_utf8_logging()
    config = load_step28_config(config_path)
    validate_step28_config(config)
    exports = config.get("exports") if isinstance(config.get("exports"), dict) else {}
    output = Path(output_dir or exports.get("output_dir") or "data/reports/step28_full_universe_market_snapshot_refresh_vnstock")
    output.mkdir(parents=True, exist_ok=True)
    raw_cache_dir = Path(exports.get("raw_cache_root") or "data/raw/vnstock_vci_market_history") / _run_date()
    raw_cache_dir.mkdir(parents=True, exist_ok=True)

    resolution = resolve_step28_inputs(config)
    core_paths = [Path(path) for path in (core_output_paths or _core_paths_from_resolution(resolution))]
    before_hashes = _hashes(core_paths)
    universe = load_universe_tickers(resolution.step25_universe_rows_path or resolution.step26_audit_rows_path)
    expected = int(config.get("expected_universe_size", 1743) or 1743)
    max_count = int(max_tickers if max_tickers is not None else config.get("max_tickers", expected) or expected)
    if universe.empty:
        result = _input_missing_result(config, Path(config_path), output, raw_cache_dir, resolution, command_used)
        write_step28_outputs(output, result)
        return result
    if len(universe) != expected and max_tickers is None:
        raise Step28SafeRunBlocked(f"Universe count {len(universe)} does not match expected {expected}.")
    universe = _select_universe_window(universe, max_count=max_count, limit=limit, start_index=start_index, end_index=end_index)

    step26_rows = _read_csv(resolution.step26_audit_rows_path)
    step27_queue = _read_csv(resolution.step27_repair_queue_path)
    step26_lookup = _build_step26_lookup(step26_rows)
    step26_blocked = _step26_tickers_by_status(step26_rows, "BLOCKED_INSUFFICIENT_MARKET_DATA")
    step26_watchlist = _step26_tickers_by_status(step26_rows, "WATCHLIST_CANDIDATE")
    step27_repair = set(_ticker_series(step27_queue))

    run_started = datetime.now(UTC)
    start = pd.to_datetime(config.get("history_start", "2024-01-01"), utc=True).to_pydatetime()
    end_value = config.get("history_end")
    end = pd.to_datetime(end_value, utc=True).to_pydatetime() if end_value else run_started
    fetcher = fetcher or fetch_vnstock_vci_history
    pause = float(request_pause_seconds if request_pause_seconds is not None else config.get("request_pause_seconds", 0.25) or 0.0)
    retry_count = min(2, int(config.get("retry_count", 2) or 1))
    retry_backoff = float(config.get("retry_backoff_seconds", 2) or 0.0)
    per_ticker_timeout = float(config.get("per_ticker_timeout_seconds", 45) or 45)
    progress_every = int(config.get("progress_log_every_tickers", 10) or 10)
    batch_size = int(config.get("batch_size", 50) or 50)
    resume = bool(config.get("resume_from_cache", True))
    force = bool(force_refresh if force_refresh is not None else config.get("force_refresh", False))
    source = str(config.get("market_source", "VCI"))
    if force:
        _reset_checkpoint_outputs(output)
    existing_snapshot_rows = load_existing_checkpoint_rows(output, max_retry_count=retry_count)
    existing_manifest_rows = _read_csv(output / "batch_fetch_manifest.csv").reindex(columns=BATCH_COLUMNS) if resume and not force else pd.DataFrame(columns=BATCH_COLUMNS)
    existing_by_ticker = {
        str(row["ticker"]).upper(): row.to_dict()
        for _, row in existing_snapshot_rows.iterrows()
        if not _is_missing(row.get("ticker"))
    }
    snapshots: list[dict[str, Any]] = []
    manifests: list[dict[str, Any]] = existing_manifest_rows.to_dict("records") if not existing_manifest_rows.empty else []
    ok_count = 0
    failed_count = 0

    for index, row in universe.reset_index(drop=True).iterrows():
        ticker_index = int(index) + 1
        ticker = str(row["ticker"]).upper()
        if resume and not force and ticker in existing_by_ticker:
            snapshot = _coerce_snapshot_row(existing_by_ticker[ticker])
            snapshots.append(snapshot)
            if str(snapshot.get("fetch_error_type")) == "OK":
                ok_count += 1
            else:
                failed_count += 1
            if ticker_index % progress_every == 0 or ticker_index == len(universe):
                _log_progress(ticker_index, len(universe), ok_count, failed_count, run_started, ticker)
            continue
        batch_index = int(index // batch_size) + 1
        batch_id = f"batch_{batch_index:04d}"
        started = datetime.now(UTC)
        snapshot, manifest = fetch_ticker_snapshot(
            ticker=ticker,
            exchange=row.get("exchange_if_available", ""),
            source=source,
            start=start,
            end=end,
            batch_id=batch_id,
            batch_index=batch_index,
            ticker_index=ticker_index,
            stale_threshold=int(config.get("recent_trading_day_stale_threshold_calendar_days", 14) or 14),
            min_rows=int(config.get("min_history_rows_for_valid_market_data", 1) or 1),
            raw_cache_dir=raw_cache_dir,
            resume_from_cache=resume,
            force_refresh=force,
            retry_count=retry_count,
            retry_backoff_seconds=retry_backoff,
            per_ticker_timeout_seconds=per_ticker_timeout,
            fetcher=fetcher,
            started_at=started,
        )
        snapshots.append(snapshot)
        manifests.append(manifest)
        if str(snapshot.get("fetch_error_type")) == "OK":
            ok_count += 1
            append_checkpoint_row(output / "market_snapshot_success.csv", snapshot, SNAPSHOT_COLUMNS)
        else:
            failed_count += 1
            append_checkpoint_row(output / "market_snapshot_failed.csv", snapshot, SNAPSHOT_COLUMNS)
        append_checkpoint_row(output / "batch_fetch_manifest.csv", manifest, BATCH_COLUMNS)
        if ticker_index % progress_every == 0 or ticker_index == len(universe):
            _log_progress(ticker_index, len(universe), ok_count, failed_count, run_started, ticker)
        if pause > 0 and not snapshot.get("cache_used", False):
            time.sleep(pause)

    snapshot_frame = pd.DataFrame(snapshots, columns=SNAPSHOT_COLUMNS)
    manifest_frame = pd.DataFrame(manifests, columns=BATCH_COLUMNS)
    if not manifest_frame.empty and "ticker" in manifest_frame.columns:
        manifest_frame = manifest_frame.drop_duplicates("ticker", keep="last").reset_index(drop=True)
    impact = build_pipeline_vs_step26_impact(snapshot_frame, step26_lookup, step26_blocked, step26_watchlist)
    success = snapshot_frame[snapshot_frame["fetch_error_type"].eq("OK")].copy()
    failed = snapshot_frame[~snapshot_frame["fetch_error_type"].eq("OK")].copy()
    recovered = impact[impact["recovery_label"].eq("RECOVERED_FROM_STEP26_BLOCKED")].copy()
    still_failed = impact[impact["recovery_label"].eq("STILL_BLOCKED_AFTER_REFRESH")].copy()
    step27_recheck = build_step27_repair_recheck(snapshot_frame, step27_repair)
    error_summary = build_fetch_error_summary(snapshot_frame)
    missing_summary = build_missing_market_field_summary(snapshot_frame)
    core_modified = before_hashes != _hashes(core_paths)
    forbidden_hits: list[str] = []
    summary = build_step28_summary(
        config=config,
        resolution=resolution,
        snapshot=snapshot_frame,
        step26_blocked_count=len(step26_blocked),
        step26_watchlist_count=len(step26_watchlist),
        step27_repair_count=len(step27_repair),
        recovered_count=len(recovered),
        still_failed_count=len(still_failed),
        step27_recovered_count=int(step27_recheck["step28_fetch_ok"].map(_as_bool).sum()) if not step27_recheck.empty else 0,
        forbidden_terms_found=forbidden_hits,
        core_outputs_modified=core_modified,
    )
    run_manifest = build_run_manifest(
        config_path=Path(config_path),
        output_dir=output,
        raw_cache_dir=raw_cache_dir,
        command_used=command_used,
        resolution=resolution,
        universe_count=len(universe),
        started_at=run_started,
        core_outputs_modified=core_modified,
    )
    result = Step28Result(
        summary=summary,
        market_snapshot_rows=snapshot_frame,
        market_snapshot_success=success,
        market_snapshot_failed=failed,
        step26_blocked_recovered=recovered,
        step26_blocked_still_failed=still_failed,
        step27_repair_queue_recheck=step27_recheck,
        ticker_fetch_error_summary=error_summary,
        missing_market_field_summary=missing_summary,
        batch_fetch_manifest=manifest_frame,
        pipeline_vs_step26_repair_impact=impact,
        run_manifest=run_manifest,
    )
    write_step28_outputs(output, result)
    forbidden_hits = scan_forbidden_terms(output)
    if forbidden_hits:
        result.summary = build_step28_summary(
            config=config,
            resolution=resolution,
            snapshot=snapshot_frame,
            step26_blocked_count=len(step26_blocked),
            step26_watchlist_count=len(step26_watchlist),
            step27_repair_count=len(step27_repair),
            recovered_count=len(recovered),
            still_failed_count=len(still_failed),
            step27_recovered_count=int(step27_recheck["step28_fetch_ok"].map(_as_bool).sum()) if not step27_recheck.empty else 0,
            forbidden_terms_found=forbidden_hits,
            core_outputs_modified=core_modified,
        )
        write_step28_outputs(output, result)
    return result


def resolve_step28_inputs(config: dict[str, Any]) -> Step28InputResolution:
    inputs = config.get("inputs") if isinstance(config.get("inputs"), dict) else {}
    specs = {
        "step25_universe_rows_path": (inputs.get("step25_universe_rows"), [["step25", "full_universe", "screening_rows"], ["step25", "primary_only", "rows"]], ".csv"),
        "step26_audit_rows_path": (inputs.get("step26_audit_rows"), [["step26", "normalized_universe_rows"], ["step26", "audit", "rows"]], ".csv"),
        "step27_repair_queue_path": (inputs.get("step27_repair_queue"), [["step27", "fetch_recovered_tickers"], ["step27", "repair_queue"]], ".csv"),
    }
    resolved: dict[str, Path | None] = {}
    missing: list[str] = []
    notes: list[dict[str, str]] = []
    for label, (configured, tokens, suffix) in specs.items():
        path = _resolve_path(configured, tokens, suffix)
        resolved[label] = path
        status = "FOUND" if path is not None else "MISSING"
        notes.append({"input_name": label, "configured_path": str(configured or ""), "resolved_path": str(path or ""), "status": status})
        if path is None and label in {"step25_universe_rows_path", "step26_audit_rows_path"}:
            missing.append(label)
    duplicate_tickers = _duplicate_tickers(_read_csv(resolved.get("step25_universe_rows_path")))
    return Step28InputResolution(
        step25_universe_rows_path=resolved["step25_universe_rows_path"],
        step26_audit_rows_path=resolved["step26_audit_rows_path"],
        step27_repair_queue_path=resolved["step27_repair_queue_path"],
        missing_input_files=missing,
        duplicate_tickers=duplicate_tickers,
        notes=notes,
    )


def _select_universe_window(
    universe: pd.DataFrame,
    *,
    max_count: int,
    limit: int | None,
    start_index: int | None,
    end_index: int | None,
) -> pd.DataFrame:
    frame = universe.head(max_count).copy()
    start_pos = max((int(start_index) - 1), 0) if start_index is not None else 0
    end_pos = int(end_index) if end_index is not None else len(frame)
    frame = frame.iloc[start_pos:end_pos].copy()
    if limit is not None:
        frame = frame.head(int(limit)).copy()
    return frame.reset_index(drop=True)


def load_existing_checkpoint_rows(output_dir: Path, *, max_retry_count: int) -> pd.DataFrame:
    frames = []
    for name in ["market_snapshot_success.csv", "market_snapshot_failed.csv"]:
        path = output_dir / name
        if path.exists():
            frame = _read_csv(path)
            if not frame.empty:
                frames.append(frame.reindex(columns=SNAPSHOT_COLUMNS))
    if not frames:
        return pd.DataFrame(columns=SNAPSHOT_COLUMNS)
    combined = pd.concat(frames, ignore_index=True)
    combined["ticker"] = combined["ticker"].astype(str).str.upper().str.strip()
    if "attempt_count" in combined.columns and "fetch_error_type" in combined.columns:
        attempts = pd.to_numeric(combined["attempt_count"], errors="coerce").fillna(0)
        invalid = combined["fetch_error_type"].astype(str).ne("OK") & attempts.gt(max_retry_count)
        combined = combined[~invalid].copy()
    return combined.drop_duplicates("ticker", keep="last").reset_index(drop=True)


def append_checkpoint_row(path: Path, row: dict[str, Any], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([{column: row.get(column, "") for column in columns}], columns=columns)
    frame.to_csv(path, mode="a", header=not path.exists(), index=False, encoding="utf-8")


def _reset_checkpoint_outputs(output_dir: Path) -> None:
    for name in [
        "market_snapshot_rows.csv",
        "market_snapshot_success.csv",
        "market_snapshot_failed.csv",
        "batch_fetch_manifest.csv",
    ]:
        path = output_dir / name
        if path.exists():
            path.unlink()


def _coerce_snapshot_row(row: dict[str, Any]) -> dict[str, Any]:
    return {column: row.get(column, "") for column in SNAPSHOT_COLUMNS}


def _cached_snapshot_valid_for_policy(snapshot: dict[str, Any], max_retry_count: int) -> bool:
    if str(snapshot.get("fetch_error_type", "")) == "OK":
        return True
    try:
        attempts = int(snapshot.get("attempt_count", 0) or 0)
    except (TypeError, ValueError):
        attempts = 0
    return attempts <= max_retry_count


def _log_progress(processed: int, total: int, ok_count: int, failed_count: int, started_at: datetime, last_ticker: str) -> None:
    elapsed = datetime.now(UTC) - started_at
    seconds = int(elapsed.total_seconds())
    print(
        f"[STEP28] processed={processed}/{total} ok={ok_count} failed={failed_count} elapsed={seconds}s last_ticker={last_ticker}",
        flush=True,
    )


def load_universe_tickers(path: Path | None) -> pd.DataFrame:
    frame = _read_csv(path)
    if frame.empty:
        return pd.DataFrame(columns=["ticker", "exchange_if_available"])
    ticker_col = _first_column(frame, ["ticker", "symbol", "code"])
    if not ticker_col:
        raise Step28SafeRunBlocked("Universe input has no ticker column.")
    exchange_col = _first_column(frame, ["exchange", "exchange_if_available", "market"])
    out = pd.DataFrame(
        {
            "ticker": frame[ticker_col].astype(str).str.upper().str.strip(),
            "exchange_if_available": frame[exchange_col].astype(str).str.strip() if exchange_col else "",
        }
    )
    out = out[out["ticker"].ne("")].drop_duplicates("ticker", keep="first").reset_index(drop=True)
    return out


def fetch_ticker_snapshot(
    *,
    ticker: str,
    exchange: str,
    source: str,
    start: datetime,
    end: datetime,
    batch_id: str,
    batch_index: int,
    ticker_index: int,
    stale_threshold: int,
    min_rows: int,
    raw_cache_dir: Path,
    resume_from_cache: bool,
    force_refresh: bool,
    retry_count: int,
    retry_backoff_seconds: float,
    per_ticker_timeout_seconds: float,
    fetcher: HistoryFetcher,
    started_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cache_json = raw_cache_dir / f"{ticker}_snapshot.json"
    raw_csv = raw_cache_dir / f"{ticker}_history.csv"
    if resume_from_cache and not force_refresh and cache_json.exists():
        try:
            cached = json.loads(cache_json.read_text(encoding="utf-8"))
            snapshot = dict(cached.get("snapshot") or {})
            if snapshot and _cached_snapshot_valid_for_policy(snapshot, retry_count):
                snapshot["cache_used"] = True
                finished = datetime.now(UTC)
                manifest = _manifest_from_snapshot(snapshot, batch_id, batch_index, ticker_index, started_at, finished)
                return snapshot, manifest
        except Exception:
            pass
    attempt_count = 0
    last_error_type = "UNKNOWN_ERROR"
    last_error_message = ""
    raw = pd.DataFrame()
    normalized = pd.DataFrame()
    for attempt in range(1, max(1, retry_count) + 1):
        attempt_count = attempt
        try:
            raw = fetch_with_timeout(
                ticker=ticker,
                start=start,
                end=end,
                source=source,
                fetcher=fetcher,
                timeout_seconds=per_ticker_timeout_seconds,
            )
            if raw.empty:
                last_error_type = "EMPTY_HISTORY"
                last_error_message = ""
                break
            normalized = normalize_history_frame(raw, ticker)
            if normalized.empty:
                last_error_type = "NORMALIZATION_ERROR"
                last_error_message = "Could not map required date/close fields from returned history."
                break
            last_error_type = "OK"
            last_error_message = ""
            break
        except BaseException as exc:  # noqa: BLE001 - vnstock may raise SystemExit on rate limits
            if isinstance(exc, KeyboardInterrupt):
                raise
            last_error_type = classify_fetch_error(exc)
            last_error_message = _clean_error_message(str(exc))
            if last_error_type in {"ENV_ENCODING_ERROR", "TICKER_MAPPING_ERROR"}:
                break
            if attempt < retry_count and retry_backoff_seconds > 0:
                time.sleep(retry_backoff_seconds * attempt)
    snapshot = build_snapshot_row(
        ticker=ticker,
        exchange=exchange,
        source=source,
        raw=raw,
        normalized=normalized,
        fetch_error_type=last_error_type,
        fetch_error_message=last_error_message,
        stale_threshold=stale_threshold,
        min_rows=min_rows,
        cache_used=False,
        attempt_count=attempt_count,
        batch_id=batch_id,
    )
    finished_at = datetime.now(UTC)
    manifest = _manifest_from_snapshot(snapshot, batch_id, batch_index, ticker_index, started_at, finished_at)
    _write_cache(cache_json, raw_csv, snapshot, raw)
    return snapshot, manifest


def fetch_with_timeout(
    *,
    ticker: str,
    start: datetime,
    end: datetime,
    source: str,
    fetcher: HistoryFetcher,
    timeout_seconds: float,
) -> pd.DataFrame:
    if fetcher is fetch_vnstock_vci_history:
        return fetch_vnstock_vci_history_with_timeout(ticker, start, end, source, timeout_seconds)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fetcher, ticker, start, end, source)
    try:
        return _ensure_frame(future.result(timeout=timeout_seconds))
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        raise TimeoutError(f"per-ticker timeout exceeded after {timeout_seconds:.2f}s") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def fetch_vnstock_vci_history_with_timeout(ticker: str, start: datetime, end: datetime, source: str, timeout_seconds: float) -> pd.DataFrame:
    ctx = mp.get_context("spawn")
    result_queue: mp.Queue = ctx.Queue(maxsize=1)
    process = ctx.Process(target=_vnstock_fetch_worker, args=(ticker, start.isoformat(), end.isoformat(), source, result_queue))
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(5)
        raise TimeoutError(f"per-ticker timeout exceeded after {timeout_seconds:.2f}s")
    try:
        status, payload, error_type, error_message = result_queue.get_nowait()
    except queue.Empty:
        if process.exitcode and process.exitcode != 0:
            raise RuntimeError(f"vnstock worker exited with code {process.exitcode}")
        return pd.DataFrame()
    if status == "ok":
        return _ensure_frame(payload)
    if error_type == "SystemExit":
        raise SystemExit(error_message)
    raise RuntimeError(f"{error_type}: {error_message}")


def _vnstock_fetch_worker(ticker: str, start_iso: str, end_iso: str, source: str, result_queue: mp.Queue) -> None:
    try:
        configure_utf8_logging()
        start = pd.to_datetime(start_iso, utc=True).to_pydatetime()
        end = pd.to_datetime(end_iso, utc=True).to_pydatetime()
        frame = fetch_vnstock_vci_history(ticker, start, end, source)
        result_queue.put(("ok", frame, "", ""))
    except BaseException as exc:  # noqa: BLE001 - child sends structured error to parent
        result_queue.put(("error", None, exc.__class__.__name__, _clean_error_message(str(exc))))


def fetch_vnstock_vci_history(ticker: str, start: datetime, end: datetime, source: str = "VCI") -> pd.DataFrame:
    configure_utf8_logging()
    output_buffer = io.StringIO()
    error_buffer = io.StringIO()
    with contextlib.redirect_stdout(output_buffer), contextlib.redirect_stderr(error_buffer):
        try:
            from vnstock import Quote  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(f"VNSTOCK_IMPORT_ERROR: {exc}") from exc
        quote = Quote(symbol=str(ticker).upper(), source=source)
        try:
            return quote.history(start=start.date().isoformat(), end=end.date().isoformat(), interval="1D")
        except TypeError:
            return quote.history(start=start.date().isoformat(), end=end.date().isoformat())


def normalize_history_frame(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if not isinstance(raw, pd.DataFrame) or raw.empty:
        return pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume", "value"])
    date_col = _first_column(raw, ["time", "date", "trading_date", "tradingDate", "Date"])
    close_col = _first_column(raw, ["close", "Close", "close_price", "price", "last_close"])
    if not date_col or not close_col:
        return pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume", "value"])
    open_col = _first_column(raw, ["open", "Open", "open_price"])
    high_col = _first_column(raw, ["high", "High", "high_price"])
    low_col = _first_column(raw, ["low", "Low", "low_price"])
    volume_col = _first_column(raw, ["volume", "Volume", "trading_volume", "total_volume", "vol", "match_volume", "matching_volume"])
    value_col = _first_column(raw, ["value", "trading_value", "turnover", "total_value"])
    out = pd.DataFrame(
        {
            "ticker": str(ticker).upper(),
            "date": pd.to_datetime(raw[date_col], errors="coerce"),
            "open": _num(raw[open_col]) if open_col else pd.Series([pd.NA] * len(raw)),
            "high": _num(raw[high_col]) if high_col else pd.Series([pd.NA] * len(raw)),
            "low": _num(raw[low_col]) if low_col else pd.Series([pd.NA] * len(raw)),
            "close": _num(raw[close_col]),
            "volume": _num(raw[volume_col]) if volume_col else pd.Series([pd.NA] * len(raw)),
            "value": _num(raw[value_col]) if value_col else pd.Series([pd.NA] * len(raw)),
        }
    )
    return out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)


def build_snapshot_row(
    *,
    ticker: str,
    exchange: str,
    source: str,
    raw: pd.DataFrame,
    normalized: pd.DataFrame,
    fetch_error_type: str,
    fetch_error_message: str,
    stale_threshold: int,
    min_rows: int,
    cache_used: bool,
    attempt_count: int,
    batch_id: str,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    error_type = fetch_error_type if fetch_error_type in ERROR_TYPES else "UNKNOWN_ERROR"
    if error_type == "OK" and len(normalized) < min_rows:
        error_type = "EMPTY_HISTORY"
    valid = normalized.copy() if isinstance(normalized, pd.DataFrame) else pd.DataFrame()
    market_ok = error_type == "OK" and not valid.empty
    first_date = ""
    last_date = ""
    last_close: Any = ""
    last_volume: Any = ""
    last_value: Any = ""
    avg_volume_20: Any = ""
    avg_volume_60: Any = ""
    avg_value_20: Any = ""
    avg_value_60: Any = ""
    stale = True
    days_since: Any = ""
    if market_ok:
        first_date = pd.to_datetime(valid["date"]).min().date().isoformat()
        last_dt = pd.to_datetime(valid["date"]).max().date()
        last_date = last_dt.isoformat()
        last_row = valid.sort_values("date").iloc[-1]
        last_close = _to_number_or_blank(last_row.get("close"))
        last_volume = _last_number(valid.get("volume"))
        last_value = _last_number(valid.get("value"))
        avg_volume_20 = _mean_tail(valid.get("volume"), 20)
        avg_volume_60 = _mean_tail(valid.get("volume"), 60)
        avg_value_20 = _mean_tail(valid.get("value"), 20)
        avg_value_60 = _mean_tail(valid.get("value"), 60)
        days_since = max(0, (now.date() - last_dt).days)
        stale = bool(days_since > stale_threshold)
    liquidity_available = not _is_missing(last_volume) or not _is_missing(last_value) or not _is_missing(avg_volume_20)
    missing_fields = _missing_market_fields(last_date, last_close, last_volume, avg_volume_20, avg_volume_60)
    return {
        "ticker": str(ticker).upper(),
        "exchange_if_available": exchange,
        "market_source": f"vnstock:{source}",
        "fetch_status": "OK" if market_ok else "FAILED",
        "fetch_error_type": "OK" if market_ok else error_type,
        "fetch_error_message": "" if market_ok else fetch_error_message,
        "history_row_count": int(len(valid) if market_ok else len(raw) if isinstance(raw, pd.DataFrame) else 0),
        "first_price_date": first_date,
        "last_price_date": last_date,
        "last_close": last_close,
        "last_volume": last_volume,
        "last_value_if_available": last_value,
        "avg_volume_20d": avg_volume_20,
        "avg_volume_60d": avg_volume_60,
        "avg_value_20d_if_available": avg_value_20,
        "avg_value_60d_if_available": avg_value_60,
        "recent_price_available": bool(last_date),
        "market_data_available": bool(market_ok),
        "liquidity_data_available": bool(liquidity_available),
        "stale_market_data": bool(stale),
        "calendar_days_since_last_price": days_since,
        "missing_market_fields": _json_list(missing_fields),
        "cache_used": bool(cache_used),
        "attempt_count": int(attempt_count),
        "batch_id": batch_id,
        "created_at": now.replace(microsecond=0).isoformat(),
    }


def classify_fetch_error(exc: BaseException | str) -> str:
    text = str(exc).lower()
    if isinstance(exc, SystemExit):
        return "SOURCE_RATE_LIMIT_OR_TIMEOUT"
    if any(token in text for token in ["unicode", "charmap", "codec", "encoding", "decode", "encode"]):
        return "ENV_ENCODING_ERROR"
    if any(token in text for token in ["timeout", "timed out", "retryerror", "rate limit", "too many requests", "429"]):
        return "SOURCE_RATE_LIMIT_OR_TIMEOUT"
    if any(token in text for token in ["invalid ticker", "invalid symbol", "not found", "symbol", "ticker"]):
        return "TICKER_MAPPING_ERROR"
    if any(token in text for token in ["connection", "network", "request", "http", "ssl"]):
        return "SOURCE_REQUEST_ERROR"
    if "vnstock" in text or "quote" in text or "api" in text:
        return "VNSTOCK_API_ERROR"
    return "UNKNOWN_ERROR"


def build_pipeline_vs_step26_impact(snapshot: pd.DataFrame, step26_lookup: dict[str, dict[str, Any]], step26_blocked: set[str], step26_watchlist: set[str]) -> pd.DataFrame:
    records = []
    for _, row in snapshot.iterrows():
        ticker = str(row.get("ticker", ""))
        ok = str(row.get("fetch_error_type", "")) == "OK"
        if ticker in step26_blocked and ok:
            label = "RECOVERED_FROM_STEP26_BLOCKED"
        elif ticker in step26_blocked and not ok:
            label = "STILL_BLOCKED_AFTER_REFRESH"
        elif ticker in step26_watchlist and ok:
            label = "ALREADY_VALID_IN_STEP26"
        elif ok:
            label = "NEWLY_VALID_MARKET_DATA"
        else:
            label = "FETCH_FAILED_NEEDS_RETRY_OR_MAPPING_FIX"
        prior = step26_lookup.get(ticker, {})
        records.append(
            {
                "ticker": ticker,
                "step26_status": prior.get("screening_status", ""),
                "step26_missing_fields": prior.get("missing_fields", ""),
                "step26_block_reasons": prior.get("block_reasons", ""),
                "step28_fetch_error_type": row.get("fetch_error_type", ""),
                "step28_market_data_available": row.get("market_data_available", False),
                "step28_last_price_date": row.get("last_price_date", ""),
                "step28_last_close": row.get("last_close", ""),
                "recovery_label": label,
            }
        )
    return pd.DataFrame(records)


def build_step27_repair_recheck(snapshot: pd.DataFrame, step27_repair: set[str]) -> pd.DataFrame:
    if not step27_repair:
        return pd.DataFrame(columns=["ticker", "step27_in_repair_queue", "step28_fetch_ok", "step28_fetch_error_type", "last_price_date", "last_close"])
    subset = snapshot[snapshot["ticker"].isin(step27_repair)].copy()
    if subset.empty:
        return pd.DataFrame(columns=["ticker", "step27_in_repair_queue", "step28_fetch_ok", "step28_fetch_error_type", "last_price_date", "last_close"])
    return pd.DataFrame(
        {
            "ticker": subset["ticker"],
            "step27_in_repair_queue": True,
            "step28_fetch_ok": subset["fetch_error_type"].eq("OK"),
            "step28_fetch_error_type": subset["fetch_error_type"],
            "last_price_date": subset["last_price_date"],
            "last_close": subset["last_close"],
        }
    )


def build_fetch_error_summary(snapshot: pd.DataFrame) -> pd.DataFrame:
    if snapshot.empty:
        return pd.DataFrame(columns=["fetch_error_type", "count", "example_tickers"])
    records = []
    for error_type, group in snapshot.groupby("fetch_error_type", dropna=False):
        records.append({"fetch_error_type": str(error_type), "count": int(len(group)), "example_tickers": _json_list(group["ticker"].head(10).tolist())})
    return pd.DataFrame(records).sort_values(["count", "fetch_error_type"], ascending=[False, True])


def build_missing_market_field_summary(snapshot: pd.DataFrame) -> pd.DataFrame:
    counts: dict[str, list[str]] = {}
    for _, row in snapshot.iterrows():
        for field in parse_listish(row.get("missing_market_fields", "")):
            counts.setdefault(field, [])
            if len(counts[field]) < 10:
                counts[field].append(str(row.get("ticker", "")))
    records = [
        {"missing_market_field": field, "count": int(snapshot["missing_market_fields"].astype(str).str.contains(field, regex=False).sum()), "example_tickers": _json_list(tickers)}
        for field, tickers in sorted(counts.items())
    ]
    return pd.DataFrame(records, columns=["missing_market_field", "count", "example_tickers"])


def build_step28_summary(
    *,
    config: dict[str, Any],
    resolution: Step28InputResolution,
    snapshot: pd.DataFrame,
    step26_blocked_count: int,
    step26_watchlist_count: int,
    step27_repair_count: int,
    recovered_count: int,
    still_failed_count: int,
    step27_recovered_count: int,
    forbidden_terms_found: list[str],
    core_outputs_modified: bool,
) -> dict[str, Any]:
    total = int(len(snapshot))
    ok_count = int(snapshot["fetch_error_type"].eq("OK").sum()) if not snapshot.empty else 0
    failed_count = total - ok_count
    empty_count = int(snapshot["fetch_error_type"].eq("EMPTY_HISTORY").sum()) if not snapshot.empty else 0
    encoding_count = int(snapshot["fetch_error_type"].eq("ENV_ENCODING_ERROR").sum()) if not snapshot.empty else 0
    mapping_count = int(snapshot["fetch_error_type"].eq("TICKER_MAPPING_ERROR").sum()) if not snapshot.empty else 0
    normalization_count = int(snapshot["fetch_error_type"].eq("NORMALIZATION_ERROR").sum()) if not snapshot.empty else 0
    coverage_improvement = max(0, ok_count - step26_watchlist_count)
    improvement_pct = round((coverage_improvement / total * 100), 4) if total else None
    final_decision = _final_decision(recovered_count, total, encoding_count, failed_count, bool(resolution.missing_input_files))
    alternative_needed = _paid_data_needed(recovered_count, empty_count, failed_count, encoding_count, mapping_count, normalization_count)
    return {
        "step_id": STEP_ID,
        "run_timestamp": _now(),
        "source_family": "vnstock",
        "market_source": "VCI",
        "expected_universe_size": int(config.get("expected_universe_size", 1743) or 1743),
        "total_tickers_attempted": total,
        "fetch_ok_count": ok_count,
        "fetch_failed_count": failed_count,
        "empty_history_count": empty_count,
        "encoding_error_count": encoding_count,
        "ticker_mapping_error_count": mapping_count,
        "normalization_error_count": normalization_count,
        "step26_blocked_count_input": int(step26_blocked_count),
        "step26_blocked_recovered_count": int(recovered_count),
        "step26_blocked_still_failed_count": int(still_failed_count),
        "step27_repair_queue_count_input": int(step27_repair_count),
        "step27_repair_queue_recovered_count": int(step27_recovered_count),
        "market_coverage_before_step28_if_known": int(step26_watchlist_count),
        "market_coverage_after_step28": ok_count,
        "coverage_improvement_count": int(coverage_improvement),
        "coverage_improvement_pct_points": improvement_pct,
        "alternative_paid_data_needed_for_market": alternative_needed,
        "final_decision": final_decision,
        "guardrails": dict(GUARDRAILS),
        "forbidden_terms_found": forbidden_terms_found,
        "core_outputs_modified": bool(core_outputs_modified),
        "missing_input_files": resolution.missing_input_files,
        "duplicate_tickers": resolution.duplicate_tickers,
    }


def write_step28_outputs(output_dir: Path, result: Step28Result) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "step28_market_refresh_summary.json", result.summary)
    result.market_snapshot_rows.to_csv(output_dir / "market_snapshot_rows.csv", index=False, encoding="utf-8")
    result.market_snapshot_success.to_csv(output_dir / "market_snapshot_success.csv", index=False, encoding="utf-8")
    result.market_snapshot_failed.to_csv(output_dir / "market_snapshot_failed.csv", index=False, encoding="utf-8")
    result.step26_blocked_recovered.to_csv(output_dir / "step26_blocked_recovered.csv", index=False, encoding="utf-8")
    result.step26_blocked_still_failed.to_csv(output_dir / "step26_blocked_still_failed.csv", index=False, encoding="utf-8")
    result.step27_repair_queue_recheck.to_csv(output_dir / "step27_repair_queue_recheck.csv", index=False, encoding="utf-8")
    result.ticker_fetch_error_summary.to_csv(output_dir / "ticker_fetch_error_summary.csv", index=False, encoding="utf-8")
    result.missing_market_field_summary.to_csv(output_dir / "missing_market_field_summary.csv", index=False, encoding="utf-8")
    result.batch_fetch_manifest.to_csv(output_dir / "batch_fetch_manifest.csv", index=False, encoding="utf-8")
    result.pipeline_vs_step26_repair_impact.to_csv(output_dir / "pipeline_vs_step26_repair_impact.csv", index=False, encoding="utf-8")
    _write_json(output_dir / "run_manifest.json", result.run_manifest)


def build_run_manifest(
    *,
    config_path: Path,
    output_dir: Path,
    raw_cache_dir: Path,
    command_used: str,
    resolution: Step28InputResolution,
    universe_count: int,
    started_at: datetime,
    core_outputs_modified: bool,
) -> dict[str, Any]:
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "commit_hash": _git_commit_hash(),
        "command_used": command_used,
        "config_path": str(config_path),
        "output_dir": str(output_dir),
        "raw_cache_dir": str(raw_cache_dir),
        "raw_cache_committed": False,
        "universe_count": int(universe_count),
        "started_at": started_at.replace(microsecond=0).isoformat(),
        "finished_at": _now(),
        "network_usage_if_known": "vnstock_vci_only",
        "core_outputs_modified": bool(core_outputs_modified),
        "previous_step_outputs_mutated": bool(core_outputs_modified),
        "input_resolution": {
            "step25_universe_rows_path": str(resolution.step25_universe_rows_path or ""),
            "step26_audit_rows_path": str(resolution.step26_audit_rows_path or ""),
            "step27_repair_queue_path": str(resolution.step27_repair_queue_path or ""),
            "missing_input_files": resolution.missing_input_files,
            "duplicate_tickers": resolution.duplicate_tickers,
            "notes": resolution.notes,
        },
    }


def scan_forbidden_terms(output_dir: Path) -> list[str]:
    hits: list[str] = []
    if not output_dir.exists():
        return hits
    for path in sorted(output_dir.glob("*")):
        if path.suffix.lower() not in {".csv", ".json", ".md", ".txt"}:
            continue
        text = _scan_text(path)
        for line_no, line in enumerate(text.splitlines(), start=1):
            lower = line.lower()
            for term in FORBIDDEN_TERMS:
                if _term_in_text(term, lower):
                    hits.append(f"{path.name}:{line_no}:{term}")
    return hits


def _input_missing_result(config: dict[str, Any], config_path: Path, output: Path, raw_cache_dir: Path, resolution: Step28InputResolution, command_used: str) -> Step28Result:
    empty_snapshot = pd.DataFrame(columns=SNAPSHOT_COLUMNS)
    empty_manifest = pd.DataFrame(columns=BATCH_COLUMNS)
    summary = build_step28_summary(
        config=config,
        resolution=resolution,
        snapshot=empty_snapshot,
        step26_blocked_count=0,
        step26_watchlist_count=0,
        step27_repair_count=0,
        recovered_count=0,
        still_failed_count=0,
        step27_recovered_count=0,
        forbidden_terms_found=[],
        core_outputs_modified=False,
    )
    summary["final_decision"] = "FAIL_MARKET_REFRESH_INPUT_MISSING"
    manifest = build_run_manifest(
        config_path=config_path,
        output_dir=output,
        raw_cache_dir=raw_cache_dir,
        command_used=command_used,
        resolution=resolution,
        universe_count=0,
        started_at=datetime.now(UTC),
        core_outputs_modified=False,
    )
    return Step28Result(
        summary=summary,
        market_snapshot_rows=empty_snapshot,
        market_snapshot_success=empty_snapshot.copy(),
        market_snapshot_failed=empty_snapshot.copy(),
        step26_blocked_recovered=pd.DataFrame(),
        step26_blocked_still_failed=pd.DataFrame(),
        step27_repair_queue_recheck=pd.DataFrame(),
        ticker_fetch_error_summary=pd.DataFrame(columns=["fetch_error_type", "count", "example_tickers"]),
        missing_market_field_summary=pd.DataFrame(columns=["missing_market_field", "count", "example_tickers"]),
        batch_fetch_manifest=empty_manifest,
        pipeline_vs_step26_repair_impact=pd.DataFrame(),
        run_manifest=manifest,
    )


def _final_decision(recovered: int, total: int, encoding_errors: int, failed: int, missing_inputs: bool) -> str:
    if missing_inputs:
        return "FAIL_MARKET_REFRESH_INPUT_MISSING"
    if recovered >= 500:
        return "PASS_MARKET_REFRESH_WITH_MAJOR_RECOVERY"
    if recovered >= 1:
        return "PASS_MARKET_REFRESH_WITH_PARTIAL_RECOVERY"
    if failed and encoding_errors / max(failed, 1) > 0.5:
        return "FAIL_MARKET_REFRESH_ENVIRONMENT_BLOCKED"
    return "PASS_MARKET_REFRESH_NO_MEANINGFUL_RECOVERY"


def _paid_data_needed(recovered: int, empty_count: int, failed_count: int, encoding_count: int, mapping_count: int, normalization_count: int) -> bool | None:
    if recovered > 0 or encoding_count or mapping_count or normalization_count:
        return False
    if failed_count and empty_count / max(failed_count, 1) > 0.8:
        return True
    return None


def _resolve_path(configured: Any, token_sets: list[list[str]], suffix: str) -> Path | None:
    if configured:
        path = Path(str(configured))
        if path.exists():
            return path
    root = Path("data/reports")
    if not root.exists():
        return None
    candidates = sorted(root.rglob(f"*{suffix}"))
    for tokens in token_sets:
        for path in candidates:
            lower = str(path).lower().replace("\\", "/")
            if all(token.lower() in lower for token in tokens):
                return path
    return None


def _read_csv(path: str | Path | None) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame()
    target = Path(path)
    if not target.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(target, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _build_step26_lookup(step26_rows: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if step26_rows.empty or "ticker" not in step26_rows.columns:
        return {}
    frame = step26_rows.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    return {str(row["ticker"]): row.to_dict() for _, row in frame.drop_duplicates("ticker").iterrows()}


def _step26_tickers_by_status(step26_rows: pd.DataFrame, status: str) -> set[str]:
    if step26_rows.empty or "ticker" not in step26_rows.columns or "screening_status" not in step26_rows.columns:
        return set()
    rows = step26_rows[step26_rows["screening_status"].astype(str).eq(status)]
    return set(rows["ticker"].astype(str).str.upper().str.strip())


def _ticker_series(frame: pd.DataFrame) -> list[str]:
    if frame.empty or "ticker" not in frame.columns:
        return []
    return [ticker for ticker in frame["ticker"].astype(str).str.upper().str.strip().tolist() if ticker]


def _duplicate_tickers(frame: pd.DataFrame) -> list[str]:
    if frame.empty:
        return []
    ticker_col = _first_column(frame, ["ticker", "symbol", "code"])
    if not ticker_col:
        return []
    tickers = frame[ticker_col].astype(str).str.upper().str.strip()
    return sorted(tickers[tickers.duplicated()].unique().tolist())


def _core_paths_from_resolution(resolution: Step28InputResolution) -> list[Path]:
    return [path for path in [resolution.step25_universe_rows_path, resolution.step26_audit_rows_path, resolution.step27_repair_queue_path] if path is not None]


def _write_cache(cache_json: Path, raw_csv: Path, snapshot: dict[str, Any], raw: pd.DataFrame) -> None:
    cache_json.parent.mkdir(parents=True, exist_ok=True)
    _write_json(cache_json, {"snapshot": snapshot})
    if isinstance(raw, pd.DataFrame) and not raw.empty:
        raw.to_csv(raw_csv, index=False, encoding="utf-8")


def _manifest_from_snapshot(snapshot: dict[str, Any], batch_id: str, batch_index: int, ticker_index: int, started: datetime, finished: datetime) -> dict[str, Any]:
    return {
        "batch_id": batch_id,
        "batch_index": int(batch_index),
        "ticker": snapshot.get("ticker", ""),
        "ticker_index": int(ticker_index),
        "fetch_status": snapshot.get("fetch_status", ""),
        "fetch_error_type": snapshot.get("fetch_error_type", ""),
        "attempt_count": int(snapshot.get("attempt_count", 0) or 0),
        "cache_used": bool(snapshot.get("cache_used", False)),
        "history_row_count": int(snapshot.get("history_row_count", 0) or 0),
        "started_at": started.replace(microsecond=0).isoformat(),
        "finished_at": finished.replace(microsecond=0).isoformat(),
        "duration_ms": int((finished - started).total_seconds() * 1000),
    }


def _missing_market_fields(last_date: Any, last_close: Any, last_volume: Any, avg_volume_20: Any, avg_volume_60: Any) -> list[str]:
    fields = []
    for name, value in [
        ("last_price_date", last_date),
        ("last_close", last_close),
        ("last_volume", last_volume),
        ("avg_volume_20d", avg_volume_20),
        ("avg_volume_60d", avg_volume_60),
    ]:
        if _is_missing(value):
            fields.append(name)
    return fields


def _first_column(frame: pd.DataFrame, candidates: list[str]) -> str:
    lowered = {str(column).strip().lower(): str(column) for column in frame.columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return ""


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _ensure_frame(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    if value is None:
        return pd.DataFrame()
    try:
        return pd.DataFrame(value)
    except Exception:
        return pd.DataFrame()


def _to_number_or_blank(value: Any) -> Any:
    if _is_missing(value):
        return ""
    try:
        return float(value)
    except (TypeError, ValueError):
        return ""


def _last_number(series: pd.Series | None) -> Any:
    if series is None:
        return ""
    values = pd.to_numeric(series, errors="coerce").dropna()
    return round(float(values.iloc[-1]), 4) if not values.empty else ""


def _mean_tail(series: pd.Series | None, count: int) -> Any:
    if series is None:
        return ""
    values = pd.to_numeric(series, errors="coerce").dropna()
    return round(float(values.tail(count).mean()), 4) if not values.empty else ""


def _is_missing(value: Any) -> bool:
    return value is None or str(value).strip() == "" or str(value).strip().lower() in {"nan", "none", "null", "na", "<na>"}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _json_list(values: list[Any]) -> str:
    return json.dumps([str(value) for value in values if not _is_missing(value)], ensure_ascii=False)


def parse_listish(value: Any) -> list[str]:
    if _is_missing(value):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if not _is_missing(item)]
    text = str(value).strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if not _is_missing(item)]
        text = text.strip("[]")
    return [part.strip() for part in re.split(r"[;,]", text) if part.strip()]


def _clean_error_message(message: str) -> str:
    return str(message).replace("\r", " ").replace("\n", " ")[:500]


def _hashes(paths: list[Path]) -> dict[str, str]:
    return {str(path): _hash_file(path) for path in paths if path.exists()}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _git_commit_hash() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:  # noqa: BLE001
        return ""
    return completed.stdout.strip()


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _run_date() -> str:
    return datetime.now(UTC).date().isoformat()


def _term_in_text(term: str, lower_text: str) -> bool:
    if " " in term:
        return term in lower_text
    return re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", lower_text) is not None


def _scan_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() != ".json":
        return text
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(data, dict):
        data = dict(data)
        data.pop("forbidden_terms_found", None)
        data.pop("guardrails", None)
    return json.dumps(data, ensure_ascii=False, indent=2)
