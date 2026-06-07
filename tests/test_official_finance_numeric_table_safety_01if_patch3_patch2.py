from src.ingestion.official_finance_numeric_table_dump import build_numeric_table_dump_frames
from src.ingestion.official_pdf_text_extractor import ExtractedPdfPage, ExtractedPdfTableCell


DOCUMENT = {
    "ticker": "SYN",
    "period": "2026-Q1",
    "document_type": "financial_statement",
    "source_url": "https://example.test/synthetic-bctc.pdf",
    "final_url": "https://example.test/synthetic-bctc.pdf",
    "local_path": "data/raw/synthetic-bctc.pdf",
    "file_hash": "synthetic_hash_safety_dump",
    "detected_file_type": "pdf",
}


def test_missing_unit_keeps_raw_dump_but_blocks_value_vnd_candidate():
    pages = [
        ExtractedPdfPage(
            page_number=1,
            text="Financial statements Total assets Total liabilities Equity",
            extraction_status="TEXT_EXTRACTED",
            backend="pymupdf",
        )
    ]
    cells = [
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 1, 1, "Item"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 1, 2, "Current period"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 2, 1, "Total assets"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 2, 2, "123,456"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 3, 1, "Total liabilities"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 3, 2, "45,678"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 4, 1, "Equity"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 4, 2, "77,778"),
    ]

    frames = build_numeric_table_dump_frames(document_row=DOCUMENT, pages=pages, table_cells=cells)

    assert len(frames.dump_index) == 1
    assert not frames.table_rows.empty
    assert frames.candidate_rows.empty
    assert set(frames.status_rows["parse_status"]) == {"UNIT_AMBIGUOUS_MANUAL_REVIEW"}
    assert set(frames.status_rows["review_reason"]) == {"MISSING_UNIT_FOR_VALUE_VND"}


def test_dump_status_notes_keep_no_ocr_and_no_inference_contract():
    pages = [
        ExtractedPdfPage(
            page_number=1,
            text="Financial statements Unit: VND Total assets Total liabilities Equity",
            extraction_status="TEXT_EXTRACTED",
            backend="pymupdf",
        )
    ]
    cells = [
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 1, 1, "Item"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 1, 2, "Current period"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 2, 1, "Total assets"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 2, 2, "123,456"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 3, 1, "Total liabilities"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 3, 2, "45,678"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 4, 1, "Equity"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 4, 2, "77,778"),
    ]

    frames = build_numeric_table_dump_frames(document_row=DOCUMENT, pages=pages, table_cells=cells)

    assert "no OCR" in frames.candidate_rows.iloc[0]["notes"]
    assert "no inferred or zero-filled values" in frames.candidate_rows.iloc[0]["notes"]
