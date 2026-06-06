"""Lightweight table audit extraction for REAL-DATA-01I-F.

This module records short table-like audit metadata only. It does not OCR and
does not store full copyrighted tables.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.ingestion.official_finance_value_parser import CANONICAL_FIELDS_01IF, detect_field_name, detect_unit, extract_numeric_tokens


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
