"""Schema loading and DataFrame validation utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None


def load_schema(schema_path: str | Path) -> dict[str, Any]:
    """Load a YAML schema file.

    PyYAML is expected for YAML support. The error message is explicit so future
    callers know which dependency is missing.
    """

    if yaml is None:
        raise ImportError(
            "PyYAML is required to load YAML schema files. Install 'pyyaml' or "
            "provide a loader before calling load_schema()."
        )

    path = Path(schema_path)
    with path.open("r", encoding="utf-8") as schema_file:
        schema = yaml.safe_load(schema_file)

    if not isinstance(schema, dict):
        raise ValueError("Schema file must contain a YAML mapping at the top level.")

    return schema


def validate_dataframe(
    df: Any, dataset_name: str, schema: dict[str, Any]
) -> dict[str, Any]:
    """Validate a DataFrame-like object against required schema columns."""

    result: dict[str, Any] = {
        "dataset_name": dataset_name,
        "is_valid": True,
        "missing_columns": [],
        "extra_columns": [],
        "warnings": [],
        "errors": [],
    }

    datasets = schema.get("datasets", {})
    if dataset_name not in datasets:
        result["is_valid"] = False
        result["errors"].append(f"Unknown dataset: {dataset_name}")
        return result

    dataset_schema = datasets[dataset_name]
    required_columns = dataset_schema.get("required_fields", [])
    if not isinstance(required_columns, list):
        result["is_valid"] = False
        result["errors"].append(
            f"Dataset '{dataset_name}' must define required_fields as a list."
        )
        return result

    if not hasattr(df, "columns"):
        result["is_valid"] = False
        result["errors"].append("Input object must expose a columns attribute.")
        return result

    actual_columns = list(df.columns)
    missing_columns = [
        column for column in required_columns if column not in actual_columns
    ]
    extra_columns = [
        column for column in actual_columns if column not in required_columns
    ]

    result["missing_columns"] = missing_columns
    result["extra_columns"] = extra_columns

    if missing_columns:
        result["is_valid"] = False
        result["warnings"].append(
            "Missing required columns: " + ", ".join(missing_columns)
        )

    return result
