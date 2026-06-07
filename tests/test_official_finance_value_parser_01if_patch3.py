import pandas as pd

from src.ingestion.official_finance_statement_targeter import (
    STATEMENT_TABLE_CANDIDATE_COLUMNS_01IF_PATCH3,
    parse_patch3_statement_rows,
)
from src.ingestion.official_pdf_table_normalizer import NormalizedFinanceTableRow


DOCUMENT = {
    "ticker": "SYN",
    "period": "2026-Q1",
    "source_url": "https://example.test/synthetic-report.pdf",
    "final_url": "https://example.test/synthetic-report.pdf",
    "local_path": "data/raw/synthetic-report.pdf",
    "file_hash": "synthetic_hash_patch3",
    "consolidated_status": "consolidated",
}


def _table_candidates(unit_detected: str = "VND") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "SYN",
                "document_id": "synthetic_hash_",
                "source_url": DOCUMENT["source_url"],
                "local_path": DOCUMENT["local_path"],
                "file_hash": DOCUMENT["file_hash"],
                "page_number": 1,
                "statement_type": "balance_sheet",
                "table_index": 1,
                "rows_count": 2,
                "cols_count": 2,
                "header_guess": "Item | Current period",
                "unit_detected": unit_detected,
                "numeric_cell_count": 1,
                "numeric_density": 0.25,
                "selected_for_value_parse": True,
                "rejection_reason": "",
            }
        ],
        columns=STATEMENT_TABLE_CANDIDATE_COLUMNS_01IF_PATCH3,
    )


def test_usable_statement_row_requires_value_unit_period_and_evidence():
    normalized_row = NormalizedFinanceTableRow(
        page_number=1,
        backend="pdfplumber_statement_pages",
        table_index=1,
        row_index=2,
        cells=["Total assets", "123,456"],
        column_contexts=["Item", "Current period"],
        unit_context="Unit: VND",
        row_text="Total assets | 123,456",
        label_guess="Total assets",
        numeric_values=["123,456"],
        unit_guess="VND",
    )

    usable, status = parse_patch3_statement_rows(
        document_row=DOCUMENT,
        normalized_rows=[normalized_row],
        table_candidates=_table_candidates(),
    )

    assert status.empty
    assert len(usable) == 1
    row = usable.iloc[0]
    assert row["field_name"] == "total_assets"
    assert row["raw_label"] == "Total assets"
    assert row["raw_value"] == "123,456"
    assert row["value_vnd"] == 123456.0
    assert row["unit_raw"] == "VND"
    assert row["period_label"] == "Current period"
    assert row["statement_type"] == "balance_sheet"
    assert row["page_number"] == 1
    assert row["table_index"] == 1
    assert row["row_index"] == 2
    assert row["source_url"] == DOCUMENT["source_url"]
    assert row["local_path"] == DOCUMENT["local_path"]
    assert row["file_hash"] == DOCUMENT["file_hash"]
    assert row["parser_backend"] == "pdfplumber_statement_pages"


def test_label_only_rows_are_status_rows_not_usable_candidates():
    normalized_row = NormalizedFinanceTableRow(
        page_number=1,
        backend="pdfplumber_statement_pages",
        table_index=1,
        row_index=2,
        cells=["Total assets"],
        column_contexts=["Item", "Current period"],
        unit_context="Unit: VND",
        row_text="Total assets",
        label_guess="Total assets",
        numeric_values=[],
        unit_guess="VND",
    )

    usable, status = parse_patch3_statement_rows(
        document_row=DOCUMENT,
        normalized_rows=[normalized_row],
        table_candidates=_table_candidates(),
    )

    assert usable.empty
    assert len(status) == 1
    assert status.iloc[0]["parse_status"] == "LABEL_ONLY_NO_VALUE"


def test_missing_unit_rows_are_status_rows_not_usable_candidates():
    normalized_row = NormalizedFinanceTableRow(
        page_number=1,
        backend="pdfplumber_statement_pages",
        table_index=1,
        row_index=2,
        cells=["Net revenue", "123,456"],
        column_contexts=["Item", "Current period"],
        unit_context="",
        row_text="Net revenue | 123,456",
        label_guess="Net revenue",
        numeric_values=["123,456"],
        unit_guess="",
    )

    usable, status = parse_patch3_statement_rows(
        document_row=DOCUMENT,
        normalized_rows=[normalized_row],
        table_candidates=_table_candidates(unit_detected=""),
    )

    assert usable.empty
    assert len(status) == 1
    assert status.iloc[0]["field_name"] == "net_revenue"
    assert status.iloc[0]["parse_status"] == "UNIT_AMBIGUOUS_MANUAL_REVIEW"
