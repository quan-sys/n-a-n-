"""Vnstock package-backed adapter for REAL-DATA-01G."""

from __future__ import annotations

import importlib.util
import time
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from src.ingestion.finance_statement_mapper import map_financial_statement_summary
from src.ingestion.source_adapter_contracts import (
    DISCLOSURE_CANDIDATE_COLUMNS,
    FINANCE_CANDIDATE_COLUMNS,
    FINANCE_CANONICAL_FIELDS,
    SOURCE_PROBE_COLUMNS,
    classify_disclosure_event,
    empty_disclosure_candidates,
    empty_finance_candidates,
)
from src.ingestion.source_adapters.base import SourceAdapter


class VnstockAdapter(SourceAdapter):
    source_name = "vnstock"
    source_category = "vnstock"
    supported_datasets = ["financial_statement_summary", "disclosure_status"]

    def probe(self, datasets: list[str] | None = None) -> pd.DataFrame:
        has_vnstock = importlib.util.find_spec("vnstock") is not None
        rows = []
        for dataset_name in datasets or self.supported_datasets:
            supported_fields = (
                FINANCE_CANONICAL_FIELDS
                if dataset_name == "financial_statement_summary"
                else ["event_date", "event_type", "severity", "title", "description"]
            )
            rows.append(
                {
                    "source_name": self.source_name,
                    "source_category": self.source_category,
                    "dataset_name": dataset_name,
                    "probe_status": "SOURCE_AVAILABLE" if has_vnstock else "DEPENDENCY_UNAVAILABLE",
                    "http_status_or_error": "" if has_vnstock else "vnstock dependency unavailable",
                    "is_accessible": bool(has_vnstock),
                    "requires_js": False,
                    "requires_login": False,
                    "blocked_or_captcha": False,
                    "schema_detected": bool(has_vnstock),
                    "supported_fields": "|".join(supported_fields),
                    "unsupported_fields": "missing fields remain blank until source provides them",
                    "sample_url": "https://vnstocks.com/",
                    "notes": "python package dependency available" if has_vnstock else "install vnstock before live package fetch",
                }
            )
        return pd.DataFrame(rows, columns=SOURCE_PROBE_COLUMNS)

    def fetch_finance(
        self,
        tickers: list[str],
        periods: list[str] | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        if importlib.util.find_spec("vnstock") is None:
            return (
                empty_finance_candidates(),
                self._diagnostics_frame(
                    [
                        self._diagnostic_row(
                            dataset_name="financial_statement_summary",
                            action="fetch_finance",
                            status="DEPENDENCY_UNAVAILABLE",
                            notes="vnstock package is not installed",
                        )
                    ]
                ),
                self._schema_frame([]),
            )

        from vnstock import Finance  # type: ignore

        candidate_rows: list[dict[str, Any]] = []
        diagnostics = []
        schema_rows = []
        for ticker in _ordered_tickers(tickers):
            fetch_time = _utc_now_iso()
            try:
                finance = Finance(source="VCI", symbol=ticker, period="quarter", get_all=True)
                statements = {
                    "income": _safe_statement(finance, "income_statement"),
                    "balance": _safe_statement(finance, "balance_sheet"),
                    "cash_flow": _safe_statement(finance, "cash_flow"),
                }
                record, warnings, missing_fields, not_applicable = map_financial_statement_summary(
                    ticker=ticker,
                    statements=statements,
                    fetch_time=fetch_time,
                    source="vnstock:vci:finance",
                    source_url="https://vnstocks.com/",
                    period_type="quarter",
                )
                if record is None:
                    status = warnings[0] if warnings else "SOURCE_EMPTY_RESPONSE"
                    diagnostics.append(
                        self._diagnostic_row(
                            dataset_name="financial_statement_summary",
                            action="fetch_finance",
                            ticker=ticker,
                            status=_normalize_fetch_status(status),
                            source_url="https://vnstocks.com/",
                            notes=";".join(warnings),
                        )
                    )
                    schema_rows.append(
                        self._schema_row(
                            dataset_name="financial_statement_summary",
                            ticker=ticker,
                            source_url="https://vnstocks.com/",
                            schema_status=_normalize_fetch_status(status),
                            unsupported_fields=FINANCE_CANONICAL_FIELDS,
                            notes="vnstock returned no mappable financial schema",
                        )
                    )
                else:
                    rows = _wide_finance_record_to_candidates(record)
                    candidate_rows.extend(rows)
                    diagnostics.append(
                        self._diagnostic_row(
                            dataset_name="financial_statement_summary",
                            action="fetch_finance",
                            ticker=ticker,
                            status="ROWS_PARSED",
                            row_count=len(rows),
                            source_url="https://vnstocks.com/",
                            notes=";".join(warnings) or "source rows parsed",
                        )
                    )
                    schema_rows.append(
                        self._schema_row(
                            dataset_name="financial_statement_summary",
                            ticker=ticker,
                            source_url="https://vnstocks.com/",
                            schema_status="SCHEMA_DETECTED",
                            detected_fields=[field for field in FINANCE_CANONICAL_FIELDS if field not in missing_fields],
                            unsupported_fields=missing_fields,
                            raw_labels=[],
                            notes="not_applicable_fields=" + ",".join(not_applicable),
                        )
                    )
            except Exception as exc:  # noqa: BLE001 - adapter must report and continue.
                diagnostics.append(
                    self._diagnostic_row(
                        dataset_name="financial_statement_summary",
                        action="fetch_finance",
                        ticker=ticker,
                        status=_status_from_exception(exc),
                        http_status_or_error=f"{type(exc).__name__}:{exc}",
                        source_url="https://vnstocks.com/",
                        notes="vnstock finance fetch failed",
                    )
                )
                schema_rows.append(
                    self._schema_row(
                        dataset_name="financial_statement_summary",
                        ticker=ticker,
                        source_url="https://vnstocks.com/",
                        schema_status=_status_from_exception(exc),
                        unsupported_fields=FINANCE_CANONICAL_FIELDS,
                        notes=str(exc),
                    )
                )
            self._sleep()

        return (
            pd.DataFrame(candidate_rows, columns=FINANCE_CANDIDATE_COLUMNS),
            self._diagnostics_frame(diagnostics),
            self._schema_frame(schema_rows),
        )

    def fetch_disclosure(
        self,
        tickers: list[str],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        if importlib.util.find_spec("vnstock") is None:
            return (
                empty_disclosure_candidates(),
                self._diagnostics_frame(
                    [
                        self._diagnostic_row(
                            dataset_name="disclosure_status",
                            action="fetch_disclosure",
                            status="DEPENDENCY_UNAVAILABLE",
                            notes="vnstock package is not installed",
                        )
                    ]
                ),
                self._schema_frame([]),
            )

        from vnstock import Company  # type: ignore

        candidate_rows: list[dict[str, Any]] = []
        diagnostics = []
        schema_rows = []
        for ticker in _ordered_tickers(tickers):
            try:
                company = Company(source="KBS", symbol=ticker)
                events = company.events()
                parsed = _events_to_disclosure_candidates(
                    events,
                    ticker=ticker,
                    fetch_time=_utc_now_iso(),
                )
                candidate_rows.extend(parsed)
                diagnostics.append(
                    self._diagnostic_row(
                        dataset_name="disclosure_status",
                        action="fetch_disclosure",
                        ticker=ticker,
                        status="ROWS_PARSED" if parsed else "SOURCE_EMPTY_RESPONSE",
                        row_count=len(parsed),
                        source_url="https://vnstocks.com/",
                        notes=(
                            "vnstock event rows matched regulatory warning patterns"
                            if parsed
                            else "vnstock returned no disclosure warning rows; not treated as clean"
                        ),
                    )
                )
                schema_rows.append(
                    self._schema_row(
                        dataset_name="disclosure_status",
                        ticker=ticker,
                        source_url="https://vnstocks.com/",
                        schema_status="SCHEMA_DETECTED" if parsed else "SOURCE_EMPTY_RESPONSE",
                        detected_fields=["event_type", "severity"] if parsed else [],
                        notes="no row is unavailable, not clean" if not parsed else "regulatory warning rows parsed",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                diagnostics.append(
                    self._diagnostic_row(
                        dataset_name="disclosure_status",
                        action="fetch_disclosure",
                        ticker=ticker,
                        status=_status_from_exception(exc),
                        http_status_or_error=f"{type(exc).__name__}:{exc}",
                        source_url="https://vnstocks.com/",
                        notes="vnstock disclosure fetch failed",
                    )
                )
                schema_rows.append(
                    self._schema_row(
                        dataset_name="disclosure_status",
                        ticker=ticker,
                        source_url="https://vnstocks.com/",
                        schema_status=_status_from_exception(exc),
                        notes=str(exc),
                    )
                )
            self._sleep()

        return (
            pd.DataFrame(candidate_rows, columns=DISCLOSURE_CANDIDATE_COLUMNS),
            self._diagnostics_frame(diagnostics),
            self._schema_frame(schema_rows),
        )


def _safe_statement(finance: Any, method_name: str) -> pd.DataFrame:
    try:
        value = getattr(finance, method_name)()
    except Exception:
        return pd.DataFrame()
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _wide_finance_record_to_candidates(record: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for field_name in FINANCE_CANONICAL_FIELDS:
        value = record.get(field_name)
        if _is_missing(value):
            continue
        rows.append(
            {
                "ticker": record.get("ticker", ""),
                "period": record.get("period", ""),
                "period_type": record.get("period_type", ""),
                "field_name": field_name,
                "value": value,
                "unit": "",
                "currency": "VND",
                "source_category": "vnstock",
                "source_name": record.get("source", "vnstock:vci:finance"),
                "source_url": record.get("source_url", "https://vnstocks.com/"),
                "fetch_time": record.get("fetch_time", ""),
                "confidence_raw": record.get("confidence_raw", "low"),
                "raw_label": field_name,
                "raw_value": value,
                "notes": record.get("notes", ""),
            }
        )
    return rows


def _events_to_disclosure_candidates(
    events: pd.DataFrame,
    *,
    ticker: str,
    fetch_time: str,
) -> list[dict[str, Any]]:
    if not isinstance(events, pd.DataFrame) or events.empty:
        return []
    rows = []
    for _, row in events.iterrows():
        raw_text = " ".join(str(value) for value in row.to_dict().values() if not _is_missing(value))
        event_type, severity = classify_disclosure_event(raw_text)
        if event_type in {"DISCLOSURE_DATA_UNAVAILABLE", "NO_MATERIAL_DISCLOSURE_FOUND_SOURCE_CHECKED"}:
            continue
        rows.append(
            {
                "ticker": ticker,
                "event_date": _first_existing(row, ["event_date", "date", "time", "created_at"]),
                "event_type": event_type,
                "severity": severity,
                "title": _first_existing(row, ["title", "event_title", "name"]) or raw_text[:180],
                "description": raw_text[:1000],
                "source_category": "vnstock",
                "source_name": "vnstock:kbs:events",
                "source_url": "https://vnstocks.com/",
                "fetch_time": fetch_time,
                "confidence_raw": "low",
                "raw_event_type": _first_existing(row, ["event_type", "type"]),
                "raw_text": raw_text[:2000],
                "notes": "vnstock company event matched regulatory warning pattern; manual review required",
            }
        )
    return rows


def _first_existing(row: pd.Series, columns: list[str]) -> str:
    for column in columns:
        if column in row.index and not _is_missing(row.get(column)):
            return str(row.get(column)).strip()
    return ""


def _normalize_fetch_status(status: str) -> str:
    status_upper = str(status).upper()
    if "EMPTY" in status_upper:
        return "SOURCE_EMPTY_RESPONSE"
    if "SCHEMA" in status_upper or "UNMAPPED" in status_upper:
        return "SOURCE_SCHEMA_UNKNOWN"
    return status_upper if status_upper.startswith("SOURCE_") else "SOURCE_PARSE_FAILED"


def _status_from_exception(exc: Exception) -> str:
    text = f"{type(exc).__name__}:{exc}".lower()
    if "rate" in text or "429" in text:
        return "SOURCE_RATE_LIMITED"
    if "captcha" in text or "forbidden" in text or "blocked" in text or "403" in text:
        return "SOURCE_BLOCKED_OR_JS_REQUIRED"
    if "schema" in text:
        return "SOURCE_SCHEMA_UNKNOWN"
    if "empty" in text:
        return "SOURCE_EMPTY_RESPONSE"
    return "SOURCE_PARSE_FAILED"


def _ordered_tickers(tickers: list[str]) -> list[str]:
    result: list[str] = []
    for ticker in tickers:
        clean = str(ticker).strip().upper()
        if clean and clean not in result:
            result.append(clean)
    return result


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        return False
    return isinstance(value, str) and not value.strip()


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
