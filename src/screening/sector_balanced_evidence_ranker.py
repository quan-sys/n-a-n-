"""Sector-balanced evidence workload ranking.

This module changes evidence queue allocation order only. It preserves the raw
provisional evidence score and does not create an investment recommendation.
"""

from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.ingestion.evidence_pack_policy import assign_evidence_stage
from src.ingestion.legacy_structured_finance_importer import FORBIDDEN_BIAS_FIELDS


FORBIDDEN_BALANCED_FIELDS = FORBIDDEN_BIAS_FIELDS | {
    "fair_value",
    "margin_of_safety",
    "target_price",
    "upside",
    "watch_candidate",
    "investment_score",
}

BALANCED_RANKING_COLUMNS = [
    "balanced_rank",
    "raw_rank",
    "ticker",
    "exchange",
    "sector_raw",
    "sector_bucket",
    "firm_type",
    "raw_evidence_priority_score",
    "balanced_evidence_priority_score",
    "liquidity_score",
    "data_completeness_score",
    "finance_sanity_score",
    "source_coverage_score",
    "market_crosscheck_status",
    "finance_crosscheck_status",
    "balance_action",
    "evidence_stage",
    "manual_review_required",
    "reason",
]

DIAGNOSTIC_COLUMNS = [
    "stage_cap",
    "ticker",
    "raw_rank",
    "balanced_rank",
    "sector_bucket",
    "firm_type",
    "balance_action",
    "diagnostic_reason",
]


def load_balance_policy(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def infer_firm_type(row: dict[str, Any] | pd.Series, policy: dict[str, Any]) -> str:
    config = policy.get("balance_policy", policy)
    rules = config.get("firm_type_rules", {})
    haystack = _normalize_text(" ".join(str(row.get(column, "")) for column in ["sector_raw", "industry_raw", "company_name", "ticker"]))
    default_type = (config.get("fallback") or {}).get("unknown_firm_type", "unknown")
    fallback_default = ""
    for firm_type, spec in rules.items():
        if spec.get("default"):
            fallback_default = firm_type
            continue
        for keyword in spec.get("keywords", []):
            if _normalize_text(keyword) in haystack:
                return firm_type
    return fallback_default or default_type


def assign_sector_bucket(row: dict[str, Any] | pd.Series, policy: dict[str, Any]) -> str:
    config = policy.get("balance_policy", policy)
    unknown = (config.get("fallback") or {}).get("unknown_sector_bucket", "UNKNOWN")
    sector = str(row.get("sector_raw", "") or "").strip()
    if not sector:
        return unknown
    for separator in ["/", ">", "|"]:
        if separator in sector:
            return sector.split(separator, 1)[0].strip() or unknown
    return sector or unknown


def apply_stage_caps(ranking_df: pd.DataFrame, policy: dict[str, Any]) -> pd.DataFrame:
    return create_balanced_ranking(ranking_df, pd.DataFrame(), pd.DataFrame(), policy)


def create_balanced_ranking(
    raw_ranking_df: pd.DataFrame,
    market_crosscheck_df: pd.DataFrame,
    finance_crosscheck_df: pd.DataFrame,
    policy: dict[str, Any],
) -> pd.DataFrame:
    raw = _prepare_raw_ranking(raw_ranking_df, policy)
    if raw.empty:
        return pd.DataFrame(columns=BALANCED_RANKING_COLUMNS)
    config = policy.get("balance_policy", policy)
    if not config.get("enabled", True):
        out = raw.copy()
        out["balanced_rank"] = range(1, len(out) + 1)
        out["balance_action"] = "KEPT"
        return _finalize(out, market_crosscheck_df, finance_crosscheck_df)

    caps = config.get("top_stage_caps", {})
    stage_limits = [
        ("stage_4_deep_dive_shortlist", caps.get("stage_4_deep_dive_shortlist", {"max_total": 10})),
        ("stage_3_final_watchlist", caps.get("stage_3_final_watchlist", {"max_total": 50})),
        ("stage_2_evidence_candidates", caps.get("stage_2_evidence_candidates", {"max_total": 200})),
    ]
    remaining = raw.to_dict("records")
    selected: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    demotion_reason: dict[str, str] = {}

    for stage_name, cap in stage_limits:
        target_total = int(cap.get("max_total", len(raw)) or len(raw))
        while len(selected) < min(target_total, len(raw)) and remaining:
            pick_index = _first_candidate_within_caps(selected, remaining, cap, target_total, demotion_reason)
            if pick_index is None:
                pick_index = 0
                remaining[pick_index]["_manual_balance_review"] = True
            item = remaining.pop(pick_index)
            item["_stage_cap_selected_under"] = stage_name
            selected.append(item)
            diagnostics.append(_diagnostic(stage_name, item, len(selected), demotion_reason.get(item["ticker"], "")))

    selected_tickers = {item["ticker"] for item in selected}
    selected.extend(item for item in raw.to_dict("records") if item["ticker"] not in selected_tickers)
    balanced = pd.DataFrame(selected)
    balanced["balanced_rank"] = range(1, len(balanced) + 1)
    balanced["balance_action"] = balanced.apply(lambda row: _balance_action(row, demotion_reason), axis=1)
    balanced["_diagnostic_reason"] = balanced["ticker"].map(demotion_reason).fillna("")
    out = _finalize(balanced, market_crosscheck_df, finance_crosscheck_df)
    out.attrs["diagnostics"] = pd.DataFrame(diagnostics, columns=DIAGNOSTIC_COLUMNS)
    return out


def build_sector_balance_diagnostics(balanced: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if balanced.empty:
        return pd.DataFrame(columns=DIAGNOSTIC_COLUMNS)
    for _, row in balanced.iterrows():
        if row.get("balance_action") == "KEPT":
            continue
        rows.append(
            {
                "stage_cap": row.get("evidence_stage", ""),
                "ticker": row.get("ticker", ""),
                "raw_rank": row.get("raw_rank", ""),
                "balanced_rank": row.get("balanced_rank", ""),
                "sector_bucket": row.get("sector_bucket", ""),
                "firm_type": row.get("firm_type", ""),
                "balance_action": row.get("balance_action", ""),
                "diagnostic_reason": row.get("reason", ""),
            }
        )
    return pd.DataFrame(rows, columns=DIAGNOSTIC_COLUMNS)


def build_sector_balance_summary(raw_ranking: pd.DataFrame, balanced: pd.DataFrame, policy: dict[str, Any]) -> str:
    old_top10 = _concentration_summary(_prepare_raw_ranking(raw_ranking, policy).head(10))
    new_top10 = _concentration_summary(balanced.head(10))
    action_counts = Counter(balanced["balance_action"].astype(str)) if not balanced.empty else {}
    lines = [
        "# Sector Balance Summary 02",
        "",
        f"- generated_at: {datetime.now(UTC).replace(microsecond=0).isoformat()}",
        "- purpose: evidence workload allocation only, not investment ranking",
        "",
        "## Old Top 10 Concentration",
        *[f"- {key}: {value}" for key, value in old_top10.items()],
        "",
        "## New Top 10 Concentration",
        *[f"- {key}: {value}" for key, value in new_top10.items()],
        "",
        "## Balance Actions",
    ]
    for action, count in sorted(action_counts.items()):
        lines.append(f"- {action}: {int(count)}")
    lines.extend(
        [
            "",
            "## Safety",
            "- Raw rank and raw_evidence_priority_score are preserved.",
            "- Balanced rank only controls staged official evidence workload.",
            "- No buy/sell/target/fair_value/MoS fields are created.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_queue_before_after_comparison(
    old_ranking: pd.DataFrame,
    new_ranking: pd.DataFrame,
    old_assignments: pd.DataFrame,
    new_assignments: pd.DataFrame,
    old_queue: pd.DataFrame,
    new_queue: pd.DataFrame,
    old_manual: pd.DataFrame,
    new_manual: pd.DataFrame,
    old_run_summary: str = "",
    new_run_summary: str = "",
    policy: dict[str, Any] | None = None,
) -> str:
    policy = policy or {}
    old_prepared = _prepare_raw_ranking(old_ranking, policy) if not old_ranking.empty else pd.DataFrame()
    new_prepared = new_ranking.copy()
    lines = [
        "# Queue Before/After Comparison 02",
        "",
        "## Top 10 Firm-Type Concentration",
        "- old: " + _format_counter(old_prepared.head(10).get("firm_type", pd.Series(dtype=str))),
        "- new: " + _format_counter(new_prepared.head(10).get("firm_type", pd.Series(dtype=str))),
        "",
        "## Top 10 Sector Concentration",
        "- old: " + _format_counter(old_prepared.head(10).get("sector_bucket", pd.Series(dtype=str))),
        "- new: " + _format_counter(new_prepared.head(10).get("sector_bucket", pd.Series(dtype=str))),
        "",
        "## Stage Distribution",
        "- old: " + _format_counter(old_assignments.get("stage", pd.Series(dtype=str))),
        "- new: " + _format_counter(new_assignments.get("stage", pd.Series(dtype=str))),
        "",
        "## Queue Rows",
        f"- old_evidence_queue_rows: {len(old_queue)}",
        f"- new_evidence_queue_rows: {len(new_queue)}",
        f"- old_manual_seed_request_rows: {len(old_manual)}",
        f"- new_manual_seed_request_rows: {len(new_manual)}",
        "",
        "## Manual Workload",
        "- old: " + _extract_workload(old_run_summary),
        "- new: " + _extract_workload(new_run_summary),
        "",
        "## Safety",
        "- Both queues are planned official evidence slots only.",
        "- No official BCTC/BCTN values were parsed or verified here.",
    ]
    return "\n".join(lines) + "\n"


def _prepare_raw_ranking(raw_ranking_df: pd.DataFrame, policy: dict[str, Any]) -> pd.DataFrame:
    raw = _strip_forbidden(raw_ranking_df)
    if raw.empty:
        return pd.DataFrame()
    raw = raw.copy()
    if "rank" not in raw.columns:
        raw["rank"] = range(1, len(raw) + 1)
    rank_values = pd.to_numeric(raw["rank"], errors="coerce")
    fallback_rank = pd.Series(range(1, len(raw) + 1), index=raw.index)
    raw["raw_rank"] = rank_values.where(rank_values.notna(), fallback_rank).astype(int)
    raw["raw_evidence_priority_score"] = pd.to_numeric(raw.get("evidence_priority_score", 0), errors="coerce").fillna(0)
    raw["sector_bucket"] = raw.apply(lambda row: assign_sector_bucket(row, policy), axis=1)
    raw["firm_type"] = raw.apply(lambda row: infer_firm_type(row, policy), axis=1)
    raw = raw.sort_values(["raw_rank", "ticker"], ascending=[True, True]).reset_index(drop=True)
    return raw


def _first_candidate_within_caps(
    selected: list[dict[str, Any]],
    remaining: list[dict[str, Any]],
    cap: dict[str, Any],
    target_total: int,
    demotion_reason: dict[str, str],
) -> int | None:
    max_per_sector = int(cap.get("max_per_sector", target_total) or target_total)
    max_per_firm_type = int(cap.get("max_per_firm_type", target_total) or target_total)
    sector_counts = Counter(item["sector_bucket"] for item in selected[:target_total])
    firm_counts = Counter(item["firm_type"] for item in selected[:target_total])
    for index, item in enumerate(remaining):
        sector_over = sector_counts[item["sector_bucket"]] >= max_per_sector
        firm_type = item["firm_type"]
        firm_over = firm_type != "non_financial" and firm_counts[firm_type] >= max_per_firm_type
        if sector_over:
            demotion_reason.setdefault(item["ticker"], "DEMOTED_SECTOR_CAP")
        if firm_over:
            demotion_reason.setdefault(item["ticker"], "DEMOTED_FIRM_TYPE_CAP")
        if not sector_over and not firm_over:
            return index
    return None


def _finalize(balanced: pd.DataFrame, market_crosscheck: pd.DataFrame, finance_crosscheck: pd.DataFrame) -> pd.DataFrame:
    market_status = _market_status_by_ticker(market_crosscheck)
    finance_status = _finance_status_by_ticker(finance_crosscheck)
    balanced = balanced.copy()
    balanced["balanced_evidence_priority_score"] = balanced["raw_evidence_priority_score"]
    balanced["market_crosscheck_status"] = balanced["ticker"].map(market_status).fillna("NOT_CHECKED")
    balanced["finance_crosscheck_status"] = balanced["ticker"].map(finance_status).fillna("ONE_SOURCE_ONLY")
    balanced["evidence_stage"] = balanced["balanced_rank"].apply(lambda rank: assign_evidence_stage({"rank": rank}))
    balanced["manual_review_required"] = balanced.apply(_manual_review_required, axis=1)
    balanced["reason"] = balanced.apply(_balanced_reason, axis=1)
    for column in [
        "exchange",
        "sector_raw",
        "liquidity_score",
        "data_completeness_score",
        "finance_sanity_score",
        "source_coverage_score",
    ]:
        if column not in balanced.columns:
            balanced[column] = ""
    return balanced[BALANCED_RANKING_COLUMNS]


def _balance_action(row: pd.Series, demotion_reason: dict[str, str]) -> str:
    if _is_true(row.get("_manual_balance_review", False)):
        return "HELD_FOR_MANUAL_REVIEW"
    if int(row["balanced_rank"]) < int(row["raw_rank"]):
        return "PROMOTED_FOR_DIVERSITY"
    if int(row["balanced_rank"]) > int(row["raw_rank"]):
        return demotion_reason.get(row["ticker"], "DEMOTED_SECTOR_CAP")
    return "KEPT"


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _diagnostic(stage_name: str, item: dict[str, Any], balanced_rank: int, reason: str) -> dict[str, Any]:
    return {
        "stage_cap": stage_name,
        "ticker": item.get("ticker", ""),
        "raw_rank": item.get("raw_rank", ""),
        "balanced_rank": balanced_rank,
        "sector_bucket": item.get("sector_bucket", ""),
        "firm_type": item.get("firm_type", ""),
        "balance_action": "KEPT" if not reason else reason,
        "diagnostic_reason": reason,
    }


def _market_status_by_ticker(frame: pd.DataFrame) -> dict[str, str]:
    if not isinstance(frame, pd.DataFrame) or frame.empty or "ticker" not in frame.columns:
        return {}
    out: dict[str, str] = {}
    for _, row in frame.iterrows():
        ticker = str(row.get("ticker", "")).upper()
        if ticker:
            out[ticker] = str(row.get("price_crosscheck_status") or "")
    return out


def _finance_status_by_ticker(frame: pd.DataFrame) -> dict[str, str]:
    if not isinstance(frame, pd.DataFrame) or frame.empty or "ticker" not in frame.columns:
        return {}
    priority = {"SOURCE_CONFLICT": 4, "MISSING_VALUE_IN_SOURCES": 3, "ONE_SOURCE_ONLY": 2, "MULTI_SOURCE_AGREES": 1}
    out: dict[str, str] = {}
    status_col = "finance_crosscheck_status" if "finance_crosscheck_status" in frame.columns else "crosscheck_status"
    for ticker, group in frame.groupby(frame["ticker"].astype(str).str.upper()):
        statuses = [str(value) for value in group.get(status_col, [])]
        out[ticker] = max(statuses, key=lambda status: priority.get(status, 0)) if statuses else "ONE_SOURCE_ONLY"
    return out


def _manual_review_required(row: pd.Series) -> bool:
    raw_flag = str(row.get("manual_review_required", "")).lower() in {"true", "1", "yes"}
    market_status = str(row.get("market_crosscheck_status", ""))
    finance_status = str(row.get("finance_crosscheck_status", ""))
    action = str(row.get("balance_action", ""))
    return raw_flag or market_status in {"MAJOR_DIFF", "PUBLIC_FILE_MISSING", "LEGACY_MARKET_MISSING", "FETCH_FAILED"} or finance_status != "MULTI_SOURCE_AGREES" or action == "HELD_FOR_MANUAL_REVIEW"


def _balanced_reason(row: pd.Series) -> str:
    return (
        "Balanced evidence workload allocation only. "
        f"raw_rank={row.get('raw_rank')}; balance_action={row.get('balance_action')}; "
        f"market_crosscheck={row.get('market_crosscheck_status')}; "
        f"finance_crosscheck={row.get('finance_crosscheck_status')}."
    )


def _strip_forbidden(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        return pd.DataFrame()
    forbidden = [column for column in frame.columns if str(column).strip().lower() in FORBIDDEN_BALANCED_FIELDS]
    return frame.drop(columns=forbidden, errors="ignore").copy()


def _normalize_text(value: Any) -> str:
    text = str(value or "").lower()
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _concentration_summary(frame: pd.DataFrame) -> dict[str, str]:
    if frame.empty:
        return {"firm_type": "none", "sector_bucket": "none"}
    return {
        "firm_type": _format_counter(frame.get("firm_type", pd.Series(dtype=str))),
        "sector_bucket": _format_counter(frame.get("sector_bucket", pd.Series(dtype=str))),
    }


def _format_counter(series: pd.Series) -> str:
    if series is None or series.empty:
        return "none"
    counts = Counter(series.astype(str))
    return "; ".join(f"{key}={value}" for key, value in counts.most_common()) or "none"


def _extract_workload(summary: str) -> str:
    values = []
    for line in str(summary or "").splitlines():
        if "assignment_estimated_files_min" in line or "assignment_estimated_files_max" in line or "evidence_collection_queue_rows" in line:
            values.append(line.strip("- ").strip())
    return "; ".join(values) if values else "unavailable"
