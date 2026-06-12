"""04C alternative provider importability and 20-ticker market probe."""

from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.providers.alternative.installability_probe import INSTALLABILITY_COLUMNS, probe_installability_04c
from src.providers.alternative.source_registry import (
    CAPABILITY_MATRIX_COLUMNS,
    build_provider_capability_matrix,
    is_independent_candidate,
    iter_provider_families,
    load_provider_probe_config,
    validate_provider_probe_config,
)
from src.providers.alternative.vietfin_adapter import fetch_vietfin_market
from src.providers.alternative.vnquant_adapter import fetch_vnquant_market


ATTEMPT_LOG_COLUMNS = [
    "ticker",
    "provider_name",
    "source_family",
    "attempt_status",
    "network_used",
    "cache_used",
    "fetch_attempted",
    "fetch_error_type",
    "fetch_error_message",
    "rows_returned",
    "last_price_date",
    "last_close",
    "avg_volume_20d",
    "avg_volume_60d",
    "raw_cache_path",
]

OBSERVATION_COLUMNS = [
    "ticker",
    "primary_source_family",
    "primary_last_price_date",
    "primary_last_close",
    "provider_name",
    "source_family",
    "candidate_independent_from_primary",
    "provider_last_price_date",
    "provider_last_close",
    "price_date_gap_days",
    "price_abs_diff",
    "price_pct_diff",
    "provider_is_current_enough",
    "comparison_status",
    "manual_review_flag",
]

INDEPENDENCE_AUDIT_COLUMNS = [
    "ticker",
    "source_family",
    "provider_count",
    "current_observation_count",
    "current_match_with_primary_count",
    "independent_current_confirmation",
    "independence_reason",
    "confidence_contribution",
]

DECISION_VALUES = {
    "PASS_WITH_INDEPENDENT_CONFIRMATION_FOR_STEP19_SHADOW_RECHECK",
    "CONDITIONAL_GO_NO_INDEPENDENT_CONFIRMATION",
    "NO_GO_PROVIDER_PROBE_BROKEN",
}

DEFAULT_CORE_OUTPUT_PATHS = [
    "data/reports/provisional_current_market_03/current_market_snapshot.csv",
    "data/reports/provisional_current_market_03/stage2_eligibility_gate.csv",
    "data/reports/provisional_current_market_03/current_market_balanced_ranked_shortlist.csv",
    "data/reports/evidence_pack_policy_03_current_market/evidence_collection_queue.csv",
    "data/reports/real_data_02_pilot_20/real_data_02_pilot_readiness.csv",
    "data/reports/alternative_source_consensus_04b/source_family_consensus_20.csv",
    "data/reports/step19_shadow_20/step19_shadow_decision.json",
]


@dataclass
class ProviderProbe04CResult:
    provider_installability: pd.DataFrame
    provider_capability_matrix: pd.DataFrame
    provider_probe_attempt_log: pd.DataFrame
    alternative_provider_market_observations: pd.DataFrame
    source_family_independence_audit: pd.DataFrame
    manual_review_cases: pd.DataFrame
    decision: dict[str, Any]


ProviderFetcher = Callable[..., list[dict[str, Any]]]


def run_provider_probe_04c(
    *,
    config_path: str | Path,
    pilot_snapshot_path: str | Path,
    output_dir: str | Path,
    cache_dir: str | Path,
    max_requests: int | None = None,
    sleep_seconds: float | None = None,
    allow_network: bool | None = None,
    core_output_paths: list[str | Path] | None = None,
    import_module_func: Callable[[str], Any] | None = None,
    find_spec_func: Callable[[str], Any] | None = None,
    version_func: Callable[[str], str] | None = None,
    provider_fetchers: dict[str, ProviderFetcher] | None = None,
) -> ProviderProbe04CResult:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    config = load_provider_probe_config(config_path)
    _apply_runtime_overrides(config, max_requests=max_requests, sleep_seconds=sleep_seconds, allow_network=allow_network)
    core_paths = [Path(path) for path in (core_output_paths or config.get("core_output_watchlist", DEFAULT_CORE_OUTPUT_PATHS))]
    before_hashes = _hashes(core_paths)

    config_errors = validate_provider_probe_config(config)
    snapshot_path = Path(pilot_snapshot_path)
    snapshot = _read_csv(snapshot_path)
    tickers = _snapshot_tickers(snapshot)
    snapshot_errors = _snapshot_errors(snapshot_path, snapshot, tickers, config)

    installability = probe_installability_04c(
        config,
        import_module_func=import_module_func,
        find_spec_func=find_spec_func,
        version_func=version_func,
    )
    capability = build_provider_capability_matrix(config)

    if config_errors or snapshot_errors:
        attempts = pd.DataFrame(columns=ATTEMPT_LOG_COLUMNS)
        observations = pd.DataFrame(columns=OBSERVATION_COLUMNS)
        audit = pd.DataFrame(columns=INDEPENDENCE_AUDIT_COLUMNS)
        manual = pd.DataFrame(columns=OBSERVATION_COLUMNS)
        core_modified = before_hashes != _hashes(core_paths)
        decision = build_decision(
            config_errors=config_errors,
            snapshot_errors=snapshot_errors,
            installability=installability,
            capability=capability,
            attempts=attempts,
            observations=observations,
            audit=audit,
            manual_review=manual,
            pilot_ticker_count=len(tickers),
            expected_ticker_count=_expected_count(config),
            core_outputs_modified=core_modified,
            forbidden_hits=[],
        )
        _write_outputs(output, installability, capability, attempts, observations, audit, manual, decision)
        forbidden_hits = forbidden_term_hits(output)
        decision = build_decision(
            config_errors=config_errors,
            snapshot_errors=snapshot_errors,
            installability=installability,
            capability=capability,
            attempts=attempts,
            observations=observations,
            audit=audit,
            manual_review=manual,
            pilot_ticker_count=len(tickers),
            expected_ticker_count=_expected_count(config),
            core_outputs_modified=core_modified,
            forbidden_hits=forbidden_hits,
        )
        _write_outputs(output, installability, capability, attempts, observations, audit, manual, decision)
        return ProviderProbe04CResult(installability, capability, attempts, observations, audit, manual, decision)

    attempts = build_provider_attempt_log(
        config=config,
        tickers=tickers,
        snapshot=snapshot,
        installability=installability,
        cache_dir=cache,
        import_module_func=import_module_func,
        provider_fetchers=provider_fetchers or {},
    )
    observations = build_market_observations(snapshot, attempts, capability, config)
    audit = build_source_family_independence_audit(observations, capability)
    manual = observations[observations["manual_review_flag"].map(_as_bool)].copy() if not observations.empty else pd.DataFrame(columns=OBSERVATION_COLUMNS)
    core_modified = before_hashes != _hashes(core_paths)
    decision = build_decision(
        config_errors=config_errors,
        snapshot_errors=snapshot_errors,
        installability=installability,
        capability=capability,
        attempts=attempts,
        observations=observations,
        audit=audit,
        manual_review=manual,
        pilot_ticker_count=len(tickers),
        expected_ticker_count=_expected_count(config),
        core_outputs_modified=core_modified,
        forbidden_hits=[],
    )
    _write_outputs(output, installability, capability, attempts, observations, audit, manual, decision)
    forbidden_hits = forbidden_term_hits(output)
    decision = build_decision(
        config_errors=config_errors,
        snapshot_errors=snapshot_errors,
        installability=installability,
        capability=capability,
        attempts=attempts,
        observations=observations,
        audit=audit,
        manual_review=manual,
        pilot_ticker_count=len(tickers),
        expected_ticker_count=_expected_count(config),
        core_outputs_modified=core_modified,
        forbidden_hits=forbidden_hits,
    )
    _write_outputs(output, installability, capability, attempts, observations, audit, manual, decision)
    return ProviderProbe04CResult(installability, capability, attempts, observations, audit, manual, decision)


def build_provider_attempt_log(
    *,
    config: dict[str, Any],
    tickers: list[str],
    snapshot: pd.DataFrame,
    installability: pd.DataFrame,
    cache_dir: Path,
    import_module_func: Callable[[str], Any] | None = None,
    provider_fetchers: dict[str, ProviderFetcher] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    provider_fetchers = provider_fetchers or {}
    installability_by_provider = _index_by(installability, "provider_name")
    allow_network = bool((config.get("run_policy") or {}).get("allow_network", False))
    max_requests = int((config.get("run_policy") or {}).get("max_requests", 20) or 20)
    sleep_seconds = float((config.get("run_policy") or {}).get("sleep_seconds", 0) or 0)
    request_remaining = max_requests
    source_families_by_provider = _families_by_provider(config)
    for provider_name, families in source_families_by_provider.items():
        package_status = installability_by_provider.get(provider_name, {})
        if provider_name == "vnstock":
            rows.extend(_primary_reference_attempts(tickers, snapshot, families))
            continue
        if provider_name == "vnstock_market_data":
            rows.extend(_static_fallback_attempts(tickers, families))
            continue
        network_families = [family["source_family"] for family in families if family.get("default_enabled", True)]
        if not allow_network:
            rows.extend(_network_disabled_attempts(tickers, provider_name, network_families))
            continue
        if package_status.get("import_status") != "IMPORT_OK":
            rows.extend(_provider_unavailable_attempts(tickers, provider_name, network_families, package_status))
            continue
        if request_remaining <= 0:
            rows.extend(_request_limit_attempts(tickers, provider_name, network_families))
            continue
        try:
            fetcher = provider_fetchers.get(provider_name)
            if fetcher is None:
                module = _import_provider_module(provider_name, package_status.get("package_name", ""), import_module_func)
                fetcher = _default_fetcher(provider_name, module)
            provider_rows = fetcher(
                tickers=tickers,
                source_families=network_families,
                cache_dir=cache_dir,
                max_requests=request_remaining,
                sleep_seconds=sleep_seconds,
            )
            provider_rows = [_complete_attempt_row(row, provider_name=provider_name) for row in provider_rows]
            rows.extend(provider_rows)
            request_remaining = max(0, request_remaining - sum(1 for row in provider_rows if _as_bool(row.get("fetch_attempted"))))
        except Exception as exc:  # noqa: BLE001 - provider probe must report, not crash.
            rows.extend(_provider_error_attempts(tickers, provider_name, network_families, type(exc).__name__, str(exc)))
    return pd.DataFrame(rows, columns=ATTEMPT_LOG_COLUMNS + ["price_basis"])[ATTEMPT_LOG_COLUMNS + ["price_basis"]]


def build_market_observations(
    snapshot: pd.DataFrame,
    attempts: pd.DataFrame,
    capability: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    if attempts.empty:
        return pd.DataFrame(columns=OBSERVATION_COLUMNS)
    primary_family = str(((config.get("source_family_rules") or {}).get("primary_source_family") or "vnstock_vci"))
    primary = _index_by_ticker(snapshot)
    capability_by_family = {str(row.get("source_family", "")): row.to_dict() for _, row in capability.iterrows()}
    rows = []
    for _, attempt in attempts.iterrows():
        ticker = str(attempt.get("ticker", "")).upper()
        primary_row = primary.get(ticker, {})
        source_family = str(attempt.get("source_family", ""))
        provider_name = str(attempt.get("provider_name", ""))
        family_config = capability_by_family.get(source_family, {})
        independent_candidate = is_independent_candidate(provider_name, source_family, family_config)
        comparison = _compare_attempt_to_primary(primary_row, attempt, independent_candidate, primary_family, config)
        rows.append(
            {
                "ticker": ticker,
                "primary_source_family": primary_family,
                "primary_last_price_date": primary_row.get("last_price_date", ""),
                "primary_last_close": primary_row.get("last_close", ""),
                "provider_name": provider_name,
                "source_family": source_family,
                "candidate_independent_from_primary": independent_candidate,
                "provider_last_price_date": attempt.get("last_price_date", ""),
                "provider_last_close": attempt.get("last_close", ""),
                "price_date_gap_days": comparison["price_date_gap_days"],
                "price_abs_diff": comparison["price_abs_diff"],
                "price_pct_diff": comparison["price_pct_diff"],
                "provider_is_current_enough": comparison["provider_is_current_enough"],
                "comparison_status": comparison["comparison_status"],
                "manual_review_flag": comparison["manual_review_flag"],
            }
        )
    return pd.DataFrame(rows, columns=OBSERVATION_COLUMNS)


def build_source_family_independence_audit(observations: pd.DataFrame, capability: pd.DataFrame) -> pd.DataFrame:
    if observations.empty:
        return pd.DataFrame(columns=INDEPENDENCE_AUDIT_COLUMNS)
    capability_by_family = {str(row.get("source_family", "")): row.to_dict() for _, row in capability.iterrows()}
    rows = []
    for (ticker, source_family), group in observations.groupby(["ticker", "source_family"], dropna=False):
        family_config = capability_by_family.get(str(source_family), {})
        candidate = bool(family_config.get("candidate_independent_from_vnstock_vci", False))
        current = group[group["provider_is_current_enough"].map(_as_bool)]
        matches = current[current["comparison_status"].eq("PRICE_MATCH")]
        independent_confirmation = bool(candidate and not matches.empty)
        reason = _independence_reason(source_family, family_config, current_count=len(current), match_count=len(matches))
        rows.append(
            {
                "ticker": ticker,
                "source_family": source_family,
                "provider_count": int(group["provider_name"].nunique()),
                "current_observation_count": int(len(current)),
                "current_match_with_primary_count": int(len(matches)),
                "independent_current_confirmation": independent_confirmation,
                "independence_reason": reason,
                "confidence_contribution": "CURRENT_INDEPENDENT_CONFIRMATION" if independent_confirmation else "NO_CURRENT_CONFIDENCE_UPGRADE",
            }
        )
    return pd.DataFrame(rows, columns=INDEPENDENCE_AUDIT_COLUMNS)


def build_decision(
    *,
    config_errors: list[str],
    snapshot_errors: list[str],
    installability: pd.DataFrame,
    capability: pd.DataFrame,
    attempts: pd.DataFrame,
    observations: pd.DataFrame,
    audit: pd.DataFrame,
    manual_review: pd.DataFrame,
    pilot_ticker_count: int,
    expected_ticker_count: int,
    core_outputs_modified: bool,
    forbidden_hits: list[str],
) -> dict[str, Any]:
    importable_statuses = {"IMPORT_OK", "PACKAGE_FOUND_IMPORT_SKIPPED_PRIMARY"}
    importable_count = int(installability["import_status"].isin(importable_statuses).sum()) if not installability.empty else 0
    not_importable_count = int(installability["import_status"].isin(["PACKAGE_NOT_FOUND", "IMPORT_ERROR"]).sum()) if not installability.empty else 0
    network_used = bool(attempts["network_used"].map(_as_bool).any()) if not attempts.empty else False
    fetch_attempt_count = int(attempts["fetch_attempted"].map(_as_bool).sum()) if not attempts.empty else 0
    independent_families = sorted(
        audit[audit["independent_current_confirmation"].map(_as_bool)]["source_family"].astype(str).unique().tolist()
    ) if not audit.empty else []
    tickers_with_confirmation = int(
        audit[audit["independent_current_confirmation"].map(_as_bool)]["ticker"].astype(str).nunique()
    ) if not audit.empty else 0
    manual_review_count = int(len(manual_review))
    schema_errors = _output_schema_errors(installability, capability, attempts, observations, audit, manual_review)
    critical_fail_count = (
        len(config_errors)
        + len(snapshot_errors)
        + len(schema_errors)
        + int(pilot_ticker_count != expected_ticker_count)
        + int(core_outputs_modified)
        + len(forbidden_hits)
    )
    if critical_fail_count:
        final_decision = "NO_GO_PROVIDER_PROBE_BROKEN"
    elif independent_families:
        final_decision = "PASS_WITH_INDEPENDENT_CONFIRMATION_FOR_STEP19_SHADOW_RECHECK"
    else:
        final_decision = "CONDITIONAL_GO_NO_INDEPENDENT_CONFIRMATION"
    if final_decision not in DECISION_VALUES:
        raise ValueError(f"Invalid 04C decision: {final_decision}")
    return {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "pilot_ticker_count": pilot_ticker_count,
        "expected_pilot_ticker_count": expected_ticker_count,
        "providers_registered": int(len(installability)),
        "provider_importable_count": importable_count,
        "provider_not_importable_count": not_importable_count,
        "network_used": network_used,
        "provider_fetch_attempt_count": fetch_attempt_count,
        "independent_current_source_family_count": int(len(independent_families)),
        "independent_current_source_families": independent_families,
        "tickers_with_independent_confirmation_count": tickers_with_confirmation,
        "manual_review_count": manual_review_count,
        "critical_fail_count": critical_fail_count,
        "config_errors": config_errors,
        "snapshot_errors": snapshot_errors,
        "schema_errors": schema_errors,
        "forbidden_terms_found": forbidden_hits,
        "core_outputs_modified": core_outputs_modified,
        "final_decision": final_decision,
        "allowed_next_step": _allowed_next_step(final_decision),
        "not_authorized": [
            "production_step19",
            "top500_refresh",
            "full_universe_live_fetch",
            "official_pdf_fetch",
            "OCR",
            "valuation",
            "target_price",
            "buy_sell_hold_recommendation",
        ],
    }


def build_summary(decision: dict[str, Any]) -> str:
    lines = [
        "# PROVISIONAL-ALT-SOURCE-04C Provider Probe Summary",
        "",
        f"- generated_at: {decision.get('generated_at', '')}",
        f"- pilot_ticker_count: {decision.get('pilot_ticker_count', 0)}",
        f"- providers_registered: {decision.get('providers_registered', 0)}",
        f"- provider_importable_count: {decision.get('provider_importable_count', 0)}",
        f"- provider_not_importable_count: {decision.get('provider_not_importable_count', 0)}",
        f"- network_used: {decision.get('network_used', False)}",
        f"- provider_fetch_attempt_count: {decision.get('provider_fetch_attempt_count', 0)}",
        f"- independent_current_source_family_count: {decision.get('independent_current_source_family_count', 0)}",
        f"- tickers_with_independent_confirmation_count: {decision.get('tickers_with_independent_confirmation_count', 0)}",
        f"- manual_review_count: {decision.get('manual_review_count', 0)}",
        f"- critical_fail_count: {decision.get('critical_fail_count', 0)}",
        f"- final_decision: {decision.get('final_decision', '')}",
        "",
        "## Interpretation",
        "- 04C strengthens 04B by separating package importability, provider fetch attempts, and source-family independence.",
        "- If network is disabled or optional packages are unavailable, the run remains diagnostic and does not fabricate observations.",
        "- Usable future consensus requires a current independent source-family with direct price-date agreement.",
        "- Finance remains provisional and one-source-only unless separately fixed.",
        "",
        "## Not authorized",
        "- not_authorized: production Step19",
        "- not_authorized: top500 refresh",
        "- not_authorized: full universe fetch",
        "- not_authorized: official PDF fetch",
        "- not_authorized: OCR",
        "- not_authorized: valuation",
        "- not_authorized: buy/sell/hold recommendation",
    ]
    return "\n".join(lines) + "\n"


def forbidden_term_hits(output_dir: Path) -> list[str]:
    terms = [
        "buy",
        "sell",
        "target_price",
        "fair_value",
        "margin_of_safety",
        "portfolio_weight",
        "entry_signal",
        "exit_signal",
        "recommendation",
    ]
    allowed = ["not_authorized", "forbidden", "blocked", "safety", "does not authorize"]
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


def _apply_runtime_overrides(config: dict[str, Any], *, max_requests: int | None, sleep_seconds: float | None, allow_network: bool | None) -> None:
    run_policy = config.setdefault("run_policy", {})
    if max_requests is not None:
        run_policy["max_requests"] = int(max_requests)
    if sleep_seconds is not None:
        run_policy["sleep_seconds"] = float(sleep_seconds)
    if allow_network is not None:
        run_policy["allow_network"] = bool(allow_network)


def _snapshot_errors(snapshot_path: Path, snapshot: pd.DataFrame, tickers: list[str], config: dict[str, Any]) -> list[str]:
    errors = []
    if not snapshot_path.exists():
        errors.append("required input snapshot is missing")
        return errors
    required = ["ticker", "last_price_date", "last_close", "avg_volume_20d", "avg_volume_60d"]
    missing = [column for column in required if column not in snapshot.columns]
    if missing:
        errors.append(f"primary snapshot schema missing columns: {','.join(missing)}")
    if len(tickers) != _expected_count(config):
        errors.append(f"pilot ticker count must be {_expected_count(config)}, got {len(tickers)}")
    return errors


def _expected_count(config: dict[str, Any]) -> int:
    return int((config.get("run_policy") or {}).get("expected_pilot_ticker_count", 20) or 20)


def _families_by_provider(config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for family in iter_provider_families(config):
        out.setdefault(str(family.get("provider_name", "")), []).append(family)
    return out


def _primary_reference_attempts(tickers: list[str], snapshot: pd.DataFrame, families: list[dict[str, Any]]) -> list[dict[str, Any]]:
    family = str(families[0].get("source_family", "vnstock_vci")) if families else "vnstock_vci"
    primary = _index_by_ticker(snapshot)
    rows = []
    for ticker in tickers:
        row = primary.get(ticker, {})
        rows.append(
            _attempt_row(
                ticker=ticker,
                provider_name="vnstock",
                source_family=family,
                attempt_status="PRIMARY_REFERENCE_ONLY",
                network_used=False,
                cache_used=False,
                fetch_attempted=False,
                rows_returned=1 if row else 0,
                last_price_date=row.get("last_price_date", ""),
                last_close=row.get("last_close", ""),
                avg_volume_20d=row.get("avg_volume_20d", ""),
                avg_volume_60d=row.get("avg_volume_60d", ""),
                raw_cache_path="",
                price_basis="unadjusted",
            )
        )
    return rows


def _static_fallback_attempts(tickers: list[str], families: list[dict[str, Any]]) -> list[dict[str, Any]]:
    family = str(families[0].get("source_family", "static_github_historical")) if families else "static_github_historical"
    return [
        _attempt_row(
            ticker=ticker,
            provider_name="vnstock_market_data",
            source_family=family,
            attempt_status="HISTORICAL_FALLBACK_ONLY",
            network_used=False,
            cache_used=False,
            fetch_attempted=False,
            fetch_error_type="StaticHistoricalFallback",
            fetch_error_message="Static fallback is not used as current confirmation in 04C.",
        )
        for ticker in tickers
    ]


def _network_disabled_attempts(tickers: list[str], provider_name: str, source_families: list[str]) -> list[dict[str, Any]]:
    return [
        _attempt_row(
            ticker=ticker,
            provider_name=provider_name,
            source_family=source_family,
            attempt_status="FETCH_SKIPPED_NETWORK_DISABLED",
            network_used=False,
            cache_used=False,
            fetch_attempted=False,
        )
        for ticker in tickers
        for source_family in source_families
    ]


def _provider_unavailable_attempts(tickers: list[str], provider_name: str, source_families: list[str], package_status: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _attempt_row(
            ticker=ticker,
            provider_name=provider_name,
            source_family=source_family,
            attempt_status="PROVIDER_NOT_IMPORTABLE",
            network_used=False,
            cache_used=False,
            fetch_attempted=False,
            fetch_error_type=str(package_status.get("import_status", "")),
            fetch_error_message=str(package_status.get("import_error_message", "")),
        )
        for ticker in tickers
        for source_family in source_families
    ]


def _provider_error_attempts(tickers: list[str], provider_name: str, source_families: list[str], error_type: str, error_message: str) -> list[dict[str, Any]]:
    return [
        _attempt_row(
            ticker=ticker,
            provider_name=provider_name,
            source_family=source_family,
            attempt_status="PROVIDER_ERROR",
            network_used=False,
            cache_used=False,
            fetch_attempted=False,
            fetch_error_type=error_type,
            fetch_error_message=error_message,
        )
        for ticker in tickers
        for source_family in source_families
    ]


def _request_limit_attempts(tickers: list[str], provider_name: str, source_families: list[str]) -> list[dict[str, Any]]:
    return [
        _attempt_row(
            ticker=ticker,
            provider_name=provider_name,
            source_family=source_family,
            attempt_status="REQUEST_LIMIT_REACHED",
            network_used=False,
            cache_used=False,
            fetch_attempted=False,
            fetch_error_type="RequestLimitReached",
            fetch_error_message="04C request limit was reached before this provider call.",
        )
        for ticker in tickers
        for source_family in source_families
    ]


def _default_fetcher(provider_name: str, module: Any) -> ProviderFetcher:
    if provider_name == "vnquant":
        return lambda **kwargs: fetch_vnquant_market(module=module, **kwargs)
    if provider_name == "vietfin":
        return lambda **kwargs: fetch_vietfin_market(module=module, **kwargs)
    raise ValueError(f"No 04C default fetcher for provider {provider_name}")


def _import_provider_module(provider_name: str, package_name: str, import_module_func: Callable[[str], Any] | None) -> Any:
    if not package_name:
        raise ValueError(f"{provider_name} has no package_name")
    importer = import_module_func or importlib.import_module
    return importer(package_name)


def _complete_attempt_row(row: dict[str, Any], *, provider_name: str) -> dict[str, Any]:
    out = _attempt_row(
        ticker=str(row.get("ticker", "")),
        provider_name=str(row.get("provider_name", provider_name) or provider_name),
        source_family=str(row.get("source_family", "")),
        attempt_status=str(row.get("attempt_status", "")),
        network_used=_as_bool(row.get("network_used")),
        cache_used=_as_bool(row.get("cache_used")),
        fetch_attempted=_as_bool(row.get("fetch_attempted")),
        fetch_error_type=str(row.get("fetch_error_type", "")),
        fetch_error_message=str(row.get("fetch_error_message", "")),
        rows_returned=row.get("rows_returned", 0),
        last_price_date=row.get("last_price_date", ""),
        last_close=row.get("last_close", ""),
        avg_volume_20d=row.get("avg_volume_20d", ""),
        avg_volume_60d=row.get("avg_volume_60d", ""),
        raw_cache_path=str(row.get("raw_cache_path", "")),
        price_basis=str(row.get("price_basis", "")),
    )
    return out


def _attempt_row(
    *,
    ticker: str,
    provider_name: str,
    source_family: str,
    attempt_status: str,
    network_used: bool,
    cache_used: bool,
    fetch_attempted: bool,
    fetch_error_type: str = "",
    fetch_error_message: str = "",
    rows_returned: Any = 0,
    last_price_date: Any = "",
    last_close: Any = "",
    avg_volume_20d: Any = "",
    avg_volume_60d: Any = "",
    raw_cache_path: str = "",
    price_basis: str = "",
) -> dict[str, Any]:
    return {
        "ticker": str(ticker).strip().upper(),
        "provider_name": provider_name,
        "source_family": source_family,
        "attempt_status": attempt_status,
        "network_used": bool(network_used),
        "cache_used": bool(cache_used),
        "fetch_attempted": bool(fetch_attempted),
        "fetch_error_type": fetch_error_type,
        "fetch_error_message": fetch_error_message,
        "rows_returned": rows_returned,
        "last_price_date": _date_label(last_price_date),
        "last_close": last_close,
        "avg_volume_20d": avg_volume_20d,
        "avg_volume_60d": avg_volume_60d,
        "raw_cache_path": raw_cache_path,
        "price_basis": price_basis,
    }


def _compare_attempt_to_primary(primary_row: dict[str, Any], attempt: pd.Series, independent_candidate: bool, primary_family: str, config: dict[str, Any]) -> dict[str, Any]:
    status = str(attempt.get("attempt_status", ""))
    source_family = str(attempt.get("source_family", ""))
    if status in {"FETCH_SKIPPED_NETWORK_DISABLED", "PROVIDER_NOT_IMPORTABLE", "PROVIDER_ERROR", "PROVIDER_API_UNSUPPORTED", "PROVIDER_NO_DATA", "REQUEST_LIMIT_REACHED"}:
        return _comparison(status)
    if source_family == "static_github_historical" or status == "HISTORICAL_FALLBACK_ONLY":
        return _comparison("HISTORICAL_FALLBACK_ONLY")
    if _missing(primary_row.get("last_close")) or _missing(primary_row.get("last_price_date")):
        return _comparison("PRIMARY_MISSING")
    if _missing(attempt.get("last_price_date")) or _missing(attempt.get("last_close")):
        return _comparison("PROVIDER_NO_DATA")
    gap = _date_gap_days(primary_row.get("last_price_date"), attempt.get("last_price_date"))
    price_abs = _abs_diff(primary_row.get("last_close"), attempt.get("last_close"))
    price_pct = _pct_diff(primary_row.get("last_close"), attempt.get("last_close"))
    current = gap is not None and abs(gap) <= int((config.get("comparison") or {}).get("max_current_reference_gap_days", 5) or 5)
    if not current:
        return _comparison("REFERENCE_STALE", gap, price_abs, price_pct, False)
    if source_family == primary_family or not independent_candidate:
        return _comparison("NOT_INDEPENDENT_SAME_SOURCE_FAMILY", gap, price_abs, price_pct, current)
    price_basis = str(attempt.get("price_basis", ""))
    if price_basis == "adjusted":
        return _comparison("MANUAL_REVIEW_PRICE_BASIS_MISMATCH", gap, price_abs, price_pct, current, True)
    if price_basis == "unknown":
        return _comparison("WARN_PRICE_BASIS_UNKNOWN", gap, price_abs, price_pct, current, True)
    threshold = float((config.get("comparison") or {}).get("max_price_pct_diff_for_match", 0.03) or 0.03)
    if price_pct is not None and abs(price_pct) > threshold:
        return _comparison("PRICE_MISMATCH", gap, price_abs, price_pct, current, True)
    volume_pct = _pct_diff(primary_row.get("avg_volume_60d"), attempt.get("avg_volume_60d"))
    volume_threshold = float((config.get("comparison") or {}).get("max_volume_60d_pct_diff_for_match", 0.50) or 0.50)
    if volume_pct is not None and abs(volume_pct) > volume_threshold:
        return _comparison("VOLUME_MISMATCH", gap, price_abs, price_pct, current, True)
    return _comparison("PRICE_MATCH", gap, price_abs, price_pct, current)


def _comparison(status: str, gap: Any = "", price_abs: Any = "", price_pct: Any = "", current: bool = False, manual: bool = False) -> dict[str, Any]:
    return {
        "price_date_gap_days": "" if gap is None else gap,
        "price_abs_diff": "" if price_abs is None else price_abs,
        "price_pct_diff": "" if price_pct is None else price_pct,
        "provider_is_current_enough": bool(current),
        "comparison_status": status,
        "manual_review_flag": bool(manual),
    }


def _independence_reason(source_family: str, family_config: dict[str, Any], *, current_count: int, match_count: int) -> str:
    if source_family == "static_github_historical":
        return "Static historical fallback is not current confirmation."
    if source_family in {"vnstock_vci", "vnstock_tcbs", "vnstock_other"}:
        return "Same primary source-family as vnstock VCI; not independent."
    if not bool(family_config.get("candidate_independent_from_vnstock_vci", False)):
        return "Source-family is not cleared as independent from vnstock VCI."
    if current_count == 0:
        return "No current observation was available."
    if match_count == 0:
        return "Current observation did not match primary within tolerance."
    return "Independent current source-family matched primary within tolerance."


def _output_schema_errors(installability: pd.DataFrame, capability: pd.DataFrame, attempts: pd.DataFrame, observations: pd.DataFrame, audit: pd.DataFrame, manual: pd.DataFrame) -> list[str]:
    checks = [
        ("provider_installability_04c", installability, INSTALLABILITY_COLUMNS),
        ("provider_capability_matrix_04c", capability, CAPABILITY_MATRIX_COLUMNS),
        ("provider_probe_attempt_log_20", attempts, ATTEMPT_LOG_COLUMNS),
        ("alternative_provider_market_observations_20", observations, OBSERVATION_COLUMNS),
        ("source_family_independence_audit_20", audit, INDEPENDENCE_AUDIT_COLUMNS),
        ("manual_review_cases", manual, OBSERVATION_COLUMNS),
    ]
    errors = []
    for name, frame, columns in checks:
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            errors.append(f"{name} missing columns: {','.join(missing)}")
    return errors


def _allowed_next_step(final_decision: str) -> str:
    if final_decision == "PASS_WITH_INDEPENDENT_CONFIRMATION_FOR_STEP19_SHADOW_RECHECK":
        return "Rerun STEP19-SHADOW-20 to propagate improved market source-family confidence."
    if final_decision == "CONDITIONAL_GO_NO_INDEPENDENT_CONFIRMATION":
        return "Fix optional provider importability or enable guarded network probe; do not run production Step19."
    return "Fix 04C probe plumbing before any next pilot step."


def _write_outputs(
    output: Path,
    installability: pd.DataFrame,
    capability: pd.DataFrame,
    attempts: pd.DataFrame,
    observations: pd.DataFrame,
    audit: pd.DataFrame,
    manual: pd.DataFrame,
    decision: dict[str, Any],
) -> None:
    installability.to_csv(output / "provider_installability_04c.csv", index=False)
    capability.to_csv(output / "provider_capability_matrix_04c.csv", index=False)
    attempts[ATTEMPT_LOG_COLUMNS].to_csv(output / "provider_probe_attempt_log_20.csv", index=False)
    observations.to_csv(output / "alternative_provider_market_observations_20.csv", index=False)
    audit.to_csv(output / "source_family_independence_audit_20.csv", index=False)
    manual.to_csv(output / "manual_review_cases.csv", index=False)
    (output / "provider_probe_summary.md").write_text(build_summary(decision), encoding="utf-8")
    (output / "provider_probe_decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")


def _index_by(frame: pd.DataFrame, column: str) -> dict[str, dict[str, Any]]:
    if frame.empty or column not in frame.columns:
        return {}
    return {str(row.get(column, "")): row.to_dict() for _, row in frame.iterrows()}


def _index_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty or "ticker" not in frame.columns:
        return {}
    return {str(row.get("ticker", "")).strip().upper(): row.to_dict() for _, row in frame.iterrows()}


def _snapshot_tickers(frame: pd.DataFrame) -> list[str]:
    if frame.empty or "ticker" not in frame.columns:
        return []
    return [ticker for ticker in frame["ticker"].astype(str).str.strip().str.upper().drop_duplicates().tolist() if ticker]


def _read_csv(path: str | Path) -> pd.DataFrame:
    target = Path(path)
    if not target.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(target, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _hashes(paths: list[Path]) -> dict[str, str]:
    return {str(path): _hash_file(path) for path in paths if path.exists()}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _date_gap_days(left: Any, right: Any) -> int | None:
    left_date = pd.to_datetime(left, errors="coerce")
    right_date = pd.to_datetime(right, errors="coerce")
    if pd.isna(left_date) or pd.isna(right_date):
        return None
    return int((left_date.date() - right_date.date()).days)


def _abs_diff(left: Any, right: Any) -> float | None:
    left_num = _to_float(left)
    right_num = _to_float(right)
    if left_num is None or right_num is None:
        return None
    return round(abs(right_num - left_num), 6)


def _pct_diff(primary: Any, provider: Any) -> float | None:
    primary_num = _to_float(primary)
    provider_num = _to_float(provider)
    if primary_num is None or provider_num is None or primary_num == 0:
        return None
    return round((provider_num - primary_num) / abs(primary_num), 6)


def _to_float(value: Any) -> float | None:
    if _missing(value):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _date_label(value: Any) -> str:
    if _missing(value):
        return ""
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return parsed.date().isoformat()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _missing(value: Any) -> bool:
    return value is None or str(value).strip() == "" or str(value).strip().lower() in {"nan", "none", "null"}


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
