import pandas as pd

from src.ingestion.financial_numeric_page_scorer import (
    build_finance_numeric_page_candidates,
    build_finance_numeric_table_candidates,
)


def test_finance_anchor_table_is_selected_as_finance_candidate():
    pages = pd.DataFrame(
        [
            {
                "ticker": "SYN",
                "period": "2025",
                "period_type": "annual",
                "source_document_type": "financial_statement",
                "source_url": "https://example.test/syn-bctc.pdf",
                "final_url": "https://example.test/syn-bctc.pdf",
                "local_path": "data/raw/syn-bctc.pdf",
                "file_hash": "hash_finance",
                "page_number": 7,
                "numeric_density": 0.5,
                "numeric_token_count": 9,
                "negative_keyword_hits": 0,
                "text_preview": "Total assets Total liabilities Equity Revenue Net profit Unit: VND",
            }
        ]
    )
    tables = pd.DataFrame(
        [
            {
                "ticker": "SYN",
                "period": "2025",
                "period_type": "annual",
                "source_document_type": "financial_statement",
                "source_url": "https://example.test/syn-bctc.pdf",
                "final_url": "https://example.test/syn-bctc.pdf",
                "local_path": "data/raw/syn-bctc.pdf",
                "file_hash": "hash_finance",
                "page_number": 7,
                "table_index": 1,
                "row_count": 5,
                "col_count": 3,
                "numeric_cell_count": 8,
                "numeric_cell_ratio": 0.5,
                "finance_anchor_hits": 3,
                "table_status": "DUMPED_RAW_EVIDENCE",
                "table_preview": "Total assets | 123 | Total liabilities | 45 | Equity | 78",
            }
        ]
    )

    finance_pages = build_finance_numeric_page_candidates(pages)
    finance_tables = build_finance_numeric_table_candidates(tables, finance_pages)

    assert finance_pages.iloc[0]["page_status"] == "FINANCE_NUMERIC_PAGE_CANDIDATE"
    assert finance_tables.iloc[0]["table_status"] == "FINANCE_NUMERIC_TABLE_CANDIDATE"


def test_market_supply_absorption_table_is_non_financial():
    pages = pd.DataFrame(
        [
            {
                "ticker": "SYN",
                "period": "2025",
                "period_type": "annual",
                "source_document_type": "annual_report",
                "source_url": "https://example.test/syn-bctn.pdf",
                "final_url": "https://example.test/syn-bctn.pdf",
                "local_path": "data/raw/syn-bctn.pdf",
                "file_hash": "hash_market",
                "page_number": 11,
                "numeric_density": 0.4,
                "numeric_token_count": 12,
                "negative_keyword_hits": 0,
                "text_preview": "Hanoi HCMC real estate market supply absorption rate new launch",
            }
        ]
    )
    tables = pd.DataFrame(
        [
            {
                "ticker": "SYN",
                "period": "2025",
                "period_type": "annual",
                "source_document_type": "annual_report",
                "source_url": "https://example.test/syn-bctn.pdf",
                "final_url": "https://example.test/syn-bctn.pdf",
                "local_path": "data/raw/syn-bctn.pdf",
                "file_hash": "hash_market",
                "page_number": 11,
                "table_index": 2,
                "row_count": 6,
                "col_count": 4,
                "numeric_cell_count": 12,
                "numeric_cell_ratio": 0.5,
                "finance_anchor_hits": 0,
                "table_status": "DUMPED_RAW_EVIDENCE",
                "table_preview": "Supply | Absorption rate | Hanoi | HCMC | New launch",
            }
        ]
    )

    finance_pages = build_finance_numeric_page_candidates(pages)
    finance_tables = build_finance_numeric_table_candidates(tables, finance_pages)

    assert finance_pages.iloc[0]["page_status"] == "NON_FINANCE_NUMERIC_PAGE"
    assert finance_tables.iloc[0]["table_status"] == "NON_FINANCIAL_NUMERIC_TABLE"


def test_prose_explanation_page_with_finance_words_is_not_selected():
    pages = pd.DataFrame(
        [
            {
                "ticker": "SYN",
                "period": "2025",
                "period_type": "annual",
                "source_document_type": "financial_statement",
                "source_url": "https://example.test/syn-bctc.pdf",
                "final_url": "https://example.test/syn-bctc.pdf",
                "local_path": "data/raw/syn-bctc.pdf",
                "file_hash": "hash_prose",
                "page_number": 95,
                "numeric_density": 0.017,
                "numeric_token_count": 8,
                "negative_keyword_hits": 0,
                "text_preview": (
                    "The accumulated net profit after tax changed compared to the "
                    "consolidated financial statement because revenue and expense "
                    "items were adjusted after audit."
                ),
            }
        ]
    )

    finance_pages = build_finance_numeric_page_candidates(pages)

    assert finance_pages.iloc[0]["page_status"] == "NON_FINANCE_NUMERIC_PAGE"
    assert finance_pages.iloc[0]["reject_reason"] == "LOW_NUMERIC_DENSITY"
