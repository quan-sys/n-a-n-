"""Text-only PDF extraction for REAL-DATA-01I-F.

No OCR is attempted here. Scanned or otherwise textless PDFs stay unresolved.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None


@dataclass(frozen=True)
class ExtractedPdfPage:
    page_number: int
    text: str
    extraction_status: str
    notes: str = ""


def extract_pdf_text_pages(
    local_path: str | Path,
    *,
    max_pages: int | None = 25,
    min_text_chars: int = 80,
) -> list[ExtractedPdfPage]:
    """Return extracted text pages from a PDF without OCR."""

    path = Path(local_path)
    if PdfReader is None:
        raise ImportError("pypdf is required for official PDF text extraction.")
    if not path.exists():
        return [ExtractedPdfPage(page_number=0, text="", extraction_status="DOCUMENT_NOT_FOUND", notes=str(path))]
    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001
        return [ExtractedPdfPage(page_number=0, text="", extraction_status="TABLE_EXTRACTION_FAILED", notes=f"{type(exc).__name__}:{exc}")]
    pages = []
    page_count = len(reader.pages)
    limit = min(page_count, max_pages) if max_pages else page_count
    for index in range(limit):
        try:
            text = reader.pages[index].extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            pages.append(
                ExtractedPdfPage(
                    page_number=index + 1,
                    text="",
                    extraction_status="TABLE_EXTRACTION_FAILED",
                    notes=f"{type(exc).__name__}:{exc}",
                )
            )
            continue
        status = "TEXT_EXTRACTED" if len(text.strip()) >= min_text_chars else "DOCUMENT_NOT_TEXT_EXTRACTABLE"
        pages.append(ExtractedPdfPage(page_number=index + 1, text=text, extraction_status=status))
    if not pages:
        return [ExtractedPdfPage(page_number=0, text="", extraction_status="DOCUMENT_NOT_TEXT_EXTRACTABLE")]
    return pages


def build_raw_text_audit_rows(
    *,
    document_row: dict[str, Any] | pd.Series,
    pages: list[ExtractedPdfPage],
    detected_unit_by_page: dict[int, str],
    max_snippet_chars: int = 320,
) -> list[dict[str, Any]]:
    rows = []
    for page in pages:
        snippet = short_finance_snippet(page.text, max_chars=max_snippet_chars)
        if not snippet and page.extraction_status == "TEXT_EXTRACTED":
            continue
        rows.append(
            {
                "ticker": document_row.get("ticker", ""),
                "period": document_row.get("period", ""),
                "local_path": document_row.get("local_path", ""),
                "file_hash": document_row.get("file_hash", ""),
                "page_number": page.page_number,
                "text_snippet": snippet,
                "detected_unit": detected_unit_by_page.get(page.page_number, ""),
                "notes": page.extraction_status if page.extraction_status != "TEXT_EXTRACTED" else "short snippet only; no full PDF text stored",
            }
        )
    return rows


def short_finance_snippet(text: str, *, max_chars: int = 320) -> str:
    clean = " ".join(str(text or "").split())
    if not clean:
        return ""
    lower = clean.lower()
    anchors = [
        "doanh thu",
        "profit after tax",
        "total assets",
        "tong tai san",
        "lợi nhuận",
        "cash flows",
        "bảng cân đối",
        "statement of financial position",
    ]
    start = 0
    for anchor in anchors:
        pos = lower.find(anchor.lower())
        if pos >= 0:
            start = max(0, pos - 80)
            break
    snippet = clean[start : start + max_chars].strip()
    return snippet
