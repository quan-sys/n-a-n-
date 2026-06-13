"""STEP27 data coverage repair probe.

This step diagnoses why STEP26 marked many tickers as missing market data. It
does not change prior outputs, fill missing values, fetch finance data, or
produce trading guidance.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yaml

from src.ingestion.current_market_data_refresh import fetch_quote_history_vnstock, normalize_quote_history


STEP_ID = "STEP27-DATA-COVERAGE-REPAIR-PROBE"
MODE = "data_coverage_repair_probe"
RANDOM_SEED = 2701

FINAL_DECISIONS = {
    "PASS_REPAIR_NEEDED_PIPELINE_MISSED_DATA",
    "PASS_SOURCE_LIMITATION_NEEDS_ALTERNATIVE_DATA",
    "PASS_MIXED_REPAIR_AND_SOURCE_LIMITATION",
    "BLOCKED_MISSING_STEP26_INPUTS",
    "BLOCKED_FORBIDDEN_TERMS_FOUND",
    "BLOCKED_CORE_OUTPUT_MUTATION",
}

COVERAGE_ISSUE_CLASSES = {
    "FETCH_OK_PIPELINE_MISSED",
    "FETCH_OK_SCHEMA_NORMALIZATION_ISSUE",
    "FETCH_OK_CACHE_OR_SNAPSHOT_STALE",
    "FETCH_EMPTY_SOURCE_LIMITATION",
    "FETCH_ERROR_SOURCE_OR_TICKER_ISSUE",
    "FETCH_SKIPPED_INPUT_INVALID",
    "FETCH_BLOCKED_BY_CONFIG",
}

REPAIR_ACTIONS = {
    "REFRESH_MARKET_SNAPSHOT_FROM_VNSTOCK",
    "FIX_NORMALIZATION_SCHEMA_MAP",
    "INVALIDATE_STALE_CACHE_AND_RERUN_STEP25",
    "CHECK_TICKER_EXCHANGE_MAPPING",
    "SOURCE_LIMITATION_NEEDS_ALTERNATIVE_DATA",
    "MANUAL_REVIEW_TICKER_STATUS",
}

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
    "investment-ready",
]

CONFIDENCE_FIELDS = {
    "market_source_confidence": "PROVISIONAL_PRIMARY_ONLY",
    "finance_source_confidence": "PROVISIONAL_LOW",
    "crosscheck_status": "NOT_AVAILABLE",
    "verification_status": "NEEDS_MANUAL_BCTC_REVIEW",
}

PROBE_COLUMNS = [
    "ticker",
    "sample_group",
    "step26_status",
    "step26_block_reason",
    "step26_missing_fields",
    "fetch_attempted",
    "fetch_ok",
    "fetch_error_type",
    "fetch_error_message",
    "raw_row_count",
    "normalized_row_count",
    "last_available_date",
    "last_close_available",
    "last_volume_available",
    "normalized_required_fields_present",
    "fetch_duration_ms",
    "provider",
    "source",
    "market_source_confidence",
    "finance_source_confidence",
    "crosscheck_status",
    "verification_status",
    "coverage_issue_class",
    "recommended_repair_action",
    "notes",
]

RAW_OBSERVATION_COLUMNS = [
    "ticker",
    "sample_group",
    "provider",
    "source",
    "raw_columns",
    "raw_row_count",
    "first_date",
    "last_date",
    "sample_close_value_present_boolean",
    "sample_volume_value_present_boolean",
]

QUEUE_COLUMNS = [
    "ticker",
    "sample_group",
    "step26_status",
    "coverage_issue_class",
    "recommended_repair_action",
    "fetch_ok",
    "normalized_row_count",
    "last_available_date",
    "last_close_available",
    "last_volume_available",
    "step26_missing_fields",
    "notes",
]


class Step27SafeRunBlocked(RuntimeError):
    """Raised when STEP27 cannot proceed safely."""


@dataclass
class Step27InputResolution:
    step25_rows_path: Path | None
    step26_audit_rows_path: Path | None
    step26_blocked_rows_path: Path | None
    step26_shortlist_path: Path | None
    step26_manual_bctc_queue_path: Path | None
    missing_input_files: list[str]
    input_resolution_notes: list[dict[str, str]]


@dataclass
class Step27Result:
    summary: dict[str, Any]
    probe_rows: pd.DataFrame
    raw_observation_manifest: pd.DataFrame
    fetch_success_examples: pd.DataFrame
    fetch_failure_examples: pd.DataFrame
    repair_queue: pd.DataFrame
    source_limitation_queue: pd.DataFrame
    schema_bug_candidates: pd.DataFrame
    input_resolution_report: dict[str, Any]
    run_manifest: dict[str, Any]


ProbeFetcher = Callable[[str, datetime, datetime, dict[str, Any]], pd.DataFrame]


def load_step27_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("STEP27 config must be a mapping.")
    return data


def validate_step27_config(config: dict[str, Any]) -> None:
    if config.get("step_id") != STEP_ID:
        raise ValueError(f"STEP27 config step_id must be {STEP_ID}.")
    safety = config.get("safety") if isinstance(config.get("safety"), dict) else {}
    required = [
        "no_recommendation",
        "no_buy_sell_hold",
        "no_valuation",
        "no_target_price",
        "no_fair_value",
        "no_intrinsic_value",
        "no_margin_of_safety",
        "no_expected_return",
        "no_zero_fill",
        "no_missing_data_inference",
        "no_pdf_ocr",
        "no_official_bctc_scrape",
        "no_core_output_mutation",
        "no_stage_promotion_to_investment_ready",
    ]
    missing = [key for key in required if safety.get(key) is not True]
    if missing:
        raise ValueError(f"STEP27 safety flags must be true: {','.join(missing)}")
    policy = config.get("source_policy") if isinstance(config.get("source_policy"), dict) else {}
    if policy.get("provider") != "vnstock":
        raise ValueError("STEP27 only allows provider=vnstock.")
    allowed = policy.get("allowed_sources") or []
    market_source = str(policy.get("market_source", "VCI"))
    if market_source not in set(map(str, allowed)):
        raise ValueError("STEP27 market_source must be listed in allowed_sources.")
    if bool(policy.get("allow_fallback_sources", False)):
        raise ValueError("STEP27 does not allow fallback sources.")


def run_step27_data_coverage_repair_probe(
    *,
    config_path: str | Path,
    output_dir: str | Path | None = None,
    allow_partial: bool | None = None,
    command_used: str = "",
    fetcher: ProbeFetcher | None = None,
    core_output_paths: list[str | Path] | None = None,
    max_total_probe_tickers: int | None = None,
    max_requests: int | None = None,
) -> Step27Result:
    config = load_step27_config(config_path)
    validate_step27_config(config)
    run_policy = dict(config.get("run") or {})
    if allow_partial is not None:
        run_policy["allow_partial"] = bool(allow_partial)
    output = Path(output_dir or (config.get("exports") or {}).get("output_dir") or "data/reports/step27_data_coverage_repair_probe")
    output.mkdir(parents=True, exist_ok=True)

    resolution = resolve_step27_inputs(config)
    core_paths = [Path(path) for path in (core_output_paths or _core_paths_from_resolution(resolution))]
    before_hashes = _hashes(core_paths)
    step26_rows = _read_csv(resolution.step26_audit_rows_path)
    shortlist = _read_csv(resolution.step26_shortlist_path)
    if step26_rows.empty:
        result = _empty_blocked_result(
            config=config,
            config_path=Path(config_path),
            output_dir=output,
            resolution=resolution,
            command_used=command_used,
            final_decision="BLOCKED_MISSING_STEP26_INPUTS",
            core_outputs_modified=before_hashes != _hashes(core_paths),
        )
        write_outputs(output, result)
        return result

    limits = dict(config.get("limits") or {})
    if max_total_probe_tickers is not None:
        limits["max_total_probe_tickers"] = int(max_total_probe_tickers)
    if max_requests is not None:
        limits["max_requests"] = int(max_requests)
    samples = build_probe_sample(step26_rows, shortlist, limits)
    fetch_policy = _build_fetch_policy(config)
    fetcher = fetcher or fetch_quote_history_vnstock
    _configure_vnstock_subprocess_encoding()
    probe_rows, raw_manifest = probe_sample(
        samples=samples,
        config=config,
        fetch_policy=fetch_policy,
        fetcher=fetcher,
        allow_network=_as_bool(run_policy.get("allow_network", True)),
        max_requests=int(limits.get("max_requests", 200) or 200),
    )
    queues = build_queues(probe_rows)
    core_modified = before_hashes != _hashes(core_paths)
    summary = build_summary(
        config=config,
        resolution=resolution,
        samples=samples,
        probe_rows=probe_rows,
        queues=queues,
        forbidden_terms_found=[],
        core_outputs_modified=core_modified,
    )
    input_report = build_input_resolution_report(resolution)
    manifest = build_run_manifest(
        config_path=Path(config_path),
        output_dir=output,
        command_used=command_used,
        resolution=resolution,
        core_outputs_modified=core_modified,
    )
    result = Step27Result(
        summary=summary,
        probe_rows=probe_rows,
        raw_observation_manifest=raw_manifest,
        fetch_success_examples=probe_rows[probe_rows["fetch_ok"].map(_as_bool)].head(25).copy(),
        fetch_failure_examples=probe_rows[~probe_rows["fetch_ok"].map(_as_bool)].head(25).copy(),
        repair_queue=queues["repair_queue"],
        source_limitation_queue=queues["source_limitation_queue"],
        schema_bug_candidates=queues["schema_bug_candidates"],
        input_resolution_report=input_report,
        run_manifest=manifest,
    )
    write_outputs(output, result)
    forbidden_hits = scan_forbidden_terms(output)
    if forbidden_hits:
        result.summary = build_summary(
            config=config,
            resolution=resolution,
            samples=samples,
            probe_rows=probe_rows,
            queues=queues,
            forbidden_terms_found=forbidden_hits,
            core_outputs_modified=core_modified,
        )
        write_outputs(output, result)
    return result


def resolve_step27_inputs(config: dict[str, Any]) -> Step27InputResolution:
    inputs = config.get("inputs") if isinstance(config.get("inputs"), dict) else {}
    specs = {
        "step25_rows_path": (
            inputs.get("step25_rows"),
            [["step25", "full_universe", "screening_rows"], ["step25", "full_universe", "primary_only", "rows"]],
            ".csv",
        ),
        "step26_audit_rows_path": (
            inputs.get("step26_audit_rows"),
            [["step26", "normalized_universe_rows"], ["step26", "full_universe", "audit_rows"]],
            ".csv",
        ),
        "step26_blocked_rows_path": (
            inputs.get("step26_blocked_rows"),
            [["step26", "data_repair_priority_queue"], ["step26", "blocked_tickers"]],
            ".csv",
        ),
        "step26_shortlist_path": (
            inputs.get("step26_shortlist"),
            [["step26", "first_review_shortlist_50"]],
            ".csv",
        ),
        "step26_manual_bctc_queue_path": (
            inputs.get("step26_manual_bctc_queue"),
            [["step26", "manual_bctc_priority_queue_100"]],
            ".csv",
        ),
    }
    resolved: dict[str, Path | None] = {}
    missing: list[str] = []
    notes: list[dict[str, str]] = []
    for label, (configured, token_sets, suffix) in specs.items():
        path = _resolve_path(configured, token_sets, suffix)
        resolved[label] = path
        notes.append(
            {
                "input_name": label,
                "configured_path": str(configured or ""),
                "resolved_path": str(path or ""),
                "status": "FOUND" if path is not None else "MISSING",
            }
        )
        if path is None:
            missing.append(label)
    return Step27InputResolution(
        step25_rows_path=resolved["step25_rows_path"],
        step26_audit_rows_path=resolved["step26_audit_rows_path"],
        step26_blocked_rows_path=resolved["step26_blocked_rows_path"],
        step26_shortlist_path=resolved["step26_shortlist_path"],
        step26_manual_bctc_queue_path=resolved["step26_manual_bctc_queue_path"],
        missing_input_files=missing,
        input_resolution_notes=notes,
    )


def build_probe_sample(step26_rows: pd.DataFrame, shortlist: pd.DataFrame, limits: dict[str, Any]) -> pd.DataFrame:
    max_total = int(limits.get("max_total_probe_tickers", 166) or 166)
    blocked_limit = int(limits.get("sample_blocked_tickers", 100) or 100)
    control_limit = int(limits.get("sample_watchlist_control_tickers", 20) or 20)
    random_limit = int(limits.get("sample_random_universe_tickers", 50) or 50)
    rows = step26_rows.copy()
    rows["ticker"] = rows.get("ticker", pd.Series(dtype=str)).astype(str).str.upper().str.strip()
    row_by_ticker = {str(row["ticker"]): row for _, row in rows.drop_duplicates("ticker").iterrows() if str(row["ticker"]).strip()}
    records: list[dict[str, Any]] = []
    selected: set[str] = set()

    blocked = rows[rows.get("screening_status", "").astype(str).eq("BLOCKED_INSUFFICIENT_MARKET_DATA")].sort_values("ticker").head(blocked_limit)
    for _, row in blocked.iterrows():
        _append_sample(records, selected, row, "BLOCKED_SAMPLE", max_total)

    if not shortlist.empty and "ticker" in shortlist.columns:
        controls = shortlist.copy()
        controls["ticker"] = controls["ticker"].astype(str).str.upper().str.strip()
        controls = controls.sort_values("ticker").head(control_limit)
        for _, control in controls.iterrows():
            row = row_by_ticker.get(str(control["ticker"]), control)
            _append_sample(records, selected, row, "WATCHLIST_CONTROL", max_total)
    else:
        controls = rows[rows.get("screening_status", "").astype(str).eq("WATCHLIST_CANDIDATE")].sort_values("ticker").head(control_limit)
        for _, row in controls.iterrows():
            _append_sample(records, selected, row, "WATCHLIST_CONTROL", max_total)

    remaining_slots = max(0, min(random_limit, max_total - len(records)))
    if remaining_slots:
        universe = rows[~rows["ticker"].isin(selected)].sort_values("ticker")
        random_sample = universe.sample(n=min(remaining_slots, len(universe)), random_state=RANDOM_SEED) if not universe.empty else universe
        for _, row in random_sample.sort_values("ticker").iterrows():
            _append_sample(records, selected, row, "RANDOM_UNIVERSE_SAMPLE", max_total)
    return pd.DataFrame(records, columns=["ticker", "sample_group", "step26_status", "step26_block_reason", "step26_missing_fields"])


def probe_sample(
    *,
    samples: pd.DataFrame,
    config: dict[str, Any],
    fetch_policy: dict[str, Any],
    fetcher: ProbeFetcher,
    allow_network: bool,
    max_requests: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    source_policy = config.get("source_policy") or {}
    provider = str(source_policy.get("provider", "vnstock"))
    source = str(source_policy.get("market_source", "VCI"))
    history_policy = config.get("history_probe") or {}
    lookback_days = int(history_policy.get("lookback_days", 120) or 120)
    required_fields = [str(field) for field in history_policy.get("required_normalized_fields", ["ticker", "date", "close", "volume"])]
    run_date = datetime.now(UTC)
    start = run_date - timedelta(days=lookback_days)
    probe_records: list[dict[str, Any]] = []
    raw_records: list[dict[str, Any]] = []
    attempted = 0

    for _, sample in samples.iterrows():
        ticker = str(sample.get("ticker", "")).strip().upper()
        base = {
            "ticker": ticker,
            "sample_group": sample.get("sample_group", ""),
            "step26_status": sample.get("step26_status", ""),
            "step26_block_reason": sample.get("step26_block_reason", ""),
            "step26_missing_fields": sample.get("step26_missing_fields", ""),
            "provider": provider,
            "source": source,
            **CONFIDENCE_FIELDS,
        }
        if not ticker:
            record = _probe_record(base, False, False, "INPUT_INVALID", "ticker is blank", 0, 0, "", False, False, False, 0, "FETCH_SKIPPED_INPUT_INVALID", "MANUAL_REVIEW_TICKER_STATUS", "missing ticker")
            probe_records.append(record)
            raw_records.append(_raw_observation(base, pd.DataFrame()))
            continue
        if not allow_network or attempted >= max_requests:
            issue = "FETCH_BLOCKED_BY_CONFIG"
            action = "MANUAL_REVIEW_TICKER_STATUS"
            note = "network disabled or request limit reached"
            record = _probe_record(base, False, False, "FETCH_BLOCKED", note, 0, 0, "", False, False, False, 0, issue, action, note)
            probe_records.append(record)
            raw_records.append(_raw_observation(base, pd.DataFrame()))
            continue

        attempted += 1
        started = time.perf_counter()
        try:
            raw = _ensure_frame(fetcher(ticker, start, run_date, fetch_policy))
            duration_ms = int((time.perf_counter() - started) * 1000)
            normalized = normalize_quote_history(raw, ticker)
            normalized_required = _normalized_required_present(normalized, required_fields)
            last_date = _last_date(normalized)
            last_close_available = _last_value_available(normalized, "close")
            last_volume_available = _last_value_available(normalized, "volume")
            raw_rows = int(len(raw))
            normalized_rows = int(len(normalized))
            fetch_ok = bool(normalized_required and normalized_rows >= int(history_policy.get("min_rows_for_fetch_ok", 1) or 1))
            issue = classify_coverage_issue(
                sample=sample,
                raw=raw,
                normalized=normalized,
                fetch_ok=fetch_ok,
                normalized_required=normalized_required,
                fetch_error=False,
            )
            action = repair_action_for_issue(issue)
            note = issue_note(issue)
            record = _probe_record(base, True, fetch_ok, "", "", raw_rows, normalized_rows, last_date, last_close_available, last_volume_available, normalized_required, duration_ms, issue, action, note)
            probe_records.append(record)
            raw_records.append(_raw_observation(base, raw))
        except Exception as exc:  # noqa: BLE001 - diagnostics must log the error and continue
            duration_ms = int((time.perf_counter() - started) * 1000)
            error_type = exc.__class__.__name__
            error_message = _clean_error_message(str(exc))
            issue = "FETCH_ERROR_SOURCE_OR_TICKER_ISSUE"
            action = repair_action_for_issue(issue)
            record = _probe_record(base, True, False, error_type, error_message, 0, 0, "", False, False, False, duration_ms, issue, action, issue_note(issue))
            probe_records.append(record)
            raw_records.append(_raw_observation(base, pd.DataFrame()))

    return (
        pd.DataFrame(probe_records, columns=PROBE_COLUMNS),
        pd.DataFrame(raw_records, columns=RAW_OBSERVATION_COLUMNS),
    )


def classify_coverage_issue(
    *,
    sample: pd.Series,
    raw: pd.DataFrame,
    normalized: pd.DataFrame,
    fetch_ok: bool,
    normalized_required: bool,
    fetch_error: bool,
) -> str:
    if fetch_error:
        return "FETCH_ERROR_SOURCE_OR_TICKER_ISSUE"
    if raw.empty:
        return "FETCH_EMPTY_SOURCE_LIMITATION"
    if _raw_has_price_columns(raw) and not normalized_required:
        return "FETCH_OK_SCHEMA_NORMALIZATION_ISSUE"
    if fetch_ok:
        step_status = str(sample.get("step26_status", ""))
        if _step26_snapshot_stale(sample, normalized):
            return "FETCH_OK_CACHE_OR_SNAPSHOT_STALE"
        if step_status == "BLOCKED_INSUFFICIENT_MARKET_DATA":
            return "FETCH_OK_PIPELINE_MISSED"
    if not normalized.empty and not normalized_required:
        return "FETCH_OK_SCHEMA_NORMALIZATION_ISSUE"
    return "FETCH_EMPTY_SOURCE_LIMITATION"


def repair_action_for_issue(issue: str) -> str:
    mapping = {
        "FETCH_OK_PIPELINE_MISSED": "REFRESH_MARKET_SNAPSHOT_FROM_VNSTOCK",
        "FETCH_OK_SCHEMA_NORMALIZATION_ISSUE": "FIX_NORMALIZATION_SCHEMA_MAP",
        "FETCH_OK_CACHE_OR_SNAPSHOT_STALE": "INVALIDATE_STALE_CACHE_AND_RERUN_STEP25",
        "FETCH_EMPTY_SOURCE_LIMITATION": "SOURCE_LIMITATION_NEEDS_ALTERNATIVE_DATA",
        "FETCH_ERROR_SOURCE_OR_TICKER_ISSUE": "CHECK_TICKER_EXCHANGE_MAPPING",
        "FETCH_SKIPPED_INPUT_INVALID": "MANUAL_REVIEW_TICKER_STATUS",
        "FETCH_BLOCKED_BY_CONFIG": "MANUAL_REVIEW_TICKER_STATUS",
    }
    return mapping.get(issue, "MANUAL_REVIEW_TICKER_STATUS")


def issue_note(issue: str) -> str:
    notes = {
        "FETCH_OK_PIPELINE_MISSED": "Direct vnstock fetch returned required market fields for a ticker Step26 marked as missing.",
        "FETCH_OK_SCHEMA_NORMALIZATION_ISSUE": "Raw data had price-like columns but normalized required fields were incomplete.",
        "FETCH_OK_CACHE_OR_SNAPSHOT_STALE": "Direct vnstock fetch returned newer data than the prior snapshot row.",
        "FETCH_EMPTY_SOURCE_LIMITATION": "Direct vnstock fetch returned no rows.",
        "FETCH_ERROR_SOURCE_OR_TICKER_ISSUE": "Direct vnstock fetch raised an error.",
        "FETCH_SKIPPED_INPUT_INVALID": "Ticker input was blank or invalid.",
        "FETCH_BLOCKED_BY_CONFIG": "Fetch was not attempted due to run configuration.",
    }
    return notes.get(issue, "")


def build_queues(probe_rows: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if probe_rows.empty:
        empty = pd.DataFrame(columns=QUEUE_COLUMNS)
        return {"repair_queue": empty, "source_limitation_queue": empty, "schema_bug_candidates": empty}
    repair = probe_rows[probe_rows["coverage_issue_class"].isin(["FETCH_OK_PIPELINE_MISSED", "FETCH_OK_CACHE_OR_SNAPSHOT_STALE"])].copy()
    source_limit = probe_rows[probe_rows["coverage_issue_class"].eq("FETCH_EMPTY_SOURCE_LIMITATION")].copy()
    schema = probe_rows[probe_rows["coverage_issue_class"].eq("FETCH_OK_SCHEMA_NORMALIZATION_ISSUE")].copy()
    return {
        "repair_queue": repair.reindex(columns=QUEUE_COLUMNS),
        "source_limitation_queue": source_limit.reindex(columns=QUEUE_COLUMNS),
        "schema_bug_candidates": schema.reindex(columns=QUEUE_COLUMNS),
    }


def build_summary(
    *,
    config: dict[str, Any],
    resolution: Step27InputResolution,
    samples: pd.DataFrame,
    probe_rows: pd.DataFrame,
    queues: dict[str, pd.DataFrame],
    forbidden_terms_found: list[str],
    core_outputs_modified: bool,
) -> dict[str, Any]:
    if resolution.step26_audit_rows_path is None or samples.empty:
        final_decision = "BLOCKED_MISSING_STEP26_INPUTS"
    elif forbidden_terms_found:
        final_decision = "BLOCKED_FORBIDDEN_TERMS_FOUND"
    elif core_outputs_modified:
        final_decision = "BLOCKED_CORE_OUTPUT_MUTATION"
    else:
        repair_count = len(queues["repair_queue"])
        source_count = len(queues["source_limitation_queue"])
        if repair_count and source_count:
            final_decision = "PASS_MIXED_REPAIR_AND_SOURCE_LIMITATION"
        elif repair_count:
            final_decision = "PASS_REPAIR_NEEDED_PIPELINE_MISSED_DATA"
        else:
            final_decision = "PASS_SOURCE_LIMITATION_NEEDS_ALTERNATIVE_DATA"
    if final_decision not in FINAL_DECISIONS:
        raise ValueError(f"Invalid STEP27 final decision: {final_decision}")
    fetch_ok = probe_rows["fetch_ok"].map(_as_bool) if "fetch_ok" in probe_rows.columns else pd.Series(dtype=bool)
    issue_counts = probe_rows["coverage_issue_class"].value_counts().to_dict() if "coverage_issue_class" in probe_rows.columns else {}
    step26_blocked_fetchable = probe_rows[
        probe_rows.get("step26_status", pd.Series(dtype=str)).astype(str).eq("BLOCKED_INSUFFICIENT_MARKET_DATA") & fetch_ok
    ]
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "mode": MODE,
        "total_probe_tickers": int(len(probe_rows)),
        "blocked_sample_count": int(samples["sample_group"].eq("BLOCKED_SAMPLE").sum()) if not samples.empty else 0,
        "control_sample_count": int(samples["sample_group"].eq("WATCHLIST_CONTROL").sum()) if not samples.empty else 0,
        "random_sample_count": int(samples["sample_group"].eq("RANDOM_UNIVERSE_SAMPLE").sum()) if not samples.empty else 0,
        "direct_fetch_attempted_count": int(probe_rows["fetch_attempted"].map(_as_bool).sum()) if "fetch_attempted" in probe_rows.columns else 0,
        "direct_fetch_ok_count": int(fetch_ok.sum()) if not fetch_ok.empty else 0,
        "direct_fetch_empty_count": int(issue_counts.get("FETCH_EMPTY_SOURCE_LIMITATION", 0)),
        "direct_fetch_error_count": int(issue_counts.get("FETCH_ERROR_SOURCE_OR_TICKER_ISSUE", 0)),
        "fetch_ok_pipeline_missed_count": int(issue_counts.get("FETCH_OK_PIPELINE_MISSED", 0)),
        "schema_normalization_issue_count": int(issue_counts.get("FETCH_OK_SCHEMA_NORMALIZATION_ISSUE", 0)),
        "cache_or_snapshot_stale_count": int(issue_counts.get("FETCH_OK_CACHE_OR_SNAPSHOT_STALE", 0)),
        "source_limitation_count": int(issue_counts.get("FETCH_EMPTY_SOURCE_LIMITATION", 0)),
        "step26_blocked_fetchable_count": int(len(step26_blocked_fetchable)),
        "repair_queue_count": int(len(queues["repair_queue"])),
        "source_limitation_queue_count": int(len(queues["source_limitation_queue"])),
        "schema_bug_candidate_count": int(len(queues["schema_bug_candidates"])),
        "alternative_data_needed": bool(len(queues["source_limitation_queue"]) > len(queues["repair_queue"])),
        "market_source_confidence": (config.get("source_policy") or {}).get("market_source_confidence", CONFIDENCE_FIELDS["market_source_confidence"]),
        "finance_source_confidence": (config.get("source_policy") or {}).get("finance_source_confidence_default", CONFIDENCE_FIELDS["finance_source_confidence"]),
        "crosscheck_status": (config.get("source_policy") or {}).get("crosscheck_status", CONFIDENCE_FIELDS["crosscheck_status"]),
        "verification_status": (config.get("source_policy") or {}).get("verification_status", CONFIDENCE_FIELDS["verification_status"]),
        "missing_input_files": resolution.missing_input_files,
        "forbidden_terms_found": forbidden_terms_found,
        "core_outputs_modified": bool(core_outputs_modified),
        "final_decision": final_decision,
    }


def build_input_resolution_report(resolution: Step27InputResolution) -> dict[str, Any]:
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "missing_input_files": resolution.missing_input_files,
        "input_resolution_notes": resolution.input_resolution_notes,
        "resolved_paths": {
            "step25_rows_path": str(resolution.step25_rows_path or ""),
            "step26_audit_rows_path": str(resolution.step26_audit_rows_path or ""),
            "step26_blocked_rows_path": str(resolution.step26_blocked_rows_path or ""),
            "step26_shortlist_path": str(resolution.step26_shortlist_path or ""),
            "step26_manual_bctc_queue_path": str(resolution.step26_manual_bctc_queue_path or ""),
        },
    }


def build_run_manifest(
    *,
    config_path: Path,
    output_dir: Path,
    command_used: str,
    resolution: Step27InputResolution,
    core_outputs_modified: bool,
) -> dict[str, Any]:
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "commit_hash": _git_commit_hash(),
        "command_used": command_used,
        "config_path": str(config_path),
        "output_dir": str(output_dir),
        "network_usage_if_known": "vnstock_only",
        "core_outputs_modified": bool(core_outputs_modified),
        "previous_step_outputs_mutated": bool(core_outputs_modified),
        "input_resolution": build_input_resolution_report(resolution),
    }


def write_outputs(output_dir: Path, result: Step27Result) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "step27_coverage_probe_summary.json", result.summary)
    _write_json(output_dir / "step27_probe_summary.json", result.summary)
    result.probe_rows.to_csv(output_dir / "step27_probe_rows.csv", index=False)
    result.probe_rows.to_csv(output_dir / "direct_fetch_probe_results.csv", index=False)
    result.raw_observation_manifest.to_csv(output_dir / "raw_observation_manifest.csv", index=False)
    result.fetch_success_examples.to_csv(output_dir / "fetch_success_examples.csv", index=False)
    result.fetch_failure_examples.to_csv(output_dir / "fetch_failure_examples.csv", index=False)
    result.probe_rows[~result.probe_rows["fetch_ok"].map(_as_bool)].to_csv(output_dir / "fetch_failed_tickers.csv", index=False)
    result.repair_queue.to_csv(output_dir / "repair_queue.csv", index=False)
    result.repair_queue.to_csv(output_dir / "fetch_recovered_tickers.csv", index=False)
    result.source_limitation_queue.to_csv(output_dir / "source_limitation_queue.csv", index=False)
    result.schema_bug_candidates.to_csv(output_dir / "schema_bug_candidates.csv", index=False)
    _pipeline_gap_rows(result.probe_rows).to_csv(output_dir / "pipeline_vs_direct_fetch_gap.csv", index=False)
    _write_json(output_dir / "input_resolution_report.json", result.input_resolution_report)
    _write_json(output_dir / "run_manifest.json", result.run_manifest)


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


def _pipeline_gap_rows(probe_rows: pd.DataFrame) -> pd.DataFrame:
    if probe_rows.empty or "coverage_issue_class" not in probe_rows.columns:
        return pd.DataFrame(columns=PROBE_COLUMNS)
    gap_classes = {
        "FETCH_OK_PIPELINE_MISSED",
        "FETCH_OK_SCHEMA_NORMALIZATION_ISSUE",
        "FETCH_OK_CACHE_OR_SNAPSHOT_STALE",
        "FETCH_EMPTY_SOURCE_LIMITATION",
        "FETCH_ERROR_SOURCE_OR_TICKER_ISSUE",
    }
    return probe_rows[probe_rows["coverage_issue_class"].isin(gap_classes)].copy()


def _empty_blocked_result(
    *,
    config: dict[str, Any],
    config_path: Path,
    output_dir: Path,
    resolution: Step27InputResolution,
    command_used: str,
    final_decision: str,
    core_outputs_modified: bool,
) -> Step27Result:
    empty_probe = pd.DataFrame(columns=PROBE_COLUMNS)
    empty_raw = pd.DataFrame(columns=RAW_OBSERVATION_COLUMNS)
    queues = build_queues(empty_probe)
    empty_samples = pd.DataFrame(columns=["ticker", "sample_group", "step26_status", "step26_block_reason", "step26_missing_fields"])
    summary = build_summary(
        config=config,
        resolution=resolution,
        samples=empty_samples,
        probe_rows=empty_probe,
        queues=queues,
        forbidden_terms_found=[],
        core_outputs_modified=core_outputs_modified,
    )
    summary["final_decision"] = final_decision
    input_report = build_input_resolution_report(resolution)
    manifest = build_run_manifest(
        config_path=config_path,
        output_dir=output_dir,
        command_used=command_used,
        resolution=resolution,
        core_outputs_modified=core_outputs_modified,
    )
    return Step27Result(
        summary=summary,
        probe_rows=empty_probe,
        raw_observation_manifest=empty_raw,
        fetch_success_examples=empty_probe.copy(),
        fetch_failure_examples=empty_probe.copy(),
        repair_queue=queues["repair_queue"],
        source_limitation_queue=queues["source_limitation_queue"],
        schema_bug_candidates=queues["schema_bug_candidates"],
        input_resolution_report=input_report,
        run_manifest=manifest,
    )


def _append_sample(records: list[dict[str, Any]], selected: set[str], row: pd.Series, sample_group: str, max_total: int) -> None:
    if len(records) >= max_total:
        return
    ticker = str(row.get("ticker", "")).upper().strip()
    if not ticker or ticker in selected:
        return
    selected.add(ticker)
    records.append(
        {
            "ticker": ticker,
            "sample_group": sample_group,
            "step26_status": row.get("screening_status", row.get("step26_status", "")),
            "step26_block_reason": _first_listish_value(row.get("block_reasons", row.get("reason_to_review", ""))) or str(row.get("reason_to_review", "")),
            "step26_missing_fields": _json_list(parse_listish(row.get("missing_fields", ""))),
        }
    )


def _probe_record(
    base: dict[str, Any],
    fetch_attempted: bool,
    fetch_ok: bool,
    error_type: str,
    error_message: str,
    raw_rows: int,
    normalized_rows: int,
    last_date: str,
    last_close_available: bool,
    last_volume_available: bool,
    normalized_required: bool,
    duration_ms: int,
    issue: str,
    action: str,
    notes: str,
) -> dict[str, Any]:
    if issue not in COVERAGE_ISSUE_CLASSES:
        issue = "FETCH_ERROR_SOURCE_OR_TICKER_ISSUE"
    if action not in REPAIR_ACTIONS:
        action = "MANUAL_REVIEW_TICKER_STATUS"
    return {
        **base,
        "fetch_attempted": bool(fetch_attempted),
        "fetch_ok": bool(fetch_ok),
        "fetch_error_type": error_type,
        "fetch_error_message": error_message,
        "raw_row_count": int(raw_rows),
        "normalized_row_count": int(normalized_rows),
        "last_available_date": last_date,
        "last_close_available": bool(last_close_available),
        "last_volume_available": bool(last_volume_available),
        "normalized_required_fields_present": bool(normalized_required),
        "fetch_duration_ms": int(duration_ms),
        "coverage_issue_class": issue,
        "recommended_repair_action": action,
        "notes": notes,
    }


def _raw_observation(base: dict[str, Any], raw: pd.DataFrame) -> dict[str, Any]:
    frame = raw.copy() if isinstance(raw, pd.DataFrame) else pd.DataFrame()
    date_col = _first_column(frame, ["time", "date", "trading_date", "tradingDate"])
    close_col = _first_column(frame, ["close", "adjusted_close", "adj_close", "close_price", "price", "last_price"])
    volume_col = _first_column(frame, ["volume", "vol", "match_volume", "matching_volume", "qty"])
    dates = pd.to_datetime(frame[date_col], errors="coerce").dropna() if date_col else pd.Series(dtype="datetime64[ns]")
    return {
        "ticker": base.get("ticker", ""),
        "sample_group": base.get("sample_group", ""),
        "provider": base.get("provider", ""),
        "source": base.get("source", ""),
        "raw_columns": _json_list(list(frame.columns)),
        "raw_row_count": int(len(frame)),
        "first_date": dates.min().date().isoformat() if not dates.empty else "",
        "last_date": dates.max().date().isoformat() if not dates.empty else "",
        "sample_close_value_present_boolean": bool(close_col and not pd.to_numeric(frame[close_col], errors="coerce").dropna().empty),
        "sample_volume_value_present_boolean": bool(volume_col and not pd.to_numeric(frame[volume_col], errors="coerce").dropna().empty),
    }


def _build_fetch_policy(config: dict[str, Any]) -> dict[str, Any]:
    source_policy = config.get("source_policy") or {}
    history = config.get("history_probe") or {}
    return {
        "market_refresh": {
            "source_name": "vnstock_quote_vci_history",
            "quote_source": source_policy.get("market_source", "VCI"),
            "lookback_calendar_days": int(history.get("lookback_days", 120) or 120),
        }
    }


def _configure_vnstock_subprocess_encoding() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")


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


def _core_paths_from_resolution(resolution: Step27InputResolution) -> list[Path]:
    return [
        path
        for path in [
            resolution.step25_rows_path,
            resolution.step26_audit_rows_path,
            resolution.step26_blocked_rows_path,
            resolution.step26_shortlist_path,
            resolution.step26_manual_bctc_queue_path,
        ]
        if path is not None
    ]


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


def _first_listish_value(value: Any) -> str:
    parsed = parse_listish(value)
    return parsed[0] if parsed else ""


def _ensure_frame(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    if value is None:
        return pd.DataFrame()
    try:
        return pd.DataFrame(value)
    except Exception:
        return pd.DataFrame()


def _normalized_required_present(frame: pd.DataFrame, required_fields: list[str]) -> bool:
    if frame.empty:
        return False
    if not set(required_fields).issubset(set(map(str, frame.columns))):
        return False
    if pd.to_datetime(frame["date"], errors="coerce").dropna().empty:
        return False
    if pd.to_numeric(frame["close"], errors="coerce").dropna().empty:
        return False
    if "volume" in required_fields and pd.to_numeric(frame["volume"], errors="coerce").dropna().empty:
        return False
    return True


def _last_date(frame: pd.DataFrame) -> str:
    if frame.empty or "date" not in frame.columns:
        return ""
    dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
    return dates.max().date().isoformat() if not dates.empty else ""


def _last_value_available(frame: pd.DataFrame, column: str) -> bool:
    if frame.empty or column not in frame.columns:
        return False
    return not pd.to_numeric(frame[column], errors="coerce").dropna().empty


def _raw_has_price_columns(frame: pd.DataFrame) -> bool:
    if frame.empty:
        return False
    lowered = {str(column).strip().lower() for column in frame.columns}
    price_like = {"close", "adjusted_close", "adj_close", "close_price", "price", "last_price"}
    date_like = {"time", "date", "trading_date", "tradingdate"}
    return bool(lowered & price_like) and bool(lowered & date_like)


def _step26_snapshot_stale(sample: pd.Series, normalized: pd.DataFrame) -> bool:
    prior = pd.to_datetime(sample.get("last_price_date", ""), errors="coerce")
    if pd.isna(prior):
        return False
    latest = pd.to_datetime(_last_date(normalized), errors="coerce")
    if pd.isna(latest):
        return False
    return latest.date() > prior.date()


def _first_column(frame: pd.DataFrame, candidates: list[str]) -> str:
    lowered = {str(column).strip().lower(): str(column) for column in frame.columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return ""


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _is_missing(value: Any) -> bool:
    return value is None or str(value).strip() == "" or str(value).strip().lower() in {"nan", "none", "null", "na"}


def _json_list(values: list[Any]) -> str:
    return json.dumps([str(value) for value in values if not _is_missing(value)], ensure_ascii=False)


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


def _term_in_text(term: str, lower_text: str) -> bool:
    if " " in term or "-" in term:
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
    return json.dumps(data, ensure_ascii=False, indent=2)
