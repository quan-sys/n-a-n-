"""STEP21 L6 timing/liquidity context engine.

The engine only produces provisional context from existing market artifacts. It
does not fetch data, create price levels, or issue action labels.
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


STEP_ID = "STEP21-L6-TIMING-LIQUIDITY-CONTEXT"
MODE = "timing_liquidity_context_only"

TIMING_BUCKETS = {
    "TIMING_RISK_LOW",
    "TIMING_RISK_MODERATE",
    "TIMING_RISK_ELEVATED",
    "TIMING_RISK_HIGH",
    "TIMING_INSUFFICIENT_DATA",
    "TIMING_MANUAL_REVIEW",
}

ENTRY_TIMING_QUALITY_VALUES = {
    "IMPROVING_PRICE_ACTION",
    "NEUTRAL_PRICE_ACTION",
    "DETERIORATING_PRICE_ACTION",
    "VOLATILE_OR_UNCLEAR",
    "INSUFFICIENT_TECHNICAL_EVIDENCE",
    "MANUAL_REVIEW_REQUIRED",
}

LIQUIDITY_BUCKETS = {
    "LIQUIDITY_RISK_LOW",
    "LIQUIDITY_RISK_MODERATE",
    "LIQUIDITY_RISK_ELEVATED",
    "LIQUIDITY_RISK_HIGH",
    "LIQUIDITY_INSUFFICIENT_DATA",
    "LIQUIDITY_MANUAL_REVIEW",
}

LIQUIDITY_QUALITY_VALUES = {
    "LIQUIDITY_STRONG",
    "LIQUIDITY_ACCEPTABLE",
    "LIQUIDITY_THIN",
    "LIQUIDITY_WEAK",
    "LIQUIDITY_INSUFFICIENT_EVIDENCE",
}

FINAL_DECISIONS = {
    "PASS_TIMING_LIQUIDITY_CONTEXT_WITH_WARNINGS",
    "CONDITIONAL_GO_FOR_WEEKLY_REPORT",
    "BLOCKED_TIMING_LIQUIDITY_CONTEXT",
}

FORBIDDEN_FINAL_DECISIONS = {
    "PASS_FOR_INVESTMENT",
    "PASS_FOR_TRADE",
    "PASS_FOR_ENTRY",
    "PASS_FOR_RECOMMENDATION",
}

FORBIDDEN_TERMS = [
    "buy",
    "sell",
    "hold",
    "buy now",
    "sell now",
    "entry price",
    "exit price",
    "stoploss",
    "stop-loss",
    "take profit",
    "target price",
    "fair value",
    "intrinsic value",
    "margin of safety",
    "expected return",
    "upside",
    "downside",
    "recommended portfolio",
    "investment-ready",
]

ROW_COLUMNS = [
    "ticker",
    "market_source_confidence",
    "finance_source_confidence",
    "crosscheck_status",
    "verification_status",
    "timing_risk_score",
    "timing_risk_bucket",
    "entry_timing_quality",
    "price_action_context",
    "technical_warning_flags",
    "timing_confidence",
    "timing_manual_review_required",
    "liquidity_risk_score",
    "liquidity_risk_bucket",
    "liquidity_quality",
    "liquidity_warning_flags",
    "liquidity_confidence",
    "liquidity_manual_review_required",
    "manual_review_required",
    "manual_review_reason",
    "missing_fields",
    "evidence_debt_reason",
    "last_price_date",
    "last_close",
    "avg_volume_20d",
    "avg_volume_60d",
    "last_volume",
    "stale_days",
    "trading_days_60d",
    "recent_trading_value",
]

TIMING_WARNING_COLUMNS = ["ticker", "timing_risk_bucket", "technical_warning_flags", "timing_confidence", "timing_manual_review_required"]
LIQUIDITY_WARNING_COLUMNS = ["ticker", "liquidity_risk_bucket", "liquidity_warning_flags", "liquidity_confidence", "liquidity_manual_review_required"]
MANUAL_QUEUE_COLUMNS = ["ticker", "manual_review_reason", "missing_fields", "technical_warning_flags", "liquidity_warning_flags", "verification_status", "evidence_debt_reason"]


class Step21SafeRunBlocked(RuntimeError):
    """Raised when a requested Step21 run violates scope controls."""


@dataclass
class Step21Result:
    rows: pd.DataFrame
    timing_warning_flags: pd.DataFrame
    liquidity_warning_flags: pd.DataFrame
    manual_review_queue: pd.DataFrame
    evidence_debt: dict[str, Any]
    run_manifest: dict[str, Any]
    summary: dict[str, Any]


def load_step21_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("STEP21 config must be a mapping.")
    return data


def run_step21_l6_timing_liquidity_context(
    *,
    config_path: str | Path,
    output_dir: str | Path | None = None,
    limit: int | None = None,
    allow_partial: bool | None = None,
    request_full_universe: bool = False,
    command_used: str = "",
    core_output_paths: list[str | Path] | None = None,
) -> Step21Result:
    config = load_step21_config(config_path)
    validate_step21_config(config)
    output = Path(output_dir or ((config.get("exports") or {}).get("output_dir") or "data/reports/step21_l6_timing_liquidity_context"))
    output.mkdir(parents=True, exist_ok=True)
    limits = config.get("limits") or {}
    if request_full_universe and not _as_bool(limits.get("full_universe_allowed", False)):
        raise Step21SafeRunBlocked("Full-universe STEP21 run is blocked by config.")

    max_tickers = int(limits.get("max_tickers", 100) or 100)
    requested_limit = max_tickers if limit is None else int(limit)
    effective_limit = min(requested_limit, max_tickers)
    warnings = []
    if requested_limit > max_tickers:
        warnings.append(f"Requested limit {requested_limit} capped to configured max {max_tickers}.")
    run_policy = dict(config.get("run") or {})
    if allow_partial is not None:
        run_policy["allow_partial"] = bool(allow_partial)
    allow_partial_effective = _as_bool(run_policy.get("allow_partial", True))

    core_paths = [Path(path) for path in (core_output_paths or config.get("core_output_watchlist", []))]
    before_hashes = _hashes(core_paths)
    frames, resolved_inputs, missing_inputs = load_step21_inputs(config, allow_partial=allow_partial_effective)
    if missing_inputs and not allow_partial_effective:
        raise Step21SafeRunBlocked("STEP21 missing input while allow_partial=false: " + ",".join(missing_inputs))

    rows = build_step21_rows(
        config=config,
        step20_rows=frames.get("step20_rows", pd.DataFrame()),
        step05a_rows=frames.get("step05a_rows", pd.DataFrame()),
        market_snapshot=frames.get("market_snapshot", pd.DataFrame()),
        limit=effective_limit,
        missing_inputs=missing_inputs,
    )
    timing_flags = rows.reindex(columns=TIMING_WARNING_COLUMNS)
    liquidity_flags = rows.reindex(columns=LIQUIDITY_WARNING_COLUMNS)
    manual_queue = rows[rows["manual_review_required"].map(_as_bool)].reindex(columns=MANUAL_QUEUE_COLUMNS) if not rows.empty else pd.DataFrame(columns=MANUAL_QUEUE_COLUMNS)
    core_modified = before_hashes != _hashes(core_paths)

    write_step21_outputs(output, rows, timing_flags, liquidity_flags, manual_queue, {}, {}, {})
    forbidden_hits = scan_forbidden_terms(output)
    summary = build_summary(config=config, rows=rows, manual_queue=manual_queue, missing_inputs=missing_inputs, warnings=warnings, forbidden_hits=forbidden_hits, core_outputs_modified=core_modified)
    evidence_debt = build_evidence_debt(rows, summary, missing_inputs)
    manifest = build_run_manifest(
        config=config,
        config_path=Path(config_path),
        output_dir=output,
        effective_limit=effective_limit,
        allow_partial=allow_partial_effective,
        command_used=command_used,
        core_outputs_modified=core_modified,
        resolved_inputs=resolved_inputs,
        missing_inputs=missing_inputs,
    )
    write_step21_outputs(output, rows, timing_flags, liquidity_flags, manual_queue, summary, evidence_debt, manifest)
    forbidden_hits = scan_forbidden_terms(output)
    if forbidden_hits != summary["forbidden_terms_found"]:
        summary = build_summary(config=config, rows=rows, manual_queue=manual_queue, missing_inputs=missing_inputs, warnings=warnings, forbidden_hits=forbidden_hits, core_outputs_modified=core_modified)
        write_step21_outputs(output, rows, timing_flags, liquidity_flags, manual_queue, summary, evidence_debt, manifest)
    return Step21Result(rows, timing_flags, liquidity_flags, manual_queue, evidence_debt, manifest, summary)


def validate_step21_config(config: dict[str, Any]) -> None:
    if config.get("step_id") != STEP_ID:
        raise ValueError(f"STEP21 config step_id must be {STEP_ID}.")
    safety = config.get("safety") if isinstance(config.get("safety"), dict) else {}
    required = [
        "no_recommendation",
        "no_buy_sell_hold",
        "no_entry_exit_price",
        "no_stoploss_takeprofit",
        "no_target_price",
        "no_fair_value",
        "no_expected_return",
        "no_portfolio_recommendation",
        "no_pdf_ocr",
        "no_official_bctc_scrape",
        "no_zero_fill",
        "no_core_output_mutation",
        "no_stage_promotion_to_investment_ready",
    ]
    missing = [key for key in required if safety.get(key) is not True]
    if missing:
        raise ValueError(f"STEP21 safety flags must be true: {','.join(missing)}")


def load_step21_inputs(config: dict[str, Any], *, allow_partial: bool) -> tuple[dict[str, pd.DataFrame], dict[str, str], list[str]]:
    frames: dict[str, pd.DataFrame] = {}
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for logical_name, spec in (config.get("inputs") or {}).items():
        if logical_name.endswith("_summary"):
            path = _first_existing_path(spec)
            if path is None:
                missing.append(str(logical_name))
            else:
                resolved[str(logical_name)] = str(path)
            continue
        path = _first_existing_path(spec)
        if path is None:
            missing.append(str(logical_name))
            frames[str(logical_name)] = pd.DataFrame()
        else:
            resolved[str(logical_name)] = str(path)
            frames[str(logical_name)] = _read_csv(path)
    if missing and not allow_partial:
        return frames, resolved, missing
    return frames, resolved, missing


def build_step21_rows(
    *,
    config: dict[str, Any],
    step20_rows: pd.DataFrame,
    step05a_rows: pd.DataFrame,
    market_snapshot: pd.DataFrame,
    limit: int,
    missing_inputs: list[str],
) -> pd.DataFrame:
    confidence = config.get("source_confidence") or {}
    thresholds = config.get("thresholds") or {}
    tickers = _ticker_list(step20_rows) or _ticker_list(step05a_rows) or _ticker_list(market_snapshot)
    tickers = tickers[:limit]
    step20_by_ticker = _index_by_ticker(step20_rows)
    step05a_by_ticker = _index_by_ticker(step05a_rows)
    market_by_ticker = _index_by_ticker(market_snapshot)
    rows = []
    for ticker in tickers:
        step20 = step20_by_ticker.get(ticker, {})
        step05a = step05a_by_ticker.get(ticker, {})
        market = market_by_ticker.get(ticker, {})
        combined_market = _merge_market(step05a, market)
        missing_fields = _missing_market_fields(combined_market, missing_inputs)
        timing = _timing_context(combined_market, missing_fields, thresholds)
        liquidity = _liquidity_context(combined_market, missing_fields, thresholds)
        manual = timing["timing_manual_review_required"] or liquidity["liquidity_manual_review_required"] or _as_bool(step20.get("manual_review_required", True))
        manual_reason = _manual_review_reason(timing, liquidity, missing_fields, missing_inputs, step20)
        evidence_debt = [
            "Market context remains primary-only.",
            "No independent current market source-family confirmation.",
            "Timing and liquidity context are not trade instructions.",
        ]
        if missing_inputs:
            evidence_debt.append("Some configured inputs were unavailable.")
        rows.append(
            {
                "ticker": ticker,
                "market_source_confidence": confidence.get("market_source_confidence", "PROVISIONAL_PRIMARY_ONLY"),
                "finance_source_confidence": confidence.get("finance_source_confidence_default", "PROVISIONAL_LOW"),
                "crosscheck_status": confidence.get("crosscheck_status", "NOT_AVAILABLE"),
                "verification_status": confidence.get("verification_status", "NEEDS_MANUAL_BCTC_REVIEW"),
                **timing,
                **liquidity,
                "manual_review_required": bool(manual),
                "manual_review_reason": manual_reason,
                "missing_fields": _json_list(missing_fields),
                "evidence_debt_reason": _json_list(evidence_debt),
                "last_price_date": combined_market.get("last_price_date", ""),
                "last_close": combined_market.get("last_close", ""),
                "avg_volume_20d": combined_market.get("avg_volume_20d", ""),
                "avg_volume_60d": combined_market.get("avg_volume_60d", ""),
                "last_volume": combined_market.get("last_volume", ""),
                "stale_days": combined_market.get("stale_days", ""),
                "trading_days_60d": combined_market.get("trading_days_60d", ""),
                "recent_trading_value": _recent_trading_value(combined_market),
            }
        )
    return pd.DataFrame(rows, columns=ROW_COLUMNS)


def build_summary(
    *,
    config: dict[str, Any],
    rows: pd.DataFrame,
    manual_queue: pd.DataFrame,
    missing_inputs: list[str],
    warnings: list[str],
    forbidden_hits: list[str],
    core_outputs_modified: bool,
) -> dict[str, Any]:
    confidence = config.get("source_confidence") or {}
    timing_insufficient = int(rows["timing_risk_bucket"].eq("TIMING_INSUFFICIENT_DATA").sum()) if not rows.empty else 0
    liquidity_insufficient = int(rows["liquidity_risk_bucket"].eq("LIQUIDITY_INSUFFICIENT_DATA").sum()) if not rows.empty else 0
    if forbidden_hits or core_outputs_modified:
        final_decision = "BLOCKED_TIMING_LIQUIDITY_CONTEXT"
    elif rows.empty:
        final_decision = "BLOCKED_TIMING_LIQUIDITY_CONTEXT"
    elif timing_insufficient or liquidity_insufficient or len(manual_queue):
        final_decision = "PASS_TIMING_LIQUIDITY_CONTEXT_WITH_WARNINGS"
    else:
        final_decision = "CONDITIONAL_GO_FOR_WEEKLY_REPORT"
    if final_decision in FORBIDDEN_FINAL_DECISIONS:
        raise ValueError(f"Forbidden STEP21 final decision: {final_decision}")
    all_warnings = list(warnings)
    all_warnings.extend(
        [
            "Timing/liquidity context remains provisional.",
            "Market confidence remains primary-only.",
            "No trade action or price-level output was produced.",
        ]
    )
    if missing_inputs:
        all_warnings.append("Some configured inputs were unavailable.")
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "mode": MODE,
        "processed_ticker_count": int(len(rows)),
        "timing_insufficient_count": timing_insufficient,
        "liquidity_insufficient_count": liquidity_insufficient,
        "manual_review_count": int(len(manual_queue)),
        "market_source_confidence": confidence.get("market_source_confidence", "PROVISIONAL_PRIMARY_ONLY"),
        "finance_source_confidence_default": confidence.get("finance_source_confidence_default", "PROVISIONAL_LOW"),
        "crosscheck_status": confidence.get("crosscheck_status", "NOT_AVAILABLE"),
        "verification_status": confidence.get("verification_status", "NEEDS_MANUAL_BCTC_REVIEW"),
        "missing_input_files": missing_inputs,
        "timing_risk_bucket_counts": _counts(rows, "timing_risk_bucket"),
        "liquidity_risk_bucket_counts": _counts(rows, "liquidity_risk_bucket"),
        "final_decision": final_decision,
        "warnings": all_warnings,
        "forbidden_terms_found": forbidden_hits,
        "core_outputs_modified": bool(core_outputs_modified),
    }


def build_evidence_debt(rows: pd.DataFrame, summary: dict[str, Any], missing_inputs: list[str]) -> dict[str, Any]:
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "limitations": [
            "Only existing primary market artifacts were used.",
            "No independent current market source-family confirmation.",
            "No price level or trade action output was produced.",
            "Manual review remains required when evidence is incomplete.",
        ],
        "missing_input_files": missing_inputs,
        "processed_ticker_count": int(summary.get("processed_ticker_count", 0)),
        "timing_risk_bucket_counts": summary.get("timing_risk_bucket_counts", {}),
        "liquidity_risk_bucket_counts": summary.get("liquidity_risk_bucket_counts", {}),
        "manual_review_count": int(summary.get("manual_review_count", 0)),
    }


def build_run_manifest(
    *,
    config: dict[str, Any],
    config_path: Path,
    output_dir: Path,
    effective_limit: int,
    allow_partial: bool,
    command_used: str,
    core_outputs_modified: bool,
    resolved_inputs: dict[str, str],
    missing_inputs: list[str],
) -> dict[str, Any]:
    limits = config.get("limits") or {}
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "commit_hash": _git_commit_hash(),
        "command_used": command_used,
        "config_path": str(config_path),
        "output_dir": str(output_dir),
        "max_tickers": int(effective_limit),
        "allow_partial": bool(allow_partial),
        "full_universe_allowed": _as_bool(limits.get("full_universe_allowed", False)),
        "network_usage_if_known": "none",
        "core_outputs_modified": bool(core_outputs_modified),
        "previous_step_outputs_mutated": bool(core_outputs_modified),
        "resolved_inputs": resolved_inputs,
        "missing_input_files": missing_inputs,
    }


def write_step21_outputs(output_dir: Path, rows: pd.DataFrame, timing_flags: pd.DataFrame, liquidity_flags: pd.DataFrame, manual_queue: pd.DataFrame, summary: dict[str, Any], evidence_debt: dict[str, Any], manifest: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows.to_csv(output_dir / "timing_liquidity_context_rows.csv", index=False)
    timing_flags.to_csv(output_dir / "timing_warning_flags.csv", index=False)
    liquidity_flags.to_csv(output_dir / "liquidity_warning_flags.csv", index=False)
    manual_queue.to_csv(output_dir / "manual_review_queue.csv", index=False)
    _write_json(output_dir / "timing_liquidity_context_summary.json", summary)
    _write_json(output_dir / "evidence_debt_report.json", evidence_debt)
    _write_json(output_dir / "run_manifest.json", manifest)


def scan_forbidden_terms(output_dir: Path) -> list[str]:
    hits: list[str] = []
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


def _timing_context(market: dict[str, Any], missing_fields: list[str], thresholds: dict[str, Any]) -> dict[str, Any]:
    flags = ["PRIMARY_ONLY_MARKET_DATA", "NO_RICH_HISTORICAL_TECHNICAL_SERIES"]
    if any(field in missing_fields for field in ["last_close", "last_price_date"]):
        flags.append("MISSING_REQUIRED_MARKET_FIELD")
        return _timing_result(85, "TIMING_INSUFFICIENT_DATA", "INSUFFICIENT_TECHNICAL_EVIDENCE", "INSUFFICIENT_CURRENT_MARKET_EVIDENCE", flags, "INSUFFICIENT", True)
    stale_days = _to_float(market.get("stale_days"))
    stale_limit = float(thresholds.get("stale_price_max_days", 10) or 10)
    if stale_days is not None and stale_days > stale_limit:
        flags.append("STALE_PRICE_CONTEXT")
        return _timing_result(75, "TIMING_RISK_ELEVATED", "MANUAL_REVIEW_REQUIRED", "STALE_PRIMARY_PRICE_CONTEXT", flags, "LOW", True)
    abnormal_ratio = _abnormal_volume_ratio(market)
    if abnormal_ratio is not None and abnormal_ratio >= float(thresholds.get("abnormal_volume_warning_ratio", 2.0) or 2.0):
        flags.append("ABNORMAL_VOLUME_CONTEXT")
        return _timing_result(60, "TIMING_RISK_MODERATE", "VOLATILE_OR_UNCLEAR", "CURRENT_PRICE_CONTEXT_WITH_VOLUME_SPIKE", flags, "LOW", True)
    return _timing_result(45, "TIMING_RISK_MODERATE", "NEUTRAL_PRICE_ACTION", "CURRENT_PRICE_CONTEXT_ONLY", flags, "LOW", False)


def _liquidity_context(market: dict[str, Any], missing_fields: list[str], thresholds: dict[str, Any]) -> dict[str, Any]:
    flags = ["PRIMARY_ONLY_LIQUIDITY_DATA"]
    avg20 = _to_float(market.get("avg_volume_20d"))
    value = _recent_trading_value(market)
    min_volume = float(thresholds.get("min_avg_volume_20d", 1) or 1)
    min_value = float(thresholds.get("min_recent_trading_value", 1) or 1)
    if avg20 is None or value == "":
        flags.append("MISSING_LIQUIDITY_FIELD")
        return _liquidity_result(90, "LIQUIDITY_INSUFFICIENT_DATA", "LIQUIDITY_INSUFFICIENT_EVIDENCE", flags, "INSUFFICIENT", True)
    if avg20 < min_volume or float(value) < min_value:
        flags.append("LOW_RECENT_LIQUIDITY")
        return _liquidity_result(80, "LIQUIDITY_RISK_HIGH", "LIQUIDITY_WEAK", flags, "LOW", True)
    trading_days = _to_float(market.get("trading_days_60d"))
    if trading_days is not None and trading_days < 30:
        flags.append("LIMITED_RECENT_TRADING_DAYS")
        return _liquidity_result(65, "LIQUIDITY_RISK_ELEVATED", "LIQUIDITY_THIN", flags, "LOW", True)
    if avg20 >= 1_000_000 and float(value) >= 100_000_000:
        return _liquidity_result(25, "LIQUIDITY_RISK_LOW", "LIQUIDITY_STRONG", flags, "MEDIUM", False)
    return _liquidity_result(45, "LIQUIDITY_RISK_MODERATE", "LIQUIDITY_ACCEPTABLE", flags, "LOW", False)


def _timing_result(score: int, bucket: str, quality: str, context: str, flags: list[str], confidence: str, review: bool) -> dict[str, Any]:
    return {
        "timing_risk_score": int(score),
        "timing_risk_bucket": bucket,
        "entry_timing_quality": quality,
        "price_action_context": context,
        "technical_warning_flags": _json_list(sorted(set(flags))),
        "timing_confidence": confidence,
        "timing_manual_review_required": bool(review),
    }


def _liquidity_result(score: int, bucket: str, quality: str, flags: list[str], confidence: str, review: bool) -> dict[str, Any]:
    return {
        "liquidity_risk_score": int(score),
        "liquidity_risk_bucket": bucket,
        "liquidity_quality": quality,
        "liquidity_warning_flags": _json_list(sorted(set(flags))),
        "liquidity_confidence": confidence,
        "liquidity_manual_review_required": bool(review),
    }


def _manual_review_reason(timing: dict[str, Any], liquidity: dict[str, Any], missing_fields: list[str], missing_inputs: list[str], step20: dict[str, Any]) -> str:
    reasons = []
    if timing.get("timing_manual_review_required"):
        reasons.append("Timing context requires manual review.")
    if liquidity.get("liquidity_manual_review_required"):
        reasons.append("Liquidity context requires manual review.")
    if missing_fields:
        reasons.append("Required market fields are missing.")
    if missing_inputs:
        reasons.append("Some configured inputs are unavailable.")
    if _as_bool(step20.get("manual_review_required", False)):
        reasons.append("Prior L5 context requires manual review.")
    return " ".join(reasons) if reasons else "No additional timing/liquidity manual review triggered."


def _missing_market_fields(market: dict[str, Any], missing_inputs: list[str]) -> list[str]:
    required = ["last_close", "last_price_date", "avg_volume_20d"]
    missing = [field for field in required if field not in market or _is_missing(market.get(field))]
    for logical_name in missing_inputs:
        missing.append(f"input:{logical_name}")
    return sorted(set(missing))


def _merge_market(step05a: dict[str, Any], market: dict[str, Any]) -> dict[str, Any]:
    merged = dict(market)
    for key in ["last_price_date", "last_close", "avg_volume_20d", "avg_volume_60d", "last_volume", "stale_days", "trading_days_60d", "recent_trading_value"]:
        if _is_missing(merged.get(key)) and key in step05a:
            merged[key] = step05a.get(key)
    return merged


def _recent_trading_value(market: dict[str, Any]) -> float | str:
    existing = _to_float(market.get("recent_trading_value"))
    if existing is not None:
        return round(existing, 4)
    close = _to_float(market.get("last_close"))
    volume = _to_float(market.get("avg_volume_20d")) or _to_float(market.get("last_volume")) or _to_float(market.get("avg_volume_60d"))
    if close is None or volume is None:
        return ""
    return round(close * volume, 4)


def _abnormal_volume_ratio(market: dict[str, Any]) -> float | None:
    last_volume = _to_float(market.get("last_volume"))
    avg20 = _to_float(market.get("avg_volume_20d"))
    if last_volume is None or avg20 is None or avg20 == 0:
        return None
    return last_volume / avg20


def build_evidence_debt_report_alias() -> None:
    return None


def _counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame.columns:
        return {}
    counts = frame[column].astype(str).value_counts().sort_index()
    return {key: int(value) for key, value in counts.items()}


def _ticker_list(frame: pd.DataFrame) -> list[str]:
    frame = _frame(frame)
    if frame.empty or "ticker" not in frame.columns:
        return []
    return [ticker for ticker in frame["ticker"].astype(str).str.strip().str.upper().drop_duplicates().tolist() if ticker]


def _index_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    frame = _frame(frame)
    if frame.empty or "ticker" not in frame.columns:
        return {}
    out = {}
    for _, row in frame.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        if ticker and ticker not in out:
            out[ticker] = row.to_dict()
    return out


def _first_existing_path(spec: Any) -> Path | None:
    candidates = spec if isinstance(spec, list) else [spec]
    for candidate in candidates:
        path = Path(str(candidate))
        if path.exists():
            return path
    return None


def _read_csv(path: str | Path) -> pd.DataFrame:
    target = Path(path)
    if not target.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(target, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()


def _json_list(values: list[Any]) -> str:
    return json.dumps([str(value) for value in values if not _is_missing(value)], ensure_ascii=False)


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
