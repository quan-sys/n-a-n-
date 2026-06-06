from __future__ import annotations

from pathlib import Path

from src.ingestion.official_finance_link_extractor import (
    extract_link_candidates_from_snapshot,
    score_official_document_candidate,
)


def test_01id_extracts_links_from_local_html_snapshot(tmp_path):
    html = """
    <html><head><link rel="canonical" href="/investor"></head>
    <body><a href="/files/bctc-hop-nhat-2025-q4.pdf">BCTC hop nhat Q4 2025</a></body></html>
    """
    snapshot = tmp_path / "page.html"
    snapshot.write_text(html, encoding="utf-8")

    candidates = extract_link_candidates_from_snapshot(
        ticker="AAA",
        source_page_url="https://official.example/investor",
        source_snapshot_path=snapshot,
        official_domain="official.example",
    )

    assert len(candidates) >= 1
    row = candidates[candidates["candidate_url"].str.endswith(".pdf")].iloc[0]
    assert row["candidate_url"] == "https://official.example/files/bctc-hop-nhat-2025-q4.pdf"
    assert row["score_band"] == "HIGH_CONFIDENCE_CANDIDATE"


def test_01id_resolves_relative_links(tmp_path):
    snapshot = tmp_path / "page.html"
    snapshot.write_text('<a href="../reports/financial-report-2025.xlsx">Financial report 2025</a>', encoding="utf-8")

    candidates = extract_link_candidates_from_snapshot(
        ticker="AAA",
        source_page_url="https://official.example/investor/financial/",
        source_snapshot_path=snapshot,
        official_domain="official.example",
    )

    assert candidates.iloc[0]["candidate_url"] == "https://official.example/investor/reports/financial-report-2025.xlsx"
    assert candidates.iloc[0]["file_extension"] == "xlsx"


def test_01id_scores_https_pdf_financial_statement_high():
    result = score_official_document_candidate(
        candidate_url="https://official.example/reports/bctc-hop-nhat-q4-2025.pdf",
        anchor_text="Bao cao tai chinh hop nhat Q4 2025",
        official_domain="official.example",
    )

    assert result["score_band"] == "HIGH_CONFIDENCE_CANDIDATE"
    assert result["manual_review_required"] is False


def test_01id_scores_https_annual_report_high():
    result = score_official_document_candidate(
        candidate_url="https://official.example/reports/annual-report-2025.pdf",
        anchor_text="Annual report 2025",
        official_domain="official.example",
    )

    assert result["score_band"] == "HIGH_CONFIDENCE_CANDIDATE"
    assert result["candidate_document_type"] == "annual_report"


def test_01id_penalizes_http_without_https_redirect():
    result = score_official_document_candidate(
        candidate_url="http://official.example/reports/bctc-2025.pdf",
        anchor_text="BCTC 2025",
        official_domain="official.example",
    )

    assert result["manual_review_required"] is True
    assert "HTTP_NOT_REDIRECTED_TO_HTTPS" in result["reason"]


def test_01id_http_redirect_to_https_is_reviewable_not_clean():
    result = score_official_document_candidate(
        candidate_url="http://official.example/reports/bctc-2025.pdf",
        final_url="https://official.example/reports/bctc-2025.pdf",
        anchor_text="BCTC 2025",
        official_domain="official.example",
    )

    assert result["score_band"] == "REVIEWABLE_CANDIDATE"
    assert result["manual_review_required"] is True
    assert "HTTP_REDIRECTED_TO_HTTPS_REVIEW" in result["reason"]


def test_01id_penalizes_error_final_url():
    result = score_official_document_candidate(
        candidate_url="https://official.example/reports/bctc-2025.pdf",
        final_url="https://official.example/error-404",
        anchor_text="BCTC 2025",
        official_domain="official.example",
    )

    assert result["manual_review_required"] is True
    assert "ERROR_OR_404_PAGE" in result["reason"]


def test_01id_penalizes_generic_news_without_finance_keywords():
    result = score_official_document_candidate(
        candidate_url="https://official.example/news/company-update-2025",
        anchor_text="Tin tuc cong ty",
        official_domain="official.example",
    )

    assert result["manual_review_required"] is True
    assert "GENERIC_NEWS_PAGE" in result["reason"]


def test_01id_rejects_old_2015_only_link():
    result = score_official_document_candidate(
        candidate_url="https://official.example/reports/bctc-2015.pdf",
        anchor_text="BCTC 2015",
        official_domain="official.example",
    )

    assert result["score_band"] == "REJECTED_CANDIDATE"
    assert "OLD_YEAR_ONLY" in result["reason"]


def test_01id_domain_mismatch_goes_to_manual_review():
    result = score_official_document_candidate(
        candidate_url="https://cdn.example/reports/bctc-2025.pdf",
        anchor_text="BCTC 2025",
        official_domain="official.example",
    )

    assert result["manual_review_required"] is True
    assert "DOMAIN_MISMATCH" in result["reason"]
