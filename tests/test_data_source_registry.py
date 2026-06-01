from copy import deepcopy

import src.fetchers.source_registry as source_registry
from src.fetchers.source_registry import (
    REQUIRED_SOURCE_FIELDS,
    get_dataset_sources,
    get_fallback_sources,
    get_primary_source,
    list_required_datasets_for_stage,
    load_source_registry,
    validate_source_registry,
)


REGISTRY_PATH = "config/data_source_registry.yaml"
REQUIRED_DATASETS = {
    "universe",
    "market_price",
    "company_profile",
    "financial_statement_summary",
    "disclosure_status",
    "macro_vietnam",
    "commodity_global",
    "sector_news",
    "company_events",
}


def _registry():
    return load_source_registry(REGISTRY_PATH)


def test_registry_file_loads_successfully():
    registry = _registry()

    assert isinstance(registry, dict)
    assert "datasets" in registry


def test_registry_contains_all_required_dataset_groups():
    registry = _registry()
    dataset_names = {dataset["dataset_name"] for dataset in registry["datasets"]}

    assert REQUIRED_DATASETS.issubset(dataset_names)


def test_each_dataset_has_at_least_one_source():
    registry = _registry()

    for dataset in registry["datasets"]:
        assert dataset["sources"]


def test_each_source_has_all_required_fields():
    registry = _registry()

    for dataset in registry["datasets"]:
        for source in dataset["sources"]:
            assert set(REQUIRED_SOURCE_FIELDS).issubset(source)


def test_enum_validation_accepts_registry_and_rejects_bad_values():
    registry = _registry()
    valid_result = validate_source_registry(registry)

    assert valid_result["is_valid"] is True
    assert valid_result["errors"] == []

    invalid_registry = deepcopy(registry)
    invalid_registry["datasets"][0]["sources"][0]["source_type"] = "bad_source_type"
    invalid_result = validate_source_registry(invalid_registry)

    assert invalid_result["is_valid"] is False
    assert any("invalid source_type" in error for error in invalid_result["errors"])


def test_get_dataset_sources_returns_sources_for_known_dataset():
    registry = _registry()
    sources = get_dataset_sources(registry, "market_price")

    assert sources
    assert all(source["output_dataset_schema"] == "market_price" for source in sources)


def test_get_primary_source_returns_primary_source_if_available():
    registry = _registry()
    primary_source = get_primary_source(registry, "universe")

    assert primary_source is not None
    assert primary_source["primary_or_backup"] == "primary"


def test_get_fallback_sources_returns_backup_and_fallback_sources():
    registry = _registry()
    fallback_sources = get_fallback_sources(registry, "company_profile")

    assert fallback_sources
    assert {
        source["primary_or_backup"] for source in fallback_sources
    }.issubset({"backup", "fallback"})


def test_unknown_dataset_returns_empty_results_without_crashing():
    registry = _registry()

    assert get_dataset_sources(registry, "unknown_dataset") == []
    assert get_primary_source(registry, "unknown_dataset") is None
    assert get_fallback_sources(registry, "unknown_dataset") == []


def test_production_required_dataset_without_primary_source_creates_warning():
    registry = _registry()
    modified_registry = deepcopy(registry)
    dataset = modified_registry["datasets"][0]
    dataset["production_required"] = True
    for source in dataset["sources"]:
        if source["primary_or_backup"] == "primary":
            source["primary_or_backup"] = "backup"

    result = validate_source_registry(modified_registry)

    assert result["is_valid"] is True
    assert any("has no primary source" in warning for warning in result["warnings"])


def test_stage_requirement_lookup_returns_expected_datasets():
    registry = _registry()
    l0_datasets = list_required_datasets_for_stage(registry, "l0_filters")

    assert {"universe", "market_price", "financial_statement_summary"}.issubset(
        set(l0_datasets)
    )


def test_no_real_data_fetching_or_filtering_scoring_is_implemented():
    public_names = {
        name
        for name in dir(source_registry)
        if not name.startswith("_") and callable(getattr(source_registry, name))
    }

    assert not any(name.startswith("fetch") for name in public_names)
    assert not any(name.startswith("filter") for name in public_names)
    assert not any(name.startswith("score") for name in public_names)
