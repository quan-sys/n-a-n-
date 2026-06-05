"""Deterministic disclosure status-list classification for REAL-DATA-01H."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None


DEFAULT_DISCLOSURE_CLASSIFIER_PATH = Path("config/disclosure_event_classifier.yaml")

ALLOWED_DISCLOSURE_EVENT_TYPES = {
    "WARNING_LIST",
    "CONTROL_LIST",
    "SUPERVISION_LIST",
    "TRADING_RESTRICTION",
    "TRADING_SUSPENSION",
    "DELISTING_WARNING",
    "DELISTING",
    "LATE_FINANCIAL_REPORT",
    "AUDIT_QUALIFIED_OPINION",
    "DISCLOSURE_VIOLATION",
    "SSC_SANCTION",
    "NO_MATERIAL_DISCLOSURE_FOUND_SOURCE_CHECKED",
    "DISCLOSURE_SOURCE_UNAVAILABLE",
    "DISCLOSURE_SCHEMA_UNKNOWN",
    "DISCLOSURE_PARSE_FAILED",
    "DISCLOSURE_DATA_UNAVAILABLE",
    "OTHER_REGULATORY_DISCLOSURE",
}

ALLOWED_DISCLOSURE_SEVERITIES = {"critical", "high", "medium", "low", "unknown"}

ALLOWED_DISCLOSURE_EVIDENCE_STATUSES = {
    "SOURCE_CONFIRMED_WARNING",
    "SOURCE_CHECKED_NOT_FOUND",
    "SOURCE_UNAVAILABLE",
    "SOURCE_SCHEMA_UNKNOWN",
    "SOURCE_PARSE_FAILED",
    "POSITIVE_CONTROL_CONFIRMED",
    "POSITIVE_CONTROL_UNAVAILABLE",
    "MANUAL_REVIEW_REQUIRED",
}

STATUS_TO_EVENT = {
    "SOURCE_SSL_FAILED": ("DISCLOSURE_SOURCE_UNAVAILABLE", "SOURCE_UNAVAILABLE"),
    "SOURCE_UNAVAILABLE": ("DISCLOSURE_SOURCE_UNAVAILABLE", "SOURCE_UNAVAILABLE"),
    "SOURCE_BLOCKED_OR_JS_REQUIRED": ("DISCLOSURE_SOURCE_UNAVAILABLE", "SOURCE_UNAVAILABLE"),
    "SOURCE_RATE_LIMITED": ("DISCLOSURE_SOURCE_UNAVAILABLE", "SOURCE_UNAVAILABLE"),
    "SOURCE_EMPTY_RESPONSE": ("DISCLOSURE_DATA_UNAVAILABLE", "SOURCE_UNAVAILABLE"),
    "SOURCE_SCHEMA_UNKNOWN": ("DISCLOSURE_SCHEMA_UNKNOWN", "SOURCE_SCHEMA_UNKNOWN"),
    "SOURCE_PARSE_FAILED": ("DISCLOSURE_PARSE_FAILED", "SOURCE_PARSE_FAILED"),
}

LIST_TYPE_EVENT_HINTS = {
    "WARNING_LIST": "WARNING_LIST",
    "CONTROL_LIST": "CONTROL_LIST",
    "SUPERVISION_LIST": "SUPERVISION_LIST",
    "TRADING_RESTRICTION_LIST": "TRADING_RESTRICTION",
    "TRADING_SUSPENSION_LIST": "TRADING_SUSPENSION",
    "DELISTING_WARNING_LIST": "DELISTING_WARNING",
    "DELISTING_LIST": "DELISTING",
    "LATE_FINANCIAL_REPORT_LIST": "LATE_FINANCIAL_REPORT",
    "AUDIT_QUALIFIED_LIST": "AUDIT_QUALIFIED_OPINION",
    "DISCLOSURE_VIOLATION_LIST": "DISCLOSURE_VIOLATION",
    "SSC_SANCTION_LIST": "SSC_SANCTION",
}

EVENT_FLAG_COLUMNS = {
    "WARNING_LIST": "appears_in_warning_list",
    "CONTROL_LIST": "appears_in_control_list",
    "SUPERVISION_LIST": "appears_in_supervision_list",
    "TRADING_RESTRICTION": "appears_in_restriction_list",
    "TRADING_SUSPENSION": "appears_in_suspension_list",
    "DELISTING_WARNING": "appears_in_delisting_warning_list",
    "DELISTING": "appears_in_delisting_list",
    "LATE_FINANCIAL_REPORT": "appears_in_late_financial_report_list",
    "AUDIT_QUALIFIED_OPINION": "appears_in_audit_qualified_list",
    "DISCLOSURE_VIOLATION": "appears_in_disclosure_violation_list",
    "SSC_SANCTION": "appears_in_sanction_list",
}

DEFAULT_EVENT_RULES = {
    "TRADING_SUSPENSION": {
        "severity": "critical",
        "keywords": ["tam ngung", "dinh chi", "suspension"],
    },
    "DELISTING": {
        "severity": "critical",
        "keywords": ["huy niem yet bat buoc", "delisting"],
    },
    "DELISTING_WARNING": {
        "severity": "high",
        "keywords": ["canh bao huy niem yet", "huy niem yet"],
    },
    "CONTROL_LIST": {
        "severity": "high",
        "keywords": ["kiem soat", "control"],
    },
    "TRADING_RESTRICTION": {
        "severity": "high",
        "keywords": ["han che giao dich", "restricted"],
    },
    "SSC_SANCTION": {
        "severity": "high",
        "keywords": ["uy ban chung khoan nha nuoc", "quyet dinh xu phat", "sanction"],
    },
    "AUDIT_QUALIFIED_OPINION": {
        "severity": "high",
        "keywords": ["y kien ngoai tru", "qualified opinion", "tu choi dua ra y kien"],
    },
    "SUPERVISION_LIST": {
        "severity": "medium",
        "keywords": ["giam sat", "supervision"],
    },
    "LATE_FINANCIAL_REPORT": {
        "severity": "medium",
        "keywords": ["cham nop bao cao tai chinh", "cham cong bo thong tin bao cao tai chinh"],
    },
    "DISCLOSURE_VIOLATION": {
        "severity": "medium",
        "keywords": ["vi pham cong bo thong tin", "cham cong bo thong tin"],
    },
    "WARNING_LIST": {
        "severity": "medium",
        "keywords": ["canh bao", "warning"],
    },
    "OTHER_REGULATORY_DISCLOSURE": {
        "severity": "unknown",
        "keywords": ["cong bo thong tin", "niem yet", "chung khoan"],
    },
}


def load_disclosure_classifier_config(
    path: str | Path = DEFAULT_DISCLOSURE_CLASSIFIER_PATH,
) -> dict[str, Any]:
    """Load classifier YAML; return defaults if PyYAML is absent."""

    if yaml is None:
        return {"events": DEFAULT_EVENT_RULES}
    config_path = Path(path)
    if not config_path.exists():
        return {"events": DEFAULT_EVENT_RULES}
    with config_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    return data if isinstance(data, dict) else {"events": DEFAULT_EVENT_RULES}


def classify_disclosure_status(
    *,
    list_type: Any,
    title: Any = "",
    raw_text: Any = "",
    config: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Classify a source list/title/raw text into event_type and severity."""

    normalized_list_type = str(list_type or "").strip().upper()
    if normalized_list_type in LIST_TYPE_EVENT_HINTS:
        hinted_event = LIST_TYPE_EVENT_HINTS[normalized_list_type]
        severity = _severity_for_event(hinted_event, config)
        refined = _classify_by_keywords(
            text=f"{title} {raw_text}",
            config=config,
            fallback_event=hinted_event,
        )
        if _severity_rank(refined[1]) > _severity_rank(severity):
            return refined
        return hinted_event, severity

    return _classify_by_keywords(text=f"{list_type} {title} {raw_text}", config=config)


def source_failure_event(probe_or_parse_status: str) -> tuple[str, str, str]:
    """Map a source failure status to event_type, severity, evidence_status."""

    event_type, evidence_status = STATUS_TO_EVENT.get(
        str(probe_or_parse_status or "").strip().upper(),
        ("DISCLOSURE_DATA_UNAVAILABLE", "MANUAL_REVIEW_REQUIRED"),
    )
    return event_type, "unknown", evidence_status


def event_flags(event_type: str) -> dict[str, bool]:
    """Return boolean status-list flags for one event type."""

    flags = {column: False for column in EVENT_FLAG_COLUMNS.values()}
    flag = EVENT_FLAG_COLUMNS.get(str(event_type or "").strip().upper())
    if flag:
        flags[flag] = True
    return flags


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


def _classify_by_keywords(
    *,
    text: str,
    config: dict[str, Any] | None = None,
    fallback_event: str = "OTHER_REGULATORY_DISCLOSURE",
) -> tuple[str, str]:
    normalized = normalize_text(text)
    rules = _event_rules(config)
    for event_type, settings in rules.items():
        keywords = [normalize_text(keyword) for keyword in settings.get("keywords", [])]
        if any(keyword and keyword in normalized for keyword in keywords):
            severity = str(settings.get("severity", "unknown")).strip().lower()
            if severity not in ALLOWED_DISCLOSURE_SEVERITIES:
                severity = "unknown"
            return event_type, severity
    if fallback_event in ALLOWED_DISCLOSURE_EVENT_TYPES:
        return fallback_event, _severity_for_event(fallback_event, config)
    return "OTHER_REGULATORY_DISCLOSURE", "unknown"


def _severity_for_event(event_type: str, config: dict[str, Any] | None = None) -> str:
    rules = _event_rules(config)
    severity = str(rules.get(event_type, {}).get("severity", "unknown")).strip().lower()
    return severity if severity in ALLOWED_DISCLOSURE_SEVERITIES else "unknown"


def _event_rules(config: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    configured = (config or {}).get("events") if isinstance(config, dict) else None
    if not isinstance(configured, dict):
        configured = DEFAULT_EVENT_RULES
    rules: dict[str, dict[str, Any]] = {}
    for event_type, settings in configured.items():
        normalized_event = str(event_type).strip().upper()
        if normalized_event in ALLOWED_DISCLOSURE_EVENT_TYPES and isinstance(settings, dict):
            rules[normalized_event] = settings
    return rules or DEFAULT_EVENT_RULES


def _severity_rank(severity: str) -> int:
    return {"unknown": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}.get(
        str(severity).lower(),
        0,
    )
