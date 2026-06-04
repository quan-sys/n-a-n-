"""Source request accounting and graceful rate-limit handling."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any, Callable

import pandas as pd


SOURCE_REQUEST_SUMMARY_COLUMNS = [
    "source_name",
    "dataset_name",
    "requests_attempted",
    "requests_succeeded",
    "requests_failed",
    "requests_skipped_due_to_budget",
    "rate_limit_errors",
    "dependency_errors",
    "notes",
]

RATE_LIMIT_MARKERS = (
    "rate limit",
    "rate_limit",
    "too many requests",
    "giới hạn api",
    "limit exceeded",
)
DEPENDENCY_MARKERS = (
    "importerror",
    "modulenotfounderror",
    "no module named",
    "no charting library",
    "dependency",
)


class SourceRequestTracker:
    """Track source calls without letting one failed call crash the batch."""

    def __init__(self, max_requests: int | None) -> None:
        self.max_requests = None if max_requests is None else max(0, int(max_requests))
        self.remaining = self.max_requests
        self._records: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()

    def request(
        self,
        *,
        source_name: str,
        dataset_name: str,
        action: Callable[[], Any],
        pause_seconds: float = 0.0,
    ) -> tuple[Any, str]:
        """Execute one request and return (result, error_text)."""

        record = self._record(source_name, dataset_name)
        if self.remaining is not None and self.remaining <= 0:
            record["requests_skipped_due_to_budget"] += 1
            self._add_note(record, "REAL_SOURCE_REQUEST_BUDGET_EXHAUSTED")
            return None, "REAL_SOURCE_REQUEST_BUDGET_EXHAUSTED"

        if self.remaining is not None:
            self.remaining -= 1
        record["requests_attempted"] += 1

        try:
            result = action()
        except BaseException as exc:  # noqa: BLE001 - third-party libraries may call sys.exit.
            if isinstance(exc, KeyboardInterrupt):
                raise
            error_text = external_error_text(exc)
            record["requests_failed"] += 1
            if is_rate_limit_error(error_text):
                record["rate_limit_errors"] += 1
            if is_dependency_error(error_text):
                record["dependency_errors"] += 1
            self._add_note(record, error_text)
            return None, error_text
        finally:
            if pause_seconds and pause_seconds > 0:
                time.sleep(float(pause_seconds))

        record["requests_succeeded"] += 1
        return result, ""

    def record_dependency_error(
        self, *, source_name: str, dataset_name: str, error_text: str
    ) -> None:
        record = self._record(source_name, dataset_name)
        record["requests_failed"] += 1
        record["dependency_errors"] += 1
        self._add_note(record, error_text)

    def to_frame(self) -> pd.DataFrame:
        rows = []
        for record in self._records.values():
            row = dict(record)
            row["notes"] = "; ".join(row["notes"])
            rows.append(row)
        return pd.DataFrame(rows, columns=SOURCE_REQUEST_SUMMARY_COLUMNS)

    def _record(self, source_name: str, dataset_name: str) -> dict[str, Any]:
        key = (source_name, dataset_name)
        if key not in self._records:
            self._records[key] = {
                "source_name": source_name,
                "dataset_name": dataset_name,
                "requests_attempted": 0,
                "requests_succeeded": 0,
                "requests_failed": 0,
                "requests_skipped_due_to_budget": 0,
                "rate_limit_errors": 0,
                "dependency_errors": 0,
                "notes": [],
            }
        return self._records[key]

    @staticmethod
    def _add_note(record: dict[str, Any], note: str) -> None:
        if note and note not in record["notes"]:
            record["notes"].append(note)


def empty_source_request_summary() -> pd.DataFrame:
    return pd.DataFrame(columns=SOURCE_REQUEST_SUMMARY_COLUMNS)


def external_error_text(exc: BaseException) -> str:
    message = str(exc).strip()
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def is_rate_limit_error(value: Any) -> bool:
    text = str(value).strip().lower()
    return any(marker in text for marker in RATE_LIMIT_MARKERS)


def is_dependency_error(value: Any) -> bool:
    text = str(value).strip().lower()
    return any(marker in text for marker in DEPENDENCY_MARKERS)
