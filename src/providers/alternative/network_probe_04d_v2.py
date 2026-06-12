"""04D-V2 actual controlled network probe for alternative market providers."""

from __future__ import annotations

import importlib
import importlib.util
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yaml

from src.providers.alternative.network_probe_04d import (
    _abs_diff,
    _as_bool,
    _date_gap_days,
    _date_label,
    _hashes,
    _index_by_ticker,
    _missing,
    _normalize_frame,
    _pct_diff,
    _pilot_tickers,
    _read_csv,
    _vnquant_loader,
    _write_cache,
)


ATTEMPT_LOG_COLUMNS = [
    "provider_name",
    "source_family",
    "ticker",
    "attempt_status",
    "network_allowed",
    "network_used",
    "optional_install_used",
    "request_count",
    "error_type",
    "error_message",
    "attempted_at",
    "elapsed_seconds",
]

OBSERVATION_COLUMNS = [
    "ticker",
    "provider_name",
    "source_family",
    "provider_last_price_date",
    "provider_last_close",
    "provider_avg_volume_20d",
    "provider_avg_volume_60d",
    "provider_trading_days_60d",
    "raw_adjustment_status",
    "raw_or_adjusted_price",
    "observation_status",
    "source_url_or_endpoint_family",
]

CONSENSUS_COLUMNS = [
    "ticker",
    "primary_source_family",
    "primary_last_price_date",
    "primary_last_close",
    "source_family",
    "provider_name",
    "provider_last_price_date",
    "provider_last_close",
    "price_date_gap_days",
    "price_abs_diff",
    "price_pct_diff",
    "provider_is_current_enough",
    "candidate_independent_from_primary",
    "comparison_status",
    "confidence_contribution",
    "manual_review_flag",
]

DECISION_VALUES = {
    "PASS_FOR_CONFIDENCE_UPGRADE_REVIEW",
    "CONDITIONAL_GO_PRIMARY_ONLY_CONFIDENCE",
    "NO_GO_FIX_PROVIDER_PROBE",
}

FORBIDDEN_TERMS = [
    "buy",
    "sell",
    "hold",
    "target price",
    "fair value",
    "margin of safety",
    "recommendation",
]

SAFETY_CONTEXT_MARKERS = [
    "not_authorized",
    "not authorized",
    "do not",
    "forbidden",
    "safety",
    "blocked",
    "no_",
    "non-goals",
]


@dataclass
class NetworkProbe04DV2Result:
    provider_network_attempt_log: pd.DataFrame
    provider_market_observations: pd.DataFrame
    source_family_consensus: pd.DataFrame
    manual_review_cases: pd.DataFrame
    decision: dict[str, Any]


ProviderFetcher = Callable[..., dict[str, Any] | pd.DataFrame]


def load_network_probe_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("04D-V2 network probe config must be a mapping.")
    return data


def run_network_probe_04d_v2(
    *,
    config_path: str | Path,
    snapshot_path: str | Path | None,
    output_dir: str | Path,
    cache_dir: str | Path,
    allow_network: bool | None = None,
    allow_partial: bool | None = None,
    max_requests: int | None = None,
    sleep_seconds: float | None = None,
    core_output_paths: list[str | Path] | None = None,
    import_module_func: Callable[[str], Any] | None = None,
    find_spec_func: Callable[[str], Any] | None = None,
    provider_fetchers: dict[str, ProviderFetcher] | None = None,
) -> NetworkProbe04DV2Result:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    config = load_network_probe_config(config_path)
    if snapshot_path is not None:
        snapshot = str(snapshot_path)
        inputs = config.setdefault("inputs", {})
        inputs["primary_snapshot"] = snapshot
        inputs["ticker_sources"] = [snapshot]
    _apply_overrides(
        config,
        allow_network=allow_network,
        allow_partial=allow_partial,
        max_requests=max_requests,
        sleep_seconds=sleep_seconds,
    )

    config_errors = validate_network_probe_config(config)
    core_paths = [Path(path) for path in (core_output_paths or config.get("core_output_watchlist", []))]
    before_hashes = _hashes(core_paths)

    ticker_source_path, ticker_source = resolve_ticker_source(config)
    primary_path = Path(((config.get("inputs") or {}).get("primary_snapshot") or ""))
    primary_snapshot = _read_csv(primary_path)
    tickers = _pilot_tickers(ticker_source)
    primary_errors = _primary_schema_errors(primary_path, primary_snapshot, tickers, config)

    if config_errors or primary_errors:
        attempts = pd.DataFrame(columns=ATTEMPT_LOG_COLUMNS)
        observations = pd.DataFrame(columns=OBSERVATION_COLUMNS)
        consensus = pd.DataFrame(columns=CONSENSUS_COLUMNS)
        manual = pd.DataFrame(columns=CONSENSUS_COLUMNS)
    else:
        attempts, observations = build_provider_network_outputs(
            config=config,
            tickers=tickers,
            cache_dir=cache,
            import_module_func=import_module_func,
            find_spec_func=find_spec_func,
            provider_fetchers=provider_fetchers or {},
        )
        consensus = build_current_consensus(primary_snapshot, observations, config)
        manual = consensus[consensus["manual_review_flag"].map(_as_bool)].copy() if not consensus.empty else pd.DataFrame(columns=CONSENSUS_COLUMNS)

    core_modified = before_hashes != _hashes(core_paths)
    decision = build_decision(
        config=config,
        attempts=attempts,
        observations=observations,
        consensus=consensus,
        manual_review=manual,
        pilot_ticker_count=len(tickers),
        core_outputs_modified=core_modified,
        config_errors=config_errors,
        primary_errors=primary_errors,
        forbidden_hits=[],
        safety_context_terms=[],
        ticker_source_path=ticker_source_path,
    )
    _write_outputs(output, attempts, observations, consensus, manual, decision)
    forbidden = scan_forbidden_terms(output)
    decision = build_decision(
        config=config,
        attempts=attempts,
        observations=observations,
        consensus=consensus,
        manual_review=manual,
        pilot_ticker_count=len(tickers),
        core_outputs_modified=core_modified,
        config_errors=config_errors,
        primary_errors=primary_errors,
        forbidden_hits=forbidden["actionable_hits"],
        safety_context_terms=forbidden["safety_context_terms"],
        ticker_source_path=ticker_source_path,
    )
    _write_outputs(output, attempts, observations, consensus, manual, decision)
    return NetworkProbe04DV2Result(attempts, observations, consensus, manual, decision)


def validate_network_probe_config(config: dict[str, Any]) -> list[str]:
    errors = []
    safety = config.get("safety") if isinstance(config, dict) else {}
    if not isinstance(safety, dict):
        return ["missing safety config"]
    for key in [
        "sandbox_only",
        "no_core_pipeline_mutation",
        "no_ranking_mutation",
        "no_stage_promotion",
        "no_production_step19",
        "no_step19_output_mutation",
        "no_real_data_02_rerun",
        "no_top500_refresh",
        "no_full_universe_fetch",
        "no_finance_fetch",
        "no_official_pdf_fetch",
        "no_ocr",
        "no_zero_fill",
    ]:
        if safety.get(key) is not True:
            errors.append(f"safety.{key} must be true")
    run_policy = config.get("run_policy") or {}
    if int(run_policy.get("expected_pilot_ticker_count", 0) or 0) != 20:
        errors.append("run_policy.expected_pilot_ticker_count must be 20")
    if bool(run_policy.get("allow_optional_install", False)):
        errors.append("run_policy.allow_optional_install must remain false")
    if not isinstance(config.get("providers"), list) or not config.get("providers"):
        errors.append("providers must be configured")
    return errors


def resolve_ticker_source(config: dict[str, Any]) -> tuple[str, pd.DataFrame]:
    for candidate in ((config.get("inputs") or {}).get("ticker_sources") or []):
        path = Path(str(candidate))
        if path.exists():
            return str(path), _read_csv(path)
    return "", pd.DataFrame()


def build_provider_network_outputs(
    *,
    config: dict[str, Any],
    tickers: list[str],
    cache_dir: Path,
    import_module_func: Callable[[str], Any] | None = None,
    find_spec_func: Callable[[str], Any] | None = None,
    provider_fetchers: dict[str, ProviderFetcher] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    run_policy = config.get("run_policy") or {}
    network_allowed = bool(run_policy.get("allow_network", False))
    allow_partial = bool(run_policy.get("allow_partial", True))
    max_requests = int(run_policy.get("max_requests", 40) or 40)
    sleep_seconds = float(run_policy.get("sleep_seconds", 0) or 0)
    find_spec_func = find_spec_func or importlib.util.find_spec
    import_module_func = import_module_func or importlib.import_module
    provider_fetchers = provider_fetchers or {}
    attempts: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    request_count = 0

    for provider in _providers(config):
        provider_name = str(provider.get("provider_name", ""))
        package_name = provider.get("package_name")
        families = _enabled_families(provider)
        if provider_name == "vnstock_market_data":
            for family in families:
                for ticker in tickers:
                    attempts.append(
                        _attempt(
                            provider_name,
                            family["source_family"],
                            ticker,
                            "HISTORICAL_FALLBACK_ONLY",
                            network_allowed,
                            False,
                            False,
                            request_count,
                            "HistoricalFallbackOnly",
                            "Static GitHub historical fallback is not current confirmation.",
                        )
                    )
                    observations.append(_observation(ticker, provider_name, family["source_family"], "HISTORICAL_FALLBACK_ONLY", source_url_or_endpoint_family=family.get("source_url_or_endpoint_family", "")))
            continue
        if not network_allowed:
            for family in families:
                for ticker in tickers:
                    attempts.append(_attempt(provider_name, family["source_family"], ticker, "NETWORK_DISABLED", False, False, False, request_count))
                    observations.append(_observation(ticker, provider_name, family["source_family"], "NETWORK_DISABLED", source_url_or_endpoint_family=family.get("source_url_or_endpoint_family", "")))
            continue
        started_import = time.perf_counter()
        if package_name and find_spec_func(str(package_name)) is None:
            elapsed = time.perf_counter() - started_import
            for family in families:
                for ticker in tickers:
                    attempts.append(_attempt(provider_name, family["source_family"], ticker, "NOT_IMPORTABLE", True, False, False, request_count, "NOT_IMPORTABLE", f"Package {package_name} is not importable.", elapsed))
                    observations.append(_observation(ticker, provider_name, family["source_family"], "NO_PROVIDER_OBSERVATION", source_url_or_endpoint_family=family.get("source_url_or_endpoint_family", "")))
            continue
        try:
            module = import_module_func(str(package_name)) if package_name else None
        except Exception as exc:  # noqa: BLE001
            elapsed = time.perf_counter() - started_import
            for family in families:
                for ticker in tickers:
                    attempts.append(_attempt(provider_name, family["source_family"], ticker, "IMPORT_ERROR", True, False, False, request_count, type(exc).__name__, str(exc), elapsed))
                    observations.append(_observation(ticker, provider_name, family["source_family"], "NO_PROVIDER_OBSERVATION", source_url_or_endpoint_family=family.get("source_url_or_endpoint_family", "")))
            continue
        fetcher = provider_fetchers.get(provider_name) or _default_fetcher(provider_name, module)
        if fetcher is None:
            for family in families:
                for ticker in tickers:
                    attempts.append(_attempt(provider_name, family["source_family"], ticker, "UNSUPPORTED_PROVIDER", True, False, False, request_count, "NoSupportedFetcher", "No supported 04D-V2 fetch interface was detected."))
                    observations.append(_observation(ticker, provider_name, family["source_family"], "NO_PROVIDER_OBSERVATION", source_url_or_endpoint_family=family.get("source_url_or_endpoint_family", "")))
            continue
        for family in families:
            source_family = str(family.get("source_family", ""))
            for ticker in tickers:
                if request_count >= max_requests:
                    attempts.append(_attempt(provider_name, source_family, ticker, "FETCH_ERROR", True, False, False, request_count, "RequestBudgetExhausted", "04D-V2 request budget exhausted."))
                    observations.append(_observation(ticker, provider_name, source_family, "FETCH_ERROR", source_url_or_endpoint_family=family.get("source_url_or_endpoint_family", "")))
                    continue
                request_count += 1
                started = time.perf_counter()
                try:
                    raw = fetcher(ticker=ticker, source_family=source_family, family_config=family, cache_dir=cache_dir, request_count=request_count)
                    normalized, row_network_used = _normalize_provider_payload(raw, ticker=ticker, provider_name=provider_name, source_family=source_family, endpoint_family=str(family.get("source_url_or_endpoint_family", "")), cache_dir=cache_dir)
                    status = "FETCH_OK" if normalized.get("observation_status") == "PROVIDER_OBSERVATION" else "FETCH_EMPTY"
                    attempts.append(_attempt(provider_name, source_family, ticker, status, True, row_network_used, False, request_count, elapsed_seconds=time.perf_counter() - started))
                    observations.append(normalized)
                except Exception as exc:  # noqa: BLE001
                    attempts.append(_attempt(provider_name, source_family, ticker, "FETCH_ERROR", True, True, False, request_count, type(exc).__name__, str(exc), time.perf_counter() - started))
                    observations.append(_observation(ticker, provider_name, source_family, "FETCH_ERROR", source_url_or_endpoint_family=family.get("source_url_or_endpoint_family", "")))
                    if not allow_partial:
                        break
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
    return pd.DataFrame(attempts, columns=ATTEMPT_LOG_COLUMNS), pd.DataFrame(observations, columns=OBSERVATION_COLUMNS)


def build_current_consensus(primary_snapshot: pd.DataFrame, observations: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    if observations.empty:
        return pd.DataFrame(columns=CONSENSUS_COLUMNS)
    primary_by_ticker = _index_by_ticker(primary_snapshot)
    primary_family = str(((config.get("source_family_rules") or {}).get("primary_source_family") or "vnstock_vci"))
    provider_family_rules = _family_rules(config)
    rows = []
    for _, obs in observations.iterrows():
        ticker = str(obs.get("ticker", "")).strip().upper()
        primary = primary_by_ticker.get(ticker, {})
        source_family = str(obs.get("source_family", ""))
        candidate_independent = bool(provider_family_rules.get(source_family, {}).get("candidate_independent_from_primary", False))
        comparison = _compare_observation(primary, obs, candidate_independent, primary_family, config)
        rows.append(
            {
                "ticker": ticker,
                "primary_source_family": primary_family,
                "primary_last_price_date": primary.get("last_price_date", ""),
                "primary_last_close": primary.get("last_close", ""),
                "source_family": source_family,
                "provider_name": obs.get("provider_name", ""),
                "provider_last_price_date": obs.get("provider_last_price_date", ""),
                "provider_last_close": obs.get("provider_last_close", ""),
                "price_date_gap_days": comparison["price_date_gap_days"],
                "price_abs_diff": comparison["price_abs_diff"],
                "price_pct_diff": comparison["price_pct_diff"],
                "provider_is_current_enough": comparison["provider_is_current_enough"],
                "candidate_independent_from_primary": candidate_independent,
                "comparison_status": comparison["comparison_status"],
                "confidence_contribution": comparison["confidence_contribution"],
                "manual_review_flag": comparison["manual_review_flag"],
            }
        )
    return pd.DataFrame(rows, columns=CONSENSUS_COLUMNS)


def build_decision(
    *,
    config: dict[str, Any],
    attempts: pd.DataFrame,
    observations: pd.DataFrame,
    consensus: pd.DataFrame,
    manual_review: pd.DataFrame,
    pilot_ticker_count: int,
    core_outputs_modified: bool,
    config_errors: list[str],
    primary_errors: list[str],
    forbidden_hits: list[str],
    safety_context_terms: list[str],
    ticker_source_path: str,
) -> dict[str, Any]:
    run_policy = config.get("run_policy") or {}
    expected_count = int(run_policy.get("expected_pilot_ticker_count", 20) or 20)
    network_allowed = bool(run_policy.get("allow_network", False))
    network_used = bool(attempts["network_used"].map(_as_bool).any()) if not attempts.empty else False
    package_attempts = attempts[~attempts["provider_name"].eq("vnstock_market_data")] if not attempts.empty else pd.DataFrame(columns=ATTEMPT_LOG_COLUMNS)
    provider_runtime_count = int(package_attempts["provider_name"].astype(str).nunique()) if not package_attempts.empty else 0
    importable_statuses = {"FETCH_OK", "FETCH_EMPTY", "FETCH_ERROR", "UNSUPPORTED_PROVIDER"}
    provider_importable_count = int(package_attempts[package_attempts["attempt_status"].isin(importable_statuses)]["provider_name"].astype(str).nunique()) if not package_attempts.empty else 0
    provider_not_importable_count = int(package_attempts[package_attempts["attempt_status"].eq("NOT_IMPORTABLE")]["provider_name"].astype(str).nunique()) if not package_attempts.empty else 0
    fetch_ok_count = int(attempts["attempt_status"].eq("FETCH_OK").sum()) if not attempts.empty else 0
    fetch_error_count = int(attempts["attempt_status"].isin(["FETCH_ERROR", "IMPORT_ERROR"]).sum()) if not attempts.empty else 0
    independent_matches = consensus[consensus["comparison_status"].eq("INDEPENDENT_MATCH")] if not consensus.empty else pd.DataFrame()
    independent_families = sorted(independent_matches["source_family"].astype(str).unique().tolist()) if not independent_matches.empty else []
    tickers_with_match = int(independent_matches["ticker"].astype(str).nunique()) if not independent_matches.empty else 0
    manual_review_count = int(len(manual_review))
    schema_errors = _output_schema_errors(attempts, observations, consensus, manual_review)
    network_disabled_for_v2 = not network_allowed
    no_runtime_provider_rows = network_allowed and provider_runtime_count == 0 and not config_errors and not primary_errors
    critical_fail_count = (
        len(config_errors)
        + len(primary_errors)
        + len(schema_errors)
        + int(pilot_ticker_count != expected_count)
        + int(core_outputs_modified)
        + len(forbidden_hits)
        + int(network_disabled_for_v2)
        + int(no_runtime_provider_rows)
    )
    pass_min = int(((config.get("comparison") or {}).get("pass_min_independent_match_tickers", 15) or 15))
    if critical_fail_count:
        final_decision = "NO_GO_FIX_PROVIDER_PROBE"
        allowed_next_step = "Fix 04D-V2 provider probe only"
    elif independent_families and tickers_with_match >= pass_min:
        final_decision = "PASS_FOR_CONFIDENCE_UPGRADE_REVIEW"
        allowed_next_step = "Review market confidence upgrade evidence only; keep finance confidence unchanged"
    else:
        final_decision = "CONDITIONAL_GO_PRIMARY_ONLY_CONFIDENCE"
        allowed_next_step = "Continue with explicit PROVISIONAL_PRIMARY_ONLY market confidence warning"
    if final_decision not in DECISION_VALUES:
        raise ValueError(f"Invalid 04D-V2 decision: {final_decision}")
    return {
        "task": "PROVISIONAL-ALT-SOURCE-04D-V2",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "ticker_source_path": ticker_source_path,
        "pilot_ticker_count": pilot_ticker_count,
        "expected_pilot_ticker_count": expected_count,
        "network_allowed": network_allowed,
        "network_used": network_used,
        "provider_runtime_count": provider_runtime_count,
        "provider_importable_count": provider_importable_count,
        "provider_not_importable_count": provider_not_importable_count,
        "fetch_ok_count": fetch_ok_count,
        "fetch_error_count": fetch_error_count,
        "independent_current_source_family_count": int(len(independent_families)),
        "independent_current_source_families": independent_families,
        "tickers_with_independent_match_count": tickers_with_match,
        "manual_review_count": manual_review_count,
        "critical_fail_count": critical_fail_count,
        "core_outputs_modified": core_outputs_modified,
        "config_errors": config_errors,
        "primary_errors": primary_errors,
        "schema_errors": schema_errors,
        "forbidden_terms_found": forbidden_hits,
        "safety_context_terms": safety_context_terms,
        "final_decision": final_decision,
        "allowed_next_step": allowed_next_step,
        "not_authorized": [
            "production_step19",
            "step19_output_mutation",
            "top500_refresh",
            "full_universe_live_fetch",
            "REAL-DATA-02-rerun",
            "official_pdf_fetch",
            "OCR",
            "finance_fetch",
            "valuation",
            "target_price",
            "buy_sell_hold_recommendation",
        ],
    }


def build_summary(decision: dict[str, Any], attempts: pd.DataFrame) -> str:
    imported = _providers_by_status(attempts, {"FETCH_OK", "FETCH_EMPTY", "FETCH_ERROR", "UNSUPPORTED_PROVIDER"})
    failed = _provider_failure_summary(attempts)
    can_upgrade = decision.get("final_decision") == "PASS_FOR_CONFIDENCE_UPGRADE_REVIEW"
    remains_primary_only = not can_upgrade
    lines = [
        "# PROVISIONAL-ALT-SOURCE-04D-V2 Network Probe Summary",
        "",
        f"- generated_at: {decision.get('generated_at', '')}",
        f"- network_allowed: {decision.get('network_allowed', False)}",
        f"- network_used: {decision.get('network_used', False)}",
        f"- provider_runtime_count: {decision.get('provider_runtime_count', 0)}",
        f"- provider_importable_count: {decision.get('provider_importable_count', 0)}",
        f"- provider_not_importable_count: {decision.get('provider_not_importable_count', 0)}",
        f"- fetch_ok_count: {decision.get('fetch_ok_count', 0)}",
        f"- independent_current_source_family_count: {decision.get('independent_current_source_family_count', 0)}",
        f"- tickers_with_independent_match_count: {decision.get('tickers_with_independent_match_count', 0)}",
        f"- manual_review_count: {decision.get('manual_review_count', 0)}",
        f"- core_outputs_modified: {decision.get('core_outputs_modified', False)}",
        f"- final_decision: {decision.get('final_decision', '')}",
        "",
        "## Provider Import Result",
        f"- imported_successfully: {', '.join(imported) if imported else 'none'}",
        f"- failed_or_unavailable: {failed if failed else 'none'}",
        "",
        "## Market Confidence Result",
        f"- market_confidence_can_be_upgraded: {can_upgrade}",
        f"- pipeline_should_remain_PROVISIONAL_PRIMARY_ONLY: {remains_primary_only}",
        "",
        "## Scope",
        "- Diagnostic market-source probe only for the existing 20 pilot tickers.",
        "- Finance confidence is unchanged and no finance statements were fetched.",
        "- Static historical fallback and raw cache rows cannot create independent current confirmation.",
        "",
        "## Not authorized",
        "- not_authorized: production Step19",
        "- not_authorized: Step19 output mutation",
        "- not_authorized: top500 refresh",
        "- not_authorized: full universe fetch",
        "- not_authorized: REAL-DATA-02 rerun",
        "- not_authorized: official PDF fetch",
        "- not_authorized: OCR",
        "- not_authorized: valuation",
        "- not_authorized: buy/sell/hold recommendation",
        "",
        "## Allowed Next Step",
        f"- {decision.get('allowed_next_step', '')}",
    ]
    return "\n".join(lines) + "\n"


def scan_forbidden_terms(output_dir: Path) -> dict[str, list[str]]:
    actionable_hits: list[str] = []
    safety_context_terms: list[str] = []
    for path in sorted(output_dir.glob("*")):
        if path.suffix.lower() not in {".csv", ".json", ".md", ".txt"}:
            continue
        text = _scan_text(path)
        for line_no, line in enumerate(text.splitlines(), start=1):
            lower = line.lower()
            for term in FORBIDDEN_TERMS:
                if term in lower:
                    hit = f"{path.name}:{line_no}:{term}"
                    if any(marker in lower for marker in SAFETY_CONTEXT_MARKERS):
                        safety_context_terms.append(hit)
                    else:
                        actionable_hits.append(hit)
    return {"actionable_hits": actionable_hits, "safety_context_terms": safety_context_terms}


def _compare_observation(primary: dict[str, Any], obs: pd.Series, candidate_independent: bool, primary_family: str, config: dict[str, Any]) -> dict[str, Any]:
    observation_status = str(obs.get("observation_status", ""))
    source_family = str(obs.get("source_family", ""))
    raw_or_adjusted = str(obs.get("raw_or_adjusted_price", "")).lower()
    if observation_status == "NETWORK_DISABLED":
        return _comparison("NETWORK_DISABLED_NO_CONFIDENCE", "NO_CONFIDENCE_UPGRADE")
    if observation_status == "HISTORICAL_FALLBACK_ONLY" or source_family == "static_github_historical":
        return _comparison("HISTORICAL_FALLBACK_ONLY", "NO_CONFIDENCE_UPGRADE")
    if observation_status == "FETCH_ERROR":
        return _comparison("FETCH_ERROR_NO_CONFIDENCE", "NO_CONFIDENCE_UPGRADE")
    if observation_status == "RAW_CACHE_ONLY" or raw_or_adjusted == "raw_cache":
        return _comparison("RAW_CACHE_NO_CONFIDENCE", "NO_CONFIDENCE_UPGRADE")
    if observation_status != "PROVIDER_OBSERVATION":
        return _comparison("NO_PROVIDER_OBSERVATION", "NO_CONFIDENCE_UPGRADE")
    if source_family == primary_family or not candidate_independent:
        return _comparison("NOT_INDEPENDENT_SAME_SOURCE_FAMILY", "NO_CONFIDENCE_UPGRADE")
    if str(obs.get("raw_adjustment_status", "")) == "ADJUSTED_OR_UNKNOWN":
        return _comparison("ADJUSTED_PRICE_NOT_COMPARABLE", "NO_CONFIDENCE_UPGRADE", manual=True)
    gap = _date_gap_days(primary.get("last_price_date"), obs.get("provider_last_price_date"))
    price_abs = _abs_diff(primary.get("last_close"), obs.get("provider_last_close"))
    price_pct = _pct_diff(primary.get("last_close"), obs.get("provider_last_close"))
    current = gap is not None and abs(gap) <= int(((config.get("comparison") or {}).get("max_current_reference_gap_days", 5) or 5))
    if not current:
        return _comparison("REFERENCE_STALE_NO_CONFIDENCE", "NO_CONFIDENCE_UPGRADE", gap, price_abs, price_pct, False, True)
    price_threshold = float(((config.get("comparison") or {}).get("max_price_pct_diff_for_match", 0.03) or 0.03))
    if price_pct is not None and abs(price_pct) > price_threshold:
        return _comparison("MANUAL_REVIEW_MISMATCH", "NO_CONFIDENCE_UPGRADE", gap, price_abs, price_pct, current, True)
    return _comparison("INDEPENDENT_MATCH", "MARKET_CONFIDENCE_UPGRADE_REVIEW_CANDIDATE", gap, price_abs, price_pct, current, False)


def _comparison(status: str, contribution: str, gap: Any = "", price_abs: Any = "", price_pct: Any = "", current: bool = False, manual: bool = False) -> dict[str, Any]:
    return {
        "price_date_gap_days": "" if gap is None else gap,
        "price_abs_diff": "" if price_abs is None else price_abs,
        "price_pct_diff": "" if price_pct is None else price_pct,
        "provider_is_current_enough": bool(current),
        "comparison_status": status,
        "confidence_contribution": contribution,
        "manual_review_flag": bool(manual),
    }


def _apply_overrides(config: dict[str, Any], *, allow_network: bool | None, allow_partial: bool | None, max_requests: int | None, sleep_seconds: float | None) -> None:
    run_policy = config.setdefault("run_policy", {})
    if allow_network is not None:
        run_policy["allow_network"] = bool(allow_network)
    if allow_partial is not None:
        run_policy["allow_partial"] = bool(allow_partial)
    if max_requests is not None:
        run_policy["max_requests"] = int(max_requests)
    if sleep_seconds is not None:
        run_policy["sleep_seconds"] = float(sleep_seconds)


def _primary_schema_errors(primary_path: Path, primary: pd.DataFrame, tickers: list[str], config: dict[str, Any]) -> list[str]:
    errors = []
    if not primary_path.exists():
        return [f"primary snapshot missing: {primary_path}"]
    required = ["ticker", "last_price_date", "last_close", "avg_volume_20d", "avg_volume_60d", "trading_days_60d"]
    missing = [column for column in required if column not in primary.columns]
    if missing:
        errors.append(f"primary snapshot missing columns: {','.join(missing)}")
    expected = int(((config.get("run_policy") or {}).get("expected_pilot_ticker_count", 20) or 20))
    if len(tickers) != expected:
        errors.append(f"pilot ticker count must be {expected}, got {len(tickers)}")
    return errors


def _providers(config: dict[str, Any]) -> list[dict[str, Any]]:
    providers = config.get("providers", [])
    return [provider for provider in providers if isinstance(provider, dict)] if isinstance(providers, list) else []


def _enabled_families(provider: dict[str, Any]) -> list[dict[str, Any]]:
    families = provider.get("source_families", [])
    return [family for family in families if isinstance(family, dict) and family.get("default_enabled", True)] if isinstance(families, list) else []


def _family_rules(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rules: dict[str, dict[str, Any]] = {}
    for provider in _providers(config):
        provider_name = str(provider.get("provider_name", ""))
        for family in _enabled_families(provider):
            row = dict(family)
            row["provider_name"] = provider_name
            rules[str(family.get("source_family", ""))] = row
    return rules


def _default_fetcher(provider_name: str, module: Any) -> ProviderFetcher | None:
    if provider_name == "vnquant":
        return lambda **kwargs: _fetch_vnquant(module=module, **kwargs)
    if provider_name == "vietfin":
        return lambda **kwargs: _fetch_vietfin(module=module, **kwargs)
    return None


def _fetch_vnquant(*, module: Any, ticker: str, source_family: str, family_config: dict[str, Any], cache_dir: Path, request_count: int) -> dict[str, Any]:
    loader_cls = _vnquant_loader(module)
    if loader_cls is None:
        raise RuntimeError("vnquant DataLoader interface was not detected")
    end_date = datetime.now(UTC).date()
    start_date = end_date - timedelta(days=120)
    loader = loader_cls(symbols=ticker, start=start_date.isoformat(), end=end_date.isoformat(), data_source=family_config.get("data_source", "cafe"), minimal=True)
    frame = loader.download()
    cache_path = _write_cache(frame, cache_dir, "vnquant", source_family, ticker)
    normalized = _normalize_frame(frame, cache_path=cache_path)
    normalized["network_used"] = True
    return normalized


def _fetch_vietfin(*, module: Any, ticker: str, source_family: str, family_config: dict[str, Any], cache_dir: Path, request_count: int) -> dict[str, Any]:
    for name in ["fetch_ohlcv", "get_ohlcv", "history", "historical"]:
        candidate = getattr(module, name, None)
        if callable(candidate):
            frame = candidate(ticker)
            cache_path = _write_cache(frame, cache_dir, "vietfin", source_family, ticker)
            normalized = _normalize_frame(frame, cache_path=cache_path)
            normalized["network_used"] = True
            return normalized
    raise RuntimeError("vietfin supported OHLCV/history interface was not detected")


def _normalize_provider_payload(raw: Any, *, ticker: str, provider_name: str, source_family: str, endpoint_family: str, cache_dir: Path) -> tuple[dict[str, Any], bool]:
    normalized: dict[str, Any]
    if isinstance(raw, pd.DataFrame):
        cache_path = _write_cache(raw, cache_dir, provider_name, source_family, ticker)
        normalized = _normalize_frame(raw, cache_path=cache_path)
    elif isinstance(raw, list):
        normalized = raw[0] if raw and isinstance(raw[0], dict) else {}
    elif isinstance(raw, dict):
        normalized = raw
    else:
        normalized = {}
    network_used = bool(normalized.get("network_used", True))
    price_basis = str(normalized.get("price_basis", normalized.get("raw_or_adjusted_price", "unknown")) or "unknown")
    raw_adjustment_status = normalized.get("raw_adjustment_status", "ADJUSTED_OR_UNKNOWN" if price_basis == "adjusted" else "UNADJUSTED_OR_RAW")
    if price_basis == "raw_cache" or normalized.get("cache_only") is True:
        status = "RAW_CACHE_ONLY"
    elif _missing(normalized.get("last_price_date")) or _missing(normalized.get("last_close")):
        status = "FETCH_EMPTY"
    else:
        status = "PROVIDER_OBSERVATION"
    return (
        _observation(
            ticker,
            provider_name,
            source_family,
            status,
            provider_last_price_date=normalized.get("last_price_date", ""),
            provider_last_close=normalized.get("last_close", ""),
            provider_avg_volume_20d=normalized.get("avg_volume_20d", ""),
            provider_avg_volume_60d=normalized.get("avg_volume_60d", ""),
            provider_trading_days_60d=normalized.get("trading_days_60d", ""),
            raw_adjustment_status=raw_adjustment_status,
            raw_or_adjusted_price=price_basis,
            source_url_or_endpoint_family=endpoint_family,
        ),
        network_used,
    )


def _attempt(
    provider_name: str,
    source_family: str,
    ticker: str,
    status: str,
    network_allowed: bool,
    network_used: bool,
    optional_install_used: bool,
    request_count: int,
    error_type: str = "",
    error_message: str = "",
    elapsed_seconds: float = 0,
) -> dict[str, Any]:
    return {
        "provider_name": provider_name,
        "source_family": source_family,
        "ticker": str(ticker).strip().upper(),
        "attempt_status": status,
        "network_allowed": bool(network_allowed),
        "network_used": bool(network_used),
        "optional_install_used": bool(optional_install_used),
        "request_count": int(request_count),
        "error_type": error_type,
        "error_message": error_message,
        "attempted_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "elapsed_seconds": round(float(elapsed_seconds), 6),
    }


def _observation(
    ticker: str,
    provider_name: str,
    source_family: str,
    observation_status: str,
    *,
    provider_last_price_date: Any = "",
    provider_last_close: Any = "",
    provider_avg_volume_20d: Any = "",
    provider_avg_volume_60d: Any = "",
    provider_trading_days_60d: Any = "",
    raw_adjustment_status: str = "",
    raw_or_adjusted_price: str = "",
    source_url_or_endpoint_family: str = "",
) -> dict[str, Any]:
    return {
        "ticker": str(ticker).strip().upper(),
        "provider_name": provider_name,
        "source_family": source_family,
        "provider_last_price_date": _date_label(provider_last_price_date),
        "provider_last_close": provider_last_close,
        "provider_avg_volume_20d": provider_avg_volume_20d,
        "provider_avg_volume_60d": provider_avg_volume_60d,
        "provider_trading_days_60d": provider_trading_days_60d,
        "raw_adjustment_status": raw_adjustment_status,
        "raw_or_adjusted_price": raw_or_adjusted_price,
        "observation_status": observation_status,
        "source_url_or_endpoint_family": source_url_or_endpoint_family,
    }


def _output_schema_errors(attempts: pd.DataFrame, observations: pd.DataFrame, consensus: pd.DataFrame, manual: pd.DataFrame) -> list[str]:
    checks = [
        ("provider_network_attempt_log", attempts, ATTEMPT_LOG_COLUMNS),
        ("provider_market_observations", observations, OBSERVATION_COLUMNS),
        ("source_family_consensus_20", consensus, CONSENSUS_COLUMNS),
        ("manual_review_cases", manual, CONSENSUS_COLUMNS),
    ]
    errors = []
    for name, frame, columns in checks:
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            errors.append(f"{name} missing columns: {','.join(missing)}")
    return errors


def _write_outputs(output: Path, attempts: pd.DataFrame, observations: pd.DataFrame, consensus: pd.DataFrame, manual: pd.DataFrame, decision: dict[str, Any]) -> None:
    attempts.to_csv(output / "provider_network_attempt_log.csv", index=False)
    observations.to_csv(output / "provider_market_observations.csv", index=False)
    consensus.to_csv(output / "source_family_consensus_20.csv", index=False)
    manual.to_csv(output / "manual_review_cases.csv", index=False)
    (output / "provider_network_probe_summary.md").write_text(build_summary(decision, attempts), encoding="utf-8")
    (output / "provider_network_probe_decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")


def _providers_by_status(attempts: pd.DataFrame, statuses: set[str]) -> list[str]:
    if attempts.empty:
        return []
    rows = attempts[attempts["attempt_status"].isin(statuses) & ~attempts["provider_name"].eq("vnstock_market_data")]
    return sorted(rows["provider_name"].astype(str).unique().tolist())


def _provider_failure_summary(attempts: pd.DataFrame) -> str:
    if attempts.empty:
        return ""
    failed = attempts[attempts["attempt_status"].isin(["NOT_IMPORTABLE", "IMPORT_ERROR", "FETCH_ERROR", "UNSUPPORTED_PROVIDER"])]
    if failed.empty:
        return ""
    parts = []
    for provider_name, group in failed.groupby("provider_name"):
        statuses = ",".join(sorted(group["attempt_status"].astype(str).unique().tolist()))
        errors = ",".join(sorted(error for error in group["error_type"].astype(str).unique().tolist() if error))
        parts.append(f"{provider_name}({statuses}{'; ' + errors if errors else ''})")
    return "; ".join(parts)


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
        data.pop("forbidden_terms_found", None)
        data.pop("safety_context_terms", None)
    return json.dumps(data, ensure_ascii=False, indent=2)
