"""Official finance document selection for REAL-DATA-01I-F."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.ingestion.official_finance_link_extractor import normalize_text


SELECTED_DOCUMENT_COLUMNS_01IF = [
    "ticker",
    "period",
    "document_type",
    "consolidated_status",
    "source_url",
    "final_url",
    "local_path",
    "file_hash",
    "detected_file_type",
    "selection_status",
    "selection_priority",
    "manual_review_required",
    "reason",
    "notes",
]

TARGET_PERIOD_PRIORITY_01IF = {
    "2026-Q1": 0,
    "2025-Q4": 1,
    "2025": 2,
    "2025-Q3": 3,
    "2025-Q2": 4,
}

SUPPORTED_PARSE_FILE_TYPES = {"pdf", "xlsx", "xls"}
SUPPORTED_DOCUMENT_TYPES = {"financial_statement", "audited_financial_statement", "annual_report"}
SUCCESS_DOCUMENT_STATUSES = {"DOWNLOADED", "DEPTH1_DOCUMENT_DOWNLOADED"}


def select_documents_for_official_parse(
    document_index: pd.DataFrame,
    *,
    target_periods: list[str] | None = None,
    tickers: list[str] | None = None,
    parse_annual_reports: bool = False,
    skip_standalone: bool = False,
) -> pd.DataFrame:
    """Select parse candidates without treating annual/standalone docs as clean by default."""

    target_periods = [str(period).upper() for period in (target_periods or list(TARGET_PERIOD_PRIORITY_01IF))]
    wanted_tickers = {ticker.strip().upper() for ticker in tickers or [] if ticker.strip()}
    rows = []
    seen_hashes: set[str] = set()
    eligible = _prepare_index(document_index)
    if wanted_tickers:
        eligible = eligible[eligible["ticker"].isin(wanted_tickers)].copy()
    consolidated_keys = {
        (row["ticker"], row["period"])
        for _, row in eligible.iterrows()
        if row["consolidated_status"] == "consolidated"
        and row["download_status"] in SUCCESS_DOCUMENT_STATUSES
        and row["detected_file_type"] in SUPPORTED_PARSE_FILE_TYPES
    }
    for _, row in _sort_index_for_selection(eligible, target_periods).iterrows():
        output = _base_selection_row(row)
        reasons: list[str] = []
        status = "SELECTED_FOR_PARSE"
        manual_review = bool(row.get("manual_review_required"))

        if row["detected_file_type"] not in SUPPORTED_PARSE_FILE_TYPES:
            status = "SKIPPED_UNSUPPORTED_FILE_TYPE"
            reasons.append(f"UNSUPPORTED_FILE_TYPE:{row['detected_file_type']}")
            manual_review = True
        elif row["download_status"] not in SUCCESS_DOCUMENT_STATUSES:
            status = "SKIPPED_NON_FINANCE_DOCUMENT"
            reasons.append(f"DOWNLOAD_STATUS_NOT_PARSEABLE:{row['download_status']}")
            manual_review = True
        elif not row["official_domain"] or not row["file_hash"] or not row["local_path"]:
            status = "SKIPPED_NON_FINANCE_DOCUMENT"
            reasons.append("MISSING_REQUIRED_DOCUMENT_EVIDENCE")
            manual_review = True
        elif row["period"] not in target_periods:
            status = "SKIPPED_OLD_PERIOD"
            reasons.append("PERIOD_OUTSIDE_TARGETS")
            manual_review = True
        elif row["file_hash"] in seen_hashes:
            status = "SKIPPED_DUPLICATE_HASH"
            reasons.append("DUPLICATE_FILE_HASH")
            manual_review = True
        elif row["document_type"] not in SUPPORTED_DOCUMENT_TYPES:
            status = "SKIPPED_NON_FINANCE_DOCUMENT"
            reasons.append("DOCUMENT_TYPE_NOT_PARSEABLE")
            manual_review = True
        elif _is_esg_or_non_finance_document(row):
            status = "SKIPPED_NON_FINANCE_DOCUMENT"
            reasons.append("ESG_OR_NON_FINANCE_DOCUMENT")
            manual_review = True
        elif row["document_type"] == "annual_report" and not parse_annual_reports:
            status = "REVIEW_ONLY_ANNUAL_REPORT"
            reasons.append("ANNUAL_REPORT_REQUIRES_EXPLICIT_PARSE_OPT_IN")
            manual_review = True
        elif row["consolidated_status"] == "standalone" and (skip_standalone or (row["ticker"], row["period"]) in consolidated_keys):
            status = "REVIEW_ONLY_STANDALONE"
            reasons.append("STANDALONE_REVIEW_REQUIRED")
            manual_review = True

        if status == "SELECTED_FOR_PARSE":
            seen_hashes.add(row["file_hash"])
        output.update(
            {
                "selection_status": status,
                "selection_priority": _selection_priority(row, target_periods),
                "manual_review_required": bool(manual_review),
                "reason": ";".join(_dedupe([*reasons, row.get("review_reason", "")])),
                "notes": _selection_notes(status),
            }
        )
        rows.append(output)
    if not rows:
        return pd.DataFrame(columns=SELECTED_DOCUMENT_COLUMNS_01IF)
    return pd.DataFrame(rows, columns=SELECTED_DOCUMENT_COLUMNS_01IF)


def _prepare_index(document_index: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(document_index, pd.DataFrame) or document_index.empty:
        return pd.DataFrame()
    frame = document_index.copy()
    for column in [
        "ticker",
        "period",
        "document_type",
        "consolidated_status",
        "source_url",
        "final_url",
        "local_path",
        "file_hash",
        "detected_file_type",
        "download_status",
        "candidate_origin",
        "review_reason",
        "notes",
        "official_domain",
    ]:
        if column not in frame.columns:
            frame[column] = ""
        frame[column] = frame[column].astype(str).str.strip()
    frame["ticker"] = frame["ticker"].str.upper()
    frame["period"] = frame["period"].str.upper()
    frame["document_type"] = frame["document_type"].str.lower()
    frame["consolidated_status"] = frame["consolidated_status"].str.lower().replace("", "unknown")
    frame["detected_file_type"] = frame["detected_file_type"].str.lower()
    return frame


def _sort_index_for_selection(frame: pd.DataFrame, target_periods: list[str]) -> pd.DataFrame:
    if frame.empty:
        return frame
    sorted_frame = frame.copy()
    sorted_frame["_selection_priority"] = sorted_frame.apply(lambda row: _selection_priority(row, target_periods), axis=1)
    return sorted_frame.sort_values(["_selection_priority", "ticker", "period", "source_url"], ascending=[True, True, True, True])


def _selection_priority(row: pd.Series | dict[str, Any], target_periods: list[str]) -> int:
    priority = 0
    priority += {"consolidated": 0, "unknown": 50, "standalone": 100}.get(str(row.get("consolidated_status", "")).lower(), 100)
    period = str(row.get("period", "")).upper()
    priority += target_periods.index(period) if period in target_periods else 500
    priority += 0 if str(row.get("document_type", "")).lower() == "financial_statement" else 25
    priority += 0 if str(row.get("candidate_origin", "")) == "REFINED_SEED_DIRECT" else 10
    source = normalize_text(f"{row.get('source_url', '')} {row.get('final_url', '')}")
    if any(token in source for token in ["bctc", "bao cao tai chinh", "financial statement"]):
        priority -= 5
    return int(priority)


def _base_selection_row(row: pd.Series | dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": row.get("ticker", ""),
        "period": row.get("period", ""),
        "document_type": row.get("document_type", ""),
        "consolidated_status": row.get("consolidated_status", "unknown"),
        "source_url": row.get("source_url", ""),
        "final_url": row.get("final_url", ""),
        "local_path": row.get("local_path", ""),
        "file_hash": row.get("file_hash", ""),
        "detected_file_type": row.get("detected_file_type", ""),
        "selection_status": "",
        "selection_priority": "",
        "manual_review_required": True,
        "reason": "",
        "notes": "",
    }


def _is_esg_or_non_finance_document(row: pd.Series | dict[str, Any]) -> bool:
    text = normalize_text(f"{row.get('source_url', '')} {row.get('final_url', '')} {row.get('notes', '')}")
    if "esg" in text and not any(token in text for token in ["bctc", "bao cao tai chinh", "financial statement"]):
        return True
    if any(token in text for token in ["brochure", "presentation", "quy che", "dieu le", "governance"]):
        return not any(token in text for token in ["bctc", "bao cao tai chinh", "financial statement", "annual report", "bctn"])
    return False


def _selection_notes(status: str) -> str:
    if status == "SELECTED_FOR_PARSE":
        return "01IF_SELECTED_TEXT_PARSE_ONLY_NO_OCR"
    return "01IF_NOT_PARSED_OR_REVIEW_ONLY; missing values remain missing"


def _dedupe(values: list[Any]) -> list[str]:
    output = []
    for value in values:
        for part in str(value or "").split(";"):
            part = part.strip()
            if part and part not in output:
                output.append(part)
    return output
