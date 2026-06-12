"""STEP25 full-universe primary-only scale engine.

This module scales the provisional screening pass across a broad ticker universe
using existing primary-only artifacts. It does not scrape official filings,
perform OCR, or produce trade guidance.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


STEP_ID = "STEP25-FULL-UNIVERSE-1743-PRIMARY-ONLY-SCALE"
MODE = "full_universe_primary_only_scale"

FINANCE_FIELDS = [
    "revenue",
    "gross_profit",
    "net_income",
    "total_assets",
    "total_liabilities",
    "equity",
    "cfo",
    "capex",
]

SCREENING_STATUSES = {
    "BLOCKED_INSUFFICIENT_MARKET_DATA",
    "BLOCKED_STALE_MARKET_DATA",
    "BLOCKED_TOO_ILLIQUID",
    "BLOCKED_MISSING_MINIMUM_FINANCE",
    "WATCHLIST_CANDIDATE",
    "MANUAL_REVIEW",
    "INSUFFICIENT_DATA",
    "FAILED_FETCH",
}

FINAL_DECISIONS = {
    "PASS_FULL_UNIVERSE_PRIMARY_ONLY_WITH_WARNINGS",
    "PARTIAL_PASS_FULL_UNIVERSE_PRIMARY_ONLY",
    "BLOCKED_FULL_UNIVERSE_PRIMARY_ONLY",
}

FORBIDDEN_TERMS = [
    "buy",
    "sell",
    "hold",
    "buy now",
    "sell now",
    "target price",
    "fair value",
    "intrinsic value",
    "margin of safety",
    "expected return",
    "entry price",
    "exit price",
    "stoploss",
    "take profit",
    "recommended portfolio",
    "strategy beats market",
    "guaranteed alpha",
]

ROW_COLUMNS = [
    "ticker",
    "exchange",
    "company_name",
    "screening_status",
    "market_source_confidence",
    "finance_source_confidence",
    "crosscheck_status",
    "verification_status",
    "manual_review_required",
    "manual_bctc_required",
    "independent_market_crosscheck_required_later",
    "finance_crosscheck_required_later",
    "evidence_debt_reason",
    "missing_fields",
    "block_reasons",
    "reason_to_review",
    "last_price_date",
    "last_close",
    "avg_volume_20d",
    "avg_volume_60d",
    "last_volume",
    "stale_days",
    "trading_days_60d",
    "recent_trading_value",
    "market_fetch_status",
    "finance_missing_fields",
    "finance_quality_status",
    "finance_source_layer",
    "source",
    "source_family",
    "fetch_time",
    "batch_id",
]

UNIVERSE_COLUMNS = ["ticker", "exchange", "company_name", "source", "source_family", "fetch_time", "source_confidence"]
QUEUE_COLUMNS = [
    "ticker",
    "exchange",
    "company_name",
    "screening_status",
    "reason_to_review",
    "missing_fields",
    "market_source_confidence",
    "finance_source_confidence",
    "crosscheck_status",
    "verification_status",
    "manual_bctc_required",
    "evidence_debt_reason",
    "batch_id",
]
FAILED_COLUMNS = ["ticker", "batch_id", "failure_reason", "missing_fields", "market_source_confidence", "finance_source_confidence", "verification_status"]
BATCH_MANIFEST_COLUMNS = [
    "batch_id",
    "batch_start_index",
    "batch_end_index",
    "ticker_count",
    "success_count",
    "failed_count",
    "skipped_count",
    "warning_count",
    "cache_used",
    "created_at",
]


class Step25SafeRunBlocked(RuntimeError):
    """Raised when a requested Step25 run violates scope controls."""


@dataclass
class Step25Result:
    rows: pd.DataFrame
    watchlist_candidates: pd.DataFrame
    manual_bctc_review_queue: pd.DataFrame
    blocked_tickers: pd.DataFrame
    failed_tickers: pd.DataFrame
    data_coverage_report: pd.DataFrame
    batch_run_manifest: pd.DataFrame
    source_confidence_summary: pd.DataFrame
    unresolved_fields_report: pd.DataFrame
    evidence_debt_report: dict[str, Any]
    run_manifest: dict[str, Any]
    summary: dict[str, Any]


def load_step25_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("STEP25 config must be a mapping.")
    return data


def run_step25_full_universe_1743_primary_only_scale(
    *,
    config_path: str | Path,
    output_dir: str | Path | None = None,
    max_tickers: int | None = None,
    batch_size: int | None = None,
    allow_partial: bool | None = None,
    resume_from_cache: bool | None = None,
    command_used: str = "",
    core_output_paths: list[str | Path] | None = None,
) -> Step25Result:
    config = load_step25_config(config_path)
    validate_step25_config(config)
    limits = config.get("limits") or {}
    if not _as_bool(limits.get("full_universe_allowed", False)):
        raise Step25SafeRunBlocked("STEP25 full-universe permission must be explicit.")

    outputs = config.get("outputs") or {}
    output = Path(output_dir or outputs.get("output_dir") or "data/reports/step25_full_universe_1743_primary_only_scale")
    raw_cache_dir = Path(outputs.get("raw_cache_dir") or "data/raw/step25_full_universe_1743")
    batch_dir = Path(outputs.get("batch_manifest_dir") or (output / "batches"))
    output.mkdir(parents=True, exist_ok=True)
    raw_cache_dir.mkdir(parents=True, exist_ok=True)
    batch_dir.mkdir(parents=True, exist_ok=True)

    requested_max = int(limits.get("max_tickers", 1743) or 1743) if max_tickers is None else int(max_tickers)
    config_max = int(limits.get("max_tickers", 1743) or 1743)
    if requested_max != config_max and not _as_bool(limits.get("allow_limit_override", False)):
        raise Step25SafeRunBlocked("STEP25 max_tickers override is disabled by config.")
    requested_max = min(requested_max, config_max)

    configured_batch = int((config.get("batching") or {}).get("batch_size", limits.get("batch_size", 100)) or 100)
    effective_batch_size = configured_batch if batch_size is None else int(batch_size)
    if effective_batch_size <= 0:
        raise ValueError("STEP25 batch_size must be positive.")

    run_policy = dict(config.get("run") or {})
    if allow_partial is not None:
        run_policy["allow_partial"] = bool(allow_partial)
    if resume_from_cache is not None:
        run_policy["resume_from_cache"] = bool(resume_from_cache)
    allow_partial_effective = _as_bool(run_policy.get("allow_partial", True))
    resume_effective = _as_bool(run_policy.get("resume_from_cache", True)) and _as_bool((config.get("batching") or {}).get("resume_from_cache", True))

    core_paths = [Path(path) for path in (core_output_paths or config.get("core_output_watchlist", []))]
    before_hashes = _hashes(core_paths)

    universe, universe_source = resolve_universe(config)
    actual_universe_count = int(len(universe))
    capped_universe = universe.head(requested_max).copy()
    market = load_market_data(config)
    finance = _read_csv((config.get("inputs") or {}).get("finance_latest_wide", ""))
    quality = _read_csv((config.get("inputs") or {}).get("finance_quality_flags", ""))
    raw_universe_path = raw_cache_dir / "resolved_universe.csv"
    capped_universe.to_csv(raw_universe_path, index=False)

    rows, batch_manifest = run_batches(
        config=config,
        universe=capped_universe,
        market=market,
        finance=finance,
        quality=quality,
        batch_dir=batch_dir,
        batch_size=effective_batch_size,
        allow_partial=allow_partial_effective,
        resume_from_cache=resume_effective,
    )
    watchlist = rows[rows["screening_status"].eq("WATCHLIST_CANDIDATE")].copy() if not rows.empty else pd.DataFrame(columns=ROW_COLUMNS)
    manual_queue = rows[rows["manual_bctc_required"].map(_as_bool)].reindex(columns=QUEUE_COLUMNS) if not rows.empty else pd.DataFrame(columns=QUEUE_COLUMNS)
    blocked = rows[rows["screening_status"].astype(str).str.startswith("BLOCKED_")].copy() if not rows.empty else pd.DataFrame(columns=ROW_COLUMNS)
    failed = build_failed_tickers(rows)
    data_coverage = build_data_coverage_report(rows)
    source_summary = build_source_confidence_summary(rows)
    unresolved = build_unresolved_fields_report(rows)
    core_modified = before_hashes != _hashes(core_paths)
    summary = build_summary(
        config=config,
        requested_max_tickers=requested_max,
        actual_universe_count=actual_universe_count,
        rows=rows,
        watchlist=watchlist,
        manual_queue=manual_queue,
        blocked=blocked,
        failed=failed,
        batch_manifest=batch_manifest,
        forbidden_hits=[],
        core_outputs_modified=core_modified,
    )
    evidence_debt = build_evidence_debt_report(rows, summary, universe_source)
    manifest = build_run_manifest(
        config=config,
        config_path=Path(config_path),
        output_dir=output,
        raw_cache_dir=raw_cache_dir,
        batch_dir=batch_dir,
        command_used=command_used,
        requested_max_tickers=requested_max,
        actual_universe_count=actual_universe_count,
        batch_size=effective_batch_size,
        allow_partial=allow_partial_effective,
        resume_from_cache=resume_effective,
        core_outputs_modified=core_modified,
        universe_source=universe_source,
        raw_universe_path=raw_universe_path,
    )
    write_step25_outputs(
        output_dir=output,
        rows=rows,
        watchlist=watchlist,
        manual_queue=manual_queue,
        blocked=blocked,
        failed=failed,
        data_coverage=data_coverage,
        evidence_debt=evidence_debt,
        batch_manifest=batch_manifest,
        source_summary=source_summary,
        unresolved=unresolved,
        summary=summary,
        manifest=manifest,
    )
    forbidden_hits = scan_forbidden_terms(output, extra_dirs=[batch_dir])
    if forbidden_hits:
        summary = build_summary(
            config=config,
            requested_max_tickers=requested_max,
            actual_universe_count=actual_universe_count,
            rows=rows,
            watchlist=watchlist,
            manual_queue=manual_queue,
            blocked=blocked,
            failed=failed,
            batch_manifest=batch_manifest,
            forbidden_hits=forbidden_hits,
            core_outputs_modified=core_modified,
        )
        write_step25_outputs(
            output_dir=output,
            rows=rows,
            watchlist=watchlist,
            manual_queue=manual_queue,
            blocked=blocked,
            failed=failed,
            data_coverage=data_coverage,
            evidence_debt=evidence_debt,
            batch_manifest=batch_manifest,
            source_summary=source_summary,
            unresolved=unresolved,
            summary=summary,
            manifest=manifest,
        )
    return Step25Result(
        rows=rows,
        watchlist_candidates=watchlist,
        manual_bctc_review_queue=manual_queue,
        blocked_tickers=blocked,
        failed_tickers=failed,
        data_coverage_report=data_coverage,
        batch_run_manifest=batch_manifest,
        source_confidence_summary=source_summary,
        unresolved_fields_report=unresolved,
        evidence_debt_report=evidence_debt,
        run_manifest=manifest,
        summary=summary,
    )


def validate_step25_config(config: dict[str, Any]) -> None:
    if config.get("step_id") != STEP_ID:
        raise ValueError(f"STEP25 config step_id must be {STEP_ID}.")
    safety = config.get("safety") if isinstance(config.get("safety"), dict) else {}
    required = [
        "no_recommendation",
        "no_buy_sell_hold",
        "no_target_price",
        "no_fair_value",
        "no_intrinsic_value",
        "no_margin_of_safety",
        "no_expected_return",
        "no_entry_exit_price",
        "no_portfolio_recommendation",
        "no_strategy_claim",
        "no_pdf_ocr",
        "no_official_bctc_scrape",
        "no_zero_fill",
        "no_previous_report_mutation",
        "no_stage_promotion_to_investment_ready",
    ]
    missing = [key for key in required if safety.get(key) is not True]
    if missing:
        raise ValueError(f"STEP25 safety flags must be true: {','.join(missing)}")
    sources = config.get("primary_sources") or {}
    if sources.get("independent_crosscheck_required") is not False:
        raise ValueError("STEP25 independent_crosscheck_required must be false.")
    if sources.get("independent_crosscheck_status") != "NOT_AVAILABLE":
        raise ValueError("STEP25 independent crosscheck status must remain NOT_AVAILABLE.")


def resolve_universe(config: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    candidates = (config.get("inputs") or {}).get("universe_candidates") or []
    if not isinstance(candidates, list):
        candidates = [candidates]
    for candidate in candidates:
        frame = _read_csv(candidate)
        if frame.empty or "ticker" not in frame.columns:
            continue
        universe = normalize_universe(frame, source_path=str(candidate))
        if not universe.empty:
            return universe, str(candidate)
    fallback_tickers = (config.get("inputs") or {}).get("fallback_tickers") or []
    if fallback_tickers:
        now = _now()
        return pd.DataFrame(
            [
                {
                    "ticker": str(ticker).strip().upper(),
                    "exchange": "",
                    "company_name": "",
                    "source": "config_fallback",
                    "source_family": "config",
                    "fetch_time": now,
                    "source_confidence": "PROVISIONAL_PRIMARY_ONLY",
                }
                for ticker in fallback_tickers
                if str(ticker).strip()
            ],
            columns=UNIVERSE_COLUMNS,
        ), "config:fallback_tickers"
    raise Step25SafeRunBlocked("No usable universe artifact or fallback ticker list found.")


def normalize_universe(frame: pd.DataFrame, *, source_path: str) -> pd.DataFrame:
    now = _now()
    rows = []
    seen: set[str] = set()
    for _, row in frame.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        source_name = _first_non_missing(row.get("source"), row.get("source_name"), source_path)
        rows.append(
            {
                "ticker": ticker,
                "exchange": _first_non_missing(row.get("exchange"), ""),
                "company_name": _first_non_missing(row.get("company_name"), ""),
                "source": source_name,
                "source_family": _source_family(source_name),
                "fetch_time": _first_non_missing(row.get("fetch_time"), row.get("fetched_at"), now),
                "source_confidence": "PROVISIONAL_PRIMARY_ONLY",
            }
        )
    return pd.DataFrame(rows, columns=UNIVERSE_COLUMNS)


def load_market_data(config: dict[str, Any]) -> pd.DataFrame:
    inputs = config.get("inputs") or {}
    frames = []
    primary_spec = inputs.get("market_primary")
    primary_candidates = primary_spec if isinstance(primary_spec, list) else [primary_spec]
    for candidate in primary_candidates:
        frame = _read_csv(candidate)
        if not frame.empty:
            frames.append(frame)
    fallback = _read_csv(inputs.get("market_fallback", ""))
    if not fallback.empty:
        frames.append(fallback)
    if not frames:
        return pd.DataFrame()
    combined: dict[str, dict[str, Any]] = {}
    for frame in frames:
        for _, row in frame.iterrows():
            ticker = str(row.get("ticker", "")).strip().upper()
            if not ticker:
                continue
            existing = combined.get(ticker, {})
            combined[ticker] = _prefer_market_row(existing, row.to_dict())
    return pd.DataFrame(list(combined.values()))


def run_batches(
    *,
    config: dict[str, Any],
    universe: pd.DataFrame,
    market: pd.DataFrame,
    finance: pd.DataFrame,
    quality: pd.DataFrame,
    batch_dir: Path,
    batch_size: int,
    allow_partial: bool,
    resume_from_cache: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    manifests = []
    row_frames = []
    market_by_ticker = _index_by_ticker(market)
    finance_by_ticker = _index_by_ticker(finance)
    quality_by_ticker = _index_by_ticker(quality)
    batch_count = (len(universe) + batch_size - 1) // batch_size
    for batch_index in range(batch_count):
        start = batch_index * batch_size
        end = min(start + batch_size, len(universe))
        batch_id = f"batch_{batch_index + 1:04d}"
        rows_path = batch_dir / f"{batch_id}_rows.csv"
        manifest_path = batch_dir / f"{batch_id}_manifest.json"
        if resume_from_cache and rows_path.exists() and manifest_path.exists():
            rows = _read_csv(rows_path)
            manifest = _read_json(manifest_path)
            manifest["cache_used"] = True
            manifests.append(manifest)
            row_frames.append(rows)
            continue
        batch_universe = universe.iloc[start:end].copy()
        batch_rows = []
        for _, universe_row in batch_universe.iterrows():
            ticker = str(universe_row.get("ticker", "")).strip().upper()
            try:
                if ticker in set((config.get("testing") or {}).get("force_failed_tickers", [])):
                    raise RuntimeError("forced test failure")
                batch_rows.append(
                    build_screening_row(
                        config=config,
                        universe_row=universe_row.to_dict(),
                        market_row=market_by_ticker.get(ticker, {}),
                        finance_row=finance_by_ticker.get(ticker, {}),
                        quality_row=quality_by_ticker.get(ticker, {}),
                        batch_id=batch_id,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                failed_row = build_failed_row(config=config, universe_row=universe_row.to_dict(), batch_id=batch_id, exc=exc)
                batch_rows.append(failed_row)
                if not allow_partial:
                    raise
        rows = pd.DataFrame(batch_rows, columns=ROW_COLUMNS)
        manifest = build_batch_manifest(batch_id=batch_id, start=start, end=end, rows=rows, cache_used=False)
        rows.to_csv(rows_path, index=False)
        _write_json(manifest_path, manifest)
        manifests.append(manifest)
        row_frames.append(rows)
    all_rows = pd.concat(row_frames, ignore_index=True) if row_frames else pd.DataFrame(columns=ROW_COLUMNS)
    return all_rows.reindex(columns=ROW_COLUMNS), pd.DataFrame(manifests, columns=BATCH_MANIFEST_COLUMNS)


def build_screening_row(
    *,
    config: dict[str, Any],
    universe_row: dict[str, Any],
    market_row: dict[str, Any],
    finance_row: dict[str, Any],
    quality_row: dict[str, Any],
    batch_id: str,
) -> dict[str, Any]:
    confidence = config.get("source_confidence") or {}
    filters = config.get("filters") or {}
    ticker = str(universe_row.get("ticker", "")).strip().upper()
    market = _merged_market_row(market_row)
    finance_missing = _finance_missing_fields(finance_row, quality_row)
    missing_market = _missing_market_fields(market)
    status, block_reasons = _screening_status(market, finance_row, finance_missing, missing_market, filters)
    is_candidate = status == "WATCHLIST_CANDIDATE"
    manual_bctc_required = bool(is_candidate or status in {"MANUAL_REVIEW", "INSUFFICIENT_DATA"})
    missing_fields = sorted(set(missing_market + finance_missing))
    evidence_debt = [
        "Market source remains primary-only.",
        "Finance source remains provisional low.",
        "Independent source-family confirmation is not available.",
        "Manual BCTC review is required before deeper analysis.",
    ]
    reason_to_review = (
        "Survived primary-only scale filters; manual BCTC/source verification remains required."
        if is_candidate
        else "; ".join(block_reasons) if block_reasons else "Manual review required by provisional policy."
    )
    return {
        "ticker": ticker,
        "exchange": _first_non_missing(universe_row.get("exchange"), finance_row.get("exchange"), market.get("exchange"), ""),
        "company_name": _first_non_missing(universe_row.get("company_name"), finance_row.get("company_name"), market.get("company_name"), ""),
        "screening_status": status,
        "market_source_confidence": confidence.get("market_source_confidence", "PROVISIONAL_PRIMARY_ONLY"),
        "finance_source_confidence": confidence.get("finance_source_confidence_default", "PROVISIONAL_LOW"),
        "crosscheck_status": confidence.get("crosscheck_status", "NOT_AVAILABLE"),
        "verification_status": confidence.get("verification_status", "NEEDS_MANUAL_BCTC_REVIEW"),
        "manual_review_required": bool(status != "WATCHLIST_CANDIDATE" or manual_bctc_required),
        "manual_bctc_required": bool(manual_bctc_required),
        "independent_market_crosscheck_required_later": True,
        "finance_crosscheck_required_later": True,
        "evidence_debt_reason": _json_list(evidence_debt),
        "missing_fields": _json_list(missing_fields),
        "block_reasons": _json_list(block_reasons),
        "reason_to_review": reason_to_review,
        "last_price_date": market.get("last_price_date", ""),
        "last_close": market.get("last_close", ""),
        "avg_volume_20d": market.get("avg_volume_20d", ""),
        "avg_volume_60d": market.get("avg_volume_60d", ""),
        "last_volume": market.get("last_volume", ""),
        "stale_days": market.get("stale_days", ""),
        "trading_days_60d": market.get("trading_days_60d", ""),
        "recent_trading_value": _recent_trading_value(market),
        "market_fetch_status": _first_non_missing(market.get("fetch_status"), ""),
        "finance_missing_fields": _json_list(finance_missing),
        "finance_quality_status": _first_non_missing(quality_row.get("export_status"), finance_row.get("source_confidence"), "UNKNOWN"),
        "finance_source_layer": _first_non_missing(finance_row.get("source_layer"), quality_row.get("source_layer"), ""),
        "source": _first_non_missing(universe_row.get("source"), ""),
        "source_family": _first_non_missing(universe_row.get("source_family"), ""),
        "fetch_time": _first_non_missing(universe_row.get("fetch_time"), ""),
        "batch_id": batch_id,
    }


def build_failed_row(*, config: dict[str, Any], universe_row: dict[str, Any], batch_id: str, exc: Exception) -> dict[str, Any]:
    confidence = config.get("source_confidence") or {}
    return {
        "ticker": str(universe_row.get("ticker", "")).strip().upper(),
        "exchange": _first_non_missing(universe_row.get("exchange"), ""),
        "company_name": _first_non_missing(universe_row.get("company_name"), ""),
        "screening_status": "FAILED_FETCH",
        "market_source_confidence": confidence.get("market_source_confidence", "PROVISIONAL_PRIMARY_ONLY"),
        "finance_source_confidence": confidence.get("finance_source_confidence_default", "PROVISIONAL_LOW"),
        "crosscheck_status": confidence.get("crosscheck_status", "NOT_AVAILABLE"),
        "verification_status": confidence.get("verification_status", "NEEDS_MANUAL_BCTC_REVIEW"),
        "manual_review_required": True,
        "manual_bctc_required": True,
        "independent_market_crosscheck_required_later": True,
        "finance_crosscheck_required_later": True,
        "evidence_debt_reason": _json_list(["Ticker failed during primary-only scale run.", "Manual review is required."]),
        "missing_fields": _json_list(["failed_ticker"]),
        "block_reasons": _json_list([f"FAILED_FETCH:{type(exc).__name__}"]),
        "reason_to_review": "Ticker failed during primary-only scale run and was logged for manual review.",
        "last_price_date": "",
        "last_close": "",
        "avg_volume_20d": "",
        "avg_volume_60d": "",
        "last_volume": "",
        "stale_days": "",
        "trading_days_60d": "",
        "recent_trading_value": "",
        "market_fetch_status": "FAILED_FETCH",
        "finance_missing_fields": _json_list(FINANCE_FIELDS),
        "finance_quality_status": "UNKNOWN",
        "finance_source_layer": "",
        "source": _first_non_missing(universe_row.get("source"), ""),
        "source_family": _first_non_missing(universe_row.get("source_family"), ""),
        "fetch_time": _first_non_missing(universe_row.get("fetch_time"), ""),
        "batch_id": batch_id,
    }


def build_batch_manifest(*, batch_id: str, start: int, end: int, rows: pd.DataFrame, cache_used: bool) -> dict[str, Any]:
    failed_count = int(rows["screening_status"].eq("FAILED_FETCH").sum()) if not rows.empty else 0
    warning_count = int(rows["screening_status"].ne("WATCHLIST_CANDIDATE").sum()) if not rows.empty else 0
    return {
        "batch_id": batch_id,
        "batch_start_index": int(start),
        "batch_end_index": int(end - 1),
        "ticker_count": int(len(rows)),
        "success_count": int(len(rows) - failed_count),
        "failed_count": failed_count,
        "skipped_count": int(len(rows)) if cache_used else 0,
        "warning_count": warning_count,
        "cache_used": bool(cache_used),
        "created_at": _now(),
    }


def build_failed_tickers(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=FAILED_COLUMNS)
    failed = rows[rows["screening_status"].eq("FAILED_FETCH")].copy()
    if failed.empty:
        return pd.DataFrame(columns=FAILED_COLUMNS)
    failed["failure_reason"] = failed["block_reasons"]
    return failed.reindex(columns=FAILED_COLUMNS)


def build_data_coverage_report(rows: pd.DataFrame) -> pd.DataFrame:
    metrics = []
    total = int(len(rows))
    metrics.append(_coverage_metric("processed_ticker_count", total, "count"))
    for status, count in _counts(rows, "screening_status").items():
        metrics.append(_coverage_metric(f"status_count:{status}", count, "count"))
    metrics.append(_coverage_metric("rows_with_missing_fields", _rows_with_missing_fields(rows), "count"))
    metrics.append(_coverage_metric("missing_field_observation_count", _missing_field_observation_count(rows), "count"))
    metrics.append(_coverage_metric("market_price_present_count", _non_missing_count(rows, "last_close"), "count"))
    metrics.append(_coverage_metric("market_date_present_count", _non_missing_count(rows, "last_price_date"), "count"))
    metrics.append(_coverage_metric("volume_present_count", _non_missing_count(rows, "avg_volume_20d"), "count"))
    metrics.append(_coverage_metric("manual_bctc_required_count", int(rows["manual_bctc_required"].map(_as_bool).sum()) if not rows.empty else 0, "count"))
    return pd.DataFrame(metrics, columns=["metric", "value", "unit"])


def build_source_confidence_summary(rows: pd.DataFrame) -> pd.DataFrame:
    columns = ["market_source_confidence", "finance_source_confidence", "crosscheck_status", "verification_status"]
    records = []
    for column in columns:
        for value, count in _counts(rows, column).items():
            records.append({"field": column, "value": value, "ticker_count": count})
    return pd.DataFrame(records, columns=["field", "value", "ticker_count"])


def build_unresolved_fields_report(rows: pd.DataFrame) -> pd.DataFrame:
    records = []
    for _, row in rows.iterrows():
        ticker = str(row.get("ticker", ""))
        for field in _parse_json_list(row.get("missing_fields", "")):
            records.append(
                {
                    "ticker": ticker,
                    "field_name": field,
                    "status": "UNRESOLVED",
                    "reason": "Missing in primary-only source artifacts.",
                    "batch_id": row.get("batch_id", ""),
                }
            )
    return pd.DataFrame(records, columns=["ticker", "field_name", "status", "reason", "batch_id"])


def build_summary(
    *,
    config: dict[str, Any],
    requested_max_tickers: int,
    actual_universe_count: int,
    rows: pd.DataFrame,
    watchlist: pd.DataFrame,
    manual_queue: pd.DataFrame,
    blocked: pd.DataFrame,
    failed: pd.DataFrame,
    batch_manifest: pd.DataFrame,
    forbidden_hits: list[str],
    core_outputs_modified: bool,
) -> dict[str, Any]:
    confidence = config.get("source_confidence") or {}
    if forbidden_hits or core_outputs_modified or rows.empty:
        decision = "BLOCKED_FULL_UNIVERSE_PRIMARY_ONLY"
    elif len(failed) or len(rows) < min(requested_max_tickers, actual_universe_count):
        decision = "PARTIAL_PASS_FULL_UNIVERSE_PRIMARY_ONLY"
    else:
        decision = "PASS_FULL_UNIVERSE_PRIMARY_ONLY_WITH_WARNINGS"
    if decision not in FINAL_DECISIONS:
        raise ValueError(f"Invalid STEP25 final decision: {decision}")
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "mode": MODE,
        "requested_max_tickers": int(requested_max_tickers),
        "actual_universe_count": int(actual_universe_count),
        "processed_ticker_count": int(len(rows)),
        "watchlist_candidate_count": int(len(watchlist)),
        "manual_bctc_review_queue_count": int(len(manual_queue)),
        "blocked_count": int(len(blocked)),
        "failed_ticker_count": int(len(failed)),
        "batch_count": int(len(batch_manifest)),
        "market_source_confidence": confidence.get("market_source_confidence", "PROVISIONAL_PRIMARY_ONLY"),
        "finance_source_confidence_default": confidence.get("finance_source_confidence_default", "PROVISIONAL_LOW"),
        "crosscheck_status": confidence.get("crosscheck_status", "NOT_AVAILABLE"),
        "verification_status": confidence.get("verification_status", "NEEDS_MANUAL_BCTC_REVIEW"),
        "screening_status_counts": _counts(rows, "screening_status"),
        "forbidden_terms_found": forbidden_hits,
        "core_outputs_modified": bool(core_outputs_modified),
        "final_decision": decision,
    }


def build_evidence_debt_report(rows: pd.DataFrame, summary: dict[str, Any], universe_source: str) -> dict[str, Any]:
    missing_counts: dict[str, int] = {}
    for value in rows.get("missing_fields", pd.Series(dtype=str)).astype(str):
        for field in _parse_json_list(value):
            missing_counts[field] = missing_counts.get(field, 0) + 1
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "universe_source": universe_source,
        "limitations": [
            "Full-universe pass remains primary-only and provisional.",
            "Independent source-family confirmation is not available.",
            "Official BCTC review remains required for surviving candidates.",
            "Missing values were not filled.",
        ],
        "processed_ticker_count": int(summary.get("processed_ticker_count", 0)),
        "watchlist_candidate_count": int(summary.get("watchlist_candidate_count", 0)),
        "manual_bctc_review_queue_count": int(summary.get("manual_bctc_review_queue_count", 0)),
        "missing_field_counts": dict(sorted(missing_counts.items())),
        "crosscheck_status": summary.get("crosscheck_status", "NOT_AVAILABLE"),
        "market_source_confidence": summary.get("market_source_confidence", "PROVISIONAL_PRIMARY_ONLY"),
        "finance_source_confidence_default": summary.get("finance_source_confidence_default", "PROVISIONAL_LOW"),
    }


def build_run_manifest(
    *,
    config: dict[str, Any],
    config_path: Path,
    output_dir: Path,
    raw_cache_dir: Path,
    batch_dir: Path,
    command_used: str,
    requested_max_tickers: int,
    actual_universe_count: int,
    batch_size: int,
    allow_partial: bool,
    resume_from_cache: bool,
    core_outputs_modified: bool,
    universe_source: str,
    raw_universe_path: Path,
) -> dict[str, Any]:
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "commit_hash": _git_commit_hash(),
        "command_used": command_used,
        "config_path": str(config_path),
        "output_dir": str(output_dir),
        "raw_cache_dir": str(raw_cache_dir),
        "batch_dir": str(batch_dir),
        "requested_max_tickers": int(requested_max_tickers),
        "actual_universe_count": int(actual_universe_count),
        "batch_size": int(batch_size),
        "allow_partial": bool(allow_partial),
        "resume_from_cache": bool(resume_from_cache),
        "universe_source": universe_source,
        "raw_universe_path": str(raw_universe_path),
        "network_usage_if_known": "none",
        "core_outputs_modified": bool(core_outputs_modified),
        "previous_step_outputs_mutated": bool(core_outputs_modified),
    }


def write_step25_outputs(
    *,
    output_dir: Path,
    rows: pd.DataFrame,
    watchlist: pd.DataFrame,
    manual_queue: pd.DataFrame,
    blocked: pd.DataFrame,
    failed: pd.DataFrame,
    data_coverage: pd.DataFrame,
    evidence_debt: dict[str, Any],
    batch_manifest: pd.DataFrame,
    source_summary: pd.DataFrame,
    unresolved: pd.DataFrame,
    summary: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows.to_csv(output_dir / "full_universe_screening_rows.csv", index=False)
    watchlist.to_csv(output_dir / "watchlist_candidates.csv", index=False)
    manual_queue.to_csv(output_dir / "manual_bctc_review_queue.csv", index=False)
    blocked.to_csv(output_dir / "blocked_tickers.csv", index=False)
    failed.to_csv(output_dir / "failed_tickers.csv", index=False)
    data_coverage.to_csv(output_dir / "data_coverage_report.csv", index=False)
    batch_manifest.to_csv(output_dir / "batch_run_manifest.csv", index=False)
    source_summary.to_csv(output_dir / "source_confidence_summary.csv", index=False)
    unresolved.to_csv(output_dir / "unresolved_fields_report.csv", index=False)
    _write_json(output_dir / "full_universe_scale_summary.json", summary)
    _write_json(output_dir / "evidence_debt_report.json", evidence_debt)
    _write_json(output_dir / "run_manifest.json", manifest)


def scan_forbidden_terms(output_dir: Path, extra_dirs: list[Path] | None = None) -> list[str]:
    hits: list[str] = []
    dirs = [output_dir] + list(extra_dirs or [])
    for directory in dirs:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*")):
            if path.suffix.lower() not in {".csv", ".json", ".md", ".txt"}:
                continue
            text = _scan_text(path)
            for line_no, line in enumerate(text.splitlines(), start=1):
                lower = line.lower()
                for term in FORBIDDEN_TERMS:
                    if _term_in_text(term, lower):
                        hits.append(f"{path.name}:{line_no}:{term}")
    return hits


def _screening_status(market: dict[str, Any], finance: dict[str, Any], finance_missing: list[str], missing_market: list[str], filters: dict[str, Any]) -> tuple[str, list[str]]:
    block_reasons = []
    if missing_market or _as_bool(market.get("missing_market_flag")) or _as_bool(market.get("missing_price_flag")):
        block_reasons.append("Primary market data missing or incomplete.")
        return "BLOCKED_INSUFFICIENT_MARKET_DATA", block_reasons
    stale_days = _to_float(market.get("stale_days"))
    stale_limit = float(filters.get("stale_price_max_days", 10) or 10)
    if _as_bool(market.get("stale_price_flag")) or (stale_days is not None and stale_days > stale_limit):
        block_reasons.append("Primary market data is stale.")
        return "BLOCKED_STALE_MARKET_DATA", block_reasons
    recent_volume = _first_number(market, ["avg_volume_20d", "last_volume", "avg_volume_60d", "avg_volume_10d"])
    recent_value = _recent_trading_value(market)
    min_volume = float(filters.get("min_recent_volume", 1) or 1)
    min_value = float(filters.get("min_recent_trading_value", 1) or 1)
    if recent_volume is None or recent_volume < min_volume or recent_value == "" or float(recent_value) < min_value:
        block_reasons.append("Primary market liquidity is below the configured floor.")
        return "BLOCKED_TOO_ILLIQUID", block_reasons
    if _as_bool(filters.get("require_minimum_finance_presence", False)):
        present_count = len(FINANCE_FIELDS) - len(finance_missing)
        if not finance or present_count <= 0:
            block_reasons.append("Minimum provisional finance presence is missing.")
            return "BLOCKED_MISSING_MINIMUM_FINANCE", block_reasons
    return "WATCHLIST_CANDIDATE", block_reasons


def _missing_market_fields(row: dict[str, Any]) -> list[str]:
    required = ["last_close", "last_price_date", "avg_volume_20d"]
    return [field for field in required if field not in row or _is_missing(row.get(field))]


def _finance_missing_fields(finance_row: dict[str, Any], quality_row: dict[str, Any]) -> list[str]:
    declared = _split_fields(finance_row.get("missing_fields", ""))
    declared.extend(_split_fields(quality_row.get("missing_required_fields", "")))
    inferred = [field for field in FINANCE_FIELDS if field not in finance_row or _is_missing(finance_row.get(field))]
    return sorted(set(declared + inferred))


def _merged_market_row(row: dict[str, Any]) -> dict[str, Any]:
    merged = dict(row)
    if _is_missing(merged.get("avg_volume_20d")) and not _is_missing(merged.get("avg_volume_10d")):
        merged["avg_volume_20d"] = merged.get("avg_volume_10d")
    if _is_missing(merged.get("last_volume")) and not _is_missing(merged.get("avg_volume_20d")):
        merged["last_volume"] = merged.get("avg_volume_20d")
    return merged


def _prefer_market_row(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    ticker = str(incoming.get("ticker", existing.get("ticker", ""))).strip().upper()
    incoming = dict(incoming)
    incoming["ticker"] = ticker
    if not existing:
        return incoming
    existing_score = _market_row_score(existing)
    incoming_score = _market_row_score(incoming)
    if incoming_score >= existing_score:
        merged = dict(existing)
        for key, value in incoming.items():
            if not _is_missing(value):
                merged[key] = value
        return merged
    return existing


def _market_row_score(row: dict[str, Any]) -> int:
    score = 0
    for field in ["last_close", "last_price_date", "avg_volume_20d", "avg_volume_10d"]:
        if not _is_missing(row.get(field)):
            score += 1
    if str(row.get("fetch_status", "")).upper() == "FETCH_OK":
        score += 2
    return score


def _recent_trading_value(row: dict[str, Any]) -> float | str:
    existing = _to_float(row.get("recent_trading_value"))
    if existing is not None:
        return round(existing, 4)
    close = _to_float(row.get("last_close"))
    volume = _first_number(row, ["avg_volume_20d", "last_volume", "avg_volume_60d", "avg_volume_10d"])
    if close is None or volume is None:
        return ""
    return round(close * volume, 4)


def _first_number(row: dict[str, Any], columns: list[str]) -> float | None:
    for column in columns:
        value = _to_float(row.get(column))
        if value is not None:
            return value
    return None


def _coverage_metric(metric: str, value: Any, unit: str) -> dict[str, Any]:
    return {"metric": metric, "value": value, "unit": unit}


def _rows_with_missing_fields(rows: pd.DataFrame) -> int:
    if rows.empty or "missing_fields" not in rows.columns:
        return 0
    return int(rows["missing_fields"].astype(str).map(lambda value: len(_parse_json_list(value)) > 0).sum())


def _missing_field_observation_count(rows: pd.DataFrame) -> int:
    if rows.empty or "missing_fields" not in rows.columns:
        return 0
    return sum(len(_parse_json_list(value)) for value in rows["missing_fields"].astype(str))


def _non_missing_count(rows: pd.DataFrame, column: str) -> int:
    if rows.empty or column not in rows.columns:
        return 0
    return int(rows[column].map(lambda value: not _is_missing(value)).sum())


def _counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame.columns:
        return {}
    counts = frame[column].astype(str).value_counts().sort_index()
    return {key: int(value) for key, value in counts.items()}


def _index_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty or "ticker" not in frame.columns:
        return {}
    out = {}
    for _, row in frame.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        if ticker and ticker not in out:
            out[ticker] = row.to_dict()
    return out


def _source_family(source: Any) -> str:
    text = str(source).lower()
    if "vnstock" in text:
        return "vnstock"
    if "cafef" in text:
        return "cafef"
    if "legacy" in text:
        return "legacy_cache"
    if "config" in text:
        return "config"
    return "existing_artifact"


def _read_csv(path: Any) -> pd.DataFrame:
    if _is_missing(path):
        return pd.DataFrame()
    target = Path(str(path))
    if not target.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(target, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _json_list(values: list[Any]) -> str:
    return json.dumps([str(value) for value in values if not _is_missing(value)], ensure_ascii=False)


def _parse_json_list(value: Any) -> list[str]:
    if _is_missing(value):
        return []
    text = str(value).strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [str(item) for item in parsed if not _is_missing(item)]
        return []
    return [field.strip() for field in text.replace(";", ",").split(",") if field.strip()]


def _split_fields(value: Any) -> list[str]:
    return _parse_json_list(value)


def _first_non_missing(*values: Any) -> str:
    for value in values:
        if not _is_missing(value):
            return str(value)
    return ""


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _is_missing(value: Any) -> bool:
    return value is None or str(value).strip() == "" or str(value).strip().lower() in {"nan", "none", "null", "na"}


def _to_float(value: Any) -> float | None:
    if _is_missing(value):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _term_in_text(term: str, lower_text: str) -> bool:
    if " " in term or "-" in term:
        return term in lower_text
    return re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", lower_text) is not None


def _hashes(paths: list[Path]) -> dict[str, str]:
    return {str(path): _hash_file(path) for path in paths if path.exists()}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit_hash() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:  # noqa: BLE001
        return ""
    return completed.stdout.strip()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


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
    return json.dumps(data, ensure_ascii=False, indent=2)
