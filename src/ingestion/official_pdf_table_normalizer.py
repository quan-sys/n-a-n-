"""Normalize Python-extracted PDF table cells into finance table rows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.ingestion.official_finance_value_parser import detect_field_name, detect_unit, extract_numeric_tokens
from src.ingestion.official_pdf_text_extractor import ExtractedPdfPage, ExtractedPdfTableCell, has_finance_keywords


NORMALIZED_TABLE_ROW_COLUMNS_01IF_PATCH2 = [
    "ticker",
    "period",
    "local_path",
    "file_hash",
    "page_number",
    "backend",
    "table_index",
    "row_index",
    "row_text",
    "label_guess",
    "numeric_values",
    "unit_guess",
    "notes",
]


@dataclass(frozen=True)
class NormalizedFinanceTableRow:
    page_number: int
    backend: str
    table_index: int
    row_index: int
    cells: list[str]
    column_contexts: list[str]
    unit_context: str
    row_text: str
    label_guess: str
    numeric_values: list[str]
    unit_guess: str
    notes: str = ""


def normalize_finance_table_rows(
    *,
    document_row: dict[str, Any] | pd.Series,
    pages: list[ExtractedPdfPage],
    table_cells: list[ExtractedPdfTableCell],
) -> tuple[list[NormalizedFinanceTableRow], pd.DataFrame]:
    page_text = {int(page.page_number): str(page.text or "") for page in pages}
    grouped = _group_cells_by_row(table_cells)
    header_by_table: dict[tuple[int, str, int], list[str]] = {}
    normalized_rows: list[NormalizedFinanceTableRow] = []

    for key in sorted(grouped):
        page_number, backend, table_index, row_index = key
        cells = [cell.cell_text.strip() for cell in sorted(grouped[key], key=lambda cell: cell.col_index) if cell.cell_text.strip()]
        if not cells:
            continue
        table_key = (page_number, backend, table_index)
        row_text = " | ".join(cells)
        if _looks_garbled(row_text):
            continue
        if _is_header_row(cells):
            header_by_table[table_key] = cells
            continue
        label_guess = _label_guess(cells)
        numeric_values = _numeric_values(cells)
        unit_context = " ".join([page_text.get(page_number, ""), " ".join(header_by_table.get(table_key, [])), row_text])
        unit_raw, _, _, unit_status = detect_unit(unit_context)
        unit_guess = unit_raw if unit_status == "UNIT_DETECTED" else ""
        if not _is_finance_normalized_row(row_text=row_text, label_guess=label_guess, numeric_values=numeric_values, page_text=page_text.get(page_number, "")):
            continue
        normalized_rows.append(
            NormalizedFinanceTableRow(
                page_number=page_number,
                backend=backend,
                table_index=table_index,
                row_index=row_index,
                cells=cells,
                column_contexts=header_by_table.get(table_key, []),
                unit_context=unit_context,
                row_text=row_text,
                label_guess=label_guess,
                numeric_values=numeric_values,
                unit_guess=unit_guess,
                notes="normalized from python-native pdf table cells; no OCR",
            )
        )

    audit_rows = [
        {
            "ticker": document_row.get("ticker", ""),
            "period": document_row.get("period", ""),
            "local_path": document_row.get("local_path", ""),
            "file_hash": document_row.get("file_hash", ""),
            "page_number": row.page_number,
            "backend": row.backend,
            "table_index": row.table_index,
            "row_index": row.row_index,
            "row_text": row.row_text[:360],
            "label_guess": row.label_guess,
            "numeric_values": "|".join(row.numeric_values),
            "unit_guess": row.unit_guess,
            "notes": row.notes,
        }
        for row in normalized_rows
    ]
    return normalized_rows, pd.DataFrame(audit_rows, columns=NORMALIZED_TABLE_ROW_COLUMNS_01IF_PATCH2)


def _group_cells_by_row(
    table_cells: list[ExtractedPdfTableCell],
) -> dict[tuple[int, str, int, int], list[ExtractedPdfTableCell]]:
    grouped: dict[tuple[int, str, int, int], list[ExtractedPdfTableCell]] = {}
    for cell in table_cells:
        if not str(cell.cell_text or "").strip():
            continue
        grouped.setdefault((cell.page_number, cell.backend, cell.table_index, cell.row_index), []).append(cell)
    return grouped


def _is_header_row(cells: list[str]) -> bool:
    text = " ".join(cells)
    normalized = text.lower()
    if detect_field_name(text):
        return False
    return bool(
        len(cells) >= 2
        and re.search(
            r"\b(20\d{2}|31/|30/|01/|current|previous|this quarter|period|quarter|year|accumulated|luy ke|lũy kế|code|ma so|mã số)\b",
            normalized,
        )
    )


def _label_guess(cells: list[str]) -> str:
    parts = []
    for cell in cells:
        if extract_numeric_tokens(cell):
            break
        text = str(cell or "").strip()
        if text and not re.fullmatch(r"\d{1,3}", text) and text not in {"-", "–"}:
            parts.append(text)
    candidate = " ".join(parts).strip()
    if detect_field_name(candidate):
        return candidate
    return candidate


def _numeric_values(cells: list[str]) -> list[str]:
    values = []
    for cell in cells:
        values.extend(extract_numeric_tokens(cell))
    return values


def _is_finance_normalized_row(
    *,
    row_text: str,
    label_guess: str,
    numeric_values: list[str],
    page_text: str,
) -> bool:
    if detect_field_name(label_guess or row_text):
        return True
    if numeric_values and (has_finance_keywords(row_text) or has_finance_keywords(page_text)):
        return True
    return False


def _looks_garbled(row_text: str) -> bool:
    return "(cid:" in row_text
