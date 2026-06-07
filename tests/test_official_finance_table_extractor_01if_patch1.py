from __future__ import annotations

from types import SimpleNamespace

from src.ingestion.official_finance_table_extractor import build_finance_table_rows, build_table_cell_audit_rows
from src.ingestion.official_pdf_text_extractor import ExtractedPdfTableCell


def test_01if_patch1_builds_table_rows_from_extracted_cells_with_header_context():
    pages = [_page("Unit: VND\nConsolidated financial statements")]
    cells = [
        _cell(1, 1, 1, "Item"),
        _cell(1, 2, 1, "Current period"),
        _cell(2, 1, 1, "Total assets"),
        _cell(2, 2, 1, "9,876,543"),
    ]

    rows = build_finance_table_rows(document_row=_document_row(), pages=pages, table_cells=cells)

    assert len(rows) == 1
    assert rows[0].cells == ["Total assets", "9,876,543"]
    assert rows[0].column_contexts == ["Item", "Current period"]


def test_01if_patch1_builds_table_rows_from_table_like_text_line():
    pages = [_page("Unit: VND\nTotal assets  9,876,543")]

    rows = build_finance_table_rows(document_row=_document_row(), pages=pages, table_cells=[])

    assert len(rows) == 1
    assert rows[0].cells == ["Total assets", "9,876,543"]


def test_01if_patch1_table_cell_audit_keeps_finance_pages_only():
    pages = [_page("Unit: VND\nTotal assets")]
    cells = [_cell(1, 2, 1, "Total assets"), _cell(1, 2, 2, "9,876,543")]

    audit_rows = build_table_cell_audit_rows(document_row=_document_row(), pages=pages, table_cells=cells)

    assert len(audit_rows) == 2
    assert audit_rows[0]["ticker"] == "AAA"


def _page(text: str):
    return SimpleNamespace(page_number=1, text=text, extraction_status="TEXT_EXTRACTED", backend="synthetic")


def _cell(row_index: int, col_index: int, table_index: int, text: str):
    return ExtractedPdfTableCell(
        page_number=1,
        backend="synthetic",
        table_index=table_index,
        row_index=row_index,
        col_index=col_index,
        cell_text=text,
        notes="synthetic",
    )


def _document_row():
    return {
        "ticker": "AAA",
        "period": "2026-Q1",
        "local_path": "data/raw/mock.pdf",
        "file_hash": "hash-1",
    }
