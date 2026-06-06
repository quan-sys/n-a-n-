from __future__ import annotations

from src.ingestion.official_finance_html_document_finder import find_depth1_document_candidates_from_html


def test_01ie_depth1_extractor_resolves_relative_links():
    html = '<a href="/reports/bctc-hop-nhat-quy-1-nam-2026.pdf">BCTC hop nhat Quy 1 nam 2026</a>'

    result = find_depth1_document_candidates_from_html(
        ticker="AAA",
        source_html_url="https://official.example/investor",
        source_html_local_path="snapshot.html",
        html=html,
        official_domain="official.example",
    )

    assert len(result) == 1
    assert result.iloc[0]["depth1_url"] == "https://official.example/reports/bctc-hop-nhat-quy-1-nam-2026.pdf"
    assert result.iloc[0]["period_guess"] == "2026-Q1"


def test_01ie_depth1_extractor_keeps_same_domain_and_official_subdomain_only():
    html = """
    <a href="https://official.example/reports/bctc-hop-nhat-q1-2026.pdf">Official</a>
    <a href="https://files.official.example/reports/bctc-hop-nhat-q1-2026.pdf">Subdomain official</a>
    <a href="https://evil.example/reports/bctc-hop-nhat-q1-2026.pdf">External</a>
    """

    result = find_depth1_document_candidates_from_html(
        ticker="AAA",
        source_html_url="https://official.example/investor",
        source_html_local_path="snapshot.html",
        html=html,
        official_domain="official.example",
    )

    assert set(result["depth1_domain"]) == {"official.example", "files.official.example"}
    assert not result["depth1_url"].str.contains("evil.example").any()


def test_01ie_depth1_extractor_filters_generic_pdf_without_finance_pattern():
    html = """
    <a href="/files/product-brochure.pdf">Product brochure</a>
    <a href="/files/bctc-hop-nhat-q1-2026.pdf">BCTC hop nhat Q1 2026</a>
    """

    result = find_depth1_document_candidates_from_html(
        ticker="AAA",
        source_html_url="https://official.example/investor",
        source_html_local_path="snapshot.html",
        html=html,
        official_domain="official.example",
    )

    assert len(result) == 1
    assert result.iloc[0]["depth1_url"].endswith("bctc-hop-nhat-q1-2026.pdf")
