"""Step 16 driver registry helpers.

This module defines and attaches business/economic drivers. It does not fetch
data, calculate indicator values, run sector-cycle scoring, compare peers,
perform valuation, or make recommendations. Step 17 should define formal
measurable indicators for these drivers.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None


REQUIRED_DRIVER_FIELDS = [
    "driver_id",
    "display_name",
    "category",
    "description",
    "applies_to_archetypes",
    "applies_to_micro_sectors",
    "economic_logic",
    "directionality",
    "cycle_relevance",
    "data_availability_expectation",
    "indicator_hints",
    "missing_data_handling",
    "manual_review_triggers",
    "notes",
]

REQUIRED_DRIVER_CATEGORIES = [
    "macro_financial",
    "fx",
    "export_demand",
    "domestic_demand",
    "commodity_price",
    "input_cost",
    "output_price",
    "spread",
    "regulation_policy",
    "real_estate_project",
    "banking_credit",
    "market_cycle",
    "operational_volume",
    "weather_hydrology",
    "trade_policy",
    "working_capital",
    "balance_sheet_risk",
    "logistics",
    "unknown",
]

REQUIRED_INITIAL_DRIVERS = [
    "USD_VND",
    "interest_rate",
    "credit_growth",
    "inflation",
    "FDI_flow",
    "consumer_demand",
    "construction_demand",
    "export_demand",
    "US_demand",
    "EU_demand",
    "China_demand",
    "order_trend",
    "customer_inventory_cycle",
    "input_cost",
    "output_price",
    "commodity_spread",
    "HRC_price",
    "iron_ore_price",
    "coking_coal_price",
    "rubber_price",
    "oil_price",
    "cotton_price",
    "feed_cost",
    "fertilizer_price",
    "NIM",
    "CASA",
    "NPL",
    "group_2_debt",
    "provisioning",
    "loan_growth",
    "legal_status",
    "presales",
    "inventory_cycle",
    "bond_maturity",
    "land_bank",
    "occupancy",
    "rental_price",
    "market_liquidity",
    "margin_lending",
    "brokerage_market_share",
    "VNIndex_trend",
    "electricity_output",
    "hydrology",
    "fuel_cost",
    "coal_price",
    "gas_price",
    "PPA_regulatory_price",
    "container_volume",
    "freight_rate",
    "export_import_volume",
    "logistics_cost",
    "anti_dumping_tax",
    "trade_defense_risk",
    "tariff_policy",
    "auto_demand",
    "raw_material_availability",
    "labor_cost",
]

DRIVER_REGISTRY_OUTPUT_COLUMNS = [
    "ticker",
    "driver_resolution_status",
    "primary_micro_sector",
    "secondary_micro_sector",
    "archetype",
    "resolved_drivers",
    "primary_drivers",
    "secondary_drivers",
    "unmapped_driver_hints",
    "driver_categories",
    "driver_evidence",
    "warning_flags",
    "manual_review_required",
]

LIST_DRIVER_FIELDS = [
    "applies_to_archetypes",
    "applies_to_micro_sectors",
    "indicator_hints",
    "manual_review_triggers",
]

TEMPLATE_DRIVER_HINT_FIELDS = [
    "key_economic_exposures",
    "typical_revenue_drivers",
    "typical_cost_drivers",
    "survival_risk_focus",
]


def load_driver_registry(config_path: str) -> dict[str, Any]:
    """Load the Step 16 driver registry YAML."""

    if yaml is None:
        raise ImportError(
            "PyYAML is required to load driver registry YAML. Install 'pyyaml' "
            "or provide a parsed registry directly."
        )

    path = Path(config_path)
    with path.open("r", encoding="utf-8") as registry_file:
        registry = yaml.safe_load(registry_file)

    if not isinstance(registry, dict):
        raise ValueError("Driver registry must contain a YAML mapping.")
    return registry


def validate_driver_registry(registry: dict[str, Any]) -> dict[str, Any]:
    """Validate the driver registry without raising for content problems."""

    result = {
        "is_valid": True,
        "missing_categories": [],
        "missing_drivers": [],
        "driver_errors": {},
        "warnings": [],
        "errors": [],
    }

    if not isinstance(registry, dict):
        result["errors"].append("REGISTRY_NOT_MAPPING")
        result["is_valid"] = False
        return result

    categories = registry.get("driver_categories")
    drivers = registry.get("drivers")
    if not isinstance(categories, list):
        result["errors"].append("DRIVER_CATEGORIES_NOT_LIST")
        categories = []
    if not isinstance(drivers, dict):
        result["errors"].append("DRIVERS_NOT_MAPPING")
        drivers = {}

    required_categories = registry.get(
        "required_driver_categories", REQUIRED_DRIVER_CATEGORIES
    )
    required_drivers = registry.get("required_initial_drivers", REQUIRED_INITIAL_DRIVERS)
    required_fields = registry.get("required_driver_fields", REQUIRED_DRIVER_FIELDS)

    result["missing_categories"] = [
        category for category in required_categories if category not in categories
    ]
    result["missing_drivers"] = [
        driver_id for driver_id in required_drivers if driver_id not in drivers
    ]

    for driver_id, driver in drivers.items():
        errors = _validate_single_driver(driver_id, driver, required_fields, categories)
        if errors:
            result["driver_errors"][driver_id] = errors

    for category in result["missing_categories"]:
        result["errors"].append(f"MISSING_DRIVER_CATEGORY:{category}")
    for driver_id in result["missing_drivers"]:
        result["errors"].append(f"MISSING_DRIVER:{driver_id}")

    if (
        result["missing_categories"]
        or result["missing_drivers"]
        or result["driver_errors"]
        or result["errors"]
    ):
        result["is_valid"] = False

    return result


def get_driver(
    driver_id: str,
    registry: dict[str, Any],
    fallback_to_unknown: bool = False,
) -> dict[str, Any]:
    """Return a driver by ID or alias."""

    resolution = normalize_driver_id(driver_id, registry)
    if resolution["status"] != "matched":
        if fallback_to_unknown:
            return _deep_copy(_drivers_mapping(registry).get("unknown", {}))
        return {}
    return _deep_copy(_drivers_mapping(registry).get(resolution["driver_id"], {}))


def find_drivers_for_archetype(archetype: str, registry: dict[str, Any]) -> list[str]:
    """Return driver IDs that apply to an archetype."""

    normalized_archetype = _normalize_token(archetype)
    return [
        driver_id
        for driver_id, driver in _drivers_mapping(registry).items()
        if normalized_archetype
        and normalized_archetype
        in {_normalize_token(value) for value in driver.get("applies_to_archetypes", [])}
    ]


def find_drivers_for_micro_sector(
    micro_sector: str, registry: dict[str, Any]
) -> list[str]:
    """Return driver IDs that apply to a micro-sector."""

    normalized_micro_sector = _normalize_token(micro_sector)
    return [
        driver_id
        for driver_id, driver in _drivers_mapping(registry).items()
        if normalized_micro_sector
        and normalized_micro_sector
        in {
            _normalize_token(value)
            for value in driver.get("applies_to_micro_sectors", [])
        }
    ]


def normalize_driver_id(raw_driver_name: Any, registry: dict[str, Any]) -> dict[str, Any]:
    """Resolve a raw driver hint to a registry ID.

    The function returns a structured result so unknown or ambiguous hints are
    visible instead of being silently ignored.
    """

    raw_name = "" if _is_missing(raw_driver_name) else str(raw_driver_name).strip()
    normalized = _normalize_token(raw_name)
    result = {
        "raw_driver_name": raw_name,
        "status": "unknown",
        "driver_id": "",
        "matches": [],
        "warnings": [],
    }
    if not normalized:
        result["warnings"].append("EMPTY_DRIVER_HINT")
        return result

    exact_matches = _exact_driver_matches(normalized, registry)
    if len(exact_matches) == 1:
        result.update(
            {
                "status": "matched",
                "driver_id": exact_matches[0],
                "matches": exact_matches,
            }
        )
        return result
    if len(exact_matches) > 1:
        result.update({"status": "ambiguous", "matches": exact_matches})
        result["warnings"].append("AMBIGUOUS_DRIVER_MATCH")
        return result

    fuzzy_matches = _fuzzy_driver_matches(normalized, registry)
    if len(fuzzy_matches) == 1:
        result.update(
            {
                "status": "matched",
                "driver_id": fuzzy_matches[0],
                "matches": fuzzy_matches,
            }
        )
        return result
    if len(fuzzy_matches) > 1:
        result.update({"status": "ambiguous", "matches": fuzzy_matches})
        result["warnings"].append("AMBIGUOUS_DRIVER_MATCH")
        return result

    result["warnings"].append("UNKNOWN_DRIVER_HINT")
    return result


def attach_driver_registry(
    classification_or_template_record: dict[str, Any] | pd.Series,
    registry: dict[str, Any],
) -> dict[str, Any]:
    """Attach resolved driver metadata to one classification/template record."""

    if isinstance(classification_or_template_record, pd.Series):
        record = classification_or_template_record.to_dict()
    elif isinstance(classification_or_template_record, dict):
        record = dict(classification_or_template_record)
    else:
        raise TypeError("classification_or_template_record must be a dict or Series.")

    context = _new_context(record)
    if not _eligible_for_driver_resolution(record):
        context["warning_flags"].append("NOT_ELIGIBLE_FOR_DRIVER_RESOLUTION")
        context["manual_review_required"] = True
        return _build_output(record, context, "NOT_ELIGIBLE_FOR_DRIVER_RESOLUTION")

    _preserve_upstream_caution(record, context)
    _resolve_driver_hints(record, registry, context)
    _resolve_archetype_template_hints(record, registry, context)
    _resolve_mapping_drivers(record, registry, context)

    status = _resolve_driver_status(context)
    return _build_output(record, context, status)


def attach_driver_registry_to_records(
    records_or_df: pd.DataFrame | list[dict[str, Any]] | dict[str, Any],
    registry: dict[str, Any],
) -> pd.DataFrame:
    """Attach driver metadata to a DataFrame, list of records, or one record."""

    if isinstance(records_or_df, pd.DataFrame):
        records = [row for _, row in records_or_df.iterrows()]
    elif isinstance(records_or_df, dict):
        records = [records_or_df]
    elif isinstance(records_or_df, list):
        records = records_or_df
    else:
        raise TypeError("records_or_df must be a DataFrame, dict, or list of dicts.")

    rows = [attach_driver_registry(record, registry) for record in records]
    result = pd.DataFrame(rows, columns=DRIVER_REGISTRY_OUTPUT_COLUMNS)
    if not result.empty:
        result["manual_review_required"] = result["manual_review_required"].astype(
            object
        )
    return result


def serialize_driver_registry_output(
    df: pd.DataFrame,
    list_columns: list[str] | None = None,
    separator: str = ";",
) -> pd.DataFrame:
    """Return a copy with list-valued driver registry columns serialized."""

    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame.")

    target_columns = list_columns or [
        "resolved_drivers",
        "primary_drivers",
        "secondary_drivers",
        "unmapped_driver_hints",
        "driver_categories",
        "driver_evidence",
        "warning_flags",
    ]
    output = df.copy(deep=True)
    for column in target_columns:
        if column in output.columns:
            output[column] = output[column].map(
                lambda value: separator.join(_serialize_list_items(value))
                if isinstance(value, list)
                else value
            )
    return output


def _resolve_driver_hints(
    record: dict[str, Any], registry: dict[str, Any], context: dict[str, Any]
) -> None:
    for raw_hint in _value_list(record.get("drivers")):
        _add_raw_driver_hint(
            raw_hint=raw_hint,
            registry=registry,
            context=context,
            matched_from="classification_driver_hint",
            source_reason=f"classification driver hint: {raw_hint}",
            bucket="primary",
        )


def _resolve_archetype_template_hints(
    record: dict[str, Any], registry: dict[str, Any], context: dict[str, Any]
) -> None:
    for field in TEMPLATE_DRIVER_HINT_FIELDS:
        for raw_hint in _value_list(record.get(field)):
            _add_raw_driver_hint(
                raw_hint=raw_hint,
                registry=registry,
                context=context,
                matched_from="archetype_template",
                source_reason=f"{field}: {raw_hint}",
                bucket="primary",
            )


def _resolve_mapping_drivers(
    record: dict[str, Any], registry: dict[str, Any], context: dict[str, Any]
) -> None:
    archetype = _clean_value(record.get("archetype"))
    if archetype and archetype != "unknown":
        for driver_id in find_drivers_for_archetype(archetype, registry):
            _add_registry_driver(
                driver_id=driver_id,
                registry=registry,
                context=context,
                matched_from="archetype_mapping",
                source_reason=f"archetype mapping: {archetype}",
                bucket="primary",
            )

    primary_micro_sector = _clean_value(record.get("primary_micro_sector"))
    if primary_micro_sector and primary_micro_sector != "unknown":
        for driver_id in find_drivers_for_micro_sector(primary_micro_sector, registry):
            _add_registry_driver(
                driver_id=driver_id,
                registry=registry,
                context=context,
                matched_from="micro_sector_mapping",
                source_reason=f"primary micro-sector mapping: {primary_micro_sector}",
                bucket="primary",
            )

    secondary_micro_sector = _clean_value(record.get("secondary_micro_sector"))
    if secondary_micro_sector and secondary_micro_sector != "unknown":
        for driver_id in find_drivers_for_micro_sector(
            secondary_micro_sector, registry
        ):
            _add_registry_driver(
                driver_id=driver_id,
                registry=registry,
                context=context,
                matched_from="micro_sector_mapping",
                source_reason=f"secondary micro-sector mapping: {secondary_micro_sector}",
                bucket="secondary",
            )


def _add_raw_driver_hint(
    *,
    raw_hint: Any,
    registry: dict[str, Any],
    context: dict[str, Any],
    matched_from: str,
    source_reason: str,
    bucket: str,
) -> None:
    resolution = normalize_driver_id(raw_hint, registry)
    if resolution["status"] == "matched":
        _add_registry_driver(
            driver_id=resolution["driver_id"],
            registry=registry,
            context=context,
            matched_from=matched_from,
            source_reason=source_reason,
            bucket=bucket,
        )
        return

    raw_name = resolution["raw_driver_name"]
    if resolution["status"] == "ambiguous":
        context["warning_flags"].append("AMBIGUOUS_DRIVER_MATCH")
        context["ambiguous_driver_hints"].append(raw_name)
        context["driver_evidence"].append(
            f"ambiguous driver hint '{raw_name}' matched {resolution['matches']}"
        )
        context["manual_review_required"] = True
        return

    context["warning_flags"].append("UNKNOWN_DRIVER_HINT")
    context["unmapped_driver_hints"].append(raw_name)
    context["driver_evidence"].append(f"unmapped driver hint: {raw_name}")
    context["manual_review_required"] = True


def _add_registry_driver(
    *,
    driver_id: str,
    registry: dict[str, Any],
    context: dict[str, Any],
    matched_from: str,
    source_reason: str,
    bucket: str,
) -> None:
    driver = _drivers_mapping(registry).get(driver_id)
    if not driver:
        context["warning_flags"].append("UNKNOWN_DRIVER_HINT")
        context["unmapped_driver_hints"].append(driver_id)
        context["manual_review_required"] = True
        return

    entry = context["resolved_by_id"].setdefault(
        driver_id,
        {
            "driver_id": driver_id,
            "display_name": driver.get("display_name", driver_id),
            "category": driver.get("category", "unknown"),
            "source_reason": [],
            "matched_from": matched_from,
            "directionality": driver.get("directionality", "context_dependent"),
            "cycle_relevance": driver.get("cycle_relevance", "unknown"),
            "data_availability_expectation": driver.get(
                "data_availability_expectation", "unknown"
            ),
        },
    )
    entry["source_reason"].append(source_reason)
    context["source_types"].append(matched_from)
    context["driver_evidence"].append(f"{driver_id}: {source_reason}")
    if bucket == "secondary":
        context["secondary_drivers"].append(driver_id)
    else:
        context["primary_drivers"].append(driver_id)


def _preserve_upstream_caution(
    record: dict[str, Any], context: dict[str, Any]
) -> None:
    if _clean_value(record.get("classification_confidence")).lower() == "low":
        context["warning_flags"].append("LOW_CLASSIFICATION_CONFIDENCE")
        context["manual_review_required"] = True

    template_status = _clean_value(
        record.get("archetype_template_status", record.get("template_status"))
    )
    if template_status and template_status != "TEMPLATE_FOUND":
        context["warning_flags"].append("UNKNOWN_ARCHETYPE_TEMPLATE")
        context["manual_review_required"] = True


def _resolve_driver_status(context: dict[str, Any]) -> str:
    resolved_count = len(context["resolved_by_id"])
    warning_flags = set(context["warning_flags"])
    source_types = set(context["source_types"])

    if resolved_count == 0:
        context["warning_flags"].append("NO_DRIVERS_RESOLVED")
        context["manual_review_required"] = True
        return "NO_DRIVERS_RESOLVED"

    weak_sources = {"classification_driver_hint"}
    if source_types and source_types.issubset(weak_sources):
        context["warning_flags"].append("WEAK_DRIVER_EVIDENCE")
        context["manual_review_required"] = True
        return "PARTIAL_DRIVERS_RESOLVED"

    if "AMBIGUOUS_DRIVER_MATCH" in warning_flags:
        context["manual_review_required"] = True
        return "DRIVER_MANUAL_REVIEW"

    if warning_flags.intersection(
        {"LOW_CLASSIFICATION_CONFIDENCE", "UNKNOWN_ARCHETYPE_TEMPLATE"}
    ):
        context["manual_review_required"] = True
        return "DRIVER_MANUAL_REVIEW"

    if "UNKNOWN_DRIVER_HINT" in warning_flags:
        return "PARTIAL_DRIVERS_RESOLVED"

    return "DRIVERS_RESOLVED"


def _build_output(
    record: dict[str, Any], context: dict[str, Any], status: str
) -> dict[str, Any]:
    resolved_drivers = []
    for driver in context["resolved_by_id"].values():
        row = dict(driver)
        row["source_reason"] = _dedupe(row["source_reason"])
        resolved_drivers.append(row)

    driver_categories = _dedupe([driver["category"] for driver in resolved_drivers])
    return {
        "ticker": _clean_value(record.get("ticker")),
        "driver_resolution_status": status,
        "primary_micro_sector": _clean_value(record.get("primary_micro_sector")),
        "secondary_micro_sector": _clean_value(record.get("secondary_micro_sector")),
        "archetype": _clean_value(record.get("archetype")),
        "resolved_drivers": resolved_drivers,
        "primary_drivers": _dedupe(context["primary_drivers"]),
        "secondary_drivers": _dedupe(context["secondary_drivers"]),
        "unmapped_driver_hints": _dedupe(context["unmapped_driver_hints"]),
        "driver_categories": driver_categories,
        "driver_evidence": _dedupe(context["driver_evidence"]),
        "warning_flags": _dedupe(context["warning_flags"]),
        "manual_review_required": bool(context["manual_review_required"]),
    }


def _eligible_for_driver_resolution(record: dict[str, Any]) -> bool:
    status = _clean_value(record.get("classification_status"))
    if status in {"NOT_CLASSIFIED", ""}:
        return False
    primary_micro_sector = _clean_value(record.get("primary_micro_sector"))
    archetype = _clean_value(record.get("archetype"))
    return primary_micro_sector != "unknown" or archetype != "unknown"


def _new_context(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "resolved_by_id": {},
        "primary_drivers": [],
        "secondary_drivers": [],
        "unmapped_driver_hints": [],
        "ambiguous_driver_hints": [],
        "driver_evidence": [],
        "warning_flags": _value_list(record.get("warning_flags")),
        "source_types": [],
        "manual_review_required": _bool_value(record.get("manual_review_required")),
    }


def _validate_single_driver(
    driver_id: str,
    driver: Any,
    required_fields: list[str],
    categories: list[str],
) -> list[str]:
    if not isinstance(driver, dict):
        return ["DRIVER_NOT_MAPPING"]

    errors: list[str] = []
    for field in required_fields:
        if field not in driver:
            errors.append(f"MISSING_FIELD:{field}")
        elif field not in LIST_DRIVER_FIELDS and _is_missing(driver[field]):
            errors.append(f"MISSING_FIELD:{field}")

    if driver.get("driver_id") != driver_id:
        errors.append("DRIVER_ID_MISMATCH")

    if driver.get("category") not in categories:
        errors.append("UNKNOWN_CATEGORY")

    for field in LIST_DRIVER_FIELDS:
        if field in driver and not isinstance(driver[field], list):
            errors.append(f"FIELD_NOT_LIST:{field}")

    if "aliases" in driver and not isinstance(driver["aliases"], list):
        errors.append("FIELD_NOT_LIST:aliases")

    return errors


def _exact_driver_matches(normalized: str, registry: dict[str, Any]) -> list[str]:
    matches = []
    for driver_id, driver in _drivers_mapping(registry).items():
        aliases = _driver_match_tokens(driver_id, driver)
        if normalized in aliases:
            matches.append(driver_id)
    return _dedupe(matches)


def _fuzzy_driver_matches(normalized: str, registry: dict[str, Any]) -> list[str]:
    if len(normalized) < 3:
        return []
    matches = []
    for driver_id, driver in _drivers_mapping(registry).items():
        if driver_id == "unknown":
            continue
        aliases = _driver_match_tokens(driver_id, driver)
        if any(normalized in alias or alias in normalized for alias in aliases):
            matches.append(driver_id)
    return _dedupe(matches)


def _driver_match_tokens(driver_id: str, driver: dict[str, Any]) -> set[str]:
    values = [driver_id, driver.get("driver_id"), driver.get("display_name")]
    values.extend(_value_list(driver.get("aliases")))
    return {_normalize_token(value) for value in values if not _is_missing(value)}


def _drivers_mapping(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(registry, dict):
        return {}
    drivers = registry.get("drivers", {})
    if not isinstance(drivers, dict):
        return {}
    return drivers


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


def _serialize_list_items(value: list[Any]) -> list[str]:
    serialized = []
    for item in value:
        if isinstance(item, dict):
            serialized.append(str(item.get("driver_id", item)))
        else:
            serialized.append(str(item))
    return serialized


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


def _bool_value(value: Any) -> bool:
    if _is_missing(value):
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _is_missing(value: Any) -> bool:
    if isinstance(value, list) or isinstance(value, tuple) or isinstance(value, set):
        return len(value) == 0
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        return False
    return isinstance(value, str) and not value.strip()


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(values))


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _deep_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_copy(item) for item in value]
    return value
