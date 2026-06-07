from __future__ import annotations

from src.ingestion import official_pdf_backend_registry as registry


def test_01if_patch2_backend_registry_reports_missing_without_crash(monkeypatch):
    def fake_import_module(name):
        if name == "pdfplumber":
            raise ImportError("not installed")
        return object()

    monkeypatch.setattr(registry, "import_module", fake_import_module)
    monkeypatch.setattr(registry.metadata, "version", lambda package: "1.0")

    rows = registry.get_pdf_backend_availability()

    by_backend = {row.backend: row for row in rows}
    assert by_backend["pymupdf"].installed is True
    assert by_backend["pdfplumber"].installed is False
    assert by_backend["pypdf"].installed is True


def test_01if_patch2_backend_registry_has_no_ocr_backend():
    backend_names = [backend for backend, _, _ in registry.PDF_BACKENDS_01IF_PATCH2]

    assert "ocr" not in "|".join(backend_names).lower()
