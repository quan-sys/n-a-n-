"""Verification/report helpers for REAL-DATA-01I-E official document downloads."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import pandas as pd

from src.ingestion.official_finance_link_extractor import normalize_text


FINANCE_DOCUMENT_INDEX_COLUMNS_01IE = [
    "ticker",
    "exchange",
    "company_name",
    "period",
    "document_type",
    "source_type",
    "source_name",
    "source_url",
    "official_domain",
    "candidate_origin",
    "candidate_score",
    "candidate_score_band",
    "expected_file_type",
    "consolidated_status",
    "final_url",
    "http_status",
    "content_type",
    "detected_file_type",
    "local_path",
    "file_hash",
    "downloaded_at",
    "download_status",
    "document_confidence",
    "manual_review_required",
    "review_reason",
    "notes",
]

DOCUMENT_DOWNLOAD_STATUS_BY_TICKER_COLUMNS = [
    "ticker",
    "refined_seed_rows",
    "direct_documents_attempted",
    "html_pages_attempted",
    "depth1_candidates_found",
    "documents_downloaded",
    "html_snapshots_saved",
    "blocked_or_failed",
    "manual_review_required",
    "has_pdf_or_xlsx",
    "has_html_finance_page",
    "has_consolidated_candidate",
    "best_document_status",
    "best_document_url",
    "download_readiness_status",
    "notes",
]

MANUAL_REVIEW_COLUMNS_01IE = [
    "ticker",
    "period",
    "document_type",
    "source_url",
    "issue",
    "manual_review_required",
    "priority",
    "notes",
]

DOWNLOAD_SUCCESS_STATUSES = {"DOWNLOADED", "DEPTH1_DOCUMENT_DOWNLOADED"}
FAILED_STATUSES = {
    "SOURCE_URL_INVALID",
    "SOURCE_UNAVAILABLE",
    "SOURCE_BLOCKED_OR_JS_REQUIRED",
    "SOURCE_CONTENT_TYPE_UNSUPPORTED",
    "DOMAIN_MISMATCH_REVIEW",
    "FILE_TYPE_MISMATCH_REVIEW",
    "DOWNLOAD_FAILED",
}


def build_01ie_index_row(
    *,
    seed_row: dict[str, Any],
    downloaded_row: dict[str, Any],
    candidate_origin: str,
    candidate_score: Any = "",
    candidate_score_band: Any = "",
) -> dict[str, Any]:
    row = {
        "ticker": seed_row.get("ticker", downloaded_row.get("ticker", "")),
        "exchange": seed_row.get("exchange", downloaded_row.get("exchange", "")),
        "company_name": seed_row.get("company_name", downloaded_row.get("company_name", "")),
        "period": seed_row.get("period", downloaded_row.get("period", "")),
        "document_type": seed_row.get("document_type", downloaded_row.get("document_type", "")),
        "source_type": seed_row.get("source_type", downloaded_row.get("source_type", "")),
        "source_name": seed_row.get("source_name", downloaded_row.get("source_name", "")),
        "source_url": seed_row.get("source_url", downloaded_row.get("source_url", "")),
        "official_domain": seed_row.get("official_domain", downloaded_row.get("official_domain", "")),
        "candidate_origin": candidate_origin,
        "candidate_score": candidate_score,
        "candidate_score_band": candidate_score_band,
        "expected_file_type": seed_row.get("expected_file_type", downloaded_row.get("expected_file_type", "")),
        "consolidated_status": seed_row.get("consolidated_status", ""),
        "final_url": downloaded_row.get("final_url", ""),
        "http_status": downloaded_row.get("http_status", ""),
        "content_type": downloaded_row.get("content_type", ""),
        "detected_file_type": downloaded_row.get("detected_file_type", ""),
        "local_path": downloaded_row.get("local_path", ""),
        "file_hash": downloaded_row.get("file_hash", ""),
        "downloaded_at": downloaded_row.get("downloaded_at", ""),
        "download_status": downloaded_row.get("download_status", ""),
        "document_confidence": downloaded_row.get("document_confidence", "low"),
        "manual_review_required": downloaded_row.get("manual_review_required", True),
        "review_reason": downloaded_row.get("review_reason", ""),
        "notes": downloaded_row.get("notes", ""),
    }
    return calibrate_01ie_document_row(row)


def calibrate_01ie_document_row(row: dict[str, Any]) -> dict[str, Any]:
    status = _clean_text(row.get("download_status"))
    detected = _clean_text(row.get("detected_file_type")).lower()
    expected = _clean_text(row.get("expected_file_type")).lower()
    final_domain = _normalize_domain(urlparse(_clean_text(row.get("final_url"))).netloc)
    official_domain = _normalize_domain(row.get("official_domain"))
    combined = normalize_text(
        " ".join(
            [
                _clean_text(row.get("source_url")),
                _clean_text(row.get("final_url")),
                _clean_text(row.get("notes")),
            ]
        )
    )
    reasons = _split_reason(row.get("review_reason"))
    manual_review = _boolish(row.get("manual_review_required"))
    if final_domain and official_domain and not _domain_matches(final_domain, official_domain):
        status = "DOMAIN_MISMATCH_REVIEW"
        manual_review = True
        reasons.append("FINAL_DOMAIN_MISMATCH_REVIEW")
    if expected in {"pdf", "xlsx", "xls"} and detected and detected != expected and status in DOWNLOAD_SUCCESS_STATUSES:
        status = "FILE_TYPE_MISMATCH_REVIEW"
        manual_review = True
        reasons.append("FILE_TYPE_MISMATCH_REVIEW")
    if _clean_text(row.get("consolidated_status")).lower() == "standalone" or "rieng" in combined or "standalone" in combined:
        manual_review = True
        reasons.append("STANDALONE_REVIEW_REQUIRED")
    if status in {"HTML_SNAPSHOT_SAVED", "MANUAL_REVIEW"} and expected == "html":
        manual_review = True
    if detected in {"pdf", "xlsx", "xls"} and status in DOWNLOAD_SUCCESS_STATUSES and not manual_review:
        confidence = "high"
    elif status == "HTML_SNAPSHOT_SAVED" or _clean_text(row.get("consolidated_status")).lower() == "standalone":
        confidence = "medium"
    else:
        confidence = "low"
    row["download_status"] = status
    row["manual_review_required"] = bool(manual_review)
    row["review_reason"] = ";".join(_dedupe(reasons))
    row["document_confidence"] = confidence
    if status in DOWNLOAD_SUCCESS_STATUSES:
        row["notes"] = _append_note(row.get("notes"), "01IE_DOCUMENT_FILE_DOWNLOADED_NOT_FINANCE_EVIDENCE")
    elif status == "HTML_SNAPSHOT_SAVED":
        row["notes"] = _append_note(row.get("notes"), "01IE_HTML_SNAPSHOT_NOT_FINANCE_EVIDENCE")
    return {column: row.get(column, "") for column in FINANCE_DOCUMENT_INDEX_COLUMNS_01IE}


def manual_review_row_from_01ie_index(row: dict[str, Any] | pd.Series, *, priority: str | None = None) -> dict[str, Any]:
    issue = _clean_text(row.get("review_reason")) or _clean_text(row.get("download_status"))
    chosen_priority = priority or _priority_for_issue(issue, row.get("download_status"))
    return {
        "ticker": _clean_text(row.get("ticker")).upper(),
        "period": _clean_text(row.get("period")),
        "document_type": _clean_text(row.get("document_type")),
        "source_url": _clean_text(row.get("source_url")),
        "issue": issue,
        "manual_review_required": True,
        "priority": chosen_priority,
        "notes": _clean_text(row.get("notes")),
    }


def build_document_download_status_by_ticker(
    *,
    refined_candidates: pd.DataFrame,
    document_index: pd.DataFrame,
    depth1_candidates: pd.DataFrame,
) -> pd.DataFrame:
    tickers = sorted(
        {
            *(_ticker_set(refined_candidates)),
            *(_ticker_set(document_index)),
            *(_ticker_set(depth1_candidates)),
        }
    )
    rows = []
    for ticker in tickers:
        refined_rows = _ticker_rows(refined_candidates, ticker)
        index_rows = _ticker_rows(document_index, ticker)
        depth_rows = _ticker_rows(depth1_candidates, ticker)
        statuses = index_rows["download_status"].astype(str).value_counts().to_dict() if not index_rows.empty else {}
        direct_attempted = int(index_rows["candidate_origin"].eq("REFINED_SEED_DIRECT").sum()) if not index_rows.empty else 0
        html_attempted = int(index_rows["candidate_origin"].eq("HTML_SNAPSHOT_ONLY").sum()) if not index_rows.empty else 0
        downloaded = int(index_rows["download_status"].isin(DOWNLOAD_SUCCESS_STATUSES).sum()) if not index_rows.empty else 0
        html_saved = int(statuses.get("HTML_SNAPSHOT_SAVED", 0))
        blocked_failed = int(sum(statuses.get(status, 0) for status in FAILED_STATUSES))
        manual = bool(index_rows["manual_review_required"].astype(bool).any()) if not index_rows.empty else bool(len(refined_rows))
        has_pdf_or_xlsx = bool(index_rows["detected_file_type"].isin(["pdf", "xlsx", "xls"]).any()) if not index_rows.empty else False
        has_html = bool(html_saved)
        has_consolidated = bool(index_rows["consolidated_status"].astype(str).str.lower().eq("consolidated").any()) if not index_rows.empty else False
        best = _best_index_row(index_rows)
        if has_pdf_or_xlsx:
            readiness = "HAS_VERIFIED_OFFICIAL_DOCUMENT_FILE"
        elif has_html:
            readiness = "HAS_REVIEWABLE_OFFICIAL_HTML_PAGE"
        elif blocked_failed:
            readiness = "ONLY_FAILED_OR_BLOCKED"
        elif refined_rows.empty:
            readiness = "NO_REFINED_CANDIDATES"
        else:
            readiness = "NEEDS_MANUAL_SEARCH"
        rows.append(
            {
                "ticker": ticker,
                "refined_seed_rows": int(len(refined_rows)),
                "direct_documents_attempted": direct_attempted,
                "html_pages_attempted": html_attempted,
                "depth1_candidates_found": int(len(depth_rows)),
                "documents_downloaded": downloaded,
                "html_snapshots_saved": html_saved,
                "blocked_or_failed": blocked_failed,
                "manual_review_required": manual,
                "has_pdf_or_xlsx": has_pdf_or_xlsx,
                "has_html_finance_page": has_html,
                "has_consolidated_candidate": has_consolidated,
                "best_document_status": best.get("download_status", ""),
                "best_document_url": best.get("final_url") or best.get("source_url", ""),
                "download_readiness_status": readiness,
                "notes": "document download evidence only; no finance values parsed",
            }
        )
    return pd.DataFrame(rows, columns=DOCUMENT_DOWNLOAD_STATUS_BY_TICKER_COLUMNS)


def build_01ie_decision_report_markdown(*, document_index: pd.DataFrame) -> str:
    downloaded_files = 0 if document_index.empty else int(
        document_index["download_status"].isin(DOWNLOAD_SUCCESS_STATUSES).sum()
    )
    html_saved = 0 if document_index.empty else int((document_index["download_status"] == "HTML_SNAPSHOT_SAVED").sum())
    document_download_ready = "True" if downloaded_files else ("Partial" if html_saved or len(document_index) else "False")
    file_ready = "Partial" if downloaded_files else "False"
    return "\n".join(
        [
            "# Datasource decision report",
            "",
            "- official_document_seed_ready: Partial",
            "- official_link_candidate_ready: Partial",
            f"- official_document_download_ready: {document_download_ready}",
            f"- official_document_file_ready: {file_ready}",
            "- finance_parse_ready: False",
            "- finance_ready_for_l0: unchanged",
            "- should_run_REAL_DATA_02: No",
            "- should_implement_Step19_now: No",
            "",
            "01I-E downloads or snapshots official document candidates only. Downloaded files are not parsed finance evidence.",
        ]
    )


def build_01ie_run_summary_markdown(
    *,
    command: str,
    refined_seed_rows_loaded: int,
    unique_tickers: int,
    document_index: pd.DataFrame,
    depth1_candidates: pd.DataFrame,
    manual_review_queue: pd.DataFrame,
    status_by_ticker: pd.DataFrame,
) -> str:
    status_counts = _counts(document_index, "download_status")
    type_counts = _counts(document_index, "detected_file_type")
    direct_attempted = int(document_index["candidate_origin"].eq("REFINED_SEED_DIRECT").sum()) if not document_index.empty else 0
    html_attempted = int(document_index["candidate_origin"].eq("HTML_SNAPSHOT_ONLY").sum()) if not document_index.empty else 0
    depth_downloaded = int((document_index["download_status"] == "DEPTH1_DOCUMENT_DOWNLOADED").sum()) if not document_index.empty else 0
    standalone = int(document_index["consolidated_status"].astype(str).str.lower().eq("standalone").sum()) if not document_index.empty else 0
    consolidated = int(document_index["consolidated_status"].astype(str).str.lower().eq("consolidated").sum()) if not document_index.empty else 0
    blocked_failed = int(sum(status_counts.get(status, 0) for status in FAILED_STATUSES))
    return "\n".join(
        [
            "# REAL-DATA-01I-E official finance document download run",
            "",
            "## Command run",
            f"`{command}`",
            "",
            "## Refined seed rows loaded",
            str(refined_seed_rows_loaded),
            "",
            "## Unique tickers",
            str(unique_tickers),
            "",
            "## Direct documents attempted",
            str(direct_attempted),
            "",
            "## HTML pages attempted",
            str(html_attempted),
            "",
            "## Depth-1 candidates found",
            str(len(depth1_candidates)),
            "",
            "## Documents downloaded",
            str(status_counts.get("DOWNLOADED", 0) + status_counts.get("DEPTH1_DOCUMENT_DOWNLOADED", 0)),
            "",
            "## HTML snapshots saved",
            str(status_counts.get("HTML_SNAPSHOT_SAVED", 0)),
            "",
            "## PDF/XLSX/XLS count",
            f"- pdf: {type_counts.get('pdf', 0)}",
            f"- xlsx: {type_counts.get('xlsx', 0)}",
            f"- xls: {type_counts.get('xls', 0)}",
            "",
            "## Standalone vs consolidated count",
            f"- consolidated: {consolidated}",
            f"- standalone: {standalone}",
            "",
            "## Manual review rows",
            str(len(manual_review_queue)),
            "",
            "## Status by ticker",
            _format_ticker_status(status_by_ticker),
            "",
            "## Main blockers",
            _format_counts({key: value for key, value in status_counts.items() if key in FAILED_STATUSES or key == "MANUAL_REVIEW"}),
            "",
            "## Next recommended action",
            "Review failed, standalone, and HTML-only documents before adding a parsing contract. Do not run REAL-DATA-02 or Step19 yet.",
            "",
            f"- depth1 documents downloaded: {depth_downloaded}",
            "- finance_parse_ready: False",
        ]
    )


def _best_index_row(index_rows: pd.DataFrame) -> dict[str, Any]:
    if not isinstance(index_rows, pd.DataFrame) or index_rows.empty:
        return {}
    priority = {
        "DOWNLOADED": 0,
        "DEPTH1_DOCUMENT_DOWNLOADED": 0,
        "HTML_SNAPSHOT_SAVED": 1,
        "DOMAIN_MISMATCH_REVIEW": 2,
        "FILE_TYPE_MISMATCH_REVIEW": 2,
    }
    frame = index_rows.copy()
    frame["_priority"] = frame["download_status"].map(priority).fillna(9).astype(int)
    frame["_score"] = pd.to_numeric(frame["candidate_score"], errors="coerce").fillna(0).astype(int)
    return frame.sort_values(["_priority", "_score", "source_url"], ascending=[True, False, True]).iloc[0].to_dict()


def _format_ticker_status(status_by_ticker: pd.DataFrame) -> str:
    if not isinstance(status_by_ticker, pd.DataFrame) or status_by_ticker.empty:
        return "- none"
    lines = []
    for _, row in status_by_ticker.iterrows():
        lines.append(
            f"- {row['ticker']}: {row['download_readiness_status']} "
            f"(files={row['documents_downloaded']}, html={row['html_snapshots_saved']}, manual={row['manual_review_required']})"
        )
    return "\n".join(lines)


def _priority_for_issue(issue: str, status: Any) -> str:
    issue_text = _clean_text(issue)
    status_text = _clean_text(status)
    if any(token in issue_text for token in ["STANDALONE", "MISMATCH", "BLOCKED", "FAILED", "UNAVAILABLE"]):
        return "high"
    if status_text == "HTML_SNAPSHOT_SAVED" or "HTML" in issue_text:
        return "medium"
    return "low"


def _ticker_set(df: pd.DataFrame) -> set[str]:
    if not isinstance(df, pd.DataFrame) or df.empty or "ticker" not in df.columns:
        return set()
    return {str(value).upper() for value in df["ticker"].dropna().astype(str)}


def _ticker_rows(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame) or df.empty or "ticker" not in df.columns:
        return pd.DataFrame(columns=df.columns if isinstance(df, pd.DataFrame) else [])
    return df[df["ticker"].astype(str).str.upper() == ticker].copy()


def _counts(df: pd.DataFrame, column: str) -> dict[str, int]:
    if not isinstance(df, pd.DataFrame) or df.empty or column not in df.columns:
        return {}
    return {str(key): int(value) for key, value in df[column].value_counts(dropna=False).items()}


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "- none"
    return "\n".join(f"- {key}: {value}" for key, value in counts.items())


def _split_reason(value: Any) -> list[str]:
    return [part.strip() for part in _clean_text(value).split(";") if part.strip()]


def _append_note(existing: Any, note: str) -> str:
    parts = [part for part in [_clean_text(existing), note] if part]
    return "; ".join(_dedupe(parts))


def _domain_matches(domain: str, official_domain: str) -> bool:
    domain = _normalize_domain(domain)
    official_domain = _normalize_domain(official_domain)
    return bool(domain and official_domain and (domain == official_domain or domain.endswith("." + official_domain)))


def _normalize_domain(value: Any) -> str:
    text = _clean_text(value).lower()
    if "://" in text:
        text = urlparse(text).netloc
    return text.split(":", 1)[0].removeprefix("www.")


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _clean_text(value).lower() in {"true", "1", "yes"}


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
