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
    assert result["score_band"] == "LOW_CONFIDENCE_CANDIDATE"


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
    assert result["score_band"] in {"LOW_CONFIDENCE_CANDIDATE", "REJECTED_CANDIDATE"}
    assert "GENERIC_PAGE_PENALTY" in result["reason"]


def test_01id_rejects_old_2015_only_link():
    result = score_official_document_candidate(
        candidate_url="https://official.example/reports/bctc-2015.pdf",
        anchor_text="BCTC 2015",
        official_domain="official.example",
    )

    assert result["score_band"] == "REJECTED_CANDIDATE"
    assert "OLD_YEAR_PENALTY" in result["reason"]


def test_01id_domain_mismatch_goes_to_manual_review():
    result = score_official_document_candidate(
        candidate_url="https://cdn.example/reports/bctc-2025.pdf",
        anchor_text="BCTC 2025",
        official_domain="official.example",
    )

    assert result["manual_review_required"] is True
    assert "DOMAIN_MISMATCH" in result["reason"]


def test_01id_patch1_scores_fpt_bctc_hop_nhat_q1_2026_reviewable_or_high():
    result = score_official_document_candidate(
        candidate_url="https://fpt.com/-/media/project/fpt-corporation/fpt/ir/information-disclosures/year-report/2026/april/20260424---fpt---bctc-hop-nhat-quy-1-nam-2026.pdf",
        anchor_text="",
        official_domain="fpt.com",
        source_download_status="SOURCE_BLOCKED_OR_JS_REQUIRED",
    )

    assert result["score_band"] in {"REVIEWABLE_CANDIDATE", "HIGH_CONFIDENCE_CANDIDATE"}
    assert result["period_guess"] == "2026-Q1"
    assert "DIRECT_PDF_FINANCE_KEYWORD" in result["reason"]
    assert "SOURCE_FROM_BLOCKED_PAGE_REVIEW" in result["reason"]
    assert result["manual_review_required"] is True


def test_01id_patch1_scores_ssi_standalone_q3_2025_reviewable_with_manual_reason():
    result = score_official_document_candidate(
        candidate_url="https://www.ssi.com.vn/upload/files/IR/20251020_SSI_Bao_cao_tai_chinh_rieng_Quy_3_nam_2025.pdf",
        anchor_text="",
        official_domain="ssi.com.vn",
        source_download_status="SOURCE_BLOCKED_OR_JS_REQUIRED",
    )

    assert result["score_band"] == "REVIEWABLE_CANDIDATE"
    assert result["period_guess"] == "2025-Q3"
    assert "STANDALONE_REVIEW_REQUIRED" in result["reason"]
    assert result["manual_review_required"] is True


def test_01id_patch1_scores_vgc_finance_document_endpoint_without_pdf_reviewable():
    result = score_official_document_candidate(
        candidate_url="https://viglacera.com.vn/document/bao-cao-tai-chinh-hop-nhat-quy-i2026-tieng-anh",
        anchor_text="Báo cáo tài chính hợp nhất Quý I/2026",
        official_domain="viglacera.com.vn",
        page_hints={"error_page": True},
    )

    assert result["score_band"] in {"REVIEWABLE_CANDIDATE", "HIGH_CONFIDENCE_CANDIDATE"}
    assert result["period_guess"] == "2026-Q1"
    assert "BCTC_KEYWORD_MATCH" in result["reason"]
    assert "SOURCE_FROM_ERROR_PAGE_REVIEW" in result["reason"]
    assert result["manual_review_required"] is True


def test_01id_patch1_generic_investor_homepage_without_finance_keywords_stays_low_or_rejected():
    result = score_official_document_candidate(
        candidate_url="https://official.example/investor-relations",
        anchor_text="Investor relations",
        official_domain="official.example",
    )

    assert result["score_band"] in {"LOW_CONFIDENCE_CANDIDATE", "REJECTED_CANDIDATE"}
    assert result["manual_review_required"] is True
    assert "NO_FINANCE_KEYWORDS" in result["reason"]


def test_01id_patch1_rejects_css_js_and_wcm_urls():
    for url in [
        "https://official.example/assets/site.css",
        "https://official.example/assets/site.js",
        "https://official.example/wcm/connect/menu",
    ]:
        result = score_official_document_candidate(
            candidate_url=url,
            anchor_text="metadata link",
            official_domain="official.example",
        )
        assert result["score_band"] == "REJECTED_CANDIDATE"
        assert "NON_DOCUMENT_ASSET" in result["reason"]


def test_01id_patch1_handles_mojibake_vietnamese_keywords():
    result = score_official_document_candidate(
        candidate_url="https://official.example/reports/bao-cao-tai-chinh-hop-nhat-quy-i2026.pdf",
        anchor_text="bÃ¡o cÃ¡o tÃ i chÃ­nh há»£p nháº¥t quÃ½ I/2026",
        official_domain="official.example",
    )

    assert result["score_band"] == "HIGH_CONFIDENCE_CANDIDATE"
    assert result["period_guess"] == "2026-Q1"
    assert "CONSOLIDATED_KEYWORD_MATCH" in result["reason"]
