from __future__ import annotations

from pathlib import Path

from src.ingestion.secret_redaction import redact_snapshot_bytes, redact_text_secrets
from src.ingestion.source_snapshot import _write_snapshot


def test_redacts_google_maps_key_from_text_without_static_secret_literal():
    key = _google_api_key()
    text = f"<script src='https://maps.example.test/js?key={key}&libraries=places'></script>"

    redacted = redact_text_secrets(text)

    assert key not in redacted
    assert "[REDACTED_GOOGLE_API_KEY]" in redacted


def test_redacts_only_text_snapshot_bytes():
    key = _google_api_key()
    html_body = f"<html><script src='https://maps.example.test/js?key={key}'></script></html>".encode(
        "utf-8"
    )
    pdf_body = b"%PDF-1.4\n" + key.encode("utf-8")

    redacted_html = redact_snapshot_bytes(html_body, content_type="text/html", file_suffix="html")
    unchanged_pdf = redact_snapshot_bytes(pdf_body, content_type="application/pdf", file_suffix="pdf")

    assert key.encode("utf-8") not in redacted_html
    assert b"[REDACTED_GOOGLE_API_KEY]" in redacted_html
    assert unchanged_pdf == pdf_body


def test_public_source_snapshot_writer_redacts_saved_html(tmp_path):
    key = _google_api_key()
    body = f"<html><script src='https://maps.example.test/js?key={key}'></script></html>".encode(
        "utf-8"
    )

    snapshot_path = _write_snapshot(
        body=body,
        url="https://example.test",
        snapshot_dir=tmp_path,
        source_name="example",
        source_category="manual_csv",
        content_type="text/html",
        content_hash="abc123",
        max_snapshot_bytes=100_000,
    )

    saved = Path(snapshot_path).read_text(encoding="utf-8")
    assert key not in saved
    assert "[REDACTED_GOOGLE_API_KEY]" in saved


def _google_api_key() -> str:
    return ("AI" + "za") + ("A" * 35)
