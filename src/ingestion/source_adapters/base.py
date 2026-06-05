"""Base source adapter classes for REAL-DATA-01G."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from io import StringIO
from typing import Any

import pandas as pd

from src.ingestion.source_adapter_contracts import (
    DISCLOSURE_CANDIDATE_COLUMNS,
    FINANCE_CANDIDATE_COLUMNS,
    FINANCE_CANONICAL_FIELDS,
    SOURCE_ADAPTER_DIAGNOSTIC_COLUMNS,
    SOURCE_SCHEMA_DIAGNOSTIC_COLUMNS,
    classify_disclosure_event,
    detect_finance_field,
    empty_disclosure_candidates,
    empty_finance_candidates,
)
from src.ingestion.source_probe import probe_public_url, safe_http_get


class SourceAdapter:
    """Stable source adapter interface."""

    source_name = ""
    source_category = ""
    supported_datasets: list[str] = []

    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        http_get: Any = safe_http_get,
        request_sleep_seconds: float = 0,
    ) -> None:
        self.config = config or {}
        self.http_get = http_get
        self.request_sleep_seconds = float(request_sleep_seconds or 0)

    def probe(self, datasets: list[str] | None = None) -> pd.DataFrame:
        raise NotImplementedError

    def fetch_finance(
        self,
        tickers: list[str],
        periods: list[str] | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        return (
            empty_finance_candidates(),
            self._diagnostics_frame(
                [
                    self._diagnostic_row(
                        dataset_name="financial_statement_summary",
                        action="fetch_finance",
                        status="UNSUPPORTED_DATASET",
                        notes="adapter does not support finance",
                    )
                ]
            ),
            self._schema_frame([]),
        )

    def fetch_disclosure(
        self,
        tickers: list[str],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        return (
            empty_disclosure_candidates(),
            self._diagnostics_frame(
                [
                    self._diagnostic_row(
                        dataset_name="disclosure_status",
                        action="fetch_disclosure",
                        status="UNSUPPORTED_DATASET",
                        notes="adapter does not support disclosure",
                    )
                ]
            ),
            self._schema_frame([]),
        )

    def _diagnostic_row(
        self,
        *,
        dataset_name: str,
        action: str,
        status: str,
        ticker: str = "",
        row_count: int = 0,
        http_status_or_error: str = "",
        source_url: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "source_category": self.source_category,
            "dataset_name": dataset_name,
            "ticker": _clean_ticker(ticker),
            "action": action,
            "status": status,
            "row_count": int(row_count),
            "http_status_or_error": http_status_or_error,
            "source_url": source_url,
            "notes": notes,
        }

    def _schema_row(
        self,
        *,
        dataset_name: str,
        ticker: str,
        source_url: str,
        schema_status: str,
        detected_fields: list[str] | None = None,
        unsupported_fields: list[str] | None = None,
        raw_labels: list[str] | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "source_category": self.source_category,
            "dataset_name": dataset_name,
            "ticker": _clean_ticker(ticker),
            "source_url": source_url,
            "schema_status": schema_status,
            "detected_fields": "|".join(detected_fields or []),
            "unsupported_fields": "|".join(unsupported_fields or []),
            "raw_labels": "|".join(raw_labels or []),
            "notes": notes,
        }

    def _diagnostics_frame(self, rows: list[dict[str, Any]]) -> pd.DataFrame:
        return pd.DataFrame(rows, columns=SOURCE_ADAPTER_DIAGNOSTIC_COLUMNS)

    def _schema_frame(self, rows: list[dict[str, Any]]) -> pd.DataFrame:
        return pd.DataFrame(rows, columns=SOURCE_SCHEMA_DIAGNOSTIC_COLUMNS)

    def _sleep(self) -> None:
        if self.request_sleep_seconds > 0:
            time.sleep(self.request_sleep_seconds)


class WebTableAdapter(SourceAdapter):
    """Best-effort public HTML table adapter with conservative parsing."""

    supported_fields = FINANCE_CANONICAL_FIELDS

    def probe(self, datasets: list[str] | None = None) -> pd.DataFrame:
        rows = []
        probe_urls = self.config.get("probe_urls", {})
        request_defaults = self.config.get("request_defaults", {})
        for dataset_name in datasets or self.supported_datasets:
            sample_url = probe_urls.get(dataset_name)
            if not sample_url:
                rows.append(
                    {
                        "source_name": self.source_name,
                        "source_category": self.source_category,
                        "dataset_name": dataset_name,
                        "probe_status": "UNSUPPORTED_DATASET",
                        "http_status_or_error": "",
                        "is_accessible": False,
                        "requires_js": False,
                        "requires_login": False,
                        "blocked_or_captcha": False,
                        "schema_detected": False,
                        "supported_fields": "",
                        "unsupported_fields": "|".join(self.supported_fields),
                        "sample_url": "",
                        "notes": "no probe URL configured",
                    }
                )
                continue
            rows.append(
                probe_public_url(
                    source_name=self.source_name,
                    source_category=self.source_category,
                    dataset_name=dataset_name,
                    sample_url=sample_url,
                    supported_fields=self.supported_fields if dataset_name == "financial_statement_summary" else [],
                    unsupported_fields=[],
                    http_get=self.http_get,
                    request_defaults=request_defaults,
                )
            )
        return pd.DataFrame(rows)

    def fetch_finance(
        self,
        tickers: list[str],
        periods: list[str] | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        patterns = list(self.config.get("finance_url_patterns", []))
        if not patterns:
            return (
                empty_finance_candidates(),
                self._diagnostics_frame(
                    [
                        self._diagnostic_row(
                            dataset_name="financial_statement_summary",
                            action="fetch_finance",
                            status="UNSUPPORTED_DATASET",
                            notes="no finance URL patterns configured",
                        )
                    ]
                ),
                self._schema_frame([]),
            )

        candidate_rows: list[dict[str, Any]] = []
        diagnostic_rows: list[dict[str, Any]] = []
        schema_rows: list[dict[str, Any]] = []
        for ticker in _ordered_tickers(tickers):
            ticker_rows_before = len(candidate_rows)
            detected_fields = set()
            raw_labels = []
            for pattern in patterns:
                url = pattern.format(ticker=ticker)
                response = self.http_get(url)
                status = _response_status(response)
                if status != "SOURCE_AVAILABLE":
                    diagnostic_rows.append(
                        self._diagnostic_row(
                            dataset_name="financial_statement_summary",
                            action="fetch_finance",
                            ticker=ticker,
                            status=status,
                            http_status_or_error=_response_error(response),
                            source_url=url,
                            notes="finance URL did not return parseable public HTML",
                        )
                    )
                    self._sleep()
                    continue
                parsed_rows, labels = parse_finance_candidate_rows(
                    html=response.body,
                    ticker=ticker,
                    source_category=self.source_category,
                    source_name=self.source_name,
                    source_url=url,
                    fetch_time=_utc_now_iso(),
                )
                candidate_rows.extend(parsed_rows)
                detected_fields.update(row["field_name"] for row in parsed_rows)
                raw_labels.extend(labels)
                diagnostic_rows.append(
                    self._diagnostic_row(
                        dataset_name="financial_statement_summary",
                        action="fetch_finance",
                        ticker=ticker,
                        status="ROWS_PARSED" if parsed_rows else "SOURCE_SCHEMA_UNKNOWN",
                        row_count=len(parsed_rows),
                        http_status_or_error=_response_error(response),
                        source_url=url,
                        notes="parsed source-provided fields only" if parsed_rows else "no supported finance labels detected",
                    )
                )
                self._sleep()
            schema_rows.append(
                self._schema_row(
                    dataset_name="financial_statement_summary",
                    ticker=ticker,
                    source_url="|".join(pattern.format(ticker=ticker) for pattern in patterns),
                    schema_status="SCHEMA_DETECTED" if len(candidate_rows) > ticker_rows_before else "SOURCE_SCHEMA_UNKNOWN",
                    detected_fields=sorted(detected_fields),
                    unsupported_fields=[
                        field for field in FINANCE_CANONICAL_FIELDS if field not in detected_fields
                    ],
                    raw_labels=raw_labels[:50],
                    notes="candidate rows are long-form evidence; missing fields remain missing",
                )
            )

        return (
            pd.DataFrame(candidate_rows, columns=FINANCE_CANDIDATE_COLUMNS),
            self._diagnostics_frame(diagnostic_rows),
            self._schema_frame(schema_rows),
        )

    def fetch_disclosure(
        self,
        tickers: list[str],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        patterns = list(self.config.get("disclosure_url_patterns", []))
        if not patterns:
            return (
                empty_disclosure_candidates(),
                self._diagnostics_frame(
                    [
                        self._diagnostic_row(
                            dataset_name="disclosure_status",
                            action="fetch_disclosure",
                            status="UNSUPPORTED_DATASET",
                            notes="no disclosure URL patterns configured",
                        )
                    ]
                ),
                self._schema_frame([]),
            )

        candidate_rows: list[dict[str, Any]] = []
        diagnostic_rows: list[dict[str, Any]] = []
        schema_rows: list[dict[str, Any]] = []
        urls_are_ticker_specific = any("{ticker}" in pattern for pattern in patterns)
        tickers_to_request = _ordered_tickers(tickers) if urls_are_ticker_specific else [""]
        for ticker in tickers_to_request:
            ticker_rows_before = len(candidate_rows)
            for pattern in patterns:
                url = pattern.format(ticker=ticker)
                response = self.http_get(url)
                status = _response_status(response)
                if status != "SOURCE_AVAILABLE":
                    diagnostic_rows.append(
                        self._diagnostic_row(
                            dataset_name="disclosure_status",
                            action="fetch_disclosure",
                            ticker=ticker,
                            status=status,
                            http_status_or_error=_response_error(response),
                            source_url=url,
                            notes="disclosure URL did not return parseable public HTML",
                        )
                    )
                    self._sleep()
                    continue
                parsed_rows = parse_disclosure_candidate_rows(
                    html=response.body,
                    ticker=ticker,
                    source_category=self.source_category,
                    source_name=self.source_name,
                    source_url=url,
                    fetch_time=_utc_now_iso(),
                )
                candidate_rows.extend(parsed_rows)
                diagnostic_rows.append(
                    self._diagnostic_row(
                        dataset_name="disclosure_status",
                        action="fetch_disclosure",
                        ticker=ticker,
                        status="ROWS_PARSED" if parsed_rows else "SOURCE_SCHEMA_UNKNOWN",
                        row_count=len(parsed_rows),
                        http_status_or_error=_response_error(response),
                        source_url=url,
                        notes="regulatory warning rows parsed" if parsed_rows else "no regulatory warning schema detected",
                    )
                )
                self._sleep()
            schema_rows.append(
                self._schema_row(
                    dataset_name="disclosure_status",
                    ticker=ticker,
                    source_url="|".join(pattern.format(ticker=ticker) for pattern in patterns),
                    schema_status="SCHEMA_DETECTED" if len(candidate_rows) > ticker_rows_before else "SOURCE_SCHEMA_UNKNOWN",
                    detected_fields=["event_type", "severity"] if len(candidate_rows) > ticker_rows_before else [],
                    unsupported_fields=[],
                    raw_labels=[],
                    notes="no row means unavailable unless a source-specific checked row is emitted",
                )
            )

        return (
            pd.DataFrame(candidate_rows, columns=DISCLOSURE_CANDIDATE_COLUMNS),
            self._diagnostics_frame(diagnostic_rows),
            self._schema_frame(schema_rows),
        )


def parse_finance_candidate_rows(
    *,
    html: str,
    ticker: str,
    source_category: str,
    source_name: str,
    source_url: str,
    fetch_time: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse finance candidate rows from HTML tables using known labels only."""

    try:
        tables = pd.read_html(StringIO(html))
    except Exception:
        return [], []

    rows: list[dict[str, Any]] = []
    raw_labels: list[str] = []
    for table in tables:
        if table.empty:
            continue
        table = table.copy()
        table.columns = [str(column) for column in table.columns]
        for _, source_row in table.iterrows():
            label = _first_text_value(source_row)
            field_name = detect_finance_field(label)
            if not field_name:
                continue
            raw_labels.append(str(label))
            for column in table.columns:
                period = _period_from_column(column)
                if not period:
                    continue
                raw_value = source_row.get(column)
                parsed_value = _parse_numeric(raw_value)
                if parsed_value is None:
                    continue
                rows.append(
                    {
                        "ticker": _clean_ticker(ticker),
                        "period": period,
                        "period_type": "quarter" if "Q" in period.upper() else "annual",
                        "field_name": field_name,
                        "value": parsed_value,
                        "unit": "",
                        "currency": "VND",
                        "source_category": source_category,
                        "source_name": source_name,
                        "source_url": source_url,
                        "fetch_time": fetch_time,
                        "confidence_raw": "medium",
                        "raw_label": str(label),
                        "raw_value": str(raw_value),
                        "notes": "parsed from public HTML table; no missing values fabricated",
                    }
                )
    return rows, raw_labels


def parse_disclosure_candidate_rows(
    *,
    html: str,
    ticker: str,
    source_category: str,
    source_name: str,
    source_url: str,
    fetch_time: str,
) -> list[dict[str, Any]]:
    """Parse regulatory/warning disclosure candidates from page text."""

    text = _html_to_text(html)
    event_type, severity = classify_disclosure_event(text)
    if event_type in {"DISCLOSURE_DATA_UNAVAILABLE", "NO_MATERIAL_DISCLOSURE_FOUND_SOURCE_CHECKED"}:
        return []
    return [
        {
            "ticker": _clean_ticker(ticker),
            "event_date": "",
            "event_type": event_type,
            "severity": severity,
            "title": text[:180],
            "description": text[:1000],
            "source_category": source_category,
            "source_name": source_name,
            "source_url": source_url,
            "fetch_time": fetch_time,
            "confidence_raw": "low",
            "raw_event_type": event_type,
            "raw_text": text[:2000],
            "notes": "text pattern matched regulatory warning; manual review required",
        }
    ]


def _response_status(response: Any) -> str:
    status = getattr(response, "status_code", None)
    body = str(getattr(response, "body", "") or "")
    error = str(getattr(response, "error", "") or "")
    lower = body.lower()
    if status == 429:
        return "SOURCE_RATE_LIMITED"
    if status in {401, 403} or "captcha" in lower or "access denied" in lower:
        return "SOURCE_BLOCKED_OR_JS_REQUIRED"
    if error or status is None or status >= 500:
        return "SOURCE_UNAVAILABLE"
    if status >= 400:
        return "SOURCE_UNAVAILABLE"
    if not body.strip():
        return "SOURCE_EMPTY_RESPONSE"
    return "SOURCE_AVAILABLE"


def _response_error(response: Any) -> str:
    error = str(getattr(response, "error", "") or "")
    status = getattr(response, "status_code", None)
    return error or str(status or "")


def _first_text_value(row: pd.Series) -> str:
    for value in row:
        if value is None or pd.isna(value):
            continue
        text = str(value).strip()
        if text and not _looks_numeric(text):
            return text
    return ""


def _period_from_column(column: Any) -> str:
    text = str(column).strip()
    match = re.search(r"(?P<year>20\d{2})\D*(?:Q|Quy)\D*(?P<quarter>[1-4])", text, re.IGNORECASE)
    if match:
        return f"{match.group('year')}-Q{match.group('quarter')}"
    match = re.search(r"Q(?P<quarter>[1-4])\D*(?P<year>20\d{2})", text, re.IGNORECASE)
    if match:
        return f"{match.group('year')}-Q{match.group('quarter')}"
    match = re.search(r"(?P<year>20\d{2})", text)
    if match:
        return match.group("year")
    return ""


def _parse_numeric(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text in {"-", "--"}:
        return None
    text = text.replace("\xa0", "").replace(" ", "")
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    cleaned = re.sub(r"[^0-9,.\-]", "", text)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        cleaned = "".join(parts) if all(len(part) == 3 for part in parts[1:]) else cleaned.replace(",", ".")
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts) > 2 and all(len(part) == 3 for part in parts[1:]):
            cleaned = "".join(parts)
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return -number if negative else number


def _html_to_text(html: str) -> str:
    text = re.sub(r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def _looks_numeric(text: str) -> bool:
    return bool(re.fullmatch(r"[\d,.\-() ]+", text))


def _ordered_tickers(tickers: list[str]) -> list[str]:
    result: list[str] = []
    for ticker in tickers:
        clean = _clean_ticker(ticker)
        if clean and clean not in result:
            result.append(clean)
    return result


def _clean_ticker(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
