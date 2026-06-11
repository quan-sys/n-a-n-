"""Reconcile provisional legacy universe counts and data availability."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd


UNIVERSE_RECONCILIATION_COLUMNS = [
    "ticker",
    "in_legacy_quality",
    "in_legacy_market",
    "in_ranking",
    "exchange",
    "sector_raw",
    "has_market_data",
    "has_finance_data",
    "data_quality_status",
    "possible_issue",
    "recommended_action",
]


def build_universe_reconciliation(legacy_quality: pd.DataFrame, ranking: pd.DataFrame, legacy_market: pd.DataFrame) -> pd.DataFrame:
    quality = _frame(legacy_quality)
    ranking = _frame(ranking)
    market = _frame(legacy_market)
    ticker_set = _tickers(quality) | _tickers(ranking) | _tickers(market)
    duplicate_tickers = _duplicate_tickers(quality) | _duplicate_tickers(ranking) | _duplicate_tickers(market)
    quality_by_ticker = _index_by_ticker(quality)
    ranking_by_ticker = _index_by_ticker(ranking)
    market_by_ticker = _index_by_ticker(market)

    rows = []
    for ticker in sorted(ticker_set):
        q = quality_by_ticker.get(ticker, {})
        r = ranking_by_ticker.get(ticker, {})
        m = market_by_ticker.get(ticker, {})
        has_market = _has_market_data(m)
        has_finance = _to_int(q.get("finance_field_count")) > 0
        exchange = _first(r.get("exchange"), m.get("exchange"))
        sector = _first(r.get("sector_raw"), m.get("sector_raw"))
        data_quality = str(q.get("export_status") or "").strip()
        issue = _issue_for_row(
            ticker=ticker,
            in_quality=ticker in quality_by_ticker,
            in_market=ticker in market_by_ticker,
            in_ranking=ticker in ranking_by_ticker,
            exchange=exchange,
            has_market=has_market,
            has_finance=has_finance,
            data_quality=data_quality,
            duplicate=ticker in duplicate_tickers,
        )
        rows.append(
            {
                "ticker": ticker,
                "in_legacy_quality": ticker in quality_by_ticker,
                "in_legacy_market": ticker in market_by_ticker,
                "in_ranking": ticker in ranking_by_ticker,
                "exchange": exchange,
                "sector_raw": sector,
                "has_market_data": has_market,
                "has_finance_data": has_finance,
                "data_quality_status": data_quality,
                "possible_issue": issue,
                "recommended_action": _recommended_action(issue),
            }
        )
    return pd.DataFrame(rows, columns=UNIVERSE_RECONCILIATION_COLUMNS)


def build_universe_reconciliation_summary(reconciliation: pd.DataFrame, old_reference_count: int = 1743) -> str:
    current_count = int(reconciliation["ticker"].nunique()) if not reconciliation.empty else 0
    enough_data = int(reconciliation["data_quality_status"].eq("OK_FOR_PROVISIONAL_SCREEN").sum()) if not reconciliation.empty else 0
    stage2_exclusions = int((~reconciliation["has_market_data"].astype(bool) | ~reconciliation["has_finance_data"].astype(bool)).sum()) if not reconciliation.empty else 0
    delta = current_count - old_reference_count
    issue_counts = Counter(reconciliation["possible_issue"].astype(str)) if not reconciliation.empty else {}
    lines = [
        "# Universe Reconciliation 02",
        "",
        f"- generated_at: {datetime.now(UTC).replace(microsecond=0).isoformat()}",
        f"- current_ticker_count: {current_count}",
        f"- old_reference_count_from_prior_snapshot: {old_reference_count}",
        f"- delta_vs_old_reference: {delta}",
        f"- enough_data_for_provisional_screening: {enough_data}",
        f"- should_exclude_from_stage_2_plus_due_to_missing_market_or_finance: {stage2_exclusions}",
        "",
        "## Possible Issue Counts",
    ]
    for issue, count in sorted(issue_counts.items()):
        lines.append(f"- {issue}: {count}")
    lines.extend(
        [
            "",
            "## 1800 vs 1743 Explanation",
            "- The current count is produced from the available legacy export/import universe, market, and quality files.",
            "- The old 1743 list is not present as a reproducible ticker snapshot in this repo, so it was not fabricated.",
            "- The difference can be explained only as far as local data allows: the current export includes all tickers present in legacy cache/output/universe inputs, including rows with CACHE_MISSING or INSUFFICIENT_DATA.",
            "- Treat tickers with missing market or finance data as lower-priority/manual-review evidence candidates, not clean stage_2+ names.",
            "",
            "## Safety",
            "- No finance values were inferred or zero-filled.",
            "- This reconciliation does not create recommendations or official verification.",
        ]
    )
    return "\n".join(lines) + "\n"


def _issue_for_row(
    *,
    ticker: str,
    in_quality: bool,
    in_market: bool,
    in_ranking: bool,
    exchange: str,
    has_market: bool,
    has_finance: bool,
    data_quality: str,
    duplicate: bool,
) -> str:
    if duplicate:
        return "POSSIBLE_DUPLICATE"
    if not exchange:
        return "UNKNOWN_EXCHANGE"
    if not in_ranking and (in_quality or in_market):
        return "CACHE_ONLY_EXTRA_TICKER"
    if not has_market:
        return "MISSING_MARKET_DATA"
    if not has_finance:
        if data_quality in {"CACHE_MISSING", "INSUFFICIENT_DATA"}:
            return "POSSIBLE_DELISTED_OR_INACTIVE"
        return "MISSING_FINANCE_DATA"
    return "OK"


def _recommended_action(issue: str) -> str:
    return {
        "OK": "Eligible for provisional evidence prioritization only.",
        "CACHE_ONLY_EXTRA_TICKER": "Keep in reconciliation report; require current universe validation before stage_2+.",
        "MISSING_MARKET_DATA": "Do not promote to stage_2+ until market data is present.",
        "MISSING_FINANCE_DATA": "Do not promote to stage_2+ until provisional or official finance data exists.",
        "POSSIBLE_DELISTED_OR_INACTIVE": "Manual review listing status before evidence collection.",
        "POSSIBLE_DUPLICATE": "Manual deduplication review.",
        "UNKNOWN_EXCHANGE": "Verify exchange/listing identity before stage_2+.",
    }.get(issue, "Manual review required.")


def _frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()


def _tickers(frame: pd.DataFrame) -> set[str]:
    if frame.empty or "ticker" not in frame.columns:
        return set()
    return {str(value).strip().upper() for value in frame["ticker"] if str(value).strip()}


def _duplicate_tickers(frame: pd.DataFrame) -> set[str]:
    if frame.empty or "ticker" not in frame.columns:
        return set()
    values = frame["ticker"].astype(str).str.upper().str.strip()
    return set(values[values.duplicated(keep=False)])


def _index_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty or "ticker" not in frame.columns:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for _, row in frame.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        if ticker:
            out[ticker] = row.to_dict()
    return out


def _has_market_data(row: dict[str, Any]) -> bool:
    return any(_to_float(row.get(column)) is not None for column in ["last_close", "avg_volume_10d", "avg_volume_20d", "avg_volume_60d"])


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _to_int(value: Any) -> int:
    number = _to_float(value)
    return int(number) if number is not None else 0


def _first(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
