"""PDF text/table extraction for REAL-DATA-01I-F.

No OCR is attempted here. Scanned or otherwise textless PDFs stay unresolved.
Optional backends are used only when installed; missing backends are recorded in
diagnostics instead of becoming hard runtime dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

try:
    import fitz
except ImportError:  # pragma: no cover
    fitz = None

try:
    import pdfplumber
except ImportError:  # pragma: no cover
    pdfplumber = None

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None


PDF_EXTRACTION_DIAGNOSTIC_COLUMNS_01IF_PATCH1 = [
    "ticker",
    "period",
    "local_path",
    "file_hash",
    "page_count",
    "backend",
    "text_chars",
    "table_count",
    "extract_status",
    "error",
    "notes",
]

PAGE_TEXT_AUDIT_COLUMNS_01IF_PATCH1 = [
    "ticker",
    "period",
    "local_path",
    "file_hash",
    "page_number",
    "backend",
    "text_char_count",
    "has_finance_keywords",
    "detected_unit",
    "text_snippet",
    "notes",
]


@dataclass(frozen=True)
class ExtractedPdfPage:
    page_number: int
    text: str
    extraction_status: str
    notes: str = ""
    backend: str = ""


@dataclass(frozen=True)
class ExtractedPdfTableCell:
    page_number: int
    backend: str
    table_index: int
    row_index: int
    col_index: int
    cell_text: str
    notes: str = ""


@dataclass(frozen=True)
class PdfExtractionDiagnostic:
    backend: str
    page_count: int
    text_chars: int
    table_count: int
    extract_status: str
    error: str = ""
    notes: str = ""


@dataclass(frozen=True)
class PdfExtractionResult:
    pages: list[ExtractedPdfPage]
    table_cells: list[ExtractedPdfTableCell]
    diagnostics: list[PdfExtractionDiagnostic]
    page_count: int


def extract_pdf_text_pages(
    local_path: str | Path,
    *,
    max_pages: int | None = 25,
    min_text_chars: int = 80,
) -> list[ExtractedPdfPage]:
    """Return extracted text pages from a PDF without OCR."""

    result = extract_pdf_document_content(
        local_path,
        max_pages=max_pages,
        min_text_chars=min_text_chars,
        use_table_extraction=False,
    )
    return result.pages


def extract_pdf_document_content(
    local_path: str | Path,
    *,
    max_pages: int | None = 25,
    min_text_chars: int = 80,
    use_table_extraction: bool = False,
) -> PdfExtractionResult:
    """Extract PDF text and optional table cells via available non-OCR backends."""

    path = Path(local_path)
    if not path.exists():
        diagnostic = PdfExtractionDiagnostic(
            backend="document",
            page_count=0,
            text_chars=0,
            table_count=0,
            extract_status="EXTRACTION_FAILED",
            error="DOCUMENT_NOT_FOUND",
            notes=str(path),
        )
        page = ExtractedPdfPage(page_number=0, text="", extraction_status="DOCUMENT_NOT_FOUND", notes=str(path), backend="document")
        return PdfExtractionResult(pages=[page], table_cells=[], diagnostics=[diagnostic], page_count=0)

    page_count = _read_page_count(path)
    diagnostics: list[PdfExtractionDiagnostic] = []
    backend_results: list[tuple[str, list[ExtractedPdfPage], list[ExtractedPdfTableCell], PdfExtractionDiagnostic]] = []

    backend_specs = [
        ("pymupdf", fitz, _extract_with_pymupdf),
        ("pdfplumber", pdfplumber, _extract_with_pdfplumber),
        ("pypdf", PdfReader, _extract_with_pypdf),
    ]
    for backend_name, module, extractor in backend_specs:
        if module is None:
            diagnostics.append(
                PdfExtractionDiagnostic(
                    backend=backend_name,
                    page_count=page_count,
                    text_chars=0,
                    table_count=0,
                    extract_status="BACKEND_UNAVAILABLE",
                    notes="optional backend not installed; no OCR attempted",
                )
            )
            continue
        try:
            pages, cells = extractor(
                path,
                max_pages=max_pages,
                min_text_chars=min_text_chars,
                use_table_extraction=use_table_extraction,
            )
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                PdfExtractionDiagnostic(
                    backend=backend_name,
                    page_count=page_count,
                    text_chars=0,
                    table_count=0,
                    extract_status="EXTRACTION_FAILED",
                    error=f"{type(exc).__name__}:{exc}",
                    notes="backend failed without OCR fallback",
                )
            )
            continue
        text_chars = sum(len(page.text.strip()) for page in pages)
        table_count = len({(cell.page_number, cell.table_index) for cell in cells})
        status = _backend_extract_status(text_chars=text_chars, table_count=table_count, min_text_chars=min_text_chars)
        diagnostic = PdfExtractionDiagnostic(
            backend=backend_name,
            page_count=page_count or len(pages),
            text_chars=text_chars,
            table_count=table_count,
            extract_status=status,
            notes="non-OCR extraction attempted",
        )
        diagnostics.append(diagnostic)
        backend_results.append((backend_name, pages, cells, diagnostic))
        if status in {"TEXT_EXTRACTED", "TABLES_EXTRACTED"}:
            return PdfExtractionResult(pages=pages, table_cells=cells, diagnostics=diagnostics, page_count=page_count or len(pages))

    fallback_pages: list[ExtractedPdfPage] = []
    fallback_cells: list[ExtractedPdfTableCell] = []
    for backend_name, pages, cells, _ in backend_results:
        if backend_name == "pypdf" and pages:
            fallback_pages = pages
            fallback_cells = cells
            break
    if not fallback_pages:
        fallback_pages = [ExtractedPdfPage(page_number=0, text="", extraction_status="DOCUMENT_NOT_TEXT_EXTRACTABLE", backend="none")]
    diagnostics.append(
        PdfExtractionDiagnostic(
            backend="overall",
            page_count=page_count or len(fallback_pages),
            text_chars=sum(len(page.text.strip()) for page in fallback_pages),
            table_count=len({(cell.page_number, cell.table_index) for cell in fallback_cells}),
            extract_status="SCANNED_OR_IMAGE_ONLY_REVIEW",
            notes="no available non-OCR backend extracted usable text or tables",
        )
    )
    return PdfExtractionResult(pages=fallback_pages, table_cells=fallback_cells, diagnostics=diagnostics, page_count=page_count or len(fallback_pages))


def build_pdf_extraction_diagnostic_rows(
    *,
    document_row: dict[str, Any] | pd.Series,
    diagnostics: list[PdfExtractionDiagnostic],
) -> list[dict[str, Any]]:
    rows = []
    for diagnostic in diagnostics:
        rows.append(
            {
                "ticker": document_row.get("ticker", ""),
                "period": document_row.get("period", ""),
                "local_path": document_row.get("local_path", ""),
                "file_hash": document_row.get("file_hash", ""),
                "page_count": diagnostic.page_count,
                "backend": diagnostic.backend,
                "text_chars": diagnostic.text_chars,
                "table_count": diagnostic.table_count,
                "extract_status": diagnostic.extract_status,
                "error": diagnostic.error,
                "notes": diagnostic.notes,
            }
        )
    return rows


def build_page_text_audit_rows(
    *,
    document_row: dict[str, Any] | pd.Series,
    pages: list[ExtractedPdfPage],
    detected_unit_by_page: dict[int, str],
    max_snippet_chars: int = 320,
) -> list[dict[str, Any]]:
    rows = []
    for page in pages:
        text = page.text or ""
        snippet = short_finance_snippet(text, max_chars=max_snippet_chars)
        rows.append(
            {
                "ticker": document_row.get("ticker", ""),
                "period": document_row.get("period", ""),
                "local_path": document_row.get("local_path", ""),
                "file_hash": document_row.get("file_hash", ""),
                "page_number": page.page_number,
                "backend": page.backend,
                "text_char_count": len(text.strip()),
                "has_finance_keywords": has_finance_keywords(text),
                "detected_unit": detected_unit_by_page.get(page.page_number, ""),
                "text_snippet": snippet,
                "notes": page.extraction_status if page.extraction_status != "TEXT_EXTRACTED" else "short snippet only; no full PDF text stored",
            }
        )
    return rows


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


def has_finance_keywords(text: Any) -> bool:
    normalized = " ".join(str(text or "").lower().split())
    keywords = [
        "doanh thu",
        "loi nhuan",
        "lợi nhuận",
        "tong tai san",
        "tổng tài sản",
        "von chu so huu",
        "vốn chủ sở hữu",
        "luu chuyen tien",
        "lưu chuyển tiền",
        "revenue",
        "profit",
        "total assets",
        "equity",
        "cash flows",
        "statement of financial position",
        "financial statements",
        "balance sheet",
    ]
    return any(keyword in normalized for keyword in keywords)


def _extract_with_pymupdf(
    path: Path,
    *,
    max_pages: int | None,
    min_text_chars: int,
    use_table_extraction: bool,
) -> tuple[list[ExtractedPdfPage], list[ExtractedPdfTableCell]]:
    del use_table_extraction
    if fitz is None:  # pragma: no cover
        return [], []
    document = fitz.open(str(path))
    limit = min(document.page_count, max_pages) if max_pages else document.page_count
    pages = []
    for index in range(limit):
        page = document.load_page(index)
        text = page.get_text("text") or ""
        status = "TEXT_EXTRACTED" if len(text.strip()) >= min_text_chars else "DOCUMENT_NOT_TEXT_EXTRACTABLE"
        pages.append(ExtractedPdfPage(page_number=index + 1, text=text, extraction_status=status, backend="pymupdf"))
    document.close()
    return pages or [ExtractedPdfPage(page_number=0, text="", extraction_status="DOCUMENT_NOT_TEXT_EXTRACTABLE", backend="pymupdf")], []


def _extract_with_pdfplumber(
    path: Path,
    *,
    max_pages: int | None,
    min_text_chars: int,
    use_table_extraction: bool,
) -> tuple[list[ExtractedPdfPage], list[ExtractedPdfTableCell]]:
    if pdfplumber is None:  # pragma: no cover
        return [], []
    pages: list[ExtractedPdfPage] = []
    table_cells: list[ExtractedPdfTableCell] = []
    with pdfplumber.open(str(path)) as pdf:
        limit = min(len(pdf.pages), max_pages) if max_pages else len(pdf.pages)
        for page_index, page in enumerate(pdf.pages[:limit], start=1):
            text = page.extract_text() or ""
            status = "TEXT_EXTRACTED" if len(text.strip()) >= min_text_chars else "DOCUMENT_NOT_TEXT_EXTRACTABLE"
            pages.append(ExtractedPdfPage(page_number=page_index, text=text, extraction_status=status, backend="pdfplumber"))
            if not use_table_extraction:
                continue
            try:
                tables = page.extract_tables() or []
            except Exception as exc:  # noqa: BLE001
                table_cells.append(
                    ExtractedPdfTableCell(
                        page_number=page_index,
                        backend="pdfplumber",
                        table_index=0,
                        row_index=0,
                        col_index=0,
                        cell_text="",
                        notes=f"TABLE_EXTRACTION_FAILED:{type(exc).__name__}:{exc}",
                    )
                )
                continue
            for table_index, table in enumerate(tables, start=1):
                for row_index, row in enumerate(table or [], start=1):
                    for col_index, cell in enumerate(row or [], start=1):
                        value = " ".join(str(cell or "").split())
                        if value:
                            table_cells.append(
                                ExtractedPdfTableCell(
                                    page_number=page_index,
                                    backend="pdfplumber",
                                    table_index=table_index,
                                    row_index=row_index,
                                    col_index=col_index,
                                    cell_text=value,
                                    notes="pdfplumber table cell; no OCR",
                                )
                            )
    return pages or [ExtractedPdfPage(page_number=0, text="", extraction_status="DOCUMENT_NOT_TEXT_EXTRACTABLE", backend="pdfplumber")], table_cells


def _extract_with_pypdf(
    path: Path,
    *,
    max_pages: int | None,
    min_text_chars: int,
    use_table_extraction: bool,
) -> tuple[list[ExtractedPdfPage], list[ExtractedPdfTableCell]]:
    del use_table_extraction
    if PdfReader is None:
        raise ImportError("pypdf is required for official PDF text extraction.")
    reader = PdfReader(str(path))
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
                    extraction_status="EXTRACTION_FAILED",
                    notes=f"{type(exc).__name__}:{exc}",
                    backend="pypdf",
                )
            )
            continue
        status = "TEXT_EXTRACTED" if len(text.strip()) >= min_text_chars else "DOCUMENT_NOT_TEXT_EXTRACTABLE"
        pages.append(ExtractedPdfPage(page_number=index + 1, text=text, extraction_status=status, backend="pypdf"))
    if not pages:
        return [ExtractedPdfPage(page_number=0, text="", extraction_status="DOCUMENT_NOT_TEXT_EXTRACTABLE", backend="pypdf")], []
    return pages, []


def _read_page_count(path: Path) -> int:
    if PdfReader is None:
        return 0
    try:
        return len(PdfReader(str(path)).pages)
    except Exception:  # noqa: BLE001
        return 0


def _backend_extract_status(*, text_chars: int, table_count: int, min_text_chars: int) -> str:
    if table_count > 0:
        return "TABLES_EXTRACTED"
    if text_chars >= min_text_chars:
        return "TEXT_EXTRACTED"
    return "NO_TEXT_EXTRACTED"
