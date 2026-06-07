from __future__ import annotations

from src.ingestion import official_pdf_text_extractor as extractor


def test_01if_patch1_missing_optional_pdf_backends_are_diagnostics_not_crashes(tmp_path, monkeypatch):
    monkeypatch.setattr(extractor, "fitz", None)
    monkeypatch.setattr(extractor, "pdfplumber", None)
    pdf_path = tmp_path / "minimal.pdf"
    pdf_path.write_text("%PDF-1.4\n%%EOF", encoding="utf-8")

    result = extractor.extract_pdf_document_content(pdf_path, use_table_extraction=True)

    statuses = {(row.backend, row.extract_status) for row in result.diagnostics}
    assert ("pymupdf", "BACKEND_UNAVAILABLE") in statuses
    assert ("pdfplumber", "BACKEND_UNAVAILABLE") in statuses
    assert result.pages


def test_01if_patch1_no_ocr_backend_is_invoked_or_reported(tmp_path):
    pdf_path = tmp_path / "minimal.pdf"
    pdf_path.write_text("%PDF-1.4\n%%EOF", encoding="utf-8")

    result = extractor.extract_pdf_document_content(pdf_path, use_table_extraction=True)

    backend_names = "|".join(row.backend.lower() for row in result.diagnostics)
    assert "ocr" not in backend_names
