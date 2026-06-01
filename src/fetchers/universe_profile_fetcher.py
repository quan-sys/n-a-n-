"""Universe and company profile fetcher interface."""

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
    "REAL_SOURCE_UNAVAILABLE: universe/company_profile fetcher has no available "
    "real source in this environment"
)

DEFAULT_SOURCE_REGISTRY_PATH = Path("config/data_source_registry.yaml")

EXPECTED_FIELDS = {
    "universe": [
        "ticker",
        "exchange",
        "company_name",
        "listing_status",
        "data_source",
        "last_updated",
    ],
    "company_profile": [
        "ticker",
        "company_name",
        "exchange",
        "industry_raw",
        "business_description",
        "source",
        "last_updated",
    ],
}


class RealSourceUnavailableError(RuntimeError):
    """Raised when real universe/profile fetching is requested but unavailable."""


class UniverseProfileFetcher(BaseFetcher):
    """Fetch universe and company profile data in the standard long format."""

    dataset_name = "universe_profile"

    def fetch(
        self,
        dataset_name: str = "universe",
        mode: str = "mock",
        source_name: str | None = None,
        manual_file_path: str | None = None,
        tickers: list[str] | None = None,
    ) -> pd.DataFrame:
        """Dispatch to the dataset-specific fetch method."""

        if dataset_name == "universe":
            return self.fetch_universe(
                mode=mode,
                source_name=source_name,
                manual_file_path=manual_file_path,
            )
        if dataset_name == "company_profile":
            return self.fetch_company_profile(
                tickers=tickers,
                mode=mode,
                source_name=source_name,
                manual_file_path=manual_file_path,
            )
        raise ValueError("dataset_name must be 'universe' or 'company_profile'.")

    def fetch_universe(
        self,
        mode: str = "mock",
        source_name: str | None = None,
        manual_file_path: str | None = None,
    ) -> pd.DataFrame:
        """Fetch or normalize universe data."""

        if mode == "mock":
            return _mock_universe()
        if mode == "manual_csv":
            return _fetch_manual_csv("universe", manual_file_path)
        if mode == "real":
            return _fetch_real_unavailable("universe", source_name)
        raise ValueError("Invalid mode. Expected 'mock', 'manual_csv', or 'real'.")

    def fetch_company_profile(
        self,
        tickers: list[str] | None = None,
        mode: str = "mock",
        source_name: str | None = None,
        manual_file_path: str | None = None,
    ) -> pd.DataFrame:
        """Fetch or normalize company profile data."""

        if mode == "mock":
            return _mock_company_profile(tickers)
        if mode == "manual_csv":
            return _fetch_manual_csv("company_profile", manual_file_path, tickers)
        if mode == "real":
            return _fetch_real_unavailable("company_profile", source_name)
        raise ValueError("Invalid mode. Expected 'mock', 'manual_csv', or 'real'.")

    def validate_output(self, df: pd.DataFrame) -> dict[str, Any]:
        """Validate standardized universe/profile output."""

        return validate_universe_profile_output(df)


def load_manual_csv(path: str) -> pd.DataFrame:
    """Load a manually provided CSV file."""

    if not path:
        raise ValueError("manual_file_path is required for manual_csv mode.")
    return pd.read_csv(path)


def normalize_wide_to_long_fetch_format(
    df: pd.DataFrame,
    dataset_name: str,
    source_label: str = "MANUAL_CSV_UNKNOWN_SOURCE",
    notes: str = "manual CSV data; user-provided and requires validation",
) -> pd.DataFrame:
    """Normalize wide universe/profile data into standardized long format."""

    if dataset_name not in EXPECTED_FIELDS:
        raise ValueError("dataset_name must be 'universe' or 'company_profile'.")
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame.")

    expected_fields = EXPECTED_FIELDS[dataset_name]
    present_fields = [field for field in expected_fields if field in df.columns]
    if not present_fields:
        present_fields = ["ticker"] if "ticker" in df.columns else []

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        row_source = _row_source(row, source_label)
        row_date = _row_date(row)
        row_fetch_time = _row_fetch_time(row)
        confidence_raw = _row_confidence(row)
        row_notes = _row_notes(row, notes)

        for field in present_fields:
            rows.append(
                {
                    "dataset_name": dataset_name,
                    "ticker": row.get("ticker", ""),
                    "date": row_date,
                    "field": field,
                    "value": row.get(field, ""),
                    "source": row_source,
                    "source_url": row.get("source_url", ""),
                    "fetch_time": row_fetch_time,
                    "confidence_raw": confidence_raw,
                    "notes": row_notes,
                }
            )

    return pd.DataFrame(rows, columns=REQUIRED_FETCH_COLUMNS)


def validate_universe_profile_output(df: pd.DataFrame) -> dict[str, Any]:
    """Validate standardized universe/profile fetch output."""

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

    for dataset_name, expected_fields in EXPECTED_FIELDS.items():
        dataset_rows = df[df["dataset_name"] == dataset_name]
        if dataset_rows.empty:
            continue

        fields = set(dataset_rows["field"])
        missing_fields = [
            field for field in expected_fields if field not in fields
        ]
        if missing_fields:
            result["warnings"].append(
                f"{dataset_name}: missing expected fields: "
                + ", ".join(missing_fields)
            )

    for index, row in df.iterrows():
        if _is_missing(row["ticker"]):
            result["is_valid"] = False
            result["errors"].append(f"row {index}: missing ticker")
        if _is_missing(row["field"]):
            result["is_valid"] = False
            result["errors"].append(f"row {index}: missing field")
        if _is_missing(row["source"]):
            result["is_valid"] = False
            result["errors"].append(f"row {index}: missing source")
        if _is_missing(row["fetch_time"]):
            result["is_valid"] = False
            result["errors"].append(f"row {index}: missing fetch_time")

        if row["field"] in {"exchange", "company_name"} and _is_missing(
            row["value"]
        ):
            result["warnings"].append(
                f"row {index}: missing value for {row['field']}"
            )

    result["warnings"] = _dedupe(result["warnings"])
    result["errors"] = _dedupe(result["errors"])
    return result


def _mock_universe() -> pd.DataFrame:
    fetch_time = normalize_fetch_time("2026-01-01T00:00:00Z")
    wide = pd.DataFrame(
        [
            {
                "ticker": "MOCK1",
                "exchange": "MOCK_EXCHANGE",
                "company_name": "Mock Company One",
                "listing_status": "MOCK_LISTED",
                "data_source": "MOCK",
                "last_updated": "2026-01-01",
                "source": "MOCK",
                "source_url": "",
                "fetch_time": fetch_time,
                "confidence_raw": "mock",
                "notes": "mock data only; not real or production universe data",
            },
            {
                "ticker": "MOCK2",
                "exchange": "MOCK_EXCHANGE",
                "company_name": "Mock Company Two",
                "listing_status": "MOCK_LISTED",
                "data_source": "MOCK",
                "last_updated": "2026-01-01",
                "source": "MOCK",
                "source_url": "",
                "fetch_time": fetch_time,
                "confidence_raw": "mock",
                "notes": "mock data only; not real or production universe data",
            },
        ]
    )
    return normalize_wide_to_long_fetch_format(
        wide,
        dataset_name="universe",
        source_label="MOCK",
        notes="mock data only; not real or production universe data",
    )


def _mock_company_profile(tickers: list[str] | None) -> pd.DataFrame:
    requested_tickers = tickers or ["MOCK1", "MOCK2", "MOCK3"]
    normalized_tickers = [_normalize_ticker(ticker) for ticker in requested_tickers]
    if any(not ticker.startswith("MOCK") for ticker in normalized_tickers):
        raise ValueError("Mock mode only supports obvious MOCK tickers.")

    fetch_time = normalize_fetch_time("2026-01-01T00:00:00Z")
    rows = []
    for ticker in normalized_tickers:
        rows.append(
            {
                "ticker": ticker,
                "company_name": f"{ticker} Company",
                "exchange": "MOCK_EXCHANGE",
                "industry_raw": "MOCK_INDUSTRY",
                "business_description": "Mock profile only; not real company data",
                "source": "MOCK",
                "last_updated": "2026-01-01",
                "source_url": "",
                "fetch_time": fetch_time,
                "confidence_raw": "mock",
                "notes": "mock data only; not real or production company profile data",
            }
        )

    return normalize_wide_to_long_fetch_format(
        pd.DataFrame(rows),
        dataset_name="company_profile",
        source_label="MOCK",
        notes="mock data only; not real or production company profile data",
    )


def _fetch_manual_csv(
    dataset_name: str,
    manual_file_path: str | None,
    tickers: list[str] | None = None,
) -> pd.DataFrame:
    manual_df = load_manual_csv(manual_file_path or "")
    if tickers is not None and "ticker" in manual_df.columns:
        requested_tickers = {_normalize_ticker(ticker) for ticker in tickers}
        manual_df = manual_df[
            manual_df["ticker"].map(_normalize_ticker).isin(requested_tickers)
        ]

    return normalize_wide_to_long_fetch_format(manual_df, dataset_name=dataset_name)


def _fetch_real_unavailable(
    dataset_name: str, source_name: str | None = None
) -> pd.DataFrame:
    registry = _load_registry_if_available()
    if registry:
        primary_source = get_primary_source(registry, dataset_name)
        fallback_sources = get_fallback_sources(registry, dataset_name)
        available_source_names = [
            source["source_name"]
            for source in [primary_source, *fallback_sources]
            if source and "source_name" in source
        ]
        if source_name and source_name not in available_source_names:
            raise RealSourceUnavailableError(
                f"{REAL_SOURCE_UNAVAILABLE_MESSAGE}; requested source "
                f"'{source_name}' is not configured for {dataset_name}"
            )

    raise RealSourceUnavailableError(REAL_SOURCE_UNAVAILABLE_MESSAGE)


def _load_registry_if_available() -> dict[str, Any] | None:
    if not DEFAULT_SOURCE_REGISTRY_PATH.exists():
        return None
    return load_source_registry(str(DEFAULT_SOURCE_REGISTRY_PATH))


def _row_source(row: pd.Series, default_source: str) -> str:
    for source_field in ["source", "data_source"]:
        if source_field in row.index and not _is_missing(row[source_field]):
            return str(row[source_field])
    return default_source


def _row_date(row: pd.Series) -> Any:
    for date_field in ["last_updated", "date", "fetch_time"]:
        if date_field in row.index and not _is_missing(row[date_field]):
            return row[date_field]
    return ""


def _row_fetch_time(row: pd.Series) -> str:
    if "fetch_time" in row.index and not _is_missing(row["fetch_time"]):
        return str(row["fetch_time"])
    return normalize_fetch_time()


def _row_confidence(row: pd.Series) -> str:
    for confidence_field in ["confidence_raw", "confidence"]:
        if confidence_field in row.index and not _is_missing(row[confidence_field]):
            return str(row[confidence_field])
    return "medium"


def _row_notes(row: pd.Series, default_notes: str) -> str:
    if "notes" in row.index and not _is_missing(row["notes"]):
        return str(row["notes"])
    return default_notes


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
        "dataset_name": "universe_profile",
        "is_valid": True,
        "missing_columns": [],
        "extra_columns": [],
        "warnings": [],
        "errors": [],
    }


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
