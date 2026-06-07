from __future__ import annotations

from src.ingestion.official_pdf_table_normalizer import normalize_finance_table_rows
from src.ingestion.official_pdf_text_extractor import ExtractedPdfPage, ExtractedPdfTableCell


def test_01if_patch2_normalizer_emits_row_with_label_numeric_unit():
    pages = [
        ExtractedPdfPage(
            page_number=1,
            text="Unit: million VND\nFinancial statements",
            extraction_status="TEXT_EXTRACTED",
            backend="pymupdf",
        )
    ]
    cells = [
        _cell(1, 1, "Item"),
        _cell(1, 2, "Current period"),
        _cell(2, 1, "Profit after tax"),
        _cell(2, 2, "1,234,567"),
    ]

    rows, frame = normalize_finance_table_rows(document_row=_document_row(), pages=pages, table_cells=cells)

    assert len(rows) == 1
    assert rows[0].label_guess == "Profit after tax"
    assert rows[0].numeric_values == ["1,234,567"]
    assert rows[0].unit_guess == "million VND"
    assert frame.iloc[0]["label_guess"] == "Profit after tax"


def test_01if_patch2_normalizer_ignores_unrelated_table_rows():
    pages = [ExtractedPdfPage(page_number=1, text="Corporate governance", extraction_status="TEXT_EXTRACTED", backend="pymupdf")]
    cells = [_cell(1, 1, "Meeting agenda"), _cell(1, 2, "2026")]

    rows, frame = normalize_finance_table_rows(document_row=_document_row(), pages=pages, table_cells=cells)

    assert rows == []
    assert frame.empty


def _cell(row_index: int, col_index: int, text: str):
    return ExtractedPdfTableCell(
        page_number=1,
        backend="pdfplumber",
        table_index=1,
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
