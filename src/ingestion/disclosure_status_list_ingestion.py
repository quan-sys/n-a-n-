"""Official disclosure/status-list ingestion for REAL-DATA-01H."""

from __future__ import annotations

import html
import json
import re
import time
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingestion.disclosure_event_classifier import (
    ALLOWED_DISCLOSURE_EVIDENCE_STATUSES,
    ALLOWED_DISCLOSURE_EVENT_TYPES,
    ALLOWED_DISCLOSURE_SEVERITIES,
    classify_disclosure_status,
    event_flags,
    load_disclosure_classifier_config,
    normalize_text,
    source_failure_event,
)
from src.ingestion.disclosure_positive_control import (
    build_positive_control_tickers,
    positive_control_status,
)
from src.ingestion.real_source_adapters import DISCLOSURE_TEMPLATE_COLUMNS
from src.ingestion.source_snapshot import (
    SNAPSHOT_METADATA_COLUMNS,
    fetch_public_snapshot,
    probe_status_from_snapshot,
    snapshot_metadata_row,
    utc_now_iso,
)

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None


DEFAULT_DISCLOSURE_STATUS_SOURCES_PATH = Path("config/disclosure_status_sources.yaml")

DISCLOSURE_SOURCE_PROBE_COLUMNS = [
    "source_name",
    "source_category",
    "source_url",
    "list_type",
    "probe_status",
    "http_status_or_error",
    "content_type",
    "requires_js",
    "requires_login",
    "blocked_or_captcha",
    "schema_detected",
    "download_link_found",
    "parser_selected",
    "parse_status",
    "rows_parsed",
    "tickers_parsed",
    "notes",
]

DISCLOSURE_LIST_PARSE_DIAGNOSTIC_COLUMNS = [
    "source_name",
    "source_category",
    "source_url",
    "list_type",
    "parser_selected",
    "parse_status",
    "rows_parsed",
    "tickers_parsed",
    "status_list_id",
    "notes",
]

DISCLOSURE_STATUS_RAW_INDEX_COLUMNS = [
    "ticker",
    "event_date",
    "source_category",
    "source_name",
    "source_url",
    "raw_list_type",
    "raw_status_list_id",
    "event_type",
    "severity",
    "evidence_status",
    "confidence_raw",
    "raw_title",
    "raw_text",
    "fetch_time",
    "notes",
]

DISCLOSURE_STATUS_BY_TICKER_COLUMNS = [
    "ticker",
    "as_of_date",
    "source_event_date",
    "market",
    "source_category",
    "source_name",
    "source_url",
    "source_checked",
    "appears_in_warning_list",
    "appears_in_control_list",
    "appears_in_supervision_list",
    "appears_in_restriction_list",
    "appears_in_suspension_list",
    "appears_in_delisting_warning_list",
    "appears_in_delisting_list",
    "appears_in_late_financial_report_list",
    "appears_in_audit_qualified_list",
    "appears_in_disclosure_violation_list",
    "appears_in_sanction_list",
    "event_type",
    "severity",
    "evidence_status",
    "confidence_raw",
    "raw_list_type",
    "raw_title",
    "raw_text",
    "fetch_time",
    "notes",
]

DISCLOSURE_COVERAGE_COLUMNS = [
    "source_category",
    "source_name",
    "event_type",
    "evidence_status",
    "row_count",
    "ticker_count",
    "warning_rows",
    "source_checked_no_warning_rows",
    "unavailable_or_failed_rows",
    "notes",
]

FAILED_SOURCE_STATUSES = {
    "SOURCE_UNAVAILABLE",
    "SOURCE_BLOCKED_OR_JS_REQUIRED",
    "SOURCE_SCHEMA_UNKNOWN",
    "SOURCE_SSL_FAILED",
    "SOURCE_PARSE_FAILED",
    "SOURCE_RATE_LIMITED",
    "SOURCE_EMPTY_RESPONSE",
}

RISK_EVENT_TYPES = {
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
}


def load_disclosure_status_sources(
    path: str | Path = DEFAULT_DISCLOSURE_STATUS_SOURCES_PATH,
) -> dict[str, Any]:
    """Load disclosure source targets."""

    if yaml is None:
        raise ImportError("PyYAML is required to load disclosure status sources.")
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise ValueError("disclosure status sources must contain a YAML mapping.")
    return data


def run_disclosure_status_01h(
    *,
    representative_tickers: list[str],
    sources: list[str],
    output_dir: str | Path,
    raw_snapshot_dir: str | Path,
    source_config: dict[str, Any] | None = None,
    classifier_config: dict[str, Any] | None = None,
    request_sleep_seconds: float = 0,
    year: int | None = None,
    page_size: int = 500,
    allow_partial: bool = False,
) -> dict[str, Any]:
    """Run 01H source discovery, positive-control, and ticker matching."""

    config = source_config or load_disclosure_status_sources()
    classifier = classifier_config or load_disclosure_classifier_config()
    selected_sources = _ordered_tokens(sources)
    if not selected_sources:
        selected_sources = list((config.get("sources") or {}).keys())
    tickers = _ordered_tickers(representative_tickers)
    if not tickers:
        raise ValueError("representative_tickers must not be empty.")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    snapshot_path = Path(raw_snapshot_dir)
    snapshot_path.mkdir(parents=True, exist_ok=True)

    context = {
        "probe_rows": [],
        "parse_rows": [],
        "index_rows": [],
        "snapshot_rows": [],
        "parsed_list_rows": [],
    }

    for source_key in selected_sources:
        source = (config.get("sources") or {}).get(source_key)
        if not isinstance(source, dict):
            if not allow_partial:
                raise ValueError(f"Unknown disclosure source: {source_key}")
            continue
        parser = str(source.get("parser", "")).strip()
        if parser == "hose_json":
            _run_hose_json_source(
                source=source,
                context=context,
                snapshot_dir=snapshot_path,
                classifier_config=classifier,
                request_defaults=config.get("request_defaults", {}),
                request_sleep_seconds=request_sleep_seconds,
                year=year or datetime.now(UTC).year,
                page_size=page_size,
            )
        elif parser == "html_table":
            _run_html_table_source(
                source=source,
                context=context,
                snapshot_dir=snapshot_path,
                classifier_config=classifier,
                request_defaults=config.get("request_defaults", {}),
                request_sleep_seconds=request_sleep_seconds,
            )
        else:
            _run_discovery_only_source(
                source=source,
                context=context,
                snapshot_dir=snapshot_path,
                request_defaults=config.get("request_defaults", {}),
                request_sleep_seconds=request_sleep_seconds,
            )

    probe_matrix = pd.DataFrame(context["probe_rows"], columns=DISCLOSURE_SOURCE_PROBE_COLUMNS)
    parse_diagnostics = pd.DataFrame(
        context["parse_rows"],
        columns=DISCLOSURE_LIST_PARSE_DIAGNOSTIC_COLUMNS,
    )
    status_list_index = pd.DataFrame(
        context["index_rows"],
        columns=DISCLOSURE_STATUS_RAW_INDEX_COLUMNS,
    )
    snapshot_metadata = pd.DataFrame(
        context["snapshot_rows"],
        columns=SNAPSHOT_METADATA_COLUMNS,
    )
    parsed_lists = pd.DataFrame(context["parsed_list_rows"])

    positive_control = build_positive_control_tickers(status_list_index, max_tickers=20)
    status_by_ticker = build_disclosure_status_by_ticker(
        representative_tickers=tickers,
        positive_control_tickers=positive_control["ticker"].tolist()
        if "ticker" in positive_control.columns
        else [],
        status_list_index=status_list_index,
        probe_matrix=probe_matrix,
        parsed_lists=parsed_lists,
        as_of_date=datetime.now(UTC).date().isoformat(),
    )
    candidate_rows = disclosure_status_by_ticker_to_raw(status_by_ticker)
    coverage = build_disclosure_coverage_by_source(status_by_ticker)
    source_checked_no_warning = status_by_ticker[
        status_by_ticker["evidence_status"] == "SOURCE_CHECKED_NOT_FOUND"
    ].copy()

    warning_rows = status_by_ticker[
        status_by_ticker["evidence_status"].isin(
            ["SOURCE_CONFIRMED_WARNING", "POSITIVE_CONTROL_CONFIRMED"]
        )
    ].copy()
    positive_control_warning_rows = warning_rows[
        warning_rows["ticker"].isin(set(positive_control.get("ticker", [])))
    ].copy()
    adapter_status = positive_control_status(
        positive_control_tickers=positive_control,
        matched_warning_rows=positive_control_warning_rows,
    )

    reports = {
        "disclosure_source_probe_matrix": probe_matrix,
        "disclosure_list_parse_diagnostics": parse_diagnostics,
        "disclosure_status_lists_raw_index": status_list_index,
        "disclosure_positive_control_tickers": positive_control,
        "disclosure_status_by_ticker": status_by_ticker,
        "disclosure_candidate_rows": candidate_rows,
        "disclosure_coverage_by_source": coverage,
        "disclosure_source_checked_no_warning": source_checked_no_warning,
        "source_snapshot_metadata": snapshot_metadata,
    }
    for name, frame in reports.items():
        frame.to_csv(output_path / f"{name}.csv", index=False)

    return {
        **reports,
        "positive_control_status": adapter_status,
        "representative_tickers": tickers,
        "parsed_lists": parsed_lists,
    }


def build_disclosure_status_by_ticker(
    *,
    representative_tickers: list[str],
    positive_control_tickers: list[str],
    status_list_index: pd.DataFrame,
    probe_matrix: pd.DataFrame,
    parsed_lists: pd.DataFrame,
    as_of_date: str,
) -> pd.DataFrame:
    """Create ticker-level warning, no-warning, and source-failure rows."""

    rows: list[dict[str, Any]] = []
    rep_tickers = _ordered_tickers(representative_tickers)
    positive_tickers = _ordered_tickers(positive_control_tickers)
    target_tickers = _ordered_tickers([*rep_tickers, *positive_tickers])
    positive_set = set(positive_tickers)

    index = (
        status_list_index
        if isinstance(status_list_index, pd.DataFrame)
        else pd.DataFrame(columns=DISCLOSURE_STATUS_RAW_INDEX_COLUMNS)
    )
    if not index.empty:
        for _, source_row in index.iterrows():
            ticker = _clean_ticker(source_row.get("ticker"))
            if ticker not in target_tickers:
                continue
            rows.append(
                _status_output_row(
                    ticker=ticker,
                    as_of_date=as_of_date,
                    source_event_date=source_row.get("event_date", "") or as_of_date,
                    market="",
                    source_category=source_row.get("source_category", ""),
                    source_name=source_row.get("source_name", ""),
                    source_url=source_row.get("source_url", ""),
                    source_checked=True,
                    event_type=source_row.get("event_type", ""),
                    severity=source_row.get("severity", ""),
                    evidence_status=(
                        "POSITIVE_CONTROL_CONFIRMED"
                        if ticker in positive_set
                        else "SOURCE_CONFIRMED_WARNING"
                    ),
                    confidence_raw=source_row.get("confidence_raw", "high"),
                    raw_list_type=source_row.get("raw_list_type", ""),
                    raw_title=source_row.get("raw_title", ""),
                    raw_text=source_row.get("raw_text", ""),
                    fetch_time=source_row.get("fetch_time", ""),
                    notes=source_row.get("notes", ""),
                )
            )

    parsed = (
        parsed_lists
        if isinstance(parsed_lists, pd.DataFrame)
        else pd.DataFrame()
    )
    if not parsed.empty:
        parsed_success = parsed[
            (parsed["parse_status"].astype(str) == "ROWS_PARSED")
            & (parsed["official"].astype(bool))
            & (parsed["event_type"].isin(RISK_EVENT_TYPES))
        ]
        for _, parsed_row in parsed_success.iterrows():
            source_url = str(parsed_row.get("source_url", ""))
            list_type = str(parsed_row.get("list_type", ""))
            source_category = str(parsed_row.get("source_category", ""))
            source_name = str(parsed_row.get("source_name", ""))
            matched = _matching_tickers(index, source_url=source_url, list_type=list_type)
            for ticker in rep_tickers:
                if ticker in matched:
                    continue
                rows.append(
                    _status_output_row(
                        ticker=ticker,
                        as_of_date=as_of_date,
                        source_event_date=as_of_date,
                        market="HOSE" if source_category == "hose" else "",
                        source_category=source_category,
                        source_name=source_name,
                        source_url=source_url,
                        source_checked=True,
                        event_type="NO_MATERIAL_DISCLOSURE_FOUND_SOURCE_CHECKED",
                        severity="unknown",
                        evidence_status="SOURCE_CHECKED_NOT_FOUND",
                        confidence_raw="medium",
                        raw_list_type=list_type,
                        raw_title=f"Not found in parsed {list_type}",
                        raw_text="",
                        fetch_time=str(parsed_row.get("fetch_time", "")),
                        notes=(
                            "Absence from parsed list is not a guarantee of clean disclosure; "
                            "it only means this ticker was not found in this parsed source/list."
                        ),
                    )
                )

    failed_probe = _failed_official_probe_rows(probe_matrix)
    for _, failed in failed_probe.iterrows():
        event_type, severity, evidence_status = source_failure_event(
            str(failed.get("parse_status") or failed.get("probe_status"))
        )
        for ticker in rep_tickers:
            rows.append(
                _status_output_row(
                    ticker=ticker,
                    as_of_date=as_of_date,
                    source_event_date=as_of_date,
                    market="",
                    source_category=failed.get("source_category", ""),
                    source_name=failed.get("source_name", ""),
                    source_url=failed.get("source_url", ""),
                    source_checked=False,
                    event_type=event_type,
                    severity=severity,
                    evidence_status=evidence_status,
                    confidence_raw="low",
                    raw_list_type=failed.get("list_type", ""),
                    raw_title=str(failed.get("probe_status", "")),
                    raw_text=str(failed.get("notes", "")),
                    fetch_time="",
                    notes="source/list could not be checked; do not treat as no-warning",
                )
            )

    return pd.DataFrame(rows, columns=DISCLOSURE_STATUS_BY_TICKER_COLUMNS)


def disclosure_status_by_ticker_to_raw(status_by_ticker: pd.DataFrame) -> pd.DataFrame:
    """Convert 01H ticker status rows to the 01F disclosure raw schema."""

    output_columns = [
        *DISCLOSURE_TEMPLATE_COLUMNS,
        "source_category",
        "source_name",
        "evidence_status",
        "raw_list_type",
    ]
    if not isinstance(status_by_ticker, pd.DataFrame) or status_by_ticker.empty:
        return pd.DataFrame(columns=output_columns)
    rows = []
    for _, row in status_by_ticker.iterrows():
        rows.append(
            {
                "ticker": _clean_ticker(row.get("ticker")),
                "event_date": row.get("source_event_date", "") or row.get("as_of_date", ""),
                "event_type": row.get("event_type", ""),
                "severity": row.get("severity", ""),
                "title": row.get("raw_title", ""),
                "description": row.get("raw_text", ""),
                "source": row.get("source_name", ""),
                "source_url": row.get("source_url", ""),
                "fetch_time": row.get("fetch_time", ""),
                "confidence_raw": row.get("confidence_raw", ""),
                "notes": (
                    f"evidence_status={row.get('evidence_status', '')}; "
                    f"raw_list_type={row.get('raw_list_type', '')}; "
                    f"{row.get('notes', '')}"
                ),
                "source_category": row.get("source_category", ""),
                "source_name": row.get("source_name", ""),
                "evidence_status": row.get("evidence_status", ""),
                "raw_list_type": row.get("raw_list_type", ""),
            }
        )
    return _aggregate_disclosure_raw_rows(pd.DataFrame(rows, columns=output_columns), output_columns)


def build_disclosure_coverage_by_source(status_by_ticker: pd.DataFrame) -> pd.DataFrame:
    """Summarize 01H ticker-level disclosure coverage by source/status."""

    if not isinstance(status_by_ticker, pd.DataFrame) or status_by_ticker.empty:
        return pd.DataFrame(columns=DISCLOSURE_COVERAGE_COLUMNS)
    rows = []
    for key, group in status_by_ticker.groupby(
        ["source_category", "source_name", "event_type", "evidence_status"],
        dropna=False,
    ):
        source_category, source_name, event_type, evidence_status = key
        rows.append(
            {
                "source_category": source_category,
                "source_name": source_name,
                "event_type": event_type,
                "evidence_status": evidence_status,
                "row_count": int(len(group)),
                "ticker_count": int(group["ticker"].nunique()),
                "warning_rows": int(
                    group["evidence_status"].isin(
                        ["SOURCE_CONFIRMED_WARNING", "POSITIVE_CONTROL_CONFIRMED"]
                    ).sum()
                ),
                "source_checked_no_warning_rows": int(
                    (group["evidence_status"] == "SOURCE_CHECKED_NOT_FOUND").sum()
                ),
                "unavailable_or_failed_rows": int(
                    group["evidence_status"].isin(
                        ["SOURCE_UNAVAILABLE", "SOURCE_SCHEMA_UNKNOWN", "SOURCE_PARSE_FAILED"]
                    ).sum()
                ),
                "notes": "01H disclosure status-list evidence; missing/source failures are not clean",
            }
        )
    return pd.DataFrame(rows, columns=DISCLOSURE_COVERAGE_COLUMNS)


def _aggregate_disclosure_raw_rows(
    raw_rows: pd.DataFrame,
    output_columns: list[str],
) -> pd.DataFrame:
    """Aggregate detailed source/list rows to evidence-layer-safe records."""

    if not isinstance(raw_rows, pd.DataFrame) or raw_rows.empty:
        return pd.DataFrame(columns=output_columns)
    group_columns = [
        "ticker",
        "event_date",
        "event_type",
        "severity",
        "source_category",
        "evidence_status",
    ]
    rows: list[dict[str, Any]] = []
    for key, group in raw_rows.groupby(group_columns, dropna=False, sort=False):
        ticker, event_date, event_type, severity, source_category, evidence_status = key
        rows.append(
            {
                "ticker": ticker,
                "event_date": event_date,
                "event_type": event_type,
                "severity": severity,
                "title": _join_unique(group["title"]),
                "description": _join_unique(group["description"]),
                "source": _join_unique(group["source"]),
                "source_url": _join_unique(group["source_url"]),
                "fetch_time": max(
                    [str(value).strip() for value in group["fetch_time"] if str(value).strip()]
                    or [""]
                ),
                "confidence_raw": _aggregate_confidence(group["confidence_raw"]),
                "notes": _join_unique(group["notes"]),
                "source_category": source_category,
                "source_name": _join_unique(group["source_name"]),
                "evidence_status": evidence_status,
                "raw_list_type": _join_unique(group["raw_list_type"]),
            }
        )
    return pd.DataFrame(rows, columns=output_columns)


def build_disclosure_01h_summary_markdown(
    *,
    command: str,
    reports: dict[str, Any],
    evidence_decisions: dict[str, Any],
    custom_decision: dict[str, Any],
) -> str:
    """Render 01H summary markdown."""

    probe = reports["disclosure_source_probe_matrix"]
    status = reports["disclosure_status_by_ticker"]
    positive = reports["disclosure_positive_control_tickers"]
    candidate = reports["disclosure_candidate_rows"]
    attempted = _join_unique(probe.get("source_category", []))
    accessible = _join_unique(
        probe.loc[
            probe["probe_status"].isin(["SOURCE_AVAILABLE", "SOURCE_SCHEMA_UNKNOWN"]),
            "source_category",
        ]
        if not probe.empty
        else []
    )
    parsed_sources = _join_unique(
        probe.loc[probe["parse_status"] == "ROWS_PARSED", "source_category"]
        if not probe.empty
        else []
    )
    failed = _failure_summary(probe)
    lines = [
        "# REAL-DATA-01H Disclosure Status Run Summary",
        "",
        f"- command: {command}",
        f"- sources_attempted: {attempted}",
        f"- sources_accessible: {accessible}",
        f"- sources_parsed: {parsed_sources}",
        f"- source_failures: {failed}",
        f"- positive_control_tickers: {len(positive)}",
        f"- positive_control_warning_rows: {_positive_warning_count(status, positive)}",
        f"- disclosure_candidate_rows: {len(candidate)}",
        f"- source_checked_no_warning_rows: {int((status['evidence_status'] == 'SOURCE_CHECKED_NOT_FOUND').sum()) if not status.empty else 0}",
        f"- unavailable_or_schema_failed_rows: {_failure_status_count(status)}",
        f"- evidence_layer_disclosure_ready_for_l0: {evidence_decisions.get('disclosure_ready_for_l0', False)}",
        f"- disclosure_ready_for_l0: {custom_decision.get('disclosure_ready_for_l0', 'False')}",
        f"- finance_disclosure_ready_for_step18: {custom_decision.get('finance_disclosure_ready_for_step18', 'False')}",
        "- step19_implemented: False",
        "",
        "Source-checked not found rows are not a guarantee of clean disclosure.",
        "Source failure rows are not treated as no-warning.",
        "",
    ]
    return "\n".join(lines)


def build_01h_decision_report_markdown(decision: dict[str, Any]) -> str:
    """Render conservative 01H data-source decision report."""

    lines = [
        "# REAL-DATA-01H Data Source Decision Report",
        "",
        f"- disclosure_ready_for_l0: {decision.get('disclosure_ready_for_l0', 'False')}",
        f"- finance_disclosure_ready_for_step18: {decision.get('finance_disclosure_ready_for_step18', 'False')}",
        f"- should_run_REAL_DATA_02: {decision.get('should_run_REAL_DATA_02', 'No')}",
        f"- should_implement_Step19_now: {decision.get('should_implement_Step19_now', 'No')}",
        f"- positive_control_status: {decision.get('positive_control_status', '')}",
        f"- representative_confirmed_warning_rows: {decision.get('representative_confirmed_warning_rows', 0)}",
        f"- representative_source_checked_no_warning_rows: {decision.get('representative_source_checked_no_warning_rows', 0)}",
        f"- representative_unavailable_schema_failed_rows: {decision.get('representative_unavailable_schema_failed_rows', 0)}",
        f"- unresolved_disclosure_count: {decision.get('unresolved_disclosure_count', 0)}",
        "- step19_implemented: False",
        "",
        "## Decision",
        "",
        "Do not scale REAL-DATA-02 and do not implement Step 19.",
        "Disclosure status evidence improved only where official lists were parsed.",
        "Finance remains insufficient, and failed official sources still require manual review.",
        "",
    ]
    return "\n".join(lines)


def build_comparison_vs_01g(
    *,
    previous_dir: str | Path,
    current_dir: str | Path,
    status_by_ticker: pd.DataFrame,
    positive_control: pd.DataFrame,
    probe_matrix: pd.DataFrame,
    unresolved_required_fields: pd.DataFrame,
    custom_decision: dict[str, Any],
) -> str:
    """Build markdown comparison between REAL-DATA-01G and 01H."""

    prev = _read_01g_metrics(Path(previous_dir))
    current_unresolved_disclosure = _dataset_count(unresolved_required_fields, "disclosure_status")
    current_candidate_rows = _read_csv(Path(current_dir) / "disclosure_candidate_rows.csv")
    official_sources_probed = _official_source_count(probe_matrix)
    official_sources_parsed = _official_source_count(
        probe_matrix[probe_matrix["parse_status"] == "ROWS_PARSED"]
        if not probe_matrix.empty
        else probe_matrix
    )
    no_warning = int(
        (status_by_ticker["evidence_status"] == "SOURCE_CHECKED_NOT_FOUND").sum()
        if not status_by_ticker.empty
        else 0
    )
    positive_warning = _positive_warning_count(status_by_ticker, positive_control)
    lines = [
        "# Comparison vs REAL-DATA-01G",
        "",
        f"- previous_dir: {previous_dir}",
        f"- current_dir: {current_dir}",
        "",
        "| Metric | 01G | 01H |",
        "| --- | ---: | ---: |",
        f"| official sources probed | {prev['official_sources_probed']} | {official_sources_probed} |",
        f"| official sources parsed | {prev['official_sources_parsed']} | {official_sources_parsed} |",
        f"| representative no-warning source-checked rows | 0 | {no_warning} |",
        f"| positive-control tickers count | 0 | {len(positive_control)} |",
        f"| positive-control warning rows count | 0 | {positive_warning} |",
        f"| disclosure candidate rows | {prev['disclosure_candidate_rows']} | {len(current_candidate_rows)} |",
        f"| unresolved disclosure fields | {prev['unresolved_disclosure_fields']} | {current_unresolved_disclosure} |",
        "",
        "## Readiness",
        "",
        f"- disclosure_ready_for_l0 before/after: {prev['disclosure_ready_for_l0']} -> {custom_decision.get('disclosure_ready_for_l0', 'False')}",
        f"- finance_disclosure_ready_for_step18 before/after: {prev['finance_disclosure_ready_for_step18']} -> {custom_decision.get('finance_disclosure_ready_for_step18', 'False')}",
        "- step19_implemented: False",
        "",
    ]
    return "\n".join(lines)


def build_custom_01h_decision(
    *,
    representative_tickers: list[str],
    status_by_ticker: pd.DataFrame,
    positive_control: pd.DataFrame,
    positive_control_status_value: str,
    evidence_decisions: dict[str, Any],
    unresolved_required_fields: pd.DataFrame,
) -> dict[str, Any]:
    """Build conservative 01H readiness independent of 01F's boolean decision."""

    reps = set(_ordered_tickers(representative_tickers))
    rep_rows = status_by_ticker[status_by_ticker["ticker"].isin(reps)] if not status_by_ticker.empty else status_by_ticker
    confirmed = int(
        rep_rows["evidence_status"].isin(["SOURCE_CONFIRMED_WARNING", "POSITIVE_CONTROL_CONFIRMED"]).sum()
        if isinstance(rep_rows, pd.DataFrame) and not rep_rows.empty
        else 0
    )
    no_warning = int(
        (rep_rows["evidence_status"] == "SOURCE_CHECKED_NOT_FOUND").sum()
        if isinstance(rep_rows, pd.DataFrame) and not rep_rows.empty
        else 0
    )
    failures = _failure_status_count(rep_rows)
    disclosure_partial = (
        positive_control_status_value == "POSITIVE_CONTROL_CONFIRMED"
        and no_warning > 0
    )
    disclosure_ready = "Partial" if disclosure_partial else "False"
    finance_disclosure_ready = "False"
    return {
        "disclosure_ready_for_l0": disclosure_ready,
        "finance_disclosure_ready_for_step18": finance_disclosure_ready,
        "should_run_REAL_DATA_02": "No",
        "should_implement_Step19_now": "No",
        "positive_control_status": positive_control_status_value,
        "positive_control_tickers_count": int(len(positive_control)),
        "positive_control_warning_rows_count": _positive_warning_count(status_by_ticker, positive_control),
        "representative_confirmed_warning_rows": confirmed,
        "representative_source_checked_no_warning_rows": no_warning,
        "representative_unavailable_schema_failed_rows": failures,
        "unresolved_disclosure_count": _dataset_count(unresolved_required_fields, "disclosure_status"),
        "evidence_layer_disclosure_ready_for_l0": evidence_decisions.get("disclosure_ready_for_l0", False),
        "step19_implemented": False,
    }


def _run_hose_json_source(
    *,
    source: dict[str, Any],
    context: dict[str, list[dict[str, Any]]],
    snapshot_dir: Path,
    classifier_config: dict[str, Any],
    request_defaults: dict[str, Any],
    request_sleep_seconds: float,
    year: int,
    page_size: int,
) -> None:
    source_name = str(source.get("source_name", "hose"))
    source_category = str(source.get("source_category", "hose"))
    status_endpoint = str(source.get("status_list_endpoint", ""))
    status_items: list[dict[str, Any]] = []
    if status_endpoint:
        result = _fetch(
            url=status_endpoint,
            source=source,
            snapshot_dir=snapshot_dir,
            request_defaults=request_defaults,
        )
        status, payload = _json_payload(result)
        parse_status = "ROWS_PARSED" if status == "SOURCE_AVAILABLE" and isinstance(payload, dict) else status
        if parse_status == "ROWS_PARSED":
            raw_status_items = payload.get("data", [])
            if isinstance(raw_status_items, list):
                for item in raw_status_items:
                    if not isinstance(item, dict):
                        continue
                    list_type, event_type, severity = _hose_status_list_type(
                        str(item.get("name", "")),
                        classifier_config,
                    )
                    status_items.append(
                        {
                            "status_list_id": item.get("id", ""),
                            "name": item.get("name", ""),
                            "list_type": list_type,
                            "event_type": event_type,
                            "severity": severity,
                            "include_as_risk": event_type in RISK_EVENT_TYPES,
                        }
                    )
        context["probe_rows"].append(
            _probe_row(
                source=source,
                url=status_endpoint,
                list_type="STATUS_LIST_INDEX",
                result=result,
                parser_selected="hose_json_status_index",
                parse_status=parse_status,
                rows_parsed=len(status_items),
                tickers_parsed=0,
                notes="HOSE status-list index endpoint",
            )
        )
        context["parse_rows"].append(
            _parse_row(
                source=source,
                url=status_endpoint,
                list_type="STATUS_LIST_INDEX",
                parser_selected="hose_json_status_index",
                parse_status=parse_status,
                rows_parsed=len(status_items),
                tickers_parsed=0,
                status_list_id="",
                notes="parsed status list ids; not ticker rows",
            )
        )
        context["snapshot_rows"].append(
            snapshot_metadata_row(
                result=result,
                source_name=source_name,
                source_category=source_category,
                parser_used="hose_json_status_index",
                parse_status=parse_status,
                notes="HOSE status-list index",
            )
        )
        _sleep(request_sleep_seconds)

    for item in status_items:
        if not item.get("include_as_risk"):
            continue
        url_template = str(source.get("stock_status_endpoint", ""))
        url = url_template.format(
            page_index=1,
            page_size=page_size,
            status_list_id=item["status_list_id"],
        )
        parsed_rows, parse_status, result, total_pages = _fetch_hose_paged_rows(
            source=source,
            url_template=url_template,
            page_size=page_size,
            year=year,
            status_list_id=item["status_list_id"],
            list_type=item["list_type"],
            classifier_config=classifier_config,
            snapshot_dir=snapshot_dir,
            request_defaults=request_defaults,
            request_sleep_seconds=request_sleep_seconds,
        )
        context["index_rows"].extend(parsed_rows)
        context["probe_rows"].append(
            _probe_row(
                source=source,
                url=url,
                list_type=item["list_type"],
                result=result,
                parser_selected="hose_json_stock_status",
                parse_status=parse_status,
                rows_parsed=len(parsed_rows),
                tickers_parsed=_ticker_count(parsed_rows),
                notes=f"HOSE status list id {item['status_list_id']}; total_pages={total_pages}",
            )
        )
        context["parse_rows"].append(
            _parse_row(
                source=source,
                url=url,
                list_type=item["list_type"],
                parser_selected="hose_json_stock_status",
                parse_status=parse_status,
                rows_parsed=len(parsed_rows),
                tickers_parsed=_ticker_count(parsed_rows),
                status_list_id=item["status_list_id"],
                notes="parsed source-provided status-list ticker rows",
            )
        )
        context["snapshot_rows"].append(
            snapshot_metadata_row(
                result=result,
                source_name=source_name,
                source_category=source_category,
                parser_used="hose_json_stock_status",
                parse_status=parse_status,
                notes=f"HOSE stock-status endpoint for status_list_id={item['status_list_id']}",
            )
        )
        context["parsed_list_rows"].append(
            _parsed_list_row(source, url, item["list_type"], item["event_type"], parse_status, len(parsed_rows), result)
        )

    for endpoint in source.get("securities_violating_endpoints", []) or []:
        if not isinstance(endpoint, dict):
            continue
        list_type = str(endpoint.get("list_type", "DISCLOSURE_VIOLATION_LIST"))
        url_template = str(endpoint.get("url", ""))
        url = url_template.format(page_index=1, page_size=page_size, year=year)
        parsed_rows, parse_status, result, total_pages = _fetch_hose_paged_rows(
            source=source,
            url_template=url_template,
            page_size=page_size,
            year=year,
            status_list_id="",
            list_type=list_type,
            classifier_config=classifier_config,
            snapshot_dir=snapshot_dir,
            request_defaults=request_defaults,
            request_sleep_seconds=request_sleep_seconds,
        )
        context["index_rows"].extend(parsed_rows)
        event_type, _ = classify_disclosure_status(
            list_type=list_type,
            title=list_type,
            raw_text="",
            config=classifier_config,
        )
        context["probe_rows"].append(
            _probe_row(
                source=source,
                url=url,
                list_type=list_type,
                result=result,
                parser_selected="hose_json_securities_violating",
                parse_status=parse_status,
                rows_parsed=len(parsed_rows),
                tickers_parsed=_ticker_count(parsed_rows),
                notes=f"HOSE securities violating endpoint; total_pages={total_pages}",
            )
        )
        context["parse_rows"].append(
            _parse_row(
                source=source,
                url=url,
                list_type=list_type,
                parser_selected="hose_json_securities_violating",
                parse_status=parse_status,
                rows_parsed=len(parsed_rows),
                tickers_parsed=_ticker_count(parsed_rows),
                status_list_id="",
                notes="parsed source-provided violation ticker rows",
            )
        )
        context["snapshot_rows"].append(
            snapshot_metadata_row(
                result=result,
                source_name=source_name,
                source_category=source_category,
                parser_used="hose_json_securities_violating",
                parse_status=parse_status,
                notes="HOSE securities violating endpoint",
            )
        )
        context["parsed_list_rows"].append(
            _parsed_list_row(source, url, list_type, event_type, parse_status, len(parsed_rows), result)
        )


def _run_html_table_source(
    *,
    source: dict[str, Any],
    context: dict[str, list[dict[str, Any]]],
    snapshot_dir: Path,
    classifier_config: dict[str, Any],
    request_defaults: dict[str, Any],
    request_sleep_seconds: float,
) -> None:
    for target in source.get("probe_urls", []) or []:
        if not isinstance(target, dict):
            continue
        url = str(target.get("url", ""))
        list_type = str(target.get("list_type", "WARNING_LIST"))
        result = _fetch(
            url=url,
            source=source,
            snapshot_dir=snapshot_dir,
            request_defaults=request_defaults,
        )
        status = probe_status_from_snapshot(result)
        parsed_rows: list[dict[str, Any]] = []
        parse_status = status
        if status == "SOURCE_AVAILABLE":
            try:
                parsed_rows = _parse_html_status_rows(
                    html_text=result.text,
                    source=source,
                    source_url=url,
                    list_type=list_type,
                    classifier_config=classifier_config,
                    fetch_time=result.fetched_at,
                )
                parse_status = "ROWS_PARSED" if parsed_rows else "SOURCE_SCHEMA_UNKNOWN"
            except Exception:  # noqa: BLE001 - source parser failures are diagnostics, not crashes.
                parsed_rows = []
                parse_status = "SOURCE_PARSE_FAILED"
        context["index_rows"].extend(parsed_rows)
        event_type, _ = classify_disclosure_status(
            list_type=list_type,
            title=list_type,
            raw_text="",
            config=classifier_config,
        )
        context["probe_rows"].append(
            _probe_row(
                source=source,
                url=url,
                list_type=list_type,
                result=result,
                parser_selected="html_table",
                parse_status=parse_status,
                rows_parsed=len(parsed_rows),
                tickers_parsed=_ticker_count(parsed_rows),
                notes="public HTML table probe for official disclosure/status list",
            )
        )
        context["parse_rows"].append(
            _parse_row(
                source=source,
                url=url,
                list_type=list_type,
                parser_selected="html_table",
                parse_status=parse_status,
                rows_parsed=len(parsed_rows),
                tickers_parsed=_ticker_count(parsed_rows),
                status_list_id="",
                notes="HTML table status-list parser",
            )
        )
        context["parsed_list_rows"].append(
            _parsed_list_row(source, url, list_type, event_type, parse_status, len(parsed_rows), result)
        )
        context["snapshot_rows"].append(
            snapshot_metadata_row(
                result=result,
                source_name=str(source.get("source_name", "")),
                source_category=str(source.get("source_category", "")),
                parser_used="html_table",
                parse_status=parse_status,
                notes="HTML table source snapshot",
            )
        )
        _sleep(request_sleep_seconds)


def _run_discovery_only_source(
    *,
    source: dict[str, Any],
    context: dict[str, list[dict[str, Any]]],
    snapshot_dir: Path,
    request_defaults: dict[str, Any],
    request_sleep_seconds: float,
) -> None:
    for target in source.get("probe_urls", []) or []:
        if not isinstance(target, dict):
            continue
        url = str(target.get("url", ""))
        list_type = str(target.get("list_type", "DISCLOSURE_VIOLATION_LIST"))
        result = _fetch(
            url=url,
            source=source,
            snapshot_dir=snapshot_dir,
            request_defaults=request_defaults,
        )
        status = probe_status_from_snapshot(result)
        if status == "SOURCE_AVAILABLE":
            status = "SOURCE_SCHEMA_UNKNOWN"
        context["probe_rows"].append(
            _probe_row(
                source=source,
                url=url,
                list_type=list_type,
                result=result,
                parser_selected="discovery_only",
                parse_status=status,
                rows_parsed=0,
                tickers_parsed=0,
                notes="secondary/discovery-only source; no official status-list parser selected",
            )
        )
        context["parse_rows"].append(
            _parse_row(
                source=source,
                url=url,
                list_type=list_type,
                parser_selected="discovery_only",
                parse_status=status,
                rows_parsed=0,
                tickers_parsed=0,
                status_list_id="",
                notes="not used as official status-list evidence",
            )
        )
        context["snapshot_rows"].append(
            snapshot_metadata_row(
                result=result,
                source_name=str(source.get("source_name", "")),
                source_category=str(source.get("source_category", "")),
                parser_used="discovery_only",
                parse_status=status,
                notes="discovery-only source snapshot",
            )
        )
        _sleep(request_sleep_seconds)


def _fetch_hose_paged_rows(
    *,
    source: dict[str, Any],
    url_template: str,
    page_size: int,
    year: int,
    status_list_id: Any,
    list_type: str,
    classifier_config: dict[str, Any],
    snapshot_dir: Path,
    request_defaults: dict[str, Any],
    request_sleep_seconds: float,
) -> tuple[list[dict[str, Any]], str, Any, int]:
    rows: list[dict[str, Any]] = []
    first_result = None
    parse_status = "SOURCE_UNAVAILABLE"
    total_pages = 1
    page = 1
    while page <= total_pages and page <= 20:
        url = url_template.format(
            page_index=page,
            page_size=page_size,
            year=year,
            status_list_id=status_list_id,
        )
        result = _fetch(
            url=url,
            source=source,
            snapshot_dir=snapshot_dir,
            request_defaults=request_defaults,
        )
        if first_result is None:
            first_result = result
        status, payload = _json_payload(result)
        if status != "SOURCE_AVAILABLE" or not isinstance(payload, dict):
            return rows, status, first_result, total_pages
        data = payload.get("data", {})
        if not isinstance(data, dict):
            return rows, "SOURCE_SCHEMA_UNKNOWN", first_result, total_pages
        paging = data.get("paging", {})
        if isinstance(paging, dict):
            total_pages = max(1, int(float(paging.get("totalPages") or 1)))
        source_rows = data.get("list", [])
        if not isinstance(source_rows, list):
            return rows, "SOURCE_SCHEMA_UNKNOWN", first_result, total_pages
        rows.extend(
            _parse_hose_json_rows(
                source_rows=source_rows,
                source=source,
                source_url=url,
                list_type=list_type,
                status_list_id=status_list_id,
                classifier_config=classifier_config,
                fetch_time=result.fetched_at,
            )
        )
        parse_status = "ROWS_PARSED"
        page += 1
        _sleep(request_sleep_seconds)
    return rows, parse_status, first_result, total_pages


def _parse_hose_json_rows(
    *,
    source_rows: list[Any],
    source: dict[str, Any],
    source_url: str,
    list_type: str,
    status_list_id: Any,
    classifier_config: dict[str, Any],
    fetch_time: str,
) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for raw in source_rows:
        if not isinstance(raw, dict):
            continue
        ticker = _clean_ticker(
            raw.get("securitiesCode")
            or raw.get("symbol")
            or raw.get("ticker")
            or raw.get("code")
        )
        if not ticker:
            continue
        title = str(raw.get("name") or raw.get("title") or "")
        raw_text = _strip_html(str(raw.get("reason") or raw.get("description") or title))
        event_type, severity = classify_disclosure_status(
            list_type=list_type,
            title=title,
            raw_text=raw_text,
            config=classifier_config,
        )
        parsed.append(
            {
                "ticker": ticker,
                "event_date": _date_from_source_value(raw.get("datePublish") or raw.get("date")),
                "source_category": source.get("source_category", ""),
                "source_name": _source_name(source, list_type),
                "source_url": source_url,
                "raw_list_type": list_type,
                "raw_status_list_id": status_list_id,
                "event_type": event_type,
                "severity": severity,
                "evidence_status": "SOURCE_CONFIRMED_WARNING",
                "confidence_raw": "high",
                "raw_title": title,
                "raw_text": raw_text,
                "fetch_time": fetch_time,
                "notes": "parsed from official/public status list; no disclosure fact fabricated",
            }
        )
    return parsed


def _parse_html_status_rows(
    *,
    html_text: str,
    source: dict[str, Any],
    source_url: str,
    list_type: str,
    classifier_config: dict[str, Any],
    fetch_time: str,
) -> list[dict[str, Any]]:
    tables = pd.read_html(StringIO(html_text))
    rows: list[dict[str, Any]] = []
    for table in tables:
        if table.empty:
            continue
        table = table.copy()
        table.columns = [str(column) for column in table.columns]
        for _, record in table.iterrows():
            text_values = [str(value) for value in record.to_list() if not pd.isna(value)]
            text = " | ".join(text_values)
            ticker = _first_ticker(text)
            if not ticker:
                continue
            event_type, severity = classify_disclosure_status(
                list_type=list_type,
                title=text_values[1] if len(text_values) > 1 else "",
                raw_text=text,
                config=classifier_config,
            )
            rows.append(
                {
                    "ticker": ticker,
                    "event_date": _first_date(text),
                    "source_category": source.get("source_category", ""),
                    "source_name": _source_name(source, list_type),
                    "source_url": source_url,
                    "raw_list_type": list_type,
                    "raw_status_list_id": "",
                    "event_type": event_type,
                    "severity": severity,
                    "evidence_status": "SOURCE_CONFIRMED_WARNING",
                    "confidence_raw": "medium",
                    "raw_title": text_values[1] if len(text_values) > 1 else ticker,
                    "raw_text": text,
                    "fetch_time": fetch_time,
                    "notes": "parsed from public HTML table; no disclosure fact fabricated",
                }
            )
    return rows


def _hose_status_list_type(
    name: str,
    classifier_config: dict[str, Any],
) -> tuple[str, str, str]:
    normalized = normalize_text(name)
    if "niem yet moi" in normalized or "chung quyen" in normalized:
        return "OTHER_STATUS_LIST", "OTHER_REGULATORY_DISCLOSURE", "unknown"
    if "cong bo thong tin" in normalized:
        return _classified_type("DISCLOSURE_VIOLATION_LIST", name, classifier_config)
    if "bao cao tai chinh" in normalized:
        return _classified_type("LATE_FINANCIAL_REPORT_LIST", name, classifier_config)
    if "dinh chi" in normalized or "tam ngung" in normalized:
        return _classified_type("TRADING_SUSPENSION_LIST", name, classifier_config)
    if "han che giao dich" in normalized:
        return _classified_type("TRADING_RESTRICTION_LIST", name, classifier_config)
    if "kiem soat" in normalized:
        return _classified_type("CONTROL_LIST", name, classifier_config)
    if "canh bao" in normalized:
        return _classified_type("WARNING_LIST", name, classifier_config)
    return _classified_type("OTHER_REGULATORY_DISCLOSURE", name, classifier_config)


def _classified_type(
    list_type: str,
    name: str,
    classifier_config: dict[str, Any],
) -> tuple[str, str, str]:
    event_type, severity = classify_disclosure_status(
        list_type=list_type,
        title=name,
        raw_text="",
        config=classifier_config,
    )
    return list_type, event_type, severity


def _fetch(
    *,
    url: str,
    source: dict[str, Any],
    snapshot_dir: Path,
    request_defaults: dict[str, Any],
) -> Any:
    headers = dict(request_defaults.get("headers", {})) if isinstance(request_defaults, dict) else {}
    user_agent = str(request_defaults.get("user_agent", "") or "")
    if user_agent:
        headers["User-Agent"] = user_agent
    return fetch_public_snapshot(
        url=url,
        snapshot_dir=snapshot_dir,
        source_name=str(source.get("source_name", "")),
        source_category=str(source.get("source_category", "")),
        parser_used=str(source.get("parser", "")),
        timeout_seconds=int(request_defaults.get("timeout_seconds", 25)),
        max_fetch_bytes=int(request_defaults.get("max_fetch_bytes", 1_200_000)),
        max_snapshot_bytes=int(request_defaults.get("max_snapshot_bytes", 350_000)),
        headers=headers,
    )


def _json_payload(result: Any) -> tuple[str, dict[str, Any] | None]:
    status = probe_status_from_snapshot(result)
    if status != "SOURCE_AVAILABLE":
        return status, None
    try:
        payload = json.loads(result.text)
    except json.JSONDecodeError:
        return "SOURCE_PARSE_FAILED", None
    if not isinstance(payload, dict) or payload.get("success") is not True:
        return "SOURCE_SCHEMA_UNKNOWN", payload if isinstance(payload, dict) else None
    return "SOURCE_AVAILABLE", payload


def _probe_row(
    *,
    source: dict[str, Any],
    url: str,
    list_type: str,
    result: Any,
    parser_selected: str,
    parse_status: str,
    rows_parsed: int,
    tickers_parsed: int,
    notes: str,
) -> dict[str, Any]:
    body = str(getattr(result, "text", "") or "").lower()
    probe_status = probe_status_from_snapshot(result)
    return {
        "source_name": source.get("source_name", ""),
        "source_category": source.get("source_category", ""),
        "source_url": url,
        "list_type": list_type,
        "probe_status": probe_status,
        "http_status_or_error": getattr(result, "error", "") or str(getattr(result, "status_code", "") or ""),
        "content_type": getattr(result, "content_type", ""),
        "requires_js": _requires_js(body),
        "requires_login": any(marker in body for marker in ["login", "dang nhap", "sign in"]),
        "blocked_or_captcha": any(marker in body for marker in ["captcha", "access denied", "forbidden"]),
        "schema_detected": parse_status == "ROWS_PARSED",
        "download_link_found": _download_link_found(body),
        "parser_selected": parser_selected,
        "parse_status": parse_status,
        "rows_parsed": int(rows_parsed),
        "tickers_parsed": int(tickers_parsed),
        "notes": notes,
    }


def _parse_row(
    *,
    source: dict[str, Any],
    url: str,
    list_type: str,
    parser_selected: str,
    parse_status: str,
    rows_parsed: int,
    tickers_parsed: int,
    status_list_id: Any,
    notes: str,
) -> dict[str, Any]:
    return {
        "source_name": source.get("source_name", ""),
        "source_category": source.get("source_category", ""),
        "source_url": url,
        "list_type": list_type,
        "parser_selected": parser_selected,
        "parse_status": parse_status,
        "rows_parsed": int(rows_parsed),
        "tickers_parsed": int(tickers_parsed),
        "status_list_id": status_list_id,
        "notes": notes,
    }


def _parsed_list_row(
    source: dict[str, Any],
    url: str,
    list_type: str,
    event_type: str,
    parse_status: str,
    rows_parsed: int,
    result: Any,
) -> dict[str, Any]:
    return {
        "source_category": source.get("source_category", ""),
        "source_name": _source_name(source, list_type),
        "source_url": url,
        "list_type": list_type,
        "event_type": event_type,
        "official": bool(source.get("official")),
        "parse_status": parse_status,
        "rows_parsed": int(rows_parsed),
        "fetch_time": getattr(result, "fetched_at", ""),
    }


def _status_output_row(
    *,
    ticker: str,
    as_of_date: str,
    source_event_date: str,
    market: str,
    source_category: Any,
    source_name: Any,
    source_url: Any,
    source_checked: bool,
    event_type: Any,
    severity: Any,
    evidence_status: Any,
    confidence_raw: Any,
    raw_list_type: Any,
    raw_title: Any,
    raw_text: Any,
    fetch_time: Any,
    notes: Any,
) -> dict[str, Any]:
    clean_event = str(event_type or "").strip().upper()
    clean_severity = str(severity or "").strip().lower()
    clean_evidence = str(evidence_status or "").strip().upper()
    if clean_event not in ALLOWED_DISCLOSURE_EVENT_TYPES:
        clean_event = "OTHER_REGULATORY_DISCLOSURE"
    if clean_severity not in ALLOWED_DISCLOSURE_SEVERITIES:
        clean_severity = "unknown"
    if clean_evidence not in ALLOWED_DISCLOSURE_EVIDENCE_STATUSES:
        clean_evidence = "MANUAL_REVIEW_REQUIRED"
    flags = event_flags(clean_event)
    return {
        "ticker": _clean_ticker(ticker),
        "as_of_date": as_of_date,
        "source_event_date": source_event_date,
        "market": market,
        "source_category": source_category,
        "source_name": source_name,
        "source_url": source_url,
        "source_checked": bool(source_checked),
        **flags,
        "event_type": clean_event,
        "severity": clean_severity,
        "evidence_status": clean_evidence,
        "confidence_raw": confidence_raw,
        "raw_list_type": raw_list_type,
        "raw_title": raw_title,
        "raw_text": raw_text,
        "fetch_time": fetch_time,
        "notes": notes,
    }


def _failed_official_probe_rows(probe_matrix: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(probe_matrix, pd.DataFrame) or probe_matrix.empty:
        return pd.DataFrame(columns=DISCLOSURE_SOURCE_PROBE_COLUMNS)
    official_categories = {"hose", "hnx", "upcom_hnx", "ssc"}
    failed = probe_matrix[
        probe_matrix["source_category"].isin(official_categories)
        & (
            probe_matrix["probe_status"].isin(FAILED_SOURCE_STATUSES)
            | probe_matrix["parse_status"].isin(FAILED_SOURCE_STATUSES)
        )
    ].copy()
    if failed.empty:
        return failed
    return failed.drop_duplicates(subset=["source_category", "source_url", "list_type"])


def _matching_tickers(index: pd.DataFrame, *, source_url: str, list_type: str) -> set[str]:
    if not isinstance(index, pd.DataFrame) or index.empty:
        return set()
    rows = index[
        (index["source_url"].astype(str) == str(source_url))
        & (index["raw_list_type"].astype(str) == str(list_type))
    ]
    return {_clean_ticker(value) for value in rows.get("ticker", []) if _clean_ticker(value)}


def _read_01g_metrics(report_dir: Path) -> dict[str, Any]:
    probe = _read_csv(report_dir / "source_probe_matrix.csv")
    adapter = _read_csv(report_dir / "source_adapter_diagnostics.csv")
    candidate = _read_csv(report_dir / "disclosure_raw_candidate_rows.csv")
    unresolved = _read_csv(report_dir / "unresolved_required_fields.csv")
    decision = _read_text(report_dir / "datasource_decision_report.md")
    official_categories = {"hose", "hnx", "ssc"}
    official_probe = (
        probe[probe["source_category"].isin(official_categories)]
        if not probe.empty and "source_category" in probe.columns
        else pd.DataFrame()
    )
    parsed = (
        adapter[
            adapter["source_category"].isin(official_categories)
            & (adapter["status"].astype(str) == "ROWS_PARSED")
        ]
        if not adapter.empty and "source_category" in adapter.columns
        else pd.DataFrame()
    )
    return {
        "official_sources_probed": int(official_probe["source_category"].nunique()) if not official_probe.empty else 0,
        "official_sources_parsed": int(parsed["source_category"].nunique()) if not parsed.empty else 0,
        "disclosure_candidate_rows": int(len(candidate)),
        "unresolved_disclosure_fields": _dataset_count(unresolved, "disclosure_status"),
        "disclosure_ready_for_l0": _markdown_value(decision, "disclosure_ready_for_l0") or "False",
        "finance_disclosure_ready_for_step18": _markdown_value(decision, "finance_disclosure_ready_for_step18") or "False",
    }


def _official_source_count(probe_matrix: pd.DataFrame) -> int:
    if not isinstance(probe_matrix, pd.DataFrame) or probe_matrix.empty:
        return 0
    rows = probe_matrix[probe_matrix["source_category"].isin({"hose", "hnx", "ssc", "upcom_hnx"})]
    return int(rows["source_category"].nunique())


def _dataset_count(df: pd.DataFrame, dataset_name: str) -> int:
    if not isinstance(df, pd.DataFrame) or df.empty or "dataset_name" not in df.columns:
        return 0
    return int((df["dataset_name"].astype(str) == dataset_name).sum())


def _positive_warning_count(status_by_ticker: pd.DataFrame, positive_control: pd.DataFrame) -> int:
    if (
        not isinstance(status_by_ticker, pd.DataFrame)
        or status_by_ticker.empty
        or not isinstance(positive_control, pd.DataFrame)
        or positive_control.empty
    ):
        return 0
    tickers = set(positive_control["ticker"].map(_clean_ticker))
    rows = status_by_ticker[
        status_by_ticker["ticker"].isin(tickers)
        & status_by_ticker["evidence_status"].isin(
            ["SOURCE_CONFIRMED_WARNING", "POSITIVE_CONTROL_CONFIRMED"]
        )
    ]
    return int(len(rows))


def _failure_status_count(status_by_ticker: pd.DataFrame) -> int:
    if not isinstance(status_by_ticker, pd.DataFrame) or status_by_ticker.empty:
        return 0
    return int(
        status_by_ticker["evidence_status"].isin(
            ["SOURCE_UNAVAILABLE", "SOURCE_SCHEMA_UNKNOWN", "SOURCE_PARSE_FAILED"]
        ).sum()
    )


def _failure_summary(probe_matrix: pd.DataFrame) -> str:
    if not isinstance(probe_matrix, pd.DataFrame) or probe_matrix.empty:
        return ""
    rows = probe_matrix[
        probe_matrix["probe_status"].isin(FAILED_SOURCE_STATUSES)
        | probe_matrix["parse_status"].isin(FAILED_SOURCE_STATUSES)
    ]
    if rows.empty:
        return ""
    values = []
    for _, row in rows.iterrows():
        values.append(
            f"{row.get('source_category', '')}:{row.get('list_type', '')}:{row.get('probe_status', '')}/{row.get('parse_status', '')}"
        )
    return "; ".join(values)


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, keep_default_na=False) if path.exists() else pd.DataFrame()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _markdown_value(text: str, key: str) -> str:
    marker = f"- {key}:"
    for line in text.splitlines():
        if line.startswith(marker):
            return line.split(":", 1)[1].strip()
    return ""


def _strip_html(value: str) -> str:
    unescaped = html.unescape(value or "")
    return " ".join(re.sub(r"<[^>]+>", " ", unescaped).split())


def _date_from_source_value(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
        if number > 10_000_000:
            return datetime.fromtimestamp(number, UTC).date().isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        pass
    text = str(value).strip()
    match = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](20\d{2})", text)
    if match:
        day, month, year = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    match = re.search(r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})", text)
    if match:
        year, month, day = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return text


def _first_ticker(text: str) -> str:
    for candidate in re.findall(r"\b[A-Z]{3,4}\b", str(text).upper()):
        if candidate not in {"CTCP", "HNX", "HOSE", "UPCOM", "ETF", "BCTC"}:
            return candidate
    return ""


def _first_date(text: str) -> str:
    match = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](20\d{2})", str(text))
    if not match:
        return ""
    day, month, year = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def _requires_js(text: str) -> bool:
    markers = ["__next", "window.", "document.", "javascript", "app-root"]
    schema = ["\"success\"", "\"data\"", "<table", "cong bo thong tin", "canh bao"]
    return sum(marker in text for marker in markers) >= 2 and not any(marker in text for marker in schema)


def _download_link_found(text: str) -> bool:
    return any(marker in text for marker in [".csv", ".xlsx", ".xls", ".pdf", "download"])


def _ticker_count(rows: list[dict[str, Any]]) -> int:
    return len({_clean_ticker(row.get("ticker")) for row in rows if _clean_ticker(row.get("ticker"))})


def _source_name(source: dict[str, Any], list_type: str) -> str:
    base = str(source.get("source_name", source.get("source_category", "")))
    return f"{base}:{str(list_type).lower()}"


def _join_unique(values: Any) -> str:
    result = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return ", ".join(result)


def _aggregate_confidence(values: Any) -> str:
    normalized = {str(value).strip().lower() for value in values if str(value).strip()}
    if "low" in normalized:
        return "low"
    if "medium" in normalized:
        return "medium"
    if "high" in normalized:
        return "high"
    return ""


def _ordered_tokens(values: list[str]) -> list[str]:
    result = []
    for value in values:
        for part in str(value).split(","):
            token = part.strip().lower()
            if token and token not in result:
                result.append(token)
    return result


def _ordered_tickers(values: list[str]) -> list[str]:
    result = []
    for value in values:
        for part in str(value).split(","):
            ticker = _clean_ticker(part)
            if ticker and ticker not in result:
                result.append(ticker)
    return result


def _clean_ticker(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def _sleep(seconds: float) -> None:
    if seconds and seconds > 0:
        time.sleep(float(seconds))
