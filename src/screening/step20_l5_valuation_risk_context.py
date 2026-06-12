"""STEP20 L5 valuation/risk context engine.

This module produces provisional context only. It reads existing artifacts and
does not fetch, infer, fill, or issue action labels.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


STEP_ID = "STEP20-L5-VALUATION-RISK-CONTEXT"
MODE = "valuation_risk_context_only"

VALUATION_CONTEXT_VALUES = {
    "RELATIVE_VALUATION_CHEAP_CONTEXT",
    "RELATIVE_VALUATION_NEUTRAL_CONTEXT",
    "RELATIVE_VALUATION_EXPENSIVE_CONTEXT",
    "VALUATION_CONTEXT_INSUFFICIENT_DATA",
    "VALUATION_CONTEXT_MANUAL_REVIEW",
    "VALUATION_CONTEXT_NOT_APPLICABLE",
}

VALUATION_RELATIVE_VALUES = {
    "LOWER_THAN_PEER_CONTEXT",
    "AROUND_PEER_CONTEXT",
    "HIGHER_THAN_PEER_CONTEXT",
    "PEER_COMPARISON_INSUFFICIENT",
    "PEER_GROUP_TOO_SMALL",
    "UNKNOWN",
}

VALUATION_CONFIDENCE_VALUES = {"LOW", "MEDIUM", "HIGH", "INSUFFICIENT", "MANUAL_REVIEW"}

STEP20_STATUS_VALUES = {
    "STEP20_CONTEXT_READY",
    "STEP20_CONTEXT_LOW_CONFIDENCE",
    "STEP20_MANUAL_REVIEW_REQUIRED",
    "STEP20_INSUFFICIENT_DATA",
    "STEP20_BLOCKED_GUARDRAIL_VIOLATION",
}

RISK_CONTEXT_VALUES = {
    "LOW_CONTEXT_RISK",
    "MODERATE_CONTEXT_RISK",
    "ELEVATED_CONTEXT_RISK",
    "HIGH_CONTEXT_RISK",
    "INSUFFICIENT_DATA_RISK",
}

FINAL_DECISIONS = {
    "CONDITIONAL_GO_FOR_STEP21_TIMING_LIQUIDITY",
    "PASS_WITH_MANUAL_REVIEW_WARNINGS",
    "BLOCKED_GUARDRAIL_VIOLATION",
    "BLOCKED_NO_USABLE_INPUT",
}

FORBIDDEN_FINAL_DECISIONS = {
    "PASS_FOR_INVESTMENT",
    "PASS_FOR_VALUATION",
    "PASS_FOR_RECOMMENDATION",
}

FORBIDDEN_TERMS = [
    "buy",
    "sell",
    "hold",
    "target price",
    "fair value",
    "intrinsic value",
    "margin of safety",
    "expected return",
    "upside",
    "downside",
    "entry price",
    "exit price",
    "stoploss",
    "take profit",
    "recommended portfolio",
    "investment-ready",
]

FINANCE_FIELDS = [
    "revenue",
    "gross_profit",
    "net_income",
    "total_assets",
    "total_liabilities",
    "equity",
    "cfo",
    "capex",
]

ROW_COLUMNS = [
    "ticker",
    "company_name",
    "primary_sector",
    "primary_micro_sector",
    "archetype",
    "peer_group_id",
    "peer_group_size",
    "market_source_confidence",
    "finance_source_confidence",
    "crosscheck_status",
    "verification_status",
    "valuation_context",
    "valuation_relative_to_peer",
    "valuation_risk_score",
    "provisional_risk_context_score",
    "valuation_confidence",
    "risk_flags",
    "manual_review_required",
    "manual_review_reason",
    "missing_fields",
    "source_conflicts",
    "evidence_debt_reason",
    "step20_status",
]

VALUATION_CONTEXT_COLUMNS = [
    "ticker",
    "primary_micro_sector",
    "archetype",
    "peer_group_id",
    "peer_group_size",
    "valuation_context",
    "valuation_relative_to_peer",
    "valuation_confidence",
    "step20_status",
]

RISK_FLAG_COLUMNS = [
    "ticker",
    "valuation_risk_score",
    "provisional_risk_context_score",
    "risk_flags",
    "manual_review_required",
    "manual_review_reason",
]

MANUAL_QUEUE_COLUMNS = [
    "ticker",
    "company_name",
    "primary_sector",
    "primary_micro_sector",
    "archetype",
    "manual_review_reason",
    "missing_fields",
    "risk_flags",
    "evidence_debt_reason",
    "verification_status",
]


class Step20SafeRunBlocked(RuntimeError):
    """Raised when a requested run violates STEP20 scope controls."""


@dataclass
class Step20Result:
    rows: pd.DataFrame
    valuation_context_by_ticker: pd.DataFrame
    risk_flags_by_ticker: pd.DataFrame
    manual_review_queue: pd.DataFrame
    peer_context_summary: pd.DataFrame
    evidence_debt: dict[str, Any]
    run_manifest: dict[str, Any]
    summary: dict[str, Any]


def load_step20_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("STEP20 config must be a mapping.")
    return data


def run_step20_l5_valuation_risk_context(
    *,
    config_path: str | Path,
    output_dir: str | Path | None = None,
    limit: int | None = None,
    allow_partial: bool | None = None,
    request_full_universe: bool = False,
    command_used: str = "",
    core_output_paths: list[str | Path] | None = None,
) -> Step20Result:
    config = load_step20_config(config_path)
    validate_step20_config(config)
    output = Path(output_dir or ((config.get("outputs") or {}).get("output_dir") or "data/reports/step20_l5_valuation_risk_context"))
    output.mkdir(parents=True, exist_ok=True)
    limits = config.get("limits") or {}
    if request_full_universe and not _as_bool(limits.get("full_universe_allowed", False)):
        raise Step20SafeRunBlocked("Full-universe STEP20 run is blocked by config.")

    max_tickers = int(limits.get("max_tickers", 100) or 100)
    requested_limit = max_tickers if limit is None else int(limit)
    effective_limit = min(requested_limit, max_tickers)
    warnings = []
    if requested_limit > max_tickers:
        warnings.append(f"Requested limit {requested_limit} capped to configured max {max_tickers}.")

    run_policy = dict(config.get("run") or {})
    if allow_partial is not None:
        run_policy["allow_partial"] = bool(allow_partial)
    allow_partial_effective = _as_bool(run_policy.get("allow_partial", True))

    core_paths = [Path(path) for path in (core_output_paths or config.get("core_output_watchlist", []))]
    before_hashes = _hashes(core_paths)
    frames, resolved_inputs, missing_inputs = load_step20_inputs(config, allow_partial=allow_partial_effective)
    if missing_inputs and not allow_partial_effective:
        raise Step20SafeRunBlocked("STEP20 missing input while allow_partial=false: " + ",".join(missing_inputs))

    rows = build_step20_rows(
        config=config,
        step05a_rows=frames.get("step05a_rows", pd.DataFrame()),
        finance_wide=frames.get("finance_latest_wide", pd.DataFrame()),
        finance_quality=frames.get("finance_quality_flags", pd.DataFrame()),
        market_snapshot=frames.get("market_snapshot", pd.DataFrame()),
        ranking_metadata=frames.get("ranking_metadata", pd.DataFrame()),
        step19_rows=frames.get("step19_rows", pd.DataFrame()),
        limit=effective_limit,
        missing_inputs=missing_inputs,
    )
    valuation_context = rows.reindex(columns=VALUATION_CONTEXT_COLUMNS)
    risk_flags = rows.reindex(columns=RISK_FLAG_COLUMNS)
    manual_queue = rows[rows["manual_review_required"].map(_as_bool)].reindex(columns=MANUAL_QUEUE_COLUMNS) if not rows.empty else pd.DataFrame(columns=MANUAL_QUEUE_COLUMNS)
    peer_summary = build_peer_context_summary(rows)
    core_modified = before_hashes != _hashes(core_paths)

    write_step20_outputs(
        output_dir=output,
        rows=rows,
        valuation_context=valuation_context,
        risk_flags=risk_flags,
        manual_queue=manual_queue,
        peer_summary=peer_summary,
        summary={},
        evidence_debt={},
        manifest={},
    )
    forbidden_hits = scan_forbidden_terms(output)
    summary = build_summary(
        config=config,
        rows=rows,
        manual_queue=manual_queue,
        missing_inputs=missing_inputs,
        warnings=warnings,
        forbidden_hits=forbidden_hits,
        core_outputs_modified=core_modified,
    )
    evidence_debt = build_evidence_debt(rows, summary, missing_inputs)
    manifest = build_run_manifest(
        config=config,
        config_path=Path(config_path),
        output_dir=output,
        effective_limit=effective_limit,
        allow_partial=allow_partial_effective,
        command_used=command_used,
        core_outputs_modified=core_modified,
        resolved_inputs=resolved_inputs,
        missing_inputs=missing_inputs,
    )
    write_step20_outputs(
        output_dir=output,
        rows=rows,
        valuation_context=valuation_context,
        risk_flags=risk_flags,
        manual_queue=manual_queue,
        peer_summary=peer_summary,
        summary=summary,
        evidence_debt=evidence_debt,
        manifest=manifest,
    )
    forbidden_hits = scan_forbidden_terms(output)
    if forbidden_hits != summary["forbidden_terms_found"]:
        summary = build_summary(
            config=config,
            rows=rows,
            manual_queue=manual_queue,
            missing_inputs=missing_inputs,
            warnings=warnings,
            forbidden_hits=forbidden_hits,
            core_outputs_modified=core_modified,
        )
        write_step20_outputs(
            output_dir=output,
            rows=rows,
            valuation_context=valuation_context,
            risk_flags=risk_flags,
            manual_queue=manual_queue,
            peer_summary=peer_summary,
            summary=summary,
            evidence_debt=evidence_debt,
            manifest=manifest,
        )
    return Step20Result(rows, valuation_context, risk_flags, manual_queue, peer_summary, evidence_debt, manifest, summary)


def validate_step20_config(config: dict[str, Any]) -> None:
    if config.get("step_id") != STEP_ID:
        raise ValueError(f"STEP20 config step_id must be {STEP_ID}.")
    safety = config.get("safety") if isinstance(config.get("safety"), dict) else {}
    required = [
        "no_recommendation",
        "no_buy_sell_hold",
        "no_target_price",
        "no_fair_value",
        "no_intrinsic_value",
        "no_margin_of_safety",
        "no_expected_return",
        "no_entry_exit_price",
        "no_portfolio_recommendation",
        "no_zero_fill",
        "no_missing_finance_inference",
        "no_pdf_ocr",
        "no_official_bctc_scrape",
        "no_core_output_mutation",
        "no_stage_promotion_to_investment_ready",
        "no_cross_sector_comparison",
    ]
    missing = [key for key in required if safety.get(key) is not True]
    if missing:
        raise ValueError(f"STEP20 safety flags must be true: {','.join(missing)}")


def load_step20_inputs(config: dict[str, Any], *, allow_partial: bool) -> tuple[dict[str, pd.DataFrame], dict[str, str], list[str]]:
    frames: dict[str, pd.DataFrame] = {}
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for logical_name, spec in (config.get("inputs") or {}).items():
        if logical_name.endswith("_decision"):
            resolved_path = _first_existing_path(spec)
            if resolved_path is None:
                missing.append(str(logical_name))
            else:
                resolved[str(logical_name)] = str(resolved_path)
            continue
        resolved_path = _first_existing_path(spec)
        if resolved_path is None:
            missing.append(str(logical_name))
            frames[str(logical_name)] = pd.DataFrame()
        else:
            resolved[str(logical_name)] = str(resolved_path)
            frames[str(logical_name)] = _read_csv(resolved_path)
    if missing and not allow_partial:
        return frames, resolved, missing
    return frames, resolved, missing


def build_step20_rows(
    *,
    config: dict[str, Any],
    step05a_rows: pd.DataFrame,
    finance_wide: pd.DataFrame,
    finance_quality: pd.DataFrame,
    market_snapshot: pd.DataFrame,
    ranking_metadata: pd.DataFrame,
    step19_rows: pd.DataFrame,
    limit: int,
    missing_inputs: list[str],
) -> pd.DataFrame:
    confidence = config.get("source_confidence") or {}
    step05a = _frame(step05a_rows)
    tickers = _ticker_list(step05a)[:limit]
    finance_by_ticker = _index_by_ticker(finance_wide)
    quality_by_ticker = _index_by_ticker(finance_quality)
    market_by_ticker = _index_by_ticker(market_snapshot)
    meta_by_ticker = _index_by_ticker(ranking_metadata)
    step19_by_ticker = _index_by_ticker(step19_rows)
    peer_info = build_peer_groups(tickers, meta_by_ticker, finance_by_ticker)
    rows = []
    for ticker in tickers:
        step05a_row = _row_for_ticker(step05a, ticker)
        finance = finance_by_ticker.get(ticker, {})
        quality = quality_by_ticker.get(ticker, {})
        market = market_by_ticker.get(ticker, {})
        meta = meta_by_ticker.get(ticker, {})
        shadow = step19_by_ticker.get(ticker, {})
        sector = _primary_sector(meta, finance)
        micro = _primary_micro_sector(meta, finance)
        archetype = _archetype(meta, finance)
        peer_group_id = _peer_group_id(micro, archetype)
        peer_group_size = int(peer_info.get(peer_group_id, {}).get("size", 0))
        missing_fields = _missing_fields(step05a_row, finance, market, missing_inputs)
        risk_flags = _risk_flags(missing_fields, step05a_row, shadow, peer_group_size, sector, micro)
        valuation_context, relative, confidence_label, status = _valuation_context(peer_group_size, missing_fields, risk_flags, config)
        manual_review = status != "STEP20_CONTEXT_READY"
        manual_reason = _manual_review_reason(status, peer_group_size, missing_fields, missing_inputs)
        evidence_debt = [
            "No independent current market source-family confirmation.",
            "Official BCTC evidence has not been checked.",
            "Step20 provides context only and requires human review.",
        ]
        if missing_inputs:
            evidence_debt.append("Some configured inputs were unavailable.")
        risk_score = _risk_context_score(risk_flags)
        rows.append(
            {
                "ticker": ticker,
                "company_name": finance.get("company_name", ""),
                "primary_sector": sector,
                "primary_micro_sector": micro,
                "archetype": archetype,
                "peer_group_id": peer_group_id,
                "peer_group_size": peer_group_size,
                "market_source_confidence": confidence.get("market_source_confidence", "PROVISIONAL_PRIMARY_ONLY"),
                "finance_source_confidence": confidence.get("finance_source_confidence_default", "PROVISIONAL_LOW"),
                "crosscheck_status": confidence.get("crosscheck_status", "NOT_AVAILABLE"),
                "verification_status": confidence.get("verification_status", "NEEDS_MANUAL_BCTC_REVIEW"),
                "valuation_context": valuation_context,
                "valuation_relative_to_peer": relative,
                "valuation_risk_score": risk_score,
                "provisional_risk_context_score": _numeric_risk_context_score(risk_flags),
                "valuation_confidence": confidence_label,
                "risk_flags": _json_list(risk_flags),
                "manual_review_required": bool(manual_review),
                "manual_review_reason": manual_reason,
                "missing_fields": _json_list(missing_fields),
                "source_conflicts": _json_list([]),
                "evidence_debt_reason": _json_list(evidence_debt),
                "step20_status": status,
            }
        )
    return pd.DataFrame(rows, columns=ROW_COLUMNS)


def build_peer_groups(tickers: list[str], meta_by_ticker: dict[str, dict[str, Any]], finance_by_ticker: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for ticker in tickers:
        meta = meta_by_ticker.get(ticker, {})
        finance = finance_by_ticker.get(ticker, {})
        peer_id = _peer_group_id(_primary_micro_sector(meta, finance), _archetype(meta, finance))
        groups.setdefault(peer_id, {"size": 0, "tickers": []})
        groups[peer_id]["size"] += 1
        groups[peer_id]["tickers"].append(ticker)
    return groups


def build_peer_context_summary(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=["peer_group_id", "primary_micro_sector", "archetype", "peer_group_size", "ticker_count", "context_ready_count", "manual_review_count"])
    summary_rows = []
    for peer_group_id, group in rows.groupby("peer_group_id"):
        summary_rows.append(
            {
                "peer_group_id": peer_group_id,
                "primary_micro_sector": _first_value(group, "primary_micro_sector"),
                "archetype": _first_value(group, "archetype"),
                "peer_group_size": int(group["ticker"].nunique()),
                "ticker_count": int(len(group)),
                "context_ready_count": int(group["step20_status"].eq("STEP20_CONTEXT_READY").sum()),
                "manual_review_count": int(group["manual_review_required"].map(_as_bool).sum()),
            }
        )
    return pd.DataFrame(summary_rows)


def build_summary(
    *,
    config: dict[str, Any],
    rows: pd.DataFrame,
    manual_queue: pd.DataFrame,
    missing_inputs: list[str],
    warnings: list[str],
    forbidden_hits: list[str],
    core_outputs_modified: bool,
) -> dict[str, Any]:
    confidence = config.get("source_confidence") or {}
    blocked_guardrail_count = int(rows["step20_status"].eq("STEP20_BLOCKED_GUARDRAIL_VIOLATION").sum()) if not rows.empty else 0
    context_ready_count = int(rows["step20_status"].eq("STEP20_CONTEXT_READY").sum()) if not rows.empty else 0
    insufficient_count = int(rows["step20_status"].eq("STEP20_INSUFFICIENT_DATA").sum()) if not rows.empty else 0
    if forbidden_hits or core_outputs_modified or blocked_guardrail_count:
        final_decision = "BLOCKED_GUARDRAIL_VIOLATION"
    elif rows.empty:
        final_decision = "BLOCKED_NO_USABLE_INPUT"
    elif context_ready_count > 0:
        final_decision = "CONDITIONAL_GO_FOR_STEP21_TIMING_LIQUIDITY"
    else:
        final_decision = "PASS_WITH_MANUAL_REVIEW_WARNINGS"
    if final_decision in FORBIDDEN_FINAL_DECISIONS:
        raise ValueError(f"Forbidden STEP20 final decision: {final_decision}")
    all_warnings = list(warnings)
    all_warnings.extend(
        [
            "Primary-only market confidence remains in force.",
            "Finance confidence remains low and provisional.",
            "Official BCTC review remains required.",
        ]
    )
    if missing_inputs:
        all_warnings.append("Some configured inputs were unavailable.")
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "processed_ticker_count": int(len(rows)),
        "context_ready_count": context_ready_count,
        "manual_review_count": int(len(manual_queue)),
        "insufficient_data_count": insufficient_count,
        "blocked_guardrail_count": blocked_guardrail_count,
        "missing_input_files": missing_inputs,
        "market_source_confidence": confidence.get("market_source_confidence", "PROVISIONAL_PRIMARY_ONLY"),
        "finance_source_confidence_default": confidence.get("finance_source_confidence_default", "PROVISIONAL_LOW"),
        "crosscheck_status": confidence.get("crosscheck_status", "NOT_AVAILABLE"),
        "verification_status": confidence.get("verification_status", "NEEDS_MANUAL_BCTC_REVIEW"),
        "final_decision": final_decision,
        "warnings": all_warnings,
        "forbidden_terms_found": forbidden_hits,
        "core_outputs_modified": bool(core_outputs_modified),
    }


def build_evidence_debt(rows: pd.DataFrame, summary: dict[str, Any], missing_inputs: list[str]) -> dict[str, Any]:
    risk_counts: dict[str, int] = {}
    for value in rows.get("risk_flags", pd.Series(dtype=str)).astype(str):
        for flag in _parse_json_list(value):
            risk_counts[flag] = risk_counts.get(flag, 0) + 1
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "limitations": [
            "No independent current market source-family confirmation.",
            "Official BCTC evidence has not been checked.",
            "Peer context may be unavailable when peer group or fields are insufficient.",
            "No action label or price objective is produced.",
        ],
        "missing_input_files": missing_inputs,
        "processed_ticker_count": int(summary.get("processed_ticker_count", 0)),
        "manual_review_count": int(summary.get("manual_review_count", 0)),
        "risk_flag_counts": dict(sorted(risk_counts.items())),
    }


def build_run_manifest(
    *,
    config: dict[str, Any],
    config_path: Path,
    output_dir: Path,
    effective_limit: int,
    allow_partial: bool,
    command_used: str,
    core_outputs_modified: bool,
    resolved_inputs: dict[str, str],
    missing_inputs: list[str],
) -> dict[str, Any]:
    limits = config.get("limits") or {}
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "commit_hash": _git_commit_hash(),
        "command_used": command_used,
        "config_path": str(config_path),
        "output_dir": str(output_dir),
        "max_tickers": int(effective_limit),
        "allow_partial": bool(allow_partial),
        "full_universe_allowed": _as_bool(limits.get("full_universe_allowed", False)),
        "network_usage_if_known": "none",
        "core_outputs_modified": bool(core_outputs_modified),
        "previous_step_outputs_mutated": bool(core_outputs_modified),
        "resolved_inputs": resolved_inputs,
        "missing_input_files": missing_inputs,
    }


def write_step20_outputs(
    *,
    output_dir: Path,
    rows: pd.DataFrame,
    valuation_context: pd.DataFrame,
    risk_flags: pd.DataFrame,
    manual_queue: pd.DataFrame,
    peer_summary: pd.DataFrame,
    summary: dict[str, Any],
    evidence_debt: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows.to_csv(output_dir / "step20_valuation_risk_rows.csv", index=False)
    valuation_context.to_csv(output_dir / "valuation_context_by_ticker.csv", index=False)
    risk_flags.to_csv(output_dir / "risk_flags_by_ticker.csv", index=False)
    manual_queue.to_csv(output_dir / "manual_review_queue_step20.csv", index=False)
    peer_summary.to_csv(output_dir / "peer_context_summary.csv", index=False)
    _write_json(output_dir / "step20_valuation_risk_summary.json", summary)
    _write_json(output_dir / "evidence_debt_step20.json", evidence_debt)
    _write_json(output_dir / "run_manifest.json", manifest)


def scan_forbidden_terms(output_dir: Path) -> list[str]:
    hits: list[str] = []
    for path in sorted(output_dir.glob("*")):
        if path.suffix.lower() not in {".csv", ".json", ".md", ".txt"}:
            continue
        text = _scan_text(path)
        for line_no, line in enumerate(text.splitlines(), start=1):
            lower = line.lower()
            for term in FORBIDDEN_TERMS:
                if _term_in_text(term, lower):
                    hits.append(f"{path.name}:{line_no}:{term}")
    return hits


def _term_in_text(term: str, lower_text: str) -> bool:
    if " " in term or "-" in term:
        return term in lower_text
    return re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", lower_text) is not None


def _valuation_context(peer_group_size: int, missing_fields: list[str], risk_flags: list[str], config: dict[str, Any]) -> tuple[str, str, str, str]:
    min_peer = int(((config.get("peer_context") or {}).get("min_peer_group_size", 3) or 3))
    if peer_group_size < min_peer:
        return "VALUATION_CONTEXT_MANUAL_REVIEW", "PEER_GROUP_TOO_SMALL", "MANUAL_REVIEW", "STEP20_MANUAL_REVIEW_REQUIRED"
    if "MISSING_REQUIRED_FINANCE_FIELD" in risk_flags or "VALUATION_CONTEXT_INSUFFICIENT" in risk_flags:
        return "VALUATION_CONTEXT_INSUFFICIENT_DATA", "PEER_COMPARISON_INSUFFICIENT", "INSUFFICIENT", "STEP20_INSUFFICIENT_DATA"
    return "VALUATION_CONTEXT_INSUFFICIENT_DATA", "PEER_COMPARISON_INSUFFICIENT", "LOW", "STEP20_CONTEXT_LOW_CONFIDENCE"


def _risk_flags(missing_fields: list[str], step05a_row: dict[str, Any], shadow: dict[str, Any], peer_group_size: int, sector: str, micro: str) -> list[str]:
    flags = [
        "FINANCE_DATA_LOW_CONFIDENCE",
        "NO_INDEPENDENT_MARKET_CROSSCHECK",
        "OFFICIAL_BCTC_NOT_VERIFIED",
    ]
    if missing_fields:
        flags.append("MISSING_REQUIRED_FINANCE_FIELD")
    if peer_group_size < 3:
        flags.append("PEER_GROUP_TOO_SMALL")
    if _is_missing(sector) or _is_missing(micro) or sector == "UNKNOWN":
        flags.append("SECTOR_CLASSIFICATION_WEAK")
    if _as_bool(step05a_row.get("manual_bctc_required", True)):
        flags.append("SURVIVAL_WEAK_OR_UNKNOWN")
    if str(shadow.get("shadow_status", "")).startswith("SHADOW_BLOCKED"):
        flags.append("SURVIVAL_WEAK_OR_UNKNOWN")
    flags.append("VALUATION_CONTEXT_INSUFFICIENT")
    return sorted(set(flags))


def _risk_context_score(flags: list[str]) -> str:
    if "MISSING_REQUIRED_FINANCE_FIELD" in flags or "SECTOR_CLASSIFICATION_WEAK" in flags:
        return "INSUFFICIENT_DATA_RISK"
    if len(flags) >= 5:
        return "HIGH_CONTEXT_RISK"
    if len(flags) >= 4:
        return "ELEVATED_CONTEXT_RISK"
    if len(flags) >= 2:
        return "MODERATE_CONTEXT_RISK"
    return "LOW_CONTEXT_RISK"


def _numeric_risk_context_score(flags: list[str]) -> int:
    return min(100, 20 + 10 * len(flags))


def _manual_review_reason(status: str, peer_group_size: int, missing_fields: list[str], missing_inputs: list[str]) -> str:
    reasons = []
    if status == "STEP20_CONTEXT_READY":
        return "Context row is available but still requires official evidence review."
    if peer_group_size < 3:
        reasons.append("Peer group is too small for context comparison.")
    if missing_fields:
        reasons.append("Required fields are missing.")
    if missing_inputs:
        reasons.append("Some configured inputs are unavailable.")
    if not reasons:
        reasons.append("Context confidence is low under primary-only evidence.")
    return " ".join(reasons)


def _missing_fields(step05a_row: dict[str, Any], finance: dict[str, Any], market: dict[str, Any], missing_inputs: list[str]) -> list[str]:
    missing = []
    missing.extend(_parse_json_list(str(step05a_row.get("missing_fields", ""))))
    for field in FINANCE_FIELDS:
        if field not in finance or _is_missing(finance.get(field)):
            missing.append(field)
    for field in ["last_close", "last_price_date"]:
        if field not in market or _is_missing(market.get(field)):
            missing.append(field)
    for logical_name in missing_inputs:
        missing.append(f"input:{logical_name}")
    return sorted(set(missing))


def _primary_sector(meta: dict[str, Any], finance: dict[str, Any]) -> str:
    return _clean_label(meta.get("sector_bucket") or finance.get("sector_raw") or "UNKNOWN")


def _primary_micro_sector(meta: dict[str, Any], finance: dict[str, Any]) -> str:
    firm_type = _clean_label(meta.get("firm_type") or finance.get("industry_raw") or "UNKNOWN")
    sector = _primary_sector(meta, finance)
    return _clean_label(f"{sector}::{firm_type}" if firm_type != "UNKNOWN" else sector)


def _archetype(meta: dict[str, Any], finance: dict[str, Any]) -> str:
    firm_type = _clean_label(meta.get("firm_type") or "")
    if firm_type and firm_type != "UNKNOWN":
        return firm_type
    sector = _clean_label(finance.get("sector_raw") or "")
    if "Tài chính" in sector or "bank" in sector.lower():
        return "financial_institution"
    return "unknown_archetype"


def _peer_group_id(micro: str, archetype: str) -> str:
    return _slug(micro) + "__" + _slug(archetype)


def _clean_label(value: Any) -> str:
    text = str(value).strip()
    return text if text else "UNKNOWN"


def _slug(value: Any) -> str:
    text = str(value).strip().lower()
    out = []
    for char in text:
        if char.isalnum():
            out.append(char)
        elif char in {" ", "_", "-", ":", "/", "\\"}:
            out.append("_")
    slug = "".join(out).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "unknown"


def _ticker_list(frame: pd.DataFrame) -> list[str]:
    if frame.empty or "ticker" not in frame.columns:
        return []
    return [ticker for ticker in frame["ticker"].astype(str).str.strip().str.upper().drop_duplicates().tolist() if ticker]


def _index_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    frame = _frame(frame)
    if frame.empty or "ticker" not in frame.columns:
        return {}
    out = {}
    for _, row in frame.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        if ticker and ticker not in out:
            out[ticker] = row.to_dict()
    return out


def _row_for_ticker(frame: pd.DataFrame, ticker: str) -> dict[str, Any]:
    if frame.empty or "ticker" not in frame.columns:
        return {}
    rows = frame[frame["ticker"].astype(str).str.upper().eq(ticker)]
    return rows.iloc[0].to_dict() if not rows.empty else {}


def _first_value(frame: pd.DataFrame, column: str) -> str:
    if frame.empty or column not in frame.columns:
        return ""
    for value in frame[column]:
        if not _is_missing(value):
            return str(value)
    return ""


def _first_existing_path(spec: Any) -> Path | None:
    candidates = spec if isinstance(spec, list) else [spec]
    for candidate in candidates:
        path = Path(str(candidate))
        if path.exists():
            return path
    return None


def _read_csv(path: str | Path) -> pd.DataFrame:
    target = Path(path)
    if not target.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(target, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()


def _json_list(values: list[Any]) -> str:
    return json.dumps([str(value) for value in values if not _is_missing(value)], ensure_ascii=False)


def _parse_json_list(value: str) -> list[str]:
    if _is_missing(value):
        return []
    text = str(value).strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [str(item) for item in parsed if not _is_missing(item)]
        return []
    return [field.strip() for field in text.replace(";", ",").split(",") if field.strip()]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _is_missing(value: Any) -> bool:
    return value is None or str(value).strip() == "" or str(value).strip().lower() in {"nan", "none", "null", "na"}


def _hashes(paths: list[Path]) -> dict[str, str]:
    return {str(path): _hash_file(path) for path in paths if path.exists()}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit_hash() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:  # noqa: BLE001
        return ""
    return completed.stdout.strip()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


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
        data.pop("forbidden_terms_found", None)
    return json.dumps(data, ensure_ascii=False, indent=2)
