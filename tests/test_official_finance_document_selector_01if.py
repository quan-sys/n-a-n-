from __future__ import annotations

import pandas as pd

from src.ingestion.official_finance_document_selector import select_documents_for_official_parse


def test_01if_selects_consolidated_financial_statement_over_standalone():
    index = pd.DataFrame(
        [
            _index_row(consolidated_status="standalone", file_hash="standalone-hash"),
            _index_row(consolidated_status="consolidated", file_hash="consolidated-hash"),
        ]
    )

    selected = select_documents_for_official_parse(index)

    consolidated = selected[selected["file_hash"] == "consolidated-hash"].iloc[0]
    standalone = selected[selected["file_hash"] == "standalone-hash"].iloc[0]
    assert consolidated["selection_status"] == "SELECTED_FOR_PARSE"
    assert standalone["selection_status"] == "REVIEW_ONLY_STANDALONE"
    assert consolidated["selection_priority"] < standalone["selection_priority"]


def test_01if_skips_esg_only_pdf_candidate():
    index = pd.DataFrame(
        [
            _index_row(
                document_type="annual_report",
                source_url="https://official.example/reports/esg-2025.pdf",
                final_url="https://official.example/reports/esg-2025.pdf",
                file_hash="esg-hash",
                notes="ESG sustainability report",
            )
        ]
    )

    selected = select_documents_for_official_parse(index, parse_annual_reports=True)

    assert selected.iloc[0]["selection_status"] == "SKIPPED_NON_FINANCE_DOCUMENT"
    assert "ESG_OR_NON_FINANCE_DOCUMENT" in selected.iloc[0]["reason"]


def test_01if_deduplicates_same_file_hash():
    index = pd.DataFrame(
        [
            _index_row(source_url="https://official.example/reports/bctc-1.pdf", file_hash="same-hash"),
            _index_row(source_url="https://official.example/reports/bctc-2.pdf", file_hash="same-hash"),
        ]
    )

    selected = select_documents_for_official_parse(index)

    assert selected["selection_status"].tolist().count("SELECTED_FOR_PARSE") == 1
    assert selected["selection_status"].tolist().count("SKIPPED_DUPLICATE_HASH") == 1


def _index_row(**overrides):
    row = {
        "ticker": "AAA",
        "period": "2026-Q1",
        "document_type": "financial_statement",
        "consolidated_status": "consolidated",
        "source_url": "https://official.example/reports/bctc-hop-nhat-q1-2026.pdf",
        "final_url": "https://official.example/reports/bctc-hop-nhat-q1-2026.pdf",
        "local_path": "data/raw/mock.pdf",
        "file_hash": "hash-1",
        "detected_file_type": "pdf",
        "download_status": "DOWNLOADED",
        "candidate_origin": "REFINED_SEED_DIRECT",
        "official_domain": "official.example",
        "manual_review_required": False,
        "review_reason": "",
        "notes": "mock document",
    }
    row.update(overrides)
    return row
