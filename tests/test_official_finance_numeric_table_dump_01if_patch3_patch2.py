from src.ingestion.official_finance_numeric_table_dump import (
    build_numeric_table_dump_frames,
    selected_numeric_page_numbers,
)
from src.ingestion.official_pdf_text_extractor import ExtractedPdfPage, ExtractedPdfTableCell


DOCUMENT = {
    "ticker": "SYN",
    "period": "2026-Q1",
    "document_type": "financial_statement",
    "source_url": "https://example.test/synthetic-bctc.pdf",
    "final_url": "https://example.test/synthetic-bctc.pdf",
    "local_path": "data/raw/synthetic-bctc.pdf",
    "file_hash": "synthetic_hash_numeric_dump",
    "detected_file_type": "pdf",
}


def test_numeric_heavy_table_is_dumped_as_raw_evidence():
    pages = [
        ExtractedPdfPage(
            page_number=1,
            text="Financial statements Unit: VND Total assets 123,456 Revenue 456,789 Net profit 12,345",
            extraction_status="TEXT_EXTRACTED",
            backend="pymupdf",
        )
    ]
    cells = [
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 1, 1, "Item"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 1, 2, "Current period"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 1, 3, "Previous period"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 2, 1, "Total assets"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 2, 2, "123,456"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 2, 3, "120,000"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 3, 1, "Total liabilities"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 3, 2, "45,678"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 3, 3, "44,000"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 4, 1, "Equity"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 4, 2, "77,778"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 4, 3, "76,000"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 5, 1, "Revenue"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 5, 2, "456,789"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 5, 3, "400,000"),
    ]

    frames = build_numeric_table_dump_frames(document_row=DOCUMENT, pages=pages, table_cells=cells)

    assert len(frames.dump_index) == 1
    assert len(frames.table_cells) == len(cells)
    assert len(frames.table_rows) == 5
    assert selected_numeric_page_numbers(frames.page_candidates) == {1}
    assert frames.table_candidates.iloc[0]["table_status"] == "DUMPED_RAW_EVIDENCE"


def test_contact_numeric_table_does_not_become_finance_candidate_row():
    pages = [
        ExtractedPdfPage(
            page_number=1,
            text="Financial statements appendix Contact address telephone email Unit: VND",
            extraction_status="TEXT_EXTRACTED",
            backend="pymupdf",
        )
    ]
    cells = [
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 1, 1, "Name"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 1, 2, "Phone"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 1, 3, "Shares"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 2, 1, "Director A"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 2, 2, "0900123456"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 2, 3, "123,456"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 3, 1, "Director B"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 3, 2, "0900654321"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 3, 3, "234,567"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 4, 1, "Director C"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 4, 2, "0900111222"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 4, 3, "345,678"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 5, 1, "Director D"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 5, 2, "0900333444"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 5, 3, "456,789"),
    ]

    frames = build_numeric_table_dump_frames(document_row=DOCUMENT, pages=pages, table_cells=cells)

    assert len(frames.dump_index) == 1
    assert frames.candidate_rows.empty
    assert frames.status_rows.empty
