"""Backend availability registry for non-OCR official PDF extraction."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from importlib import metadata
from typing import Any

import pandas as pd


PDF_BACKEND_AVAILABILITY_COLUMNS_01IF_PATCH2 = [
    "backend",
    "installed",
    "version",
    "import_error",
    "notes",
]

PDF_BACKENDS_01IF_PATCH2 = [
    ("pymupdf", "fitz", "pymupdf"),
    ("pdfplumber", "pdfplumber", "pdfplumber"),
    ("pypdf", "pypdf", "pypdf"),
]


@dataclass(frozen=True)
class PdfBackendAvailability:
    backend: str
    installed: bool
    version: str
    import_error: str = ""
    notes: str = ""


def get_pdf_backend_availability() -> list[PdfBackendAvailability]:
    """Return importability diagnostics for non-OCR PDF backends."""

    rows = []
    for backend, module_name, package_name in PDF_BACKENDS_01IF_PATCH2:
        try:
            import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            rows.append(
                PdfBackendAvailability(
                    backend=backend,
                    installed=False,
                    version="",
                    import_error=f"{type(exc).__name__}:{exc}",
                    notes="optional non-OCR backend unavailable",
                )
            )
            continue
        rows.append(
            PdfBackendAvailability(
                backend=backend,
                installed=True,
                version=_package_version(package_name),
                notes="available; no OCR capability used",
            )
        )
    return rows


def build_pdf_backend_availability_rows(
    availability: list[PdfBackendAvailability] | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for backend in availability or get_pdf_backend_availability():
        rows.append(
            {
                "backend": backend.backend,
                "installed": backend.installed,
                "version": backend.version,
                "import_error": backend.import_error,
                "notes": backend.notes,
            }
        )
    return rows


def pdf_python_backend_ready_status(availability: pd.DataFrame | list[PdfBackendAvailability] | None) -> str:
    if availability is None:
        availability = get_pdf_backend_availability()
    if isinstance(availability, pd.DataFrame):
        if availability.empty:
            return "False"
        installed = {
            str(row.get("backend", "")): str(row.get("installed", "")).lower() in {"true", "1", "yes"}
            for _, row in availability.iterrows()
        }
    else:
        installed = {row.backend: bool(row.installed) for row in availability}
    if installed.get("pymupdf") and installed.get("pdfplumber"):
        return "True"
    if any(installed.values()):
        return "Partial"
    return "False"


def _package_version(package_name: str) -> str:
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return ""
