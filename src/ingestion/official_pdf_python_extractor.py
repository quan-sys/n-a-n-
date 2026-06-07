"""Python-native non-OCR PDF extraction for REAL-DATA-01I-F-PATCH2."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingestion.official_finance_value_parser import detect_field_name, detect_unit
from src.ingestion.official_pdf_backend_registry import get_pdf_backend_availability
from src.ingestion.official_pdf_text_extractor import (
    ExtractedPdfPage,
    ExtractedPdfTableCell,
    PdfExtractionDiagnostic,
    has_finance_keywords,
    short_finance_snippet,
)


PDF_EXTRACTION_DIAGNOSTIC_COLUMNS_01IF_PATCH2 = [
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

PAGE_TEXT_AUDIT_COLUMNS_01IF_PATCH2 = [
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

TABLE_CELL_COLUMNS_01IF_PATCH2 = [
    "ticker",
    "period",
    "local_path",
    "file_hash",
    "page_number",
    "backend",
    "table_index",
    "row_index",
    "col_index",
    "cell_text",
    "notes",
]


@dataclass(frozen=True)
class PythonPdfExtractionResult:
    pages: list[ExtractedPdfPage]
    table_cells: list[ExtractedPdfTableCell]
    diagnostics: list[PdfExtractionDiagnostic]
    page_count: int
    backend_text_pages: dict[str, list[ExtractedPdfPage]]


def extract_pdf_with_python_backends(
    local_path: str | Path,
    *,
    max_pages: int | None = 25,
    min_text_chars: int = 80,
    use_table_extraction: bool = True,
) -> PythonPdfExtractionResult:
    """Extract text and tables with installed Python PDF libraries only."""

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
        return PythonPdfExtractionResult(pages=[page], table_cells=[], diagnostics=[diagnostic], page_count=0, backend_text_pages={})

    availability = {row.backend: row for row in get_pdf_backend_availability()}
    diagnostics: list[PdfExtractionDiagnostic] = []
    backend_text_pages: dict[str, list[ExtractedPdfPage]] = {}
    page_count = 0

    if availability["pymupdf"].installed:
        try:
            pages, page_count = _extract_pymupdf_pages(path, max_pages=max_pages, min_text_chars=min_text_chars)
            backend_text_pages["pymupdf"] = pages
            diagnostics.append(_diagnostic("pymupdf", page_count, pages, []))
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(_failed_diagnostic("pymupdf", page_count, exc))
    else:
        diagnostics.append(_unavailable_diagnostic("pymupdf", page_count, availability["pymupdf"].import_error))

    pdfplumber_pages: list[ExtractedPdfPage] = []
    pdfplumber_cells: list[ExtractedPdfTableCell] = []
    if availability["pdfplumber"].installed:
        try:
            pdfplumber_pages, pdfplumber_cells, pdfplumber_page_count = _extract_pdfplumber_content(
                path,
                max_pages=max_pages,
                min_text_chars=min_text_chars,
                use_table_extraction=use_table_extraction,
                page_text_hints=_page_text_by_number(backend_text_pages.get("pymupdf", [])),
            )
            page_count = page_count or pdfplumber_page_count
            backend_text_pages["pdfplumber"] = pdfplumber_pages
            diagnostics.append(_diagnostic("pdfplumber", page_count, pdfplumber_pages, pdfplumber_cells))
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(_failed_diagnostic("pdfplumber", page_count, exc))
    else:
        diagnostics.append(_unavailable_diagnostic("pdfplumber", page_count, availability["pdfplumber"].import_error))

    if availability["pypdf"].installed:
        try:
            pypdf_pages, pypdf_page_count = _extract_pypdf_pages(path, max_pages=max_pages, min_text_chars=min_text_chars)
            page_count = page_count or pypdf_page_count
            backend_text_pages["pypdf"] = pypdf_pages
            diagnostics.append(_diagnostic("pypdf", page_count, pypdf_pages, []))
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(_failed_diagnostic("pypdf", page_count, exc))
    else:
        diagnostics.append(_unavailable_diagnostic("pypdf", page_count, availability["pypdf"].import_error))

    pages = _choose_best_pages(backend_text_pages)
    table_cells = pdfplumber_cells if use_table_extraction else []
    if not pages:
        pages = [ExtractedPdfPage(page_number=0, text="", extraction_status="DOCUMENT_NOT_TEXT_EXTRACTABLE", backend="none")]
    if not _has_any_text(pages, min_text_chars=min_text_chars) and not table_cells:
        diagnostics.append(
            PdfExtractionDiagnostic(
                backend="overall",
                page_count=page_count or len(pages),
                text_chars=sum(len(page.text.strip()) for page in pages),
                table_count=0,
                extract_status="SCANNED_OR_IMAGE_ONLY_REVIEW",
                notes="no non-OCR Python backend extracted usable text or tables",
            )
        )
    return PythonPdfExtractionResult(
        pages=pages,
        table_cells=table_cells,
        diagnostics=diagnostics,
        page_count=page_count or len(pages),
        backend_text_pages=backend_text_pages,
    )


def extract_pdfplumber_tables_for_pages(
    local_path: str | Path,
    *,
    selected_page_numbers: set[int],
    page_text_hints: dict[int, str] | None = None,
) -> tuple[list[ExtractedPdfTableCell], PdfExtractionDiagnostic]:
    """Extract pdfplumber tables only from selected statement pages."""

    path = Path(local_path)
    if not path.exists():
        return [], PdfExtractionDiagnostic(
            backend="pdfplumber_statement_pages",
            page_count=0,
            text_chars=0,
            table_count=0,
            extract_status="EXTRACTION_FAILED",
            error="DOCUMENT_NOT_FOUND",
            notes=str(path),
        )
    availability = {row.backend: row for row in get_pdf_backend_availability()}
    if not availability["pdfplumber"].installed:
        return [], PdfExtractionDiagnostic(
            backend="pdfplumber_statement_pages",
            page_count=0,
            text_chars=0,
            table_count=0,
            extract_status="BACKEND_UNAVAILABLE",
            error=availability["pdfplumber"].import_error,
            notes="pdfplumber unavailable; no OCR fallback attempted",
        )
    pdfplumber = import_module("pdfplumber")
    page_text_hints = page_text_hints or {}
    table_cells: list[ExtractedPdfTableCell] = []
    try:
        with pdfplumber.open(str(path)) as pdf:
            page_count = len(pdf.pages)
            for page_number in sorted(number for number in selected_page_numbers if 1 <= number <= page_count):
                page = pdf.pages[page_number - 1]
                text = page.extract_text() or ""
                tables = _extract_pdfplumber_tables(page)
                retained_tables = _retain_finance_tables(
                    tables=tables,
                    page_text=" ".join([page_text_hints.get(page_number, ""), text]),
                )
                for table_index, table in retained_tables:
                    for row_index, row in enumerate(table or [], start=1):
                        for col_index, cell in enumerate(row or [], start=1):
                            value = " ".join(str(cell or "").split())
                            if not value:
                                continue
                            table_cells.append(
                                ExtractedPdfTableCell(
                                    page_number=page_number,
                                    backend="pdfplumber_statement_pages",
                                    table_index=table_index,
                                    row_index=row_index,
                                    col_index=col_index,
                                    cell_text=value,
                                    notes="pdfplumber extraction limited to selected statement pages; no OCR",
                                )
                            )
        table_count = len({(cell.page_number, cell.table_index) for cell in table_cells})
        return table_cells, PdfExtractionDiagnostic(
            backend="pdfplumber_statement_pages",
            page_count=page_count,
            text_chars=sum(len(page_text_hints.get(number, "")) for number in selected_page_numbers),
            table_count=table_count,
            extract_status="TABLES_EXTRACTED" if table_count else "NO_TABLES_EXTRACTED",
            notes="statement-page-only table extraction; no OCR",
        )
    except Exception as exc:  # noqa: BLE001
        return [], PdfExtractionDiagnostic(
            backend="pdfplumber_statement_pages",
            page_count=0,
            text_chars=0,
            table_count=0,
            extract_status="TABLE_EXTRACTION_FAILED",
            error=f"{type(exc).__name__}:{exc}",
            notes="statement-page table extraction failed; no OCR fallback attempted",
        )


def extract_pdfplumber_all_tables_for_pages(
    local_path: str | Path,
    *,
    selected_page_numbers: set[int] | None = None,
    page_text_hints: dict[int, str] | None = None,
) -> tuple[list[ExtractedPdfTableCell], PdfExtractionDiagnostic]:
    """Extract all pdfplumber tables from selected pages without semantic filtering."""

    path = Path(local_path)
    if not path.exists():
        return [], PdfExtractionDiagnostic(
            backend="pdfplumber_numeric_table_dump",
            page_count=0,
            text_chars=0,
            table_count=0,
            extract_status="EXTRACTION_FAILED",
            error="DOCUMENT_NOT_FOUND",
            notes=str(path),
        )
    availability = {row.backend: row for row in get_pdf_backend_availability()}
    if not availability["pdfplumber"].installed:
        return [], PdfExtractionDiagnostic(
            backend="pdfplumber_numeric_table_dump",
            page_count=0,
            text_chars=0,
            table_count=0,
            extract_status="BACKEND_UNAVAILABLE",
            error=availability["pdfplumber"].import_error,
            notes="pdfplumber unavailable; no OCR fallback attempted",
        )
    pdfplumber = import_module("pdfplumber")
    page_text_hints = page_text_hints or {}
    table_cells: list[ExtractedPdfTableCell] = []
    try:
        with pdfplumber.open(str(path)) as pdf:
            page_count = len(pdf.pages)
            target_pages = selected_page_numbers or set(range(1, page_count + 1))
            for page_number in sorted(number for number in target_pages if 1 <= number <= page_count):
                page = pdf.pages[page_number - 1]
                tables = _extract_pdfplumber_tables(page)
                for table_index, table in tables:
                    for row_index, row in enumerate(table or [], start=1):
                        for col_index, cell in enumerate(row or [], start=1):
                            value = " ".join(str(cell or "").split())
                            if not value:
                                continue
                            table_cells.append(
                                ExtractedPdfTableCell(
                                    page_number=page_number,
                                    backend="pdfplumber_numeric_table_dump",
                                    table_index=table_index,
                                    row_index=row_index,
                                    col_index=col_index,
                                    cell_text=value,
                                    notes="raw numeric table dump extraction; no OCR",
                                )
                            )
        table_count = len({(cell.page_number, cell.table_index) for cell in table_cells})
        return table_cells, PdfExtractionDiagnostic(
            backend="pdfplumber_numeric_table_dump",
            page_count=page_count,
            text_chars=sum(len(page_text_hints.get(number, "")) for number in selected_page_numbers or []),
            table_count=table_count,
            extract_status="TABLES_EXTRACTED" if table_count else "NO_TABLES_EXTRACTED",
            notes="raw table extraction for numeric evidence dump; no OCR",
        )
    except Exception as exc:  # noqa: BLE001
        return [], PdfExtractionDiagnostic(
            backend="pdfplumber_numeric_table_dump",
            page_count=0,
            text_chars=0,
            table_count=0,
            extract_status="TABLE_EXTRACTION_FAILED",
            error=f"{type(exc).__name__}:{exc}",
            notes="numeric table dump extraction failed; no OCR fallback attempted",
        )


def build_python_pdf_diagnostic_rows(
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


def build_python_page_text_audit_rows(
    *,
    document_row: dict[str, Any] | pd.Series,
    pages: list[ExtractedPdfPage],
    max_snippet_chars: int = 320,
) -> list[dict[str, Any]]:
    rows = []
    for page in pages:
        unit_raw, _, _, unit_status = detect_unit(page.text)
        rows.append(
            {
                "ticker": document_row.get("ticker", ""),
                "period": document_row.get("period", ""),
                "local_path": document_row.get("local_path", ""),
                "file_hash": document_row.get("file_hash", ""),
                "page_number": page.page_number,
                "backend": page.backend,
                "text_char_count": len(str(page.text or "").strip()),
                "has_finance_keywords": has_finance_keywords(page.text),
                "detected_unit": unit_raw if unit_status == "UNIT_DETECTED" else "",
                "text_snippet": short_finance_snippet(page.text, max_chars=max_snippet_chars),
                "notes": page.extraction_status if page.extraction_status != "TEXT_EXTRACTED" else "short snippet only; no full PDF text stored",
            }
        )
    return rows


def build_python_table_cell_rows(
    *,
    document_row: dict[str, Any] | pd.Series,
    table_cells: list[ExtractedPdfTableCell],
) -> list[dict[str, Any]]:
    rows = []
    for cell in table_cells:
        rows.append(
            {
                "ticker": document_row.get("ticker", ""),
                "period": document_row.get("period", ""),
                "local_path": document_row.get("local_path", ""),
                "file_hash": document_row.get("file_hash", ""),
                "page_number": cell.page_number,
                "backend": cell.backend,
                "table_index": cell.table_index,
                "row_index": cell.row_index,
                "col_index": cell.col_index,
                "cell_text": str(cell.cell_text or "")[:240],
                "notes": cell.notes or "python pdf table cell; no OCR",
            }
        )
    return rows


def write_markdown_audit(
    *,
    document_row: dict[str, Any] | pd.Series,
    pages: list[ExtractedPdfPage],
    normalized_rows: pd.DataFrame,
    output_dir: str | Path,
    max_rows: int = 80,
) -> Path | None:
    finance_pages = [page for page in pages if has_finance_keywords(page.text)]
    doc_rows = normalized_rows if isinstance(normalized_rows, pd.DataFrame) else pd.DataFrame()
    if not finance_pages and doc_rows.empty:
        return None
    audit_dir = Path(output_dir) / "markdown_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    safe_ticker = str(document_row.get("ticker", "")).lower() or "unknown"
    safe_period = str(document_row.get("period", "")).lower().replace("-", "_") or "unknown"
    short_hash = str(document_row.get("file_hash", ""))[:16] or "nohash"
    path = audit_dir / f"{safe_ticker}_{safe_period}_{short_hash}.md"
    lines = [
        f"# PDF audit {document_row.get('ticker', '')} {document_row.get('period', '')}",
        "",
        "Markdown is for human audit only; structured CSV rows remain the source of truth.",
        "",
        f"- local_path: {document_row.get('local_path', '')}",
        f"- file_hash: {document_row.get('file_hash', '')}",
        "",
    ]
    for page in finance_pages[:8]:
        lines.extend(
            [
                f"## Page {page.page_number} ({page.backend})",
                "",
                short_finance_snippet(page.text, max_chars=500),
                "",
            ]
        )
    if not doc_rows.empty:
        lines.extend(["## Normalized Table Rows", ""])
        for _, row in doc_rows.head(max_rows).iterrows():
            lines.append(
                f"- p{row.get('page_number', '')} t{row.get('table_index', '')} r{row.get('row_index', '')}: "
                f"{row.get('label_guess', '')} | {row.get('numeric_values', '')} | unit={row.get('unit_guess', '')}"
            )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _extract_pymupdf_pages(
    path: Path,
    *,
    max_pages: int | None,
    min_text_chars: int,
) -> tuple[list[ExtractedPdfPage], int]:
    fitz = import_module("fitz")
    document = fitz.open(str(path))
    try:
        page_count = int(document.page_count)
        limit = min(page_count, max_pages) if max_pages else page_count
        pages = []
        for index in range(limit):
            page = document.load_page(index)
            text = page.get_text("text") or ""
            status = "TEXT_EXTRACTED" if len(text.strip()) >= min_text_chars else "DOCUMENT_NOT_TEXT_EXTRACTABLE"
            pages.append(ExtractedPdfPage(page_number=index + 1, text=text, extraction_status=status, backend="pymupdf"))
        return pages, page_count
    finally:
        document.close()


def _extract_pdfplumber_content(
    path: Path,
    *,
    max_pages: int | None,
    min_text_chars: int,
    use_table_extraction: bool,
    page_text_hints: dict[int, str],
) -> tuple[list[ExtractedPdfPage], list[ExtractedPdfTableCell], int]:
    pdfplumber = import_module("pdfplumber")
    pages: list[ExtractedPdfPage] = []
    table_cells: list[ExtractedPdfTableCell] = []
    with pdfplumber.open(str(path)) as pdf:
        page_count = len(pdf.pages)
        limit = min(page_count, max_pages) if max_pages else page_count
        for page_index, page in enumerate(pdf.pages[:limit], start=1):
            text = page.extract_text() or ""
            status = "TEXT_EXTRACTED" if len(text.strip()) >= min_text_chars else "DOCUMENT_NOT_TEXT_EXTRACTABLE"
            pages.append(ExtractedPdfPage(page_number=page_index, text=text, extraction_status=status, backend="pdfplumber"))
            if not use_table_extraction:
                continue
            tables = _extract_pdfplumber_tables(page)
            retained_tables = _retain_finance_tables(
                tables=tables,
                page_text=" ".join([page_text_hints.get(page_index, ""), text]),
            )
            for table_index, table in retained_tables:
                for row_index, row in enumerate(table or [], start=1):
                    for col_index, cell in enumerate(row or [], start=1):
                        value = " ".join(str(cell or "").split())
                        if not value:
                            continue
                        table_cells.append(
                            ExtractedPdfTableCell(
                                page_number=page_index,
                                backend="pdfplumber",
                                table_index=table_index,
                                row_index=row_index,
                                col_index=col_index,
                                cell_text=value,
                                notes="pdfplumber native table extraction; no OCR",
                            )
                        )
    return pages, table_cells, page_count


def _extract_pypdf_pages(
    path: Path,
    *,
    max_pages: int | None,
    min_text_chars: int,
) -> tuple[list[ExtractedPdfPage], int]:
    reader_class = getattr(import_module("pypdf"), "PdfReader")
    reader = reader_class(str(path))
    page_count = len(reader.pages)
    limit = min(page_count, max_pages) if max_pages else page_count
    pages = []
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
    return pages, page_count


def _extract_pdfplumber_tables(page: Any) -> list[tuple[int, list[list[Any]]]]:
    output = []
    seen: set[str] = set()
    settings = [
        None,
        {
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "snap_tolerance": 3,
            "join_tolerance": 3,
            "intersection_tolerance": 5,
        },
    ]
    for setting in settings:
        try:
            tables = page.extract_tables(table_settings=setting) if setting else page.extract_tables()
        except Exception:  # noqa: BLE001
            continue
        for table in tables or []:
            key = repr(table)
            if key in seen:
                continue
            seen.add(key)
            output.append((len(output) + 1, table))
    return output


def _retain_finance_tables(
    *,
    tables: list[tuple[int, list[list[Any]]]],
    page_text: str,
) -> list[tuple[int, list[list[Any]]]]:
    retained = []
    page_has_finance = has_finance_keywords(page_text) or detect_unit(page_text)[3] == "UNIT_DETECTED"
    for table_index, table in tables:
        table_text = " ".join(str(cell or "") for row in table or [] for cell in row or [])
        if page_has_finance or has_finance_keywords(table_text) or detect_field_name(table_text):
            retained.append((table_index, table))
    return retained


def _diagnostic(
    backend: str,
    page_count: int,
    pages: list[ExtractedPdfPage],
    table_cells: list[ExtractedPdfTableCell],
) -> PdfExtractionDiagnostic:
    text_chars = sum(len(page.text.strip()) for page in pages)
    table_count = len({(cell.page_number, cell.table_index) for cell in table_cells})
    if table_count:
        status = "TABLES_EXTRACTED"
    elif text_chars:
        status = "TEXT_EXTRACTED"
    else:
        status = "NO_TEXT_EXTRACTED"
    return PdfExtractionDiagnostic(
        backend=backend,
        page_count=page_count or len(pages),
        text_chars=text_chars,
        table_count=table_count,
        extract_status=status,
        notes="python-native non-OCR extraction",
    )


def _failed_diagnostic(backend: str, page_count: int, exc: Exception) -> PdfExtractionDiagnostic:
    return PdfExtractionDiagnostic(
        backend=backend,
        page_count=page_count,
        text_chars=0,
        table_count=0,
        extract_status="EXTRACTION_FAILED",
        error=f"{type(exc).__name__}:{exc}",
        notes="backend failed; no OCR fallback attempted",
    )


def _unavailable_diagnostic(backend: str, page_count: int, import_error: str) -> PdfExtractionDiagnostic:
    return PdfExtractionDiagnostic(
        backend=backend,
        page_count=page_count,
        text_chars=0,
        table_count=0,
        extract_status="BACKEND_UNAVAILABLE",
        error=import_error,
        notes="optional non-OCR backend unavailable",
    )


def _page_text_by_number(pages: list[ExtractedPdfPage]) -> dict[int, str]:
    return {page.page_number: page.text for page in pages}


def _choose_best_pages(backend_text_pages: dict[str, list[ExtractedPdfPage]]) -> list[ExtractedPdfPage]:
    for backend in ["pymupdf", "pdfplumber", "pypdf"]:
        pages = backend_text_pages.get(backend, [])
        if any(page.extraction_status == "TEXT_EXTRACTED" for page in pages):
            return pages
    for backend in ["pymupdf", "pdfplumber", "pypdf"]:
        if backend_text_pages.get(backend):
            return backend_text_pages[backend]
    return []


def _has_any_text(pages: list[ExtractedPdfPage], *, min_text_chars: int) -> bool:
    return any(len(str(page.text or "").strip()) >= min_text_chars for page in pages)
