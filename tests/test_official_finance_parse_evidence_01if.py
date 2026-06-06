from __future__ import annotations

import pandas as pd

from scripts.run_official_finance_parse_01if import _failed_parse_row
from src.ingestion.official_finance_document_selector import SELECTED_DOCUMENT_COLUMNS_01IF
from src.ingestion.official_finance_parse_evidence import (
    build_01if_decision_report_markdown,
    build_field_coverage,
    build_unresolved_fields,
)
from src.ingestion.official_finance_value_parser import OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF


def test_01if_scanned_or_no_text_pdf_is_document_not_text_extractable():
    row = _failed_parse_row(_selected_document().iloc[0], "DOCUMENT_NOT_TEXT_EXTRACTABLE", "NO_TEXT_EXTRACTED_NO_OCR")

    assert row["parse_status"] == "DOCUMENT_NOT_TEXT_EXTRACTABLE"
    assert row["manual_review_required"] is True
    assert row["value_vnd"] == ""


def test_01if_no_finance_values_fabricated_when_field_missing():
    selected = _selected_document()
    candidates = pd.DataFrame(
        [
            {
                **_candidate_row("net_profit", 123),
                "parse_status": "FIELD_PARSED",
            }
        ],
        columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF,
    )

    coverage = build_field_coverage(selected_documents=selected, candidate_rows=candidates)
    unresolved = build_unresolved_fields(selected_documents=selected, candidate_rows=candidates, coverage=coverage)

    assert "revenue" in coverage.iloc[0]["fields_missing"]
    assert "revenue" in set(unresolved["field_name"])
    assert not (unresolved["issue"] == "FIELD_PARSED").any()


def test_01if_decision_report_keeps_real_data_02_and_step19_off():
    selected = _selected_document()
    candidates = pd.DataFrame([_candidate_row("net_profit", 123)], columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF)
    coverage = build_field_coverage(selected_documents=selected, candidate_rows=candidates)

    report = build_01if_decision_report_markdown(
        selected_documents=selected,
        candidate_rows=candidates,
        coverage=coverage,
    )

    assert "- should_run_REAL_DATA_02: No" in report
    assert "- should_implement_Step19_now: No" in report


def _selected_document():
    return pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "period": "2026-Q1",
                "document_type": "financial_statement",
                "consolidated_status": "consolidated",
                "source_url": "https://official.example/bctc.pdf",
                "final_url": "https://official.example/bctc.pdf",
                "local_path": "data/raw/mock.pdf",
                "file_hash": "hash-1",
                "detected_file_type": "pdf",
                "selection_status": "SELECTED_FOR_PARSE",
                "selection_priority": 0,
                "manual_review_required": False,
                "reason": "",
                "notes": "mock",
            }
        ],
        columns=SELECTED_DOCUMENT_COLUMNS_01IF,
    )


def _candidate_row(field_name: str, value: int):
    return {
        "ticker": "AAA",
        "period": "2026-Q1",
        "period_type": "quarter",
        "field_name": field_name,
        "value_vnd": value,
        "raw_value": "123",
        "unit_raw": "VND",
        "unit_multiplier": 1,
        "currency": "VND",
        "source_category": "official_company_document",
        "source_name": "official_pdf_parser_01if",
        "source_url": "https://official.example/bctc.pdf",
        "final_url": "https://official.example/bctc.pdf",
        "local_path": "data/raw/mock.pdf",
        "file_hash": "hash-1",
        "page_number": 1,
        "table_index": "",
        "row_index": 1,
        "raw_label": field_name,
        "raw_context": field_name,
        "parser_name": "official_pdf_text_line_parser_01if",
        "parse_status": "FIELD_PARSED",
        "confidence_raw": "high",
        "manual_review_required": False,
        "review_reason": "",
        "fetch_time": "2026-01-01T00:00:00+00:00",
        "notes": "mock",
    }
