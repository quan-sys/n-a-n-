from __future__ import annotations

from src.ingestion import official_pdf_python_extractor as extractor
from src.ingestion.official_pdf_backend_registry import PdfBackendAvailability


def test_01if_patch2_fake_pymupdf_extractor_emits_page_text(tmp_path, monkeypatch):
    pdf_path = tmp_path / "fake.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(
        extractor,
        "get_pdf_backend_availability",
        lambda: [
            PdfBackendAvailability("pymupdf", True, "1"),
            PdfBackendAvailability("pdfplumber", False, "", "missing"),
            PdfBackendAvailability("pypdf", False, "", "missing"),
        ],
    )
    monkeypatch.setattr(extractor, "import_module", lambda name: _fake_fitz_module())

    result = extractor.extract_pdf_with_python_backends(pdf_path, use_table_extraction=False)

    assert result.pages[0].backend == "pymupdf"
    assert "Total assets" in result.pages[0].text
    assert result.diagnostics[0].extract_status == "TEXT_EXTRACTED"


def test_01if_patch2_fake_pdfplumber_extractor_emits_table_cells(tmp_path, monkeypatch):
    pdf_path = tmp_path / "fake.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(
        extractor,
        "get_pdf_backend_availability",
        lambda: [
            PdfBackendAvailability("pymupdf", False, "", "missing"),
            PdfBackendAvailability("pdfplumber", True, "1"),
            PdfBackendAvailability("pypdf", False, "", "missing"),
        ],
    )
    monkeypatch.setattr(extractor, "import_module", lambda name: _fake_pdfplumber_module())

    result = extractor.extract_pdf_with_python_backends(pdf_path, use_table_extraction=True)

    assert result.table_cells
    assert result.table_cells[0].backend == "pdfplumber"
    assert any(cell.cell_text == "Total assets" for cell in result.table_cells)


def test_01if_patch2_extraction_diagnostics_have_no_ocr_backend(tmp_path, monkeypatch):
    pdf_path = tmp_path / "fake.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(
        extractor,
        "get_pdf_backend_availability",
        lambda: [
            PdfBackendAvailability("pymupdf", False, "", "missing"),
            PdfBackendAvailability("pdfplumber", False, "", "missing"),
            PdfBackendAvailability("pypdf", False, "", "missing"),
        ],
    )

    result = extractor.extract_pdf_with_python_backends(pdf_path, use_table_extraction=True)

    assert "ocr" not in "|".join(row.backend.lower() for row in result.diagnostics)


def _fake_fitz_module():
    class Page:
        def get_text(self, mode):
            assert mode == "text"
            return "Unit: VND\nTotal assets 9,876,543"

    class Document:
        page_count = 1

        def load_page(self, index):
            assert index == 0
            return Page()

        def close(self):
            return None

    class Fitz:
        @staticmethod
        def open(path):
            return Document()

    return Fitz


def _fake_pdfplumber_module():
    class Page:
        def extract_text(self):
            return "Unit: VND\nFinancial statements\nTotal assets"

        def extract_tables(self, table_settings=None):
            return [[["Item", "Current period"], ["Total assets", "9,876,543"]]]

    class Pdf:
        pages = [Page()]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class PdfPlumber:
        @staticmethod
        def open(path):
            return Pdf()

    return PdfPlumber
