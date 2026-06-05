"""Positive-control selection for official disclosure status-list ingestion."""

from __future__ import annotations

from typing import Any

import pandas as pd


POSITIVE_CONTROL_COLUMNS = [
    "ticker",
    "source_category",
    "source_name",
    "source_url",
    "raw_list_type",
    "event_type",
    "severity",
    "evidence_status",
    "notes",
]

SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "unknown": 4,
}


def build_positive_control_tickers(
    status_list_index: pd.DataFrame,
    *,
    max_tickers: int = 20,
) -> pd.DataFrame:
    """Select up to max_tickers from parsed source-confirmed warning rows."""

    if not isinstance(status_list_index, pd.DataFrame) or status_list_index.empty:
        return pd.DataFrame(columns=POSITIVE_CONTROL_COLUMNS)

    required_columns = {"ticker", "event_type", "severity", "evidence_status"}
    if not required_columns.issubset(status_list_index.columns):
        return pd.DataFrame(columns=POSITIVE_CONTROL_COLUMNS)

    candidates = status_list_index.copy()
    candidates["ticker"] = candidates["ticker"].map(_clean_ticker)
    candidates = candidates[candidates["ticker"] != ""]
    candidates = candidates[
        candidates["evidence_status"].astype(str).str.upper() == "SOURCE_CONFIRMED_WARNING"
    ]
    candidates = candidates[
        ~candidates["event_type"].astype(str).str.upper().isin(
            {
                "NO_MATERIAL_DISCLOSURE_FOUND_SOURCE_CHECKED",
                "DISCLOSURE_SOURCE_UNAVAILABLE",
                "DISCLOSURE_SCHEMA_UNKNOWN",
                "DISCLOSURE_PARSE_FAILED",
                "DISCLOSURE_DATA_UNAVAILABLE",
            }
        )
    ]
    if candidates.empty:
        return pd.DataFrame(columns=POSITIVE_CONTROL_COLUMNS)

    candidates["_severity_rank"] = candidates["severity"].map(
        lambda value: SEVERITY_ORDER.get(str(value).strip().lower(), 99)
    )
    candidates = candidates.sort_values(
        by=["_severity_rank", "source_category", "raw_list_type", "ticker"],
        kind="mergesort",
    )

    rows: list[dict[str, Any]] = []
    seen = set()
    for _, row in candidates.iterrows():
        ticker = _clean_ticker(row.get("ticker"))
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        rows.append(
            {
                "ticker": ticker,
                "source_category": row.get("source_category", ""),
                "source_name": row.get("source_name", ""),
                "source_url": row.get("source_url", ""),
                "raw_list_type": row.get("raw_list_type", ""),
                "event_type": row.get("event_type", ""),
                "severity": row.get("severity", ""),
                "evidence_status": "POSITIVE_CONTROL_CONFIRMED",
                "notes": "selected from parsed official/public warning/status list; not manually chosen",
            }
        )
        if len(rows) >= int(max_tickers):
            break
    return pd.DataFrame(rows, columns=POSITIVE_CONTROL_COLUMNS)


def positive_control_status(
    *,
    positive_control_tickers: pd.DataFrame,
    matched_warning_rows: pd.DataFrame,
) -> str:
    """Return the positive-control adapter status requested by 01H."""

    if not isinstance(positive_control_tickers, pd.DataFrame) or positive_control_tickers.empty:
        return "POSITIVE_CONTROL_UNAVAILABLE"
    if not isinstance(matched_warning_rows, pd.DataFrame) or matched_warning_rows.empty:
        return "DISCLOSURE_ADAPTER_FAILED_POSITIVE_CONTROL"
    return "POSITIVE_CONTROL_CONFIRMED"


def _clean_ticker(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()
