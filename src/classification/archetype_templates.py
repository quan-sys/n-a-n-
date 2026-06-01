"""Reusable L1 archetype template helpers.

These helpers define and validate analytical templates only. They do not score
stocks, run sector cycles, compare peers, perform valuation, or make
recommendations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None


REQUIRED_ARCHETYPES = [
    "export_manufacturer",
    "commodity_processor",
    "financial_bank",
    "real_estate_developer",
    "utility_regulated",
    "logistics_infrastructure",
    "consumer_defensive",
    "cyclical_manufacturer",
    "securities_broker",
    "holding_company",
    "unknown",
]

REQUIRED_TEMPLATE_FIELDS = [
    "archetype_id",
    "display_name",
    "description",
    "typical_micro_sectors",
    "business_model_logic",
    "key_economic_exposures",
    "typical_revenue_drivers",
    "typical_cost_drivers",
    "balance_sheet_focus",
    "cash_flow_focus",
    "survival_risk_focus",
    "quality_signals",
    "red_flags",
    "cycle_sensitivity",
    "data_requirements",
    "manual_review_triggers",
    "notes",
]

LIST_TEMPLATE_FIELDS = [
    "typical_micro_sectors",
    "business_model_logic",
    "key_economic_exposures",
    "typical_revenue_drivers",
    "typical_cost_drivers",
    "balance_sheet_focus",
    "cash_flow_focus",
    "survival_risk_focus",
    "quality_signals",
    "red_flags",
    "data_requirements",
    "manual_review_triggers",
]

ATTACHED_TEMPLATE_COLUMNS = [
    "archetype_template_status",
    "archetype_template_confidence",
    "archetype_display_name",
    "archetype_cycle_sensitivity",
    "archetype_data_requirements",
    "archetype_manual_review_triggers",
    "archetype_warning_flags",
    "archetype_template_notes",
]


def load_archetype_templates(path: str) -> dict[str, Any]:
    """Load archetype template YAML config."""

    if yaml is None:
        raise ImportError(
            "PyYAML is required to load archetype templates. Install 'pyyaml' "
            "or provide a parsed config directly."
        )

    template_path = Path(path)
    with template_path.open("r", encoding="utf-8") as template_file:
        data = yaml.safe_load(template_file)

    if not isinstance(data, dict):
        raise ValueError("Archetype template config must contain a YAML mapping.")
    return data


def validate_archetype_templates(
    config: dict[str, Any],
    required_archetypes: list[str] | None = None,
    required_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Validate template config without raising for missing template fields."""

    result = {
        "is_valid": True,
        "missing_archetypes": [],
        "template_errors": {},
        "warnings": [],
        "errors": [],
    }

    if not isinstance(config, dict):
        result["errors"].append("CONFIG_NOT_MAPPING")
        result["is_valid"] = False
        return result

    templates = config.get("templates")
    if not isinstance(templates, dict):
        result["errors"].append("TEMPLATES_NOT_MAPPING")
        result["is_valid"] = False
        return result

    expected_archetypes = required_archetypes or REQUIRED_ARCHETYPES
    expected_fields = required_fields or config.get(
        "required_template_fields", REQUIRED_TEMPLATE_FIELDS
    )
    missing_archetypes = [
        archetype for archetype in expected_archetypes if archetype not in templates
    ]
    result["missing_archetypes"] = missing_archetypes

    for archetype_id, template in templates.items():
        errors = _validate_single_template(archetype_id, template, expected_fields)
        if errors:
            result["template_errors"][archetype_id] = errors

    for archetype_id in missing_archetypes:
        result["errors"].append(f"MISSING_ARCHETYPE:{archetype_id}")

    if result["missing_archetypes"] or result["template_errors"] or result["errors"]:
        result["is_valid"] = False

    return result


def list_archetype_ids(config: dict[str, Any]) -> list[str]:
    """List archetype IDs in config order."""

    return list(_templates_mapping(config).keys())


def get_archetype_template(
    archetype_id: str,
    config: dict[str, Any],
    fallback_to_unknown: bool = True,
) -> dict[str, Any]:
    """Return one archetype template, falling back to unknown when requested."""

    templates = _templates_mapping(config)
    normalized_id = _normalize_id(archetype_id)
    template = templates.get(normalized_id)
    if template is None and fallback_to_unknown:
        template = templates.get("unknown")
    if template is None:
        return {}
    return _deep_copy(template)


def archetype_templates_to_dataframe(config: dict[str, Any]) -> pd.DataFrame:
    """Convert template config into a tabular DataFrame."""

    rows = []
    for archetype_id, template in _templates_mapping(config).items():
        row = _deep_copy(template)
        row.setdefault("archetype_id", archetype_id)
        rows.append(row)
    return pd.DataFrame(rows)


def attach_archetype_template_metadata(
    classification_df: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    """Attach template metadata to L1 classification output.

    Unknown or missing archetypes receive the `unknown` template with low
    confidence and a warning flag.
    """

    if not isinstance(classification_df, pd.DataFrame):
        raise TypeError("classification_df must be a pandas DataFrame.")
    if "archetype" not in classification_df.columns:
        raise ValueError("classification_df must contain an 'archetype' column.")

    templates = _templates_mapping(config)
    output = classification_df.copy(deep=True)
    attached_rows = []
    for _, row in output.iterrows():
        archetype_id = _normalize_id(row.get("archetype"))
        template = templates.get(archetype_id)
        template_found = template is not None and archetype_id != "unknown"
        if template is None:
            template = templates.get("unknown", {})

        warning_flags = [] if template_found else ["UNKNOWN_ARCHETYPE_TEMPLATE"]
        attached_rows.append(
            {
                "archetype_template_status": (
                    "TEMPLATE_FOUND" if template_found else "UNKNOWN_ARCHETYPE_TEMPLATE"
                ),
                "archetype_template_confidence": "medium" if template_found else "low",
                "archetype_display_name": template.get("display_name", "Unknown"),
                "archetype_cycle_sensitivity": template.get(
                    "cycle_sensitivity", "unknown"
                ),
                "archetype_data_requirements": _list_value(
                    template.get("data_requirements")
                ),
                "archetype_manual_review_triggers": _list_value(
                    template.get("manual_review_triggers")
                ),
                "archetype_warning_flags": warning_flags,
                "archetype_template_notes": template.get(
                    "notes", "Template unavailable; manual review required."
                ),
            }
        )

    attached = pd.DataFrame(attached_rows, index=output.index)
    for column in ATTACHED_TEMPLATE_COLUMNS:
        output[column] = attached[column]
    return output


def serialize_archetype_template_columns(
    df: pd.DataFrame,
    list_columns: list[str] | None = None,
    separator: str = ";",
) -> pd.DataFrame:
    """Return a copy with list-valued template columns serialized."""

    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame.")

    target_columns = list_columns or [
        "archetype_data_requirements",
        "archetype_manual_review_triggers",
        "archetype_warning_flags",
    ]
    output = df.copy(deep=True)
    for column in target_columns:
        if column in output.columns:
            output[column] = output[column].map(
                lambda value: separator.join(map(str, value))
                if isinstance(value, list)
                else value
            )
    return output


def _validate_single_template(
    archetype_id: str,
    template: Any,
    required_fields: list[str],
) -> list[str]:
    if not isinstance(template, dict):
        return ["TEMPLATE_NOT_MAPPING"]

    errors: list[str] = []
    for field in required_fields:
        if field not in template or _is_missing(template[field]):
            errors.append(f"MISSING_FIELD:{field}")

    if template.get("archetype_id") != archetype_id:
        errors.append("ARCHETYPE_ID_MISMATCH")

    for field in LIST_TEMPLATE_FIELDS:
        if field in template and not isinstance(template[field], list):
            errors.append(f"FIELD_NOT_LIST:{field}")

    cycle_sensitivity = _normalize_id(template.get("cycle_sensitivity"))
    allowed_sensitivity = {"low", "medium", "high", "mixed", "unknown"}
    if cycle_sensitivity and cycle_sensitivity not in allowed_sensitivity:
        errors.append("INVALID_CYCLE_SENSITIVITY")

    return errors


def _templates_mapping(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(config, dict):
        return {}
    templates = config.get("templates", {})
    if not isinstance(templates, dict):
        return {}
    return templates


def _normalize_id(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip().lower()


def _list_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        return _deep_copy(value)
    if _is_missing(value):
        return []
    return [value]


def _is_missing(value: Any) -> bool:
    if isinstance(value, list):
        return len(value) == 0
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        return False
    return isinstance(value, str) and not value.strip()


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _deep_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_copy(item) for item in value]
    return value
