from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.ingestion.official_finance_candidate_downloader import (
    download_refined_document_candidates,
    run_official_finance_candidate_download_01ie,
)
from src.ingestion.official_finance_document_downloader import DocumentFetchResponse
from src.ingestion.official_finance_document_seed import SEED_COLUMNS


def test_01ie_direct_pdf_candidate_downloads_and_saves_hash(tmp_path):
    result = download_refined_document_candidates(
        _prepared_refined_df(source_url="https://official.example/reports/bctc-hop-nhat-q1-2026.pdf", expected_file_type="pdf"),
        raw_output_dir=tmp_path,
        http_get=_mock_http_get,
    )

    row = result["finance_document_index"].iloc[0]
    assert row["download_status"] == "DOWNLOADED"
    assert row["detected_file_type"] == "pdf"
    assert len(row["file_hash"]) == 64
    assert Path(row["local_path"]).exists()


def test_01ie_direct_xlsx_candidate_downloads_and_saves_hash(tmp_path):
    result = download_refined_document_candidates(
        _prepared_refined_df(source_url="https://official.example/reports/bctc-hop-nhat-q1-2026.xlsx", expected_file_type="xlsx"),
        raw_output_dir=tmp_path,
        http_get=_mock_http_get,
    )

    row = result["finance_document_index"].iloc[0]
    assert row["download_status"] == "DOWNLOADED"
    assert row["detected_file_type"] == "xlsx"
    assert len(row["file_hash"]) == 64
    assert Path(row["local_path"]).suffix == ".xlsx"


def test_01ie_html_candidate_snapshots_and_downloads_depth1_pdf(tmp_path):
    result = download_refined_document_candidates(
        _prepared_refined_df(source_url="https://official.example/investor/financial-statements", expected_file_type="html"),
        raw_output_dir=tmp_path,
        http_get=_mock_http_get,
        max_depth1_documents_per_page=1,
    )

    index = result["finance_document_index"]
    assert set(index["candidate_origin"]) == {"HTML_SNAPSHOT_ONLY", "DEPTH1_FROM_HTML"}
    assert "HTML_SNAPSHOT_SAVED" in set(index["download_status"])
    assert "DEPTH1_DOCUMENT_DOWNLOADED" in set(index["download_status"])
    assert len(result["depth1_document_candidates"]) == 1


def test_01ie_blocks_js_captcha_like_page(tmp_path):
    result = download_refined_document_candidates(
        _prepared_refined_df(source_url="https://official.example/blocked", expected_file_type="html"),
        raw_output_dir=tmp_path,
        http_get=_mock_http_get,
    )

    row = result["finance_document_index"].iloc[0]
    assert row["download_status"] == "SOURCE_BLOCKED_OR_JS_REQUIRED"
    assert bool(row["manual_review_required"]) is True


def test_01ie_domain_mismatch_goes_to_manual_review(tmp_path):
    result = download_refined_document_candidates(
        _prepared_refined_df(
            source_url="https://cdn.example/reports/bctc-hop-nhat-q1-2026.pdf",
            expected_file_type="pdf",
            official_domain="official.example",
        ),
        raw_output_dir=tmp_path,
        http_get=_mock_http_get,
    )

    row = result["finance_document_index"].iloc[0]
    assert row["download_status"] == "DOMAIN_MISMATCH_REVIEW"
    assert bool(row["manual_review_required"]) is True


def test_01ie_standalone_document_downloaded_but_requires_manual_review(tmp_path):
    result = download_refined_document_candidates(
        _prepared_refined_df(
            source_url="https://official.example/reports/bao-cao-tai-chinh-rieng-quy-3-nam-2025.pdf",
            expected_file_type="pdf",
            consolidated_status="standalone",
            period="2025-Q3",
        ),
        raw_output_dir=tmp_path,
        http_get=_mock_http_get,
    )

    row = result["finance_document_index"].iloc[0]
    assert row["download_status"] == "DOWNLOADED"
    assert bool(row["manual_review_required"]) is True
    assert "STANDALONE_REVIEW_REQUIRED" in row["review_reason"]


def test_01ie_dry_run_does_not_create_raw_files_or_report_downloaded(tmp_path):
    refined_file = tmp_path / "refined.csv"
    candidate_file = tmp_path / "candidates.csv"
    _seed_df().to_csv(refined_file, index=False)
    _candidate_df().to_csv(candidate_file, index=False)

    result = run_official_finance_candidate_download_01ie(
        refined_seed_file=refined_file,
        candidate_file=candidate_file,
        output_dir=tmp_path / "reports",
        raw_output_dir=tmp_path / "raw",
        dry_run=True,
        allow_partial=True,
    )

    index = result["finance_document_index"]
    assert not (tmp_path / "raw").exists()
    assert not index["download_status"].isin(["DOWNLOADED", "DEPTH1_DOCUMENT_DOWNLOADED"]).any()
    assert index.iloc[0]["file_hash"] == ""


def test_01ie_no_finance_numeric_parsing_occurs(tmp_path):
    result = download_refined_document_candidates(
        _prepared_refined_df(source_url="https://official.example/reports/bctc-hop-nhat-q1-2026.pdf", expected_file_type="pdf"),
        raw_output_dir=tmp_path,
        http_get=_mock_http_get,
    )

    prohibited = {"revenue", "net_profit", "assets", "equity", "cash_flow", "eps"}
    assert prohibited.isdisjoint(set(result["finance_document_index"].columns))


def _seed_df(**overrides):
    row = {
        "ticker": "AAA",
        "exchange": "HOSE",
        "company_name": "Example A",
        "period": "2026-Q1",
        "document_type": "financial_statement",
        "source_type": "company_ir",
        "source_name": "Example official",
        "source_url": "https://official.example/reports/bctc-hop-nhat-q1-2026.pdf",
        "official_domain": "official.example",
        "expected_file_type": "pdf",
        "consolidated_status": "consolidated",
        "language": "vi",
        "confidence_seed": "medium",
        "notes": "01ID_PATCH1_CANDIDATE_NOT_FINANCE_EVIDENCE_YET",
    }
    row.update(overrides)
    return pd.DataFrame([row], columns=SEED_COLUMNS)


def _prepared_refined_df(**overrides):
    frame = _seed_df(**overrides)
    frame["candidate_score"] = 79
    frame["candidate_score_band"] = "REVIEWABLE_CANDIDATE"
    frame["candidate_reason"] = "DIRECT_PDF_FINANCE_KEYWORD"
    frame["anchor_text"] = ""
    frame["candidate_manual_review_required"] = True
    return frame


def _candidate_df():
    return pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "candidate_url": "https://official.example/reports/bctc-hop-nhat-q1-2026.pdf",
                "score": 79,
                "score_band": "REVIEWABLE_CANDIDATE",
                "manual_review_required": True,
                "reason": "DIRECT_PDF_FINANCE_KEYWORD",
                "anchor_text": "BCTC hop nhat Q1 2026",
            }
        ]
    )


def _mock_http_get(**kwargs):
    url = kwargs["url"]
    if url.endswith(".xlsx"):
        return DocumentFetchResponse(
            url=url,
            final_url=url,
            status_code=200,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            body=b"PK\x03\x04mock xlsx body",
        )
    if url.endswith(".pdf"):
        return DocumentFetchResponse(
            url=url,
            final_url=url,
            status_code=200,
            content_type="application/pdf",
            body=b"%PDF-1.4\nmock official finance document",
        )
    if url.endswith("/blocked"):
        return DocumentFetchResponse(
            url=url,
            final_url=url,
            status_code=200,
            content_type="text/html",
            body=b"<html><body><div id='app-root'></div><script>window.__APP={}</script><p>Enable JavaScript</p></body></html>",
        )
    return DocumentFetchResponse(
        url=url,
        final_url=url,
        status_code=200,
        content_type="text/html; charset=utf-8",
        body=b"""
        <!doctype html><html><body>
        <a href="/reports/bctc-hop-nhat-quy-1-nam-2026.pdf">BCTC hop nhat Quy 1 nam 2026</a>
        </body></html>
        """,
    )
