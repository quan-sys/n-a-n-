from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.ingestion.official_finance_document_downloader import (
    DocumentFetchResponse,
    download_seed_documents,
)
from src.ingestion.official_finance_document_seed import SEED_COLUMNS


def test_01ib_domain_mismatch_downloads_but_requires_manual_review(tmp_path):
    seed = _seed_df(source_url="https://cdn.example/aaa.pdf", official_domain="official.example")

    result = download_seed_documents(seed, raw_output_dir=tmp_path, http_get=_pdf_response)
    row = result["finance_document_index"].iloc[0]

    assert row["download_status"] == "DOMAIN_MISMATCH_REVIEW"
    assert bool(row["manual_review_required"]) is True
    assert Path(row["local_path"]).exists()


def test_01ib_mock_pdf_response_saved_with_hash(tmp_path):
    result = download_seed_documents(_seed_df(), raw_output_dir=tmp_path, http_get=_pdf_response)
    row = result["finance_document_index"].iloc[0]

    assert row["download_status"] == "DOWNLOADED"
    assert row["detected_file_type"] == "pdf"
    assert len(row["file_hash"]) == 64
    assert Path(row["local_path"]).suffix == ".pdf"


def test_01ib_mock_xlsx_response_saved_with_hash(tmp_path):
    seed = _seed_df(expected_file_type="xlsx", source_url="https://official.example/aaa.xlsx")
    result = download_seed_documents(seed, raw_output_dir=tmp_path, http_get=_xlsx_response)
    row = result["finance_document_index"].iloc[0]

    assert row["download_status"] == "DOWNLOADED"
    assert row["detected_file_type"] == "xlsx"
    assert len(row["file_hash"]) == 64
    assert Path(row["local_path"]).suffix == ".xlsx"


def test_01ib_mock_html_response_saved_as_snapshot(tmp_path):
    seed = _seed_df(expected_file_type="html", source_url="https://official.example/ir")
    result = download_seed_documents(seed, raw_output_dir=tmp_path, http_get=_html_response)
    row = result["finance_document_index"].iloc[0]

    assert row["download_status"] == "HTML_SNAPSHOT_SAVED"
    assert row["detected_file_type"] == "html"
    assert Path(row["local_path"]).suffix == ".html"


def test_01ib_mock_js_block_page_is_blocked_and_manual_review(tmp_path):
    seed = _seed_df(expected_file_type="html", source_url="https://official.example/blocked")
    result = download_seed_documents(seed, raw_output_dir=tmp_path, http_get=_blocked_html_response)
    row = result["finance_document_index"].iloc[0]

    assert row["download_status"] == "SOURCE_BLOCKED_OR_JS_REQUIRED"
    assert bool(row["manual_review_required"]) is True
    assert result["manual_review_queue"].iloc[0]["priority"] == "high"


def _seed_df(**overrides):
    row = {
        "ticker": "AAA",
        "exchange": "HOSE",
        "company_name": "Example A",
        "period": "2025-Q4",
        "document_type": "financial_statement",
        "source_type": "exchange_filing",
        "source_name": "Example official",
        "source_url": "https://official.example/aaa.pdf",
        "official_domain": "official.example",
        "expected_file_type": "pdf",
        "consolidated_status": "consolidated",
        "language": "vi",
        "confidence_seed": "medium",
        "notes": "mock seed only",
    }
    row.update(overrides)
    return pd.DataFrame([row], columns=SEED_COLUMNS)


def _pdf_response(**kwargs):
    url = kwargs["url"]
    return DocumentFetchResponse(
        url=url,
        final_url=url,
        status_code=200,
        content_type="application/pdf",
        body=b"%PDF-1.4\nmock official document",
    )


def _xlsx_response(**kwargs):
    url = kwargs["url"]
    return DocumentFetchResponse(
        url=url,
        final_url=url,
        status_code=200,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        body=b"PK\x03\x04mock xlsx body",
    )


def _html_response(**kwargs):
    url = kwargs["url"]
    return DocumentFetchResponse(
        url=url,
        final_url=url,
        status_code=200,
        content_type="text/html; charset=utf-8",
        body=b"<!doctype html><html><body>official IR page</body></html>",
    )


def _blocked_html_response(**kwargs):
    url = kwargs["url"]
    return DocumentFetchResponse(
        url=url,
        final_url=url,
        status_code=200,
        content_type="text/html",
        body=b"<html><body><div id='app-root'></div><script>window.__APP={}</script><p>Enable JavaScript</p></body></html>",
    )

