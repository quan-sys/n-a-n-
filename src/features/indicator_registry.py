"""Step 17 indicator registry helpers.

This module defines and resolves indicator metadata only. It does not fetch
live data, calculate indicator values, run sector-cycle scoring, compare peers,
perform valuation, or produce recommendations.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None


DEFAULT_REGISTRY_PATH = "config/indicator_registry.yaml"

INDICATOR_GROUPS = [
    "core_indicators",
    "archetype_indicators",
    "sector_specific_indicators",
]

REQUIRED_INDICATOR_FIELDS = [
    "indicator_id",
    "display_name",
    "category",
    "description",
    "data_type",
    "unit",
    "frequency",
    "source_dataset",
    "required_fields",
    "applies_to_drivers",
    "applies_to_archetypes",
    "applies_to_micro_sectors",
    "calculation_hint",
    "interpretation_hint",
    "missing_data_handling",
    "stale_data_policy",
    "confidence_rules",
    "manual_review_triggers",
    "notes",
]

LIST_INDICATOR_FIELDS = [
    "required_fields",
    "applies_to_drivers",
    "applies_to_archetypes",
    "applies_to_micro_sectors",
    "confidence_rules",
    "manual_review_triggers",
]

OPTIONAL_BOOLEAN_FIELDS = ["higher_is_better", "requires_manual_input"]
OPTIONAL_LIST_FIELDS: list[str] = []

LOW_DATA_AVAILABILITY_VALUES = {"low", "unknown"}


def load_indicator_registry(
    path: str | Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    """Load the Step 17 indicator registry YAML."""

    if yaml is None:
        raise ImportError(
            "PyYAML is required to load indicator registry YAML. Install "
            "'pyyaml' or provide a parsed registry directly."
        )

    registry_path = Path(path)
    with registry_path.open("r", encoding="utf-8") as registry_file:
        registry = yaml.safe_load(registry_file)

    if not isinstance(registry, dict):
        raise ValueError("Indicator registry must contain a YAML mapping.")
    return registry


def validate_indicator_registry(registry: dict[str, Any]) -> list[str]:
    """Validate registry structure and required indicator fields."""

    errors: list[str] = []
    if not isinstance(registry, dict):
        return ["REGISTRY_NOT_MAPPING"]

    actual_groups = set(registry)
    expected_groups = set(INDICATOR_GROUPS)
    missing_groups = sorted(expected_groups - actual_groups)
    extra_groups = sorted(actual_groups - expected_groups)
    for group in missing_groups:
        errors.append(f"MISSING_TOP_LEVEL_GROUP:{group}")
    for group in extra_groups:
        errors.append(f"UNEXPECTED_TOP_LEVEL_GROUP:{group}")

    for group in INDICATOR_GROUPS:
        if group not in registry:
            continue
        if not isinstance(registry[group], dict):
            errors.append(f"GROUP_NOT_MAPPING:{group}")
            continue
        for source_key, indicator in _iter_group_records(group, registry[group]):
            errors.extend(_validate_single_indicator(source_key, indicator))

    return _dedupe(errors)


def flatten_indicator_registry(registry: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten all indicator groups into deduplicated indicator records.

    Duplicate ``indicator_id`` entries are merged. The first definition keeps
    scalar metadata, while list-valued mapping fields are combined so core
    indicators can also apply to archetypes or micro-sectors.
    """

    merged_by_id: dict[str, dict[str, Any]] = {}
    for group in INDICATOR_GROUPS:
        group_value = registry.get(group, {})
        if not isinstance(group_value, dict):
            continue
        for source_key, indicator in _iter_group_records(group, group_value):
            if not isinstance(indicator, dict):
                continue
            indicator_id = str(indicator.get("indicator_id", source_key)).strip()
            if not indicator_id:
                continue
            record = _deep_copy(indicator)
            record["indicator_id"] = indicator_id
            record.setdefault("registry_group", group)

            existing = merged_by_id.get(_normalize_token(indicator_id))
            if existing is None:
                merged_by_id[_normalize_token(indicator_id)] = record
                continue
            _merge_indicator_record(existing, record)

    return list(merged_by_id.values())


def get_indicator_by_id(
    indicator_id: str,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return one indicator by ID, case-insensitively."""

    normalized_id = _normalize_token(indicator_id)
    if not normalized_id:
        return None
    for indicator in flatten_indicator_registry(_active_registry(registry)):
        if _normalize_token(indicator.get("indicator_id")) == normalized_id:
            return _deep_copy(indicator)
    return None


def get_indicators_for_driver(
    driver_id: str,
    registry: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return indicators that map to a driver ID."""

    normalized_driver = _normalize_token(driver_id)
    if not normalized_driver:
        return []
    return [
        _deep_copy(indicator)
        for indicator in flatten_indicator_registry(_active_registry(registry))
        if normalized_driver
        in {_normalize_token(value) for value in _value_list(indicator.get("applies_to_drivers"))}
    ]


def get_indicators_for_archetype(
    archetype: str,
    registry: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return indicators that apply to an archetype."""

    normalized_archetype = _normalize_token(archetype)
    if not normalized_archetype:
        return []
    return [
        _deep_copy(indicator)
        for indicator in flatten_indicator_registry(_active_registry(registry))
        if normalized_archetype
        in {
            _normalize_token(value)
            for value in _value_list(indicator.get("applies_to_archetypes"))
        }
    ]


def get_indicators_for_micro_sector(
    micro_sector: str,
    registry: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return indicators that apply to a micro-sector."""

    normalized_micro_sector = _normalize_token(micro_sector)
    if not normalized_micro_sector:
        return []
    return [
        _deep_copy(indicator)
        for indicator in flatten_indicator_registry(_active_registry(registry))
        if normalized_micro_sector
        in {
            _normalize_token(value)
            for value in _value_list(indicator.get("applies_to_micro_sectors"))
        }
    ]


def resolve_indicators(
    drivers: list[str] | None = None,
    archetype: str | None = None,
    primary_micro_sector: str | None = None,
    secondary_micro_sector: str | None = None,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve core, archetype, sector, and driver indicators.

    The resolver only returns metadata definitions. Missing mappings and weak
    metadata availability are visible through warning flags, low confidence, and
    manual-review output.
    """

    active_registry = _active_registry(registry)
    validation_errors = validate_indicator_registry(active_registry)
    if validation_errors:
        return {
            "indicator_resolution_status": "INVALID_REGISTRY",
            "resolved_indicators": [],
            "core_indicators": [],
            "archetype_indicators": [],
            "sector_specific_indicators": [],
            "unmapped_driver_hints": _dedupe(_value_list(drivers)),
            "missing_data_warnings": [],
            "manual_review_required": True,
            "warning_flags": validation_errors,
            "confidence": "low",
        }

    context = _new_resolution_context()
    core_indicators = _core_indicator_records(active_registry)
    for indicator in core_indicators:
        _add_indicator(indicator, context, "core")

    for raw_driver in _value_list(drivers):
        driver_indicators = get_indicators_for_driver(raw_driver, active_registry)
        if not driver_indicators:
            context["unmapped_driver_hints"].append(str(raw_driver).strip())
            context["warning_flags"].append("UNKNOWN_DRIVER_FOR_INDICATOR_MAPPING")
            context["manual_review_required"] = True
            continue
        for indicator in driver_indicators:
            _add_indicator(indicator, context, _bucket_for_group(indicator))

    _resolve_archetype(archetype, active_registry, context)
    _resolve_micro_sector(
        primary_micro_sector, active_registry, context, warn_if_unknown=True
    )
    _resolve_micro_sector(
        secondary_micro_sector, active_registry, context, warn_if_unknown=False
    )
    _apply_metadata_availability_warnings(context)

    resolved_indicators = list(context["resolved_by_id"].values())
    status = _resolve_status(resolved_indicators, context)
    confidence = _resolve_confidence(resolved_indicators, context)

    return {
        "indicator_resolution_status": status,
        "resolved_indicators": _deep_copy(resolved_indicators),
        "core_indicators": _deep_copy(context["core_indicators"]),
        "archetype_indicators": _deep_copy(context["archetype_indicators"]),
        "sector_specific_indicators": _deep_copy(context["sector_specific_indicators"]),
        "unmapped_driver_hints": _dedupe(context["unmapped_driver_hints"]),
        "missing_data_warnings": _dedupe(context["missing_data_warnings"]),
        "manual_review_required": bool(context["manual_review_required"]),
        "warning_flags": _dedupe(context["warning_flags"]),
        "confidence": confidence,
    }


def _active_registry(registry: dict[str, Any] | None) -> dict[str, Any]:
    return registry if registry is not None else load_indicator_registry()


def _iter_group_records(
    group_name: str, group_value: dict[str, Any]
) -> list[tuple[str, Any]]:
    if group_name == "core_indicators":
        return list(group_value.items())

    rows: list[tuple[str, Any]] = []
    for scope_key, scoped_indicators in group_value.items():
        if isinstance(scoped_indicators, dict):
            for indicator_key, indicator in scoped_indicators.items():
                rows.append((f"{scope_key}.{indicator_key}", indicator))
        elif isinstance(scoped_indicators, list):
            for index, indicator in enumerate(scoped_indicators):
                rows.append((f"{scope_key}.{index}", indicator))
        else:
            rows.append((str(scope_key), scoped_indicators))
    return rows


def _validate_single_indicator(source_key: str, indicator: Any) -> list[str]:
    if not isinstance(indicator, dict):
        return [f"{source_key}:INDICATOR_NOT_MAPPING"]

    errors: list[str] = []
    indicator_id = str(indicator.get("indicator_id", source_key)).strip()
    for field in REQUIRED_INDICATOR_FIELDS:
        if field not in indicator:
            errors.append(f"{indicator_id}:MISSING_FIELD:{field}")
            continue
        if field not in LIST_INDICATOR_FIELDS and _is_missing(indicator[field]):
            errors.append(f"{indicator_id}:MISSING_FIELD:{field}")

    for field in LIST_INDICATOR_FIELDS:
        if field in indicator and not isinstance(indicator[field], list):
            errors.append(f"{indicator_id}:FIELD_NOT_LIST:{field}")

    for field in OPTIONAL_LIST_FIELDS:
        if field in indicator and not isinstance(indicator[field], list):
            errors.append(f"{indicator_id}:FIELD_NOT_LIST:{field}")

    for field in OPTIONAL_BOOLEAN_FIELDS:
        if field in indicator and indicator[field] is not None and not isinstance(
            indicator[field], bool
        ):
            errors.append(f"{indicator_id}:FIELD_NOT_BOOL:{field}")

    return errors


def _merge_indicator_record(
    existing: dict[str, Any], incoming: dict[str, Any]
) -> None:
    for field in [*LIST_INDICATOR_FIELDS, *OPTIONAL_LIST_FIELDS]:
        existing[field] = _dedupe(
            _value_list(existing.get(field)) + _value_list(incoming.get(field))
        )
    groups = _value_list(existing.get("registry_group")) + _value_list(
        incoming.get("registry_group")
    )
    existing["registry_group"] = _dedupe(groups)

    existing_availability = str(existing.get("data_availability", "")).lower()
    incoming_availability = str(incoming.get("data_availability", "")).lower()
    if existing_availability not in LOW_DATA_AVAILABILITY_VALUES:
        if incoming_availability in LOW_DATA_AVAILABILITY_VALUES:
            existing["data_availability"] = incoming.get("data_availability")

    if incoming.get("requires_manual_input"):
        existing["requires_manual_input"] = True


def _core_indicator_records(registry: dict[str, Any]) -> list[dict[str, Any]]:
    core_indicators = registry.get("core_indicators", {})
    if not isinstance(core_indicators, dict):
        return []
    records = []
    for _, indicator in core_indicators.items():
        if isinstance(indicator, dict):
            record = _deep_copy(indicator)
            record.setdefault("registry_group", "core_indicators")
            records.append(record)
    return records


def _resolve_archetype(
    archetype: str | None, registry: dict[str, Any], context: dict[str, Any]
) -> None:
    clean_archetype = _clean_value(archetype)
    if not clean_archetype:
        return
    if _normalize_token(clean_archetype) == "unknown":
        context["warning_flags"].append("UNKNOWN_ARCHETYPE_FOR_INDICATOR_MAPPING")
        context["manual_review_required"] = True
        return

    indicators = get_indicators_for_archetype(clean_archetype, registry)
    if not indicators:
        context["warning_flags"].append("UNKNOWN_ARCHETYPE_FOR_INDICATOR_MAPPING")
        context["manual_review_required"] = True
        return

    for indicator in indicators:
        _add_indicator(indicator, context, _bucket_for_group(indicator))


def _resolve_micro_sector(
    micro_sector: str | None,
    registry: dict[str, Any],
    context: dict[str, Any],
    *,
    warn_if_unknown: bool,
) -> None:
    clean_micro_sector = _clean_value(micro_sector)
    if not clean_micro_sector:
        return
    if _normalize_token(clean_micro_sector) == "unknown":
        if warn_if_unknown:
            context["warning_flags"].append(
                "UNKNOWN_MICRO_SECTOR_FOR_INDICATOR_MAPPING"
            )
            context["manual_review_required"] = True
        return

    indicators = get_indicators_for_micro_sector(clean_micro_sector, registry)
    if not indicators:
        if warn_if_unknown:
            context["warning_flags"].append(
                "UNKNOWN_MICRO_SECTOR_FOR_INDICATOR_MAPPING"
            )
            context["manual_review_required"] = True
        return

    for indicator in indicators:
        _add_indicator(indicator, context, _bucket_for_group(indicator))


def _apply_metadata_availability_warnings(context: dict[str, Any]) -> None:
    for indicator in context["resolved_by_id"].values():
        indicator_id = indicator.get("indicator_id", "")
        data_availability = str(indicator.get("data_availability", "")).lower()
        if data_availability in LOW_DATA_AVAILABILITY_VALUES:
            context["missing_data_warnings"].append(
                f"LOW_DATA_AVAILABILITY:{indicator_id}"
            )
            context["warning_flags"].append("LOW_INDICATOR_DATA_AVAILABILITY")
            context["manual_review_required"] = True
        if indicator.get("requires_manual_input") is True:
            context["missing_data_warnings"].append(
                f"MANUAL_INPUT_REQUIRED:{indicator_id}"
            )
            context["warning_flags"].append("INDICATOR_REQUIRES_MANUAL_INPUT")
            context["manual_review_required"] = True


def _add_indicator(
    indicator: dict[str, Any], context: dict[str, Any], bucket: str
) -> None:
    indicator_id = str(indicator.get("indicator_id", "")).strip()
    if not indicator_id:
        return

    existing = context["resolved_by_id"].get(_normalize_token(indicator_id))
    if existing is None:
        context["resolved_by_id"][_normalize_token(indicator_id)] = _deep_copy(
            indicator
        )
        target = _bucket_column(bucket)
        context[target].append(_deep_copy(indicator))
        return

    _merge_indicator_record(existing, indicator)


def _bucket_for_group(indicator: dict[str, Any]) -> str:
    groups = _value_list(indicator.get("registry_group"))
    if "sector_specific_indicators" in groups:
        return "sector_specific"
    if "archetype_indicators" in groups:
        return "archetype"
    return "core"


def _bucket_column(bucket: str) -> str:
    if bucket == "sector_specific":
        return "sector_specific_indicators"
    if bucket == "archetype":
        return "archetype_indicators"
    return "core_indicators"


def _resolve_status(
    resolved_indicators: list[dict[str, Any]], context: dict[str, Any]
) -> str:
    if not resolved_indicators:
        context["warning_flags"].append("NO_INDICATORS_RESOLVED")
        context["manual_review_required"] = True
        return "NO_INDICATORS_RESOLVED"
    if context["manual_review_required"]:
        unknown_warnings = {
            "UNKNOWN_DRIVER_FOR_INDICATOR_MAPPING",
            "UNKNOWN_ARCHETYPE_FOR_INDICATOR_MAPPING",
            "UNKNOWN_MICRO_SECTOR_FOR_INDICATOR_MAPPING",
        }
        if set(context["warning_flags"]).intersection(unknown_warnings):
            return "PARTIAL_INDICATORS_RESOLVED"
        return "INDICATOR_MANUAL_REVIEW"
    return "INDICATORS_RESOLVED"


def _resolve_confidence(
    resolved_indicators: list[dict[str, Any]], context: dict[str, Any]
) -> str:
    if not resolved_indicators:
        return "low"
    warning_flags = set(context["warning_flags"])
    if warning_flags.intersection(
        {
            "UNKNOWN_DRIVER_FOR_INDICATOR_MAPPING",
            "UNKNOWN_ARCHETYPE_FOR_INDICATOR_MAPPING",
            "UNKNOWN_MICRO_SECTOR_FOR_INDICATOR_MAPPING",
            "LOW_INDICATOR_DATA_AVAILABILITY",
            "INDICATOR_REQUIRES_MANUAL_INPUT",
        }
    ):
        return "low"
    if context["archetype_indicators"] and context["sector_specific_indicators"]:
        return "high"
    return "medium"


def _new_resolution_context() -> dict[str, Any]:
    return {
        "resolved_by_id": {},
        "core_indicators": [],
        "archetype_indicators": [],
        "sector_specific_indicators": [],
        "unmapped_driver_hints": [],
        "missing_data_warnings": [],
        "manual_review_required": False,
        "warning_flags": [],
    }


def _normalize_token(value: Any) -> str:
    if _is_missing(value):
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def _clean_value(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip()


def _value_list(value: Any) -> list[Any]:
    if _is_missing(value):
        return []
    if isinstance(value, list):
        return [item for item in value if not _is_missing(item)]
    if isinstance(value, tuple) or isinstance(value, set):
        return [item for item in value if not _is_missing(item)]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if ";" in stripped:
            return [part.strip() for part in stripped.split(";") if part.strip()]
        return [stripped]
    return [value]


def _is_missing(value: Any) -> bool:
    if isinstance(value, list) or isinstance(value, tuple) or isinstance(value, set):
        return len(value) == 0
    if value is None:
        return True
    return isinstance(value, str) and not value.strip()


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(values))


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _deep_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_copy(item) for item in value]
    return value
