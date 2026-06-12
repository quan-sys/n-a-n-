"""Diagnostic-only Step19 shadow run for the same 20 pilot tickers."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


DIAGNOSTIC_COLUMNS = [
    "ticker",
    "shadow_status",
    "input_market_status",
    "input_finance_status",
    "readiness_status_from_real_data_02",
    "market_source_confidence",
    "finance_source_confidence",
    "independent_current_source_family_count",
    "missing_required_fields",
    "warning_count",
    "critical_issue_count",
    "shadow_engine_ran",
    "production_step19_allowed",
    "investment_recommendation_allowed",
    "valuation_allowed",
    "notes",
]

REASON_COLUMNS = ["ticker", "severity", "reason_code", "reason_message", "source_file", "field_name"]
SUMMARY_COLUMNS = ["metric", "value"]
AUDIT_COLUMNS = ["audit_item", "status", "observed_value", "expected_value", "detail"]

DECISION_VALUES = {
    "PASS_SHADOW_DIAGNOSTIC_PLUMBING",
    "CONDITIONAL_GO_FOR_ALT_SOURCE_FIX_OR_SCALE_PILOT",
    "NO_GO_FIX_SHADOW_PIPELINE",
}

SHADOW_STATUSES = {
    "SHADOW_READY_DIAGNOSTIC_ONLY",
    "SHADOW_CONDITIONAL_DIAGNOSTIC_ONLY",
    "SHADOW_BLOCKED_MISSING_INPUT",
    "SHADOW_BLOCKED_CRITICAL_DATA",
}


@dataclass
class Step19ShadowResult:
    diagnostics: pd.DataFrame
    reason_codes: pd.DataFrame
    readiness_summary: pd.DataFrame
    blocked_actionable_outputs_audit: pd.DataFrame
    decision: dict[str, Any]


def load_shadow_policy(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def run_step19_shadow_20(
    *,
    config_path: str | Path,
    output_dir: str | Path,
    core_output_paths: list[str | Path] | None = None,
) -> Step19ShadowResult:
    policy = load_shadow_policy(config_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    resolved_inputs, missing_inputs = resolve_input_paths(policy)
    core_paths = [Path(path) for path in (core_output_paths or policy.get("core_output_watchlist", []))]
    before_hashes = _hashes(core_paths)

    config_errors = validate_policy(policy)
    expected_count = int(((policy.get("run_policy") or {}).get("expected_pilot_ticker_count", 20) or 20))
    snapshot = _read_csv(resolved_inputs.get("current_market_snapshot", ""))
    tickers = _snapshot_tickers(snapshot)

    if missing_inputs or config_errors:
        diagnostics, reasons = _missing_input_outputs(tickers, missing_inputs, config_errors)
        after_hashes = _hashes(core_paths)
        decision = build_decision(
            diagnostics=diagnostics,
            reasons=reasons,
            missing_inputs=missing_inputs,
            config_errors=config_errors,
            expected_count=expected_count,
            core_outputs_modified=before_hashes != after_hashes,
            forbidden_hits=[],
        )
        readiness_summary = build_readiness_summary(diagnostics, reasons, decision)
        audit = build_blocked_actionable_outputs_audit(diagnostics, forbidden_hits=[])
        _write_outputs(output, diagnostics, reasons, readiness_summary, audit, decision)
        forbidden_hits = forbidden_term_hits(output)
        decision = build_decision(
            diagnostics=diagnostics,
            reasons=reasons,
            missing_inputs=missing_inputs,
            config_errors=config_errors,
            expected_count=expected_count,
            core_outputs_modified=before_hashes != after_hashes,
            forbidden_hits=forbidden_hits,
        )
        audit = build_blocked_actionable_outputs_audit(diagnostics, forbidden_hits=forbidden_hits)
        readiness_summary = build_readiness_summary(diagnostics, reasons, decision)
        _write_outputs(output, diagnostics, reasons, readiness_summary, audit, decision)
        return Step19ShadowResult(diagnostics, reasons, readiness_summary, audit, decision)

    stage2 = _read_csv(resolved_inputs["stage2_eligibility_gate"])
    readiness = _read_csv(resolved_inputs["real_data_02_readiness"])
    observations = _read_csv(resolved_inputs["alt_source_04b_observations"])
    consensus = _read_csv(resolved_inputs["alt_source_04b_consensus"])
    schema_errors = validate_input_schemas(snapshot=snapshot, stage2=stage2, readiness=readiness, observations=observations, consensus=consensus)

    diagnostics, reasons = build_shadow_diagnostics(
        tickers=tickers,
        snapshot=snapshot,
        stage2=stage2,
        readiness=readiness,
        observations=observations,
        consensus=consensus,
        policy=policy,
        resolved_inputs=resolved_inputs,
        schema_errors=schema_errors,
    )
    after_hashes = _hashes(core_paths)
    decision = build_decision(
        diagnostics=diagnostics,
        reasons=reasons,
        missing_inputs=[],
        config_errors=schema_errors,
        expected_count=expected_count,
        core_outputs_modified=before_hashes != after_hashes,
        forbidden_hits=[],
    )
    readiness_summary = build_readiness_summary(diagnostics, reasons, decision)
    audit = build_blocked_actionable_outputs_audit(diagnostics, forbidden_hits=[])
    _write_outputs(output, diagnostics, reasons, readiness_summary, audit, decision)
    forbidden_hits = forbidden_term_hits(output)
    decision = build_decision(
        diagnostics=diagnostics,
        reasons=reasons,
        missing_inputs=[],
        config_errors=schema_errors,
        expected_count=expected_count,
        core_outputs_modified=before_hashes != after_hashes,
        forbidden_hits=forbidden_hits,
    )
    audit = build_blocked_actionable_outputs_audit(diagnostics, forbidden_hits=forbidden_hits)
    readiness_summary = build_readiness_summary(diagnostics, reasons, decision)
    _write_outputs(output, diagnostics, reasons, readiness_summary, audit, decision)
    return Step19ShadowResult(diagnostics, reasons, readiness_summary, audit, decision)


def resolve_input_paths(policy: dict[str, Any]) -> tuple[dict[str, Path], list[str]]:
    resolved: dict[str, Path] = {}
    missing: list[str] = []
    inputs = policy.get("inputs") or {}
    for logical_name, candidates in inputs.items():
        candidate_paths = candidates if isinstance(candidates, list) else [candidates]
        chosen = None
        for candidate in candidate_paths:
            path = Path(str(candidate))
            if path.exists():
                chosen = path
                break
        if chosen is None:
            missing.append(str(logical_name))
        else:
            resolved[str(logical_name)] = chosen
    return resolved, missing


def validate_policy(policy: dict[str, Any]) -> list[str]:
    errors = []
    safety = policy.get("safety") if isinstance(policy, dict) else {}
    if not isinstance(safety, dict):
        return ["missing safety config"]
    for key in [
        "shadow_only",
        "no_production_step19",
        "no_core_pipeline_mutation",
        "no_ranking_mutation",
        "no_stage_promotion",
        "no_real_data_02_rerun",
        "no_top500_refresh",
        "no_full_universe_fetch",
        "no_official_pdf_fetch",
        "no_ocr",
        "no_web_scraping",
        "no_live_market_fetch",
        "no_finance_fetch",
    ]:
        if safety.get(key) is not True:
            errors.append(f"safety.{key} must be true")
    return errors


def validate_input_schemas(*, snapshot: pd.DataFrame, stage2: pd.DataFrame, readiness: pd.DataFrame, observations: pd.DataFrame, consensus: pd.DataFrame) -> list[str]:
    checks = [
        ("current_market_snapshot", snapshot, ["ticker", "last_close", "last_price_date", "missing_market_flag", "stale_price_flag"]),
        ("stage2_eligibility_gate", stage2, ["ticker", "finance_crosscheck_status", "finance_confidence"]),
        ("real_data_02_readiness", readiness, ["ticker", "readiness_status", "warnings", "missing_fields"]),
        ("alt_source_04b_observations", observations, ["ticker", "source_provider_id", "source_family", "observation_status", "is_independent_current_candidate"]),
        ("alt_source_04b_consensus", consensus, ["ticker", "primary_status", "independent_current_source_family_count"]),
    ]
    errors = []
    for name, frame, columns in checks:
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            errors.append(f"{name} missing columns: {','.join(missing)}")
    return errors


def build_shadow_diagnostics(
    *,
    tickers: list[str],
    snapshot: pd.DataFrame,
    stage2: pd.DataFrame,
    readiness: pd.DataFrame,
    observations: pd.DataFrame,
    consensus: pd.DataFrame,
    policy: dict[str, Any],
    resolved_inputs: dict[str, Path],
    schema_errors: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    snapshot_by_ticker = _index_by_ticker(snapshot)
    stage2_by_ticker = _index_by_ticker(stage2)
    readiness_by_ticker = _index_by_ticker(readiness)
    consensus_by_ticker = _index_by_ticker(consensus)
    raw_cache_tickers = _raw_cache_tickers(observations)
    run_policy = policy.get("run_policy") or {}
    finance_confidence = str(run_policy.get("finance_source_confidence") or "PROVISIONAL_LOW")
    market_primary_only = str(run_policy.get("market_source_confidence_when_no_independent") or "PROVISIONAL_PRIMARY_ONLY")
    diagnostics = []
    all_reasons = []
    for ticker in tickers:
        ticker_reasons: list[dict[str, Any]] = []
        snapshot_row = snapshot_by_ticker.get(ticker, {})
        stage2_row = stage2_by_ticker.get(ticker, {})
        readiness_row = readiness_by_ticker.get(ticker, {})
        consensus_row = consensus_by_ticker.get(ticker, {})

        input_market_status = str(consensus_row.get("primary_status", "") or _snapshot_market_status(snapshot_row))
        readiness_status = str(readiness_row.get("readiness_status", "") or "MISSING_READINESS")
        input_finance_status = str(readiness_row.get("finance_data_confidence", "") or stage2_row.get("finance_quality_status", "") or stage2_row.get("finance_confidence", ""))
        independent_count = _to_int(consensus_row.get("independent_current_source_family_count"), 0)
        market_confidence = market_primary_only if independent_count == 0 else str(consensus_row.get("consensus_confidence", "") or "PROVISIONAL_MEDIUM")
        missing_fields = str(readiness_row.get("missing_fields", "") or "")

        if schema_errors:
            ticker_reasons.extend(_critical_reasons_for_schema(ticker, schema_errors))
        if input_market_status == "PRIMARY_OK":
            ticker_reasons.append(_reason(ticker, "INFO", "MARKET_PRIMARY_FRESH", "Primary market row is fresh in the 04B primary reference.", resolved_inputs["alt_source_04b_consensus"], "primary_status"))
        else:
            ticker_reasons.append(_reason(ticker, "CRITICAL", "MARKET_PRIMARY_NOT_READY", "Primary market row is missing, stale, or unavailable.", resolved_inputs["alt_source_04b_consensus"], "primary_status"))
        if independent_count == 0:
            ticker_reasons.append(_reason(ticker, "WARN", "MARKET_NO_INDEPENDENT_CURRENT_CONFIRMATION", "04B found no independent current market source-family for this ticker.", resolved_inputs["alt_source_04b_consensus"], "independent_current_source_family_count"))
        if ticker in raw_cache_tickers:
            ticker_reasons.append(_reason(ticker, "INFO", "MARKET_RAW_CACHE_NOT_INDEPENDENT", "Raw cache is same source-family and is not counted as independent confirmation.", resolved_inputs["alt_source_04b_observations"], "source_family"))
        if str(stage2_row.get("finance_crosscheck_status", "")).upper() == "ONE_SOURCE_ONLY" or str(readiness_row.get("finance_data_confidence", "")).upper() == "ONE_SOURCE_ONLY":
            ticker_reasons.append(_reason(ticker, "WARN", "FINANCE_ONE_SOURCE_ONLY", "Finance layer remains provisional and one-source-only.", resolved_inputs["stage2_eligibility_gate"], "finance_crosscheck_status"))
        for field in _split_fields(missing_fields):
            ticker_reasons.append(_reason(ticker, "WARN", "FINANCE_FIELD_MISSING", "Required finance field is missing and was not filled.", resolved_inputs["real_data_02_readiness"], field))
        if readiness_status == "READY_FOR_SHADOW":
            ticker_reasons.append(_reason(ticker, "INFO", "READY_FOR_SHADOW_FROM_REAL_DATA_02", "REAL-DATA-02 marked this ticker ready for diagnostic shadow.", resolved_inputs["real_data_02_readiness"], "readiness_status"))
        elif readiness_status == "CONDITIONAL_READY":
            ticker_reasons.append(_reason(ticker, "WARN", "CONDITIONAL_READY_FROM_REAL_DATA_02", "REAL-DATA-02 marked this ticker conditionally ready for diagnostic shadow.", resolved_inputs["real_data_02_readiness"], "readiness_status"))
        else:
            ticker_reasons.append(_reason(ticker, "CRITICAL", "REAL_DATA_02_READINESS_MISSING", "REAL-DATA-02 readiness status is missing or not usable.", resolved_inputs["real_data_02_readiness"], "readiness_status"))
        ticker_reasons.append(_reason(ticker, "INFO", "ACTIONABLE_OUTPUT_BLOCKED", "Actionable company output is blocked in shadow mode.", "STEP19-SHADOW-20", "investment_recommendation_allowed"))
        ticker_reasons.append(_reason(ticker, "INFO", "VALUATION_BLOCKED", "Valuation output is blocked in shadow mode.", "STEP19-SHADOW-20", "valuation_allowed"))
        ticker_reasons.append(_reason(ticker, "INFO", "PRODUCTION_STEP19_BLOCKED", "Production Step19 is blocked; this run is diagnostic only.", "STEP19-SHADOW-20", "production_step19_allowed"))

        warning_count = sum(1 for reason in ticker_reasons if reason["severity"] == "WARN")
        critical_count = sum(1 for reason in ticker_reasons if reason["severity"] == "CRITICAL")
        if critical_count:
            shadow_status = "SHADOW_BLOCKED_CRITICAL_DATA"
        elif warning_count:
            shadow_status = "SHADOW_CONDITIONAL_DIAGNOSTIC_ONLY"
        else:
            shadow_status = "SHADOW_READY_DIAGNOSTIC_ONLY"
        diagnostics.append(
            {
                "ticker": ticker,
                "shadow_status": shadow_status,
                "input_market_status": input_market_status,
                "input_finance_status": input_finance_status,
                "readiness_status_from_real_data_02": readiness_status,
                "market_source_confidence": market_confidence,
                "finance_source_confidence": finance_confidence,
                "independent_current_source_family_count": independent_count,
                "missing_required_fields": missing_fields,
                "warning_count": warning_count,
                "critical_issue_count": critical_count,
                "shadow_engine_ran": critical_count == 0,
                "production_step19_allowed": False,
                "investment_recommendation_allowed": False,
                "valuation_allowed": False,
                "notes": "Diagnostic plumbing only; market primary-only; finance provisional low.",
            }
        )
        all_reasons.extend(ticker_reasons)
    return pd.DataFrame(diagnostics, columns=DIAGNOSTIC_COLUMNS), pd.DataFrame(all_reasons, columns=REASON_COLUMNS)


def build_decision(
    *,
    diagnostics: pd.DataFrame,
    reasons: pd.DataFrame,
    missing_inputs: list[str],
    config_errors: list[str],
    expected_count: int,
    core_outputs_modified: bool,
    forbidden_hits: list[str],
) -> dict[str, Any]:
    pilot_count = int(len(diagnostics))
    critical_issue_count = int(diagnostics["critical_issue_count"].astype(int).sum()) if not diagnostics.empty else int(bool(missing_inputs or config_errors))
    warning_count = int(diagnostics["warning_count"].astype(int).sum()) if not diagnostics.empty else 0
    production_count = _true_count(diagnostics, "production_step19_allowed")
    actionable_count = _true_count(diagnostics, "investment_recommendation_allowed")
    valuation_count = _true_count(diagnostics, "valuation_allowed")
    blocked_count = int(diagnostics["shadow_status"].astype(str).str.startswith("SHADOW_BLOCKED").sum()) if not diagnostics.empty else 0
    row_count_mismatch = pilot_count != expected_count
    no_go_reasons = []
    if missing_inputs:
        no_go_reasons.append("NO_GO_MISSING_INPUT")
    if config_errors:
        no_go_reasons.append("NO_GO_SCHEMA_OR_CONFIG")
    if row_count_mismatch:
        no_go_reasons.append("NO_GO_TICKER_COUNT_MISMATCH")
    if forbidden_hits:
        no_go_reasons.append("NO_GO_FORBIDDEN_OUTPUT")
    if core_outputs_modified:
        no_go_reasons.append("NO_GO_CORE_OUTPUT_MUTATION")
    if production_count or actionable_count or valuation_count:
        no_go_reasons.append("NO_GO_ACTIONABLE_OUTPUT")

    if no_go_reasons:
        final_decision = "NO_GO_FIX_SHADOW_PIPELINE"
        allowed_next_step = "Fix STEP19-SHADOW-20 inputs or safety issues before any next pilot step."
    elif critical_issue_count:
        final_decision = "NO_GO_FIX_SHADOW_PIPELINE"
        allowed_next_step = "Fix critical shadow data issues before any next pilot step."
    elif warning_count:
        final_decision = "CONDITIONAL_GO_FOR_ALT_SOURCE_FIX_OR_SCALE_PILOT"
        allowed_next_step = "Fix alternative source importability and rerun 04B, or scale pilot only with explicit approval; do not run production Step19 yet."
    else:
        final_decision = "PASS_SHADOW_DIAGNOSTIC_PLUMBING"
        allowed_next_step = "Diagnostic plumbing passed; production Step19 remains blocked until explicitly authorized."
    if final_decision not in DECISION_VALUES:
        raise ValueError(f"Invalid STEP19 shadow decision: {final_decision}")
    return {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "pilot_ticker_count": pilot_count,
        "expected_pilot_ticker_count": expected_count,
        "shadow_ready_count": _status_count(diagnostics, "SHADOW_READY_DIAGNOSTIC_ONLY"),
        "shadow_conditional_count": _status_count(diagnostics, "SHADOW_CONDITIONAL_DIAGNOSTIC_ONLY"),
        "shadow_blocked_count": blocked_count,
        "critical_issue_count": critical_issue_count,
        "warning_count": warning_count,
        "forbidden_terms_found": forbidden_hits,
        "production_step19_allowed_count": production_count,
        "investment_recommendation_allowed_count": actionable_count,
        "valuation_allowed_count": valuation_count,
        "market_source_confidence_distribution": _distribution(diagnostics, "market_source_confidence"),
        "finance_source_confidence_distribution": _distribution(diagnostics, "finance_source_confidence"),
        "missing_inputs": missing_inputs,
        "config_errors": config_errors,
        "no_go_reasons": no_go_reasons,
        "core_outputs_modified": core_outputs_modified,
        "final_decision": final_decision,
        "allowed_next_step": allowed_next_step,
        "not_authorized": [
            "production_step19",
            "REAL-DATA-02_rerun",
            "top500_refresh",
            "full_universe_live_fetch",
            "official_pdf_fetch",
            "OCR",
            "valuation",
            "target_price",
            "buy_sell_hold_recommendation",
        ],
    }


def build_readiness_summary(diagnostics: pd.DataFrame, reasons: pd.DataFrame, decision: dict[str, Any]) -> pd.DataFrame:
    metrics = {
        "generated_at": decision.get("generated_at", ""),
        "pilot_ticker_count": decision.get("pilot_ticker_count", 0),
        "shadow_ready_count": decision.get("shadow_ready_count", 0),
        "shadow_conditional_count": decision.get("shadow_conditional_count", 0),
        "shadow_blocked_count": decision.get("shadow_blocked_count", 0),
        "critical_issue_count": decision.get("critical_issue_count", 0),
        "warning_count": decision.get("warning_count", 0),
        "forbidden_terms_found": len(decision.get("forbidden_terms_found", [])),
        "production_step19_allowed_count": decision.get("production_step19_allowed_count", 0),
        "investment_recommendation_allowed_count": decision.get("investment_recommendation_allowed_count", 0),
        "valuation_allowed_count": decision.get("valuation_allowed_count", 0),
        "market_source_confidence_distribution": json.dumps(decision.get("market_source_confidence_distribution", {}), sort_keys=True),
        "finance_source_confidence_distribution": json.dumps(decision.get("finance_source_confidence_distribution", {}), sort_keys=True),
        "finance_field_missing_count": int(reasons["reason_code"].eq("FINANCE_FIELD_MISSING").sum()) if not reasons.empty else 0,
        "final_decision": decision.get("final_decision", ""),
    }
    return pd.DataFrame([{"metric": key, "value": value} for key, value in metrics.items()], columns=SUMMARY_COLUMNS)


def build_blocked_actionable_outputs_audit(diagnostics: pd.DataFrame, forbidden_hits: list[str]) -> pd.DataFrame:
    rows = [
        _audit("production_step19_allowed_count", _true_count(diagnostics, "production_step19_allowed"), 0, "Production Step19 must stay blocked."),
        _audit("investment_recommendation_allowed_count", _true_count(diagnostics, "investment_recommendation_allowed"), 0, "Actionable company output must stay blocked."),
        _audit("valuation_allowed_count", _true_count(diagnostics, "valuation_allowed"), 0, "Valuation output must stay blocked."),
        _audit("forbidden_terms_found_count", len(forbidden_hits), 0, ";".join(forbidden_hits)),
    ]
    return pd.DataFrame(rows, columns=AUDIT_COLUMNS)


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
        "portfolio weight",
        "entry signal",
        "exit signal",
        "good stock",
        "bad stock",
        "official bctc verification",
        "recommendation",
    ]
    allowed_contexts = [
        "not_authorized",
        "blocked",
        "allowed_count",
        "investment_recommendation_allowed",
        "does not authorize",
        "no actionable",
        "forbidden_terms_found",
        "forbidden_terms_found_count",
        "safety",
    ]
    hits = []
    for path in sorted(output_dir.glob("*")):
        if path.suffix.lower() not in {".csv", ".json", ".md", ".txt"}:
            continue
        text = _scan_text(path)
        for line_no, line in enumerate(text.splitlines(), start=1):
            lower = line.lower()
            if any(context in lower for context in allowed_contexts):
                continue
            for term in terms:
                if term in lower:
                    hits.append(f"{path.name}:{line_no}:{term}")
    return hits


def build_summary_markdown(decision: dict[str, Any]) -> str:
    no_go_reasons = decision.get("no_go_reasons", [])
    lines = [
        "# STEP19-SHADOW-20 Summary",
        "",
        f"- generated_at: {decision.get('generated_at', '')}",
        f"- pilot_ticker_count: {decision.get('pilot_ticker_count', 0)}",
        f"- shadow_ready_count: {decision.get('shadow_ready_count', 0)}",
        f"- shadow_conditional_count: {decision.get('shadow_conditional_count', 0)}",
        f"- shadow_blocked_count: {decision.get('shadow_blocked_count', 0)}",
        f"- critical_issue_count: {decision.get('critical_issue_count', 0)}",
        f"- warning_count: {decision.get('warning_count', 0)}",
        f"- forbidden_terms_found: {len(decision.get('forbidden_terms_found', []))}",
        f"- production_step19_allowed_count: {decision.get('production_step19_allowed_count', 0)}",
        f"- investment_recommendation_allowed_count: {decision.get('investment_recommendation_allowed_count', 0)}",
        f"- valuation_allowed_count: {decision.get('valuation_allowed_count', 0)}",
        f"- market_source_confidence_distribution: {decision.get('market_source_confidence_distribution', {})}",
        f"- finance_source_confidence_distribution: {decision.get('finance_source_confidence_distribution', {})}",
        f"- final_decision: {decision.get('final_decision', '')}",
    ]
    if no_go_reasons:
        lines.append(f"- no_go_reasons: {no_go_reasons}")
    lines.extend(
        [
            "",
            "## Interpretation",
            "- This validates plumbing only.",
            "- This does not validate investment quality.",
            "- This does not authorize production Step19.",
            "- This does not authorize recommendations or valuation.",
            "- Market confidence remains primary-only because 04B found no independent current source-family.",
            "- Finance confidence remains provisional low because it is still one-source-only.",
            "",
            "## Allowed Next Step",
            "- Fix alternative source importability and rerun 04B.",
            "- Scale pilot to 100 only if the user explicitly approves.",
            "- Do not run production Step19 yet.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_outputs(
    output: Path,
    diagnostics: pd.DataFrame,
    reasons: pd.DataFrame,
    readiness_summary: pd.DataFrame,
    audit: pd.DataFrame,
    decision: dict[str, Any],
) -> None:
    diagnostics.to_csv(output / "company_shadow_diagnostics_20.csv", index=False)
    reasons.to_csv(output / "company_shadow_reason_codes_20.csv", index=False)
    readiness_summary.to_csv(output / "company_shadow_readiness_summary.csv", index=False)
    audit.to_csv(output / "blocked_actionable_outputs_audit.csv", index=False)
    (output / "step19_shadow_summary.md").write_text(build_summary_markdown(decision), encoding="utf-8")
    (output / "step19_shadow_decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")


def _missing_input_outputs(tickers: list[str], missing_inputs: list[str], config_errors: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not tickers:
        return pd.DataFrame(columns=DIAGNOSTIC_COLUMNS), pd.DataFrame(columns=REASON_COLUMNS)
    reason_message = "Missing required logical inputs: " + ",".join(missing_inputs + config_errors)
    diagnostics = []
    reasons = []
    for ticker in tickers:
        diagnostics.append(
            {
                "ticker": ticker,
                "shadow_status": "SHADOW_BLOCKED_MISSING_INPUT",
                "input_market_status": "NO_GO_MISSING_INPUT",
                "input_finance_status": "NO_GO_MISSING_INPUT",
                "readiness_status_from_real_data_02": "NO_GO_MISSING_INPUT",
                "market_source_confidence": "NO_GO_MISSING_INPUT",
                "finance_source_confidence": "NO_GO_MISSING_INPUT",
                "independent_current_source_family_count": 0,
                "missing_required_fields": ",".join(missing_inputs + config_errors),
                "warning_count": 0,
                "critical_issue_count": 1,
                "shadow_engine_ran": False,
                "production_step19_allowed": False,
                "investment_recommendation_allowed": False,
                "valuation_allowed": False,
                "notes": "NO_GO_MISSING_INPUT",
            }
        )
        reasons.append(_reason(ticker, "CRITICAL", "NO_GO_MISSING_INPUT", reason_message, "STEP19-SHADOW-20", "inputs"))
    return pd.DataFrame(diagnostics, columns=DIAGNOSTIC_COLUMNS), pd.DataFrame(reasons, columns=REASON_COLUMNS)


def _critical_reasons_for_schema(ticker: str, schema_errors: list[str]) -> list[dict[str, Any]]:
    return [_reason(ticker, "CRITICAL", "NO_GO_MISSING_INPUT", error, "STEP19-SHADOW-20", "schema") for error in schema_errors]


def _reason(ticker: str, severity: str, reason_code: str, reason_message: str, source_file: str | Path, field_name: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "severity": severity,
        "reason_code": reason_code,
        "reason_message": reason_message,
        "source_file": str(source_file),
        "field_name": field_name,
    }


def _audit(audit_item: str, observed: int, expected: int, detail: str) -> dict[str, Any]:
    return {
        "audit_item": audit_item,
        "status": "PASS" if observed == expected else "FAIL",
        "observed_value": observed,
        "expected_value": expected,
        "detail": detail,
    }


def _snapshot_market_status(row: dict[str, Any]) -> str:
    if not row:
        return "PRIMARY_MISSING"
    if _as_bool(row.get("missing_market_flag")) or _is_missing(row.get("last_close")) or _is_missing(row.get("last_price_date")):
        return "PRIMARY_MISSING"
    if _as_bool(row.get("stale_price_flag")):
        return "REFERENCE_STALE"
    return "PRIMARY_OK"


def _raw_cache_tickers(observations: pd.DataFrame) -> set[str]:
    if observations.empty or "source_provider_id" not in observations.columns:
        return set()
    rows = observations[observations["source_provider_id"].astype(str).eq("raw_cache_current_market_03")]
    return set(rows.get("ticker", pd.Series(dtype=str)).astype(str).str.upper())


def _hashes(paths: list[Path]) -> dict[str, str]:
    return {str(path): _hash_file(path) for path in paths if path.exists()}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: str | Path) -> pd.DataFrame:
    if not path:
        return pd.DataFrame()
    target = Path(path)
    if not target.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(target, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _snapshot_tickers(frame: pd.DataFrame) -> list[str]:
    if frame.empty or "ticker" not in frame.columns:
        return []
    return [ticker for ticker in frame["ticker"].astype(str).str.strip().str.upper().drop_duplicates().tolist() if ticker]


def _index_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty or "ticker" not in frame.columns:
        return {}
    out = {}
    for _, row in frame.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        if ticker and ticker not in out:
            out[ticker] = row.to_dict()
    return out


def _split_fields(value: Any) -> list[str]:
    if _is_missing(value):
        return []
    return [field.strip() for field in str(value).replace(";", ",").split(",") if field.strip()]


def _true_count(frame: pd.DataFrame, column: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    return int(frame[column].map(_as_bool).sum())


def _status_count(frame: pd.DataFrame, status: str) -> int:
    if frame.empty or "shadow_status" not in frame.columns:
        return 0
    return int(frame["shadow_status"].eq(status).sum())


def _distribution(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame.columns:
        return {}
    counts = Counter(frame[column].astype(str))
    return {key: int(counts[key]) for key in sorted(counts)}


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if _is_missing(value):
            return default
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


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
