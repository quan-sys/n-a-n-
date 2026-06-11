"""Stage-2 eligibility gate based on fresh market data and finance minimums."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


STAGE2_PLUS = {
    "stage_2_evidence_candidates",
    "stage_3_final_watchlist",
    "stage_4_deep_dive_shortlist",
}

STAGE1 = "stage_1_provisional_shortlist"

GATE_COLUMNS = [
    "ticker",
    "raw_rank",
    "original_stage",
    "new_stage",
    "eligibility_status",
    "demotion_reason",
    "exchange",
    "missing_market_flag",
    "stale_price_flag",
    "stale_days",
    "trading_days_60d",
    "avg_volume_60d",
    "finance_quality_status",
    "finance_core_metrics_present",
    "finance_years_any_core_metric",
    "finance_minimum_pass",
    "finance_crosscheck_status",
    "finance_confidence",
    "manual_review_required",
]


def load_stage2_gate_policy(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def build_stage2_eligibility_gate(
    ranking: pd.DataFrame,
    current_market: pd.DataFrame,
    finance_quality: pd.DataFrame,
    finance_long: pd.DataFrame,
    finance_crosscheck: pd.DataFrame,
    policy: dict[str, Any],
) -> pd.DataFrame:
    rank_frame = _frame(ranking)
    market_by_ticker = _index_by_ticker(current_market)
    quality_by_ticker = _index_by_ticker(finance_quality)
    finance_counts = _finance_metric_counts(finance_long, policy)
    finance_status = _finance_crosscheck_status_by_ticker(finance_crosscheck)
    rows = []
    for _, row in rank_frame.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        original_stage = _original_stage(row)
        market = market_by_ticker.get(ticker, {})
        quality = quality_by_ticker.get(ticker, {})
        metric_count = finance_counts.get(ticker, {}).get("metric_count", 0)
        years_count = finance_counts.get(ticker, {}).get("years_count", 0)
        finance_pass = _finance_minimum_pass(quality, metric_count, years_count, policy)
        status = _eligibility_status(row, market, quality, finance_pass, finance_status.get(ticker, "ONE_SOURCE_ONLY"), policy)
        new_stage = STAGE1 if original_stage in STAGE2_PLUS and status != "STAGE2_ELIGIBLE" else original_stage
        rows.append(
            {
                "ticker": ticker,
                "raw_rank": _rank_value(row),
                "original_stage": original_stage,
                "new_stage": new_stage,
                "eligibility_status": status,
                "demotion_reason": "" if new_stage == original_stage else status,
                "exchange": row.get("exchange", ""),
                "missing_market_flag": _as_bool(market.get("missing_market_flag", True)),
                "stale_price_flag": _as_bool(market.get("stale_price_flag", True)),
                "stale_days": market.get("stale_days", ""),
                "trading_days_60d": _to_int(market.get("trading_days_60d")),
                "avg_volume_60d": market.get("avg_volume_60d", ""),
                "finance_quality_status": quality.get("export_status", ""),
                "finance_core_metrics_present": metric_count,
                "finance_years_any_core_metric": years_count,
                "finance_minimum_pass": finance_pass,
                "finance_crosscheck_status": finance_status.get(ticker, "ONE_SOURCE_ONLY"),
                "finance_confidence": "PROVISIONAL_LOW",
                "manual_review_required": status != "STAGE2_ELIGIBLE",
            }
        )
    return pd.DataFrame(rows, columns=GATE_COLUMNS)


def build_stage2_eligibility_summary(gate: pd.DataFrame) -> str:
    status_counts = Counter(gate["eligibility_status"].astype(str)) if not gate.empty else {}
    before = Counter(gate["original_stage"].astype(str)) if not gate.empty else {}
    after = Counter(gate["new_stage"].astype(str)) if not gate.empty else {}
    demoted = int((gate["original_stage"].isin(STAGE2_PLUS) & ~gate["original_stage"].eq(gate["new_stage"])).sum()) if not gate.empty else 0
    lines = [
        "# Stage-2 Eligibility Gate 03",
        "",
        f"- generated_at: {datetime.now(UTC).replace(microsecond=0).isoformat()}",
        f"- total_rows: {len(gate)}",
        f"- eligible_count: {int(status_counts.get('STAGE2_ELIGIBLE', 0))}",
        f"- blocked_missing_market_count: {int(status_counts.get('BLOCKED_MISSING_MARKET', 0))}",
        f"- blocked_stale_market_count: {int(status_counts.get('BLOCKED_STALE_MARKET', 0))}",
        f"- blocked_insufficient_trading_days_count: {int(status_counts.get('BLOCKED_INSUFFICIENT_TRADING_DAYS', 0))}",
        f"- blocked_missing_min_finance_count: {int(status_counts.get('BLOCKED_MISSING_MIN_FINANCE', 0))}",
        f"- blocked_unknown_exchange_count: {int(status_counts.get('BLOCKED_UNKNOWN_EXCHANGE', 0))}",
        f"- manual_review_count: {int((gate['manual_review_required'].astype(bool)).sum()) if not gate.empty else 0}",
        f"- demoted_from_stage2_plus_count: {demoted}",
        "",
        "## Stage Distribution Before",
        *[f"- {stage}: {count}" for stage, count in sorted(before.items())],
        "",
        "## Stage Distribution After",
        *[f"- {stage}: {count}" for stage, count in sorted(after.items())],
        "",
        "## Safety",
        "- ONE_SOURCE_ONLY finance remains PROVISIONAL_LOW.",
        "- The gate demotes evidence workload stage only; it does not delete tickers or create recommendations.",
    ]
    return "\n".join(lines) + "\n"


def _eligibility_status(
    ranking_row: pd.Series,
    market: dict[str, Any],
    quality: dict[str, Any],
    finance_pass: bool,
    finance_crosscheck_status: str,
    policy: dict[str, Any],
) -> str:
    exchange = str(ranking_row.get("exchange", "") or "").strip().upper()
    if not exchange or exchange == "UNKNOWN":
        return "BLOCKED_UNKNOWN_EXCHANGE"
    if str(finance_crosscheck_status) == "SOURCE_CONFLICT":
        return "MANUAL_REVIEW_DATA_CONFLICT"
    if _as_bool(market.get("missing_market_flag", True)):
        return "BLOCKED_MISSING_MARKET"
    if _as_bool(market.get("stale_price_flag", True)):
        return "BLOCKED_STALE_MARKET"
    min_days = int((policy.get("market_refresh", {}) or {}).get("min_trading_days_60d_for_stage2", 30) or 30)
    if _to_int(market.get("trading_days_60d")) < min_days:
        return "BLOCKED_INSUFFICIENT_TRADING_DAYS"
    min_volume = (policy.get("market_refresh", {}) or {}).get("min_avg_volume_60d_for_stage2")
    if min_volume is not None and _to_float(market.get("avg_volume_60d")) is not None and _to_float(market.get("avg_volume_60d")) < float(min_volume):
        return "BLOCKED_INSUFFICIENT_TRADING_DAYS"
    if not finance_pass:
        return "BLOCKED_MISSING_MIN_FINANCE"
    return "STAGE2_ELIGIBLE"


def _finance_minimum_pass(quality: dict[str, Any], metric_count: int, years_count: int, policy: dict[str, Any]) -> bool:
    status = str(quality.get("export_status", "") or "").strip().upper()
    if status == "OK_FOR_PROVISIONAL_SCREEN":
        return True
    if status in {"INSUFFICIENT_DATA", "CACHE_MISSING"}:
        return False
    minimum = policy.get("minimum_finance_required", {})
    min_metrics = int(minimum.get("min_core_metrics_present", 3) or 3)
    min_years = int(minimum.get("min_years_any_core_metric", 2) or 2)
    return metric_count >= min_metrics and years_count >= min_years


def _finance_metric_counts(finance_long: pd.DataFrame, policy: dict[str, Any]) -> dict[str, dict[str, int]]:
    frame = _frame(finance_long)
    if frame.empty:
        return {}
    minimum = policy.get("minimum_finance_required", {})
    metrics = set(minimum.get("core_metrics", ["revenue", "net_income", "total_assets", "equity", "cfo"]))
    if minimum.get("allow_financial_income_for_financial_firms", True):
        metrics.add("financial_income")
    for column in ["ticker", "field_name", "period", "value"]:
        if column not in frame.columns:
            frame[column] = ""
    frame = frame[frame["field_name"].astype(str).isin(metrics)].copy()
    frame["_numeric_value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["_numeric_value"])
    out: dict[str, dict[str, int]] = {}
    for ticker, group in frame.groupby(frame["ticker"].astype(str).str.upper()):
        out[ticker] = {
            "metric_count": int(group["field_name"].nunique()),
            "years_count": int(group["period"].astype(str).nunique()),
        }
    return out


def _finance_crosscheck_status_by_ticker(frame: pd.DataFrame) -> dict[str, str]:
    frame = _frame(frame)
    if frame.empty or "ticker" not in frame.columns:
        return {}
    status_col = "finance_crosscheck_status" if "finance_crosscheck_status" in frame.columns else "crosscheck_status"
    priority = {"SOURCE_CONFLICT": 3, "MISSING_VALUE_IN_SOURCES": 2, "ONE_SOURCE_ONLY": 1, "MULTI_SOURCE_AGREES": 0}
    out = {}
    for ticker, group in frame.groupby(frame["ticker"].astype(str).str.upper()):
        statuses = [str(value) for value in group.get(status_col, [])]
        out[ticker] = max(statuses, key=lambda status: priority.get(status, 0)) if statuses else "ONE_SOURCE_ONLY"
    return out


def _original_stage(row: pd.Series) -> str:
    return str(row.get("stage") or row.get("evidence_stage") or "").strip()


def _rank_value(row: pd.Series) -> int:
    for column in ["balanced_rank", "rank", "raw_rank"]:
        if column in row and _to_int(row.get(column)) > 0:
            return _to_int(row.get(column))
    return 0


def _index_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    frame = _frame(frame)
    if frame.empty or "ticker" not in frame.columns:
        return {}
    out = {}
    for _, row in frame.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        if ticker:
            out[ticker] = row.to_dict()
    return out


def _frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _to_int(value: Any) -> int:
    number = _to_float(value)
    return int(number) if number is not None else 0


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None
