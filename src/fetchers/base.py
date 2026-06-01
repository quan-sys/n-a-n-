"""Base interface for standardized data fetchers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import pandas as pd


REQUIRED_FETCH_COLUMNS = [
    "dataset_name",
    "ticker",
    "date",
    "field",
    "value",
    "source",
    "source_url",
    "fetch_time",
    "confidence_raw",
    "notes",
]


class BaseFetcher(ABC):
    """Abstract base class for future data fetchers."""

    dataset_name: str

    @abstractmethod
    def fetch(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        """Return fetched data in the standardized long-form format."""

    def validate_output(self, df: pd.DataFrame) -> dict[str, Any]:
        """Validate fetcher output without raising on missing columns."""

        result: dict[str, Any] = {
            "dataset_name": getattr(self, "dataset_name", None),
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
        missing_columns = [
            column for column in REQUIRED_FETCH_COLUMNS if column not in actual_columns
        ]
        extra_columns = [
            column for column in actual_columns if column not in REQUIRED_FETCH_COLUMNS
        ]

        result["missing_columns"] = missing_columns
        result["extra_columns"] = extra_columns

        if missing_columns:
            result["is_valid"] = False
            result["warnings"].append(
                "Missing required fetch columns: " + ", ".join(missing_columns)
            )

        return result


def normalize_fetch_time(fetch_time: datetime | str | None = None) -> str:
    """Return an ISO-like fetch timestamp for standardized fetcher rows."""

    if fetch_time is None:
        return datetime.now(timezone.utc).isoformat()

    if isinstance(fetch_time, datetime):
        if fetch_time.tzinfo is None:
            fetch_time = fetch_time.replace(tzinfo=timezone.utc)
        return fetch_time.isoformat()

    return str(fetch_time)
