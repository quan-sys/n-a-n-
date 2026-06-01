"""Utilities for loading and validating candidate data source registries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None


REQUIRED_DATASET_FIELDS = [
    "dataset_name",
    "description",
    "required_for_stage",
    "production_required",
    "sources",
]

REQUIRED_SOURCE_FIELDS = [
    "source_name",
    "source_type",
    "primary_or_backup",
    "expected_fields",
    "update_frequency",
    "reliability_level",
    "requires_api_key",
    "access_method",
    "output_dataset_schema",
    "confidence_default",
    "notes",
    "legal_or_terms_notes",
]

ALLOWED_SOURCE_TYPES = {
    "python_package",
    "official_exchange",
    "official_regulator",
    "official_macro",
    "official_company",
    "public_file",
    "news_site",
    "manual_file",
    "unknown",
}

ALLOWED_PRIMARY_OR_BACKUP = {"primary", "backup", "fallback"}

ALLOWED_RELIABILITY_LEVELS = {"high", "medium", "low", "unknown"}

ALLOWED_UPDATE_FREQUENCIES = {
    "daily",
    "weekly",
    "monthly",
    "quarterly",
    "event_driven",
    "manual",
    "unknown",
}

ALLOWED_ACCESS_METHODS = {
    "package",
    "api",
    "csv_download",
    "xlsx_download",
    "html_table",
    "pdf_download",
    "manual_upload",
    "rss",
    "unknown",
}


def load_source_registry(path: str) -> dict[str, Any]:
    """Load the YAML source registry."""

    if yaml is None:
        raise ImportError(
            "PyYAML is required to load YAML registry files. Install 'pyyaml' "
            "before calling load_source_registry()."
        )

    registry_path = Path(path)
    with registry_path.open("r", encoding="utf-8") as registry_file:
        registry = yaml.safe_load(registry_file)

    if not isinstance(registry, dict):
        raise ValueError("Source registry must contain a YAML mapping.")

    return registry


def validate_source_registry(registry: dict[str, Any]) -> dict[str, Any]:
    """Validate registry structure and enum values without raising on bad config."""

    result: dict[str, Any] = {
        "is_valid": True,
        "errors": [],
        "warnings": [],
        "datasets": [],
    }

    if not isinstance(registry, dict):
        result["is_valid"] = False
        result["errors"].append("Registry must be a dictionary.")
        return result

    datasets = registry.get("datasets")
    if not isinstance(datasets, list):
        result["is_valid"] = False
        result["errors"].append("Registry must contain a datasets list.")
        return result

    for dataset_index, dataset in enumerate(datasets):
        if not isinstance(dataset, dict):
            result["is_valid"] = False
            result["errors"].append(f"Dataset at index {dataset_index} must be a dict.")
            continue

        dataset_name = dataset.get("dataset_name", f"<dataset_{dataset_index}>")
        result["datasets"].append(dataset_name)
        _validate_dataset(dataset, dataset_name, result)

    result["warnings"] = _dedupe(result["warnings"])
    result["errors"] = _dedupe(result["errors"])
    result["is_valid"] = not result["errors"]
    return result


def get_dataset_sources(
    registry: dict[str, Any], dataset_name: str
) -> list[dict[str, Any]]:
    """Return all source entries for a dataset, or an empty list if unknown."""

    dataset = _find_dataset(registry, dataset_name)
    if not dataset:
        return []

    sources = dataset.get("sources", [])
    if not isinstance(sources, list):
        return []

    return [source for source in sources if isinstance(source, dict)]


def get_primary_source(
    registry: dict[str, Any], dataset_name: str
) -> dict[str, Any] | None:
    """Return the first primary source for a dataset, if configured."""

    for source in get_dataset_sources(registry, dataset_name):
        if source.get("primary_or_backup") == "primary":
            return source
    return None


def get_fallback_sources(
    registry: dict[str, Any], dataset_name: str
) -> list[dict[str, Any]]:
    """Return backup and fallback source entries for a dataset."""

    return [
        source
        for source in get_dataset_sources(registry, dataset_name)
        if source.get("primary_or_backup") in {"backup", "fallback"}
    ]


def list_required_datasets_for_stage(
    registry: dict[str, Any], stage_name: str
) -> list[str]:
    """List datasets marked as required for a pipeline stage."""

    if not isinstance(registry, dict):
        return []

    required_datasets: list[str] = []
    for dataset in registry.get("datasets", []):
        if not isinstance(dataset, dict):
            continue

        required_for_stage = dataset.get("required_for_stage", [])
        if isinstance(required_for_stage, str):
            stages = [required_for_stage]
        elif isinstance(required_for_stage, list):
            stages = required_for_stage
        else:
            stages = []

        if stage_name in stages and isinstance(dataset.get("dataset_name"), str):
            required_datasets.append(dataset["dataset_name"])

    return required_datasets


def _validate_dataset(
    dataset: dict[str, Any], dataset_name: str, result: dict[str, Any]
) -> None:
    for field in REQUIRED_DATASET_FIELDS:
        if field not in dataset:
            result["errors"].append(f"{dataset_name}: missing dataset field '{field}'.")

    sources = dataset.get("sources", [])
    if not isinstance(sources, list):
        result["errors"].append(f"{dataset_name}: sources must be a list.")
        sources = []
    elif not sources:
        result["errors"].append(f"{dataset_name}: at least one source is required.")

    production_required = bool(dataset.get("production_required"))
    has_primary_source = any(
        isinstance(source, dict) and source.get("primary_or_backup") == "primary"
        for source in sources
    )
    if production_required and not has_primary_source:
        result["warnings"].append(
            f"{dataset_name}: production-required dataset has no primary source."
        )

    for source_index, source in enumerate(sources):
        if not isinstance(source, dict):
            result["errors"].append(
                f"{dataset_name}: source at index {source_index} must be a dict."
            )
            continue
        _validate_source(source, dataset_name, source_index, result)


def _validate_source(
    source: dict[str, Any],
    dataset_name: str,
    source_index: int,
    result: dict[str, Any],
) -> None:
    source_label = source.get("source_name", f"source_{source_index}")
    context = f"{dataset_name}/{source_label}"

    for field in REQUIRED_SOURCE_FIELDS:
        if field not in source:
            result["errors"].append(f"{context}: missing source field '{field}'.")

    _check_enum(source, "source_type", ALLOWED_SOURCE_TYPES, context, result)
    _check_enum(
        source,
        "primary_or_backup",
        ALLOWED_PRIMARY_OR_BACKUP,
        context,
        result,
    )
    _check_enum(
        source,
        "reliability_level",
        ALLOWED_RELIABILITY_LEVELS,
        context,
        result,
    )
    _check_enum(
        source,
        "update_frequency",
        ALLOWED_UPDATE_FREQUENCIES,
        context,
        result,
    )
    _check_enum(source, "access_method", ALLOWED_ACCESS_METHODS, context, result)

    reliability_level = source.get("reliability_level")
    if reliability_level in {"low", "unknown"}:
        result["warnings"].append(
            f"{context}: reliability_level is {reliability_level}."
        )

    access_method = source.get("access_method")
    if access_method == "unknown":
        result["warnings"].append(f"{context}: access_method is unknown.")

    needs_terms_note = (
        source.get("source_type") == "news_site"
        or source.get("access_method") in {"html_table", "pdf_download"}
    )
    if needs_terms_note and not _has_text(source.get("legal_or_terms_notes")):
        result["warnings"].append(
            f"{context}: legal_or_terms_notes should explain access constraints."
        )


def _check_enum(
    source: dict[str, Any],
    field: str,
    allowed_values: set[str],
    context: str,
    result: dict[str, Any],
) -> None:
    value = source.get(field)
    if value is None:
        return
    if value not in allowed_values:
        result["errors"].append(
            f"{context}: invalid {field} '{value}'. Allowed values: "
            f"{', '.join(sorted(allowed_values))}."
        )


def _find_dataset(
    registry: dict[str, Any], dataset_name: str
) -> dict[str, Any] | None:
    if not isinstance(registry, dict):
        return None

    for dataset in registry.get("datasets", []):
        if isinstance(dataset, dict) and dataset.get("dataset_name") == dataset_name:
            return dataset

    return None


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
