"""Category-first BCTC/BCTN document scoring for 01IF PATCH3-PATCH3."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.ingestion.official_finance_link_extractor import normalize_text


BCTC_BCTN_DOCUMENT_SCORE_COLUMNS_01IF_PATCH3_PATCH3 = [
    "ticker",
    "period",
    "period_type",
    "source_name",
    "source_category",
    "source_url",
    "final_url",
    "local_path",
    "file_hash",
    "detected_file_type",
    "document_category_raw",
    "document_category_normalized",
    "document_title",
    "source_document_type",
    "consolidated_status",
    "document_score",
    "document_status",
    "tier",
    "manual_review_required",
    "review_reason",
    "notes",
]

STRONG_BCTC_SIGNALS = [
    "bao cao tai chinh",
    "baocaotaichinh",
    "bctc",
    "financial statement",
    "financial statements",
    "consolidated financial statements",
    "audited financial statements",
]

CONSOLIDATED_SIGNALS = ["hop nhat", "consolidated", "audited", "kiem toan"]

ANNUAL_REPORT_SIGNALS = [
    "bao cao thuong nien",
    "baocaothuongnien",
    "bctn",
    "annual report",
    "year report",
]

STRONG_NEGATIVE_SIGNALS = [
    "nghi quyet",
    "esop",
    "dieu le",
    "tai lieu dai hoi",
    "tai lieu dhdcd",
    "giai trinh",
    "bao cao quan tri",
    "presentation",
    "highlights",
    "agm",
    "investor presentation",
    "market overview",
    "esg",
]

TARGET_STATUSES = {"ACCEPTED_TARGET_BCTC", "ACCEPTED_TARGET_BCTN"}


def score_document_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame(columns=BCTC_BCTN_DOCUMENT_SCORE_COLUMNS_01IF_PATCH3_PATCH3)
    rows = [score_document_candidate(row) for _, row in frame.iterrows()]
    return pd.DataFrame(rows, columns=BCTC_BCTN_DOCUMENT_SCORE_COLUMNS_01IF_PATCH3_PATCH3)


def score_document_candidate(row: pd.Series | dict[str, Any]) -> dict[str, Any]:
    category = _normalized_category(row)
    title_url = " ".join(
        [
            str(row.get("document_title", "")),
            str(row.get("source_url", "")),
            str(row.get("final_url", "")),
            str(row.get("candidate_url", "")),
            str(row.get("local_path", "")),
            str(row.get("document_type", "")),
            str(row.get("source_name", "")),
        ]
    )
    normalized = normalize_text(title_url)
    score = 0
    notes = []
    if category == "financial_statement":
        score += 100
        notes.append("category=financial_statement")
    if category == "annual_report":
        score += 70
        notes.append("category=annual_report")
    if _has_any(normalized, STRONG_BCTC_SIGNALS):
        score += 40
        notes.append("bctc_title_url_signal")
    if _has_any(normalized, CONSOLIDATED_SIGNALS):
        score += 25
        notes.append("consolidated_or_audited_signal")
    if _has_any(normalized, ANNUAL_REPORT_SIGNALS):
        score += 20
        notes.append("annual_report_signal")
    negative = _has_any(normalized, STRONG_NEGATIVE_SIGNALS)
    if negative:
        score -= 100
        notes.append("negative_title_signal")

    manual_review = False
    reason = ""
    if negative:
        status = "REJECTED_NEGATIVE_TITLE"
        manual_review = True
        reason = "REJECTED_NEGATIVE_TITLE"
    elif category not in {"financial_statement", "annual_report"}:
        status = "REJECTED_NON_TARGET_CATEGORY"
        manual_review = True
        reason = "REJECTED_NON_TARGET_CATEGORY"
    elif score < 80:
        status = "REJECTED_LOW_DOCUMENT_SCORE"
        manual_review = True
        reason = "REJECTED_LOW_DOCUMENT_SCORE"
    elif category == "financial_statement":
        status = "ACCEPTED_TARGET_BCTC"
    else:
        status = "ACCEPTED_TARGET_BCTN"

    period = str(row.get("period") or row.get("period_guess") or "")
    period_type = str(row.get("period_type") or ("quarter" if "-Q" in period.upper() else "annual" if period else ""))
    return {
        "ticker": str(row.get("ticker", "")).upper(),
        "period": period,
        "period_type": period_type,
        "source_name": row.get("source_name", ""),
        "source_category": row.get("source_category", ""),
        "source_url": row.get("source_url", ""),
        "final_url": row.get("final_url", row.get("candidate_url", "")),
        "local_path": row.get("local_path", ""),
        "file_hash": row.get("file_hash", ""),
        "detected_file_type": str(row.get("detected_file_type", row.get("file_type", ""))).lower(),
        "document_category_raw": row.get("document_category_raw", row.get("document_type", "")),
        "document_category_normalized": category,
        "document_title": row.get("document_title", row.get("source_name", "")),
        "source_document_type": "annual_report" if category == "annual_report" else "financial_statement" if category == "financial_statement" else "other",
        "consolidated_status": str(row.get("consolidated_status", "") or _infer_consolidated_status(normalized)),
        "document_score": int(score),
        "document_status": status,
        "tier": _tier(row, category),
        "manual_review_required": manual_review,
        "review_reason": reason,
        "notes": ";".join(notes),
    }


def build_document_score_inputs(
    *,
    document_index: pd.DataFrame,
    vietstock_candidates: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if isinstance(document_index, pd.DataFrame) and not document_index.empty:
        for _, row in document_index.iterrows():
            rows.append(
                {
                    **row.to_dict(),
                    "document_category_raw": row.get("document_type", ""),
                    "document_category_normalized": _document_type_to_category(row.get("document_type", "")),
                    "document_title": row.get("source_name", ""),
                    "source_category": row.get("source_type", ""),
                }
            )
    if isinstance(vietstock_candidates, pd.DataFrame) and not vietstock_candidates.empty:
        for _, row in vietstock_candidates.iterrows():
            rows.append(
                {
                    **row.to_dict(),
                    "source_name": row.get("source_name", "vietstock_finance_documents"),
                    "source_category": row.get("source_category", "vietstock_public_document_page"),
                    "source_url": row.get("source_url", ""),
                    "final_url": row.get("final_url", ""),
                    "detected_file_type": row.get("file_type", ""),
                    "document_type": row.get("document_category_normalized", ""),
                    "consolidated_status": "unknown",
                }
            )
    return pd.DataFrame(rows)


def select_scored_local_documents_for_parse(
    scores: pd.DataFrame,
    *,
    max_documents: int | None = None,
) -> pd.DataFrame:
    if not isinstance(scores, pd.DataFrame) or scores.empty:
        return pd.DataFrame(columns=BCTC_BCTN_DOCUMENT_SCORE_COLUMNS_01IF_PATCH3_PATCH3)
    frame = scores[scores["document_status"].isin(TARGET_STATUSES)].copy()
    frame = frame[frame["local_path"].astype(str).str.strip().ne("")].copy()
    frame = frame[frame["detected_file_type"].astype(str).str.lower().isin({"pdf", "xlsx", "xls"})].copy()
    if frame.empty:
        return frame
    frame["_type_priority"] = frame["document_status"].map({"ACCEPTED_TARGET_BCTC": 0, "ACCEPTED_TARGET_BCTN": 2}).fillna(9)
    frame["_consolidated_priority"] = frame["consolidated_status"].astype(str).str.lower().map({"consolidated": 0, "unknown": 1, "standalone": 2}).fillna(2)
    frame["_period_sort"] = frame["period"].astype(str).map(_period_sort_value)
    frame = frame.sort_values(
        ["_type_priority", "_consolidated_priority", "_period_sort", "document_score", "ticker"],
        ascending=[True, True, False, False, True],
    ).drop(columns=["_type_priority", "_consolidated_priority", "_period_sort"])
    if max_documents:
        frame = frame.head(max_documents)
    return frame[BCTC_BCTN_DOCUMENT_SCORE_COLUMNS_01IF_PATCH3_PATCH3]


def _normalized_category(row: pd.Series | dict[str, Any]) -> str:
    existing = str(row.get("document_category_normalized", "")).strip()
    if existing:
        return existing
    return _document_type_to_category(row.get("document_type", ""))


def _document_type_to_category(value: Any) -> str:
    normalized = normalize_text(value)
    if any(token in normalized for token in ["financial statement", "audited financial statement", "bao cao tai chinh", "bctc"]):
        return "financial_statement"
    if any(token in normalized for token in ["annual report", "bao cao thuong nien", "bctn"]):
        return "annual_report"
    if normalized in {"financial statement", "financial statements", "audited financial statement", "audited financial statements"}:
        return "financial_statement"
    return "other"


def _tier(row: pd.Series | dict[str, Any], category: str) -> int:
    source = normalize_text(f"{row.get('source_category', '')} {row.get('source_name', '')} {row.get('source_url', '')}")
    if "vietstock" in source and category == "financial_statement":
        return 1
    if category == "financial_statement":
        return 2
    if "vietstock" in source and category == "annual_report":
        return 3
    if category == "annual_report":
        return 4
    return 9


def _has_any(normalized: str, keywords: list[str]) -> bool:
    return any(normalize_text(keyword) in normalized for keyword in keywords)


def _infer_consolidated_status(normalized: str) -> str:
    if any(token in normalized for token in ["hop nhat", "consolidated"]):
        return "consolidated"
    if any(token in normalized for token in ["cong ty me", "standalone", "separate"]):
        return "standalone"
    return "unknown"


def _period_sort_value(period: Any) -> int:
    text = str(period or "").upper()
    if not text:
        return 0
    year = 0
    quarter = 0
    parts = text.split("-Q")
    try:
        year = int(parts[0])
    except ValueError:
        return 0
    if len(parts) > 1:
        try:
            quarter = int(parts[1])
        except ValueError:
            quarter = 0
    return year * 10 + quarter
