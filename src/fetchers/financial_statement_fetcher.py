"""Financial statement summary fetcher interface."""

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
    "REAL_SOURCE_UNAVAILABLE: financial_statement_summary fetcher has no "
    "available real source in this environment"
)

DEFAULT_SOURCE_REGISTRY_PATH = Path("config/data_source_registry.yaml")

FINANCIAL_NUMERIC_FIELDS = [
    "revenue",
    "gross_profit",
    "operating_profit",
    "net_profit",
    "total_assets",
    "total_liabilities",
    "equity",
    "cash",
    "short_term_debt",
    "long_term_debt",
    "operating_cash_flow",
    "inventory",
]

EXPECTED_FINANCIAL_FIELDS = [
    "period",
    *FINANCIAL_NUMERIC_FIELDS,
    "source",
    "fetch_time",
]


class RealSourceUnavailableError(RuntimeError):
    """Raised when real financial statement fetching is unavailable."""


class FinancialStatementFetcher(BaseFetcher):
    """Fetch financial statement summaries in the standard long format."""

    dataset_name = "financial_statement_summary"

    def fetch(
        self,
        tickers: list[str] | None = None,
        periods: list[str] | None = None,
        mode: str = "mock",
        source_name: str | None = None,
        manual_file_path: str | None = None,
    ) -> pd.DataFrame:
        """Fetch or normalize financial statement summary data."""

        if mode == "mock":
            return _fetch_mock(tickers=tickers, periods=periods)
        if mode == "manual_csv":
            return _fetch_manual_file(
                manual_file_path=manual_file_path,
                file_type="csv",
                tickers=tickers,
                periods=periods,
            )
        if mode == "manual_xlsx":
            return _fetch_manual_file(
                manual_file_path=manual_file_path,
                file_type="xlsx",
                tickers=tickers,
                periods=periods,
            )
        if mode == "real":
            return _fetch_real_unavailable(source_name=source_name)

        raise ValueError(
            "Invalid mode. Expected 'mock', 'manual_csv', 'manual_xlsx', or 'real'."
        )

    def validate_output(self, df: pd.DataFrame) -> dict[str, Any]:
        """Validate standardized financial statement output."""

        return validate_financial_statement_output(df)


def load_manual_financial_file(path: str, file_type: str) -> pd.DataFrame:
    """Load a manually provided CSV or XLSX file."""

    if not path:
        raise ValueError("manual_file_path is required for manual file modes.")

    if file_type == "csv":
        return pd.read_csv(path)
    if file_type == "xlsx":
        return pd.read_excel(path)

    raise ValueError("file_type must be 'csv' or 'xlsx'.")


def normalize_financials_wide_to_long(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize wide financial statement rows into standard long fetch format."""

    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame.")

    present_fields = [
        field for field in EXPECTED_FINANCIAL_FIELDS if field in df.columns
    ]
    if not present_fields:
        present_fields = ["ticker"] if "ticker" in df.columns else []

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        ticker = row.get("ticker", "")
        period = row.get("period", "")
        row_source = _row_source(row)
        row_fetch_time = _row_fetch_time(row)
        confidence_raw = _row_confidence(row)
        notes = _row_notes(row)

        for field in present_fields:
            rows.append(
                {
                    "dataset_name": "financial_statement_summary",
                    "ticker": ticker,
                    "date": period,
                    "field": field,
                    "value": row.get(field, pd.NA),
                    "source": row_source,
                    "source_url": row.get("source_url", ""),
                    "fetch_time": row_fetch_time,
                    "confidence_raw": confidence_raw,
                    "notes": notes,
                }
            )

    return pd.DataFrame(rows, columns=REQUIRED_FETCH_COLUMNS)


def validate_financial_statement_output(df: pd.DataFrame) -> dict[str, Any]:
    """Validate standardized financial statement fetch output."""

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

    dataset_rows = df[df["dataset_name"] == "financial_statement_summary"]
    if not dataset_rows.empty:
        fields = set(dataset_rows["field"])
        missing_fields = [
            field for field in EXPECTED_FINANCIAL_FIELDS if field not in fields
        ]
        if missing_fields:
            result["warnings"].append(
                "financial_statement_summary: missing expected fields: "
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
            result["errors"].append(f"row {index}: missing period")
        if _is_missing(field):
            result["is_valid"] = False
            result["errors"].append(f"row {index}: missing field")
        if _is_missing(row["source"]):
            result["is_valid"] = False
            result["errors"].append(f"row {index}: missing source")
        if _is_missing(row["fetch_time"]):
            result["is_valid"] = False
            result["errors"].append(f"row {index}: missing fetch_time")

        if field == "period" and _is_missing(value):
            result["is_valid"] = False
            result["errors"].append(f"row {index}: missing period value")
        elif field in FINANCIAL_NUMERIC_FIELDS:
            if _is_missing(value):
                result["warnings"].append(
                    f"row {index}: missing numeric field {field}"
                )
            elif not _is_numeric(value):
                result["is_valid"] = False
                result["errors"].append(
                    f"row {index}: {field} must be numeric when provided"
                )

    result["warnings"] = _dedupe(result["warnings"])
    result["errors"] = _dedupe(result["errors"])
    return result


def _fetch_mock(
    tickers: list[str] | None = None, periods: list[str] | None = None
) -> pd.DataFrame:
    requested_tickers = tickers or ["MOCK1", "MOCK2", "MOCK3"]
    requested_periods = periods or ["MOCK2026Q1"]
    normalized_tickers = [_normalize_ticker(ticker) for ticker in requested_tickers]
    if any(not ticker.startswith("MOCK") for ticker in normalized_tickers):
        raise ValueError("Mock mode only supports obvious MOCK tickers.")

    fetch_time = normalize_fetch_time("2026-01-01T00:00:00Z")
    rows = []
    for ticker_index, ticker in enumerate(normalized_tickers, start=1):
        for period_index, period in enumerate(requested_periods, start=1):
            base_value = ticker_index * 1000 + period_index * 100
            rows.append(
                {
                    "ticker": ticker,
                    "period": period,
                    "revenue": base_value,
                    "gross_profit": base_value * 0.3,
                    "operating_profit": base_value * 0.2,
                    "net_profit": base_value * 0.1,
                    "total_assets": base_value * 5,
                    "total_liabilities": base_value * 2,
                    "equity": base_value * 3,
                    "cash": base_value * 0.5,
                    "short_term_debt": base_value * 0.2,
                    "long_term_debt": base_value * 0.4,
                    "operating_cash_flow": base_value * 0.15,
                    "inventory": base_value * 0.25,
                    "source": "MOCK",
                    "fetch_time": fetch_time,
                    "source_url": "",
                    "confidence_raw": "mock",
                    "notes": (
                        "mock financial statement data only; not real or "
                        "production financial data"
                    ),
                }
            )

    return normalize_financials_wide_to_long(pd.DataFrame(rows))


def _fetch_manual_file(
    manual_file_path: str | None,
    file_type: str,
    tickers: list[str] | None = None,
    periods: list[str] | None = None,
) -> pd.DataFrame:
    manual_df = load_manual_financial_file(manual_file_path or "", file_type)

    if tickers is not None and "ticker" in manual_df.columns:
        requested_tickers = {_normalize_ticker(ticker) for ticker in tickers}
        manual_df = manual_df[
            manual_df["ticker"].map(_normalize_ticker).isin(requested_tickers)
        ]

    if periods is not None and "period" in manual_df.columns:
        requested_periods = {str(period) for period in periods}
        manual_df = manual_df[manual_df["period"].map(str).isin(requested_periods)]

    return normalize_financials_wide_to_long(manual_df)


def _fetch_real_unavailable(source_name: str | None = None) -> pd.DataFrame:
    registry = _load_registry_if_available()
    if registry:
        primary_source = get_primary_source(
            registry, "financial_statement_summary"
        )
        fallback_sources = get_fallback_sources(
            registry, "financial_statement_summary"
        )
        available_source_names = [
            source["source_name"]
            for source in [primary_source, *fallback_sources]
            if source and "source_name" in source
        ]
        if source_name and source_name not in available_source_names:
            raise RealSourceUnavailableError(
                f"{REAL_SOURCE_UNAVAILABLE_MESSAGE}; requested source "
                f"'{source_name}' is not configured for financial_statement_summary"
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
    return "manual financial statement file; user-provided and requires validation"


def _normalize_ticker(ticker: Any) -> str:
    if ticker is None or pd.isna(ticker):
        return ""
    return str(ticker).strip().upper()


def _is_missing(value: Any) -> bool:
    if value is None or pd.isna(value):
        return True
    return isinstance(value, str) and not value.strip()


def _is_numeric(value: Any) -> bool:
    numeric_value = pd.to_numeric(value, errors="coerce")
    return not pd.isna(numeric_value)


def _standard_validation_result() -> dict[str, Any]:
    return {
        "dataset_name": "financial_statement_summary",
        "is_valid": True,
        "missing_columns": [],
        "extra_columns": [],
        "warnings": [],
        "errors": [],
    }


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
