import pandas as pd

from src.ingestion.bctc_bctn_document_filter import score_document_candidates, select_scored_local_documents_for_parse


def test_bctc_documents_outscore_bctn_documents():
    frame = pd.DataFrame(
        [
            {
                "ticker": "SYN",
                "period": "2025",
                "source_name": "vietstock",
                "source_category": "vietstock_public_document_page",
                "source_url": "https://example.test/syn-bctc-2025.pdf",
                "final_url": "https://example.test/syn-bctc-2025.pdf",
                "local_path": "data/raw/syn-bctc.pdf",
                "file_hash": "hash_bctc",
                "detected_file_type": "pdf",
                "document_category_raw": "Bao cao tai chinh",
                "document_category_normalized": "financial_statement",
                "document_title": "SYN BCTC hop nhat 2025",
                "consolidated_status": "consolidated",
            },
            {
                "ticker": "SYN",
                "period": "2025",
                "source_name": "vietstock",
                "source_category": "vietstock_public_document_page",
                "source_url": "https://example.test/syn-bctn-2025.pdf",
                "final_url": "https://example.test/syn-bctn-2025.pdf",
                "local_path": "data/raw/syn-bctn.pdf",
                "file_hash": "hash_bctn",
                "detected_file_type": "pdf",
                "document_category_raw": "Bao cao thuong nien",
                "document_category_normalized": "annual_report",
                "document_title": "SYN BCTN 2025",
                "consolidated_status": "unknown",
            },
        ]
    )

    scored = score_document_candidates(frame)
    bctc = scored[scored["document_status"] == "ACCEPTED_TARGET_BCTC"].iloc[0]
    bctn = scored[scored["document_status"] == "ACCEPTED_TARGET_BCTN"].iloc[0]

    assert bctc["document_score"] > bctn["document_score"]
    assert select_scored_local_documents_for_parse(scored).iloc[0]["file_hash"] == "hash_bctc"


def test_negative_document_titles_are_rejected():
    frame = pd.DataFrame(
        [
            {
                "ticker": "SYN",
                "period": "2025",
                "source_name": "company_ir",
                "source_category": "company_ir",
                "source_url": "https://example.test/esop-nghi-quyet.pdf",
                "document_category_normalized": "financial_statement",
                "document_title": "Nghi quyet ESOP 2025",
                "detected_file_type": "pdf",
            }
        ]
    )

    scored = score_document_candidates(frame)

    assert scored.iloc[0]["document_status"] == "REJECTED_NEGATIVE_TITLE"
    assert bool(scored.iloc[0]["manual_review_required"])
