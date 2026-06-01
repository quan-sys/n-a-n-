import pandas as pd

import src.features.driver_registry as driver_registry
from src.features.driver_registry import (
    DRIVER_REGISTRY_OUTPUT_COLUMNS,
    REQUIRED_DRIVER_CATEGORIES,
    REQUIRED_DRIVER_FIELDS,
    REQUIRED_INITIAL_DRIVERS,
    attach_driver_registry,
    attach_driver_registry_to_records,
    find_drivers_for_archetype,
    find_drivers_for_micro_sector,
    get_driver,
    load_driver_registry,
    normalize_driver_id,
    serialize_driver_registry_output,
    validate_driver_registry,
)


REGISTRY_PATH = "config/driver_registry.yaml"


def _registry():
    return load_driver_registry(REGISTRY_PATH)


def _classification_record(**overrides):
    record = {
        "ticker": "MOCK1",
        "classification_status": "CLASSIFIED",
        "primary_micro_sector": "textile_export",
        "secondary_micro_sector": "unknown",
        "primary_exposure_weight": 1.0,
        "secondary_exposure_weight": 0.0,
        "archetype": "export_manufacturer",
        "drivers": ["USD_VND", "export_demand", "order_trend"],
        "classification_confidence": "medium",
        "classification_notes": "mock classification only",
        "classification_evidence": ["mock evidence"],
        "warning_flags": [],
        "manual_review_required": False,
        "archetype_template_status": "TEMPLATE_FOUND",
        "key_economic_exposures": ["USD_VND", "input_cost", "logistics_cost"],
        "typical_revenue_drivers": ["order_trend"],
        "typical_cost_drivers": ["input_cost", "labor_cost"],
    }
    record.update(overrides)
    return record


def test_config_loads_successfully_and_validates():
    registry = _registry()
    result = validate_driver_registry(registry)

    assert result["is_valid"] is True
    assert result["missing_categories"] == []
    assert result["missing_drivers"] == []
    assert result["driver_errors"] == {}


def test_required_drivers_and_categories_exist():
    registry = _registry()

    assert set(REQUIRED_DRIVER_CATEGORIES).issubset(
        set(registry["driver_categories"])
    )
    assert set(REQUIRED_INITIAL_DRIVERS).issubset(set(registry["drivers"]))


def test_every_driver_has_required_fields():
    registry = _registry()

    for driver_id, driver in registry["drivers"].items():
        assert set(REQUIRED_DRIVER_FIELDS).issubset(set(driver))
        assert driver["driver_id"] == driver_id


def test_driver_lookup_by_exact_id_works():
    driver = get_driver("USD_VND", _registry())

    assert driver["driver_id"] == "USD_VND"
    assert driver["category"] == "fx"
    assert "export_manufacturer" in driver["applies_to_archetypes"]


def test_raw_driver_name_normalization_works_for_simple_variants():
    registry = _registry()

    assert normalize_driver_id("USD/VND", registry)["driver_id"] == "USD_VND"
    assert normalize_driver_id("usd vnd", registry)["driver_id"] == "USD_VND"
    assert normalize_driver_id("HRC", registry)["driver_id"] == "HRC_price"


def test_drivers_can_be_resolved_from_archetype():
    drivers = find_drivers_for_archetype("financial_bank", _registry())

    assert "NIM" in drivers
    assert "NPL" in drivers
    assert "loan_growth" in drivers
    assert "credit_growth" in drivers


def test_drivers_can_be_resolved_from_micro_sector():
    drivers = find_drivers_for_micro_sector("commercial_bank", _registry())

    assert "NIM" in drivers
    assert "CASA" in drivers
    assert "provisioning" in drivers


def test_driver_resolution_deduplicates_classification_and_template_hints():
    result = attach_driver_registry(_classification_record(), _registry())
    resolved_ids = [driver["driver_id"] for driver in result["resolved_drivers"]]

    assert result["driver_resolution_status"] == "DRIVERS_RESOLVED"
    assert resolved_ids.count("USD_VND") == 1
    assert resolved_ids.count("input_cost") == 1
    assert "export_demand" in result["primary_drivers"]
    assert "fx" in result["driver_categories"]
    assert bool(result["manual_review_required"]) is False


def test_unknown_driver_hints_are_not_silently_ignored():
    result = attach_driver_registry(
        _classification_record(drivers=["mock_unknown_driver"]), _registry()
    )

    assert result["driver_resolution_status"] == "PARTIAL_DRIVERS_RESOLVED"
    assert "UNKNOWN_DRIVER_HINT" in result["warning_flags"]
    assert "mock_unknown_driver" in result["unmapped_driver_hints"]
    assert bool(result["manual_review_required"]) is True


def test_ambiguous_driver_hints_trigger_manual_review():
    result = attach_driver_registry(
        _classification_record(drivers=["demand"]), _registry()
    )

    assert result["driver_resolution_status"] == "DRIVER_MANUAL_REVIEW"
    assert "AMBIGUOUS_DRIVER_MATCH" in result["warning_flags"]
    assert bool(result["manual_review_required"]) is True


def test_invalid_or_not_classified_ticker_is_not_eligible():
    result = attach_driver_registry(
        _classification_record(
            classification_status="NOT_CLASSIFIED",
            primary_micro_sector="unknown",
            archetype="unknown",
            drivers=[],
        ),
        _registry(),
    )

    assert result["driver_resolution_status"] == "NOT_ELIGIBLE_FOR_DRIVER_RESOLUTION"
    assert result["resolved_drivers"] == []
    assert "NOT_ELIGIBLE_FOR_DRIVER_RESOLUTION" in result["warning_flags"]


def test_low_classification_confidence_preserves_manual_review():
    result = attach_driver_registry(
        _classification_record(classification_confidence="low"),
        _registry(),
    )

    assert result["driver_resolution_status"] == "DRIVER_MANUAL_REVIEW"
    assert "LOW_CLASSIFICATION_CONFIDENCE" in result["warning_flags"]
    assert bool(result["manual_review_required"]) is True


def test_unknown_archetype_template_status_preserves_manual_review():
    result = attach_driver_registry(
        _classification_record(archetype_template_status="UNKNOWN_ARCHETYPE_TEMPLATE"),
        _registry(),
    )

    assert result["driver_resolution_status"] == "DRIVER_MANUAL_REVIEW"
    assert "UNKNOWN_ARCHETYPE_TEMPLATE" in result["warning_flags"]
    assert bool(result["manual_review_required"]) is True


def test_attach_driver_registry_to_records_returns_output_schema():
    dataframe = pd.DataFrame([_classification_record(ticker="MOCK1")])
    result = attach_driver_registry_to_records(dataframe, _registry())

    assert list(result.columns) == DRIVER_REGISTRY_OUTPUT_COLUMNS
    assert result.loc[0, "ticker"] == "MOCK1"
    assert isinstance(result.loc[0, "resolved_drivers"], list)


def test_serialization_helper_converts_list_columns():
    result = attach_driver_registry_to_records(
        [_classification_record()], _registry()
    )
    serialized = serialize_driver_registry_output(result)

    assert isinstance(serialized.loc[0, "resolved_drivers"], str)
    assert "USD_VND" in serialized.loc[0, "resolved_drivers"]


def test_step_16_does_not_calculate_indicator_values():
    result = attach_driver_registry(_classification_record(), _registry())
    public_names = {
        name
        for name in dir(driver_registry)
        if not name.startswith("_") and callable(getattr(driver_registry, name))
    }

    assert not any(name.startswith("calculate") for name in public_names)
    assert not any(name.startswith("score") for name in public_names)
    assert not any(name.startswith("run_sector_cycle") for name in public_names)
    assert "indicator_value" not in result
    assert "sector_cycle_score" not in result


def test_no_real_vietnamese_company_financial_data_is_required():
    result = attach_driver_registry_to_records(
        [_classification_record(ticker="MOCK1")], _registry()
    )

    assert set(result["ticker"]) == {"MOCK1"}
    assert result["ticker"].str.startswith("MOCK").all()

    registry_text = str(_registry()).upper()
    assert "BUY" not in registry_text
    assert "SELL" not in registry_text
    assert "TARGET_PRICE" not in registry_text
