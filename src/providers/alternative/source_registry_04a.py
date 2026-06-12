"""Alternative provider source-family registry for 04A sandbox probing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml


PROVIDER_INVENTORY_COLUMNS = [
    "provider_id",
    "package_name",
    "repo",
    "role",
    "configured_source_families",
    "expected_capabilities",
    "current_confirmation_allowed",
    "confidence_ceiling",
    "sandbox_only",
]

SOURCE_FAMILY_COLUMNS = [
    "provider_id",
    "source_family",
    "is_independent_candidate",
    "is_current_confirmation_allowed",
    "is_historical_fallback_only",
    "independence_note",
    "confidence_ceiling",
]

CAPABILITY_COLUMNS = [
    "provider_id",
    "capability",
    "configured_expected",
    "probe_supported",
    "support_status",
    "notes",
]

REQUIRED_PROVIDER_IDS = {
    "vnstock_primary_reference",
    "vnquant_secondary_candidate",
    "vietfin_experimental_candidate",
    "vnstock_market_data_historical_fallback",
}

NON_INDEPENDENT_FAMILIES = {
    "vnstock_vci",
    "vnstock_tcbs",
    "vnstock_other",
    "possible_vnstock_related",
    "static_github_historical",
    "unknown_brokerage_api",
    "local_cache_only",
}


def load_provider_registry(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("Alternative provider registry must be a mapping.")
    return data


def validate_provider_registry(registry: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(registry, dict):
        return {"is_valid": False, "errors": ["registry is not a mapping"], "warnings": warnings}
    safety = registry.get("safety")
    policy = registry.get("probe_policy")
    providers = registry.get("providers")
    if not isinstance(safety, dict):
        errors.append("missing safety config")
    else:
        for key in [
            "sandbox_only",
            "no_core_pipeline_mutation",
            "no_step19",
            "no_real_data_02",
            "no_top500_refresh",
            "no_full_universe_fetch",
        ]:
            if safety.get(key) is not True:
                errors.append(f"safety.{key} must be true")
    if not isinstance(policy, dict):
        errors.append("missing probe_policy config")
    else:
        for key in ["allow_import_probe", "allow_network_fetch", "allow_market_data_fetch", "allow_finance_data_fetch", "allow_auto_install"]:
            if policy.get(key) is not False:
                errors.append(f"probe_policy.{key} must be false")
    if not isinstance(providers, list) or not providers:
        errors.append("providers must be a non-empty list")
        providers = []
    provider_ids = set()
    for index, provider in enumerate(providers):
        if not isinstance(provider, dict):
            errors.append(f"provider[{index}] must be a mapping")
            continue
        provider_id = str(provider.get("provider_id", "")).strip()
        provider_ids.add(provider_id)
        for field in [
            "provider_id",
            "repo",
            "role",
            "source_families",
            "expected_capabilities",
            "independence_note",
            "current_confirmation_allowed",
            "confidence_ceiling",
        ]:
            if field not in provider:
                errors.append(f"{provider_id or index}: missing {field}")
        if not isinstance(provider.get("source_families", []), list):
            errors.append(f"{provider_id}: source_families must be a list")
        if not isinstance(provider.get("expected_capabilities", []), list):
            errors.append(f"{provider_id}: expected_capabilities must be a list")
    missing_required = sorted(REQUIRED_PROVIDER_IDS - provider_ids)
    if missing_required:
        errors.append(f"missing required providers: {','.join(missing_required)}")
    return {"is_valid": not errors, "errors": errors, "warnings": warnings}


def providers_from_registry(registry: dict[str, Any]) -> list[dict[str, Any]]:
    providers = registry.get("providers", [])
    return [provider for provider in providers if isinstance(provider, dict)] if isinstance(providers, list) else []


def build_provider_inventory(registry: dict[str, Any]) -> pd.DataFrame:
    sandbox_only = bool((registry.get("safety") or {}).get("sandbox_only", False))
    rows = []
    for provider in providers_from_registry(registry):
        rows.append(
            {
                "provider_id": provider.get("provider_id", ""),
                "package_name": provider.get("package_name", ""),
                "repo": provider.get("repo", ""),
                "role": provider.get("role", ""),
                "configured_source_families": ";".join(str(item) for item in provider.get("source_families", [])),
                "expected_capabilities": ";".join(str(item) for item in provider.get("expected_capabilities", [])),
                "current_confirmation_allowed": provider.get("current_confirmation_allowed", ""),
                "confidence_ceiling": provider.get("confidence_ceiling", ""),
                "sandbox_only": sandbox_only,
            }
        )
    return pd.DataFrame(rows, columns=PROVIDER_INVENTORY_COLUMNS)


def build_source_family_registry(registry: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for provider in providers_from_registry(registry):
        for family in provider.get("source_families", []):
            family_name = str(family)
            rows.append(
                {
                    "provider_id": provider.get("provider_id", ""),
                    "source_family": family_name,
                    "is_independent_candidate": is_independent_source_family(provider, family_name),
                    "is_current_confirmation_allowed": _current_allowed_label(provider.get("current_confirmation_allowed", False)),
                    "is_historical_fallback_only": is_historical_fallback_only(provider, family_name),
                    "independence_note": provider.get("independence_note", ""),
                    "confidence_ceiling": provider.get("confidence_ceiling", ""),
                }
            )
    return pd.DataFrame(rows, columns=SOURCE_FAMILY_COLUMNS)


def build_capability_matrix(registry: dict[str, Any], probe_log: pd.DataFrame | None = None) -> pd.DataFrame:
    import_status = {}
    if isinstance(probe_log, pd.DataFrame) and not probe_log.empty and "provider_id" in probe_log.columns:
        import_status = dict(zip(probe_log["provider_id"], probe_log["import_status"], strict=False))
    rows = []
    for provider in providers_from_registry(registry):
        provider_id = str(provider.get("provider_id", ""))
        status = import_status.get(provider_id, "NOT_PROBED")
        for capability in provider.get("expected_capabilities", []):
            rows.append(
                {
                    "provider_id": provider_id,
                    "capability": capability,
                    "configured_expected": True,
                    "probe_supported": status == "IMPORT_OK",
                    "support_status": _capability_support_status(provider, status),
                    "notes": _capability_note(provider, status),
                }
            )
    return pd.DataFrame(rows, columns=CAPABILITY_COLUMNS)


def is_independent_source_family(provider: dict[str, Any], source_family: str) -> bool:
    family = str(source_family).strip().lower()
    role = str(provider.get("role", "")).strip().upper()
    if role in {"PRIMARY_PROVIDER_REFERENCE", "HISTORICAL_FALLBACK_ONLY"}:
        return False
    if family in NON_INDEPENDENT_FAMILIES:
        return False
    if _current_allowed_label(provider.get("current_confirmation_allowed", False)) == "false":
        return False
    return True


def is_historical_fallback_only(provider: dict[str, Any], source_family: str) -> bool:
    role = str(provider.get("role", "")).strip().upper()
    family = str(source_family).strip().lower()
    return role == "HISTORICAL_FALLBACK_ONLY" or family == "static_github_historical"


def count_independent_candidate_families(source_family_registry: pd.DataFrame) -> int:
    if source_family_registry.empty or "is_independent_candidate" not in source_family_registry.columns:
        return 0
    return int(source_family_registry["is_independent_candidate"].astype(bool).sum())


def _current_allowed_label(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip().lower()
    return text or "false"


def _capability_support_status(provider: dict[str, Any], import_status: str) -> str:
    if str(provider.get("role", "")).upper() == "HISTORICAL_FALLBACK_ONLY":
        return "HISTORICAL_FALLBACK_CONFIGURED"
    if import_status == "IMPORT_OK":
        return "IMPORTABLE_PACKAGE_CAPABILITY_UNVERIFIED"
    if import_status == "PACKAGE_FOUND_IMPORT_SKIPPED":
        return "PACKAGE_FOUND_CAPABILITY_UNVERIFIED"
    if import_status in {"NOT_IMPORTABLE", "IMPORT_ERROR"}:
        return "PACKAGE_NOT_IMPORTABLE_CAPABILITY_UNVERIFIED"
    if import_status == "SKIPPED_NO_PACKAGE":
        return "NO_PACKAGE_CAPABILITY_CONFIGURED_ONLY"
    return "CONFIGURED_ONLY"


def _capability_note(provider: dict[str, Any], import_status: str) -> str:
    if import_status == "IMPORT_OK":
        return "Package imports, but no market or finance data fetch was attempted in 04A."
    if import_status == "PACKAGE_FOUND_IMPORT_SKIPPED":
        return "Package spec was found; module import was deliberately skipped to avoid provider side effects."
    if str(provider.get("role", "")).upper() == "HISTORICAL_FALLBACK_ONLY":
        return "Static historical fallback only; not current confirmation."
    return "Configured capability only; provider must be validated in a later sandbox step."
