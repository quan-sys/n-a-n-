"""20-ticker alternative market consensus sandbox for PROVISIONAL-ALT-SOURCE-04B."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yaml

from src.providers.alternative.market_provider_adapters_04b import (
    OBSERVATION_COLUMNS,
    PRIMARY_SNAPSHOT_PROVIDER_ID,
    PRIMARY_SOURCE_FAMILY,
    RAW_CACHE_PROVIDER_ID,
    RUNTIME_STATUS_COLUMNS,
    STATIC_FALLBACK_PROVIDER_ID,
    STATIC_FALLBACK_SOURCE_FAMILY,
    ProviderAdapterResult,
    ProviderFetcher,
    build_primary_snapshot_observations,
    build_raw_cache_observations,
    build_static_historical_fallback_observations,
    run_optional_market_provider,
)


SOURCE_FAMILY_CONSENSUS_COLUMNS = [
    "ticker",
    "primary_status",
    "primary_last_price_date",
    "primary_last_close",
    "provider_observation_count",
    "independent_current_source_family_count",
    "matching_independent_source_family_count",
    "matching_source_families",
    "non_independent_current_source_family_count",
    "historical_fallback_observation_count",
    "severe_mismatch_count",
    "consensus_confidence",
    "consensus_status",
    "consensus_reason",
]

MISMATCH_COLUMNS = [
    "ticker",
    "source_provider_id",
    "source_family",
    "mismatch_status",
    "primary_last_price_date",
    "primary_last_close",
    "alternative_last_price_date",
    "alternative_last_close",
    "price_date_gap_days",
    "price_pct_diff",
    "volume_60d_pct_diff",
    "reason",
]

DECISION_VALUES = {
    "PASS_FOR_STEP19_SHADOW_20",
    "CONDITIONAL_GO_FOR_STEP19_SHADOW_20",
    "NO_GO_FIX_ALT_SOURCE_04B",
}

OPTIONAL_PROVIDERS = [
    ("vnquant_secondary_candidate", "vnquant", ["cafef", "vndirect"]),
    ("vietfin_experimental_candidate", "vietfin", ["unknown_brokerage_api", "possible_vnstock_related"]),
]

DEFAULT_CORE_OUTPUT_PATHS = [
    "data/reports/provisional_current_market_03/current_market_snapshot.csv",
    "data/reports/provisional_current_market_03/stage2_eligibility_gate.csv",
    "data/reports/provisional_current_market_03/current_market_balanced_ranked_shortlist.csv",
    "data/reports/provisional_current_market_03b_crosscheck/market_crosscheck_20.csv",
    "data/reports/provisional_current_market_03c_replay/replay_decision.json",
    "data/reports/real_data_02_pilot_20/real_data_02_pilot_decision.json",
]
DEFAULT_PROVIDER_INVENTORY_PATH = "data/reports/alternative_source_probe_04a/provider_inventory.csv"


@dataclass
class AlternativeMarketConsensusResult:
    provider_runtime_status: pd.DataFrame
    alternative_market_observations: pd.DataFrame
    source_family_consensus: pd.DataFrame
    consensus_mismatch_cases: pd.DataFrame
    manual_review_cases: pd.DataFrame
    decision: dict[str, Any]


def load_consensus_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def run_alternative_market_consensus(
    *,
    snapshot_path: str | Path,
    output_dir: str | Path,
    config_path: str | Path,
    provider_inventory_path: str | Path | None = DEFAULT_PROVIDER_INVENTORY_PATH,
    raw_cache_dir: str | Path | None = None,
    prior_crosscheck_path: str | Path | None = None,
    core_output_paths: list[str | Path] | None = None,
    import_module_func: Callable[[str], Any] | None = None,
    provider_fetchers: dict[str, ProviderFetcher] | None = None,
) -> AlternativeMarketConsensusResult:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    config = load_consensus_config(config_path)
    config_errors = validate_consensus_config(config)
    core_paths = [Path(path) for path in (core_output_paths or DEFAULT_CORE_OUTPUT_PATHS)]
    before_hashes = _hashes(core_paths)

    snapshot = _read_csv(snapshot_path)
    tickers = _snapshot_tickers(snapshot)
    max_tickers = int(((config.get("run_policy") or {}).get("max_tickers", 20) or 20))

    primary_result = build_primary_snapshot_observations(snapshot, config)
    primary_observations = primary_result.observations
    runtime_frames = [primary_result.runtime_status]
    observation_frames = [primary_observations]

    raw_cache = build_raw_cache_observations(
        tickers=tickers,
        raw_cache_dir=raw_cache_dir,
        primary_observations=primary_observations,
        config=config,
    )
    if not raw_cache.empty:
        observation_frames.append(raw_cache)

    provider_fetchers = provider_fetchers or {}
    optional_providers = load_optional_provider_specs(provider_inventory_path)
    for provider_id, package_name, families in optional_providers:
        result = run_optional_market_provider(
            provider_id=provider_id,
            package_name=package_name,
            source_families=families,
            tickers=tickers,
            config=config,
            import_module_func=import_module_func,
            fetcher_func=provider_fetchers.get(provider_id),
        )
        runtime_frames.append(result.runtime_status)
        observation_frames.append(result.observations)

    static_result = build_static_historical_fallback_observations(
        tickers=tickers,
        prior_crosscheck_path=prior_crosscheck_path,
        config=config,
    )
    runtime_frames.append(static_result.runtime_status)
    if not static_result.observations.empty:
        observation_frames.append(static_result.observations)

    provider_runtime_status = _concat(runtime_frames, RUNTIME_STATUS_COLUMNS)
    observations = _concat(observation_frames, OBSERVATION_COLUMNS)
    observations = compare_observations_to_primary(observations, config)
    source_family_consensus = build_source_family_consensus(observations, config)
    mismatches = build_mismatch_cases(observations)
    manual_review = build_manual_review_cases(observations, source_family_consensus)

    after_hashes = _hashes(core_paths)
    core_outputs_modified = before_hashes != after_hashes
    schema_errors = _schema_errors(provider_runtime_status, observations, source_family_consensus, mismatches, manual_review)
    provisional_decision = build_decision(
        config_errors=config_errors,
        schema_errors=schema_errors,
        provider_runtime_status=provider_runtime_status,
        observations=observations,
        source_family_consensus=source_family_consensus,
        pilot_ticker_count=len(tickers),
        expected_ticker_count=max_tickers,
        core_outputs_modified=core_outputs_modified,
        forbidden_hits=[],
    )
    _write_outputs(output, provider_runtime_status, observations, source_family_consensus, mismatches, manual_review, provisional_decision)
    forbidden_hits = forbidden_term_hits(output)
    decision = build_decision(
        config_errors=config_errors,
        schema_errors=schema_errors,
        provider_runtime_status=provider_runtime_status,
        observations=observations,
        source_family_consensus=source_family_consensus,
        pilot_ticker_count=len(tickers),
        expected_ticker_count=max_tickers,
        core_outputs_modified=core_outputs_modified,
        forbidden_hits=forbidden_hits,
    )
    _write_outputs(output, provider_runtime_status, observations, source_family_consensus, mismatches, manual_review, decision)
    return AlternativeMarketConsensusResult(
        provider_runtime_status=provider_runtime_status,
        alternative_market_observations=observations,
        source_family_consensus=source_family_consensus,
        consensus_mismatch_cases=mismatches,
        manual_review_cases=manual_review,
        decision=decision,
    )


def load_optional_provider_specs(provider_inventory_path: str | Path | None = DEFAULT_PROVIDER_INVENTORY_PATH) -> list[tuple[str, str, list[str]]]:
    if not provider_inventory_path:
        return OPTIONAL_PROVIDERS
    frame = _read_csv(provider_inventory_path)
    required = {"provider_id", "package_name", "configured_source_families"}
    if frame.empty or not required.issubset(set(frame.columns)):
        return OPTIONAL_PROVIDERS
    specs = []
    for _, row in frame.iterrows():
        provider_id = str(row.get("provider_id", ""))
        if provider_id not in {"vnquant_secondary_candidate", "vietfin_experimental_candidate"}:
            continue
        package_name = str(row.get("package_name", ""))
        families = [family for family in str(row.get("configured_source_families", "")).split(";") if family]
        specs.append((provider_id, package_name, families))
    return specs or OPTIONAL_PROVIDERS


def validate_consensus_config(config: dict[str, Any]) -> list[str]:
    errors = []
    safety = config.get("safety") if isinstance(config, dict) else {}
    run_policy = config.get("run_policy") if isinstance(config, dict) else {}
    rules = config.get("source_family_rules") if isinstance(config, dict) else {}
    if not isinstance(safety, dict):
        errors.append("missing safety config")
    else:
        for key in [
            "sandbox_only",
            "no_core_pipeline_mutation",
            "no_ranking_mutation",
            "no_stage_promotion",
            "no_step19",
            "no_real_data_02",
            "no_top500_refresh",
            "no_full_universe_fetch",
            "no_official_pdf_fetch",
            "no_ocr",
        ]:
            if safety.get(key) is not True:
                errors.append(f"safety.{key} must be true")
    if not isinstance(run_policy, dict):
        errors.append("missing run_policy config")
    else:
        if run_policy.get("allow_finance_data_fetch") is not False:
            errors.append("run_policy.allow_finance_data_fetch must be false")
        if run_policy.get("allow_auto_install") is not False:
            errors.append("run_policy.allow_auto_install must be false")
    if not isinstance(rules, dict):
        errors.append("missing source_family_rules config")
    else:
        if rules.get("raw_cache_is_independent") is not False:
            errors.append("source_family_rules.raw_cache_is_independent must be false")
        if rules.get("static_github_historical_is_current_confirmation") is not False:
            errors.append("source_family_rules.static_github_historical_is_current_confirmation must be false")
        if rules.get("same_upstream_family_counts_once") is not True:
            errors.append("source_family_rules.same_upstream_family_counts_once must be true")
    return errors


def compare_observations_to_primary(observations: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    if observations.empty:
        return pd.DataFrame(columns=OBSERVATION_COLUMNS)
    primary_by_ticker = _primary_by_ticker(observations)
    primary_family = str(((config.get("source_family_rules") or {}).get("primary_source_family") or PRIMARY_SOURCE_FAMILY))
    price_threshold = float(((config.get("comparison") or {}).get("max_price_pct_diff_for_match", 0.03) or 0.03))
    volume_threshold = float(((config.get("comparison") or {}).get("max_volume_60d_pct_diff_for_match", 0.50) or 0.50))
    max_gap_days = int(((config.get("comparison") or {}).get("max_current_reference_gap_days", 5) or 5))
    rows = []
    for _, row in observations.iterrows():
        out = {column: row.get(column, "") for column in OBSERVATION_COLUMNS}
        ticker = str(out.get("ticker", "")).upper()
        primary = primary_by_ticker.get(ticker, {})
        provider_id = str(out.get("source_provider_id", ""))
        source_family = str(out.get("source_family", ""))
        status = str(out.get("observation_status", ""))
        if provider_id == PRIMARY_SNAPSHOT_PROVIDER_ID:
            rows.append(out)
            continue
        if status in {"PROVIDER_NOT_IMPORTABLE", "PROVIDER_NO_DATA", "PROVIDER_ERROR"}:
            rows.append(out)
            continue
        if provider_id == STATIC_FALLBACK_PROVIDER_ID or _as_bool(out.get("is_historical_fallback_only")):
            out["observation_status"] = "HISTORICAL_FALLBACK_ONLY"
            out["is_current_enough"] = False
            out["is_independent_current_candidate"] = False
            rows.append(out)
            continue
        gap = _date_gap_days(primary.get("last_price_date"), out.get("last_price_date"))
        out["price_date_gap_days"] = gap if gap is not None else ""
        out["price_pct_diff"] = _pct_diff(primary.get("last_close"), out.get("last_close"))
        out["volume_60d_pct_diff"] = _pct_diff(primary.get("avg_volume_60d"), out.get("avg_volume_60d"))
        if _is_missing(out.get("last_price_date")):
            out["observation_status"] = "REFERENCE_DATE_MISSING"
            out["is_current_enough"] = False
            rows.append(out)
            continue
        if _is_missing(out.get("last_close")):
            out["observation_status"] = "PROVIDER_NO_DATA"
            out["is_current_enough"] = False
            rows.append(out)
            continue
        current_enough = gap is not None and abs(gap) <= max_gap_days
        out["is_current_enough"] = current_enough
        if not current_enough:
            out["observation_status"] = "REFERENCE_STALE"
            out["is_independent_current_candidate"] = False
            rows.append(out)
            continue
        same_family = provider_id == RAW_CACHE_PROVIDER_ID or source_family == primary_family
        independent_candidate = _is_independent_current_candidate(provider_id, source_family, same_family)
        out["is_independent_current_candidate"] = independent_candidate
        if str(out.get("price_basis", "")).lower() == "adjusted":
            out["observation_status"] = "MANUAL_REVIEW_PRICE_BASIS"
            out["manual_review_flag"] = True
            rows.append(out)
            continue
        price_pct_diff = _to_float(out.get("price_pct_diff"))
        volume_pct_diff = _to_float(out.get("volume_60d_pct_diff"))
        if price_pct_diff is not None and abs(price_pct_diff) > price_threshold:
            out["observation_status"] = "PRICE_MISMATCH"
            out["price_match_status"] = "PRICE_MISMATCH"
            out["manual_review_flag"] = True
        elif volume_pct_diff is not None and abs(volume_pct_diff) > volume_threshold:
            out["observation_status"] = "VOLUME_MISMATCH"
            out["price_match_status"] = "PRICE_MATCH"
            out["volume_match_status"] = "VOLUME_MISMATCH"
            out["manual_review_flag"] = True
        elif same_family or not independent_candidate:
            out["observation_status"] = "NOT_INDEPENDENT_SAME_SOURCE_FAMILY"
            out["price_match_status"] = "PRICE_MATCH"
            out["volume_match_status"] = "VOLUME_MATCH" if volume_pct_diff is not None else ""
            out["manual_review_flag"] = False
        else:
            out["observation_status"] = "PRICE_MATCH"
            out["price_match_status"] = "PRICE_MATCH"
            out["volume_match_status"] = "VOLUME_MATCH" if volume_pct_diff is None or abs(volume_pct_diff) <= volume_threshold else "VOLUME_MISMATCH"
            out["manual_review_flag"] = False
        rows.append(out)
    return pd.DataFrame(rows, columns=OBSERVATION_COLUMNS)


def build_source_family_consensus(observations: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    if observations.empty:
        return pd.DataFrame(columns=SOURCE_FAMILY_CONSENSUS_COLUMNS)
    primary_rows = observations[observations["source_provider_id"].eq(PRIMARY_SNAPSHOT_PROVIDER_ID)]
    tickers = _snapshot_tickers(primary_rows)
    medium_min = int(((config.get("comparison") or {}).get("min_independent_current_source_families_for_medium_confidence", 1) or 1))
    medium_high_min = int(((config.get("comparison") or {}).get("min_independent_current_source_families_for_medium_high_confidence", 2) or 2))
    rows = []
    for ticker in tickers:
        ticker_rows = observations[observations["ticker"].astype(str).str.upper().eq(ticker)]
        primary = ticker_rows[ticker_rows["source_provider_id"].eq(PRIMARY_SNAPSHOT_PROVIDER_ID)].head(1)
        primary_row = primary.iloc[0].to_dict() if not primary.empty else {}
        primary_status = str(primary_row.get("observation_status", "PRIMARY_MISSING") or "PRIMARY_MISSING")
        non_primary = ticker_rows[~ticker_rows["source_provider_id"].eq(PRIMARY_SNAPSHOT_PROVIDER_ID)]
        independent_current = non_primary[
            non_primary["is_independent_current_candidate"].map(_as_bool)
            & non_primary["is_current_enough"].map(_as_bool)
        ]
        independent_families = _unique_families(independent_current)
        matching_independent = independent_current[
            independent_current["observation_status"].isin(["PRICE_MATCH", "VOLUME_MATCH"])
            | independent_current["price_match_status"].eq("PRICE_MATCH")
        ]
        matching_families = _unique_families(matching_independent[~matching_independent["volume_match_status"].eq("VOLUME_MISMATCH")])
        severe = non_primary[
            non_primary["observation_status"].isin(["PRICE_MISMATCH", "VOLUME_MISMATCH", "MANUAL_REVIEW_PRICE_BASIS"])
            & non_primary["is_independent_current_candidate"].map(_as_bool)
        ]
        raw_current = non_primary[
            non_primary["source_provider_id"].eq(RAW_CACHE_PROVIDER_ID)
            & non_primary["is_current_enough"].map(_as_bool)
        ]
        historical = non_primary[non_primary["is_historical_fallback_only"].map(_as_bool)]
        confidence, status, reason = _consensus_confidence(
            primary_status=primary_status,
            matching_count=len(matching_families),
            independent_count=len(independent_families),
            severe_count=len(severe),
            raw_current_count=len(raw_current),
            medium_min=medium_min,
            medium_high_min=medium_high_min,
        )
        rows.append(
            {
                "ticker": ticker,
                "primary_status": primary_status,
                "primary_last_price_date": primary_row.get("last_price_date", ""),
                "primary_last_close": primary_row.get("last_close", ""),
                "provider_observation_count": int(len(non_primary)),
                "independent_current_source_family_count": int(len(independent_families)),
                "matching_independent_source_family_count": int(len(matching_families)),
                "matching_source_families": ";".join(matching_families),
                "non_independent_current_source_family_count": int(len(raw_current)),
                "historical_fallback_observation_count": int(len(historical)),
                "severe_mismatch_count": int(len(severe)),
                "consensus_confidence": confidence,
                "consensus_status": status,
                "consensus_reason": reason,
            }
        )
    return pd.DataFrame(rows, columns=SOURCE_FAMILY_CONSENSUS_COLUMNS)


def build_mismatch_cases(observations: pd.DataFrame) -> pd.DataFrame:
    if observations.empty:
        return pd.DataFrame(columns=MISMATCH_COLUMNS)
    primary_by_ticker = _primary_by_ticker(observations)
    rows = []
    mismatch_rows = observations[observations["observation_status"].isin(["PRICE_MISMATCH", "VOLUME_MISMATCH"])]
    for _, row in mismatch_rows.iterrows():
        primary = primary_by_ticker.get(str(row.get("ticker", "")).upper(), {})
        rows.append(
            {
                "ticker": row.get("ticker", ""),
                "source_provider_id": row.get("source_provider_id", ""),
                "source_family": row.get("source_family", ""),
                "mismatch_status": row.get("observation_status", ""),
                "primary_last_price_date": primary.get("last_price_date", ""),
                "primary_last_close": primary.get("last_close", ""),
                "alternative_last_price_date": row.get("last_price_date", ""),
                "alternative_last_close": row.get("last_close", ""),
                "price_date_gap_days": row.get("price_date_gap_days", ""),
                "price_pct_diff": row.get("price_pct_diff", ""),
                "volume_60d_pct_diff": row.get("volume_60d_pct_diff", ""),
                "reason": "Alternative market observation differs beyond configured tolerance.",
            }
        )
    return pd.DataFrame(rows, columns=MISMATCH_COLUMNS)


def build_manual_review_cases(observations: pd.DataFrame, source_family_consensus: pd.DataFrame) -> pd.DataFrame:
    observation_cases = observations[
        observations["manual_review_flag"].map(_as_bool)
        | observations["observation_status"].isin(["MANUAL_REVIEW_PRICE_BASIS", "PRICE_MISMATCH", "VOLUME_MISMATCH"])
    ].copy() if not observations.empty else pd.DataFrame(columns=OBSERVATION_COLUMNS)
    consensus_cases = source_family_consensus[
        source_family_consensus["consensus_confidence"].isin(["MANUAL_REVIEW", "NO_GO_DATA_QUALITY"])
    ].copy() if not source_family_consensus.empty else pd.DataFrame(columns=SOURCE_FAMILY_CONSENSUS_COLUMNS)
    if consensus_cases.empty:
        return observation_cases
    consensus_cases = consensus_cases.rename(columns={"consensus_status": "observation_status"})
    for column in OBSERVATION_COLUMNS:
        if column not in consensus_cases.columns:
            consensus_cases[column] = ""
    return pd.concat([observation_cases, consensus_cases[OBSERVATION_COLUMNS]], ignore_index=True)


def build_decision(
    *,
    config_errors: list[str],
    schema_errors: list[str],
    provider_runtime_status: pd.DataFrame,
    observations: pd.DataFrame,
    source_family_consensus: pd.DataFrame,
    pilot_ticker_count: int,
    expected_ticker_count: int,
    core_outputs_modified: bool,
    forbidden_hits: list[str],
) -> dict[str, Any]:
    provider_runtime_count = int(len(provider_runtime_status))
    provider_importable_count = int(provider_runtime_status["provider_importable"].map(_as_bool).sum()) if not provider_runtime_status.empty else 0
    provider_not_importable_count = _count_runtime(provider_runtime_status, "PROVIDER_NOT_IMPORTABLE")
    provider_error_count = _count_runtime(provider_runtime_status, "PROVIDER_ERROR")
    observations_count = int(len(observations))
    independent_families = _unique_families(
        observations[
            observations["is_independent_current_candidate"].map(_as_bool)
            & observations["is_current_enough"].map(_as_bool)
        ]
    ) if not observations.empty else []
    tickers_with_independent_match_count = int(
        source_family_consensus["matching_independent_source_family_count"].astype(int).gt(0).sum()
        if not source_family_consensus.empty
        else 0
    )
    tickers_manual_review_count = int(
        source_family_consensus["consensus_confidence"].isin(["MANUAL_REVIEW", "NO_GO_DATA_QUALITY"]).sum()
        if not source_family_consensus.empty
        else 0
    )
    primary_invalid_count = int(
        source_family_consensus["consensus_confidence"].eq("NO_GO_DATA_QUALITY").sum()
        if not source_family_consensus.empty
        else 1
    )
    severe_mismatch_count = int(
        source_family_consensus["severe_mismatch_count"].astype(int).sum()
        if not source_family_consensus.empty
        else 0
    )
    ticker_count_mismatch = pilot_ticker_count != expected_ticker_count
    critical_fail_count = (
        len(config_errors)
        + len(schema_errors)
        + int(ticker_count_mismatch)
        + int(core_outputs_modified)
        + len(forbidden_hits)
        + primary_invalid_count
        + severe_mismatch_count
    )
    network_used = bool(provider_runtime_status["network_used"].map(_as_bool).any()) if not provider_runtime_status.empty else False
    market_data_fetched = bool(provider_runtime_status["market_data_fetched"].map(_as_bool).any()) if not provider_runtime_status.empty else False
    finance_data_fetched = bool(provider_runtime_status["finance_data_fetched"].map(_as_bool).any()) if not provider_runtime_status.empty else False
    if critical_fail_count or finance_data_fetched:
        final_decision = "NO_GO_FIX_ALT_SOURCE_04B"
        allowed_next_step = "Fix PROVISIONAL-ALT-SOURCE-04B data quality or safety issues before STEP19-SHADOW-20."
    elif tickers_with_independent_match_count > 0:
        final_decision = "PASS_FOR_STEP19_SHADOW_20"
        allowed_next_step = "STEP19-SHADOW-20"
    else:
        final_decision = "CONDITIONAL_GO_FOR_STEP19_SHADOW_20"
        allowed_next_step = "STEP19-SHADOW-20 with low market-source confidence notes."
    if final_decision not in DECISION_VALUES:
        raise ValueError(f"Invalid 04B decision: {final_decision}")
    return {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "pilot_ticker_count": pilot_ticker_count,
        "expected_ticker_count": expected_ticker_count,
        "provider_runtime_count": provider_runtime_count,
        "provider_importable_count": provider_importable_count,
        "provider_not_importable_count": provider_not_importable_count,
        "provider_error_count": provider_error_count,
        "observations_count": observations_count,
        "independent_current_source_family_count": len(independent_families),
        "independent_current_source_families": independent_families,
        "tickers_with_independent_match_count": tickers_with_independent_match_count,
        "tickers_manual_review_count": tickers_manual_review_count,
        "critical_fail_count": critical_fail_count,
        "config_errors": config_errors,
        "schema_errors": schema_errors,
        "forbidden_terms_found": forbidden_hits,
        "primary_invalid_count": primary_invalid_count,
        "severe_mismatch_count": severe_mismatch_count,
        "network_used": network_used,
        "market_data_fetched": market_data_fetched,
        "finance_data_fetched": finance_data_fetched,
        "core_outputs_modified": core_outputs_modified,
        "final_decision": final_decision,
        "allowed_next_step": allowed_next_step,
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


def build_summary(decision: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# PROVISIONAL-ALT-SOURCE-04B Market Consensus Summary",
            "",
            f"- generated_at: {decision.get('generated_at', '')}",
            f"- pilot_ticker_count: {decision.get('pilot_ticker_count', 0)}",
            f"- provider_runtime_count: {decision.get('provider_runtime_count', 0)}",
            f"- provider_importable_count: {decision.get('provider_importable_count', 0)}",
            f"- provider_not_importable_count: {decision.get('provider_not_importable_count', 0)}",
            f"- provider_error_count: {decision.get('provider_error_count', 0)}",
            f"- observations_count: {decision.get('observations_count', 0)}",
            f"- independent_current_source_family_count: {decision.get('independent_current_source_family_count', 0)}",
            f"- tickers_with_independent_match_count: {decision.get('tickers_with_independent_match_count', 0)}",
            f"- tickers_manual_review_count: {decision.get('tickers_manual_review_count', 0)}",
            f"- critical_fail_count: {decision.get('critical_fail_count', 0)}",
            f"- network_used: {decision.get('network_used', False)}",
            f"- market_data_fetched: {decision.get('market_data_fetched', False)}",
            f"- finance_data_fetched: {decision.get('finance_data_fetched', False)}",
            f"- core_outputs_modified: {decision.get('core_outputs_modified', False)}",
            f"- final_decision: {decision.get('final_decision', '')}",
            "",
            "## Interpretation",
            "- This is a sandbox-only market source-family check for the existing 20 pilot tickers.",
            "- Static historical fallback rows do not increase current confidence.",
            "- Raw cache rows are treated as same-family local consistency checks only.",
            "- Missing optional providers are recorded without fabricating values.",
            "",
            "## Allowed next step",
            f"- {decision.get('allowed_next_step', '')}",
        ]
    ) + "\n"


def forbidden_term_hits(output_dir: Path) -> list[str]:
    terms = [
        "buy",
        "sell",
        "hold",
        "target price",
        "target_price",
        "fair value",
        "fair_value",
        "margin of safety",
        "margin_of_safety",
        "mos",
        "recommendation",
    ]
    allowed = ["not_authorized", "no_", "no ", "not ", "forbidden", "safety", "does not authorize"]
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


def _write_outputs(
    output: Path,
    provider_runtime_status: pd.DataFrame,
    observations: pd.DataFrame,
    source_family_consensus: pd.DataFrame,
    mismatches: pd.DataFrame,
    manual_review: pd.DataFrame,
    decision: dict[str, Any],
) -> None:
    provider_runtime_status.to_csv(output / "provider_runtime_status.csv", index=False)
    observations.to_csv(output / "alternative_market_observations_20.csv", index=False)
    source_family_consensus.to_csv(output / "source_family_consensus_20.csv", index=False)
    mismatches.to_csv(output / "consensus_mismatch_cases.csv", index=False)
    manual_review.to_csv(output / "manual_review_cases.csv", index=False)
    (output / "alternative_market_consensus_summary.md").write_text(build_summary(decision), encoding="utf-8")
    (output / "alt_source_04b_decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")


def _consensus_confidence(
    *,
    primary_status: str,
    matching_count: int,
    independent_count: int,
    severe_count: int,
    raw_current_count: int,
    medium_min: int,
    medium_high_min: int,
) -> tuple[str, str, str]:
    if primary_status != "PRIMARY_OK":
        return "NO_GO_DATA_QUALITY", primary_status, "Primary market reference is missing or stale."
    if severe_count:
        return "MANUAL_REVIEW", "SEVERE_MISMATCH", "At least one independent current source-family differs beyond tolerance."
    if matching_count >= medium_high_min:
        return "PROVISIONAL_MEDIUM_HIGH", "INDEPENDENT_MATCH", "Two or more independent current source-families match within tolerance."
    if matching_count >= medium_min:
        return "PROVISIONAL_MEDIUM", "INDEPENDENT_MATCH", "At least one independent current source-family matches within tolerance."
    if independent_count:
        return "PROVISIONAL_LOW", "INDEPENDENT_SOURCE_NO_MATCH", "Independent current source-family was present but did not produce a usable match."
    if raw_current_count:
        return "PROVISIONAL_LOW_PLUS", "PRIMARY_WITH_RAW_CACHE_ONLY", "Only same-family raw cache consistency is available."
    return "PROVISIONAL_LOW", "PRIMARY_ONLY_NO_ALT_SOURCE", "No independent current alternative source-family is available."


def _schema_errors(
    provider_runtime_status: pd.DataFrame,
    observations: pd.DataFrame,
    source_family_consensus: pd.DataFrame,
    mismatches: pd.DataFrame,
    manual_review: pd.DataFrame,
) -> list[str]:
    checks = [
        ("provider_runtime_status", provider_runtime_status, RUNTIME_STATUS_COLUMNS),
        ("alternative_market_observations_20", observations, OBSERVATION_COLUMNS),
        ("source_family_consensus_20", source_family_consensus, SOURCE_FAMILY_CONSENSUS_COLUMNS),
        ("consensus_mismatch_cases", mismatches, MISMATCH_COLUMNS),
        ("manual_review_cases", manual_review, OBSERVATION_COLUMNS),
    ]
    errors = []
    for name, frame, columns in checks:
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            errors.append(f"{name} missing columns: {','.join(missing)}")
    return errors


def _concat(frames: list[pd.DataFrame], columns: list[str]) -> pd.DataFrame:
    present = [frame for frame in frames if isinstance(frame, pd.DataFrame) and not frame.empty]
    if not present:
        return pd.DataFrame(columns=columns)
    return pd.concat(present, ignore_index=True)[columns]


def _count_runtime(frame: pd.DataFrame, status: str) -> int:
    if frame.empty or "runtime_status" not in frame.columns:
        return 0
    return int(frame["runtime_status"].eq(status).sum())


def _is_independent_current_candidate(provider_id: str, source_family: str, same_family: bool) -> bool:
    if same_family:
        return False
    if provider_id == "vietfin_experimental_candidate":
        return False
    if source_family in {STATIC_FALLBACK_SOURCE_FAMILY, PRIMARY_SOURCE_FAMILY, "vnstock_tcbs", "vnstock_other", "possible_vnstock_related", "unknown_brokerage_api"}:
        return False
    return source_family in {"cafef", "vndirect"}


def _unique_families(frame: pd.DataFrame) -> list[str]:
    if frame.empty or "source_family" not in frame.columns:
        return []
    return sorted({str(value) for value in frame["source_family"].dropna().tolist() if str(value).strip()})


def _primary_by_ticker(observations: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if observations.empty:
        return {}
    primary = observations[observations["source_provider_id"].eq(PRIMARY_SNAPSHOT_PROVIDER_ID)]
    return {str(row.get("ticker", "")).upper(): row.to_dict() for _, row in primary.iterrows()}


def _snapshot_tickers(frame: pd.DataFrame) -> list[str]:
    if frame.empty or "ticker" not in frame.columns:
        return []
    return [ticker for ticker in frame["ticker"].astype(str).str.strip().str.upper().drop_duplicates().tolist() if ticker]


def _hashes(paths: list[Path]) -> dict[str, str]:
    return {str(path): _hash_file(path) for path in paths if path.exists()}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: str | Path) -> pd.DataFrame:
    target = Path(path)
    if not target.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(target, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _date_gap_days(left: Any, right: Any) -> int | None:
    left_date = pd.to_datetime(left, errors="coerce")
    right_date = pd.to_datetime(right, errors="coerce")
    if pd.isna(left_date) or pd.isna(right_date):
        return None
    return int((left_date.date() - right_date.date()).days)


def _pct_diff(primary: Any, alternative: Any) -> float | None:
    primary_num = _to_float(primary)
    alternative_num = _to_float(alternative)
    if primary_num is None or alternative_num is None or primary_num == 0:
        return None
    return round((alternative_num - primary_num) / abs(primary_num), 6)


def _to_float(value: Any) -> float | None:
    if _is_missing(value):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _is_missing(value: Any) -> bool:
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
