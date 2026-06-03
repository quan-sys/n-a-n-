import src.features.indicator_registry as indicator_registry
from src.features.indicator_registry import (
    REQUIRED_INDICATOR_FIELDS,
    flatten_indicator_registry,
    get_indicator_by_id,
    get_indicators_for_archetype,
    get_indicators_for_driver,
    get_indicators_for_micro_sector,
    load_indicator_registry,
    resolve_indicators,
    validate_indicator_registry,
)


REGISTRY_PATH = "config/indicator_registry.yaml"

REQUIRED_CORE_INDICATORS = {
    "price",
    "volume",
    "trading_value",
    "market_cap",
    "revenue",
    "net_profit",
    "gross_margin",
    "operating_margin",
    "operating_cash_flow",
    "debt",
    "inventory",
    "equity",
    "ROE",
    "ROA",
}

REQUIRED_ARCHETYPES = {
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
}

REQUIRED_MICRO_SECTORS = {
    "steel_integrated",
    "galvanized_steel",
    "natural_rubber",
    "tire_manufacturing",
    "pangasius_export",
    "shrimp_export",
    "textile_export",
    "residential_real_estate",
    "industrial_park",
    "commercial_bank",
    "securities_broker",
    "power_generation",
    "port_logistics",
    "oil_gas_upstream",
    "oil_gas_services",
    "fertilizer",
    "consumer_staples",
    "retail_distribution",
    "construction_materials",
    "holding_company",
    "unknown",
}


def _registry():
    return load_indicator_registry(REGISTRY_PATH)


def _ids(indicators):
    return {indicator["indicator_id"] for indicator in indicators}


def test_yaml_loads_successfully_and_validates():
    registry = _registry()

    assert isinstance(registry, dict)
    assert validate_indicator_registry(registry) == []


def test_registry_has_exact_required_top_level_groups():
    registry = _registry()

    assert set(registry) == {
        "core_indicators",
        "archetype_indicators",
        "sector_specific_indicators",
    }


def test_every_indicator_has_all_required_fields():
    registry = _registry()

    for indicator in flatten_indicator_registry(registry):
        assert set(REQUIRED_INDICATOR_FIELDS).issubset(set(indicator))


def test_core_indicators_include_required_core_set():
    registry = _registry()

    assert REQUIRED_CORE_INDICATORS.issubset(set(registry["core_indicators"]))


def test_required_archetype_and_micro_sector_coverage_exists():
    registry = _registry()

    assert REQUIRED_ARCHETYPES.issubset(set(registry["archetype_indicators"]))
    assert REQUIRED_MICRO_SECTORS.issubset(
        set(registry["sector_specific_indicators"])
    )


def test_lookup_by_indicator_id_works_case_insensitively():
    indicator = get_indicator_by_id("roe", _registry())

    assert indicator is not None
    assert indicator["indicator_id"] == "ROE"
    assert indicator["confidence_rules"]


def test_driver_lookup_returns_usd_vnd_indicator():
    indicators = get_indicators_for_driver("USD_VND", _registry())

    assert "usd_vnd_rate" in _ids(indicators)
    assert all("USD_VND" in indicator["applies_to_drivers"] for indicator in indicators)


def test_archetype_lookup_returns_export_manufacturer_indicators():
    indicators = get_indicators_for_archetype("export_manufacturer", _registry())
    indicator_ids = _ids(indicators)

    assert "usd_vnd_rate" in indicator_ids
    assert "export_demand_index" in indicator_ids
    assert "input_cost_index" in indicator_ids
    assert "logistics_cost_index" in indicator_ids
    assert "gross_margin" in indicator_ids
    assert "inventory" in indicator_ids


def test_micro_sector_lookup_returns_steel_specific_indicators():
    indicators = get_indicators_for_micro_sector("steel_integrated", _registry())
    indicator_ids = _ids(indicators)

    assert "HRC_price" in indicator_ids
    assert "iron_ore_price" in indicator_ids
    assert "coking_coal_price" in indicator_ids
    assert "steel_spread" in indicator_ids
    assert "construction_demand" in indicator_ids


def test_unknown_driver_creates_warning_and_manual_review():
    result = resolve_indicators(drivers=["mock_unknown_driver"], registry=_registry())

    assert result["indicator_resolution_status"] == "PARTIAL_INDICATORS_RESOLVED"
    assert "UNKNOWN_DRIVER_FOR_INDICATOR_MAPPING" in result["warning_flags"]
    assert "mock_unknown_driver" in result["unmapped_driver_hints"]
    assert bool(result["manual_review_required"]) is True
    assert result["confidence"] == "low"


def test_unknown_archetype_creates_warning_and_manual_review():
    result = resolve_indicators(
        archetype="mock_unknown_archetype", registry=_registry()
    )

    assert "UNKNOWN_ARCHETYPE_FOR_INDICATOR_MAPPING" in result["warning_flags"]
    assert bool(result["manual_review_required"]) is True
    assert result["confidence"] == "low"


def test_unknown_micro_sector_creates_warning_and_manual_review():
    result = resolve_indicators(
        primary_micro_sector="mock_unknown_micro_sector", registry=_registry()
    )

    assert "UNKNOWN_MICRO_SECTOR_FOR_INDICATOR_MAPPING" in result["warning_flags"]
    assert bool(result["manual_review_required"]) is True
    assert result["confidence"] == "low"


def test_resolver_deduplicates_repeated_indicator_mappings():
    result = resolve_indicators(
        drivers=["USD_VND", "USD_VND", "export_demand"],
        archetype="export_manufacturer",
        primary_micro_sector="textile_export",
        secondary_micro_sector="unknown",
        registry=_registry(),
    )
    resolved_ids = [indicator["indicator_id"] for indicator in result["resolved_indicators"]]

    assert len(resolved_ids) == len(set(resolved_ids))
    assert resolved_ids.count("usd_vnd_rate") == 1


def test_resolver_output_has_required_shape_and_metadata_only():
    result = resolve_indicators(
        drivers=["USD_VND"],
        archetype="export_manufacturer",
        primary_micro_sector="textile_export",
        registry=_registry(),
    )

    assert set(result) == {
        "indicator_resolution_status",
        "resolved_indicators",
        "core_indicators",
        "archetype_indicators",
        "sector_specific_indicators",
        "unmapped_driver_hints",
        "missing_data_warnings",
        "manual_review_required",
        "warning_flags",
        "confidence",
    }
    assert "indicator_value" not in result
    assert "sector_cycle_score" not in result
    assert "company_score" not in result


def test_resolver_never_returns_recommendation_or_price_object_fields():
    result = resolve_indicators(
        drivers=["USD_VND"],
        archetype="export_manufacturer",
        primary_micro_sector="textile_export",
        registry=_registry(),
    )
    output_keys = _recursive_keys(result)

    assert "buy" not in output_keys
    assert "sell" not in output_keys
    assert "target_price" not in output_keys


def test_invalid_registry_returns_invalid_registry_status():
    result = resolve_indicators(registry={"core_indicators": {}})

    assert result["indicator_resolution_status"] == "INVALID_REGISTRY"
    assert bool(result["manual_review_required"]) is True
    assert result["confidence"] == "low"


def test_no_real_vietnamese_company_financial_data_is_required():
    result = resolve_indicators(
        drivers=["USD_VND"],
        archetype="export_manufacturer",
        primary_micro_sector="textile_export",
        registry=_registry(),
    )

    assert result["resolved_indicators"]
    assert "ticker" not in result

    public_names = {
        name
        for name in dir(indicator_registry)
        if not name.startswith("_") and callable(getattr(indicator_registry, name))
    }
    assert not any(name.startswith("fetch") for name in public_names)
    assert not any(name.startswith("calculate") for name in public_names)
    assert not any(name.startswith("score") for name in public_names)


def _recursive_keys(value):
    keys = set()
    if isinstance(value, dict):
        for key, nested_value in value.items():
            keys.add(str(key).lower())
            keys.update(_recursive_keys(nested_value))
    elif isinstance(value, list):
        for item in value:
            keys.update(_recursive_keys(item))
    return keys
