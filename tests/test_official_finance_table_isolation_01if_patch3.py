import pandas as pd

from src.ingestion.official_finance_statement_targeter import (
    STATEMENT_PAGE_CANDIDATE_COLUMNS_01IF_PATCH3,
    build_statement_table_candidates,
    filter_cells_to_selected_statement_tables,
)
from src.ingestion.official_pdf_text_extractor import ExtractedPdfTableCell


DOCUMENT = {
    "ticker": "SYN",
    "period": "2026-Q1",
    "source_url": "https://example.test/synthetic-report.pdf",
    "local_path": "data/raw/synthetic-report.pdf",
    "file_hash": "synthetic_hash_patch3",
}


def test_table_candidates_are_built_only_from_selected_statement_pages():
    page_candidates = pd.DataFrame(
        [
            {
                "ticker": "SYN",
                "document_id": "synthetic_hash_",
                "source_url": DOCUMENT["source_url"],
                "local_path": DOCUMENT["local_path"],
                "file_hash": DOCUMENT["file_hash"],
                "page_number": 1,
                "statement_type": "balance_sheet",
                "statement_title_detected": "balance sheet",
                "positive_score": 16,
                "negative_score": 0,
                "numeric_density": 0.4,
                "table_like_score": 4,
                "unit_detected": "VND",
                "selected_for_table_extraction": True,
                "rejection_reason": "",
            },
            {
                "ticker": "SYN",
                "document_id": "synthetic_hash_",
                "source_url": DOCUMENT["source_url"],
                "local_path": DOCUMENT["local_path"],
                "file_hash": DOCUMENT["file_hash"],
                "page_number": 2,
                "statement_type": "",
                "statement_title_detected": "",
                "positive_score": 0,
                "negative_score": 9,
                "numeric_density": 0.05,
                "table_like_score": 0,
                "unit_detected": "",
                "selected_for_table_extraction": False,
                "rejection_reason": "NO_FORMAL_STATEMENT_TITLE",
            },
        ],
        columns=STATEMENT_PAGE_CANDIDATE_COLUMNS_01IF_PATCH3,
    )
    cells = [
        ExtractedPdfTableCell(1, "pdfplumber_statement_pages", 1, 1, 1, "Item"),
        ExtractedPdfTableCell(1, "pdfplumber_statement_pages", 1, 1, 2, "Current period"),
        ExtractedPdfTableCell(1, "pdfplumber_statement_pages", 1, 1, 3, "Unit: VND"),
        ExtractedPdfTableCell(1, "pdfplumber_statement_pages", 1, 2, 1, "Total assets"),
        ExtractedPdfTableCell(1, "pdfplumber_statement_pages", 1, 2, 2, "123,456"),
        ExtractedPdfTableCell(2, "pdfplumber_statement_pages", 1, 1, 1, "Email"),
        ExtractedPdfTableCell(2, "pdfplumber_statement_pages", 1, 1, 2, "contact@example.test"),
        ExtractedPdfTableCell(2, "pdfplumber_statement_pages", 1, 2, 1, "Phone"),
        ExtractedPdfTableCell(2, "pdfplumber_statement_pages", 1, 2, 2, "123456"),
    ]

    table_candidates = build_statement_table_candidates(
        document_row=DOCUMENT,
        table_cells=cells,
        page_candidates=page_candidates,
    )
    selected_cells = filter_cells_to_selected_statement_tables(cells, table_candidates)

    assert list(table_candidates["page_number"]) == [1]
    assert bool(table_candidates.iloc[0]["selected_for_value_parse"])
    assert table_candidates.iloc[0]["unit_detected"] == "VND"
    assert {cell.page_number for cell in selected_cells} == {1}
