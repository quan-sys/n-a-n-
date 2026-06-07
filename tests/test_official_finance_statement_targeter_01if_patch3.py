from src.ingestion.official_finance_statement_targeter import build_statement_page_candidates
from src.ingestion.official_pdf_text_extractor import ExtractedPdfPage


DOCUMENT = {
    "ticker": "SYN",
    "period": "2026-Q1",
    "source_url": "https://example.test/synthetic-report.pdf",
    "local_path": "data/raw/synthetic-report.pdf",
    "file_hash": "synthetic_hash_patch3",
}


def test_synthetic_balance_sheet_page_is_selected_for_table_extraction():
    text = "\n".join(
        [
            "Balance sheet",
            "Unit: VND",
            "Code Current period Previous period",
            "Total assets 123,456 120,000",
            "Total liabilities 45,678 44,000",
            "Equity 77,878 76,000",
        ]
    )
    frame = build_statement_page_candidates(
        document_row=DOCUMENT,
        pages=[ExtractedPdfPage(page_number=1, text=text, extraction_status="TEXT_EXTRACTED", backend="pymupdf")],
    )

    row = frame.iloc[0]
    assert row["statement_type"] == "balance_sheet"
    assert row["statement_title_detected"] == "balance sheet"
    assert bool(row["selected_for_table_extraction"])
    assert row["unit_detected"] == "VND"
    assert row["rejection_reason"] == ""


def test_synthetic_income_statement_page_is_selected_for_table_extraction():
    text = "\n".join(
        [
            "Income statement",
            "Unit: VND",
            "Item Current period Previous period",
            "Revenue 456,789 400,000",
            "Gross profit 123,456 110,000",
            "Profit after tax 12,345 10,000",
        ]
    )
    frame = build_statement_page_candidates(
        document_row=DOCUMENT,
        pages=[ExtractedPdfPage(page_number=2, text=text, extraction_status="TEXT_EXTRACTED", backend="pymupdf")],
    )

    row = frame.iloc[0]
    assert row["statement_type"] == "income_statement"
    assert bool(row["selected_for_table_extraction"])
    assert row["negative_score"] == 0


def test_formal_line_item_cluster_can_select_page_when_title_is_not_extractable():
    text = "\n".join(
        [
            "Unit: VND",
            "Item Current period Previous period",
            "Current assets 222,222 200,000",
            "Cash and cash equivalents 12,345 10,000",
            "Inventory 23,456 20,000",
            "Total assets 345,678 330,000",
            "Current liabilities 111,111 100,000",
            "Total liabilities 123,456 120,000",
            "Equity 222,222 210,000",
        ]
    )
    frame = build_statement_page_candidates(
        document_row=DOCUMENT,
        pages=[ExtractedPdfPage(page_number=5, text=text, extraction_status="TEXT_EXTRACTED", backend="pymupdf")],
    )

    row = frame.iloc[0]
    assert row["statement_type"] == "balance_sheet"
    assert row["statement_title_detected"] == "line_item_cluster:balance_sheet"
    assert bool(row["selected_for_table_extraction"])


def test_contact_and_explanation_pages_are_rejected():
    pages = [
        ExtractedPdfPage(
            page_number=3,
            text="\n".join(
                [
                    "Notice",
                    "Contact information",
                    "Address 1 Example Street",
                    "Telephone 123456",
                    "Email contact@example.test",
                    "Website example.test",
                ]
            ),
            extraction_status="TEXT_EXTRACTED",
            backend="pymupdf",
        ),
        ExtractedPdfPage(
            page_number=4,
            text="\n".join(
                [
                    "Giai trinh",
                    "Kinh gui Uy ban chung khoan",
                    "This narrative explanation page discusses changes in business activity.",
                    "It is not a formal statement table.",
                ]
            ),
            extraction_status="TEXT_EXTRACTED",
            backend="pymupdf",
        ),
    ]
    frame = build_statement_page_candidates(document_row=DOCUMENT, pages=pages)

    assert frame["selected_for_table_extraction"].astype(bool).sum() == 0
    assert set(frame["rejection_reason"]) == {"NO_FORMAL_STATEMENT_TITLE"}
