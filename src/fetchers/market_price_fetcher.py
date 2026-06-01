"""Market price and liquidity fetcher interface."""

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
    "REAL_SOURCE_UNAVAILABLE: market_price fetcher has no available real source "
    "in this environment"
)

DEFAULT_SOURCE_REGISTRY_PATH = Path("config/data_source_registry.yaml")
MARKET_PRICE_FIELDS = ["close", "volume", "trading_value"]


class RealSourceUnavailableError(RuntimeError):
    """Raised when real market data fetching is requested but unavailable."""


class MarketPriceFetcher(BaseFetcher):
    """Fetch market price data in the standardized long-form format."""

    dataset_name = "market_price"

    def fetch(
        self,
        tickers: list[str],
        start_date: str | None = None,
        end_date: str | None = None,
        mode: str = "mock",
        source_name: str | None = None,
    ) -> pd.DataFrame:
        """Fetch market price data.

        Mock mode returns deterministic interface-test rows only. Real mode is
        intentionally unavailable until an approved real source connector exists.
        """

        if mode == "mock":
            return self._fetch_mock(tickers, start_date=start_date, end_date=end_date)
        if mode == "real":
            return self._fetch_real_unavailable(source_name=source_name)

        raise ValueError("Invalid mode. Expected 'mock' or 'real'.")

    def validate_output(self, df: pd.DataFrame) -> dict[str, Any]:
        """Validate standardized columns and market-price field values."""

        return validate_market_price_output(df)

    def _fetch_mock(
        self,
        tickers: list[str],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        if not tickers:
            raise ValueError("tickers must contain at least one ticker.")

        normalized_tickers = [_normalize_ticker(ticker) for ticker in tickers]
        non_mock_tickers = [
            ticker for ticker in normalized_tickers if not ticker.startswith("MOCK")
        ]
        if non_mock_tickers:
            raise ValueError("Mock mode only supports obvious MOCK tickers.")

        observation_date = start_date or end_date or "2026-01-01"
        fetch_time = normalize_fetch_time("2026-01-01T00:00:00Z")
        wide_rows: list[dict[str, Any]] = []
        for index, ticker in enumerate(normalized_tickers, start=1):
            close = 1000 + index * 10
            volume = index * 100
            wide_rows.append(
                {
                    "ticker": ticker,
                    "date": observation_date,
                    "close": close,
                    "volume": volume,
                    "trading_value": close * volume,
                    "source": "MOCK",
                    "source_url": "",
                    "fetch_time": fetch_time,
                    "confidence_raw": "mock",
                    "notes": "mock data only; not real or production market data",
                }
            )

        return normalize_market_price_to_long_format(pd.DataFrame(wide_rows))

    def _fetch_real_unavailable(self, source_name: str | None = None) -> pd.DataFrame:
        registry = _load_registry_if_available()
        if registry:
            primary_source = get_primary_source(registry, self.dataset_name)
            fallback_sources = get_fallback_sources(registry, self.dataset_name)
            available_source_names = [
                source["source_name"]
                for source in [primary_source, *fallback_sources]
                if source and "source_name" in source
            ]
            if source_name and source_name not in available_source_names:
                raise RealSourceUnavailableError(
                    f"{REAL_SOURCE_UNAVAILABLE_MESSAGE}; requested source "
                    f"'{source_name}' is not configured for market_price"
                )

        raise RealSourceUnavailableError(REAL_SOURCE_UNAVAILABLE_MESSAGE)


def normalize_market_price_to_long_format(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize wide market price rows into the standard fetcher long format."""

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        for field in MARKET_PRICE_FIELDS:
            if field not in df.columns:
                continue
            rows.append(
                {
                    "dataset_name": "market_price",
                    "ticker": row.get("ticker"),
                    "date": row.get("date"),
                    "field": field,
                    "value": row.get(field),
                    "source": row.get("source", ""),
                    "source_url": row.get("source_url", ""),
                    "fetch_time": row.get("fetch_time", ""),
                    "confidence_raw": row.get("confidence_raw", ""),
                    "notes": row.get("notes", ""),
                }
            )

    return pd.DataFrame(rows, columns=REQUIRED_FETCH_COLUMNS)


def validate_market_price_output(df: pd.DataFrame) -> dict[str, Any]:
    """Validate standardized market price fetch output."""

    base_result = _validate_required_columns(df)
    if not base_result["is_valid"]:
        return base_result

    for index, row in df.iterrows():
        ticker = row["ticker"]
        date = row["date"]
        field = row["field"]
        value = row["value"]

        if _is_missing(ticker):
            base_result["is_valid"] = False
            base_result["errors"].append(f"row {index}: missing ticker")
        if _is_missing(date):
            base_result["is_valid"] = False
            base_result["errors"].append(f"row {index}: missing date")

        if field == "close" and not _is_positive_number(value):
            base_result["is_valid"] = False
            base_result["errors"].append(f"row {index}: close must be positive")
        elif field in {"volume", "trading_value"} and not _is_non_negative_number(
            value
        ):
            base_result["is_valid"] = False
            base_result["errors"].append(
                f"row {index}: {field} must be greater than or equal to 0"
            )

    base_result["errors"] = _dedupe(base_result["errors"])
    return base_result


def _validate_required_columns(df: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {
        "dataset_name": "market_price",
        "is_valid": True,
        "missing_columns": [],
        "extra_columns": [],
        "warnings": [],
        "errors": [],
    }

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


def _load_registry_if_available() -> dict[str, Any] | None:
    if not DEFAULT_SOURCE_REGISTRY_PATH.exists():
        return None
    return load_source_registry(str(DEFAULT_SOURCE_REGISTRY_PATH))


def _normalize_ticker(ticker: Any) -> str:
    if ticker is None or pd.isna(ticker):
        return ""
    return str(ticker).strip().upper()


def _is_missing(value: Any) -> bool:
    if value is None or pd.isna(value):
        return True
    return isinstance(value, str) and not value.strip()


def _is_positive_number(value: Any) -> bool:
    numeric_value = pd.to_numeric(value, errors="coerce")
    return not pd.isna(numeric_value) and numeric_value > 0


def _is_non_negative_number(value: Any) -> bool:
    numeric_value = pd.to_numeric(value, errors="coerce")
    return not pd.isna(numeric_value) and numeric_value >= 0


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
