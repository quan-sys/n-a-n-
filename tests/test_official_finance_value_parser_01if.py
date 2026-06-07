from __future__ import annotations

from types import SimpleNamespace

from src.ingestion.official_finance_value_parser import (
    detect_unit,
    parse_official_finance_values_from_pages,
    parse_official_finance_values_from_table_rows,
    split_usable_and_status_rows,
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


def test_01if_patch1_table_row_maps_net_profit_to_usable_candidate():
    table_rows = [
        _table_row(
            cells=["Lợi nhuận sau thuế", "1,234,567"],
            unit_context="Đơn vị: triệu đồng",
        )
    ]

    result = parse_official_finance_values_from_table_rows(
        document_row=_document_row(),
        table_rows=table_rows,
        pages=[_page("Đơn vị: triệu đồng")],
    )
    usable, status = split_usable_and_status_rows(result)

    assert status.empty
    row = usable.iloc[0]
    assert row["field_name"] == "net_profit"
    assert row["parse_status"] == "FIELD_PARSED"
    assert row["value_vnd"] == 1_234_567_000_000


def test_01if_patch1_table_row_maps_total_assets_to_usable_candidate():
    table_rows = [
        _table_row(
            cells=["Total assets", "9,876,543"],
            unit_context="Unit: thousand VND",
        )
    ]

    result = parse_official_finance_values_from_table_rows(
        document_row=_document_row(),
        table_rows=table_rows,
        pages=[_page("Unit: thousand VND")],
    )

    row = result.iloc[0]
    assert row["field_name"] == "total_assets"
    assert row["value_vnd"] == 9_876_543_000


def test_01if_patch1_parentheses_negative_value_parsed():
    table_rows = [_table_row(cells=["Profit after tax", "(1,234,567)"], unit_context="Unit: VND")]

    result = parse_official_finance_values_from_table_rows(
        document_row=_document_row(),
        table_rows=table_rows,
        pages=[_page("Unit: VND")],
    )

    assert result.iloc[0]["value_vnd"] == -1_234_567


def test_01if_patch1_missing_unit_table_row_goes_to_manual_review():
    table_rows = [_table_row(cells=["Total assets", "9,876,543"], unit_context="")]

    result = parse_official_finance_values_from_table_rows(
        document_row=_document_row(),
        table_rows=table_rows,
        pages=[_page("Total assets 9,876,543")],
    )

    usable, status = split_usable_and_status_rows(result)
    assert usable.empty
    assert status.iloc[0]["parse_status"] == "UNIT_AMBIGUOUS_MANUAL_REVIEW"
    assert bool(status.iloc[0]["manual_review_required"]) is True


def test_01if_patch1_label_only_row_is_not_usable_candidate():
    result = parse_official_finance_values_from_pages(
        document_row=_document_row(),
        pages=[_page("Unit: VND\nRevenue")],
    )

    usable, status = split_usable_and_status_rows(result)
    assert usable.empty
    assert status.iloc[0]["parse_status"] == "FIELD_VALUE_AMBIGUOUS"


def test_01if_patch1_prose_revenue_without_value_is_not_high_confidence():
    result = parse_official_finance_values_from_pages(
        document_row=_document_row(),
        pages=[_page("Unit: VND\nRevenue grew because of a new project handover.")],
    )

    usable, status = split_usable_and_status_rows(result)
    assert usable.empty
    assert status.iloc[0]["confidence_raw"] == "low"


def _page(text: str):
    return SimpleNamespace(page_number=1, text=text, extraction_status="TEXT_EXTRACTED")


def _table_row(cells, unit_context):
    return SimpleNamespace(
        page_number=1,
        backend="synthetic",
        table_index=1,
        row_index=1,
        cells=cells,
        column_contexts=[],
        unit_context=unit_context,
        notes="synthetic table row",
    )


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
