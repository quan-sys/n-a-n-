"""Lightweight table audit extraction for REAL-DATA-01I-F.

This module records short table-like audit metadata only. It does not OCR and
does not store full copyrighted tables.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.ingestion.official_finance_value_parser import CANONICAL_FIELDS_01IF, detect_field_name, detect_unit, extract_numeric_tokens
from src.ingestion.official_pdf_text_extractor import ExtractedPdfTableCell, has_finance_keywords


RAW_TABLE_AUDIT_COLUMNS_01IF = [
    "ticker",
    "period",
    "local_path",
    "file_hash",
    "page_number",
    "table_index",
    "row_count",
    "column_count",
    "detected_unit",
    "notes",
]

TABLE_CELL_COLUMNS_01IF_PATCH1 = [
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
class FinanceTableRow:
    page_number: int
    backend: str
    table_index: int
    row_index: int
    cells: list[str]
    column_contexts: list[str]
    unit_context: str
    notes: str = ""


def build_raw_table_audit_rows(
    *,
    document_row: dict[str, Any] | pd.Series,
    pages: list[Any],
) -> list[dict[str, Any]]:
    rows = []
    for page in pages:
        text = getattr(page, "text", "")
        if getattr(page, "extraction_status", "") != "TEXT_EXTRACTED":
            continue
        table_lines = [
            line.strip()
            for line in str(text).splitlines()
            if line.strip() and detect_field_name(line) in CANONICAL_FIELDS_01IF and extract_numeric_tokens(line)
        ]
        if not table_lines:
            continue
        unit_raw, _, _, unit_status = detect_unit(text)
        max_numeric_count = max(len(extract_numeric_tokens(line)) for line in table_lines)
        rows.append(
            {
                "ticker": document_row.get("ticker", ""),
                "period": document_row.get("period", ""),
                "local_path": document_row.get("local_path", ""),
                "file_hash": document_row.get("file_hash", ""),
                "page_number": getattr(page, "page_number", ""),
                "table_index": 1,
                "row_count": len(table_lines),
                "column_count": max_numeric_count + 1,
                "detected_unit": unit_raw if unit_status == "UNIT_DETECTED" else "",
                "notes": "heuristic table-like audit metadata only; no full table stored",
            }
        )
    return rows


def build_table_cell_audit_rows(
    *,
    document_row: dict[str, Any] | pd.Series,
    table_cells: list[ExtractedPdfTableCell],
    pages: list[Any],
) -> list[dict[str, Any]]:
    """Return short table cell audit rows from finance-related pages only."""

    finance_pages = _finance_pages(pages, table_cells)
    rows = []
    for cell in table_cells:
        if cell.page_number not in finance_pages:
            continue
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
                "notes": cell.notes or "table cell retained for finance parser audit; no OCR",
            }
        )
    return rows


def build_finance_table_rows(
    *,
    document_row: dict[str, Any] | pd.Series,
    pages: list[Any],
    table_cells: list[ExtractedPdfTableCell],
) -> list[FinanceTableRow]:
    """Build explicit table-like rows for finance value parsing."""

    del document_row
    rows = []
    rows.extend(_rows_from_extracted_table_cells(pages=pages, table_cells=table_cells))
    rows.extend(_rows_from_table_like_text(pages=pages))
    return rows


def _rows_from_extracted_table_cells(
    *,
    pages: list[Any],
    table_cells: list[ExtractedPdfTableCell],
) -> list[FinanceTableRow]:
    page_text = {int(getattr(page, "page_number", 0)): str(getattr(page, "text", "") or "") for page in pages}
    grouped: dict[tuple[int, str, int, int], list[ExtractedPdfTableCell]] = {}
    for cell in table_cells:
        if not str(cell.cell_text or "").strip():
            continue
        grouped.setdefault((cell.page_number, cell.backend, cell.table_index, cell.row_index), []).append(cell)

    output = []
    header_by_table: dict[tuple[int, str, int], list[str]] = {}
    for key in sorted(grouped):
        page_number, backend, table_index, row_index = key
        sorted_cells = sorted(grouped[key], key=lambda cell: cell.col_index)
        cells = [str(cell.cell_text or "").strip() for cell in sorted_cells]
        table_key = (page_number, backend, table_index)
        if _is_header_row(cells):
            header_by_table[table_key] = cells
            continue
        if not _row_has_finance_signal(cells):
            continue
        unit_context = " ".join([page_text.get(page_number, ""), " ".join(header_by_table.get(table_key, [])), " ".join(cells)])
        output.append(
            FinanceTableRow(
                page_number=page_number,
                backend=backend,
                table_index=table_index,
                row_index=row_index,
                cells=cells,
                column_contexts=header_by_table.get(table_key, []),
                unit_context=unit_context,
                notes="extracted table row; no OCR",
            )
        )
    return output


def _rows_from_table_like_text(*, pages: list[Any]) -> list[FinanceTableRow]:
    output = []
    for page in pages:
        if getattr(page, "extraction_status", "") != "TEXT_EXTRACTED":
            continue
        text = str(getattr(page, "text", "") or "")
        unit_raw, _, _, unit_status = detect_unit(text)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for row_index, line in enumerate(lines, start=1):
            cells = _split_table_like_line(line)
            if not _row_has_finance_signal(cells):
                continue
            if not any(extract_numeric_tokens(cell) for cell in cells):
                continue
            output.append(
                FinanceTableRow(
                    page_number=int(getattr(page, "page_number", 0)),
                    backend=f"{getattr(page, 'backend', '') or 'text'}_line_heuristic",
                    table_index=0,
                    row_index=row_index,
                    cells=cells,
                    column_contexts=[],
                    unit_context=f"{unit_raw if unit_status == 'UNIT_DETECTED' else ''} {text[:600]}",
                    notes="text line looked table-like with explicit label and numeric token; no OCR",
                )
            )
    return output


def _finance_pages(pages: list[Any], table_cells: list[ExtractedPdfTableCell]) -> set[int]:
    output = {
        int(getattr(page, "page_number", 0))
        for page in pages
        if has_finance_keywords(getattr(page, "text", ""))
    }
    grouped_text: dict[int, str] = {}
    for cell in table_cells:
        grouped_text[cell.page_number] = f"{grouped_text.get(cell.page_number, '')} {cell.cell_text}"
    for page_number, text in grouped_text.items():
        if has_finance_keywords(text):
            output.add(page_number)
    return output


def _row_has_finance_signal(cells: list[str]) -> bool:
    text = " ".join(str(cell or "") for cell in cells)
    return bool(detect_field_name(text) or has_finance_keywords(text))


def _is_header_row(cells: list[str]) -> bool:
    text = " ".join(str(cell or "").lower() for cell in cells)
    if detect_field_name(text):
        return False
    return bool(
        re.search(r"\b(20\d{2}|31/|30/|01/|current|previous|this quarter|period|quarter|year|accumulated|luy ke|lũy kế)\b", text)
        and len(cells) >= 2
    )


def _split_table_like_line(line: str) -> list[str]:
    clean = " ".join(str(line or "").split())
    if not clean:
        return []
    if "|" in clean:
        return [part.strip() for part in clean.split("|") if part.strip()]
    parts = [part.strip() for part in re.split(r"\s{2,}|\t+", str(line or "")) if part.strip()]
    if len(parts) >= 2:
        return parts
    numeric_tokens = extract_numeric_tokens(clean)
    if not numeric_tokens:
        return [clean]
    first_numeric = numeric_tokens[0]
    index = clean.find(first_numeric)
    if index <= 0:
        return [clean]
    return [clean[:index].strip(), clean[index:].strip()]
