"""Local installability probe for alternative provider sandbox 04A."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.providers.alternative.source_registry_04a import (
    CAPABILITY_COLUMNS,
    PROVIDER_INVENTORY_COLUMNS,
    SOURCE_FAMILY_COLUMNS,
    build_capability_matrix,
    build_provider_inventory,
    build_source_family_registry,
    count_independent_candidate_families,
    load_provider_registry,
    providers_from_registry,
    validate_provider_registry,
)


INSTALLABILITY_COLUMNS = [
    "provider_id",
    "package_name",
    "probe_attempted",
    "import_status",
    "installed_version",
    "error_type",
    "error_message",
    "network_used",
    "market_data_fetched",
    "finance_data_fetched",
]

DECISION_VALUES = {"PASS_FOR_ALT_SOURCE_04B", "CONDITIONAL_GO_FOR_ALT_SOURCE_04B", "NO_GO"}

DEFAULT_CORE_OUTPUT_PATHS = [
    "data/reports/provisional_current_market_03/current_market_snapshot.csv",
    "data/reports/provisional_current_market_03/stage2_eligibility_gate.csv",
    "data/reports/provisional_current_market_03/current_market_balanced_ranked_shortlist.csv",
    "data/reports/evidence_pack_policy_03_current_market/evidence_collection_queue.csv",
    "data/reports/real_data_02_pilot_20/real_data_02_pilot_decision.json",
]


def run_alternative_provider_probe(
    *,
    config_path: str | Path,
    output_dir: str | Path,
    core_output_paths: list[str | Path] | None = None,
    import_module_func: Callable[[str], Any] | None = None,
    find_spec_func: Callable[[str], Any] | None = None,
    version_func: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    core_paths = [Path(path) for path in (core_output_paths or DEFAULT_CORE_OUTPUT_PATHS)]
    before_hashes = _hashes(core_paths)

    registry_errors: list[str] = []
    try:
        registry = load_provider_registry(config_path)
    except Exception as exc:  # noqa: BLE001 - registry load failure must produce NO_GO report.
        registry = {}
        registry_errors.append(f"{type(exc).__name__}:{exc}")
    validation = validate_provider_registry(registry) if registry else {"is_valid": False, "errors": registry_errors or ["registry did not load"], "warnings": []}
    registry_errors.extend(validation.get("errors", []))

    provider_inventory = build_provider_inventory(registry) if registry else pd.DataFrame(columns=PROVIDER_INVENTORY_COLUMNS)
    probe_log = probe_installability(
        registry,
        import_module_func=import_module_func,
        find_spec_func=find_spec_func,
        version_func=version_func,
    )
    source_family_registry = build_source_family_registry(registry) if registry else pd.DataFrame(columns=SOURCE_FAMILY_COLUMNS)
    capability_matrix = build_capability_matrix(registry, probe_log) if registry else pd.DataFrame(columns=CAPABILITY_COLUMNS)

    provider_inventory.to_csv(output / "provider_inventory.csv", index=False)
    capability_matrix.to_csv(output / "provider_capability_matrix.csv", index=False)
    source_family_registry.to_csv(output / "source_family_registry.csv", index=False)
    probe_log.to_csv(output / "installability_probe_log.csv", index=False)

    after_hashes = _hashes(core_paths)
    core_outputs_modified = before_hashes != after_hashes
    schema_errors = _output_schema_errors(provider_inventory, capability_matrix, source_family_registry, probe_log)
    decision = build_decision(
        registry_errors=registry_errors,
        schema_errors=schema_errors,
        registry=registry,
        provider_inventory=provider_inventory,
        source_family_registry=source_family_registry,
        probe_log=probe_log,
        core_outputs_modified=core_outputs_modified,
        forbidden_hits=[],
    )
    _write_decision_and_summary(output, decision, validation)
    forbidden_hits = forbidden_term_hits(output)
    if forbidden_hits:
        decision = build_decision(
            registry_errors=registry_errors,
            schema_errors=schema_errors,
            registry=registry,
            provider_inventory=provider_inventory,
            source_family_registry=source_family_registry,
            probe_log=probe_log,
            core_outputs_modified=core_outputs_modified,
            forbidden_hits=forbidden_hits,
        )
        _write_decision_and_summary(output, decision, validation)
    return {
        "provider_inventory": provider_inventory,
        "provider_capability_matrix": capability_matrix,
        "source_family_registry": source_family_registry,
        "installability_probe_log": probe_log,
        "decision": decision,
        "validation": validation,
    }


def probe_installability(
    registry: dict[str, Any],
    *,
    import_module_func: Callable[[str], Any] | None = None,
    find_spec_func: Callable[[str], Any] | None = None,
    version_func: Callable[[str], str] | None = None,
) -> pd.DataFrame:
    policy = registry.get("probe_policy", {}) if isinstance(registry, dict) else {}
    allow_import = bool(policy.get("allow_import_probe", False))
    allow_metadata = bool(policy.get("allow_package_metadata_probe", False))
    import_module_func = import_module_func or importlib.import_module
    find_spec_func = find_spec_func or importlib.util.find_spec
    version_func = version_func or importlib.metadata.version
    rows = []
    for provider in providers_from_registry(registry):
        package_name = provider.get("package_name")
        provider_id = str(provider.get("provider_id", ""))
        if not package_name:
            rows.append(_probe_row(provider_id, "", False, "SKIPPED_NO_PACKAGE", "", "", "", False, False, False))
            continue
        package = str(package_name)
        installed_version = ""
        error_type = ""
        error_message = ""
        probe_attempted = True
        spec = None
        try:
            spec = find_spec_func(package)
        except Exception as exc:  # noqa: BLE001
            error_type = type(exc).__name__
            error_message = str(exc)
        if allow_metadata:
            try:
                installed_version = version_func(package)
            except importlib.metadata.PackageNotFoundError:
                installed_version = ""
            except Exception as exc:  # noqa: BLE001
                if not error_type:
                    error_type = type(exc).__name__
                    error_message = str(exc)
        if spec is None:
            status = "NOT_IMPORTABLE"
        elif not allow_import:
            status = "PACKAGE_FOUND_IMPORT_SKIPPED"
        else:
            try:
                import_module_func(package)
                status = "IMPORT_OK"
            except Exception as exc:  # noqa: BLE001
                status = "IMPORT_ERROR"
                error_type = type(exc).__name__
                error_message = str(exc)
        rows.append(_probe_row(provider_id, package, probe_attempted, status, installed_version, error_type, error_message, False, False, False))
    return pd.DataFrame(rows, columns=INSTALLABILITY_COLUMNS)


def build_decision(
    *,
    registry_errors: list[str],
    schema_errors: list[str],
    registry: dict[str, Any],
    provider_inventory: pd.DataFrame,
    source_family_registry: pd.DataFrame,
    probe_log: pd.DataFrame,
    core_outputs_modified: bool,
    forbidden_hits: list[str],
) -> dict[str, Any]:
    provider_count = int(len(provider_inventory))
    importable_statuses = {"IMPORT_OK", "PACKAGE_FOUND_IMPORT_SKIPPED"}
    importable_count = int(probe_log["import_status"].isin(importable_statuses).sum()) if not probe_log.empty else 0
    non_importable_count = int(probe_log["import_status"].isin(["NOT_IMPORTABLE", "IMPORT_ERROR"]).sum()) if not probe_log.empty else 0
    source_family_count = int(len(source_family_registry))
    independent_count = count_independent_candidate_families(source_family_registry)
    historical_count = int(source_family_registry["is_historical_fallback_only"].astype(bool).sum()) if not source_family_registry.empty else 0
    network_used = False
    market_data_fetched = False
    finance_data_fetched = False
    safety = registry.get("safety", {}) if isinstance(registry, dict) else {}
    safety_missing = not bool(safety)
    if registry_errors or schema_errors or safety_missing or network_used or market_data_fetched or finance_data_fetched or core_outputs_modified or forbidden_hits:
        final_decision = "NO_GO"
    elif non_importable_count or independent_count == 0:
        final_decision = "CONDITIONAL_GO_FOR_ALT_SOURCE_04B"
    else:
        final_decision = "PASS_FOR_ALT_SOURCE_04B"
    if final_decision not in DECISION_VALUES:
        raise ValueError(f"Invalid 04A decision: {final_decision}")
    return {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "provider_count": provider_count,
        "importable_provider_count": importable_count,
        "non_importable_provider_count": non_importable_count,
        "source_family_count": source_family_count,
        "independent_candidate_family_count": independent_count,
        "historical_fallback_only_count": historical_count,
        "network_used": network_used,
        "market_data_fetched": market_data_fetched,
        "finance_data_fetched": finance_data_fetched,
        "core_outputs_modified": core_outputs_modified,
        "registry_errors": registry_errors,
        "schema_errors": schema_errors,
        "forbidden_terms_found": forbidden_hits,
        "final_decision": final_decision,
        "allowed_next_step": "PROVISIONAL-ALT-SOURCE-04B - 20-Ticker Market Consensus Cross-Check" if final_decision != "NO_GO" else "Fix 04A registry/probe issues before 04B.",
        "not_authorized": [
            "Step19",
            "REAL-DATA-02",
            "top500_refresh",
            "full_universe_live_fetch",
            "official_pdf_fetch",
            "OCR",
            "valuation",
            "target_price",
            "buy_sell_hold_recommendation",
        ],
    }


def forbidden_term_hits(output_dir: Path) -> list[str]:
    terms = [
        "buy",
        "sell",
        "target price",
        "target_price",
        "fair value",
        "fair_value",
        "margin of safety",
        "margin_of_safety",
        "recommendation",
    ]
    allowed = ["not_authorized", "no_", "no ", "not ", "forbidden", "blocked", "safety", "does not authorize"]
    hits = []
    for path in sorted(output_dir.glob("*")):
        if path.suffix.lower() not in {".csv", ".json", ".md", ".txt"}:
            continue
        text = _scan_text(path)
        for line_no, line in enumerate(text.splitlines(), start=1):
            lower = line.lower()
            if any(marker in lower for marker in allowed):
                continue
            for term in terms:
                if term in lower:
                    hits.append(f"{path.name}:{line_no}:{term}")
    return hits


def build_run_summary(decision: dict[str, Any], validation: dict[str, Any]) -> str:
    lines = [
        "# PROVISIONAL-ALT-SOURCE-04A Summary",
        "",
        f"- provider_count: {decision.get('provider_count', 0)}",
        f"- importable_provider_count: {decision.get('importable_provider_count', 0)}",
        f"- non_importable_provider_count: {decision.get('non_importable_provider_count', 0)}",
        f"- source_family_count: {decision.get('source_family_count', 0)}",
        f"- independent_candidate_family_count: {decision.get('independent_candidate_family_count', 0)}",
        f"- historical_fallback_only_count: {decision.get('historical_fallback_only_count', 0)}",
        f"- network_used: {decision.get('network_used', False)}",
        f"- market_data_fetched: {decision.get('market_data_fetched', False)}",
        f"- finance_data_fetched: {decision.get('finance_data_fetched', False)}",
        f"- core_outputs_modified: {decision.get('core_outputs_modified', False)}",
        f"- final_decision: {decision.get('final_decision', '')}",
        "",
        "## Interpretation",
        "- This is only a sandbox installability and source-family probe.",
        "- It does not confirm any ticker prices yet.",
        "- It does not authorize Step19.",
        "- It does not authorize top500 or full-universe refresh.",
        "",
        "## Registry Issues",
    ]
    issues = list(validation.get("errors", [])) if validation else []
    lines.extend([f"- {issue}" for issue in issues] if issues else ["- none"])
    lines.extend(
        [
            "",
            "## Allowed next step",
            "PROVISIONAL-ALT-SOURCE-04B - 20-Ticker Market Consensus Cross-Check",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_decision_and_summary(output: Path, decision: dict[str, Any], validation: dict[str, Any]) -> None:
    (output / "alt_source_04a_decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "run_summary.md").write_text(build_run_summary(decision, validation), encoding="utf-8")


def _output_schema_errors(provider_inventory: pd.DataFrame, capability_matrix: pd.DataFrame, source_family_registry: pd.DataFrame, probe_log: pd.DataFrame) -> list[str]:
    checks = [
        ("provider_inventory", provider_inventory, PROVIDER_INVENTORY_COLUMNS),
        ("provider_capability_matrix", capability_matrix, CAPABILITY_COLUMNS),
        ("source_family_registry", source_family_registry, SOURCE_FAMILY_COLUMNS),
        ("installability_probe_log", probe_log, INSTALLABILITY_COLUMNS),
    ]
    errors = []
    for name, frame, columns in checks:
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            errors.append(f"{name} missing columns: {','.join(missing)}")
    return errors


def _probe_row(
    provider_id: str,
    package_name: str,
    probe_attempted: bool,
    import_status: str,
    installed_version: str,
    error_type: str,
    error_message: str,
    network_used: bool,
    market_data_fetched: bool,
    finance_data_fetched: bool,
) -> dict[str, Any]:
    return {
        "provider_id": provider_id,
        "package_name": package_name,
        "probe_attempted": probe_attempted,
        "import_status": import_status,
        "installed_version": installed_version,
        "error_type": error_type,
        "error_message": error_message,
        "network_used": network_used,
        "market_data_fetched": market_data_fetched,
        "finance_data_fetched": finance_data_fetched,
    }


def _hashes(paths: list[Path]) -> dict[str, str]:
    return {str(path): _hash_file(path) for path in paths if path.exists()}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scan_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() != ".json":
        return text
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(data, dict):
        data = dict(data)
        data.pop("not_authorized", None)
    return json.dumps(data, ensure_ascii=False, indent=2)
