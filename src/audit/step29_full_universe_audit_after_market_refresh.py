"""STEP29 full-universe audit after STEP28 market refresh.

This step is read-only with respect to earlier artifacts. It merges the latest
STEP28 market snapshot into the STEP26 full-universe audit view and keeps any
remaining finance/company gaps as manual-review or insufficient-data statuses.
"""

from __future__ import annotations

import ast
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

from src.audit.step26_full_universe_output_audit_first_shortlist import normalize_rows


STEP_ID = "STEP29-FULL-UNIVERSE-AUDIT-AFTER-MARKET-REFRESH"
MODE = "rerun_audit_after_market_refresh"

FINAL_DECISIONS = {
    "PASS_AUDIT_AFTER_MARKET_REFRESH_WITH_SHORTLIST",
    "PASS_AUDIT_AFTER_MARKET_REFRESH_WITH_MANUAL_REVIEW",
    "PASS_AUDIT_AFTER_MARKET_REFRESH_WITH_DATA_GAPS",
    "BLOCKED_MISSING_INPUT",
    "BLOCKED_GUARDRAIL_VIOLATION",
}

MARKET_MISSING_FIELDS = {
    "last_close",
    "last_price_date",
    "last_volume",
    "avg_volume_20d",
    "avg_volume_60d",
}

MARKET_BLOCK_REASONS = {
    "Primary market data missing or incomplete.",
    "primary market data missing or incomplete.",
    "missing_market_data",
}

FINANCE_INSUFFICIENT_STATUSES = {"INSUFFICIENT_DATA", "CACHE_MISSING", "MISSING_DATA"}

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
    "portfolio",
    "recommendation",
]

ALLOWED_SAFETY_LINES = {
    "this report does not contain buy/sell/hold signals.",
}

REQUIRED_SAFETY_FLAGS = [
    "no_recommendation",
    "no_buy_sell_hold",
    "no_target_price",
    "no_fair_value",
    "no_intrinsic_value",
    "no_margin_of_safety",
    "no_expected_return",
    "no_zero_fill",
    "no_mock_sample_data",
    "no_new_data_fetch",
    "no_missing_finance_inference",
]

AUDIT_COLUMNS = [
    "ticker",
    "company_name",
    "exchange_if_available",
    "step26_screening_status",
    "step29_screening_status",
    "step29_review_status",
    "step29_market_recovery_status",
    "watchlist_status",
    "shortlist_eligible",
    "shortlist_exclusion_reason",
    "step29_manual_review_required",
    "manual_bctc_required",
    "market_data_available_after_step28",
    "recent_price_available_after_step28",
    "liquidity_data_available_after_step28",
    "step28_fetch_status",
    "step28_fetch_error_type",
    "step28_last_price_date",
    "step28_last_close",
    "step28_last_volume",
    "last_price_date",
    "last_close",
    "avg_volume_20d",
    "avg_volume_60d",
    "last_volume",
    "recent_trading_value",
    "remaining_missing_fields",
    "remaining_block_reasons",
    "finance_quality_status",
    "finance_source_confidence",
    "market_source_confidence",
    "crosscheck_status",
    "verification_status",
    "data_quality_status",
    "confidence_status",
]

SHORTLIST_COLUMNS = [
    "ticker",
    "company_name",
    "step29_screening_status",
    "step29_review_status",
    "market_data_available_after_step28",
    "last_price_date",
    "last_close",
    "avg_volume_20d",
    "avg_volume_60d",
    "last_volume",
    "recent_trading_value",
    "remaining_missing_fields",
    "finance_quality_status",
    "verification_status",
    "confidence_status",
]

GUARDRAILS = {
    "no_recommendation": True,
    "no_buy_sell_hold": True,
    "no_target_price": True,
    "no_fair_value": True,
    "no_intrinsic_value": True,
    "no_margin_of_safety": True,
    "no_expected_return": True,
    "no_zero_fill": True,
    "no_mock_sample_data": True,
    "no_new_data_fetch": True,
    "no_missing_finance_inference": True,
}


class Step29SafeRunBlocked(RuntimeError):
    """Raised when STEP29 cannot proceed safely."""


@dataclass
class Step29InputResolution:
    step25_rows_path: Path | None
    step26_audit_rows_path: Path | None
    step26_summary_path: Path | None
    step28_market_snapshot_rows_path: Path | None
    step28_summary_path: Path | None
    missing_input_files: list[str]


@dataclass
class Step29Result:
    summary: dict[str, Any]
    audit: pd.DataFrame
    shortlist: pd.DataFrame
    comparison: dict[str, Any]
    guardrail_report: dict[str, Any]
    readme: str


def load_step29_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("STEP29 config must be a mapping.")
    return data


def validate_step29_config(config: dict[str, Any]) -> None:
    if config.get("step_id") != STEP_ID:
        raise ValueError(f"STEP29 config step_id must be {STEP_ID}.")
    safety = config.get("safety") if isinstance(config.get("safety"), dict) else {}
    missing = [key for key in REQUIRED_SAFETY_FLAGS if safety.get(key) is not True]
    if missing:
        raise ValueError(f"STEP29 safety flags must be true: {','.join(missing)}")


def run_step29_full_universe_audit_after_market_refresh(
    *,
    config_path: str | Path,
    output_dir: str | Path | None = None,
    command_used: str = "",
    pytest_result: str | None = None,
    core_output_paths: list[str | Path] | None = None,
) -> Step29Result:
    config = load_step29_config(config_path)
    validate_step29_config(config)
    exports = config.get("exports") if isinstance(config.get("exports"), dict) else {}
    output = Path(output_dir or exports.get("output_dir") or "data/reports/step29_full_universe_audit_after_market_refresh")
    output.mkdir(parents=True, exist_ok=True)
    resolution = resolve_step29_inputs(config)
    core_paths = [Path(path) for path in (core_output_paths or _core_paths_from_resolution(resolution))]
    before_hashes = _hashes(core_paths)

    step25_rows = _read_csv(resolution.step25_rows_path)
    baseline = load_baseline_rows(resolution.step26_audit_rows_path, step25_rows)
    step28_snapshot = _read_csv(resolution.step28_market_snapshot_rows_path)
    step26_summary = _read_json(resolution.step26_summary_path)
    step28_summary = _read_json(resolution.step28_summary_path)

    audit = build_step29_audit(config, baseline, step28_snapshot)
    shortlist = build_step29_shortlist(config, audit)
    comparison = build_step26_comparison(step26_summary, step28_summary, audit, step28_snapshot)
    core_modified = before_hashes != _hashes(core_paths)
    pytest_value = pytest_result or str(config.get("pytest_result") or "NOT_RECORDED")
    summary = build_step29_summary(
        config=config,
        resolution=resolution,
        audit=audit,
        shortlist=shortlist,
        comparison=comparison,
        forbidden_terms_found=[],
        core_outputs_modified=core_modified,
        pytest_result=pytest_value,
    )
    guardrail_report = build_guardrail_report(
        forbidden_terms_found=[],
        core_outputs_modified=core_modified,
        missing_input_files=resolution.missing_input_files,
    )
    readme = build_readme(summary, comparison)
    write_step29_outputs(output, summary, audit, shortlist, comparison, guardrail_report, readme)

    forbidden_hits = scan_forbidden_terms(output)
    if forbidden_hits:
        summary = build_step29_summary(
            config=config,
            resolution=resolution,
            audit=audit,
            shortlist=shortlist,
            comparison=comparison,
            forbidden_terms_found=forbidden_hits,
            core_outputs_modified=core_modified,
            pytest_result=pytest_value,
        )
        guardrail_report = build_guardrail_report(
            forbidden_terms_found=forbidden_hits,
            core_outputs_modified=core_modified,
            missing_input_files=resolution.missing_input_files,
        )
        readme = build_readme(summary, comparison)
        write_step29_outputs(output, summary, audit, shortlist, comparison, guardrail_report, readme)

    return Step29Result(
        summary=summary,
        audit=audit,
        shortlist=shortlist,
        comparison=comparison,
        guardrail_report=guardrail_report,
        readme=readme,
    )


def resolve_step29_inputs(config: dict[str, Any]) -> Step29InputResolution:
    inputs = config.get("inputs") if isinstance(config.get("inputs"), dict) else {}
    specs = {
        "step25_rows_path": (
            inputs.get("step25_universe_rows"),
            "data/reports/step25_full_universe_1743_primary_only_scale/full_universe_screening_rows.csv",
        ),
        "step26_audit_rows_path": (
            inputs.get("step26_audit_rows"),
            "data/reports/step26_full_universe_output_audit_first_shortlist/normalized_universe_rows.csv",
        ),
        "step26_summary_path": (
            inputs.get("step26_summary"),
            "data/reports/step26_full_universe_output_audit_first_shortlist/step26_audit_summary.json",
        ),
        "step28_market_snapshot_rows_path": (
            inputs.get("step28_market_snapshot_rows"),
            "data/reports/step28_full_universe_market_snapshot_refresh_vnstock/market_snapshot_rows.csv",
        ),
        "step28_summary_path": (
            inputs.get("step28_summary"),
            "data/reports/step28_full_universe_market_snapshot_refresh_vnstock/step28_market_refresh_summary.json",
        ),
    }
    resolved: dict[str, Path | None] = {}
    missing: list[str] = []
    required = {"step25_rows_path", "step26_audit_rows_path", "step28_market_snapshot_rows_path"}
    for label, (configured, fallback) in specs.items():
        path = _resolve_existing_path(configured) or _resolve_existing_path(fallback)
        resolved[label] = path
        if path is None and label in required:
            missing.append(label)
    return Step29InputResolution(
        step25_rows_path=resolved["step25_rows_path"],
        step26_audit_rows_path=resolved["step26_audit_rows_path"],
        step26_summary_path=resolved["step26_summary_path"],
        step28_market_snapshot_rows_path=resolved["step28_market_snapshot_rows_path"],
        step28_summary_path=resolved["step28_summary_path"],
        missing_input_files=missing,
    )


def load_baseline_rows(step26_rows_path: Path | None, step25_rows: pd.DataFrame) -> pd.DataFrame:
    step26_rows = _read_csv(step26_rows_path)
    if not step26_rows.empty:
        return step26_rows.copy()
    return normalize_rows(step25_rows)


def build_step29_audit(config: dict[str, Any], baseline: pd.DataFrame, step28_snapshot: pd.DataFrame) -> pd.DataFrame:
    if baseline.empty:
        return pd.DataFrame(columns=AUDIT_COLUMNS)
    rows = baseline.copy()
    rows["ticker"] = rows["ticker"].astype(str).str.upper().str.strip()
    snapshot = _snapshot_lookup(step28_snapshot)
    records = []
    for _, row in rows.iterrows():
        ticker = str(row.get("ticker", "")).upper().strip()
        snap = snapshot.get(ticker, {})
        records.append(build_step29_row(config, row.to_dict(), snap))
    return pd.DataFrame(records, columns=AUDIT_COLUMNS)


def build_step29_row(config: dict[str, Any], row: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    original_status = str(row.get("screening_status", ""))
    fetch_error = str(snapshot.get("fetch_error_type", "") or "NOT_ATTEMPTED")
    fetch_status = str(snapshot.get("fetch_status", "") or "NOT_ATTEMPTED")
    snapshot_market_ok = _as_bool(snapshot.get("market_data_available")) and fetch_error == "OK"
    original_market_ok = _has_original_market_data(row)
    market_available = bool(snapshot_market_ok or original_market_ok)
    recent_price = bool(_as_bool(snapshot.get("recent_price_available")) if snapshot else original_market_ok)
    liquidity = bool(_as_bool(snapshot.get("liquidity_data_available")) if snapshot else _has_original_liquidity_data(row))

    updated = dict(row)
    if snapshot_market_ok:
        _copy_if_present(updated, "last_price_date", snapshot.get("last_price_date"))
        _copy_if_present(updated, "last_close", snapshot.get("last_close"))
        _copy_if_present(updated, "last_volume", snapshot.get("last_volume"))
        _copy_if_present(updated, "avg_volume_20d", snapshot.get("avg_volume_20d"))
        _copy_if_present(updated, "avg_volume_60d", snapshot.get("avg_volume_60d"))
        _copy_if_present(updated, "recent_trading_value", snapshot.get("avg_value_20d_if_available") or snapshot.get("last_value_if_available"))

    missing_fields = parse_listish(row.get("missing_fields", ""))
    block_reasons = parse_listish(row.get("block_reasons", ""))
    if snapshot_market_ok:
        still_missing_market = set(parse_listish(snapshot.get("missing_market_fields", "")))
        available_market_fields = MARKET_MISSING_FIELDS - still_missing_market
        remaining_missing = [field for field in missing_fields if field not in available_market_fields]
        remaining_blocks = [reason for reason in block_reasons if reason not in MARKET_BLOCK_REASONS]
    else:
        remaining_missing = missing_fields
        remaining_blocks = block_reasons

    recovery_status = _market_recovery_status(original_status, snapshot_market_ok, fetch_error)
    step29_status, review_status = _step29_status(
        original_status=original_status,
        market_available=market_available,
        snapshot_market_ok=snapshot_market_ok,
        remaining_missing=remaining_missing,
        finance_quality_status=updated.get("finance_quality_status", ""),
    )
    if not remaining_blocks and step29_status in {"MANUAL_REVIEW", "INSUFFICIENT_DATA"}:
        remaining_blocks = [_manual_review_reason(step29_status)]
    if step29_status == "BLOCKED_INSUFFICIENT_MARKET_DATA" and fetch_error not in {"", "NOT_ATTEMPTED", "OK"}:
        remaining_blocks = _append_unique(remaining_blocks, f"STEP28 market refresh failed with error type: {fetch_error}.")

    shortlist_eligible, exclusion = _shortlist_eligibility(step29_status, market_available, remaining_missing, updated)
    manual_review_required = step29_status in {"WATCHLIST_CANDIDATE", "MANUAL_REVIEW", "INSUFFICIENT_DATA"} or str(review_status).startswith("NEEDS_")
    manual_bctc_required = _as_bool(updated.get("manual_bctc_required")) or manual_review_required
    data_quality_status = _data_quality_status(step29_status, market_available, remaining_missing)

    return {
        "ticker": str(updated.get("ticker", "")).upper().strip(),
        "company_name": updated.get("company_name", ""),
        "exchange_if_available": snapshot.get("exchange_if_available", row.get("exchange", "")),
        "step26_screening_status": original_status,
        "step29_screening_status": step29_status,
        "step29_review_status": review_status,
        "step29_market_recovery_status": recovery_status,
        "watchlist_status": _watchlist_status(step29_status),
        "shortlist_eligible": bool(shortlist_eligible),
        "shortlist_exclusion_reason": exclusion,
        "step29_manual_review_required": bool(manual_review_required),
        "manual_bctc_required": bool(manual_bctc_required),
        "market_data_available_after_step28": bool(market_available),
        "recent_price_available_after_step28": bool(recent_price),
        "liquidity_data_available_after_step28": bool(liquidity),
        "step28_fetch_status": fetch_status,
        "step28_fetch_error_type": fetch_error,
        "step28_last_price_date": snapshot.get("last_price_date", ""),
        "step28_last_close": snapshot.get("last_close", ""),
        "step28_last_volume": snapshot.get("last_volume", ""),
        "last_price_date": updated.get("last_price_date", ""),
        "last_close": updated.get("last_close", ""),
        "avg_volume_20d": updated.get("avg_volume_20d", ""),
        "avg_volume_60d": updated.get("avg_volume_60d", ""),
        "last_volume": updated.get("last_volume", ""),
        "recent_trading_value": updated.get("recent_trading_value", ""),
        "remaining_missing_fields": _json_list(remaining_missing),
        "remaining_block_reasons": _json_list(remaining_blocks),
        "finance_quality_status": updated.get("finance_quality_status", ""),
        "finance_source_confidence": updated.get("finance_source_confidence", ""),
        "market_source_confidence": updated.get("market_source_confidence", "PROVISIONAL_PRIMARY_ONLY"),
        "crosscheck_status": updated.get("crosscheck_status", "NOT_AVAILABLE"),
        "verification_status": updated.get("verification_status", "NEEDS_MANUAL_BCTC_REVIEW"),
        "data_quality_status": data_quality_status,
        "confidence_status": _confidence_status(market_available, remaining_missing, updated.get("finance_quality_status", "")),
    }


def build_step29_shortlist(config: dict[str, Any], audit: pd.DataFrame) -> pd.DataFrame:
    if audit.empty:
        return pd.DataFrame(columns=SHORTLIST_COLUMNS)
    limit = int((config.get("limits") or {}).get("shortlist_size", 50) or 50)
    frame = audit[audit["shortlist_eligible"].map(_as_bool)].copy()
    if frame.empty:
        return pd.DataFrame(columns=SHORTLIST_COLUMNS)
    frame["remaining_missing_count"] = frame["remaining_missing_fields"].map(lambda value: len(parse_listish(value)))
    frame["recent_trading_value_num"] = frame["recent_trading_value"].map(_to_float).fillna(-1)
    frame = frame.sort_values(
        ["remaining_missing_count", "recent_trading_value_num", "ticker"],
        ascending=[True, False, True],
    ).head(limit)
    return frame.reindex(columns=SHORTLIST_COLUMNS)


def build_step26_comparison(
    step26_summary: dict[str, Any],
    step28_summary: dict[str, Any],
    audit: pd.DataFrame,
    step28_snapshot: pd.DataFrame,
) -> dict[str, Any]:
    step26_status_counts = step26_summary.get("status_distribution") if isinstance(step26_summary.get("status_distribution"), dict) else {}
    step26_blocked = int(step26_status_counts.get("BLOCKED_INSUFFICIENT_MARKET_DATA", 0) or 0)
    step26_candidates = int(step26_status_counts.get("WATCHLIST_CANDIDATE", 0) or 0)
    recovered = int(audit["step29_market_recovery_status"].eq("RECOVERED_FROM_STEP26_BLOCKED").sum()) if not audit.empty else 0
    still_blocked = int(audit["step29_screening_status"].eq("BLOCKED_INSUFFICIENT_MARKET_DATA").sum()) if not audit.empty else 0
    candidates = int(audit["step29_screening_status"].eq("WATCHLIST_CANDIDATE").sum()) if not audit.empty else 0
    market_available = int(audit["market_data_available_after_step28"].map(_as_bool).sum()) if not audit.empty else 0
    attempted = len(step28_snapshot) if not step28_snapshot.empty else int(step28_summary.get("total_tickers_attempted", 0) or 0)
    ok_count = int(step28_snapshot["fetch_error_type"].eq("OK").sum()) if "fetch_error_type" in step28_snapshot.columns else int(step28_summary.get("fetch_ok_count", 0) or 0)
    failed_count = max(0, int(attempted) - int(ok_count))
    total = int(len(audit))
    return {
        "step26_total_universe": int(step26_summary.get("total_universe_rows_read", total) or total),
        "step29_total_universe": total,
        "step26_blocked_insufficient_market_data": step26_blocked,
        "step29_still_blocked_insufficient_market_data": still_blocked,
        "recovered_from_step26_blocked": recovered,
        "step26_watchlist_candidate_count": step26_candidates,
        "step29_watchlist_candidate_count": candidates,
        "watchlist_candidate_delta": int(candidates - step26_candidates),
        "market_data_available_after_step28": market_available,
        "step28_snapshot_tickers_used": int(attempted),
        "step28_fetch_ok_count": int(ok_count),
        "step28_fetch_failed_count": int(failed_count),
        "step28_not_attempted_or_not_in_snapshot": max(0, total - int(attempted)),
        "step28_summary_final_decision": step28_summary.get("final_decision", ""),
    }


def build_step29_summary(
    *,
    config: dict[str, Any],
    resolution: Step29InputResolution,
    audit: pd.DataFrame,
    shortlist: pd.DataFrame,
    comparison: dict[str, Any],
    forbidden_terms_found: list[str],
    core_outputs_modified: bool,
    pytest_result: str,
) -> dict[str, Any]:
    total = int(len(audit))
    watchlist_count = int(audit["step29_screening_status"].eq("WATCHLIST_CANDIDATE").sum()) if not audit.empty else 0
    manual_review_count = int(audit["step29_manual_review_required"].map(_as_bool).sum()) if not audit.empty else 0
    insufficient_count = int(audit["step29_screening_status"].eq("INSUFFICIENT_DATA").sum()) if not audit.empty else 0
    failed_count = int(audit["step28_fetch_error_type"].astype(str).isin(["EMPTY_HISTORY", "SOURCE_NO_DATA", "SOURCE_RATE_LIMIT_OR_TIMEOUT", "SOURCE_REQUEST_ERROR", "VNSTOCK_API_ERROR", "TICKER_MAPPING_ERROR", "ENV_ENCODING_ERROR", "NORMALIZATION_ERROR", "CACHE_INVALID", "UNKNOWN_ERROR"]).sum()) if not audit.empty else 0
    final_decision = _final_decision(
        missing_inputs=bool(resolution.missing_input_files),
        guardrail_block=bool(forbidden_terms_found or core_outputs_modified),
        watchlist_count=watchlist_count,
        manual_review_count=manual_review_count,
    )
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "mode": MODE,
        "total_universe": total,
        "expected_universe_size": int((config.get("limits") or {}).get("expected_universe_size", 1743) or 1743),
        "market_data_available_after_step28": int(comparison.get("market_data_available_after_step28", 0)),
        "still_blocked_insufficient_market_data": int(comparison.get("step29_still_blocked_insufficient_market_data", 0)),
        "recovered_from_step26_blocked": int(comparison.get("recovered_from_step26_blocked", 0)),
        "watchlist_candidate_count": watchlist_count,
        "shortlist_count": int(len(shortlist)),
        "manual_review_count": manual_review_count,
        "failed_count": failed_count,
        "insufficient_data_count": insufficient_count,
        "failed_or_insufficient_count": int(failed_count + insufficient_count),
        "pytest_result": pytest_result,
        "guardrails": dict(GUARDRAILS),
        "forbidden_terms_found": forbidden_terms_found,
        "core_outputs_modified": bool(core_outputs_modified),
        "missing_input_files": resolution.missing_input_files,
        "final_decision": final_decision,
    }


def build_guardrail_report(
    *,
    forbidden_terms_found: list[str],
    core_outputs_modified: bool,
    missing_input_files: list[str],
) -> dict[str, Any]:
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "guardrails": dict(GUARDRAILS),
        "no_guardrail_violations": not forbidden_terms_found and not core_outputs_modified and not missing_input_files,
        "forbidden_terms_found": forbidden_terms_found,
        "core_outputs_modified": bool(core_outputs_modified),
        "missing_input_files": missing_input_files,
        "network_usage_if_known": "none",
        "data_fetch_performed": False,
        "mock_sample_data_used_in_real_output": False,
        "zero_fill_missing_data": False,
    }


def build_readme(summary: dict[str, Any], comparison: dict[str, Any]) -> str:
    lines = [
        "# STEP29 Full-Universe Audit After Market Refresh",
        "",
        "## Scope",
        "This report is a provisional engineering audit for human review planning.",
        "This report does not contain buy/sell/hold signals.",
        "No new data fetch was performed by STEP29.",
        "",
        "## Inputs",
        "- STEP25 full-universe screening rows",
        "- STEP26 normalized audit rows and summary",
        "- STEP28 market snapshot rows and summary",
        "",
        "## Key Counts",
        f"- total_universe: {summary.get('total_universe', 0)}",
        f"- market_data_available_after_step28: {summary.get('market_data_available_after_step28', 0)}",
        f"- still_blocked_insufficient_market_data: {summary.get('still_blocked_insufficient_market_data', 0)}",
        f"- recovered_from_step26_blocked: {summary.get('recovered_from_step26_blocked', 0)}",
        f"- watchlist_candidate_count: {summary.get('watchlist_candidate_count', 0)}",
        f"- manual_review_count: {summary.get('manual_review_count', 0)}",
        f"- failed_count: {summary.get('failed_count', 0)}",
        f"- insufficient_data_count: {summary.get('insufficient_data_count', 0)}",
        f"- shortlist_count: {summary.get('shortlist_count', 0)}",
        "",
        "## Step26 Comparison",
        f"- step26_blocked_insufficient_market_data: {comparison.get('step26_blocked_insufficient_market_data', 0)}",
        f"- step29_still_blocked_insufficient_market_data: {comparison.get('step29_still_blocked_insufficient_market_data', 0)}",
        f"- watchlist_candidate_delta: {comparison.get('watchlist_candidate_delta', 0)}",
        "",
        "## Result",
        f"- final_decision: {summary.get('final_decision', '')}",
        f"- pytest_result: {summary.get('pytest_result', '')}",
        f"- forbidden_terms_found: {summary.get('forbidden_terms_found', [])}",
        "",
        "## Next Engineering Step",
        "Run the full STEP28 universe refresh before repeating this audit if broader market coverage is required.",
    ]
    return "\n".join(lines) + "\n"


def write_step29_outputs(
    output_dir: Path,
    summary: dict[str, Any],
    audit: pd.DataFrame,
    shortlist: pd.DataFrame,
    comparison: dict[str, Any],
    guardrail_report: dict[str, Any],
    readme: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "step29_audit_summary.json", summary)
    audit.to_csv(output_dir / "step29_full_universe_audit.csv", index=False, encoding="utf-8")
    shortlist.to_csv(output_dir / "step29_shortlist.csv", index=False, encoding="utf-8")
    _write_json(output_dir / "step29_step26_comparison.json", comparison)
    _write_json(output_dir / "step29_guardrail_report.json", guardrail_report)
    (output_dir / "README.md").write_text(readme, encoding="utf-8")


def scan_forbidden_terms(output_dir: Path) -> list[str]:
    hits: list[str] = []
    if not output_dir.exists():
        return hits
    for path in sorted(output_dir.glob("*")):
        if path.suffix.lower() not in {".csv", ".json", ".md", ".txt"}:
            continue
        text = _scan_text(path)
        for line_no, line in enumerate(text.splitlines(), start=1):
            lower = line.lower().strip()
            if lower in ALLOWED_SAFETY_LINES:
                continue
            for term in FORBIDDEN_TERMS:
                if _term_in_text(term, lower):
                    hits.append(f"{path.name}:{line_no}:{term}")
    return hits


def parse_listish(value: Any) -> list[str]:
    if _is_missing(value):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if not _is_missing(item)]
    text = str(value).strip()
    if text.startswith(("[", "(", "{")):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(text)
            except (SyntaxError, ValueError):
                parsed = None
        if isinstance(parsed, (list, tuple, set)):
            return [str(item).strip() for item in parsed if not _is_missing(item)]
        if parsed is not None:
            return []
        text = text.strip("[](){}")
    return [part.strip() for part in re.split(r"[;,]", text) if part.strip()]


def _step29_status(
    *,
    original_status: str,
    market_available: bool,
    snapshot_market_ok: bool,
    remaining_missing: list[str],
    finance_quality_status: Any,
) -> tuple[str, str]:
    finance_status = str(finance_quality_status).upper()
    non_market_missing = [field for field in remaining_missing if field not in MARKET_MISSING_FIELDS]
    if original_status == "WATCHLIST_CANDIDATE" and market_available:
        return "WATCHLIST_CANDIDATE", "NEEDS_MANUAL_BCTC_REVIEW"
    if original_status == "BLOCKED_INSUFFICIENT_MARKET_DATA" and not snapshot_market_ok:
        return "BLOCKED_INSUFFICIENT_MARKET_DATA", "DATA_REPAIR_REQUIRED"
    if not market_available:
        return "BLOCKED_INSUFFICIENT_MARKET_DATA", "DATA_REPAIR_REQUIRED"
    if finance_status in FINANCE_INSUFFICIENT_STATUSES:
        return "INSUFFICIENT_DATA", "NEEDS_MANUAL_BCTC_REVIEW"
    if non_market_missing:
        return "MANUAL_REVIEW", "NEEDS_MANUAL_BCTC_REVIEW"
    return "WATCHLIST_CANDIDATE", "NEEDS_MANUAL_BCTC_REVIEW"


def _market_recovery_status(original_status: str, snapshot_market_ok: bool, fetch_error: str) -> str:
    if original_status == "BLOCKED_INSUFFICIENT_MARKET_DATA" and snapshot_market_ok:
        return "RECOVERED_FROM_STEP26_BLOCKED"
    if original_status == "BLOCKED_INSUFFICIENT_MARKET_DATA" and fetch_error == "NOT_ATTEMPTED":
        return "STEP28_NOT_ATTEMPTED"
    if original_status == "BLOCKED_INSUFFICIENT_MARKET_DATA":
        return "STILL_BLOCKED_INSUFFICIENT_MARKET_DATA"
    if snapshot_market_ok:
        return "STEP28_CONFIRMED_MARKET_DATA"
    return "ALREADY_VALID_OR_NOT_MARKET_BLOCKED"


def _shortlist_eligibility(status: str, market_available: bool, remaining_missing: list[str], row: dict[str, Any]) -> tuple[bool, str]:
    if status != "WATCHLIST_CANDIDATE":
        return False, "NOT_WATCHLIST_CANDIDATE"
    if not market_available:
        return False, "MARKET_DATA_UNAVAILABLE"
    finance_status = str(row.get("finance_quality_status", "")).upper()
    if finance_status in FINANCE_INSUFFICIENT_STATUSES:
        return False, "FINANCE_DATA_INSUFFICIENT"
    non_market_missing = [field for field in remaining_missing if field not in MARKET_MISSING_FIELDS]
    if non_market_missing:
        return False, "COMPANY_OR_FINANCE_FIELDS_NEED_REVIEW"
    return True, ""


def _manual_review_reason(status: str) -> str:
    if status == "INSUFFICIENT_DATA":
        return "Finance/company evidence remains insufficient after market refresh."
    return "Market data recovered; manual BCTC review remains required."


def _data_quality_status(status: str, market_available: bool, remaining_missing: list[str]) -> str:
    if not market_available:
        return "INSUFFICIENT_MARKET_DATA"
    if status == "INSUFFICIENT_DATA":
        return "INSUFFICIENT_DATA"
    if remaining_missing:
        return "MANUAL_REVIEW"
    return "PROVISIONAL_PRIMARY_ONLY"


def _confidence_status(market_available: bool, remaining_missing: list[str], finance_quality_status: Any) -> str:
    if not market_available:
        return "LOW_CONFIDENCE_MARKET_DATA_GAP"
    if str(finance_quality_status).upper() in FINANCE_INSUFFICIENT_STATUSES:
        return "LOW_CONFIDENCE_FINANCE_DATA_GAP"
    if remaining_missing:
        return "PROVISIONAL_LOW_NEEDS_MANUAL_REVIEW"
    return "PROVISIONAL_LOW"


def _watchlist_status(status: str) -> str:
    if status == "WATCHLIST_CANDIDATE":
        return "WATCH_ONLY"
    if status in {"MANUAL_REVIEW", "INSUFFICIENT_DATA"}:
        return status
    if status.startswith("BLOCKED_"):
        return "REJECTED"
    return "MANUAL_REVIEW"


def _final_decision(*, missing_inputs: bool, guardrail_block: bool, watchlist_count: int, manual_review_count: int) -> str:
    if missing_inputs:
        return "BLOCKED_MISSING_INPUT"
    if guardrail_block:
        return "BLOCKED_GUARDRAIL_VIOLATION"
    if watchlist_count > 0:
        return "PASS_AUDIT_AFTER_MARKET_REFRESH_WITH_SHORTLIST"
    if manual_review_count > 0:
        return "PASS_AUDIT_AFTER_MARKET_REFRESH_WITH_MANUAL_REVIEW"
    return "PASS_AUDIT_AFTER_MARKET_REFRESH_WITH_DATA_GAPS"


def _snapshot_lookup(step28_snapshot: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if step28_snapshot.empty or "ticker" not in step28_snapshot.columns:
        return {}
    frame = step28_snapshot.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    return {str(row["ticker"]): row.to_dict() for _, row in frame.drop_duplicates("ticker", keep="last").iterrows()}


def _has_original_market_data(row: dict[str, Any]) -> bool:
    return not _is_missing(row.get("last_close")) and not _is_missing(row.get("last_price_date"))


def _has_original_liquidity_data(row: dict[str, Any]) -> bool:
    return any(not _is_missing(row.get(field)) for field in ["recent_trading_value", "avg_volume_20d", "avg_volume_60d", "last_volume"])


def _copy_if_present(target: dict[str, Any], key: str, value: Any) -> None:
    if not _is_missing(value):
        target[key] = value


def _append_unique(values: list[str], value: str) -> list[str]:
    if value not in values:
        return [*values, value]
    return values


def _core_paths_from_resolution(resolution: Step29InputResolution) -> list[Path]:
    return [
        path
        for path in [
            resolution.step25_rows_path,
            resolution.step26_audit_rows_path,
            resolution.step26_summary_path,
            resolution.step28_market_snapshot_rows_path,
            resolution.step28_summary_path,
        ]
        if path is not None
    ]


def _resolve_existing_path(value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    return path if path.exists() else None


def _read_csv(path: str | Path | None) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame()
    target = Path(path)
    if not target.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(target, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _read_json(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    target = Path(path)
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _json_list(values: list[Any]) -> str:
    return json.dumps([str(value) for value in values if not _is_missing(value)], ensure_ascii=False)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _is_missing(value: Any) -> bool:
    return value is None or str(value).strip() == "" or str(value).strip().lower() in {"nan", "none", "null", "na", "<na>"}


def _to_float(value: Any) -> float | None:
    if _is_missing(value):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _term_in_text(term: str, lower_text: str) -> bool:
    if " " in term or "/" in term:
        return term in lower_text
    return re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", lower_text) is not None


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
        data.pop("guardrails", None)
    return json.dumps(data, ensure_ascii=False, indent=2)


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
            encoding="utf-8",
            errors="replace",
        )
    except Exception:  # noqa: BLE001
        return ""
    return completed.stdout.strip()


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
