"""STEP23 filter monitoring and stability module.

This module tracks whether the evidence pipeline is stable over time. It does
not fetch data, create trade signals, compute portfolio outcomes, or make
performance claims.
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


STEP_ID = "STEP23-BACKTEST-MONITORING-MODULE"
MODE = "monitoring_filter_stability_only"
SAFETY_NOTICE = (
    "This module monitors filter stability and data quality. "
    "It does not make performance claims and it does not provide trade guidance."
)

FINAL_DECISIONS = {
    "PASS_MONITORING_WITH_WARNINGS",
    "CONDITIONAL_GO_FOR_STEP24_FINAL_INTEGRATION",
    "BLOCKED_MONITORING_MODULE",
}

WATCHLIST_CANDIDATE_STATUSES = {
    "HIGH_CONFIDENCE_WATCHLIST",
    "MEDIUM_CONFIDENCE_WATCHLIST",
    "WATCH_ONLY",
}

FORBIDDEN_TERMS = [
    "strategy beats market",
    "guaranteed alpha",
    "alpha guaranteed",
    "expected profit",
    "expected return",
    "recommended portfolio",
    "buy",
    "sell",
    "hold",
    "target price",
    "fair value",
    "intrinsic value",
    "margin of safety",
    "entry price",
    "exit price",
    "stoploss",
    "take profit",
]

SNAPSHOT_COLUMNS = [
    "snapshot_id",
    "snapshot_created_at",
    "ticker",
    "company_name",
    "micro_sector",
    "watchlist_status",
    "confidence_score",
    "manual_review_required",
    "missing_fields",
    "source_conflicts",
    "reject_reason",
    "cycle_status",
    "survival_status",
    "valuation_context",
    "timing_liquidity_status",
    "market_source_confidence",
    "finance_source_confidence",
    "crosscheck_status",
    "verification_status",
]

DASHBOARD_COLUMNS = [
    "metric_name",
    "current_value",
    "previous_value",
    "change",
    "trend_direction",
    "interpretation",
    "confidence",
    "manual_review_required",
]

WATCHLIST_CHANGE_COLUMNS = [
    "ticker",
    "previous_status",
    "current_status",
    "change_type",
    "previous_confidence_score",
    "current_confidence_score",
    "confidence_score_change",
    "manual_review_change",
    "confidence",
]

SCORE_CHANGE_COLUMNS = [
    "ticker",
    "score_name",
    "previous_value",
    "current_value",
    "change",
    "drift_flag",
    "confidence",
]

TREND_COLUMNS = [
    "metric_name",
    "current_value",
    "previous_value",
    "change",
    "trend_direction",
    "interpretation",
    "confidence",
    "manual_review_required",
]

REJECT_TREND_COLUMNS = ["reject_reason", "current_count", "previous_count", "change", "trend_direction", "confidence"]
SECTOR_DRIFT_COLUMNS = ["micro_sector", "current_ticker_count", "previous_ticker_count", "current_status_mix", "previous_status_mix", "drift_status", "confidence"]
COMPANY_DRIFT_COLUMNS = ["ticker", "current_confidence_score", "previous_confidence_score", "score_change", "drift_status", "confidence"]


class Step23SafeRunBlocked(RuntimeError):
    """Raised when a requested Step23 run violates scope controls."""


@dataclass
class Step23Result:
    current_snapshot: pd.DataFrame
    monitoring_dashboard: pd.DataFrame
    watchlist_history: pd.DataFrame
    watchlist_change_log: pd.DataFrame
    score_change_log: pd.DataFrame
    reject_reason_trend: pd.DataFrame
    manual_review_trend: pd.DataFrame
    data_coverage_trend: pd.DataFrame
    source_conflict_trend: pd.DataFrame
    sector_signal_drift: pd.DataFrame
    company_score_drift: pd.DataFrame
    run_manifest: dict[str, Any]
    summary: dict[str, Any]


def load_step23_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("STEP23 config must be a mapping.")
    return data


def run_step23_backtest_monitoring_module(
    *,
    config_path: str | Path,
    output_dir: str | Path | None = None,
    limit: int | None = None,
    allow_partial: bool | None = None,
    request_full_universe: bool = False,
    command_used: str = "",
    core_output_paths: list[str | Path] | None = None,
) -> Step23Result:
    config = load_step23_config(config_path)
    validate_step23_config(config)
    output = Path(output_dir or ((config.get("exports") or {}).get("output_dir") or "data/reports/step23_backtest_monitoring_module"))
    output.mkdir(parents=True, exist_ok=True)

    limits = config.get("limits") or {}
    if request_full_universe and not _as_bool(limits.get("full_universe_allowed", False)):
        raise Step23SafeRunBlocked("Full-universe STEP23 run is blocked by config.")
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
    frames, resolved_inputs, missing_inputs, snapshots_dir = load_step23_inputs(config, allow_partial=allow_partial_effective)
    if missing_inputs and not allow_partial_effective:
        raise Step23SafeRunBlocked("STEP23 missing input while allow_partial=false: " + ",".join(missing_inputs))

    monitoring_cfg = config.get("monitoring") or {}
    if not snapshots_dir.exists():
        if _as_bool(monitoring_cfg.get("initialize_snapshot_if_missing", True)):
            snapshots_dir.mkdir(parents=True, exist_ok=True)
        else:
            raise Step23SafeRunBlocked("Monitoring snapshot directory is missing and initialization is disabled.")
    previous_snapshot_path = find_previous_snapshot(snapshots_dir) if _as_bool(monitoring_cfg.get("compare_to_previous_snapshot_if_available", True)) else None
    previous_snapshot = _read_csv(previous_snapshot_path) if previous_snapshot_path else pd.DataFrame(columns=SNAPSHOT_COLUMNS)

    created_at = _now()
    snapshot_id = _snapshot_id(created_at)
    current_snapshot = build_current_snapshot(config=config, frames=frames, snapshot_id=snapshot_id, created_at=created_at, limit=effective_limit)
    snapshot_path = write_snapshot(snapshots_dir, current_snapshot, snapshot_id)
    previous_found = previous_snapshot_path is not None and not previous_snapshot.empty

    monitoring_dashboard = build_monitoring_dashboard(current_snapshot, previous_snapshot)
    watchlist_history = build_watchlist_history(current_snapshot, previous_snapshot, previous_found)
    watchlist_change_log = build_watchlist_change_log(current_snapshot, previous_snapshot, previous_found)
    score_change_log = build_score_change_log(current_snapshot, previous_snapshot, previous_found)
    reject_reason_trend = build_reject_reason_trend(current_snapshot, previous_snapshot, previous_found)
    manual_review_trend = build_manual_review_trend(current_snapshot, previous_snapshot, previous_found)
    data_coverage_trend = build_data_coverage_trend(current_snapshot, previous_snapshot, previous_found)
    source_conflict_trend = build_source_conflict_trend(current_snapshot, previous_snapshot, previous_found)
    sector_signal_drift = build_sector_signal_drift(current_snapshot, previous_snapshot, previous_found)
    company_score_drift = build_company_score_drift(current_snapshot, previous_snapshot, previous_found)
    core_modified = before_hashes != _hashes(core_paths)
    summary = build_summary(
        config=config,
        current_snapshot=current_snapshot,
        previous_found=previous_found,
        snapshot_created=snapshot_path.exists(),
        watchlist_change_log=watchlist_change_log,
        manual_review_trend=manual_review_trend,
        data_coverage_trend=data_coverage_trend,
        source_conflict_trend=source_conflict_trend,
        missing_inputs=missing_inputs,
        warnings=warnings,
        forbidden_hits=[],
        core_outputs_modified=core_modified,
    )
    manifest = build_run_manifest(
        config=config,
        config_path=Path(config_path),
        output_dir=output,
        snapshots_dir=snapshots_dir,
        snapshot_path=snapshot_path,
        previous_snapshot_path=previous_snapshot_path,
        effective_limit=effective_limit,
        allow_partial=allow_partial_effective,
        command_used=command_used,
        core_outputs_modified=core_modified,
        resolved_inputs=resolved_inputs,
        missing_inputs=missing_inputs,
    )
    write_step23_outputs(
        output_dir=output,
        monitoring_dashboard=monitoring_dashboard,
        watchlist_history=watchlist_history,
        watchlist_change_log=watchlist_change_log,
        score_change_log=score_change_log,
        reject_reason_trend=reject_reason_trend,
        manual_review_trend=manual_review_trend,
        data_coverage_trend=data_coverage_trend,
        source_conflict_trend=source_conflict_trend,
        sector_signal_drift=sector_signal_drift,
        company_score_drift=company_score_drift,
        summary=summary,
        manifest=manifest,
    )
    forbidden_hits = scan_forbidden_terms(output, extra_paths=[snapshot_path])
    if forbidden_hits:
        summary = build_summary(
            config=config,
            current_snapshot=current_snapshot,
            previous_found=previous_found,
            snapshot_created=snapshot_path.exists(),
            watchlist_change_log=watchlist_change_log,
            manual_review_trend=manual_review_trend,
            data_coverage_trend=data_coverage_trend,
            source_conflict_trend=source_conflict_trend,
            missing_inputs=missing_inputs,
            warnings=warnings,
            forbidden_hits=forbidden_hits,
            core_outputs_modified=core_modified,
        )
        write_step23_outputs(
            output_dir=output,
            monitoring_dashboard=monitoring_dashboard,
            watchlist_history=watchlist_history,
            watchlist_change_log=watchlist_change_log,
            score_change_log=score_change_log,
            reject_reason_trend=reject_reason_trend,
            manual_review_trend=manual_review_trend,
            data_coverage_trend=data_coverage_trend,
            source_conflict_trend=source_conflict_trend,
            sector_signal_drift=sector_signal_drift,
            company_score_drift=company_score_drift,
            summary=summary,
            manifest=manifest,
        )
    return Step23Result(
        current_snapshot=current_snapshot,
        monitoring_dashboard=monitoring_dashboard,
        watchlist_history=watchlist_history,
        watchlist_change_log=watchlist_change_log,
        score_change_log=score_change_log,
        reject_reason_trend=reject_reason_trend,
        manual_review_trend=manual_review_trend,
        data_coverage_trend=data_coverage_trend,
        source_conflict_trend=source_conflict_trend,
        sector_signal_drift=sector_signal_drift,
        company_score_drift=company_score_drift,
        run_manifest=manifest,
        summary=summary,
    )


def validate_step23_config(config: dict[str, Any]) -> None:
    if config.get("step_id") != STEP_ID:
        raise ValueError(f"STEP23 config step_id must be {STEP_ID}.")
    safety = config.get("safety") if isinstance(config.get("safety"), dict) else {}
    required = [
        "no_recommendation",
        "no_buy_sell_hold",
        "no_strategy_claim",
        "no_alpha_claim",
        "no_expected_profit",
        "no_expected_return",
        "no_target_price",
        "no_fair_value",
        "no_margin_of_safety",
        "no_entry_exit_price",
        "no_portfolio_recommendation",
        "no_zero_fill",
        "no_core_output_mutation",
    ]
    missing = [key for key in required if safety.get(key) is not True]
    if missing:
        raise ValueError(f"STEP23 safety flags must be true: {','.join(missing)}")


def load_step23_inputs(config: dict[str, Any], *, allow_partial: bool) -> tuple[dict[str, pd.DataFrame], dict[str, str], list[str], Path]:
    frames: dict[str, pd.DataFrame] = {}
    resolved: dict[str, str] = {}
    missing: list[str] = []
    snapshots_dir = Path(str((config.get("inputs") or {}).get("monitoring_snapshots_dir") or "data/reports/monitoring_snapshots"))
    for logical_name, spec in (config.get("inputs") or {}).items():
        if logical_name == "monitoring_snapshots_dir":
            resolved[str(logical_name)] = str(Path(str(spec)))
            continue
        path = _first_existing_path(spec)
        if path is None:
            missing.append(f"{logical_name}:{_spec_text(spec)}")
            frames[str(logical_name)] = pd.DataFrame()
        else:
            resolved[str(logical_name)] = str(path)
            frames[str(logical_name)] = _read_csv(path)
    if missing and not allow_partial:
        return frames, resolved, missing, snapshots_dir
    return frames, resolved, missing, snapshots_dir


def build_current_snapshot(*, config: dict[str, Any], frames: dict[str, pd.DataFrame], snapshot_id: str, created_at: str, limit: int) -> pd.DataFrame:
    confidence = config.get("source_confidence") or {}
    watchlist = _frame(frames.get("step22_watchlist", pd.DataFrame()))
    manual = _frame(frames.get("step22_manual_review_queue", pd.DataFrame()))
    reject = _frame(frames.get("step22_reject_log", pd.DataFrame()))
    step21 = _frame(frames.get("step21_rows", pd.DataFrame()))
    tickers = _combined_tickers(watchlist, manual, reject, step21)[:limit]
    watch_by_ticker = _index_by_ticker(watchlist)
    manual_by_ticker = _index_by_ticker(manual)
    reject_by_ticker = _index_by_ticker(reject)
    step21_by_ticker = _index_by_ticker(step21)
    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        current = watch_by_ticker.get(ticker, {})
        manual_row = manual_by_ticker.get(ticker, {})
        reject_row = reject_by_ticker.get(ticker, {})
        step21_row = step21_by_ticker.get(ticker, {})
        status = _first_non_missing(current.get("watchlist_status"), manual_row.get("watchlist_status"), reject_row.get("watchlist_status"), "INSUFFICIENT_DATA")
        if reject_row and status == "INSUFFICIENT_DATA":
            status = "REJECTED"
        rows.append(
            {
                "snapshot_id": snapshot_id,
                "snapshot_created_at": created_at,
                "ticker": ticker,
                "company_name": _first_non_missing(current.get("company_name"), manual_row.get("company_name"), reject_row.get("company_name"), "UNKNOWN"),
                "micro_sector": _first_non_missing(current.get("micro_sector"), "UNKNOWN"),
                "watchlist_status": status,
                "confidence_score": _first_non_missing(current.get("confidence_score"), ""),
                "manual_review_required": _first_non_missing(current.get("manual_review_required"), manual_row.get("manual_review_required"), "UNKNOWN"),
                "missing_fields": _first_non_missing(current.get("missing_fields"), manual_row.get("missing_fields"), "[]"),
                "source_conflicts": _first_non_missing(current.get("source_conflicts"), manual_row.get("source_conflicts"), "[]"),
                "reject_reason": _first_non_missing(reject_row.get("reject_reason"), ""),
                "cycle_status": _first_non_missing(current.get("cycle_status"), "INSUFFICIENT_DATA"),
                "survival_status": _first_non_missing(current.get("survival_status"), "UNKNOWN"),
                "valuation_context": _first_non_missing(current.get("valuation_context"), "INSUFFICIENT_DATA"),
                "timing_liquidity_status": _first_non_missing(current.get("timing_liquidity_status"), _timing_liquidity_status(step21_row), "INSUFFICIENT_DATA"),
                "market_source_confidence": confidence.get("market_source_confidence", "PROVISIONAL_PRIMARY_ONLY"),
                "finance_source_confidence": confidence.get("finance_source_confidence_default", "PROVISIONAL_LOW"),
                "crosscheck_status": confidence.get("crosscheck_status", "NOT_AVAILABLE"),
                "verification_status": confidence.get("verification_status", "NEEDS_MANUAL_BCTC_REVIEW"),
            }
        )
    return pd.DataFrame(rows, columns=SNAPSHOT_COLUMNS)


def find_previous_snapshot(snapshots_dir: Path) -> Path | None:
    if not snapshots_dir.exists():
        return None
    candidates = sorted(path for path in snapshots_dir.glob("snapshot_*.csv") if path.is_file())
    if not candidates:
        return None
    return candidates[-1]


def write_snapshot(snapshots_dir: Path, snapshot: pd.DataFrame, snapshot_id: str) -> Path:
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    base = snapshots_dir / f"{snapshot_id}.csv"
    path = base
    suffix = 1
    while path.exists():
        path = snapshots_dir / f"{snapshot_id}_{suffix:02d}.csv"
        suffix += 1
    snapshot.to_csv(path, index=False)
    return path


def build_monitoring_dashboard(current: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    previous_found = not previous.empty
    current_metrics = _snapshot_metrics(current)
    previous_metrics = _snapshot_metrics(previous) if previous_found else {}
    rows = []
    for metric_name, current_value in current_metrics.items():
        previous_value = previous_metrics.get(metric_name, "INSUFFICIENT_HISTORY")
        rows.append(_dashboard_row(metric_name, current_value, previous_value, previous_found))
    return pd.DataFrame(rows, columns=DASHBOARD_COLUMNS)


def build_watchlist_history(current: pd.DataFrame, previous: pd.DataFrame, previous_found: bool) -> pd.DataFrame:
    frames = []
    if previous_found:
        previous_copy = previous.reindex(columns=SNAPSHOT_COLUMNS).copy()
        previous_copy["history_role"] = "PREVIOUS"
        frames.append(previous_copy)
    current_copy = current.reindex(columns=SNAPSHOT_COLUMNS).copy()
    current_copy["history_role"] = "CURRENT"
    frames.append(current_copy)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SNAPSHOT_COLUMNS + ["history_role"])


def build_watchlist_change_log(current: pd.DataFrame, previous: pd.DataFrame, previous_found: bool) -> pd.DataFrame:
    current_by_ticker = _index_by_ticker(current)
    previous_by_ticker = _index_by_ticker(previous)
    tickers = sorted(set(current_by_ticker) | set(previous_by_ticker))
    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        cur = current_by_ticker.get(ticker, {})
        prev = previous_by_ticker.get(ticker, {})
        current_status = _first_non_missing(cur.get("watchlist_status"), "MISSING_CURRENT")
        previous_status = _first_non_missing(prev.get("watchlist_status"), "INSUFFICIENT_HISTORY" if not previous_found else "MISSING_PREVIOUS")
        cur_score = _first_non_missing(cur.get("confidence_score"), "")
        prev_score = _first_non_missing(prev.get("confidence_score"), "INSUFFICIENT_HISTORY" if not previous_found else "")
        if not previous_found:
            change_type = "INSUFFICIENT_HISTORY"
        elif ticker not in previous_by_ticker:
            change_type = "ADDED"
        elif ticker not in current_by_ticker:
            change_type = "REMOVED"
        elif current_status != previous_status:
            change_type = "STATUS_CHANGED"
        elif _score_change(prev_score, cur_score) not in {"", 0}:
            change_type = "SCORE_CHANGED"
        else:
            change_type = "UNCHANGED"
        rows.append(
            {
                "ticker": ticker,
                "previous_status": previous_status,
                "current_status": current_status,
                "change_type": change_type,
                "previous_confidence_score": prev_score,
                "current_confidence_score": cur_score,
                "confidence_score_change": _score_change(prev_score, cur_score) if previous_found else "INSUFFICIENT_HISTORY",
                "manual_review_change": _manual_review_change(prev.get("manual_review_required"), cur.get("manual_review_required"), previous_found),
                "confidence": "LOW" if not previous_found else "MEDIUM",
            }
        )
    return pd.DataFrame(rows, columns=WATCHLIST_CHANGE_COLUMNS)


def build_score_change_log(current: pd.DataFrame, previous: pd.DataFrame, previous_found: bool) -> pd.DataFrame:
    current_by_ticker = _index_by_ticker(current)
    previous_by_ticker = _index_by_ticker(previous)
    tickers = sorted(set(current_by_ticker) | set(previous_by_ticker))
    rows = []
    for ticker in tickers:
        cur_score = _first_non_missing(current_by_ticker.get(ticker, {}).get("confidence_score"), "")
        prev_score = _first_non_missing(previous_by_ticker.get(ticker, {}).get("confidence_score"), "INSUFFICIENT_HISTORY" if not previous_found else "")
        change = _score_change(prev_score, cur_score) if previous_found else "INSUFFICIENT_HISTORY"
        rows.append(
            {
                "ticker": ticker,
                "score_name": "confidence_score",
                "previous_value": prev_score,
                "current_value": cur_score,
                "change": change,
                "drift_flag": _drift_flag(change, previous_found),
                "confidence": "LOW" if not previous_found else "MEDIUM",
            }
        )
    return pd.DataFrame(rows, columns=SCORE_CHANGE_COLUMNS)


def build_reject_reason_trend(current: pd.DataFrame, previous: pd.DataFrame, previous_found: bool) -> pd.DataFrame:
    current_counts = _reject_counts(current)
    previous_counts = _reject_counts(previous) if previous_found else {}
    reasons = sorted(set(current_counts) | set(previous_counts) | ({"NO_REJECTED_ROWS"} if not current_counts else set()))
    rows = []
    for reason in reasons:
        current_count = current_counts.get(reason, 0)
        previous_count: Any = previous_counts.get(reason, "INSUFFICIENT_HISTORY") if not previous_found else previous_counts.get(reason, 0)
        change = current_count - previous_count if isinstance(previous_count, int) else "INSUFFICIENT_HISTORY"
        rows.append(
            {
                "reject_reason": reason,
                "current_count": int(current_count),
                "previous_count": previous_count,
                "change": change,
                "trend_direction": _trend_direction(change),
                "confidence": "LOW" if not previous_found else "MEDIUM",
            }
        )
    return pd.DataFrame(rows, columns=REJECT_TREND_COLUMNS)


def build_manual_review_trend(current: pd.DataFrame, previous: pd.DataFrame, previous_found: bool) -> pd.DataFrame:
    return pd.DataFrame(
        [
            _dashboard_row(
                "manual_review_count",
                _manual_review_count(current),
                _manual_review_count(previous) if previous_found else "INSUFFICIENT_HISTORY",
                previous_found,
            )
        ],
        columns=TREND_COLUMNS,
    )


def build_data_coverage_trend(current: pd.DataFrame, previous: pd.DataFrame, previous_found: bool) -> pd.DataFrame:
    rows = [
        _dashboard_row(
            "unresolved_field_count",
            _unresolved_field_count(current),
            _unresolved_field_count(previous) if previous_found else "INSUFFICIENT_HISTORY",
            previous_found,
        ),
        _dashboard_row(
            "rows_with_unresolved_fields",
            _rows_with_missing_fields(current),
            _rows_with_missing_fields(previous) if previous_found else "INSUFFICIENT_HISTORY",
            previous_found,
        ),
    ]
    return pd.DataFrame(rows, columns=TREND_COLUMNS)


def build_source_conflict_trend(current: pd.DataFrame, previous: pd.DataFrame, previous_found: bool) -> pd.DataFrame:
    rows = [
        _dashboard_row(
            "source_conflict_count",
            _source_conflict_count(current),
            _source_conflict_count(previous) if previous_found else "INSUFFICIENT_HISTORY",
            previous_found,
        ),
        _dashboard_row(
            "crosscheck_not_available_count",
            _crosscheck_not_available_count(current),
            _crosscheck_not_available_count(previous) if previous_found else "INSUFFICIENT_HISTORY",
            previous_found,
        ),
    ]
    return pd.DataFrame(rows, columns=TREND_COLUMNS)


def build_sector_signal_drift(current: pd.DataFrame, previous: pd.DataFrame, previous_found: bool) -> pd.DataFrame:
    current_groups = _sector_group_summary(current)
    previous_groups = _sector_group_summary(previous) if previous_found else {}
    sectors = sorted(set(current_groups) | set(previous_groups))
    rows = []
    if not sectors:
        rows.append(
            {
                "micro_sector": "INSUFFICIENT_DATA",
                "current_ticker_count": 0 if not current.empty else "INSUFFICIENT_DATA",
                "previous_ticker_count": "INSUFFICIENT_HISTORY",
                "current_status_mix": "{}",
                "previous_status_mix": "INSUFFICIENT_HISTORY",
                "drift_status": "INSUFFICIENT_HISTORY",
                "confidence": "LOW",
            }
        )
    for sector in sectors:
        cur = current_groups.get(sector, {"count": 0, "status_mix": {}})
        prev = previous_groups.get(sector, {"count": "INSUFFICIENT_HISTORY", "status_mix": "INSUFFICIENT_HISTORY"})
        rows.append(
            {
                "micro_sector": sector,
                "current_ticker_count": cur["count"],
                "previous_ticker_count": prev["count"],
                "current_status_mix": json.dumps(cur["status_mix"], ensure_ascii=False, sort_keys=True),
                "previous_status_mix": json.dumps(prev["status_mix"], ensure_ascii=False, sort_keys=True) if isinstance(prev["status_mix"], dict) else prev["status_mix"],
                "drift_status": "INSUFFICIENT_HISTORY" if not previous_found else ("DRIFT_PRESENT" if cur != prev else "NO_DRIFT_DETECTED"),
                "confidence": "LOW" if not previous_found else "MEDIUM",
            }
        )
    return pd.DataFrame(rows, columns=SECTOR_DRIFT_COLUMNS)


def build_company_score_drift(current: pd.DataFrame, previous: pd.DataFrame, previous_found: bool) -> pd.DataFrame:
    current_by_ticker = _index_by_ticker(current)
    previous_by_ticker = _index_by_ticker(previous)
    tickers = sorted(set(current_by_ticker) | set(previous_by_ticker))
    rows = []
    for ticker in tickers:
        current_score = _first_non_missing(current_by_ticker.get(ticker, {}).get("confidence_score"), "")
        previous_score = _first_non_missing(previous_by_ticker.get(ticker, {}).get("confidence_score"), "INSUFFICIENT_HISTORY" if not previous_found else "")
        change = _score_change(previous_score, current_score) if previous_found else "INSUFFICIENT_HISTORY"
        rows.append(
            {
                "ticker": ticker,
                "current_confidence_score": current_score,
                "previous_confidence_score": previous_score,
                "score_change": change,
                "drift_status": _drift_flag(change, previous_found),
                "confidence": "LOW" if not previous_found else "MEDIUM",
            }
        )
    return pd.DataFrame(rows, columns=COMPANY_DRIFT_COLUMNS)


def build_summary(
    *,
    config: dict[str, Any],
    current_snapshot: pd.DataFrame,
    previous_found: bool,
    snapshot_created: bool,
    watchlist_change_log: pd.DataFrame,
    manual_review_trend: pd.DataFrame,
    data_coverage_trend: pd.DataFrame,
    source_conflict_trend: pd.DataFrame,
    missing_inputs: list[str],
    warnings: list[str],
    forbidden_hits: list[str],
    core_outputs_modified: bool,
) -> dict[str, Any]:
    confidence = config.get("source_confidence") or {}
    change_count = int(watchlist_change_log["change_type"].isin(["ADDED", "REMOVED", "STATUS_CHANGED", "SCORE_CHANGED"]).sum()) if not watchlist_change_log.empty else 0
    manual_trend_available = previous_found and _trend_available(manual_review_trend)
    data_trend_available = previous_found and _trend_available(data_coverage_trend)
    source_trend_available = previous_found and _trend_available(source_conflict_trend)
    if forbidden_hits or core_outputs_modified or current_snapshot.empty:
        final_decision = "BLOCKED_MONITORING_MODULE"
    elif previous_found and not missing_inputs:
        final_decision = "CONDITIONAL_GO_FOR_STEP24_FINAL_INTEGRATION"
    else:
        final_decision = "PASS_MONITORING_WITH_WARNINGS"
    if final_decision not in FINAL_DECISIONS:
        raise ValueError(f"Invalid STEP23 final decision: {final_decision}")
    summary_warnings = list(warnings)
    summary_warnings.extend(
        [
            SAFETY_NOTICE,
            "Monitoring uses existing provisional artifacts only.",
            "Missing historical context is reported as INSUFFICIENT_HISTORY.",
            "Manual BCTC and independent source verification remain required.",
        ]
    )
    if missing_inputs:
        summary_warnings.append("Some configured inputs were unavailable.")
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "mode": MODE,
        "snapshot_created": bool(snapshot_created),
        "previous_snapshot_found": bool(previous_found),
        "processed_ticker_count": int(len(current_snapshot)),
        "watchlist_change_count": change_count,
        "manual_review_trend_available": bool(manual_trend_available),
        "data_coverage_trend_available": bool(data_trend_available),
        "source_conflict_trend_available": bool(source_trend_available),
        "missing_input_files": missing_inputs,
        "market_source_confidence": confidence.get("market_source_confidence", "PROVISIONAL_PRIMARY_ONLY"),
        "finance_source_confidence_default": confidence.get("finance_source_confidence_default", "PROVISIONAL_LOW"),
        "crosscheck_status": confidence.get("crosscheck_status", "NOT_AVAILABLE"),
        "verification_status": confidence.get("verification_status", "NEEDS_MANUAL_BCTC_REVIEW"),
        "final_decision": final_decision,
        "forbidden_terms_found": forbidden_hits,
        "warnings": summary_warnings,
        "core_outputs_modified": bool(core_outputs_modified),
    }


def build_run_manifest(
    *,
    config: dict[str, Any],
    config_path: Path,
    output_dir: Path,
    snapshots_dir: Path,
    snapshot_path: Path,
    previous_snapshot_path: Path | None,
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
        "snapshots_dir": str(snapshots_dir),
        "snapshot_path": str(snapshot_path),
        "previous_snapshot_path": str(previous_snapshot_path) if previous_snapshot_path else "",
        "max_tickers": int(effective_limit),
        "allow_partial": bool(allow_partial),
        "full_universe_allowed": _as_bool(limits.get("full_universe_allowed", False)),
        "network_usage_if_known": "none",
        "core_outputs_modified": bool(core_outputs_modified),
        "previous_step_outputs_mutated": bool(core_outputs_modified),
        "resolved_inputs": resolved_inputs,
        "missing_input_files": missing_inputs,
    }


def write_step23_outputs(
    *,
    output_dir: Path,
    monitoring_dashboard: pd.DataFrame,
    watchlist_history: pd.DataFrame,
    watchlist_change_log: pd.DataFrame,
    score_change_log: pd.DataFrame,
    reject_reason_trend: pd.DataFrame,
    manual_review_trend: pd.DataFrame,
    data_coverage_trend: pd.DataFrame,
    source_conflict_trend: pd.DataFrame,
    sector_signal_drift: pd.DataFrame,
    company_score_drift: pd.DataFrame,
    summary: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    monitoring_dashboard.to_csv(output_dir / "monitoring_dashboard.csv", index=False)
    watchlist_history.to_csv(output_dir / "watchlist_history.csv", index=False)
    watchlist_change_log.to_csv(output_dir / "watchlist_change_log.csv", index=False)
    score_change_log.to_csv(output_dir / "score_change_log.csv", index=False)
    reject_reason_trend.to_csv(output_dir / "reject_reason_trend.csv", index=False)
    manual_review_trend.to_csv(output_dir / "manual_review_trend.csv", index=False)
    data_coverage_trend.to_csv(output_dir / "data_coverage_trend.csv", index=False)
    source_conflict_trend.to_csv(output_dir / "source_conflict_trend.csv", index=False)
    sector_signal_drift.to_csv(output_dir / "sector_signal_drift.csv", index=False)
    company_score_drift.to_csv(output_dir / "company_score_drift.csv", index=False)
    _write_json(output_dir / "monitoring_summary.json", summary)
    _write_json(output_dir / "run_manifest.json", manifest)
    (output_dir / "backtest_summary.md").write_text(
        build_summary_markdown(
            monitoring_dashboard=monitoring_dashboard,
            watchlist_change_log=watchlist_change_log,
            reject_reason_trend=reject_reason_trend,
            manual_review_trend=manual_review_trend,
            data_coverage_trend=data_coverage_trend,
            source_conflict_trend=source_conflict_trend,
            sector_signal_drift=sector_signal_drift,
            company_score_drift=company_score_drift,
            summary=summary,
        ),
        encoding="utf-8",
    )


def build_summary_markdown(
    *,
    monitoring_dashboard: pd.DataFrame,
    watchlist_change_log: pd.DataFrame,
    reject_reason_trend: pd.DataFrame,
    manual_review_trend: pd.DataFrame,
    data_coverage_trend: pd.DataFrame,
    source_conflict_trend: pd.DataFrame,
    sector_signal_drift: pd.DataFrame,
    company_score_drift: pd.DataFrame,
    summary: dict[str, Any],
) -> str:
    lines = [
        "# Filter Monitoring Summary -- Not a Performance Claim",
        "",
        "## Safety Notice",
        SAFETY_NOTICE,
        "",
        "## Snapshot Summary",
        f"- snapshot_created: {summary.get('snapshot_created', False)}",
        f"- previous_snapshot_found: {summary.get('previous_snapshot_found', False)}",
        f"- processed_ticker_count: {summary.get('processed_ticker_count', 0)}",
        f"- final_decision: {summary.get('final_decision', '')}",
        "",
        "## Watchlist Changes",
        _markdown_table(watchlist_change_log.head(20), ["ticker", "previous_status", "current_status", "change_type"]),
        "",
        "## Reject Reason Trend",
        _markdown_table(reject_reason_trend.head(20), ["reject_reason", "current_count", "previous_count", "trend_direction"]),
        "",
        "## Manual Review Trend",
        _markdown_table(manual_review_trend, ["metric_name", "current_value", "previous_value", "trend_direction", "interpretation"]),
        "",
        "## Data Coverage Trend",
        _markdown_table(data_coverage_trend, ["metric_name", "current_value", "previous_value", "trend_direction", "interpretation"]),
        "",
        "## Source Conflict Trend",
        _markdown_table(source_conflict_trend, ["metric_name", "current_value", "previous_value", "trend_direction", "interpretation"]),
        "",
        "## Sector Signal Drift",
        _markdown_table(sector_signal_drift.head(20), ["micro_sector", "current_ticker_count", "previous_ticker_count", "drift_status"]),
        "",
        "## Company Score Drift",
        _markdown_table(company_score_drift.head(20), ["ticker", "current_confidence_score", "previous_confidence_score", "score_change", "drift_status"]),
        "",
        "## Stability Notes",
        _markdown_table(monitoring_dashboard, ["metric_name", "current_value", "previous_value", "trend_direction", "interpretation"]),
        "",
        "## Data Limitations",
        "- Current evidence remains provisional and primary-only.",
        "- Missing historical context is marked explicitly.",
        "- Missing fields are left unresolved rather than filled.",
        "",
        "## Next Validation Actions",
        "- Keep collecting weekly snapshots.",
        "- Review status drift and data coverage changes.",
        "- Resolve manual BCTC/source verification gaps before deeper conclusions.",
    ]
    return "\n".join(lines) + "\n"


def scan_forbidden_terms(output_dir: Path, extra_paths: list[Path] | None = None) -> list[str]:
    hits: list[str] = []
    paths = [path for path in sorted(output_dir.glob("*")) if path.suffix.lower() in {".csv", ".json", ".md", ".txt"}]
    paths.extend(path for path in (extra_paths or []) if path.exists() and path.suffix.lower() in {".csv", ".json", ".md", ".txt"})
    for path in paths:
        text = _scan_text(path)
        for line_no, line in enumerate(text.splitlines(), start=1):
            lower = line.lower()
            for term in FORBIDDEN_TERMS:
                if _term_in_text(term, lower):
                    hits.append(f"{path.name}:{line_no}:{term}")
    return hits


def _snapshot_metrics(snapshot: pd.DataFrame) -> dict[str, int]:
    return {
        "processed_ticker_count": int(len(snapshot)),
        "watchlist_candidate_count": int(snapshot.get("watchlist_status", pd.Series(dtype=str)).isin(WATCHLIST_CANDIDATE_STATUSES).sum()) if not snapshot.empty else 0,
        "manual_review_count": _manual_review_count(snapshot),
        "rejected_count": int(snapshot.get("watchlist_status", pd.Series(dtype=str)).eq("REJECTED").sum()) if not snapshot.empty else 0,
        "unresolved_field_count": _unresolved_field_count(snapshot),
        "rows_with_unresolved_fields": _rows_with_missing_fields(snapshot),
        "source_conflict_count": _source_conflict_count(snapshot),
        "crosscheck_not_available_count": _crosscheck_not_available_count(snapshot),
        "score_observation_count": _score_observation_count(snapshot),
    }


def _dashboard_row(metric_name: str, current_value: Any, previous_value: Any, previous_found: bool) -> dict[str, Any]:
    if not previous_found or not _is_number(previous_value):
        change: Any = "INSUFFICIENT_HISTORY"
    else:
        change = int(float(current_value) - float(previous_value)) if _is_number(current_value) else "INSUFFICIENT_DATA"
    return {
        "metric_name": metric_name,
        "current_value": current_value,
        "previous_value": previous_value,
        "change": change,
        "trend_direction": _trend_direction(change),
        "interpretation": _interpretation(metric_name, change),
        "confidence": "LOW" if not previous_found else "MEDIUM",
        "manual_review_required": not previous_found or change != 0,
    }


def _interpretation(metric_name: str, change: Any) -> str:
    if change == "INSUFFICIENT_HISTORY":
        return "insufficient_history"
    if not _is_number(change):
        return "insufficient_history"
    numeric_change = float(change)
    if metric_name in {"manual_review_count"}:
        if numeric_change > 0:
            return "manual_review_burden_increased"
        if numeric_change < 0:
            return "manual_review_burden_reduced"
        return "filter_stability_improved"
    if metric_name in {"unresolved_field_count", "rows_with_unresolved_fields"}:
        if numeric_change > 0:
            return "data_coverage_worsened"
        if numeric_change < 0:
            return "data_coverage_improved"
        return "filter_stability_improved"
    if metric_name in {"source_conflict_count", "crosscheck_not_available_count"}:
        if numeric_change > 0:
            return "source_conflicts_increased"
        if numeric_change < 0:
            return "source_conflicts_reduced"
        return "filter_stability_improved"
    if numeric_change == 0:
        return "filter_stability_improved"
    return "filter_stability_worsened"


def _trend_direction(change: Any) -> str:
    if change == "INSUFFICIENT_HISTORY" or not _is_number(change):
        return "insufficient_history"
    numeric_change = float(change)
    if numeric_change > 0:
        return "increased"
    if numeric_change < 0:
        return "decreased"
    return "unchanged"


def _manual_review_count(snapshot: pd.DataFrame) -> int:
    if snapshot.empty or "manual_review_required" not in snapshot.columns:
        return 0
    return int(snapshot["manual_review_required"].map(_as_bool).sum())


def _unresolved_field_count(snapshot: pd.DataFrame) -> int:
    if snapshot.empty or "missing_fields" not in snapshot.columns:
        return 0
    return sum(len(_parse_json_list(value)) for value in snapshot["missing_fields"].astype(str))


def _rows_with_missing_fields(snapshot: pd.DataFrame) -> int:
    if snapshot.empty or "missing_fields" not in snapshot.columns:
        return 0
    return int(snapshot["missing_fields"].astype(str).map(lambda value: len(_parse_json_list(value)) > 0).sum())


def _source_conflict_count(snapshot: pd.DataFrame) -> int:
    if snapshot.empty or "source_conflicts" not in snapshot.columns:
        return 0
    return int(snapshot["source_conflicts"].astype(str).map(lambda value: len(_parse_json_list(value)) > 0).sum())


def _crosscheck_not_available_count(snapshot: pd.DataFrame) -> int:
    if snapshot.empty or "crosscheck_status" not in snapshot.columns:
        return 0
    return int(snapshot["crosscheck_status"].astype(str).str.upper().eq("NOT_AVAILABLE").sum())


def _score_observation_count(snapshot: pd.DataFrame) -> int:
    if snapshot.empty or "confidence_score" not in snapshot.columns:
        return 0
    return int(snapshot["confidence_score"].map(_is_number).sum())


def _reject_counts(snapshot: pd.DataFrame) -> dict[str, int]:
    if snapshot.empty:
        return {}
    rejected = snapshot[snapshot.get("watchlist_status", pd.Series(dtype=str)).astype(str).eq("REJECTED")]
    counts: dict[str, int] = {}
    for reason in rejected.get("reject_reason", pd.Series(dtype=str)).astype(str):
        label = reason if reason.strip() else "REJECTED_WITHOUT_REASON"
        counts[label] = counts.get(label, 0) + 1
    return counts


def _sector_group_summary(snapshot: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if snapshot.empty or "micro_sector" not in snapshot.columns:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for sector, group in snapshot.groupby("micro_sector", dropna=False):
        status_mix = group.get("watchlist_status", pd.Series(dtype=str)).astype(str).value_counts().sort_index()
        out[str(sector or "UNKNOWN")] = {
            "count": int(group["ticker"].nunique()) if "ticker" in group.columns else int(len(group)),
            "status_mix": {key: int(value) for key, value in status_mix.items()},
        }
    return out


def _score_change(previous_score: Any, current_score: Any) -> int | str:
    if not _is_number(previous_score) or not _is_number(current_score):
        return ""
    return int(float(current_score) - float(previous_score))


def _drift_flag(change: Any, previous_found: bool) -> str:
    if not previous_found:
        return "INSUFFICIENT_HISTORY"
    if not _is_number(change):
        return "INSUFFICIENT_DATA"
    if abs(float(change)) >= 10:
        return "SCORE_DRIFT_REVIEW"
    if float(change) != 0:
        return "SCORE_DRIFT_SMALL"
    return "NO_DRIFT_DETECTED"


def _manual_review_change(previous_value: Any, current_value: Any, previous_found: bool) -> str:
    if not previous_found:
        return "INSUFFICIENT_HISTORY"
    previous_bool = _as_bool(previous_value)
    current_bool = _as_bool(current_value)
    if previous_bool == current_bool:
        return "UNCHANGED"
    if current_bool:
        return "NOW_REQUIRES_MANUAL_REVIEW"
    return "MANUAL_REVIEW_REMOVED"


def _trend_available(frame: pd.DataFrame) -> bool:
    if frame.empty or "trend_direction" not in frame.columns:
        return False
    return not frame["trend_direction"].astype(str).eq("insufficient_history").all()


def _timing_liquidity_status(step21_row: dict[str, Any]) -> str:
    timing = str(step21_row.get("timing_risk_bucket", "")).strip()
    liquidity = str(step21_row.get("liquidity_risk_bucket", "")).strip()
    if not timing and not liquidity:
        return "INSUFFICIENT_DATA"
    return f"{timing or 'INSUFFICIENT_DATA'}|{liquidity or 'INSUFFICIENT_DATA'}"


def _combined_tickers(*frames: pd.DataFrame) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for frame in frames:
        for ticker in _ticker_list(frame):
            if ticker not in seen:
                seen.add(ticker)
                out.append(ticker)
    return out


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


def _first_existing_path(spec: Any) -> Path | None:
    candidates = spec if isinstance(spec, list) else [spec]
    for candidate in candidates:
        path = Path(str(candidate))
        if path.exists():
            return path
    return None


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


def _frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    return frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()


def _json_list(values: list[Any]) -> str:
    return json.dumps([str(value) for value in values if not _is_missing(value)], ensure_ascii=False)


def _parse_json_list(value: Any) -> list[str]:
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


def _first_non_missing(*values: Any) -> str:
    for value in values:
        if not _is_missing(value):
            return str(value)
    return "UNKNOWN"


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _is_missing(value: Any) -> bool:
    return value is None or str(value).strip() == "" or str(value).strip().lower() in {"nan", "none", "null", "na"}


def _is_number(value: Any) -> bool:
    if _is_missing(value):
        return False
    try:
        float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return False
    return True


def _term_in_text(term: str, lower_text: str) -> bool:
    if " " in term or "-" in term:
        return term in lower_text
    return re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", lower_text) is not None


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    if frame.empty:
        return "INSUFFICIENT_DATA"
    available = [column for column in columns if column in frame.columns]
    if not available:
        return "INSUFFICIENT_DATA"
    lines = ["| " + " | ".join(available) + " |", "| " + " | ".join(["---"] * len(available)) + " |"]
    for _, row in frame.reindex(columns=available).iterrows():
        values = [_clean_markdown_cell(row.get(column, "UNKNOWN")) for column in available]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def _clean_markdown_cell(value: Any) -> str:
    text = str(value)
    text = text.replace("|", "/").replace("\n", " ").strip()
    return text if text else "UNKNOWN"


def _spec_text(spec: Any) -> str:
    if isinstance(spec, list):
        return "|".join(str(item) for item in spec)
    return str(spec)


def _snapshot_id(created_at: str) -> str:
    compact = created_at.replace("-", "").replace(":", "").replace("+00:00", "Z")
    compact = compact.split(".", 1)[0].replace("T", "_")
    return f"snapshot_{compact}"


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
