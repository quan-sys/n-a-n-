"""Staged official evidence pack policy for BCTC/BCTN collection.

This module plans official document evidence workload only. It does not fetch,
parse, infer, or score financial values.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml


DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "evidence_pack_policy.yaml"

STAGE_0 = "stage_0_full_universe"
STAGE_1 = "stage_1_provisional_shortlist"
STAGE_2 = "stage_2_evidence_candidates"
STAGE_3 = "stage_3_final_watchlist"
STAGE_4 = "stage_4_deep_dive_shortlist"
STAGE_5 = "stage_5_full_historical_research"

DEFAULT_STAGE_ORDER = [STAGE_0, STAGE_1, STAGE_2, STAGE_3, STAGE_4, STAGE_5]
RANK_COLUMNS = ["rank", "balanced_rank", "rank_position", "ranking", "screen_rank", "watchlist_rank"]
RANK_SCORE_COLUMNS = ["rank_score", "score", "screen_score", "watchlist_score"]

CANDIDATE_STAGE_ASSIGNMENT_COLUMNS = [
    "ticker",
    "input_rank",
    "rank_source",
    "stage",
    "stage_assignment_status",
    "assignment_reason",
    "official_files_per_ticker_min",
    "official_files_per_ticker_max",
    "target_max_tickers_for_stage",
    "template_only",
    "manual_review_required",
    "no_financial_claim",
]

EVIDENCE_COLLECTION_QUEUE_COLUMNS = [
    "ticker",
    "stage",
    "document_priority",
    "document_requirement",
    "period_target",
    "period_type_target",
    "preferred_document_category",
    "preferred_source_tier",
    "max_files_allowed",
    "required",
    "manual_review_required",
    "reason",
]

DOCUMENT_DISCOVERY_PLAN_COLUMNS = [
    "ticker",
    "stage",
    "document_priority",
    "discovery_mode",
    "preferred_source_tiers",
    "force_download",
    "plan_status",
    "reason",
]

MANUAL_SEED_REQUEST_COLUMNS = [
    "ticker",
    "stage",
    "needed_document",
    "where_to_get_it",
    "suggested_category",
    "document_priority",
    "reason",
]

EVIDENCE_PACK_STATUS_COLUMNS = [
    "ticker",
    "stage",
    "required_slots",
    "slots_filled",
    "slots_missing",
    "latest_bctc_available",
    "latest_audited_annual_fs_available",
    "latest_bctn_available",
    "same_period_previous_year_available",
    "three_year_history_available",
    "evidence_pack_status",
    "manual_review_required",
    "next_action",
]

EVIDENCE_WORKLOAD_BUDGET_COLUMNS = [
    "stage",
    "target_tickers",
    "files_per_ticker_min",
    "files_per_ticker_max",
    "estimated_files_min",
    "estimated_files_max",
    "manual_minutes_per_file_assumption",
    "manual_hours_min",
    "manual_hours_max",
    "paid_data_recommended",
]

SCOPE_VALIDATION_COLUMNS = [
    "issue_code",
    "ticker",
    "stage",
    "requested_files_per_ticker",
    "stage_files_per_ticker_max",
    "message",
]

FORBIDDEN_OUTPUT_TERMS = ["buy", "sell", "target_price", "target price", "recommendation"]


def load_evidence_pack_policy(path: str | Path | None = None) -> dict[str, Any]:
    policy_path = Path(path or DEFAULT_POLICY_PATH)
    with policy_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    _validate_policy_shape(data)
    return data


def assign_evidence_stage(ticker_row: dict[str, Any] | pd.Series) -> str:
    explicit_stage = str(_get(ticker_row, "stage", "") or _get(ticker_row, "evidence_stage", "")).strip()
    if explicit_stage in DEFAULT_STAGE_ORDER:
        return explicit_stage
    rank_value = _rank_from_row(ticker_row)
    if rank_value is None:
        return STAGE_0
    if rank_value <= 10:
        return STAGE_4
    if rank_value <= 50:
        return STAGE_3
    if rank_value <= 200:
        return STAGE_2
    if rank_value <= 500:
        return STAGE_1
    return STAGE_0


def required_documents_for_stage(stage: str, policy: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    policy = policy or load_evidence_pack_policy()
    order = stage_order(policy)
    if stage not in order:
        raise ValueError(f"Unknown evidence stage: {stage}")
    stage_index = order.index(stage)
    documents = []
    for priority, spec in policy.get("document_priorities", {}).items():
        required_from = str(spec.get("required_from_stage", ""))
        if required_from in order and order.index(required_from) <= stage_index:
            documents.append(
                {
                    "document_priority": priority,
                    "document_requirement": spec.get("document_requirement", priority),
                    "period_target": spec.get("period_target", ""),
                    "period_type_target": spec.get("period_type_target", ""),
                    "preferred_document_category": spec.get("preferred_document_category", ""),
                    "max_files_allowed": int(spec.get("max_files_per_ticker", 1) or 1),
                    "required_from_stage": required_from,
                    "required": True,
                }
            )
    return documents


def estimate_document_workload(stage_assignments: pd.DataFrame | list[dict[str, Any]], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or load_evidence_pack_policy()
    frame = _to_frame(stage_assignments)
    by_stage: dict[str, dict[str, int]] = {}
    total_min = 0
    total_max = 0
    for stage in stage_order(policy):
        spec = policy["stages"][stage]
        count = int(frame["stage"].astype(str).eq(stage).sum()) if not frame.empty and "stage" in frame.columns else 0
        files_min = int(spec.get("official_files_per_ticker_min", 0) or 0)
        files_max = int(spec.get("official_files_per_ticker_max", 0) or 0)
        stage_min = count * files_min
        stage_max = count * files_max
        total_min += stage_min
        total_max += stage_max
        by_stage[stage] = {
            "ticker_count": count,
            "files_per_ticker_min": files_min,
            "files_per_ticker_max": files_max,
            "estimated_files_min": stage_min,
            "estimated_files_max": stage_max,
        }
    return {"by_stage": by_stage, "total_estimated_files_min": total_min, "total_estimated_files_max": total_max}


def validate_evidence_scope(stage_assignments: pd.DataFrame | list[dict[str, Any]], policy: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    policy = policy or load_evidence_pack_policy()
    frame = _to_frame(stage_assignments)
    if frame.empty:
        return []
    issues = []
    requested_col = _requested_files_column(frame)
    for _, row in frame.iterrows():
        stage = str(row.get("stage", ""))
        if stage not in policy["stages"]:
            issues.append(_scope_issue("UNKNOWN_STAGE", row, stage, "", "", f"Unknown evidence stage: {stage}"))
            continue
        stage_max = int(policy["stages"][stage].get("official_files_per_ticker_max", 0) or 0)
        requested = _to_int(row.get(requested_col, stage_max if requested_col else stage_max))
        if requested > stage_max:
            issues.append(
                _scope_issue(
                    "REQUESTED_FILES_EXCEED_STAGE_CAP",
                    row,
                    stage,
                    requested,
                    stage_max,
                    f"Requested {requested} official files per ticker before stage policy allows it.",
                )
            )
    if "stage" in frame.columns:
        counts = frame["stage"].astype(str).value_counts()
        for stage, count in counts.items():
            if stage not in policy["stages"]:
                continue
            target_max = int(policy["stages"][stage].get("target_max_tickers", 0) or 0)
            if target_max and int(count) > target_max:
                issues.append(
                    {
                        "issue_code": "STAGE_TICKER_COUNT_EXCEEDS_TARGET",
                        "ticker": "",
                        "stage": stage,
                        "requested_files_per_ticker": "",
                        "stage_files_per_ticker_max": policy["stages"][stage].get("official_files_per_ticker_max", 0),
                        "message": f"Stage has {int(count)} tickers, above target max {target_max}.",
                    }
                )
    return issues


def build_candidate_stage_assignments(
    input_frame: pd.DataFrame | None,
    policy: dict[str, Any] | None = None,
) -> pd.DataFrame:
    policy = policy or load_evidence_pack_policy()
    if not isinstance(input_frame, pd.DataFrame) or input_frame.empty:
        return _template_stage_assignments(policy)
    frame = input_frame.copy()
    ticker_col = _first_existing_column(frame, ["ticker", "symbol", "code"])
    if not ticker_col:
        return _template_stage_assignments(policy)
    rank_col = _first_existing_column(frame, RANK_COLUMNS)
    score_col = _first_existing_column(frame, RANK_SCORE_COLUMNS)
    if not rank_col and score_col:
        frame = frame.sort_values(score_col, ascending=False).reset_index(drop=True)
        frame["_derived_evidence_rank"] = frame.index + 1
        rank_col = "_derived_evidence_rank"
    rows = []
    for _, row in frame.iterrows():
        ticker = str(row.get(ticker_col, "")).strip().upper()
        if not ticker:
            continue
        rank_value = _to_int(row.get(rank_col, "")) if rank_col else 0
        stage = assign_evidence_stage({"rank": rank_value}) if rank_col else STAGE_0
        stage_spec = policy["stages"][stage]
        status = "ASSIGNED_FROM_RANK" if rank_col and not str(rank_col).startswith("_derived") else "ASSIGNED_FROM_RANK_SCORE" if rank_col else "MISSING_RANKING_INPUT"
        reason = (
            "Rank used only to size official evidence workload, not investment recommendation."
            if rank_col
            else "MISSING_RANKING_INPUT; no real investment ranking was inferred."
        )
        rows.append(
            {
                "ticker": ticker,
                "input_rank": rank_value if rank_col else "",
                "rank_source": "" if not rank_col else "derived_from_rank_score" if str(rank_col).startswith("_derived") else rank_col,
                "stage": stage,
                "stage_assignment_status": status,
                "assignment_reason": reason,
                "official_files_per_ticker_min": stage_spec.get("official_files_per_ticker_min", 0),
                "official_files_per_ticker_max": stage_spec.get("official_files_per_ticker_max", 0),
                "target_max_tickers_for_stage": stage_spec.get("target_max_tickers", 0),
                "template_only": False,
                "manual_review_required": status == "MISSING_RANKING_INPUT",
                "no_financial_claim": True,
            }
        )
    return pd.DataFrame(rows, columns=CANDIDATE_STAGE_ASSIGNMENT_COLUMNS)


def build_evidence_collection_queue(assignments: pd.DataFrame, policy: dict[str, Any] | None = None) -> pd.DataFrame:
    policy = policy or load_evidence_pack_policy()
    rows = []
    for _, assignment in _real_assignments(assignments).iterrows():
        stage = str(assignment.get("stage", ""))
        if stage not in policy["stages"]:
            continue
        if int(policy["stages"][stage].get("official_files_per_ticker_max", 0) or 0) == 0:
            continue
        for document in required_documents_for_stage(stage, policy):
            rows.append(
                {
                    "ticker": assignment.get("ticker", ""),
                    "stage": stage,
                    "document_priority": document["document_priority"],
                    "document_requirement": document["document_requirement"],
                    "period_target": document["period_target"],
                    "period_type_target": document["period_type_target"],
                    "preferred_document_category": document["preferred_document_category"],
                    "preferred_source_tier": "1_user_manual_seed_vietstock_category_page",
                    "max_files_allowed": document["max_files_allowed"],
                    "required": True,
                    "manual_review_required": True,
                    "reason": "EVIDENCE_SLOT_PLANNED_ONLY_NO_DOWNLOAD_FORCED",
                }
            )
    return pd.DataFrame(rows, columns=EVIDENCE_COLLECTION_QUEUE_COLUMNS)


def build_document_discovery_plan(
    assignments: pd.DataFrame,
    queue: pd.DataFrame,
    policy: dict[str, Any] | None = None,
) -> pd.DataFrame:
    policy = policy or load_evidence_pack_policy()
    rows = []
    if queue.empty:
        for _, assignment in assignments.iterrows():
            rows.append(
                {
                    "ticker": assignment.get("ticker", ""),
                    "stage": assignment.get("stage", ""),
                    "document_priority": "",
                    "discovery_mode": "planning_template_only" if bool(assignment.get("template_only", False)) else "deferred",
                    "preferred_source_tiers": _format_source_tiers(policy),
                    "force_download": False,
                    "plan_status": assignment.get("stage_assignment_status", "NO_EVIDENCE_QUEUE_CREATED"),
                    "reason": "No real ranked shortlist input; no PDF download requested.",
                }
            )
    else:
        for _, row in queue.iterrows():
            rows.append(
                {
                    "ticker": row.get("ticker", ""),
                    "stage": row.get("stage", ""),
                    "document_priority": row.get("document_priority", ""),
                    "discovery_mode": "manual_seed_or_metadata_discovery_only",
                    "preferred_source_tiers": _format_source_tiers(policy),
                    "force_download": False,
                    "plan_status": "PLANNED_NO_DOWNLOAD",
                    "reason": "Create evidence availability map before any parse/download expansion.",
                }
            )
    return pd.DataFrame(rows, columns=DOCUMENT_DISCOVERY_PLAN_COLUMNS)


def build_manual_seed_requests(queue: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in queue.iterrows():
        category = _suggested_vietstock_category(row.get("preferred_document_category", ""))
        rows.append(
            {
                "ticker": row.get("ticker", ""),
                "stage": row.get("stage", ""),
                "needed_document": row.get("document_priority", ""),
                "where_to_get_it": "Vietstock > Tai lieu > Bao cao tai chinh/Bao cao thuong nien, or company IR direct link",
                "suggested_category": category,
                "document_priority": row.get("document_priority", ""),
                "reason": "Manual seed requested only for staged evidence slots; no automated bulk download.",
            }
        )
    return pd.DataFrame(rows, columns=MANUAL_SEED_REQUEST_COLUMNS)


def build_evidence_pack_status(
    assignments: pd.DataFrame,
    policy: dict[str, Any] | None = None,
    document_index: pd.DataFrame | None = None,
) -> pd.DataFrame:
    policy = policy or load_evidence_pack_policy()
    doc_index = _prepare_document_index(document_index)
    rows = []
    for _, assignment in assignments.iterrows():
        ticker = str(assignment.get("ticker", "")).upper()
        stage = str(assignment.get("stage", ""))
        stage_spec = policy["stages"].get(stage, {})
        required_slots = _required_file_slots(stage, policy) if not bool(assignment.get("template_only", False)) else 0
        availability = _availability_for_ticker(ticker, doc_index)
        slots_filled = _filled_slots_for_stage(stage, availability, policy) if required_slots else 0
        slots_filled = min(slots_filled, required_slots)
        slots_missing = max(0, required_slots - slots_filled)
        status = _evidence_status(
            stage=stage,
            stage_spec=stage_spec,
            required_slots=required_slots,
            slots_filled=slots_filled,
            template_only=bool(assignment.get("template_only", False)),
        )
        rows.append(
            {
                "ticker": ticker,
                "stage": stage,
                "required_slots": required_slots,
                "slots_filled": slots_filled,
                "slots_missing": slots_missing,
                "latest_bctc_available": availability["latest_bctc_available"],
                "latest_audited_annual_fs_available": availability["latest_audited_annual_fs_available"],
                "latest_bctn_available": availability["latest_bctn_available"],
                "same_period_previous_year_available": availability["same_period_previous_year_available"],
                "three_year_history_available": availability["three_year_history_available"],
                "evidence_pack_status": status,
                "manual_review_required": status not in {"NO_OFFICIAL_EVIDENCE_NEEDED_YET", "MINIMUM_EVIDENCE_PACK_READY", "DEEP_DIVE_EVIDENCE_READY"},
                "next_action": _next_action(status, bool(assignment.get("template_only", False))),
            }
        )
    return pd.DataFrame(rows, columns=EVIDENCE_PACK_STATUS_COLUMNS)


def build_workload_budget_estimate(policy: dict[str, Any] | None = None) -> pd.DataFrame:
    policy = policy or load_evidence_pack_policy()
    assumptions = policy.get("workload_assumptions", {})
    minutes_min = int(assumptions.get("manual_minutes_per_file_min", 2) or 2)
    minutes_max = int(assumptions.get("manual_minutes_per_file_max", 5) or 5)
    rows = []
    for stage in stage_order(policy):
        spec = policy["stages"][stage]
        target = int(spec.get("target_max_tickers", 0) or 0)
        files_min = int(spec.get("official_files_per_ticker_min", 0) or 0)
        files_max = int(spec.get("official_files_per_ticker_max", 0) or 0)
        estimated_min = target * files_min
        estimated_max = target * files_max
        rows.append(
            {
                "stage": stage,
                "target_tickers": target,
                "files_per_ticker_min": files_min,
                "files_per_ticker_max": files_max,
                "estimated_files_min": estimated_min,
                "estimated_files_max": estimated_max,
                "manual_minutes_per_file_assumption": f"{minutes_min}-{minutes_max}",
                "manual_hours_min": round(estimated_min * minutes_min / 60, 2),
                "manual_hours_max": round(estimated_max * minutes_max / 60, 2),
                "paid_data_recommended": _paid_data_recommendation(stage),
            }
        )
    return pd.DataFrame(rows, columns=EVIDENCE_WORKLOAD_BUDGET_COLUMNS)


def stage_order(policy: dict[str, Any]) -> list[str]:
    stages = list((policy.get("stages") or {}).keys())
    return stages or DEFAULT_STAGE_ORDER


def forbidden_policy_output_columns() -> list[str]:
    columns = (
        CANDIDATE_STAGE_ASSIGNMENT_COLUMNS
        + EVIDENCE_COLLECTION_QUEUE_COLUMNS
        + DOCUMENT_DISCOVERY_PLAN_COLUMNS
        + MANUAL_SEED_REQUEST_COLUMNS
        + EVIDENCE_PACK_STATUS_COLUMNS
        + EVIDENCE_WORKLOAD_BUDGET_COLUMNS
    )
    return [column for column in columns if any(term in column.lower() for term in FORBIDDEN_OUTPUT_TERMS)]


def _template_stage_assignments(policy: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for stage in stage_order(policy):
        spec = policy["stages"][stage]
        rows.append(
            {
                "ticker": f"TEMPLATE_{stage.upper()}",
                "input_rank": "",
                "rank_source": "",
                "stage": stage,
                "stage_assignment_status": "MISSING_RANKING_INPUT",
                "assignment_reason": "MISSING_RANKING_INPUT; No real investment ranking was inferred.",
                "official_files_per_ticker_min": spec.get("official_files_per_ticker_min", 0),
                "official_files_per_ticker_max": spec.get("official_files_per_ticker_max", 0),
                "target_max_tickers_for_stage": spec.get("target_max_tickers", 0),
                "template_only": True,
                "manual_review_required": True,
                "no_financial_claim": True,
            }
        )
    return pd.DataFrame(rows, columns=CANDIDATE_STAGE_ASSIGNMENT_COLUMNS)


def _validate_policy_shape(policy: dict[str, Any]) -> None:
    if not isinstance(policy.get("stages"), dict) or not isinstance(policy.get("document_priorities"), dict):
        raise ValueError("Evidence pack policy must define stages and document_priorities.")


def _rank_from_row(row: dict[str, Any] | pd.Series) -> int | None:
    for column in RANK_COLUMNS:
        value = _to_int(_get(row, column, ""))
        if value > 0:
            return value
    return None


def _requested_files_column(frame: pd.DataFrame) -> str:
    for column in ["requested_files_per_ticker", "planned_files_per_ticker", "official_files_per_ticker_requested"]:
        if column in frame.columns:
            return column
    return ""


def _scope_issue(
    issue_code: str,
    row: pd.Series | dict[str, Any],
    stage: str,
    requested: Any,
    stage_max: Any,
    message: str,
) -> dict[str, Any]:
    return {
        "issue_code": issue_code,
        "ticker": _get(row, "ticker", ""),
        "stage": stage,
        "requested_files_per_ticker": requested,
        "stage_files_per_ticker_max": stage_max,
        "message": message,
    }


def _real_assignments(assignments: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(assignments, pd.DataFrame) or assignments.empty:
        return pd.DataFrame(columns=CANDIDATE_STAGE_ASSIGNMENT_COLUMNS)
    if "template_only" not in assignments.columns:
        return assignments.copy()
    return assignments[~assignments["template_only"].astype(bool)].copy()


def _required_file_slots(stage: str, policy: dict[str, Any]) -> int:
    if stage not in policy["stages"]:
        return 0
    stage_max = int(policy["stages"][stage].get("official_files_per_ticker_max", 0) or 0)
    return min(stage_max, sum(int(doc.get("max_files_allowed", 1) or 1) for doc in required_documents_for_stage(stage, policy)))


def _filled_slots_for_stage(stage: str, availability: dict[str, Any], policy: dict[str, Any]) -> int:
    slots = 0
    for document in required_documents_for_stage(stage, policy):
        priority = document["document_priority"]
        max_files = int(document.get("max_files_allowed", 1) or 1)
        if priority.startswith("P0") and availability["latest_bctc_available"]:
            slots += 1
        elif priority.startswith("P1") and availability["latest_audited_annual_fs_available"]:
            slots += 1
        elif priority.startswith("P2") and availability["latest_bctn_available"]:
            slots += 1
        elif priority.startswith("P3") and availability["same_period_previous_year_available"]:
            slots += 1
        elif priority.startswith("P4") and availability["three_year_history_available"]:
            slots += min(max_files, 3)
        elif priority.startswith("P5"):
            slots += min(max_files, int(availability.get("historical_file_count", 0)))
    return slots


def _availability_for_ticker(ticker: str, document_index: pd.DataFrame) -> dict[str, Any]:
    if not isinstance(document_index, pd.DataFrame) or document_index.empty or not ticker:
        return _empty_availability()
    docs = document_index[document_index["ticker"].astype(str).str.upper().eq(ticker)].copy()
    if docs.empty:
        return _empty_availability()
    doc_type = docs.get("document_type", pd.Series(dtype=str)).astype(str).str.lower()
    period = docs.get("period", pd.Series(dtype=str)).astype(str).str.upper()
    is_financial = doc_type.isin(["financial_statement", "audited_financial_statement"])
    is_annual_fs = is_financial & ~period.str.contains("-Q", regex=False)
    annual_period_count = int(period[is_annual_fs].nunique())
    return {
        "latest_bctc_available": bool(is_financial.any()),
        "latest_audited_annual_fs_available": bool(is_annual_fs.any()),
        "latest_bctn_available": bool(doc_type.eq("annual_report").any()),
        "same_period_previous_year_available": bool(period[is_financial].nunique() >= 2),
        "three_year_history_available": bool(annual_period_count >= 3),
        "historical_file_count": int(is_financial.sum() + doc_type.eq("annual_report").sum()),
    }


def _empty_availability() -> dict[str, Any]:
    return {
        "latest_bctc_available": False,
        "latest_audited_annual_fs_available": False,
        "latest_bctn_available": False,
        "same_period_previous_year_available": False,
        "three_year_history_available": False,
        "historical_file_count": 0,
    }


def _prepare_document_index(document_index: pd.DataFrame | None) -> pd.DataFrame:
    if not isinstance(document_index, pd.DataFrame) or document_index.empty:
        return pd.DataFrame()
    frame = document_index.copy()
    for column in ["ticker", "period", "document_type"]:
        if column not in frame.columns:
            frame[column] = ""
    return frame


def _evidence_status(
    *,
    stage: str,
    stage_spec: dict[str, Any],
    required_slots: int,
    slots_filled: int,
    template_only: bool,
) -> str:
    if template_only:
        return "NO_OFFICIAL_EVIDENCE_NEEDED_YET" if required_slots == 0 else "INSUFFICIENT_EVIDENCE"
    stage_max = int(stage_spec.get("official_files_per_ticker_max", 0) or 0)
    stage_min = int(stage_spec.get("official_files_per_ticker_min", 0) or 0)
    if stage_max == 0:
        return "NO_OFFICIAL_EVIDENCE_NEEDED_YET"
    if slots_filled >= stage_min and stage in {STAGE_4, STAGE_5}:
        return "DEEP_DIVE_EVIDENCE_READY"
    if slots_filled >= stage_min:
        return "MINIMUM_EVIDENCE_PACK_READY"
    if slots_filled > 0:
        return "PARTIAL_EVIDENCE_PACK"
    return "EVIDENCE_QUEUE_CREATED"


def _next_action(status: str, template_only: bool) -> str:
    if template_only:
        return "Provide a ranked shortlist/watchlist input before creating real evidence requests."
    if status == "NO_OFFICIAL_EVIDENCE_NEEDED_YET":
        return "Keep using cheap/provisional data; no official document collection yet."
    if status == "EVIDENCE_QUEUE_CREATED":
        return "Collect only staged manual seeds/links; do not bulk download PDFs."
    if status == "PARTIAL_EVIDENCE_PACK":
        return "Fill missing staged evidence slots before readiness gate."
    if status in {"MINIMUM_EVIDENCE_PACK_READY", "DEEP_DIVE_EVIDENCE_READY"}:
        return "Evidence-file-ready only; parsed finance readiness still requires value extraction."
    return "Manual review required."


def _format_source_tiers(policy: dict[str, Any]) -> str:
    tiers = policy.get("preferred_source_tiers", [])
    return "; ".join(f"{item.get('tier')}:{item.get('name')}" for item in tiers)


def _suggested_vietstock_category(category: Any) -> str:
    normalized = str(category or "").lower()
    if "annual" in normalized:
        return "Bao cao thuong nien"
    if "financial" in normalized:
        return "Bao cao tai chinh"
    return "Bao cao tai chinh or Bao cao thuong nien"


def _paid_data_recommendation(stage: str) -> str:
    if stage in {STAGE_4, STAGE_5}:
        return "Yes, if manual collection blocks progress"
    if stage == STAGE_3:
        return "Maybe, only if manual seed workload is too high"
    return "No"


def _first_existing_column(frame: pd.DataFrame, names: list[str]) -> str:
    lowered = {column.lower(): column for column in frame.columns}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return ""


def _to_frame(value: pd.DataFrame | list[dict[str, Any]]) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    if isinstance(value, list):
        return pd.DataFrame(value)
    return pd.DataFrame()


def _get(row: dict[str, Any] | pd.Series, key: str, default: Any = "") -> Any:
    try:
        return row.get(key, default)
    except AttributeError:
        return default


def _to_int(value: Any) -> int:
    try:
        if str(value).strip() == "":
            return 0
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0
