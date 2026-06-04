"""Disclosure coverage reporting helpers."""

from __future__ import annotations

from typing import Any

import pandas as pd


DISCLOSURE_COVERAGE_STATUS_COLUMNS = [
    "ticker",
    "status",
    "row_count",
    "source_attempted",
    "source_succeeded",
    "source_empty_response",
    "source_failed",
    "manual_import_available",
    "treated_as_clean",
    "warning_flags",
    "notes",
]


def build_disclosure_coverage_status(
    *,
    tickers: list[str],
    disclosure_df: pd.DataFrame,
    failed_rows: list[dict[str, Any]],
    source_request_summary: pd.DataFrame | None = None,
    manual_import_available: bool = True,
) -> pd.DataFrame:
    request_info = _request_info(source_request_summary)
    rows = []
    failed_by_ticker = {
        clean_ticker(row.get("ticker")): row
        for row in failed_rows
        if row.get("dataset_name") == "disclosure_status"
    }
    row_counts = _row_counts(disclosure_df)
    for ticker in tickers:
        clean = clean_ticker(ticker)
        count = row_counts.get(clean, 0)
        failed = failed_by_ticker.get(clean, {})
        source_attempted = bool(request_info["attempted"])
        source_succeeded = bool(count > 0)
        source_failed = bool(failed)
        empty_response = source_attempted and count == 0 and not source_failed
        status = (
            "DISCLOSURE_DATA_AVAILABLE"
            if count > 0
            else failed.get("status", "DISCLOSURE_DATA_UNAVAILABLE")
        )
        warnings = []
        if count == 0:
            warnings.append("DISCLOSURE_DATA_UNAVAILABLE")
        if empty_response:
            warnings.append("DISCLOSURE_SOURCE_EMPTY_RESPONSE")
        if failed and "BUDGET" in str(failed.get("reason", "")).upper():
            warnings.append("DISCLOSURE_REQUEST_SKIPPED_DUE_TO_BUDGET")
        rows.append(
            {
                "ticker": clean,
                "status": status,
                "row_count": count,
                "source_attempted": source_attempted,
                "source_succeeded": source_succeeded,
                "source_empty_response": empty_response,
                "source_failed": source_failed,
                "manual_import_available": bool(manual_import_available),
                "treated_as_clean": False,
                "warning_flags": "|".join(warnings),
                "notes": failed.get(
                    "reason",
                    "disclosure unavailable is unknown, not clean" if count == 0 else "source rows available",
                ),
            }
        )
    return pd.DataFrame(rows, columns=DISCLOSURE_COVERAGE_STATUS_COLUMNS)


def _request_info(source_request_summary: pd.DataFrame | None) -> dict[str, int]:
    if not isinstance(source_request_summary, pd.DataFrame) or source_request_summary.empty:
        return {"attempted": 0, "succeeded": 0, "failed": 0, "skipped": 0}
    rows = source_request_summary[
        source_request_summary["dataset_name"].astype(str) == "disclosure_status"
    ]
    if rows.empty:
        return {"attempted": 0, "succeeded": 0, "failed": 0, "skipped": 0}
    return {
        "attempted": int(rows["requests_attempted"].astype(int).sum()),
        "succeeded": int(rows["requests_succeeded"].astype(int).sum()),
        "failed": int(rows["requests_failed"].astype(int).sum()),
        "skipped": int(rows["requests_skipped_due_to_budget"].astype(int).sum()),
    }


def _row_counts(df: pd.DataFrame) -> dict[str, int]:
    if not isinstance(df, pd.DataFrame) or df.empty or "ticker" not in df.columns:
        return {}
    return df.assign(_ticker=df["ticker"].map(clean_ticker)).groupby("_ticker").size().to_dict()


def clean_ticker(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()
