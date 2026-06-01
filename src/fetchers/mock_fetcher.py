"""Mock-only fetcher implementations for interface tests and fixtures."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.fetchers.base import BaseFetcher, REQUIRED_FETCH_COLUMNS


SUPPORTED_MOCK_DATASETS = {
    "universe",
    "market_price",
    "company_profile",
    "financial_statement_summary",
    "disclosure_status",
}

MOCK_FETCH_TIME = "2026-01-01T00:00:00Z"


class MockFetcher(BaseFetcher):
    """Return clearly labeled mock data in the standardized fetcher format."""

    def __init__(self, dataset_name: str) -> None:
        if dataset_name not in SUPPORTED_MOCK_DATASETS:
            supported = ", ".join(sorted(SUPPORTED_MOCK_DATASETS))
            raise ValueError(
                f"Unsupported mock dataset '{dataset_name}'. "
                f"Supported datasets: {supported}."
            )
        self.dataset_name = dataset_name

    def fetch(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        rows = _mock_rows_for_dataset(self.dataset_name)
        return pd.DataFrame(rows, columns=REQUIRED_FETCH_COLUMNS)


def _base_row(ticker: str, date: str | None, field: str, value: Any) -> dict[str, Any]:
    return {
        "dataset_name": None,
        "ticker": ticker,
        "date": date,
        "field": field,
        "value": value,
        "source": "MOCK",
        "source_url": "",
        "fetch_time": MOCK_FETCH_TIME,
        "confidence_raw": "mock",
        "notes": "mock data only; not real Vietnamese stock data",
    }


def _mock_rows_for_dataset(dataset_name: str) -> list[dict[str, Any]]:
    if dataset_name == "universe":
        rows = [
            _base_row("MOCK1", None, "listing_status", "MOCK_LISTED"),
            _base_row("MOCK2", None, "listing_status", "MOCK_LISTED"),
        ]
    elif dataset_name == "market_price":
        rows = [
            _base_row("MOCK1", "2026-01-01", "close", 1000),
            _base_row("MOCK1", "2026-01-01", "volume", 100),
        ]
    elif dataset_name == "company_profile":
        rows = [
            _base_row(
                "MOCK1",
                None,
                "business_description",
                "Mock company profile for interface tests",
            ),
            _base_row("MOCK1", None, "industry_raw", "MOCK_INDUSTRY"),
        ]
    elif dataset_name == "financial_statement_summary":
        rows = [
            _base_row("MOCK1", "2026Q1", "revenue", 1000),
            _base_row("MOCK1", "2026Q1", "net_profit", 100),
        ]
    elif dataset_name == "disclosure_status":
        rows = [
            _base_row("MOCK1", "2026-01-01", "event_type", "MOCK_DISCLOSURE"),
            _base_row("MOCK1", "2026-01-01", "severity", "mock_low"),
        ]
    else:
        raise ValueError(f"Unsupported mock dataset '{dataset_name}'.")

    for row in rows:
        row["dataset_name"] = dataset_name

    return rows
