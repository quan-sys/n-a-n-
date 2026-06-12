"""Controlled 04D network probe for alternative market providers."""

from __future__ import annotations

import hashlib
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


ATTEMPT_LOG_COLUMNS = [
    "provider_name",
    "source_family",
    "ticker",
    "attempt_status",
    "network_used",
    "optional_install_used",
    "request_count",
    "error_type",
    "error_message",
    "attempted_at",
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
    "PASS_FOR_MARKET_CONFIDENCE_UPGRADE_AND_SCALE_DECISION",
    "CONDITIONAL_GO_FOR_SCALE_DECISION_WITH_PRIMARY_ONLY_MARKET_CONFIDENCE",
    "NO_GO_FIX_PROVIDER_PROBE_BEFORE_ANY_SCALE",
}

FORBIDDEN_TERMS = [
    "buy",
    "sell",
    "hold",
    "target price",
    "fair value",
    "margin of safety",
    "recommendation",
    "entry signal",
    "exit signal",
    "portfolio weight",
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
class NetworkProbe04DResult:
    provider_network_attempt_log: pd.DataFrame
    alternative_market_observations: pd.DataFrame
    source_family_current_consensus: pd.DataFrame
    manual_review_cases: pd.DataFrame
    decision: dict[str, Any]


ProviderFetcher = Callable[..., list[dict[str, Any]]]


def load_network_probe_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("04D network probe config must be a mapping.")
    return data


def run_network_probe_04d(
    *,
    config_path: str | Path,
    output_dir: str | Path,
    cache_dir: str | Path,
    allow_network: bool | None = None,
    allow_optional_install: bool | None = None,
    allow_partial: bool | None = None,
    max_requests: int | None = None,
    sleep_seconds: float | None = None,
    core_output_paths: list[str | Path] | None = None,
    import_module_func: Callable[[str], Any] | None = None,
    find_spec_func: Callable[[str], Any] | None = None,
    provider_fetchers: dict[str, ProviderFetcher] | None = None,
    optional_install_func: Callable[[str, Path], tuple[bool, str]] | None = None,
) -> NetworkProbe04DResult:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    config = load_network_probe_config(config_path)
    _apply_overrides(config, allow_network=allow_network, allow_optional_install=allow_optional_install, allow_partial=allow_partial, max_requests=max_requests, sleep_seconds=sleep_seconds)
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
        return NetworkProbe04DResult(attempts, observations, consensus, manual, decision)

    attempts, observations = build_provider_network_outputs(
        config=config,
        tickers=tickers,
        cache_dir=cache,
        import_module_func=import_module_func,
        find_spec_func=find_spec_func,
        provider_fetchers=provider_fetchers or {},
        optional_install_func=optional_install_func,
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
        config_errors=[],
        primary_errors=[],
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
        config_errors=[],
        primary_errors=[],
        forbidden_hits=forbidden["actionable_hits"],
        safety_context_terms=forbidden["safety_context_terms"],
        ticker_source_path=ticker_source_path,
    )
    _write_outputs(output, attempts, observations, consensus, manual, decision)
    return NetworkProbe04DResult(attempts, observations, consensus, manual, decision)


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
    if int(((config.get("run_policy") or {}).get("expected_pilot_ticker_count", 0) or 0)) != 20:
        errors.append("run_policy.expected_pilot_ticker_count must be 20")
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
    optional_install_func: Callable[[str, Path], tuple[bool, str]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    run_policy = config.get("run_policy") or {}
    allow_network = bool(run_policy.get("allow_network", False))
    allow_optional_install = bool(run_policy.get("allow_optional_install", False))
    allow_partial = bool(run_policy.get("allow_partial", False))
    max_requests = int(run_policy.get("max_requests", 40) or 40)
    sleep_seconds = float(run_policy.get("sleep_seconds", 0) or 0)
    find_spec_func = find_spec_func or importlib.util.find_spec
    import_module_func = import_module_func or importlib.import_module
    optional_install_func = optional_install_func or _default_optional_install
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
                    attempts.append(_attempt(provider_name, family["source_family"], ticker, "PROVIDER_NOT_SUPPORTED", False, False, request_count, "HistoricalFallbackOnly", "Static historical fallback is not current confirmation."))
                    observations.append(_observation(ticker, provider_name, family["source_family"], "HISTORICAL_FALLBACK_ONLY", source_url_or_endpoint_family=family.get("source_url_or_endpoint_family", "")))
            continue
        if not allow_network:
            for family in families:
                for ticker in tickers:
                    attempts.append(_attempt(provider_name, family["source_family"], ticker, "NETWORK_DISABLED", False, False, request_count))
                    observations.append(_observation(ticker, provider_name, family["source_family"], "FETCH_SKIPPED_NETWORK_DISABLED", source_url_or_endpoint_family=family.get("source_url_or_endpoint_family", "")))
            continue
        if package_name and find_spec_func(str(package_name)) is None:
            if allow_optional_install:
                install_ok, install_message = optional_install_func(str(package_name), cache_dir / "_optional_install")
                attempts.append(_attempt(provider_name, "", "", "INSTALL_SKIPPED" if not install_ok else "INSTALL_FAILED", False, False, request_count, "OptionalInstallNotPerformed" if not install_ok else "InstallFailed", install_message, optional_install_used=False))
            for family in families:
                for ticker in tickers:
                    attempts.append(_attempt(provider_name, family["source_family"], ticker, "IMPORT_ERROR", False, False, request_count, "NOT_IMPORTABLE", f"Package {package_name} is not importable."))
                    observations.append(_observation(ticker, provider_name, family["source_family"], "NO_PROVIDER_OBSERVATION", source_url_or_endpoint_family=family.get("source_url_or_endpoint_family", "")))
            if not allow_partial:
                continue
            continue
        try:
            module = import_module_func(str(package_name)) if package_name else None
        except Exception as exc:  # noqa: BLE001
            for family in families:
                for ticker in tickers:
                    attempts.append(_attempt(provider_name, family["source_family"], ticker, "IMPORT_ERROR", False, False, request_count, type(exc).__name__, str(exc)))
                    observations.append(_observation(ticker, provider_name, family["source_family"], "NO_PROVIDER_OBSERVATION", source_url_or_endpoint_family=family.get("source_url_or_endpoint_family", "")))
            if not allow_partial:
                continue
            continue
        fetcher = provider_fetchers.get(provider_name) or _default_fetcher(provider_name, module)
        if fetcher is None:
            for family in families:
                for ticker in tickers:
                    attempts.append(_attempt(provider_name, family["source_family"], ticker, "PROVIDER_NOT_SUPPORTED", False, False, request_count, "NoSupportedFetcher", "No supported 04D fetch interface was detected."))
                    observations.append(_observation(ticker, provider_name, family["source_family"], "NO_PROVIDER_OBSERVATION", source_url_or_endpoint_family=family.get("source_url_or_endpoint_family", "")))
            continue
        for family in families:
            source_family = str(family.get("source_family", ""))
            for ticker in tickers:
                if request_count >= max_requests:
                    attempts.append(_attempt(provider_name, source_family, ticker, "REQUEST_BUDGET_EXHAUSTED", False, False, request_count, "RequestBudgetExhausted", "04D request budget exhausted."))
                    observations.append(_observation(ticker, provider_name, source_family, "NO_PROVIDER_OBSERVATION", source_url_or_endpoint_family=family.get("source_url_or_endpoint_family", "")))
                    continue
                request_count += 1
                try:
                    raw = fetcher(ticker=ticker, source_family=source_family, family_config=family, cache_dir=cache_dir, request_count=request_count)
                    normalized = _normalize_provider_payload(raw, ticker=ticker, provider_name=provider_name, source_family=source_family, endpoint_family=str(family.get("source_url_or_endpoint_family", "")))
                    attempts.append(_attempt(provider_name, source_family, ticker, "FETCH_OK" if normalized.get("observation_status") == "PROVIDER_OBSERVATION" else "FETCH_EMPTY", True, False, request_count))
                    observations.append(normalized)
                except Exception as exc:  # noqa: BLE001
                    attempts.append(_attempt(provider_name, source_family, ticker, "FETCH_ERROR", True, False, request_count, type(exc).__name__, str(exc)))
                    observations.append(_observation(ticker, provider_name, source_family, "NO_PROVIDER_OBSERVATION", source_url_or_endpoint_family=family.get("source_url_or_endpoint_family", "")))
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
        provider_name = str(obs.get("provider_name", ""))
        candidate_independent = bool(provider_family_rules.get(source_family, {}).get("candidate_independent_from_primary", False))
        comparison = _compare_observation(primary, obs, candidate_independent, primary_family, config)
        rows.append(
            {
                "ticker": ticker,
                "primary_source_family": primary_family,
                "primary_last_price_date": primary.get("last_price_date", ""),
                "primary_last_close": primary.get("last_close", ""),
                "source_family": source_family,
                "provider_name": provider_name,
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
    expected_count = int(((config.get("run_policy") or {}).get("expected_pilot_ticker_count", 20) or 20))
    network_used = bool(attempts["network_used"].map(_as_bool).any()) if not attempts.empty else False
    optional_install_used = bool(attempts["optional_install_used"].map(_as_bool).any()) if not attempts.empty else False
    attempted = attempts[attempts["attempt_status"].isin(["FETCH_OK", "FETCH_EMPTY", "FETCH_ERROR"])] if not attempts.empty else pd.DataFrame()
    fetch_ok = attempts[attempts["attempt_status"].eq("FETCH_OK")] if not attempts.empty else pd.DataFrame()
    independent_matches = consensus[consensus["comparison_status"].eq("INDEPENDENT_CURRENT_MATCH")] if not consensus.empty else pd.DataFrame()
    independent_mismatches = consensus[consensus["comparison_status"].eq("INDEPENDENT_CURRENT_PRICE_MISMATCH")] if not consensus.empty else pd.DataFrame()
    independent_families = sorted(independent_matches["source_family"].astype(str).unique().tolist()) if not independent_matches.empty else []
    tickers_with_match = int(independent_matches["ticker"].astype(str).nunique()) if not independent_matches.empty else 0
    tickers_with_mismatch = int(independent_mismatches["ticker"].astype(str).nunique()) if not independent_mismatches.empty else 0
    manual_review_count = int(len(manual_review))
    schema_errors = _output_schema_errors(attempts, observations, consensus, manual_review)
    severe_manual = manual_review_count > 10 or tickers_with_mismatch > 5
    critical_fail_count = (
        len(config_errors)
        + len(primary_errors)
        + len(schema_errors)
        + int(pilot_ticker_count != expected_count)
        + int(core_outputs_modified)
        + len(forbidden_hits)
        + int(severe_manual)
    )
    pass_min = int(((config.get("comparison") or {}).get("pass_min_independent_match_tickers", 15) or 15))
    if critical_fail_count:
        final_decision = "NO_GO_FIX_PROVIDER_PROBE_BEFORE_ANY_SCALE"
        allowed_next_step = "Fix 04D issues only"
    elif independent_families and tickers_with_match >= pass_min:
        final_decision = "PASS_FOR_MARKET_CONFIDENCE_UPGRADE_AND_SCALE_DECISION"
        allowed_next_step = "SCALE-DECISION-05A or STEP19-SHADOW-RERUN-WITH-UPGRADED-MARKET-CONFIDENCE"
    else:
        final_decision = "CONDITIONAL_GO_FOR_SCALE_DECISION_WITH_PRIMARY_ONLY_MARKET_CONFIDENCE"
        allowed_next_step = "SCALE-DECISION-05A with explicit primary-only warning"
    if final_decision not in DECISION_VALUES:
        raise ValueError(f"Invalid 04D decision: {final_decision}")
    return {
        "task": "PROVISIONAL-ALT-SOURCE-04D",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "ticker_source_path": ticker_source_path,
        "pilot_ticker_count": pilot_ticker_count,
        "expected_pilot_ticker_count": expected_count,
        "network_used": network_used,
        "optional_install_used": optional_install_used,
        "provider_count_attempted": int(attempted["provider_name"].nunique()) if not attempted.empty else 0,
        "provider_count_fetch_ok": int(fetch_ok["provider_name"].nunique()) if not fetch_ok.empty else 0,
        "independent_current_source_family_count": int(len(independent_families)),
        "independent_current_source_families": independent_families,
        "tickers_with_independent_match_count": tickers_with_match,
        "tickers_with_independent_mismatch_count": tickers_with_mismatch,
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
            "top500_refresh",
            "full_universe_live_fetch",
            "REAL-DATA-02-rerun",
            "official_pdf_fetch",
            "OCR",
            "valuation",
            "target_price",
            "buy_sell_hold_recommendation",
        ],
    }


def build_summary(decision: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# PROVISIONAL-ALT-SOURCE-04D Network Probe Summary",
            "",
            f"- generated_at: {decision.get('generated_at', '')}",
            f"- pilot_ticker_count: {decision.get('pilot_ticker_count', 0)}",
            f"- network_used: {decision.get('network_used', False)}",
            f"- optional_install_used: {decision.get('optional_install_used', False)}",
            f"- provider_count_attempted: {decision.get('provider_count_attempted', 0)}",
            f"- provider_count_fetch_ok: {decision.get('provider_count_fetch_ok', 0)}",
            f"- independent_current_source_family_count: {decision.get('independent_current_source_family_count', 0)}",
            f"- tickers_with_independent_match_count: {decision.get('tickers_with_independent_match_count', 0)}",
            f"- tickers_with_independent_mismatch_count: {decision.get('tickers_with_independent_mismatch_count', 0)}",
            f"- manual_review_count: {decision.get('manual_review_count', 0)}",
            f"- critical_fail_count: {decision.get('critical_fail_count', 0)}",
            f"- core_outputs_modified: {decision.get('core_outputs_modified', False)}",
            f"- final_decision: {decision.get('final_decision', '')}",
            "",
            "## Interpretation",
            "- This is only a controlled provider network probe for the existing 20 pilot tickers.",
            "- It can improve market source-family confidence only if independent current observations match primary data.",
            "- It does not change finance confidence and does not fetch finance statements.",
            "- Static historical fallback and same-source-family rows do not count as current independent confirmation.",
            "",
            "## Not authorized",
            "- not_authorized: production Step19",
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
    ) + "\n"


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


def _apply_overrides(config: dict[str, Any], *, allow_network: bool | None, allow_optional_install: bool | None, allow_partial: bool | None, max_requests: int | None, sleep_seconds: float | None) -> None:
    run_policy = config.setdefault("run_policy", {})
    if allow_network is not None:
        run_policy["allow_network"] = bool(allow_network)
    if allow_optional_install is not None:
        run_policy["allow_optional_install"] = bool(allow_optional_install)
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


def _default_optional_install(package_name: str, target_dir: Path) -> tuple[bool, str]:
    target_dir.mkdir(parents=True, exist_ok=True)
    return False, f"Isolated optional install for {package_name} was not performed; 04D keeps dependency files and base environment unchanged."


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
    return _normalize_frame(frame, cache_path=cache_path)


def _fetch_vietfin(*, module: Any, ticker: str, source_family: str, family_config: dict[str, Any], cache_dir: Path, request_count: int) -> dict[str, Any]:
    for name in ["fetch_ohlcv", "get_ohlcv", "history", "historical"]:
        candidate = getattr(module, name, None)
        if callable(candidate):
            frame = candidate(ticker)
            cache_path = _write_cache(frame, cache_dir, "vietfin", source_family, ticker)
            return _normalize_frame(frame, cache_path=cache_path)
    raise RuntimeError("vietfin supported OHLCV/history interface was not detected")


def _vnquant_loader(module: Any) -> Any:
    loader = getattr(module, "DataLoader", None)
    if hasattr(loader, "DataLoader"):
        return loader.DataLoader
    if callable(loader):
        return loader
    try:
        data_loader_module = importlib.import_module("vnquant.DataLoader")
    except Exception:  # noqa: BLE001
        return None
    return getattr(data_loader_module, "DataLoader", None)


def _normalize_provider_payload(raw: Any, *, ticker: str, provider_name: str, source_family: str, endpoint_family: str) -> dict[str, Any]:
    normalized = raw if isinstance(raw, dict) else {}
    status = "PROVIDER_OBSERVATION" if _not_missing(normalized.get("last_price_date")) and _not_missing(normalized.get("last_close")) else "FETCH_EMPTY"
    return _observation(
        ticker,
        provider_name,
        source_family,
        status,
        provider_last_price_date=normalized.get("last_price_date", ""),
        provider_last_close=normalized.get("last_close", ""),
        provider_avg_volume_20d=normalized.get("avg_volume_20d", ""),
        provider_avg_volume_60d=normalized.get("avg_volume_60d", ""),
        provider_trading_days_60d=normalized.get("trading_days_60d", ""),
        raw_adjustment_status=normalized.get("raw_adjustment_status", "ADJUSTED_OR_UNKNOWN" if normalized.get("price_basis") == "adjusted" else "UNADJUSTED_OR_RAW"),
        raw_or_adjusted_price=normalized.get("price_basis", "unknown"),
        source_url_or_endpoint_family=endpoint_family,
    )


def _normalize_frame(frame: Any, *, cache_path: str) -> dict[str, Any]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return {"raw_cache_path": cache_path}
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = ["_".join(str(part) for part in column if str(part)) for column in data.columns]
    if isinstance(data.index, pd.DatetimeIndex):
        data = data.reset_index().rename(columns={"index": "date"})
    date_col = _first_column(data, ["date", "time", "trading_date"])
    close_col = _first_column(data, ["close", "close_price"])
    adjusted_col = _first_column(data, ["adjusted_close", "adj_close", "adjust"])
    volume_col = _first_column(data, ["volume", "vol", "match_volume"])
    price_basis = "unadjusted"
    if not close_col and adjusted_col:
        close_col = adjusted_col
        price_basis = "adjusted"
    if not date_col or not close_col:
        return {"raw_cache_path": cache_path}
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(data[date_col], errors="coerce"),
            "close": pd.to_numeric(data[close_col], errors="coerce"),
            "volume": pd.to_numeric(data[volume_col], errors="coerce") if volume_col else pd.Series(dtype=float),
        }
    ).dropna(subset=["date", "close"]).sort_values("date")
    if out.empty:
        return {"raw_cache_path": cache_path}
    volumes = pd.to_numeric(out["volume"], errors="coerce").dropna()
    return {
        "last_price_date": out.iloc[-1]["date"].date().isoformat(),
        "last_close": float(out.iloc[-1]["close"]),
        "avg_volume_20d": round(float(volumes.tail(20).mean()), 4) if not volumes.empty else "",
        "avg_volume_60d": round(float(volumes.tail(60).mean()), 4) if not volumes.empty else "",
        "trading_days_60d": int(min(len(volumes), 60)),
        "price_basis": price_basis,
        "raw_cache_path": cache_path,
    }


def _compare_observation(primary: dict[str, Any], obs: pd.Series, candidate_independent: bool, primary_family: str, config: dict[str, Any]) -> dict[str, Any]:
    observation_status = str(obs.get("observation_status", ""))
    source_family = str(obs.get("source_family", ""))
    if observation_status == "FETCH_SKIPPED_NETWORK_DISABLED":
        return _comparison("FETCH_SKIPPED_NETWORK_DISABLED", "NO_CONFIDENCE_UPGRADE")
    if observation_status == "HISTORICAL_FALLBACK_ONLY" or source_family == "static_github_historical":
        return _comparison("HISTORICAL_FALLBACK_ONLY", "NO_CONFIDENCE_UPGRADE")
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
        return _comparison("INDEPENDENT_CURRENT_DATE_MISMATCH", "NO_CONFIDENCE_UPGRADE", gap, price_abs, price_pct, False, True)
    price_threshold = float(((config.get("comparison") or {}).get("max_price_pct_diff_for_match", 0.03) or 0.03))
    if price_pct is not None and abs(price_pct) > price_threshold:
        return _comparison("INDEPENDENT_CURRENT_PRICE_MISMATCH", "NO_CONFIDENCE_UPGRADE", gap, price_abs, price_pct, current, True)
    return _comparison("INDEPENDENT_CURRENT_MATCH", "MARKET_CONFIDENCE_UPGRADE_CANDIDATE", gap, price_abs, price_pct, current, False)


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


def _attempt(provider_name: str, source_family: str, ticker: str, status: str, network_used: bool, optional_install_used: bool, request_count: int, error_type: str = "", error_message: str = "") -> dict[str, Any]:
    return {
        "provider_name": provider_name,
        "source_family": source_family,
        "ticker": str(ticker).strip().upper(),
        "attempt_status": status,
        "network_used": bool(network_used),
        "optional_install_used": bool(optional_install_used),
        "request_count": int(request_count),
        "error_type": error_type,
        "error_message": error_message,
        "attempted_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
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
        ("alternative_market_observations_20", observations, OBSERVATION_COLUMNS),
        ("source_family_current_consensus_20", consensus, CONSENSUS_COLUMNS),
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
    observations.to_csv(output / "alternative_market_observations_20.csv", index=False)
    consensus.to_csv(output / "source_family_current_consensus_20.csv", index=False)
    manual.to_csv(output / "manual_review_cases.csv", index=False)
    (output / "provider_network_probe_summary.md").write_text(build_summary(decision), encoding="utf-8")
    (output / "provider_network_probe_decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_csv(path: str | Path) -> pd.DataFrame:
    target = Path(path)
    if not target.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(target, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _pilot_tickers(frame: pd.DataFrame) -> list[str]:
    if frame.empty or "ticker" not in frame.columns:
        return []
    return [ticker for ticker in frame["ticker"].astype(str).str.strip().str.upper().drop_duplicates().tolist() if ticker]


def _index_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty or "ticker" not in frame.columns:
        return {}
    return {str(row.get("ticker", "")).strip().upper(): row.to_dict() for _, row in frame.iterrows()}


def _hashes(paths: list[Path]) -> dict[str, str]:
    return {str(path): _hash_file(path) for path in paths if path.exists()}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_cache(frame: Any, cache_dir: Path, provider_name: str, source_family: str, ticker: str) -> str:
    path = cache_dir / provider_name / source_family / f"{ticker}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(frame, pd.DataFrame):
        frame.to_csv(path, index=True)
        return str(path)
    path.with_suffix(".txt").write_text(str(frame), encoding="utf-8")
    return str(path.with_suffix(".txt"))


def _first_column(frame: pd.DataFrame, candidates: list[str]) -> str:
    lowered = {str(column).strip().lower(): str(column) for column in frame.columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    for column_lower, original in lowered.items():
        for candidate in candidates:
            candidate_lower = candidate.lower()
            if column_lower.startswith(f"{candidate_lower}_") or column_lower.endswith(f"_{candidate_lower}"):
                return original
    return ""


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


def _not_missing(value: Any) -> bool:
    return not _missing(value)


def _missing(value: Any) -> bool:
    return value is None or str(value).strip() == "" or str(value).strip().lower() in {"nan", "none", "null"}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


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
