from __future__ import annotations

from types import SimpleNamespace

from src.ingestion.official_finance_value_parser import (
    detect_unit,
    parse_official_finance_values_from_pages,
)


def test_01if_parses_vietnamese_net_profit_label_to_canonical_field():
    pages = [_page("Đơn vị tính: triệu đồng\nLợi nhuận sau thuế 1,234")]

    result = parse_official_finance_values_from_pages(document_row=_document_row(), pages=pages)

    row = result.iloc[0]
    assert row["field_name"] == "net_profit"
    assert row["parse_status"] == "FIELD_PARSED"
    assert row["value_vnd"] == 1_234_000_000


def test_01if_parses_english_operating_cash_flow_label_to_canonical_field():
    pages = [_page("Unit: million VND\nNet cash flows from operating activities 987")]

    result = parse_official_finance_values_from_pages(document_row=_document_row(), pages=pages)

    row = result.iloc[0]
    assert row["field_name"] == "operating_cash_flow"
    assert row["value_vnd"] == 987_000_000


def test_01if_detects_trieu_dong_unit_multiplier():
    unit_raw, multiplier, currency, status = detect_unit("Đơn vị: triệu đồng")

    assert status == "UNIT_DETECTED"
    assert unit_raw == "million VND"
    assert multiplier == 1_000_000
    assert currency == "VND"


def test_01if_missing_unit_goes_to_manual_review():
    pages = [_page("Lợi nhuận sau thuế 1,234")]

    result = parse_official_finance_values_from_pages(document_row=_document_row(), pages=pages)

    row = result.iloc[0]
    assert row["parse_status"] == "UNIT_AMBIGUOUS_MANUAL_REVIEW"
    assert bool(row["manual_review_required"]) is True


def test_01if_ambiguous_duplicate_labels_go_to_manual_review():
    pages = [_page("Đơn vị: triệu đồng\nLợi nhuận sau thuế 1,234\nLợi nhuận sau thuế 1,235")]

    result = parse_official_finance_values_from_pages(document_row=_document_row(), pages=pages)

    assert set(result["parse_status"]) == {"FIELD_LABEL_AMBIGUOUS"}
    assert result["manual_review_required"].astype(bool).all()
    assert result["review_reason"].str.contains("CONFLICTING_DUPLICATE_LABELS").all()


def test_01if_output_candidate_rows_include_source_evidence_fields():
    pages = [_page("Đơn vị: triệu đồng\nTổng tài sản 1,234")]

    result = parse_official_finance_values_from_pages(document_row=_document_row(), pages=pages)

    row = result.iloc[0]
    assert row["source_url"] == "https://official.example/bctc.pdf"
    assert row["local_path"] == "data/raw/mock.pdf"
    assert row["file_hash"] == "hash-1"
    assert row["page_number"] == 1


def _page(text: str):
    return SimpleNamespace(page_number=1, text=text, extraction_status="TEXT_EXTRACTED")


def _document_row():
    return {
        "ticker": "AAA",
        "period": "2026-Q1",
        "consolidated_status": "consolidated",
        "source_url": "https://official.example/bctc.pdf",
        "final_url": "https://official.example/bctc.pdf",
        "local_path": "data/raw/mock.pdf",
        "file_hash": "hash-1",
    }
