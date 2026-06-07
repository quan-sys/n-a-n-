from src.ingestion.vietstock_document_discovery import (
    normalize_vietstock_category,
    parse_vietstock_document_candidates_from_html,
)


def test_vietstock_categories_map_to_financial_statement_and_annual_report():
    assert normalize_vietstock_category("Bao cao tai chinh") == "financial_statement"
    assert normalize_vietstock_category("Bao cao thuong nien") == "annual_report"


def test_vietstock_non_target_categories_are_explicitly_rejected():
    html = """
    <div data-category="Bao cao tai chinh">
      <a href="/ABC/bctc-2025.pdf">ABC BCTC 2025</a>
    </div>
    <div data-category="Bao cao thuong nien">
      <a href="/ABC/bctn-2025.pdf">ABC BCTN 2025</a>
    </div>
    <div data-category="Nghi quyet HDQT">
      <a href="/ABC/nghi-quyet-2025.pdf">ABC Nghi quyet 2025</a>
    </div>
    """

    rows = parse_vietstock_document_candidates_from_html(
        ticker="ABC",
        html=html,
        years=[2025],
        source_url="https://finance.vietstock.vn/ABC/tai-tai-lieu.htm",
    )

    categories = {row.document_title: row.document_category_normalized for row in rows}
    assert categories["ABC BCTC 2025"] == "financial_statement"
    assert categories["ABC BCTN 2025"] == "annual_report"
    rejected = [row for row in rows if row.document_title == "ABC Nghi quyet 2025"][0]
    assert rejected.document_category_normalized == "other"
    assert rejected.manual_review_required
    assert rejected.review_reason == "REJECTED_NON_TARGET_VIETSTOCK_CATEGORY"
