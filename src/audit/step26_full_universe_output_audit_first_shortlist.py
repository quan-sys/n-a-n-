"""STEP26 full-universe output audit and first manual-review shortlist.

This module audits STEP25 outputs and creates neutral review queues. It does not
fetch new data, infer missing finance values, or produce investment conclusions.
"""

from __future__ import annotations

import hashlib
import ast
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


STEP_ID = "STEP26-FULL-UNIVERSE-OUTPUT-AUDIT-FIRST-SHORTLIST"
MODE = "output_audit_first_shortlist"

FINAL_DECISIONS = {
    "PASS_FULL_UNIVERSE_AUDIT_WITH_SHORTLIST",
    "PASS_FULL_UNIVERSE_AUDIT_WITH_DATA_GAPS",
    "BLOCKED_NO_STEP25_ROW_ARTIFACT",
    "BLOCKED_GUARDRAIL_VIOLATION",
}

SHORTLIST_STATUSES = {
    "FIRST_REVIEW_SHORTLIST",
    "BCTC_PRIORITY_REVIEW",
    "DATA_REPAIR_FIRST",
    "MANUAL_REVIEW_LATER",
    "INSUFFICIENT_DATA",
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
    "recommended portfolio",
    "investment-ready",
]

ALLOWED_SAFETY_LINES = {
    "this report does not contain buy/sell/hold signals.",
}

NORMALIZED_COLUMNS = [
    "ticker",
    "company_name",
    "screening_status",
    "watchlist_status",
    "manual_review_required",
    "manual_bctc_required",
    "market_source_confidence",
    "finance_source_confidence",
    "crosscheck_status",
    "verification_status",
    "missing_fields",
    "block_reasons",
    "reason_to_review",
    "last_price_date",
    "last_close",
    "avg_volume_20d",
    "avg_volume_60d",
    "last_volume",
    "recent_trading_value",
    "stale_days",
    "market_fetch_status",
    "finance_quality_status",
    "finance_source_layer",
    "micro_sector",
    "sector",
    "archetype",
    "cycle_status",
    "survival_status",
    "valuation_context",
    "timing_liquidity_status",
    "confidence_score",
    "source_conflicts",
]

DISTRIBUTION_COLUMNS = ["field_name", "field_value", "count", "percentage_of_universe"]
REASON_COLUMNS = ["reason_or_field", "count", "percentage_of_universe", "example_tickers"]
COVERAGE_COLUMNS = [
    "ticker",
    "company_name",
    "screening_status",
    "market_data_available",
    "recent_price_available",
    "liquidity_data_available",
    "finance_data_available",
    "sector_classification_available",
    "cycle_context_available",
    "valuation_context_available",
    "timing_liquidity_context_available",
    "missing_field_count",
    "block_reason_count",
    "source_conflict_count",
    "data_coverage_score",
    "coverage_status",
]
SHORTLIST_COLUMNS = [
    "ticker",
    "company_name",
    "screening_status",
    "review_status",
    "review_priority",
    "coverage_rank",
    "manual_review_priority",
    "data_coverage_score",
    "missing_field_count",
    "recent_trading_value",
    "manual_bctc_required",
    "market_source_confidence",
    "finance_source_confidence",
    "crosscheck_status",
    "verification_status",
    "reason_to_review",
]


class Step26SafeRunBlocked(RuntimeError):
    """Raised when STEP26 cannot proceed safely."""


@dataclass
class Step26Artifacts:
    step25_rows_path: Path | None
    watchlist_path: Path | None
    manual_queue_path: Path | None
    blocked_path: Path | None
    summary_path: Path | None
    manifest_path: Path | None
    missing_input_files: list[str]


@dataclass
class Step26Result:
    artifacts: Step26Artifacts
    normalized_rows: pd.DataFrame
    status_distribution: pd.DataFrame
    source_confidence_distribution: pd.DataFrame
    manual_review_distribution: pd.DataFrame
    block_reason_distribution: pd.DataFrame
    missing_field_distribution: pd.DataFrame
    reject_reason_distribution: pd.DataFrame
    data_coverage_by_ticker: pd.DataFrame
    data_gap_report: pd.DataFrame
    schema_gap_report: pd.DataFrame
    first_review_shortlist: pd.DataFrame
    manual_bctc_priority_queue: pd.DataFrame
    surviving_primary_only_candidates: pd.DataFrame
    data_repair_priority_queue: pd.DataFrame
    sector_candidate_distribution: pd.DataFrame
    micro_sector_candidate_distribution: pd.DataFrame
    sector_data_gap_summary: pd.DataFrame
    run_manifest: dict[str, Any]
    summary: dict[str, Any]


def load_step26_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("STEP26 config must be a mapping.")
    return data


def run_step26_full_universe_output_audit_first_shortlist(
    *,
    config_path: str | Path,
    output_dir: str | Path | None = None,
    allow_partial: bool | None = None,
    command_used: str = "",
    core_output_paths: list[str | Path] | None = None,
) -> Step26Result:
    config = load_step26_config(config_path)
    validate_step26_config(config)
    exports = config.get("exports") or {}
    output = Path(output_dir or exports.get("output_dir") or "data/reports/step26_full_universe_output_audit_first_shortlist")
    output.mkdir(parents=True, exist_ok=True)
    run_policy = dict(config.get("run") or {})
    if allow_partial is not None:
        run_policy["allow_partial"] = bool(allow_partial)
    allow_partial_effective = _as_bool(run_policy.get("allow_partial", True))

    core_paths = [Path(path) for path in (core_output_paths or config.get("core_output_watchlist", []))]
    before_hashes = _hashes(core_paths)
    artifacts = find_step25_artifacts(config)
    if artifacts.step25_rows_path is None and not allow_partial_effective:
        raise Step26SafeRunBlocked("No usable STEP25 row-level artifact found.")

    source_columns: set[str] = set()
    if artifacts.step25_rows_path is None:
        normalized = pd.DataFrame(columns=NORMALIZED_COLUMNS)
    else:
        max_rows = int((config.get("limits") or {}).get("max_rows_to_read", 2000) or 2000)
        step25_rows = _read_csv(artifacts.step25_rows_path).head(max_rows)
        source_columns = set(step25_rows.columns)
        normalized = normalize_rows(step25_rows)

    status_distribution = build_status_distribution(normalized)
    source_distribution = build_distribution(normalized, ["market_source_confidence", "finance_source_confidence", "crosscheck_status", "verification_status"])
    manual_distribution = build_distribution(normalized, ["manual_review_required", "manual_bctc_required"])
    block_reasons = build_reason_distribution(normalized, "block_reasons")
    missing_fields = build_reason_distribution(normalized, "missing_fields")
    reject_reasons = build_reject_reason_distribution(normalized)
    coverage = build_data_coverage_by_ticker(normalized)
    data_gap = build_data_gap_report(coverage, missing_fields, block_reasons)
    schema_gap = build_schema_gap_report(normalized, source_columns)
    first_shortlist, manual_queue, survivors, repair_queue = build_shortlists(config, normalized, coverage)
    sector_distribution = build_sector_summary(normalized, coverage, "sector")
    micro_distribution = build_sector_summary(normalized, coverage, "micro_sector")
    sector_gap = build_sector_data_gap_summary(normalized, coverage)
    core_modified = before_hashes != _hashes(core_paths)
    summary = build_summary(
        config=config,
        artifacts=artifacts,
        normalized=normalized,
        first_shortlist=first_shortlist,
        manual_queue=manual_queue,
        repair_queue=repair_queue,
        status_distribution=status_distribution,
        block_reasons=block_reasons,
        missing_fields=missing_fields,
        forbidden_hits=[],
        core_outputs_modified=core_modified,
    )
    manifest = build_run_manifest(
        config=config,
        config_path=Path(config_path),
        output_dir=output,
        artifacts=artifacts,
        command_used=command_used,
        allow_partial=allow_partial_effective,
        core_outputs_modified=core_modified,
    )
    write_outputs(
        output_dir=output,
        normalized=normalized,
        status_distribution=status_distribution,
        source_distribution=source_distribution,
        manual_distribution=manual_distribution,
        block_reasons=block_reasons,
        missing_fields=missing_fields,
        reject_reasons=reject_reasons,
        coverage=coverage,
        data_gap=data_gap,
        schema_gap=schema_gap,
        first_shortlist=first_shortlist,
        manual_queue=manual_queue,
        survivors=survivors,
        repair_queue=repair_queue,
        sector_distribution=sector_distribution,
        micro_distribution=micro_distribution,
        sector_gap=sector_gap,
        summary=summary,
        manifest=manifest,
    )
    forbidden_hits = scan_forbidden_terms(output)
    if forbidden_hits:
        summary = build_summary(
            config=config,
            artifacts=artifacts,
            normalized=normalized,
            first_shortlist=first_shortlist,
            manual_queue=manual_queue,
            repair_queue=repair_queue,
            status_distribution=status_distribution,
            block_reasons=block_reasons,
            missing_fields=missing_fields,
            forbidden_hits=forbidden_hits,
            core_outputs_modified=core_modified,
        )
        write_outputs(
            output_dir=output,
            normalized=normalized,
            status_distribution=status_distribution,
            source_distribution=source_distribution,
            manual_distribution=manual_distribution,
            block_reasons=block_reasons,
            missing_fields=missing_fields,
            reject_reasons=reject_reasons,
            coverage=coverage,
            data_gap=data_gap,
            schema_gap=schema_gap,
            first_shortlist=first_shortlist,
            manual_queue=manual_queue,
            survivors=survivors,
            repair_queue=repair_queue,
            sector_distribution=sector_distribution,
            micro_distribution=micro_distribution,
            sector_gap=sector_gap,
            summary=summary,
            manifest=manifest,
        )
    return Step26Result(
        artifacts=artifacts,
        normalized_rows=normalized,
        status_distribution=status_distribution,
        source_confidence_distribution=source_distribution,
        manual_review_distribution=manual_distribution,
        block_reason_distribution=block_reasons,
        missing_field_distribution=missing_fields,
        reject_reason_distribution=reject_reasons,
        data_coverage_by_ticker=coverage,
        data_gap_report=data_gap,
        schema_gap_report=schema_gap,
        first_review_shortlist=first_shortlist,
        manual_bctc_priority_queue=manual_queue,
        surviving_primary_only_candidates=survivors,
        data_repair_priority_queue=repair_queue,
        sector_candidate_distribution=sector_distribution,
        micro_sector_candidate_distribution=micro_distribution,
        sector_data_gap_summary=sector_gap,
        run_manifest=manifest,
        summary=summary,
    )


def validate_step26_config(config: dict[str, Any]) -> None:
    if config.get("step_id") != STEP_ID:
        raise ValueError(f"STEP26 config step_id must be {STEP_ID}.")
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
        "no_zero_fill",
        "no_missing_finance_inference",
        "no_pdf_ocr",
        "no_official_bctc_scrape",
        "no_core_output_mutation",
        "no_stage_promotion_to_investment_ready",
    ]
    missing = [key for key in required if safety.get(key) is not True]
    if missing:
        raise ValueError(f"STEP26 safety flags must be true: {','.join(missing)}")


def find_step25_artifacts(config: dict[str, Any]) -> Step26Artifacts:
    roots = [Path(path) for path in ((config.get("inputs") or {}).get("step25_search_dirs") or [])]
    roots.extend([Path("data/reports/step25_full_universe_1743_primary_only_scale"), Path("data/reports")])
    row_names = [
        "full_universe_screening_rows.csv",
        "full_universe_primary_only_rows.csv",
        "primary_only_screening_rows.csv",
        "full_universe_rows.csv",
    ]
    watchlist_names = ["watchlist_candidates.csv"]
    manual_names = ["manual_bctc_review_queue.csv"]
    blocked_names = ["blocked_tickers.csv"]
    summary_names = ["full_universe_scale_summary.json", "full_universe_summary.json", "scale_summary.json", "batch_summary.json"]
    manifest_names = ["run_manifest.json"]
    rows_path = _find_named_artifact(roots, row_names) or _search_artifact(["step25", "full_universe"], ".csv")
    watchlist = _find_named_artifact(roots, watchlist_names, preferred_parent=rows_path.parent if rows_path else None)
    manual = _find_named_artifact(roots, manual_names, preferred_parent=rows_path.parent if rows_path else None)
    blocked = _find_named_artifact(roots, blocked_names, preferred_parent=rows_path.parent if rows_path else None)
    summary = _find_named_artifact(roots, summary_names, preferred_parent=rows_path.parent if rows_path else None)
    manifest = _find_named_artifact(roots, manifest_names, preferred_parent=rows_path.parent if rows_path else None)
    missing = []
    for label, path in [
        ("step25_rows_path", rows_path),
        ("watchlist_path", watchlist),
        ("manual_queue_path", manual),
        ("blocked_path", blocked),
        ("summary_path", summary),
        ("manifest_path", manifest),
    ]:
        if path is None:
            missing.append(label)
    return Step26Artifacts(rows_path, watchlist, manual, blocked, summary, manifest, missing)


def normalize_rows(rows: pd.DataFrame) -> pd.DataFrame:
    normalized = pd.DataFrame()
    for column in NORMALIZED_COLUMNS:
        if column in rows.columns:
            normalized[column] = rows[column]
        else:
            normalized[column] = ""
    if "watchlist_status" not in rows.columns:
        normalized["watchlist_status"] = normalized["screening_status"].map(_screening_to_watchlist_status)
    return normalized.reindex(columns=NORMALIZED_COLUMNS)


def build_status_distribution(rows: pd.DataFrame) -> pd.DataFrame:
    fields = [
        "screening_status",
        "watchlist_status",
        "manual_review_required",
        "manual_bctc_required",
        "market_fetch_status",
        "finance_quality_status",
    ]
    return build_distribution(rows, fields)


def build_distribution(rows: pd.DataFrame, fields: list[str]) -> pd.DataFrame:
    total = len(rows)
    records = []
    for field in fields:
        if field not in rows.columns:
            records.append({"field_name": field, "field_value": "SCHEMA_FIELD_MISSING", "count": 0, "percentage_of_universe": 0.0})
            continue
        counts = rows[field].astype(str).replace("", "BLANK").value_counts().sort_index()
        for value, count in counts.items():
            records.append(
                {
                    "field_name": field,
                    "field_value": value,
                    "count": int(count),
                    "percentage_of_universe": round((int(count) / total * 100) if total else 0.0, 4),
                }
            )
    return pd.DataFrame(records, columns=DISTRIBUTION_COLUMNS)


def build_reason_distribution(rows: pd.DataFrame, column: str, denominator: int | None = None) -> pd.DataFrame:
    total = len(rows) if denominator is None else denominator
    counts: dict[str, dict[str, Any]] = {}
    if column not in rows.columns:
        return pd.DataFrame(columns=REASON_COLUMNS)
    for _, row in rows.iterrows():
        ticker = str(row.get("ticker", ""))
        values = parse_listish(row.get(column, ""))
        if not values and column == "block_reasons" and not _is_missing(row.get("reason_to_review")):
            values = [str(row.get("reason_to_review"))]
        for value in values:
            counts.setdefault(value, {"count": 0, "tickers": []})
            counts[value]["count"] += 1
            if len(counts[value]["tickers"]) < 5:
                counts[value]["tickers"].append(ticker)
    records = [
        {
            "reason_or_field": key,
            "count": int(value["count"]),
            "percentage_of_universe": round((int(value["count"]) / total * 100) if total else 0.0, 4),
            "example_tickers": _json_list(value["tickers"]),
        }
        for key, value in sorted(counts.items(), key=lambda item: (-item[1]["count"], item[0]))
    ]
    return pd.DataFrame(records, columns=REASON_COLUMNS)


def build_reject_reason_distribution(rows: pd.DataFrame) -> pd.DataFrame:
    rejected = rows[rows["watchlist_status"].astype(str).isin(["REJECTED", "INSUFFICIENT_DATA"])] if not rows.empty else rows
    return build_reason_distribution(rejected, "block_reasons", denominator=len(rows))


def build_data_coverage_by_ticker(rows: pd.DataFrame) -> pd.DataFrame:
    records = []
    for _, row in rows.iterrows():
        missing_count = len(parse_listish(row.get("missing_fields", "")))
        block_count = len(parse_listish(row.get("block_reasons", "")))
        conflict_count = len(parse_listish(row.get("source_conflicts", "")))
        market_available = not _is_missing(row.get("last_close")) and not _is_missing(row.get("last_price_date"))
        recent_price = not _is_missing(row.get("last_price_date")) and _to_float(row.get("stale_days")) in {None, 0.0}
        liquidity = any(not _is_missing(row.get(field)) for field in ["recent_trading_value", "avg_volume_20d", "last_volume", "avg_volume_60d"])
        finance_available = str(row.get("finance_quality_status", "")).upper() not in {"", "INSUFFICIENT_DATA", "BLANK"}
        sector_available = not _is_missing(row.get("sector")) or not _is_missing(row.get("micro_sector"))
        cycle_available = not _is_missing(row.get("cycle_status"))
        valuation_available = not _is_missing(row.get("valuation_context"))
        timing_available = not _is_missing(row.get("timing_liquidity_status"))
        score = 0
        for flag, points in [
            (market_available, 25),
            (recent_price, 15),
            (liquidity, 15),
            (finance_available, 15),
            (sector_available, 10),
            (cycle_available, 5),
            (valuation_available, 5),
            (timing_available, 5),
            (conflict_count == 0, 5),
        ]:
            if flag:
                score += points
        score = max(0, min(100, score - min(30, missing_count * 2) - min(20, block_count * 5)))
        records.append(
            {
                "ticker": row.get("ticker", ""),
                "company_name": row.get("company_name", ""),
                "screening_status": row.get("screening_status", ""),
                "market_data_available": bool(market_available),
                "recent_price_available": bool(recent_price),
                "liquidity_data_available": bool(liquidity),
                "finance_data_available": bool(finance_available),
                "sector_classification_available": bool(sector_available),
                "cycle_context_available": bool(cycle_available),
                "valuation_context_available": bool(valuation_available),
                "timing_liquidity_context_available": bool(timing_available),
                "missing_field_count": int(missing_count),
                "block_reason_count": int(block_count),
                "source_conflict_count": int(conflict_count),
                "data_coverage_score": int(score),
                "coverage_status": _coverage_status(score, market_available, missing_count),
            }
        )
    return pd.DataFrame(records, columns=COVERAGE_COLUMNS)


def build_data_gap_report(coverage: pd.DataFrame, missing_fields: pd.DataFrame, block_reasons: pd.DataFrame) -> pd.DataFrame:
    records = []
    if not coverage.empty:
        for metric in ["market_data_available", "recent_price_available", "liquidity_data_available", "finance_data_available", "sector_classification_available"]:
            missing_count = int((~coverage[metric].map(_as_bool)).sum())
            records.append({"gap_type": metric, "affected_count": missing_count, "details": "availability_flag_false"})
    for _, row in missing_fields.head(20).iterrows():
        records.append({"gap_type": f"missing_field:{row['reason_or_field']}", "affected_count": int(row["count"]), "details": row["example_tickers"]})
    for _, row in block_reasons.head(20).iterrows():
        records.append({"gap_type": f"block_reason:{row['reason_or_field']}", "affected_count": int(row["count"]), "details": row["example_tickers"]})
    return pd.DataFrame(records, columns=["gap_type", "affected_count", "details"])


def build_schema_gap_report(normalized: pd.DataFrame, source_columns: set[str] | None = None) -> pd.DataFrame:
    source_columns = source_columns or set()
    records = []
    for column in NORMALIZED_COLUMNS:
        blank_count = int(normalized[column].map(_is_missing).sum()) if column in normalized.columns else 0
        source_present = column in source_columns
        if not source_present:
            status = "SOURCE_FIELD_MISSING"
        elif blank_count >= len(normalized):
            status = "FIELD_EMPTY_OR_UNAVAILABLE"
        else:
            status = "AVAILABLE"
        records.append(
            {
                "field_name": column,
                "present_in_normalized_schema": column in normalized.columns,
                "present_in_step25_source": source_present,
                "blank_or_missing_count": blank_count,
                "status": status,
            }
        )
    return pd.DataFrame(records, columns=["field_name", "present_in_normalized_schema", "present_in_step25_source", "blank_or_missing_count", "status"])


def build_shortlists(config: dict[str, Any], rows: pd.DataFrame, coverage: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if rows.empty:
        empty = pd.DataFrame(columns=SHORTLIST_COLUMNS)
        return empty, empty, empty, empty
    merged = rows.merge(coverage[["ticker", "data_coverage_score", "missing_field_count", "source_conflict_count"]], on="ticker", how="left")
    merged["status_severity"] = merged["screening_status"].map(_status_severity)
    merged["recent_trading_value_num"] = merged["recent_trading_value"].map(_to_float).fillna(-1)
    merged["manual_bctc_bool"] = merged["manual_bctc_required"].map(_as_bool)
    merged["review_status"] = merged.apply(_review_status, axis=1)
    merged = merged.sort_values(
        by=["status_severity", "manual_bctc_bool", "missing_field_count", "source_conflict_count", "recent_trading_value_num", "ticker"],
        ascending=[True, False, True, True, False, True],
    ).copy()
    merged["coverage_rank"] = range(1, len(merged) + 1)
    merged["review_priority"] = merged["coverage_rank"]
    merged["manual_review_priority"] = merged["coverage_rank"]
    first_size = int((config.get("limits") or {}).get("first_shortlist_size", 50) or 50)
    queue_size = int((config.get("limits") or {}).get("bctc_priority_queue_size", 100) or 100)
    survivors = merged[merged["screening_status"].eq("WATCHLIST_CANDIDATE")].copy()
    first_pool = survivors if not survivors.empty else merged[merged["status_severity"] <= 3].copy()
    first = first_pool.head(first_size).copy()
    first["review_status"] = "FIRST_REVIEW_SHORTLIST"
    manual_queue = merged[merged["manual_bctc_bool"]].head(queue_size).copy()
    manual_queue["review_status"] = "BCTC_PRIORITY_REVIEW"
    repair = merged[merged["screening_status"].astype(str).str.startswith("BLOCKED_")].sort_values(
        by=["missing_field_count", "data_coverage_score", "ticker"],
        ascending=[False, True, True],
    ).copy()
    repair["review_status"] = "DATA_REPAIR_FIRST"
    return (
        first.reindex(columns=SHORTLIST_COLUMNS),
        manual_queue.reindex(columns=SHORTLIST_COLUMNS),
        survivors.reindex(columns=SHORTLIST_COLUMNS),
        repair.reindex(columns=SHORTLIST_COLUMNS),
    )


def build_sector_summary(rows: pd.DataFrame, coverage: pd.DataFrame, field: str) -> pd.DataFrame:
    output_columns = [
        "sector_or_micro_sector",
        "total_tickers",
        "watch_only_count",
        "manual_review_count",
        "blocked_count",
        "insufficient_data_count",
        "avg_data_coverage_score",
        "common_missing_fields",
        "common_block_reasons",
    ]
    if rows.empty or field not in rows.columns or rows[field].map(_is_missing).all():
        return pd.DataFrame(
            [
                {
                    "sector_or_micro_sector": f"{field}_classification_not_available_in_step25_output",
                    "total_tickers": 0,
                    "watch_only_count": 0,
                    "manual_review_count": 0,
                    "blocked_count": 0,
                    "insufficient_data_count": 0,
                    "avg_data_coverage_score": 0,
                    "common_missing_fields": "[]",
                    "common_block_reasons": "[]",
                }
            ],
            columns=output_columns,
        )
    merged = rows.merge(coverage[["ticker", "data_coverage_score"]], on="ticker", how="left")
    records = []
    for sector, group in merged.groupby(field, dropna=False):
        records.append(
            {
                "sector_or_micro_sector": str(sector or "UNKNOWN"),
                "total_tickers": int(len(group)),
                "watch_only_count": int(group["watchlist_status"].eq("WATCH_ONLY").sum()),
                "manual_review_count": int(group["manual_review_required"].map(_as_bool).sum()),
                "blocked_count": int(group["screening_status"].astype(str).str.startswith("BLOCKED_").sum()),
                "insufficient_data_count": int(group["watchlist_status"].eq("INSUFFICIENT_DATA").sum()),
                "avg_data_coverage_score": round(float(group["data_coverage_score"].fillna(0).mean()), 4),
                "common_missing_fields": _json_list(_top_list_values(group["missing_fields"], 5)),
                "common_block_reasons": _json_list(_top_list_values(group["block_reasons"], 5)),
            }
        )
    return pd.DataFrame(records, columns=output_columns)


def build_sector_data_gap_summary(rows: pd.DataFrame, coverage: pd.DataFrame) -> pd.DataFrame:
    if rows.empty or (("sector" not in rows.columns or rows["sector"].map(_is_missing).all()) and ("micro_sector" not in rows.columns or rows["micro_sector"].map(_is_missing).all())):
        return pd.DataFrame(
            [
                {
                    "sector_or_micro_sector": "sector_classification_not_available_in_step25_output",
                    "total_tickers": int(len(rows)),
                    "avg_data_coverage_score": round(float(coverage["data_coverage_score"].mean()), 4) if not coverage.empty else 0,
                    "common_missing_fields": "[]",
                    "common_block_reasons": "[]",
                }
            ],
            columns=["sector_or_micro_sector", "total_tickers", "avg_data_coverage_score", "common_missing_fields", "common_block_reasons"],
        )
    field = "micro_sector" if "micro_sector" in rows.columns and not rows["micro_sector"].map(_is_missing).all() else "sector"
    summary = build_sector_summary(rows, coverage, field)
    return summary.reindex(columns=["sector_or_micro_sector", "total_tickers", "avg_data_coverage_score", "common_missing_fields", "common_block_reasons"])


def build_summary(
    *,
    config: dict[str, Any],
    artifacts: Step26Artifacts,
    normalized: pd.DataFrame,
    first_shortlist: pd.DataFrame,
    manual_queue: pd.DataFrame,
    repair_queue: pd.DataFrame,
    status_distribution: pd.DataFrame,
    block_reasons: pd.DataFrame,
    missing_fields: pd.DataFrame,
    forbidden_hits: list[str],
    core_outputs_modified: bool,
) -> dict[str, Any]:
    confidence = config.get("source_confidence") or {}
    if artifacts.step25_rows_path is None:
        final_decision = "BLOCKED_NO_STEP25_ROW_ARTIFACT"
    elif forbidden_hits or core_outputs_modified:
        final_decision = "BLOCKED_GUARDRAIL_VIOLATION"
    elif len(first_shortlist) >= 1:
        final_decision = "PASS_FULL_UNIVERSE_AUDIT_WITH_SHORTLIST"
    else:
        final_decision = "PASS_FULL_UNIVERSE_AUDIT_WITH_DATA_GAPS"
    if final_decision not in FINAL_DECISIONS:
        raise ValueError(f"Invalid STEP26 final decision: {final_decision}")
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "mode": MODE,
        "step25_rows_path": str(artifacts.step25_rows_path or ""),
        "total_universe_rows_read": int(len(normalized)),
        "expected_universe_size": int((config.get("limits") or {}).get("expected_universe_size", 1743) or 1743),
        "first_review_shortlist_count": int(len(first_shortlist)),
        "manual_bctc_priority_queue_count": int(len(manual_queue)),
        "surviving_primary_only_candidate_count": int(normalized["screening_status"].eq("WATCHLIST_CANDIDATE").sum()) if not normalized.empty else 0,
        "data_repair_priority_count": int(len(repair_queue)),
        "status_distribution": _distribution_to_dict(status_distribution, "screening_status"),
        "block_reason_top_10": _top_records(block_reasons, 10),
        "missing_fields_top_10": _top_records(missing_fields, 10),
        "market_source_confidence": confidence.get("market_source_confidence", "PROVISIONAL_PRIMARY_ONLY"),
        "finance_source_confidence_default": confidence.get("finance_source_confidence_default", "PROVISIONAL_LOW"),
        "crosscheck_status": confidence.get("crosscheck_status", "NOT_AVAILABLE"),
        "verification_status": confidence.get("verification_status", "NEEDS_MANUAL_BCTC_REVIEW"),
        "missing_input_files": artifacts.missing_input_files,
        "forbidden_terms_found": forbidden_hits,
        "core_outputs_modified": bool(core_outputs_modified),
        "final_decision": final_decision,
    }


def build_run_manifest(
    *,
    config: dict[str, Any],
    config_path: Path,
    output_dir: Path,
    artifacts: Step26Artifacts,
    command_used: str,
    allow_partial: bool,
    core_outputs_modified: bool,
) -> dict[str, Any]:
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "commit_hash": _git_commit_hash(),
        "command_used": command_used,
        "config_path": str(config_path),
        "output_dir": str(output_dir),
        "allow_partial": bool(allow_partial),
        "network_usage_if_known": "none",
        "core_outputs_modified": bool(core_outputs_modified),
        "previous_step_outputs_mutated": bool(core_outputs_modified),
        "discovered_artifacts": {
            "step25_rows_path": str(artifacts.step25_rows_path or ""),
            "watchlist_path": str(artifacts.watchlist_path or ""),
            "manual_queue_path": str(artifacts.manual_queue_path or ""),
            "blocked_path": str(artifacts.blocked_path or ""),
            "summary_path": str(artifacts.summary_path or ""),
            "manifest_path": str(artifacts.manifest_path or ""),
        },
        "missing_input_files": artifacts.missing_input_files,
    }


def write_outputs(
    *,
    output_dir: Path,
    normalized: pd.DataFrame,
    status_distribution: pd.DataFrame,
    source_distribution: pd.DataFrame,
    manual_distribution: pd.DataFrame,
    block_reasons: pd.DataFrame,
    missing_fields: pd.DataFrame,
    reject_reasons: pd.DataFrame,
    coverage: pd.DataFrame,
    data_gap: pd.DataFrame,
    schema_gap: pd.DataFrame,
    first_shortlist: pd.DataFrame,
    manual_queue: pd.DataFrame,
    survivors: pd.DataFrame,
    repair_queue: pd.DataFrame,
    sector_distribution: pd.DataFrame,
    micro_distribution: pd.DataFrame,
    sector_gap: pd.DataFrame,
    summary: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized.to_csv(output_dir / "normalized_universe_rows.csv", index=False)
    status_distribution.to_csv(output_dir / "status_distribution.csv", index=False)
    source_distribution.to_csv(output_dir / "source_confidence_distribution.csv", index=False)
    manual_distribution.to_csv(output_dir / "manual_review_distribution.csv", index=False)
    block_reasons.to_csv(output_dir / "block_reason_distribution.csv", index=False)
    missing_fields.to_csv(output_dir / "missing_field_distribution.csv", index=False)
    reject_reasons.to_csv(output_dir / "reject_reason_distribution.csv", index=False)
    coverage.to_csv(output_dir / "data_coverage_by_ticker.csv", index=False)
    data_gap.to_csv(output_dir / "data_gap_report.csv", index=False)
    schema_gap.to_csv(output_dir / "schema_gap_report.csv", index=False)
    first_shortlist.to_csv(output_dir / "first_review_shortlist_50.csv", index=False)
    manual_queue.to_csv(output_dir / "manual_bctc_priority_queue_100.csv", index=False)
    survivors.to_csv(output_dir / "surviving_primary_only_candidates.csv", index=False)
    repair_queue.to_csv(output_dir / "data_repair_priority_queue.csv", index=False)
    sector_distribution.to_csv(output_dir / "sector_candidate_distribution.csv", index=False)
    micro_distribution.to_csv(output_dir / "micro_sector_candidate_distribution.csv", index=False)
    sector_gap.to_csv(output_dir / "sector_data_gap_summary.csv", index=False)
    _write_json(output_dir / "step26_audit_summary.json", summary)
    _write_json(output_dir / "run_manifest.json", manifest)
    (output_dir / "step26_full_universe_audit_report.md").write_text(build_markdown_report(summary, status_distribution, block_reasons, missing_fields, first_shortlist, manual_queue, data_gap, sector_distribution), encoding="utf-8")


def build_markdown_report(
    summary: dict[str, Any],
    status_distribution: pd.DataFrame,
    block_reasons: pd.DataFrame,
    missing_fields: pd.DataFrame,
    first_shortlist: pd.DataFrame,
    manual_queue: pd.DataFrame,
    data_gap: pd.DataFrame,
    sector_distribution: pd.DataFrame,
) -> str:
    lines = [
        "# STEP26 Full-Universe Output Audit",
        "",
        "## 1. Scope",
        "This report is not investment advice.",
        "This report does not contain buy/sell/hold signals.",
        "This report is a provisional evidence audit based on primary-only data.",
        "Official BCTC/manual review is required before deeper analysis.",
        "",
        "## 2. Input Artifacts Found",
        f"- step25_rows_path: {summary.get('step25_rows_path', '')}",
        f"- total_universe_rows_read: {summary.get('total_universe_rows_read', 0)}",
        "",
        "## 3. Universe Coverage",
        f"- first_review_shortlist_count: {summary.get('first_review_shortlist_count', 0)}",
        f"- manual_bctc_priority_queue_count: {summary.get('manual_bctc_priority_queue_count', 0)}",
        f"- data_repair_priority_count: {summary.get('data_repair_priority_count', 0)}",
        "",
        "## 4. Status Distribution",
        _markdown_table(status_distribution[status_distribution["field_name"].eq("screening_status")].head(20), ["field_value", "count", "percentage_of_universe"]),
        "",
        "## 5. Block / Reject Reasons",
        _markdown_table(block_reasons.head(10), ["reason_or_field", "count", "percentage_of_universe"]),
        "",
        "## 6. Data Coverage Problems",
        _markdown_table(data_gap.head(20), ["gap_type", "affected_count"]),
        "",
        "## 7. First Review Shortlist Method",
        "Shortlist priority uses technical coverage, non-blocked status, recent market data, liquidity evidence, fewer missing fields, and manual BCTC requirement.",
        "",
        "## 8. Manual BCTC Priority Queue",
        _markdown_table(manual_queue.head(20), ["ticker", "screening_status", "review_status", "data_coverage_score", "missing_field_count"]),
        "",
        "## 9. Sector / Micro-Sector Observations",
        _markdown_table(sector_distribution.head(20), ["sector_or_micro_sector", "total_tickers", "avg_data_coverage_score"]),
        "",
        "## 10. Guardrail Check",
        f"- forbidden_terms_found: {summary.get('forbidden_terms_found', [])}",
        f"- crosscheck_status: {summary.get('crosscheck_status', '')}",
        f"- verification_status: {summary.get('verification_status', '')}",
        "",
        "## 11. What This Report Does NOT Mean",
        "This audit does not rank attractiveness, assign valuation conclusions, or provide trading guidance.",
        "",
        "## 12. Recommended Next Actions",
        "- Review the first manual BCTC queue.",
        "- Repair missing market data before deeper filtering.",
        "- Preserve provisional confidence labels until source verification improves.",
    ]
    return "\n".join(lines) + "\n"


def scan_forbidden_terms(output_dir: Path) -> list[str]:
    hits: list[str] = []
    if not output_dir.exists():
        return hits
    for path in sorted(output_dir.glob("*")):
        if path.suffix.lower() not in {".csv", ".json", ".md", ".txt"}:
            continue
        text = _scan_text(path)
        for line_no, line in enumerate(text.splitlines(), start=1):
            lower = line.lower().strip()
            if lower in ALLOWED_SAFETY_LINES:
                continue
            for term in FORBIDDEN_TERMS:
                if _term_in_text(term, lower):
                    hits.append(f"{path.name}:{line_no}:{term}")
    return hits


def parse_listish(value: Any) -> list[str]:
    if _is_missing(value):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if not _is_missing(item)]
    text = str(value).strip()
    if text.startswith(("[", "(", "{")):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(text)
            except (SyntaxError, ValueError):
                parsed = None
        if isinstance(parsed, (list, tuple, set)):
            return [str(item) for item in parsed if not _is_missing(item)]
        if parsed is not None:
            return []
        text = text.strip("[](){}")
    return [part.strip() for part in re.split(r"[;,]", text) if part.strip()]


def _find_named_artifact(roots: list[Path], names: list[str], preferred_parent: Path | None = None) -> Path | None:
    if preferred_parent is not None:
        for name in names:
            path = preferred_parent / name
            if path.exists():
                return path
    for root in roots:
        if not root.exists():
            continue
        for name in names:
            direct = root / name
            if direct.exists():
                return direct
        for path in root.rglob("*"):
            if path.name in names:
                return path
    return None


def _search_artifact(required_tokens: list[str], suffix: str) -> Path | None:
    root = Path("data/reports")
    if not root.exists():
        return None
    for path in sorted(root.rglob(f"*{suffix}")):
        lower = str(path).lower()
        if all(token.lower() in lower for token in required_tokens) and ("rows" in path.name.lower() or "screening" in path.name.lower()):
            return path
    return None


def _screening_to_watchlist_status(status: Any) -> str:
    text = str(status)
    if text == "WATCHLIST_CANDIDATE":
        return "WATCH_ONLY"
    if text.startswith("BLOCKED_"):
        return "REJECTED"
    if text in {"MANUAL_REVIEW", "INSUFFICIENT_DATA", "FAILED_FETCH"}:
        return text
    return "INSUFFICIENT_DATA" if _is_missing(text) else text


def _review_status(row: pd.Series) -> str:
    status = str(row.get("screening_status", ""))
    if status == "WATCHLIST_CANDIDATE":
        return "FIRST_REVIEW_SHORTLIST"
    if status in {"MANUAL_REVIEW", "INSUFFICIENT_DATA"}:
        return status
    if status.startswith("BLOCKED_"):
        return "DATA_REPAIR_FIRST"
    return "MANUAL_REVIEW_LATER"


def _status_severity(status: Any) -> int:
    text = str(status)
    order = {
        "WATCHLIST_CANDIDATE": 0,
        "WATCH_ONLY": 1,
        "MANUAL_REVIEW": 2,
        "INSUFFICIENT_DATA": 3,
        "BLOCKED_TOO_ILLIQUID": 4,
        "BLOCKED_STALE_MARKET_DATA": 5,
        "BLOCKED_INSUFFICIENT_MARKET_DATA": 6,
        "BLOCKED_MISSING_MINIMUM_FINANCE": 7,
        "FAILED_FETCH": 8,
    }
    return order.get(text, 9)


def _coverage_status(score: int, market_available: bool, missing_count: int) -> str:
    if not market_available:
        return "DATA_GAP"
    if score >= 70 and missing_count <= 2:
        return "PROVISIONAL_CANDIDATE"
    if score >= 45:
        return "BCTC_REVIEW_REQUIRED"
    return "INSUFFICIENT_DATA"


def _top_list_values(series: pd.Series, limit: int) -> list[str]:
    counts: dict[str, int] = {}
    for value in series.astype(str):
        for item in parse_listish(value):
            counts[item] = counts.get(item, 0) + 1
    return [key for key, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def _distribution_to_dict(distribution: pd.DataFrame, field_name: str) -> dict[str, int]:
    if distribution.empty:
        return {}
    subset = distribution[distribution["field_name"].eq(field_name)]
    return {str(row["field_value"]): int(row["count"]) for _, row in subset.iterrows()}


def _top_records(frame: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    records = []
    for _, row in frame.head(limit).iterrows():
        records.append({"reason_or_field": row.get("reason_or_field", ""), "count": int(row.get("count", 0))})
    return records


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


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    if frame.empty:
        return "INSUFFICIENT_DATA"
    available = [column for column in columns if column in frame.columns]
    lines = ["| " + " | ".join(available) + " |", "| " + " | ".join(["---"] * len(available)) + " |"]
    for _, row in frame.reindex(columns=available).iterrows():
        values = [str(row.get(column, "UNKNOWN")).replace("|", "/").replace("\n", " ") or "UNKNOWN" for column in available]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


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
