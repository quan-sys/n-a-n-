"""Installability/importability diagnostics for 04C alternative providers."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
from typing import Any, Callable

import pandas as pd

from src.providers.alternative.source_registry import providers_from_config


INSTALLABILITY_COLUMNS = [
    "provider_name",
    "package_name",
    "package_found",
    "import_attempted",
    "import_status",
    "import_error_type",
    "import_error_message",
    "version_detected",
    "usable_for_04c",
    "notes",
]


def probe_installability_04c(
    config: dict[str, Any],
    *,
    import_module_func: Callable[[str], Any] | None = None,
    find_spec_func: Callable[[str], Any] | None = None,
    version_func: Callable[[str], str] | None = None,
) -> pd.DataFrame:
    import_module_func = import_module_func or importlib.import_module
    find_spec_func = find_spec_func or importlib.util.find_spec
    version_func = version_func or importlib.metadata.version
    rows = []
    for provider in providers_from_config(config):
        provider_name = str(provider.get("provider_name", ""))
        package_name = provider.get("package_name")
        if not package_name:
            rows.append(
                _row(
                    provider_name=provider_name,
                    package_name="",
                    package_found=False,
                    import_attempted=False,
                    import_status="NO_PACKAGE_STATIC_SOURCE",
                    version_detected="",
                    usable_for_04c=str(provider.get("role", "")) == "static_historical_fallback_only",
                    notes="No Python package configured; static/local source only.",
                )
            )
            continue
        package = str(package_name)
        package_found = False
        version_detected = ""
        import_status = "PACKAGE_NOT_FOUND"
        error_type = ""
        error_message = ""
        try:
            package_found = find_spec_func(package) is not None
        except Exception as exc:  # noqa: BLE001 - diagnostic path must not fail the probe.
            error_type = type(exc).__name__
            error_message = str(exc)
        try:
            version_detected = version_func(package)
        except importlib.metadata.PackageNotFoundError:
            version_detected = ""
        except Exception as exc:  # noqa: BLE001
            if not error_type:
                error_type = type(exc).__name__
                error_message = str(exc)
        if str(provider.get("role", "")) == "primary_reference":
            import_status = "PACKAGE_FOUND_IMPORT_SKIPPED_PRIMARY" if package_found else "PACKAGE_NOT_FOUND"
            rows.append(
                _row(
                    provider_name=provider_name,
                    package_name=package,
                    package_found=package_found,
                    import_attempted=False,
                    import_status=import_status,
                    import_error_type=error_type,
                    import_error_message=error_message,
                    version_detected=version_detected,
                    usable_for_04c=package_found,
                    notes="Primary provider package import is skipped to avoid side effects; primary data comes from the existing snapshot.",
                )
            )
            continue
        import_attempted = bool(package_found)
        if package_found:
            try:
                import_module_func(package)
                import_status = "IMPORT_OK"
            except Exception as exc:  # noqa: BLE001
                import_status = "IMPORT_ERROR"
                error_type = type(exc).__name__
                error_message = str(exc)
        rows.append(
            _row(
                provider_name=provider_name,
                package_name=package,
                package_found=package_found,
                import_attempted=import_attempted,
                import_status=import_status,
                import_error_type=error_type,
                import_error_message=error_message,
                version_detected=version_detected,
                usable_for_04c=import_status == "IMPORT_OK",
                notes=_notes(provider_name, import_status),
            )
        )
    return pd.DataFrame(rows, columns=INSTALLABILITY_COLUMNS)


def _row(
    *,
    provider_name: str,
    package_name: str,
    package_found: bool,
    import_attempted: bool,
    import_status: str,
    import_error_type: str = "",
    import_error_message: str = "",
    version_detected: str = "",
    usable_for_04c: bool = False,
    notes: str = "",
) -> dict[str, Any]:
    return {
        "provider_name": provider_name,
        "package_name": package_name,
        "package_found": bool(package_found),
        "import_attempted": bool(import_attempted),
        "import_status": import_status,
        "import_error_type": import_error_type,
        "import_error_message": import_error_message,
        "version_detected": version_detected,
        "usable_for_04c": bool(usable_for_04c),
        "notes": notes,
    }


def _notes(provider_name: str, import_status: str) -> str:
    if import_status == "IMPORT_OK":
        return "Package imported; 04C may attempt guarded provider calls if network is enabled."
    if import_status == "PACKAGE_NOT_FOUND":
        return "Optional provider package is not installed; 04C records this without failing."
    if import_status == "IMPORT_ERROR":
        return "Optional provider package was found but failed import; inspect error fields."
    return f"{provider_name} import status: {import_status}"
