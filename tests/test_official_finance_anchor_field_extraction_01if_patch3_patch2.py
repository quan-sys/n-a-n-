from src.ingestion.official_finance_numeric_table_dump import build_numeric_table_dump_frames
from src.ingestion.official_pdf_text_extractor import ExtractedPdfPage, ExtractedPdfTableCell


DOCUMENT = {
    "ticker": "SYN",
    "period": "2026-Q1",
    "document_type": "financial_statement",
    "source_url": "https://example.test/synthetic-bctc.pdf",
    "final_url": "https://example.test/synthetic-bctc.pdf",
    "local_path": "data/raw/synthetic-bctc.pdf",
    "file_hash": "synthetic_hash_anchor_dump",
    "detected_file_type": "pdf",
}


def _anchor_cells_with_header(*, ambiguous: bool = False) -> list[ExtractedPdfTableCell]:
    second_header = "2026" if ambiguous else "Current period"
    third_header = "2025" if ambiguous else "Previous period"
    return [
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 1, 1, "Item"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 1, 2, second_header),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 1, 3, third_header),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 2, 1, "Total assets"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 2, 2, "123,456"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 2, 3, "120,000"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 3, 1, "Total liabilities"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 3, 2, "45,678"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 3, 3, "44,000"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 4, 1, "Equity"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 4, 2, "77,778"),
        ExtractedPdfTableCell(1, "pdfplumber_numeric_table_dump", 1, 4, 3, "76,000"),
    ]


def test_clear_anchor_row_with_unit_emits_strict_total_assets_candidate():
    pages = [
        ExtractedPdfPage(
            page_number=1,
            text="Financial statements Unit: VND Total assets Total liabilities Equity",
            extraction_status="TEXT_EXTRACTED",
            backend="pymupdf",
        )
    ]

    frames = build_numeric_table_dump_frames(document_row=DOCUMENT, pages=pages, table_cells=_anchor_cells_with_header())

    assert len(frames.candidate_rows) == 3
    row = frames.candidate_rows[frames.candidate_rows["field_name"] == "total_assets"].iloc[0]
    assert row["parse_status"] == "USABLE_VALUE_PARSED"
    assert row["raw_value"] == "123,456"
    assert row["value_vnd"] == 123456.0
    assert row["unit_raw"] == "VND"
    assert row["source_url"] == DOCUMENT["source_url"]
    assert row["local_path"] == DOCUMENT["local_path"]
    assert row["file_hash"] == DOCUMENT["file_hash"]
    assert row["page_number"] == 1
    assert row["table_index"] == 1
    assert row["row_index"] == 2


def test_ambiguous_period_columns_do_not_emit_strict_candidate_rows():
    pages = [
        ExtractedPdfPage(
            page_number=1,
            text="Financial statements Unit: VND Total assets Total liabilities Equity",
            extraction_status="TEXT_EXTRACTED",
            backend="pymupdf",
        )
    ]

    frames = build_numeric_table_dump_frames(
        document_row=DOCUMENT,
        pages=pages,
        table_cells=_anchor_cells_with_header(ambiguous=True),
    )

    assert frames.candidate_rows.empty
    assert set(frames.status_rows["parse_status"]) == {"FIELD_VALUE_AMBIGUOUS"}
    assert set(frames.status_rows["review_reason"]) == {"AMBIGUOUS_PERIOD_COLUMNS"}
