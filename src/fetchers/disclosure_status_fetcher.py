"""Disclosure, warning, audit, and trading restriction fetcher interface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.fetchers.base import BaseFetcher, REQUIRED_FETCH_COLUMNS, normalize_fetch_time
from src.fetchers.source_registry import (
    get_fallback_sources,
    get_primary_source,
    load_source_registry,
)


REAL_SOURCE_UNAVAILABLE_MESSAGE = (
    "REAL_SOURCE_UNAVAILABLE: disclosure_status fetcher has no available real "
    "source in this environment"
)

DEFAULT_SOURCE_REGISTRY_PATH = Path("config/data_source_registry.yaml")

RECOMMENDED_EVENT_TYPES = {
    "AUDIT_WARNING",
    "DISCLOSURE_VIOLATION",
    "TRADING_RESTRICTION",
    "SUSPENSION",
    "DELISTING_WARNING",
    "LATE_FINANCIAL_REPORT",
    "NEGATIVE_EQUITY_WARNING",
    "REGULATORY_SANCTION",
    "CORPORATE_GOVERNANCE_WARNING",
    "OTHER",
    "UNKNOWN",
}

RECOMMENDED_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"}

EXPECTED_DISCLOSURE_FIELDS = ["event_type", "severity", "source_url", "notes"]
EXPECTED_MANUAL_COLUMNS = [
    "ticker",
    "date",
    "event_type",
    "severity",
    "source",
    "source_url",
    "notes",
]


class RealSourceUnavailableError(RuntimeError):
    """Raised when real disclosure status fetching is unavailable."""


class DisclosureStatusFetcher(BaseFetcher):
    """Fetch disclosure status data in the standard long format."""

    dataset_name = "disclosure_status"

    def fetch(
        self,
        tickers: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        mode: str = "mock",
        source_name: str | None = None,
        manual_file_path: str | None = None,
    ) -> pd.DataFrame:
        """Fetch or normalize disclosure status data."""

        if mode == "mock":
            return _fetch_mock(tickers=tickers, start_date=start_date)
        if mode == "manual_csv":
            return _fetch_manual_file(
                manual_file_path=manual_file_path,
                file_type="csv",
                tickers=tickers,
                start_date=start_date,
                end_date=end_date,
            )
        if mode == "manual_xlsx":
            return _fetch_manual_file(
                manual_file_path=manual_file_path,
                file_type="xlsx",
                tickers=tickers,
                start_date=start_date,
                end_date=end_date,
            )
        if mode == "real":
            return _fetch_real_unavailable(source_name=source_name)

        raise ValueError(
            "Invalid mode. Expected 'mock', 'manual_csv', 'manual_xlsx', or 'real'."
        )

    def validate_output(self, df: pd.DataFrame) -> dict[str, Any]:
        """Validate standardized disclosure status output."""

        return validate_disclosure_status_output(df)


def load_manual_disclosure_file(path: str, file_type: str) -> pd.DataFrame:
    """Load a manually provided CSV or XLSX file."""

    if not path:
        raise ValueError("manual_file_path is required for manual file modes.")

    if file_type == "csv":
        return pd.read_csv(path)
    if file_type == "xlsx":
        return pd.read_excel(path)

    raise ValueError("file_type must be 'csv' or 'xlsx'.")


def normalize_disclosure_wide_to_long(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize wide disclosure status rows into standard long fetch format."""

    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame.")

    normalized_df = df.copy()
    if "event_type" in normalized_df.columns:
        normalized_df["event_type"] = normalized_df["event_type"].map(
            normalize_event_type
        )
    if "severity" in normalized_df.columns:
        normalized_df["severity"] = normalized_df["severity"].map(normalize_severity)

    present_fields = [
        field for field in EXPECTED_DISCLOSURE_FIELDS if field in normalized_df.columns
    ]
    if not present_fields:
        present_fields = ["ticker"] if "ticker" in normalized_df.columns else []

    rows: list[dict[str, Any]] = []
    for _, row in normalized_df.iterrows():
        ticker = row.get("ticker", "")
        event_date = row.get("date", "")
        row_source = _row_source(row)
        row_source_url = row.get("source_url", "")
        row_fetch_time = _row_fetch_time(row)
        confidence_raw = _row_confidence(row)
        row_notes = _row_notes(row)

        for field in present_fields:
            rows.append(
                {
                    "dataset_name": "disclosure_status",
                    "ticker": ticker,
                    "date": event_date,
                    "field": field,
                    "value": row.get(field, pd.NA),
                    "source": row_source,
                    "source_url": row_source_url,
                    "fetch_time": row_fetch_time,
                    "confidence_raw": confidence_raw,
                    "notes": row_notes,
                }
            )

    return pd.DataFrame(rows, columns=REQUIRED_FETCH_COLUMNS)


def normalize_event_type(value: Any) -> str:
    """Normalize event type to a recommended disclosure event label."""

    if _is_missing(value):
        return "UNKNOWN"

    normalized = str(value).strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "AUDIT": "AUDIT_WARNING",
        "AUDIT_ISSUE": "AUDIT_WARNING",
        "DISCLOSURE": "DISCLOSURE_VIOLATION",
        "VIOLATION": "DISCLOSURE_VIOLATION",
        "RESTRICTED": "TRADING_RESTRICTION",
        "TRADING_RESTRICTED": "TRADING_RESTRICTION",
        "SUSPENDED": "SUSPENSION",
        "DELISTING": "DELISTING_WARNING",
        "LATE_REPORT": "LATE_FINANCIAL_REPORT",
        "NEGATIVE_EQUITY": "NEGATIVE_EQUITY_WARNING",
        "SANCTION": "REGULATORY_SANCTION",
        "GOVERNANCE": "CORPORATE_GOVERNANCE_WARNING",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in RECOMMENDED_EVENT_TYPES:
        return normalized
    return "UNKNOWN"


def normalize_severity(value: Any) -> str:
    """Normalize severity to LOW, MEDIUM, HIGH, CRITICAL, or UNKNOWN."""

    if _is_missing(value):
        return "UNKNOWN"

    normalized = str(value).strip().upper()
    aliases = {
        "L": "LOW",
        "M": "MEDIUM",
        "MED": "MEDIUM",
        "H": "HIGH",
        "SEVERE": "HIGH",
        "C": "CRITICAL",
        "CRIT": "CRITICAL",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in RECOMMENDED_SEVERITIES:
        return normalized
    return "UNKNOWN"


def validate_disclosure_status_output(df: pd.DataFrame) -> dict[str, Any]:
    """Validate standardized disclosure status fetch output."""

    result = _standard_validation_result()
    if not isinstance(df, pd.DataFrame):
        result["is_valid"] = False
        result["errors"].append("Fetcher output must be a pandas DataFrame.")
        return result

    actual_columns = list(df.columns)
    result["missing_columns"] = [
        column for column in REQUIRED_FETCH_COLUMNS if column not in actual_columns
    ]
    result["extra_columns"] = [
        column for column in actual_columns if column not in REQUIRED_FETCH_COLUMNS
    ]
    if result["missing_columns"]:
        result["is_valid"] = False
        result["warnings"].append(
            "Missing required fetch columns: "
            + ", ".join(result["missing_columns"])
        )
        return result

    disclosure_rows = df[df["dataset_name"] == "disclosure_status"]
    if not disclosure_rows.empty:
        fields = set(disclosure_rows["field"])
        missing_fields = [
            field for field in EXPECTED_DISCLOSURE_FIELDS if field not in fields
        ]
        if missing_fields:
            result["warnings"].append(
                "disclosure_status: missing expected fields: "
                + ", ".join(missing_fields)
            )

    for index, row in df.iterrows():
        field = row["field"]
        value = row["value"]

        if _is_missing(row["ticker"]):
            result["is_valid"] = False
            result["errors"].append(f"row {index}: missing ticker")
        if _is_missing(row["date"]):
            result["is_valid"] = False
            result["errors"].append(f"row {index}: missing date")
        if _is_missing(field):
            result["is_valid"] = False
            result["errors"].append(f"row {index}: missing field")
        if _is_missing(row["source"]):
            result["is_valid"] = False
            result["errors"].append(f"row {index}: missing source")
        if _is_missing(row["fetch_time"]):
            result["is_valid"] = False
            result["errors"].append(f"row {index}: missing fetch_time")

        if field == "event_type":
            normalized_value = normalize_event_type(value)
            if _is_missing(value):
                result["warnings"].append(f"row {index}: missing event_type")
            elif normalized_value == "UNKNOWN" and str(value).strip().upper() != "UNKNOWN":
                result["warnings"].append(
                    f"row {index}: event_type normalized to UNKNOWN"
                )
        elif field == "severity":
            normalized_value = normalize_severity(value)
            if _is_missing(value):
                result["warnings"].append(f"row {index}: missing severity")
            elif normalized_value == "UNKNOWN" and str(value).strip().upper() != "UNKNOWN":
                result["warnings"].append(
                    f"row {index}: severity normalized to UNKNOWN"
                )

    result["warnings"] = _dedupe(result["warnings"])
    result["errors"] = _dedupe(result["errors"])
    return result


def _fetch_mock(
    tickers: list[str] | None = None, start_date: str | None = None
) -> pd.DataFrame:
    requested_tickers = tickers or ["MOCK1", "MOCK2", "MOCK3"]
    normalized_tickers = [_normalize_ticker(ticker) for ticker in requested_tickers]
    if any(not ticker.startswith("MOCK") for ticker in normalized_tickers):
        raise ValueError("Mock mode only supports obvious MOCK tickers.")

    event_date = start_date or "2026-01-01"
    fetch_time = normalize_fetch_time("2026-01-01T00:00:00Z")
    rows = []
    event_types = ["AUDIT_WARNING", "TRADING_RESTRICTION", "OTHER"]
    severities = ["LOW", "MEDIUM", "HIGH"]
    for index, ticker in enumerate(normalized_tickers):
        rows.append(
            {
                "ticker": ticker,
                "date": event_date,
                "event_type": event_types[index % len(event_types)],
                "severity": severities[index % len(severities)],
                "source": "MOCK",
                "source_url": "",
                "fetch_time": fetch_time,
                "confidence_raw": "mock",
                "notes": (
                    "mock disclosure status data only; not real or production "
                    "disclosure data"
                ),
            }
        )

    return normalize_disclosure_wide_to_long(pd.DataFrame(rows))


def _fetch_manual_file(
    manual_file_path: str | None,
    file_type: str,
    tickers: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    manual_df = load_manual_disclosure_file(manual_file_path or "", file_type)

    if tickers is not None and "ticker" in manual_df.columns:
        requested_tickers = {_normalize_ticker(ticker) for ticker in tickers}
        manual_df = manual_df[
            manual_df["ticker"].map(_normalize_ticker).isin(requested_tickers)
        ]

    if "date" in manual_df.columns:
        dates = pd.to_datetime(manual_df["date"], errors="coerce")
        if start_date is not None:
            manual_df = manual_df[dates >= pd.Timestamp(start_date)]
            dates = pd.to_datetime(manual_df["date"], errors="coerce")
        if end_date is not None:
            manual_df = manual_df[dates <= pd.Timestamp(end_date)]

    return normalize_disclosure_wide_to_long(manual_df)


def _fetch_real_unavailable(source_name: str | None = None) -> pd.DataFrame:
    registry = _load_registry_if_available()
    if registry:
        primary_source = get_primary_source(registry, "disclosure_status")
        fallback_sources = get_fallback_sources(registry, "disclosure_status")
        available_source_names = [
            source["source_name"]
            for source in [primary_source, *fallback_sources]
            if source and "source_name" in source
        ]
        if source_name and source_name not in available_source_names:
            raise RealSourceUnavailableError(
                f"{REAL_SOURCE_UNAVAILABLE_MESSAGE}; requested source "
                f"'{source_name}' is not configured for disclosure_status"
            )

    raise RealSourceUnavailableError(REAL_SOURCE_UNAVAILABLE_MESSAGE)


def _load_registry_if_available() -> dict[str, Any] | None:
    if not DEFAULT_SOURCE_REGISTRY_PATH.exists():
        return None
    return load_source_registry(str(DEFAULT_SOURCE_REGISTRY_PATH))


def _row_source(row: pd.Series) -> str:
    if "source" in row.index and not _is_missing(row["source"]):
        return str(row["source"])
    return "MANUAL_FILE_UNKNOWN_SOURCE"


def _row_fetch_time(row: pd.Series) -> str:
    if "fetch_time" in row.index and not _is_missing(row["fetch_time"]):
        return str(row["fetch_time"])
    return normalize_fetch_time()


def _row_confidence(row: pd.Series) -> str:
    for confidence_field in ["confidence_raw", "confidence"]:
        if confidence_field in row.index and not _is_missing(row[confidence_field]):
            return str(row[confidence_field])
    return "medium"


def _row_notes(row: pd.Series) -> str:
    if "notes" in row.index and not _is_missing(row["notes"]):
        return str(row["notes"])
    return "manual disclosure status file; user-provided and requires validation"


def _normalize_ticker(ticker: Any) -> str:
    if ticker is None or pd.isna(ticker):
        return ""
    return str(ticker).strip().upper()


def _is_missing(value: Any) -> bool:
    if value is None or pd.isna(value):
        return True
    return isinstance(value, str) and not value.strip()


def _standard_validation_result() -> dict[str, Any]:
    return {
        "dataset_name": "disclosure_status",
        "is_valid": True,
        "missing_columns": [],
        "extra_columns": [],
        "warnings": [],
        "errors": [],
    }


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
