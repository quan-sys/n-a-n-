"""STEP22 L7 weekly report and manual review engine.

This module only turns existing provisional artifacts into a human review pack.
It does not fetch data, verify official filings, produce price levels, or issue
trade action labels.
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


STEP_ID = "STEP22-L7-WEEKLY-REPORT-MANUAL-REVIEW"
MODE = "weekly_report_manual_review_only"
SAFETY_NOTICE = (
    "This report is not investment advice. It contains provisional screening evidence only. "
    "Manual BCTC and source verification are required before deeper analysis."
)

WATCHLIST_STATUSES = {
    "HIGH_CONFIDENCE_WATCHLIST",
    "MEDIUM_CONFIDENCE_WATCHLIST",
    "WATCH_ONLY",
    "MANUAL_REVIEW",
    "REJECTED",
    "INSUFFICIENT_DATA",
}

WATCHLIST_CANDIDATE_STATUSES = {
    "HIGH_CONFIDENCE_WATCHLIST",
    "MEDIUM_CONFIDENCE_WATCHLIST",
    "WATCH_ONLY",
}

FINAL_DECISIONS = {
    "PASS_WEEKLY_REPORT_WITH_WARNINGS",
    "CONDITIONAL_GO_FOR_MONITORING_MODULE",
    "BLOCKED_WEEKLY_REPORT",
}

FORBIDDEN_TERMS = [
    "buy",
    "sell",
    "hold",
    "buy now",
    "sell now",
    "strong buy",
    "strong sell",
    "target price",
    "fair value",
    "intrinsic value",
    "margin of safety",
    "expected return",
    "entry price",
    "exit price",
    "stoploss",
    "stop-loss",
    "take profit",
    "recommended portfolio",
    "allocation",
]

ROW_COLUMNS = [
    "ticker",
    "company_name",
    "micro_sector",
    "archetype",
    "cycle_status",
    "survival_status",
    "peer_rank",
    "valuation_context",
    "timing_liquidity_status",
    "key_evidence",
    "key_risks",
    "missing_fields",
    "source_conflicts",
    "confidence_score",
    "watchlist_status",
    "manual_review_required",
    "market_source_confidence",
    "finance_source_confidence",
    "crosscheck_status",
    "verification_status",
    "evidence_debt_reason",
]

MANUAL_QUEUE_COLUMNS = [
    "ticker",
    "company_name",
    "watchlist_status",
    "manual_review_reason",
    "missing_fields",
    "source_conflicts",
    "market_source_confidence",
    "finance_source_confidence",
    "crosscheck_status",
    "verification_status",
    "evidence_debt_reason",
]

REJECT_LOG_COLUMNS = [
    "ticker",
    "company_name",
    "watchlist_status",
    "reject_reason",
    "evidence_fields",
    "confidence_score",
    "market_source_confidence",
    "finance_source_confidence",
    "verification_status",
]

SUMMARY_COLUMNS = ["metric", "value"]

SECTOR_COLUMNS = [
    "micro_sector",
    "ticker_count",
    "cycle_status",
    "top_improving_count",
    "distressed_without_recovery_count",
    "overheating_count",
    "structural_warning_count",
    "anomaly_alert_count",
    "data_quality_warning_count",
    "confidence_status",
]

COMPANY_ENGINE_COLUMNS = [
    "ticker",
    "company_name",
    "survival_status",
    "peer_rank",
    "step20_status",
    "valuation_context",
    "confidence_score",
    "manual_review_required",
    "watchlist_status",
]

RISK_WARNING_COLUMNS = ["warning_flag", "affected_ticker_count", "affected_tickers"]
SOURCE_CONFLICT_COLUMNS = ["ticker", "crosscheck_status", "source_conflict_status", "source_conflicts", "resolution_status"]
UNRESOLVED_COLUMNS = ["ticker", "field_name", "status", "reason", "source_layer"]


class Step22SafeRunBlocked(RuntimeError):
    """Raised when a requested Step22 run violates scope controls."""


@dataclass
class Step22Result:
    rows: pd.DataFrame
    manual_review_queue: pd.DataFrame
    reject_log: pd.DataFrame
    evidence_summary: pd.DataFrame
    data_quality_summary: pd.DataFrame
    sector_cycle_summary: pd.DataFrame
    company_engine_summary: pd.DataFrame
    risk_warning_summary: pd.DataFrame
    source_conflict_report: pd.DataFrame
    unresolved_fields_report: pd.DataFrame
    evidence_debt: dict[str, Any]
    run_manifest: dict[str, Any]
    summary: dict[str, Any]


def load_step22_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("STEP22 config must be a mapping.")
    return data


def run_step22_l7_weekly_report_manual_review(
    *,
    config_path: str | Path,
    output_dir: str | Path | None = None,
    limit: int | None = None,
    allow_partial: bool | None = None,
    request_full_universe: bool = False,
    command_used: str = "",
    core_output_paths: list[str | Path] | None = None,
) -> Step22Result:
    config = load_step22_config(config_path)
    validate_step22_config(config)
    output = Path(output_dir or ((config.get("exports") or {}).get("output_dir") or "data/reports/step22_l7_weekly_report_manual_review"))
    output.mkdir(parents=True, exist_ok=True)

    limits = config.get("limits") or {}
    if request_full_universe and not _as_bool(limits.get("full_universe_allowed", False)):
        raise Step22SafeRunBlocked("Full-universe STEP22 run is blocked by config.")
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
    frames, resolved_inputs, missing_inputs = load_step22_inputs(config, allow_partial=allow_partial_effective)
    if missing_inputs and not allow_partial_effective:
        raise Step22SafeRunBlocked("STEP22 missing input while allow_partial=false: " + ",".join(missing_inputs))

    rows = build_watchlist_rows(config=config, frames=frames, limit=effective_limit, missing_inputs=missing_inputs)
    manual_queue = build_manual_review_queue(rows)
    reject_log = build_reject_log(rows)
    evidence_summary = build_evidence_summary(rows)
    data_quality_summary = build_data_quality_summary(rows, missing_inputs)
    sector_summary = build_sector_cycle_summary(rows)
    company_summary = build_company_engine_summary(rows, frames.get("step20_rows", pd.DataFrame()))
    risk_summary = build_risk_warning_summary(rows)
    source_conflicts = build_source_conflict_report(rows)
    unresolved = build_unresolved_fields_report(rows)
    core_modified = before_hashes != _hashes(core_paths)
    summary = build_summary(
        config=config,
        rows=rows,
        manual_queue=manual_queue,
        reject_log=reject_log,
        missing_inputs=missing_inputs,
        warnings=warnings,
        forbidden_hits=[],
        core_outputs_modified=core_modified,
    )
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

    write_step22_outputs(
        output_dir=output,
        rows=rows,
        manual_queue=manual_queue,
        reject_log=reject_log,
        evidence_summary=evidence_summary,
        data_quality_summary=data_quality_summary,
        sector_summary=sector_summary,
        company_summary=company_summary,
        risk_summary=risk_summary,
        source_conflicts=source_conflicts,
        unresolved=unresolved,
        summary=summary,
        evidence_debt=evidence_debt,
        manifest=manifest,
    )
    forbidden_hits = scan_forbidden_terms(output)
    if forbidden_hits:
        summary = build_summary(
            config=config,
            rows=rows,
            manual_queue=manual_queue,
            reject_log=reject_log,
            missing_inputs=missing_inputs,
            warnings=warnings,
            forbidden_hits=forbidden_hits,
            core_outputs_modified=core_modified,
        )
        evidence_debt = build_evidence_debt(rows, summary, missing_inputs)
        write_step22_outputs(
            output_dir=output,
            rows=rows,
            manual_queue=manual_queue,
            reject_log=reject_log,
            evidence_summary=evidence_summary,
            data_quality_summary=data_quality_summary,
            sector_summary=sector_summary,
            company_summary=company_summary,
            risk_summary=risk_summary,
            source_conflicts=source_conflicts,
            unresolved=unresolved,
            summary=summary,
            evidence_debt=evidence_debt,
            manifest=manifest,
        )
    return Step22Result(
        rows=rows,
        manual_review_queue=manual_queue,
        reject_log=reject_log,
        evidence_summary=evidence_summary,
        data_quality_summary=data_quality_summary,
        sector_cycle_summary=sector_summary,
        company_engine_summary=company_summary,
        risk_warning_summary=risk_summary,
        source_conflict_report=source_conflicts,
        unresolved_fields_report=unresolved,
        evidence_debt=evidence_debt,
        run_manifest=manifest,
        summary=summary,
    )


def validate_step22_config(config: dict[str, Any]) -> None:
    if config.get("step_id") != STEP_ID:
        raise ValueError(f"STEP22 config step_id must be {STEP_ID}.")
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
        "no_stoploss_takeprofit",
        "no_portfolio_recommendation",
        "no_pdf_ocr",
        "no_official_bctc_scrape",
        "no_zero_fill",
        "no_core_output_mutation",
        "no_stage_promotion_to_investment_ready",
    ]
    missing = [key for key in required if safety.get(key) is not True]
    if missing:
        raise ValueError(f"STEP22 safety flags must be true: {','.join(missing)}")


def load_step22_inputs(config: dict[str, Any], *, allow_partial: bool) -> tuple[dict[str, pd.DataFrame], dict[str, str], list[str]]:
    frames: dict[str, pd.DataFrame] = {}
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for logical_name, spec in (config.get("inputs") or {}).items():
        path = _first_existing_path(spec)
        if path is None:
            missing.append(f"{logical_name}:{_spec_text(spec)}")
            frames[str(logical_name)] = pd.DataFrame()
        else:
            resolved[str(logical_name)] = str(path)
            frames[str(logical_name)] = _read_csv(path)
    if missing and not allow_partial:
        return frames, resolved, missing
    return frames, resolved, missing


def build_watchlist_rows(*, config: dict[str, Any], frames: dict[str, pd.DataFrame], limit: int, missing_inputs: list[str]) -> pd.DataFrame:
    confidence = config.get("source_confidence") or {}
    step21_by_ticker = _index_by_ticker(frames.get("step21_rows", pd.DataFrame()))
    step20_by_ticker = _index_by_ticker(frames.get("step20_rows", pd.DataFrame()))
    step19_by_ticker = _index_by_ticker(frames.get("step19_rows", pd.DataFrame()))
    step05a_by_ticker = _index_by_ticker(frames.get("step05a_rows", pd.DataFrame()))
    quality_by_ticker = _index_by_ticker(frames.get("provisional_data_quality_flags", pd.DataFrame()))
    market_by_ticker = _index_by_ticker(frames.get("market_snapshot", pd.DataFrame()))
    tickers = _combined_tickers(
        frames.get("step21_rows", pd.DataFrame()),
        frames.get("step20_rows", pd.DataFrame()),
        frames.get("step05a_rows", pd.DataFrame()),
        frames.get("market_snapshot", pd.DataFrame()),
    )[:limit]
    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        step21 = step21_by_ticker.get(ticker, {})
        step20 = step20_by_ticker.get(ticker, {})
        step19 = step19_by_ticker.get(ticker, {})
        step05a = step05a_by_ticker.get(ticker, {})
        quality = quality_by_ticker.get(ticker, {})
        market = market_by_ticker.get(ticker, {})
        missing_fields = _merged_missing_fields(step21, step20, step19, step05a, quality, missing_inputs)
        source_conflicts = _parse_json_list(step20.get("source_conflicts", ""))
        key_evidence = _key_evidence(step05a, step19, step20, step21)
        key_risks = _key_risks(step20, step21, step19, step05a, missing_fields, source_conflicts)
        score = _confidence_score(step05a, step19, step20, step21, missing_fields, source_conflicts, confidence)
        status = _watchlist_status(step05a, step19, step20, step21, missing_fields, source_conflicts, score)
        manual_review = _manual_review_required(status, confidence, step05a, step20, step21, source_conflicts)
        row = {
            "ticker": ticker,
            "company_name": _first_non_missing(step20.get("company_name"), market.get("company_name"), "UNKNOWN"),
            "micro_sector": _first_non_missing(step20.get("primary_micro_sector"), step20.get("primary_sector"), "UNKNOWN"),
            "archetype": _first_non_missing(step20.get("archetype"), "UNKNOWN"),
            "cycle_status": _cycle_status(step20),
            "survival_status": _first_non_missing(step19.get("shadow_status"), "UNKNOWN"),
            "peer_rank": _peer_rank(step20),
            "valuation_context": _first_non_missing(step20.get("valuation_context"), "INSUFFICIENT_DATA"),
            "timing_liquidity_status": _timing_liquidity_status(step21),
            "key_evidence": _json_list(key_evidence),
            "key_risks": _json_list(key_risks),
            "missing_fields": _json_list(missing_fields),
            "source_conflicts": _json_list(source_conflicts),
            "confidence_score": int(score),
            "watchlist_status": status,
            "manual_review_required": bool(manual_review),
            "market_source_confidence": confidence.get("market_source_confidence", "PROVISIONAL_PRIMARY_ONLY"),
            "finance_source_confidence": confidence.get("finance_source_confidence_default", "PROVISIONAL_LOW"),
            "crosscheck_status": confidence.get("crosscheck_status", "NOT_AVAILABLE"),
            "verification_status": confidence.get("verification_status", "NEEDS_MANUAL_BCTC_REVIEW"),
            "evidence_debt_reason": _json_list(_evidence_debt_reasons(missing_fields, source_conflicts, missing_inputs)),
        }
        rows.append(row)
    return pd.DataFrame(rows, columns=ROW_COLUMNS)


def build_manual_review_queue(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=MANUAL_QUEUE_COLUMNS)
    manual = rows[rows["manual_review_required"].map(_as_bool)].copy()
    manual["manual_review_reason"] = manual.apply(_manual_review_reason, axis=1)
    return manual.reindex(columns=MANUAL_QUEUE_COLUMNS)


def build_reject_log(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=REJECT_LOG_COLUMNS)
    rejected = rows[rows["watchlist_status"].eq("REJECTED")].copy()
    if rejected.empty:
        return pd.DataFrame(columns=REJECT_LOG_COLUMNS)
    rejected["reject_reason"] = rejected.apply(_reject_reason, axis=1)
    rejected["evidence_fields"] = rejected["key_risks"]
    return rejected.reindex(columns=REJECT_LOG_COLUMNS)


def build_evidence_summary(rows: pd.DataFrame) -> pd.DataFrame:
    return rows.reindex(
        columns=[
            "ticker",
            "company_name",
            "micro_sector",
            "cycle_status",
            "survival_status",
            "peer_rank",
            "valuation_context",
            "timing_liquidity_status",
            "key_evidence",
            "key_risks",
            "confidence_score",
            "watchlist_status",
        ]
    )


def build_data_quality_summary(rows: pd.DataFrame, missing_inputs: list[str]) -> pd.DataFrame:
    unresolved_count = sum(len(_parse_json_list(value)) for value in rows.get("missing_fields", pd.Series(dtype=str)).astype(str))
    metrics: list[dict[str, Any]] = [
        {"metric": "processed_ticker_count", "value": int(len(rows))},
        {"metric": "missing_input_file_count", "value": int(len(missing_inputs))},
        {"metric": "missing_input_files", "value": json.dumps(missing_inputs, ensure_ascii=False)},
        {"metric": "manual_review_count", "value": int(rows.get("manual_review_required", pd.Series(dtype=str)).map(_as_bool).sum()) if not rows.empty else 0},
        {"metric": "rejected_count", "value": _status_count(rows, "REJECTED")},
        {"metric": "insufficient_data_count", "value": _status_count(rows, "INSUFFICIENT_DATA")},
        {"metric": "unresolved_field_count", "value": int(unresolved_count)},
        {"metric": "market_source_confidence", "value": _first_value(rows, "market_source_confidence", "UNKNOWN")},
        {"metric": "finance_source_confidence", "value": _first_value(rows, "finance_source_confidence", "UNKNOWN")},
        {"metric": "crosscheck_status", "value": _first_value(rows, "crosscheck_status", "UNKNOWN")},
        {"metric": "verification_status", "value": _first_value(rows, "verification_status", "UNKNOWN")},
    ]
    return pd.DataFrame(metrics, columns=SUMMARY_COLUMNS)


def build_sector_cycle_summary(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=SECTOR_COLUMNS)
    summary_rows: list[dict[str, Any]] = []
    for micro_sector, group in rows.groupby("micro_sector", dropna=False):
        risks = " ".join(group["key_risks"].astype(str).tolist()).upper()
        cycle_status = "INSUFFICIENT_DATA"
        summary_rows.append(
            {
                "micro_sector": str(micro_sector or "UNKNOWN"),
                "ticker_count": int(group["ticker"].nunique()),
                "cycle_status": cycle_status,
                "top_improving_count": int(group["cycle_status"].astype(str).str.contains("RECOVERY|IMPROVING", case=False, regex=True).sum()),
                "distressed_without_recovery_count": 1 if "DISTRESS" in risks and "RECOVERY" not in risks else 0,
                "overheating_count": int(group["cycle_status"].astype(str).str.contains("OVERHEAT", case=False, regex=True).sum()),
                "structural_warning_count": 1 if "STRUCTURAL" in risks else 0,
                "anomaly_alert_count": 1 if "ANOMALY" in risks else 0,
                "data_quality_warning_count": int(group["manual_review_required"].map(_as_bool).sum()),
                "confidence_status": "INSUFFICIENT_DATA",
            }
        )
    return pd.DataFrame(summary_rows, columns=SECTOR_COLUMNS)


def build_company_engine_summary(rows: pd.DataFrame, step20_rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=COMPANY_ENGINE_COLUMNS)
    step20_by_ticker = _index_by_ticker(step20_rows)
    output_rows = []
    for _, row in rows.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        step20 = step20_by_ticker.get(ticker, {})
        output_rows.append(
            {
                "ticker": ticker,
                "company_name": row.get("company_name", "UNKNOWN"),
                "survival_status": row.get("survival_status", "UNKNOWN"),
                "peer_rank": row.get("peer_rank", "UNKNOWN"),
                "step20_status": _first_non_missing(step20.get("step20_status"), "UNKNOWN"),
                "valuation_context": row.get("valuation_context", "INSUFFICIENT_DATA"),
                "confidence_score": int(row.get("confidence_score", 0)),
                "manual_review_required": bool(_as_bool(row.get("manual_review_required"))),
                "watchlist_status": row.get("watchlist_status", "MANUAL_REVIEW"),
            }
        )
    return pd.DataFrame(output_rows, columns=COMPANY_ENGINE_COLUMNS)


def build_risk_warning_summary(rows: pd.DataFrame) -> pd.DataFrame:
    counts: dict[str, set[str]] = {}
    for _, row in rows.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        for flag in _parse_json_list(row.get("key_risks", "")):
            counts.setdefault(flag, set()).add(ticker)
        if str(row.get("crosscheck_status", "")).upper() == "NOT_AVAILABLE":
            counts.setdefault("CROSSCHECK_NOT_AVAILABLE", set()).add(ticker)
        if str(row.get("verification_status", "")).upper() == "NEEDS_MANUAL_BCTC_REVIEW":
            counts.setdefault("OFFICIAL_BCTC_REVIEW_REQUIRED", set()).add(ticker)
    output_rows = [
        {"warning_flag": flag, "affected_ticker_count": len(tickers), "affected_tickers": _json_list(sorted(tickers))}
        for flag, tickers in sorted(counts.items())
    ]
    return pd.DataFrame(output_rows, columns=RISK_WARNING_COLUMNS)


def build_source_conflict_report(rows: pd.DataFrame) -> pd.DataFrame:
    output_rows = []
    for _, row in rows.iterrows():
        conflicts = _parse_json_list(row.get("source_conflicts", ""))
        crosscheck = str(row.get("crosscheck_status", "UNKNOWN"))
        if conflicts:
            status = "SOURCE_CONFLICT_REPORTED"
            resolution = "MANUAL_REVIEW_REQUIRED"
        elif crosscheck.upper() == "NOT_AVAILABLE":
            status = "CROSSCHECK_NOT_AVAILABLE"
            resolution = "MANUAL_REVIEW_REQUIRED"
        else:
            status = "NO_CONFLICT_REPORTED"
            resolution = "NO_ACTION_REQUIRED"
        output_rows.append(
            {
                "ticker": row.get("ticker", ""),
                "crosscheck_status": crosscheck,
                "source_conflict_status": status,
                "source_conflicts": _json_list(conflicts),
                "resolution_status": resolution,
            }
        )
    return pd.DataFrame(output_rows, columns=SOURCE_CONFLICT_COLUMNS)


def build_unresolved_fields_report(rows: pd.DataFrame) -> pd.DataFrame:
    output_rows: list[dict[str, Any]] = []
    for _, row in rows.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        for field in _parse_json_list(row.get("missing_fields", "")):
            output_rows.append(
                {
                    "ticker": ticker,
                    "field_name": field,
                    "status": "UNRESOLVED",
                    "reason": "Input artifact reported this field as missing.",
                    "source_layer": "previous_layer",
                }
            )
        if str(row.get("verification_status", "")).upper() == "NEEDS_MANUAL_BCTC_REVIEW":
            output_rows.append(
                {
                    "ticker": ticker,
                    "field_name": "official_bctc_verification",
                    "status": "NEEDS_MANUAL_BCTC_REVIEW",
                    "reason": "Official filing evidence has not been manually checked.",
                    "source_layer": "manual_review",
                }
            )
        if str(row.get("crosscheck_status", "")).upper() == "NOT_AVAILABLE":
            output_rows.append(
                {
                    "ticker": ticker,
                    "field_name": "independent_crosscheck",
                    "status": "NOT_AVAILABLE",
                    "reason": "Independent source-family confirmation is not available.",
                    "source_layer": "crosscheck",
                }
            )
    return pd.DataFrame(output_rows, columns=UNRESOLVED_COLUMNS)


def build_summary(
    *,
    config: dict[str, Any],
    rows: pd.DataFrame,
    manual_queue: pd.DataFrame,
    reject_log: pd.DataFrame,
    missing_inputs: list[str],
    warnings: list[str],
    forbidden_hits: list[str],
    core_outputs_modified: bool,
) -> dict[str, Any]:
    confidence = config.get("source_confidence") or {}
    status_counts = _counts(rows, "watchlist_status")
    watchlist_count = sum(int(status_counts.get(status, 0)) for status in WATCHLIST_CANDIDATE_STATUSES)
    insufficient_count = int(status_counts.get("INSUFFICIENT_DATA", 0))
    if forbidden_hits or core_outputs_modified or rows.empty:
        final_decision = "BLOCKED_WEEKLY_REPORT"
    elif missing_inputs or len(manual_queue) or len(reject_log) or insufficient_count:
        final_decision = "PASS_WEEKLY_REPORT_WITH_WARNINGS"
    else:
        final_decision = "CONDITIONAL_GO_FOR_MONITORING_MODULE"
    if final_decision not in FINAL_DECISIONS:
        raise ValueError(f"Invalid STEP22 final decision: {final_decision}")
    summary_warnings = list(warnings)
    summary_warnings.extend(
        [
            SAFETY_NOTICE,
            "Market source confidence remains PROVISIONAL_PRIMARY_ONLY.",
            "Finance source confidence remains PROVISIONAL_LOW.",
            "Cross-check status remains NOT_AVAILABLE.",
            "Manual BCTC review remains required.",
        ]
    )
    if missing_inputs:
        summary_warnings.append("Some configured inputs were unavailable.")
    if core_outputs_modified:
        summary_warnings.append("Previous output hash changed during STEP22.")
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "mode": MODE,
        "processed_ticker_count": int(len(rows)),
        "watchlist_candidate_count": int(watchlist_count),
        "manual_review_count": int(len(manual_queue)),
        "rejected_count": int(len(reject_log)),
        "insufficient_data_count": insufficient_count,
        "watchlist_status_counts": status_counts,
        "missing_input_files": missing_inputs,
        "market_source_confidence": confidence.get("market_source_confidence", "PROVISIONAL_PRIMARY_ONLY"),
        "finance_source_confidence_default": confidence.get("finance_source_confidence_default", "PROVISIONAL_LOW"),
        "crosscheck_status": confidence.get("crosscheck_status", "NOT_AVAILABLE"),
        "verification_status": confidence.get("verification_status", "NEEDS_MANUAL_BCTC_REVIEW"),
        "final_decision": final_decision,
        "forbidden_terms_found": forbidden_hits,
        "warnings": summary_warnings,
        "core_outputs_modified": bool(core_outputs_modified),
    }


def build_evidence_debt(rows: pd.DataFrame, summary: dict[str, Any], missing_inputs: list[str]) -> dict[str, Any]:
    unresolved_count = sum(len(_parse_json_list(value)) for value in rows.get("missing_fields", pd.Series(dtype=str)).astype(str))
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "limitations": [
            "Only existing provisional artifacts were used.",
            "No official filing retrieval or OCR was performed.",
            "No trade action labels or price levels were produced.",
            "Manual BCTC and source verification remain required.",
        ],
        "missing_input_files": missing_inputs,
        "processed_ticker_count": int(summary.get("processed_ticker_count", 0)),
        "watchlist_status_counts": summary.get("watchlist_status_counts", {}),
        "manual_review_count": int(summary.get("manual_review_count", 0)),
        "unresolved_field_count": int(unresolved_count),
        "market_source_confidence": summary.get("market_source_confidence", "PROVISIONAL_PRIMARY_ONLY"),
        "finance_source_confidence_default": summary.get("finance_source_confidence_default", "PROVISIONAL_LOW"),
        "crosscheck_status": summary.get("crosscheck_status", "NOT_AVAILABLE"),
        "verification_status": summary.get("verification_status", "NEEDS_MANUAL_BCTC_REVIEW"),
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


def write_step22_outputs(
    *,
    output_dir: Path,
    rows: pd.DataFrame,
    manual_queue: pd.DataFrame,
    reject_log: pd.DataFrame,
    evidence_summary: pd.DataFrame,
    data_quality_summary: pd.DataFrame,
    sector_summary: pd.DataFrame,
    company_summary: pd.DataFrame,
    risk_summary: pd.DataFrame,
    source_conflicts: pd.DataFrame,
    unresolved: pd.DataFrame,
    summary: dict[str, Any],
    evidence_debt: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows.to_csv(output_dir / "watchlist_candidates.csv", index=False)
    manual_queue.to_csv(output_dir / "manual_review_queue.csv", index=False)
    reject_log.to_csv(output_dir / "reject_log.csv", index=False)
    evidence_summary.to_csv(output_dir / "evidence_summary.csv", index=False)
    data_quality_summary.to_csv(output_dir / "data_quality_summary.csv", index=False)
    sector_summary.to_csv(output_dir / "sector_cycle_summary.csv", index=False)
    company_summary.to_csv(output_dir / "company_engine_summary.csv", index=False)
    risk_summary.to_csv(output_dir / "risk_warning_summary.csv", index=False)
    source_conflicts.to_csv(output_dir / "source_conflict_report.csv", index=False)
    unresolved.to_csv(output_dir / "unresolved_fields_report.csv", index=False)
    _write_json(output_dir / "weekly_report_summary.json", summary)
    _write_json(output_dir / "evidence_debt_report.json", evidence_debt)
    _write_json(output_dir / "run_manifest.json", manifest)
    (output_dir / "weekly_report.md").write_text(
        build_weekly_report_markdown(rows, manual_queue, reject_log, sector_summary, risk_summary, source_conflicts, unresolved, summary),
        encoding="utf-8",
    )


def build_weekly_report_markdown(
    rows: pd.DataFrame,
    manual_queue: pd.DataFrame,
    reject_log: pd.DataFrame,
    sector_summary: pd.DataFrame,
    risk_summary: pd.DataFrame,
    source_conflicts: pd.DataFrame,
    unresolved: pd.DataFrame,
    summary: dict[str, Any],
) -> str:
    status_counts = summary.get("watchlist_status_counts", {})
    lines = [
        "# Weekly Screening Report -- Provisional Evidence Only",
        "",
        "## Safety Notice",
        SAFETY_NOTICE,
        "",
        "## Run Summary",
        f"- processed_ticker_count: {summary.get('processed_ticker_count', 0)}",
        f"- watchlist_candidate_count: {summary.get('watchlist_candidate_count', 0)}",
        f"- manual_review_count: {summary.get('manual_review_count', 0)}",
        f"- rejected_count: {summary.get('rejected_count', 0)}",
        f"- insufficient_data_count: {summary.get('insufficient_data_count', 0)}",
        f"- final_decision: {summary.get('final_decision', '')}",
        f"- watchlist_status_counts: {status_counts}",
        "",
        "## Data Confidence",
        f"- market_source_confidence: {summary.get('market_source_confidence', '')}",
        f"- finance_source_confidence_default: {summary.get('finance_source_confidence_default', '')}",
        f"- crosscheck_status: {summary.get('crosscheck_status', '')}",
        f"- verification_status: {summary.get('verification_status', '')}",
        f"- missing_input_files: {summary.get('missing_input_files', [])}",
        "",
        "## Top Improving Micro-Sectors",
        _sector_section(sector_summary, "top_improving_count"),
        "",
        "## Distressed Sectors Without Recovery Signal",
        _sector_section(sector_summary, "distressed_without_recovery_count"),
        "",
        "## Overheating Sectors",
        _sector_section(sector_summary, "overheating_count"),
        "",
        "## Structural Risk Warnings",
        _sector_section(sector_summary, "structural_warning_count"),
        "",
        "## Anomaly Alerts",
        _sector_section(sector_summary, "anomaly_alert_count"),
        "",
        "## Data Quality Warnings",
        _markdown_table(risk_summary.head(10), ["warning_flag", "affected_ticker_count"]),
        "",
        "## Watchlist Candidates",
        _markdown_table(rows[rows["watchlist_status"].isin(WATCHLIST_CANDIDATE_STATUSES)].head(20), ["ticker", "company_name", "watchlist_status", "confidence_score", "micro_sector"]),
        "",
        "## Rejected / Blocked Stocks",
        _markdown_table(reject_log.head(20), ["ticker", "company_name", "reject_reason"]),
        "",
        "## Manual Review Queue",
        _markdown_table(manual_queue.head(20), ["ticker", "company_name", "watchlist_status", "manual_review_reason"]),
        "",
        "## Evidence Debt",
        "- Official BCTC and independent source verification remain unresolved.",
        "- Prior outputs are summarized only; they are not mutated by this report.",
        "- Source confidence remains provisional under the configured policy.",
        "",
        "## Missing Fields / Source Conflicts",
        _markdown_table(unresolved.head(20), ["ticker", "field_name", "status"]),
        "",
        "### Source Conflict Snapshot",
        _markdown_table(source_conflicts.head(20), ["ticker", "crosscheck_status", "source_conflict_status", "resolution_status"]),
        "",
        "## Next Manual Actions",
        "- Review unresolved official BCTC verification items.",
        "- Review independent source-family gaps.",
        "- Review tickers with MANUAL_REVIEW or INSUFFICIENT_DATA status before any deeper layer.",
    ]
    return "\n".join(lines) + "\n"


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


def _watchlist_status(
    step05a: dict[str, Any],
    step19: dict[str, Any],
    step20: dict[str, Any],
    step21: dict[str, Any],
    missing_fields: list[str],
    source_conflicts: list[str],
    confidence_score: int,
) -> str:
    screening_status = str(step05a.get("screening_status", "")).upper()
    shadow_status = str(step19.get("shadow_status", "")).upper()
    if screening_status.startswith("BLOCKED_") or shadow_status.startswith("SHADOW_BLOCKED"):
        return "REJECTED"
    if source_conflicts:
        return "MANUAL_REVIEW"
    if _has_critical_missing_fields(missing_fields) or _timing_or_liquidity_insufficient(step21):
        return "INSUFFICIENT_DATA"
    step20_status = str(step20.get("step20_status", "")).upper()
    if confidence_score >= 80 and step20_status in {"STEP20_CONTEXT_READY", "STEP20_CONTEXT_LOW_CONFIDENCE", ""}:
        return "HIGH_CONFIDENCE_WATCHLIST"
    if confidence_score >= 65:
        return "MEDIUM_CONFIDENCE_WATCHLIST"
    if confidence_score >= 45:
        return "WATCH_ONLY"
    return "MANUAL_REVIEW"


def _manual_review_required(status: str, confidence: dict[str, Any], step05a: dict[str, Any], step20: dict[str, Any], step21: dict[str, Any], source_conflicts: list[str]) -> bool:
    if status in {"MANUAL_REVIEW", "REJECTED", "INSUFFICIENT_DATA"}:
        return True
    if source_conflicts:
        return True
    if str(confidence.get("verification_status", "")).upper() == "NEEDS_MANUAL_BCTC_REVIEW":
        return True
    if str(confidence.get("crosscheck_status", "")).upper() == "NOT_AVAILABLE":
        return True
    if str(confidence.get("finance_source_confidence_default", "")).upper() == "PROVISIONAL_LOW":
        return True
    return any(
        _as_bool(row.get("manual_review_required")) or _as_bool(row.get("manual_bctc_required"))
        for row in [step05a, step20, step21]
    )


def _confidence_score(step05a: dict[str, Any], step19: dict[str, Any], step20: dict[str, Any], step21: dict[str, Any], missing_fields: list[str], source_conflicts: list[str], confidence: dict[str, Any]) -> int:
    score = 50
    screening_status = str(step05a.get("screening_status", "")).upper()
    if screening_status == "WATCHLIST_CANDIDATE":
        score += 10
    elif screening_status.startswith("BLOCKED_"):
        score -= 30

    shadow_status = str(step19.get("shadow_status", "")).upper()
    if shadow_status == "SHADOW_READY_DIAGNOSTIC_ONLY":
        score += 15
    elif shadow_status == "SHADOW_CONDITIONAL_DIAGNOSTIC_ONLY":
        score += 5
    elif shadow_status.startswith("SHADOW_BLOCKED"):
        score -= 25

    step20_status = str(step20.get("step20_status", "")).upper()
    if step20_status == "STEP20_CONTEXT_READY":
        score += 15
    elif step20_status == "STEP20_CONTEXT_LOW_CONFIDENCE":
        score += 5
    elif step20_status == "STEP20_INSUFFICIENT_DATA":
        score -= 15
    elif step20_status == "STEP20_MANUAL_REVIEW_REQUIRED":
        score -= 10

    timing_bucket = str(step21.get("timing_risk_bucket", "")).upper()
    if timing_bucket == "TIMING_RISK_LOW":
        score += 10
    elif timing_bucket in {"TIMING_RISK_ELEVATED", "TIMING_RISK_HIGH", "TIMING_INSUFFICIENT_DATA"}:
        score -= 15

    liquidity_bucket = str(step21.get("liquidity_risk_bucket", "")).upper()
    if liquidity_bucket == "LIQUIDITY_RISK_LOW":
        score += 10
    elif liquidity_bucket == "LIQUIDITY_RISK_MODERATE":
        score += 5
    elif liquidity_bucket in {"LIQUIDITY_RISK_ELEVATED", "LIQUIDITY_RISK_HIGH", "LIQUIDITY_INSUFFICIENT_DATA"}:
        score -= 15

    if str(confidence.get("crosscheck_status", "")).upper() == "NOT_AVAILABLE":
        score -= 5
    if str(confidence.get("verification_status", "")).upper() == "NEEDS_MANUAL_BCTC_REVIEW":
        score -= 10
    if source_conflicts:
        score -= 15
    score -= min(30, len(missing_fields) * 3)
    return max(0, min(100, int(score)))


def _key_evidence(step05a: dict[str, Any], step19: dict[str, Any], step20: dict[str, Any], step21: dict[str, Any]) -> list[str]:
    evidence = []
    if not _is_missing(step05a.get("screening_status")):
        evidence.append(f"Step05A status: {step05a.get('screening_status')}")
    if not _is_missing(step19.get("shadow_status")):
        evidence.append(f"Step19 diagnostic status: {step19.get('shadow_status')}")
    if not _is_missing(step20.get("step20_status")):
        evidence.append(f"Step20 context status: {step20.get('step20_status')}")
    timing = _timing_liquidity_status(step21)
    if timing != "INSUFFICIENT_DATA":
        evidence.append(f"Step21 timing/liquidity context: {timing}")
    return evidence or ["INSUFFICIENT_DATA"]


def _key_risks(step20: dict[str, Any], step21: dict[str, Any], step19: dict[str, Any], step05a: dict[str, Any], missing_fields: list[str], source_conflicts: list[str]) -> list[str]:
    risks: list[str] = []
    risks.extend(_parse_json_list(step20.get("risk_flags", "")))
    risks.extend(_parse_json_list(step21.get("technical_warning_flags", "")))
    risks.extend(_parse_json_list(step21.get("liquidity_warning_flags", "")))
    risks.extend(_parse_json_list(step05a.get("block_reasons", "")))
    if str(step19.get("shadow_status", "")).upper().startswith("SHADOW_BLOCKED"):
        risks.append("SHADOW_DIAGNOSTIC_BLOCKED")
    if missing_fields:
        risks.append("UNRESOLVED_FIELDS_PRESENT")
    if source_conflicts:
        risks.append("SOURCE_CONFLICT_REPORTED")
    risks.append("PROVISIONAL_SOURCE_CONFIDENCE")
    return sorted(set(risks))


def _merged_missing_fields(*rows_and_missing: Any) -> list[str]:
    *rows, missing_inputs = rows_and_missing
    fields: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for column in ["missing_fields", "missing_required_fields", "finance_missing_fields"]:
            fields.extend(_parse_json_list(row.get(column, "")))
    for item in missing_inputs:
        logical = str(item).split(":", 1)[0]
        fields.append(f"input:{logical}")
    return sorted(set(field for field in fields if not _is_missing(field)))


def _has_critical_missing_fields(missing_fields: list[str]) -> bool:
    critical = {"ticker", "last_close", "last_price_date", "avg_volume_20d"}
    return any(field in critical or field.startswith("input:step21_rows") for field in missing_fields)


def _timing_or_liquidity_insufficient(step21: dict[str, Any]) -> bool:
    return str(step21.get("timing_risk_bucket", "")).upper() == "TIMING_INSUFFICIENT_DATA" or str(step21.get("liquidity_risk_bucket", "")).upper() == "LIQUIDITY_INSUFFICIENT_DATA"


def _cycle_status(step20: dict[str, Any]) -> str:
    if _is_missing(step20.get("primary_micro_sector")):
        return "INSUFFICIENT_DATA"
    return "INSUFFICIENT_DATA"


def _peer_rank(step20: dict[str, Any]) -> str:
    for column in ["peer_rank", "peer_rank_bucket", "peer_rank_percentile", "rank_within_peer_group"]:
        if not _is_missing(step20.get(column)):
            return str(step20.get(column))
    return "UNKNOWN"


def _timing_liquidity_status(step21: dict[str, Any]) -> str:
    timing = str(step21.get("timing_risk_bucket", "")).strip()
    liquidity = str(step21.get("liquidity_risk_bucket", "")).strip()
    if not timing and not liquidity:
        return "INSUFFICIENT_DATA"
    return f"{timing or 'INSUFFICIENT_DATA'}|{liquidity or 'INSUFFICIENT_DATA'}"


def _evidence_debt_reasons(missing_fields: list[str], source_conflicts: list[str], missing_inputs: list[str]) -> list[str]:
    reasons = [
        "Market source remains primary-only.",
        "Finance source remains provisional low.",
        "Manual BCTC/source verification remains required.",
    ]
    if missing_fields:
        reasons.append("Some fields remain unresolved.")
    if source_conflicts:
        reasons.append("Source conflict requires manual review.")
    if missing_inputs:
        reasons.append("Some configured inputs were unavailable.")
    return reasons


def _manual_review_reason(row: pd.Series) -> str:
    reasons = []
    status = str(row.get("watchlist_status", ""))
    if status in {"MANUAL_REVIEW", "INSUFFICIENT_DATA", "REJECTED"}:
        reasons.append(f"Status is {status}.")
    if str(row.get("verification_status", "")).upper() == "NEEDS_MANUAL_BCTC_REVIEW":
        reasons.append("Manual BCTC/source verification required.")
    if str(row.get("crosscheck_status", "")).upper() == "NOT_AVAILABLE":
        reasons.append("Independent cross-check is not available.")
    if _parse_json_list(row.get("missing_fields", "")):
        reasons.append("Unresolved fields are present.")
    if _parse_json_list(row.get("source_conflicts", "")):
        reasons.append("Source conflict is unresolved.")
    return " ".join(reasons) if reasons else "Manual review required by provisional policy."


def _reject_reason(row: pd.Series) -> str:
    risks = _parse_json_list(row.get("key_risks", ""))
    if "SHADOW_DIAGNOSTIC_BLOCKED" in risks:
        return "Step19 diagnostic blocked this ticker."
    if _parse_json_list(row.get("missing_fields", "")):
        return "Critical required fields are unresolved."
    return "Preliminary evidence marked this ticker as blocked."


def _sector_section(sector_summary: pd.DataFrame, count_column: str) -> str:
    if sector_summary.empty or count_column not in sector_summary.columns:
        return "INSUFFICIENT_DATA"
    rows = sector_summary[sector_summary[count_column].astype(int) > 0].head(10)
    if rows.empty:
        return "INSUFFICIENT_DATA"
    return _markdown_table(rows, ["micro_sector", count_column, "confidence_status"])


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    if frame.empty:
        return "INSUFFICIENT_DATA"
    available = [column for column in columns if column in frame.columns]
    if not available:
        return "INSUFFICIENT_DATA"
    lines = ["| " + " | ".join(available) + " |", "| " + " | ".join(["---"] * len(available)) + " |"]
    for _, row in frame.reindex(columns=available).iterrows():
        values = [_clean_markdown_cell(row.get(column, "UNKNOWN")) for column in available]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def _clean_markdown_cell(value: Any) -> str:
    text = str(value)
    text = text.replace("|", "/").replace("\n", " ").strip()
    return text if text else "UNKNOWN"


def _combined_tickers(*frames: pd.DataFrame) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for frame in frames:
        for ticker in _ticker_list(frame):
            if ticker not in seen:
                seen.add(ticker)
                out.append(ticker)
    return out


def _ticker_list(frame: pd.DataFrame) -> list[str]:
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


def _frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    return frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()


def _counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame.columns:
        return {}
    counts = frame[column].astype(str).value_counts().sort_index()
    return {key: int(value) for key, value in counts.items()}


def _status_count(frame: pd.DataFrame, status: str) -> int:
    if frame.empty or "watchlist_status" not in frame.columns:
        return 0
    return int(frame["watchlist_status"].eq(status).sum())


def _first_value(frame: pd.DataFrame, column: str, default: str) -> str:
    if frame.empty or column not in frame.columns:
        return default
    for value in frame[column]:
        if not _is_missing(value):
            return str(value)
    return default


def _first_non_missing(*values: Any) -> str:
    for value in values:
        if not _is_missing(value):
            return str(value)
    return "UNKNOWN"


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


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _is_missing(value: Any) -> bool:
    return value is None or str(value).strip() == "" or str(value).strip().lower() in {"nan", "none", "null", "na"}


def _term_in_text(term: str, lower_text: str) -> bool:
    if " " in term or "-" in term:
        return term in lower_text
    return re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", lower_text) is not None


def _spec_text(spec: Any) -> str:
    if isinstance(spec, list):
        return "|".join(str(item) for item in spec)
    return str(spec)


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
