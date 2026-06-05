"""Contracts for REAL-DATA-01G source probes and candidate rows."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd


SOURCE_STATUSES = {
    "SOURCE_AVAILABLE",
    "SOURCE_UNAVAILABLE",
    "SOURCE_SCHEMA_UNKNOWN",
    "SOURCE_BLOCKED_OR_JS_REQUIRED",
    "SOURCE_PARSE_FAILED",
    "SOURCE_RATE_LIMITED",
    "SOURCE_EMPTY_RESPONSE",
    "DEPENDENCY_UNAVAILABLE",
    "UNSUPPORTED_DATASET",
    "FETCH_SKIPPED",
    "ROWS_PARSED",
}

SOURCE_PROBE_COLUMNS = [
    "source_name",
    "source_category",
    "dataset_name",
    "probe_status",
    "http_status_or_error",
    "is_accessible",
    "requires_js",
    "requires_login",
    "blocked_or_captcha",
    "schema_detected",
    "supported_fields",
    "unsupported_fields",
    "sample_url",
    "notes",
]

SOURCE_ADAPTER_DIAGNOSTIC_COLUMNS = [
    "source_name",
    "source_category",
    "dataset_name",
    "ticker",
    "action",
    "status",
    "row_count",
    "http_status_or_error",
    "source_url",
    "notes",
]

SOURCE_SCHEMA_DIAGNOSTIC_COLUMNS = [
    "source_name",
    "source_category",
    "dataset_name",
    "ticker",
    "source_url",
    "schema_status",
    "detected_fields",
    "unsupported_fields",
    "raw_labels",
    "notes",
]

FINANCE_CANDIDATE_COLUMNS = [
    "ticker",
    "period",
    "period_type",
    "field_name",
    "value",
    "unit",
    "currency",
    "source_category",
    "source_name",
    "source_url",
    "fetch_time",
    "confidence_raw",
    "raw_label",
    "raw_value",
    "notes",
]

DISCLOSURE_CANDIDATE_COLUMNS = [
    "ticker",
    "event_date",
    "event_type",
    "severity",
    "title",
    "description",
    "source_category",
    "source_name",
    "source_url",
    "fetch_time",
    "confidence_raw",
    "raw_event_type",
    "raw_text",
    "notes",
]

FINANCE_CANONICAL_FIELDS = [
    "revenue",
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

DISCLOSURE_EVENT_TYPES = [
    "LATE_FINANCIAL_REPORT",
    "AUDIT_QUALIFIED_OPINION",
    "GOING_CONCERN_WARNING",
    "WARNING_LIST",
    "CONTROL_LIST",
    "TRADING_RESTRICTION",
    "TRADING_SUSPENSION",
    "DELISTING_WARNING",
    "DISCLOSURE_VIOLATION",
    "SSC_SANCTION",
    "NEGATIVE_EQUITY_WARNING",
    "MATERIAL_INTERNAL_TRANSACTION",
    "OTHER_REGULATORY_DISCLOSURE",
    "NO_MATERIAL_DISCLOSURE_FOUND_SOURCE_CHECKED",
    "DISCLOSURE_DATA_UNAVAILABLE",
]

FINANCE_LABEL_PATTERNS = {
    "revenue": [
        "doanh thu thuan",
        "doanh thu",
        "net revenue",
        "revenue",
        "sales",
    ],
    "net_profit": [
        "loi nhuan sau thue cua co dong cong ty me",
        "loi nhuan sau thue",
        "lnst",
        "profit after tax",
        "net profit",
        "post tax profit",
    ],
    "total_assets": [
        "tong tai san",
        "total assets",
        "assets",
    ],
    "total_liabilities": [
        "no phai tra",
        "tong no phai tra",
        "liabilities",
        "total liabilities",
    ],
    "equity": [
        "von chu so huu",
        "equity",
        "owners equity",
        "shareholders equity",
    ],
    "cash": [
        "tien va tuong duong tien",
        "cash and cash equivalents",
        "cash",
    ],
    "short_term_debt": [
        "vay va no thue tai chinh ngan han",
        "short term borrowings",
        "short term debt",
    ],
    "long_term_debt": [
        "vay va no thue tai chinh dai han",
        "long term borrowings",
        "long term debt",
    ],
    "operating_cash_flow": [
        "luu chuyen tien thuan tu hoat dong kinh doanh",
        "net cash flows from operating activities",
        "operating cash flow",
    ],
    "inventory": [
        "hang ton kho",
        "inventories",
        "inventory",
    ],
}


def empty_probe_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=SOURCE_PROBE_COLUMNS)


def empty_adapter_diagnostics() -> pd.DataFrame:
    return pd.DataFrame(columns=SOURCE_ADAPTER_DIAGNOSTIC_COLUMNS)


def empty_schema_diagnostics() -> pd.DataFrame:
    return pd.DataFrame(columns=SOURCE_SCHEMA_DIAGNOSTIC_COLUMNS)


def empty_finance_candidates() -> pd.DataFrame:
    return pd.DataFrame(columns=FINANCE_CANDIDATE_COLUMNS)


def empty_disclosure_candidates() -> pd.DataFrame:
    return pd.DataFrame(columns=DISCLOSURE_CANDIDATE_COLUMNS)


def validate_probe_frame(df: pd.DataFrame) -> dict[str, Any]:
    return _validate_columns(df, SOURCE_PROBE_COLUMNS, "source_probe")


def validate_candidate_frame(df: pd.DataFrame, dataset_name: str) -> dict[str, Any]:
    if dataset_name == "financial_statement_summary":
        return _validate_columns(df, FINANCE_CANDIDATE_COLUMNS, dataset_name)
    if dataset_name == "disclosure_status":
        return _validate_columns(df, DISCLOSURE_CANDIDATE_COLUMNS, dataset_name)
    return {"is_valid": False, "errors": [f"Unsupported candidate dataset: {dataset_name}"]}


def detect_finance_field(raw_label: Any) -> str:
    """Map a source label to a canonical finance field when safely identifiable."""

    normalized = normalize_text(raw_label)
    if not normalized:
        return ""
    for field_name, patterns in FINANCE_LABEL_PATTERNS.items():
        if any(pattern in normalized for pattern in patterns):
            return field_name
    return ""


def classify_disclosure_event(text: Any) -> tuple[str, str]:
    """Classify regulatory/warning disclosure text deterministically."""

    normalized = normalize_text(text)
    if not normalized:
        return "DISCLOSURE_DATA_UNAVAILABLE", "unknown"

    rules = [
        ("GOING_CONCERN_WARNING", "critical", ["going concern", "hoat dong lien tuc"]),
        ("TRADING_SUSPENSION", "critical", ["tam ngung giao dich", "suspension", "dinh chi giao dich"]),
        ("DELISTING_WARNING", "critical", ["huy niem yet", "delisting"]),
        ("CONTROL_LIST", "high", ["dien kiem soat", "kiem soat dac biet", "control list"]),
        ("TRADING_RESTRICTION", "high", ["han che giao dich", "restricted trading", "giao dich han che"]),
        ("NEGATIVE_EQUITY_WARNING", "high", ["am von chu so huu", "negative equity"]),
        ("SSC_SANCTION", "high", ["uy ban chung khoan", "ssc", "xu phat", "sanction"]),
        ("AUDIT_QUALIFIED_OPINION", "medium", ["ngoai tru", "qualified opinion", "kiem toan ngoai tru"]),
        ("WARNING_LIST", "medium", ["dien canh bao", "warning list", "canh bao"]),
        ("LATE_FINANCIAL_REPORT", "medium", ["cham nop", "nop bao cao tai chinh cham", "late financial report"]),
        ("DISCLOSURE_VIOLATION", "medium", ["vi pham cong bo thong tin", "disclosure violation"]),
        ("MATERIAL_INTERNAL_TRANSACTION", "low", ["giao dich noi bo", "internal transaction"]),
    ]
    for event_type, severity, patterns in rules:
        if any(pattern in normalized for pattern in patterns):
            return event_type, severity
    regulatory_markers = [
        "cong bo thong tin",
        "bao cao tai chinh",
        "kiem toan",
        "niem yet",
        "so giao dich",
    ]
    if any(marker in normalized for marker in regulatory_markers):
        return "OTHER_REGULATORY_DISCLOSURE", "unknown"
    return "DISCLOSURE_DATA_UNAVAILABLE", "unknown"


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFD", text)
    without_marks = "".join(
        character
        for character in decomposed
        if unicodedata.category(character) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", without_marks).strip()


def _validate_columns(df: pd.DataFrame, required: list[str], label: str) -> dict[str, Any]:
    if not isinstance(df, pd.DataFrame):
        return {"is_valid": False, "errors": [f"{label}: expected DataFrame"]}
    missing = [column for column in required if column not in df.columns]
    return {
        "is_valid": not missing,
        "errors": [f"{label}: missing columns: {', '.join(missing)}"] if missing else [],
    }
