"""Downloader for REAL-DATA-01I-B official finance documents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import sleep
from typing import Any, Callable
from urllib.parse import urlparse

import pandas as pd

from src.ingestion.secret_redaction import redact_snapshot_bytes

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


DOCUMENT_INDEX_COLUMNS = [
    "ticker",
    "exchange",
    "company_name",
    "period",
    "document_type",
    "source_type",
    "source_name",
    "source_url",
    "official_domain",
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

MANUAL_REVIEW_COLUMNS = [
    "ticker",
    "period",
    "document_type",
    "source_url",
    "issue",
    "manual_review_required",
    "priority",
    "notes",
]

VALID_DOWNLOAD_STATUSES = {
    "DRY_RUN_VALIDATED",
    "DOWNLOADED",
    "HTML_SNAPSHOT_SAVED",
    "SOURCE_URL_INVALID",
    "SOURCE_UNAVAILABLE",
    "SOURCE_BLOCKED_OR_JS_REQUIRED",
    "SOURCE_CONTENT_TYPE_UNSUPPORTED",
    "DOMAIN_MISMATCH_REVIEW",
    "FILE_TYPE_MISMATCH_REVIEW",
    "DOWNLOAD_FAILED",
    "MANUAL_REVIEW",
}


@dataclass(frozen=True)
class DocumentFetchResponse:
    url: str
    final_url: str
    status_code: int | None
    content_type: str
    body: bytes
    error: str = ""


def download_seed_documents(
    seed_rows: pd.DataFrame,
    *,
    raw_output_dir: str | Path,
    request_sleep_seconds: float = 0,
    timeout_seconds: int = 25,
    max_documents: int | None = None,
    allowed_domains: set[str] | None = None,
    http_get: Callable[..., DocumentFetchResponse] | None = None,
    dry_run: bool = False,
) -> dict[str, pd.DataFrame]:
    rows = []
    review_rows = []
    selected = seed_rows.head(max_documents) if max_documents else seed_rows
    for _, seed_row in selected.iterrows():
        index_row = download_one_seed_document(
            seed_row.to_dict(),
            raw_output_dir=raw_output_dir,
            timeout_seconds=timeout_seconds,
            allowed_domains=allowed_domains,
            http_get=http_get,
            dry_run=dry_run,
        )
        rows.append(index_row)
        if index_row["manual_review_required"]:
            review_rows.append(manual_review_row_from_index(index_row))
        if request_sleep_seconds and not dry_run:
            sleep(float(request_sleep_seconds))
    return {
        "finance_document_index": pd.DataFrame(rows, columns=DOCUMENT_INDEX_COLUMNS),
        "manual_review_queue": pd.DataFrame(review_rows, columns=MANUAL_REVIEW_COLUMNS),
    }


def download_one_seed_document(
    seed_row: dict[str, Any],
    *,
    raw_output_dir: str | Path,
    timeout_seconds: int = 25,
    allowed_domains: set[str] | None = None,
    http_get: Callable[..., DocumentFetchResponse] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    row = _base_index_row(seed_row)
    source_url = str(row["source_url"])
    if not _is_public_http_url(source_url):
        return _finish(row, "SOURCE_URL_INVALID", True, "SOURCE_URL_INVALID", "high", "only public http/https URLs are allowed")

    expected_domain = _normalize_domain(row["official_domain"])
    source_domain = _normalize_domain(urlparse(source_url).netloc)
    if allowed_domains and source_domain not in allowed_domains:
        return _finish(row, "DOMAIN_MISMATCH_REVIEW", True, "DOMAIN_NOT_IN_ALLOWED_LIST", "high", "source domain is not in allowed domains file")
    domain_mismatch = bool(expected_domain and source_domain and not _domain_matches(source_domain, expected_domain))

    if dry_run:
        row["detected_file_type"] = str(row.get("expected_file_type", "")).lower() or "unknown"
        status = "DOMAIN_MISMATCH_REVIEW" if domain_mismatch else "DRY_RUN_VALIDATED"
        return _finish(
            row,
            status,
            domain_mismatch,
            "DOMAIN_MISMATCH_REVIEW" if domain_mismatch else "",
            "high" if domain_mismatch else "low",
            "dry-run validation only; no document downloaded",
        )

    fetch = http_get or _requests_get
    try:
        response = fetch(url=source_url, timeout_seconds=timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        return _finish(row, "DOWNLOAD_FAILED", True, "DOWNLOAD_FAILED", "medium", f"{type(exc).__name__}:{exc}")

    row["final_url"] = response.final_url or response.url
    row["http_status"] = response.status_code or ""
    row["content_type"] = response.content_type
    if response.error or response.status_code is None or response.status_code >= 500 or response.status_code >= 400:
        return _finish(row, "SOURCE_UNAVAILABLE", True, "SOURCE_UNAVAILABLE", "medium", response.error or f"HTTP_STATUS:{response.status_code}")
    if not response.body:
        return _finish(row, "SOURCE_UNAVAILABLE", True, "SOURCE_EMPTY_RESPONSE", "medium", "empty response body")

    detected = detect_file_type(response.content_type, response.body)
    row["detected_file_type"] = detected
    if detected == "html" and is_blocked_or_js_html(response.body):
        path, digest = save_document(response.body, raw_output_dir, row, detected)
        row["local_path"] = path
        row["file_hash"] = digest
        return _finish(row, "SOURCE_BLOCKED_OR_JS_REQUIRED", True, "SOURCE_BLOCKED_OR_JS_REQUIRED", "high", "HTML page appears blocked, JS-only, login, or CAPTCHA")
    if detected == "unknown":
        return _finish(row, "SOURCE_CONTENT_TYPE_UNSUPPORTED", True, "SOURCE_CONTENT_TYPE_UNSUPPORTED", "medium", "unsupported or unknown content type")

    path, digest = save_document(response.body, raw_output_dir, row, detected)
    row["local_path"] = path
    row["file_hash"] = digest
    expected_file_type = str(row.get("expected_file_type", "unknown")).lower()
    if expected_file_type != "unknown" and expected_file_type != detected:
        return _finish(row, "FILE_TYPE_MISMATCH_REVIEW", True, "FILE_TYPE_MISMATCH_REVIEW", "high", f"expected {expected_file_type}, detected {detected}")
    if domain_mismatch:
        return _finish(row, "DOMAIN_MISMATCH_REVIEW", True, "DOMAIN_MISMATCH_REVIEW", "high", f"source domain {source_domain} differs from official domain {expected_domain}")
    status = "HTML_SNAPSHOT_SAVED" if detected == "html" else "DOWNLOADED"
    return _finish(row, status, False, "", "low", "document saved; no finance values parsed in 01I-B")


def detect_file_type(content_type: str, body: bytes) -> str:
    lower = str(content_type).lower()
    prefix = body[:16].lower()
    if "pdf" in lower or body.startswith(b"%PDF"):
        return "pdf"
    if "spreadsheet" in lower or "excel" in lower or prefix.startswith(b"pk\x03\x04"):
        return "xlsx"
    if "ms-excel" in lower or prefix.startswith(b"\xd0\xcf\x11\xe0"):
        return "xls"
    if "html" in lower or b"<html" in body[:500].lower() or b"<!doctype html" in body[:500].lower():
        return "html"
    return "unknown"


def is_blocked_or_js_html(body: bytes) -> bool:
    text = body[:100_000].decode("utf-8", errors="ignore").lower()
    blocked = ["captcha", "access denied", "forbidden", "dang nhap", "login required", "cloudflare"]
    js_markers = ["__next", "app-root", "window.__", "enable javascript", "document.createelement"]
    return any(marker in text for marker in blocked) or sum(marker in text for marker in js_markers) >= 2


def save_document(body: bytes, raw_output_dir: str | Path, row: dict[str, Any], detected_file_type: str) -> tuple[str, str]:
    body_to_save = (
        redact_snapshot_bytes(body, content_type="text/html", file_suffix="html")
        if detected_file_type == "html"
        else body
    )
    digest = sha256(body_to_save).hexdigest()
    directory = Path(raw_output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    ticker = _safe_token(row.get("ticker", "unknown"))
    period = _safe_token(row.get("period", "unknown"))
    doc_type = _safe_token(row.get("document_type", "document"))
    suffix = "html" if detected_file_type == "html" else detected_file_type
    path = directory / f"{ticker}_{period}_{doc_type}_{digest[:16]}.{suffix}"
    if not path.exists():
        path.write_bytes(body_to_save)
    return str(path), digest


def manual_review_row_from_index(row: dict[str, Any]) -> dict[str, Any]:
    priority = "high" if row.get("download_status") in {"DOMAIN_MISMATCH_REVIEW", "FILE_TYPE_MISMATCH_REVIEW", "SOURCE_BLOCKED_OR_JS_REQUIRED", "SOURCE_URL_INVALID"} else "medium"
    if "EXAMPLE_ONLY" in str(row.get("notes", "")):
        priority = "low"
    return {
        "ticker": row.get("ticker", ""),
        "period": row.get("period", ""),
        "document_type": row.get("document_type", ""),
        "source_url": row.get("source_url", ""),
        "issue": row.get("review_reason", ""),
        "manual_review_required": True,
        "priority": priority,
        "notes": row.get("notes", ""),
    }


def _requests_get(*, url: str, timeout_seconds: int) -> DocumentFetchResponse:
    if requests is None:
        raise ImportError("requests is required for real document downloads.")
    headers = {"User-Agent": "VietnameseStockPipeline/01I-B official-document-research"}
    response = requests.get(url, headers=headers, timeout=timeout_seconds, verify=True)
    return DocumentFetchResponse(
        url=url,
        final_url=str(response.url),
        status_code=int(response.status_code),
        content_type=str(response.headers.get("content-type", "")),
        body=bytes(response.content),
        error="",
    )


def _base_index_row(seed_row: dict[str, Any]) -> dict[str, Any]:
    row = {column: seed_row.get(column, "") for column in DOCUMENT_INDEX_COLUMNS}
    for column in ["ticker", "exchange", "company_name", "period", "document_type", "source_type", "source_name", "source_url", "official_domain"]:
        row[column] = str(seed_row.get(column, "")).strip()
    row["expected_file_type"] = str(seed_row.get("expected_file_type", "")).strip().lower()
    row["downloaded_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    row["document_confidence"] = str(seed_row.get("confidence_seed", "low")).strip().lower() or "low"
    row["notes"] = str(seed_row.get("notes", "")).strip()
    return row


def _finish(row: dict[str, Any], status: str, manual_review: bool, reason: str, priority: str, note: str) -> dict[str, Any]:
    assert status in VALID_DOWNLOAD_STATUSES
    row["download_status"] = status
    row["manual_review_required"] = bool(manual_review)
    row["review_reason"] = reason
    existing = str(row.get("notes", "")).strip()
    row["notes"] = "; ".join(part for part in [existing, note] if part)
    if manual_review and priority == "high":
        row["document_confidence"] = "low"
    return {column: row.get(column, "") for column in DOCUMENT_INDEX_COLUMNS}


def _is_public_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _domain_matches(source_domain: str, official_domain: str) -> bool:
    return source_domain == official_domain or source_domain.endswith("." + official_domain)


def _normalize_domain(value: Any) -> str:
    text = str(value or "").strip().lower()
    if "://" in text:
        text = urlparse(text).netloc
    return text.split(":", 1)[0].removeprefix("www.")


def _safe_token(value: Any) -> str:
    return "".join(char if char.isalnum() else "_" for char in str(value).lower()).strip("_") or "unknown"
