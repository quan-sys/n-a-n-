"""Source-family registry helpers for alternative provider sandbox probes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml


CAPABILITY_MATRIX_COLUMNS = [
    "provider_name",
    "source_family",
    "candidate_independent_from_vnstock_vci",
    "market_current_candidate",
    "historical_candidate",
    "finance_candidate",
    "requires_network",
    "requires_optional_install",
    "default_enabled",
    "confidence_ceiling",
    "notes",
]

NON_INDEPENDENT_SOURCE_FAMILIES = {
    "vnstock_vci",
    "vnstock_tcbs",
    "vnstock_other",
    "static_github_historical",
    "raw_cache_current_market_03",
    "unknown_brokerage_api",
    "possible_vnstock_related",
}

REQUIRED_PROVIDERS = {"vnstock", "vnquant", "vietfin", "vnstock_market_data"}


def load_provider_probe_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("04C provider probe config must be a mapping.")
    return data


def validate_provider_probe_config(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    safety = config.get("safety") if isinstance(config, dict) else {}
    run_policy = config.get("run_policy") if isinstance(config, dict) else {}
    providers = config.get("providers") if isinstance(config, dict) else []
    if not isinstance(safety, dict):
        errors.append("missing safety config")
    else:
        for key in [
            "sandbox_only",
            "no_core_pipeline_mutation",
            "no_ranking_mutation",
            "no_stage_promotion",
            "no_production_step19",
            "no_real_data_02_rerun",
            "no_top500_refresh",
            "no_full_universe_fetch",
            "no_official_pdf_fetch",
            "no_ocr",
            "no_finance_fetch",
            "no_zero_fill",
        ]:
            if safety.get(key) is not True:
                errors.append(f"safety.{key} must be true")
    if not isinstance(run_policy, dict):
        errors.append("missing run_policy config")
    else:
        if run_policy.get("allow_auto_install") is not False:
            errors.append("run_policy.allow_auto_install must be false")
        if int(run_policy.get("expected_pilot_ticker_count", 0) or 0) != 20:
            errors.append("run_policy.expected_pilot_ticker_count must be 20")
    provider_list = providers_from_config(config)
    provider_names = {str(provider.get("provider_name", "")) for provider in provider_list}
    missing = sorted(REQUIRED_PROVIDERS - provider_names)
    if missing:
        errors.append(f"missing required providers: {','.join(missing)}")
    for provider in provider_list:
        provider_name = str(provider.get("provider_name", ""))
        if not provider_name:
            errors.append("provider missing provider_name")
        if "source_families" not in provider or not isinstance(provider.get("source_families"), list):
            errors.append(f"{provider_name}: source_families must be a list")
    return errors


def providers_from_config(config: dict[str, Any]) -> list[dict[str, Any]]:
    providers = config.get("providers", [])
    return [provider for provider in providers if isinstance(provider, dict)] if isinstance(providers, list) else []


def iter_provider_families(config: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for provider in providers_from_config(config):
        provider_name = str(provider.get("provider_name", ""))
        package_name = provider.get("package_name", "")
        role = str(provider.get("role", ""))
        for family in provider.get("source_families", []):
            if not isinstance(family, dict):
                continue
            row = dict(family)
            row["provider_name"] = provider_name
            row["package_name"] = "" if package_name is None else str(package_name)
            row["role"] = role
            rows.append(row)
    return rows


def build_provider_capability_matrix(config: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for family in iter_provider_families(config):
        source_family = str(family.get("source_family", ""))
        rows.append(
            {
                "provider_name": family.get("provider_name", ""),
                "source_family": source_family,
                "candidate_independent_from_vnstock_vci": is_independent_candidate(family.get("provider_name", ""), source_family, family),
                "market_current_candidate": bool(family.get("market_current_candidate", False)),
                "historical_candidate": bool(family.get("historical_candidate", False)),
                "finance_candidate": bool(family.get("finance_candidate", False)),
                "requires_network": bool(family.get("requires_network", False)),
                "requires_optional_install": bool(family.get("requires_optional_install", False)),
                "default_enabled": bool(family.get("default_enabled", False)),
                "confidence_ceiling": family.get("confidence_ceiling", ""),
                "notes": family.get("notes", ""),
            }
        )
    return pd.DataFrame(rows, columns=CAPABILITY_MATRIX_COLUMNS)


def is_independent_candidate(provider_name: str, source_family: str, family_config: dict[str, Any] | None = None) -> bool:
    family = str(source_family).strip()
    provider = str(provider_name).strip()
    if family in NON_INDEPENDENT_SOURCE_FAMILIES:
        return False
    if provider in {"vnstock", "vnstock_market_data"}:
        return False
    if family_config is not None and family_config.get("candidate_independent_from_vnstock_vci") is False:
        return False
    return family in {"cafef_structured_or_market", "vndirect_market"}


def package_by_provider(config: dict[str, Any]) -> dict[str, str]:
    return {
        str(provider.get("provider_name", "")): "" if provider.get("package_name") is None else str(provider.get("package_name", ""))
        for provider in providers_from_config(config)
    }
