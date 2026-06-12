from pathlib import Path

from src.providers.alternative.source_registry_04a import (
    REQUIRED_PROVIDER_IDS,
    build_source_family_registry,
    is_independent_source_family,
    load_provider_registry,
    validate_provider_registry,
)


CONFIG = Path("config/alternative_provider_registry_04a.yaml")


def test_registry_loads_and_contains_required_providers():
    registry = load_provider_registry(CONFIG)
    validation = validate_provider_registry(registry)
    provider_ids = {provider["provider_id"] for provider in registry["providers"]}

    assert validation["is_valid"], validation["errors"]
    assert REQUIRED_PROVIDER_IDS.issubset(provider_ids)


def test_different_repo_is_not_automatically_independent():
    provider = {
        "role": "SECONDARY_PROVIDER_CANDIDATE",
        "current_confirmation_allowed": "conditional",
        "source_families": ["vnstock_vci"],
    }

    assert is_independent_source_family(provider, "vnstock_vci") is False


def test_raw_local_cache_is_not_independent():
    provider = {"role": "SECONDARY_PROVIDER_CANDIDATE", "current_confirmation_allowed": "conditional"}

    assert is_independent_source_family(provider, "local_cache_only") is False


def test_unknown_brokerage_api_is_not_assumed_independent():
    provider = {"role": "EXPERIMENTAL_SECONDARY_PROVIDER_CANDIDATE", "current_confirmation_allowed": "conditional"}

    assert is_independent_source_family(provider, "unknown_brokerage_api") is False


def test_static_github_historical_fallback_is_not_current_confirmation():
    registry = load_provider_registry(CONFIG)
    source_families = build_source_family_registry(registry)
    rows = source_families[source_families["source_family"].eq("static_github_historical")]

    assert not rows.empty
    assert rows.iloc[0]["is_current_confirmation_allowed"] == "false"
    assert rows.iloc[0]["is_historical_fallback_only"] is True or str(rows.iloc[0]["is_historical_fallback_only"]).lower() == "true"
    assert rows.iloc[0]["is_independent_candidate"] is False or str(rows.iloc[0]["is_independent_candidate"]).lower() == "false"
