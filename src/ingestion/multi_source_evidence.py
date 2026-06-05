"""Multi-source field evidence and deterministic reconciliation.

This module does not fetch live data. It reconciles already-ingested raw/manual
source rows into auditable evidence reports.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingestion.contracts import PROHIBITED_RECOMMENDATION_FIELDS

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None


DEFAULT_MULTI_SOURCE_REGISTRY_PATH = Path("config/multi_source_registry.yaml")
DEFAULT_SOURCE_PRIORITY_PATH = Path("config/source_priority.yaml")

SOURCE_AVAILABILITY_MATRIX_COLUMNS = [
    "dataset_name",
    "source_category",
    "source_names",
    "configured",
    "source_priority_rank",
    "row_count",
    "ticker_count",
    "latest_fetch_time",
    "has_source_url",
    "availability_status",
    "notes",
]

FIELD_LEVEL_EVIDENCE_COLUMNS = [
    "dataset_name",
    "record_key",
    "ticker",
    "field_name",
    "source_category",
    "source_name",
    "source_priority_rank",
    "value",
    "normalized_value",
    "source_url",
    "fetch_time",
    "confidence_raw",
    "evidence_status",
    "reconciliation_status",
    "notes",
]

RECONCILED_FIELD_COLUMNS = [
    "dataset_name",
    "record_key",
    "ticker",
    "field_name",
    "resolved_value",
    "resolved_source_category",
    "resolved_source_name",
    "source_count",
    "independent_source_category_count",
    "reconciliation_status",
    "confidence",
    "manual_review_required",
    "notes",
]

SOURCE_CONFLICT_REPORT_COLUMNS = [
    "dataset_name",
    "record_key",
    "ticker",
    "field_name",
    "observed_values",
    "source_categories",
    "source_names",
    "conflict_status",
    "manual_review_required",
    "notes",
]

UNRESOLVED_REQUIRED_FIELDS_COLUMNS = [
    "dataset_name",
    "record_key",
    "ticker",
    "field_name",
    "issue",
    "blocked_readiness",
    "manual_review_required",
    "evidence_status",
    "notes",
]

READINESS_STAGES = ["l0", "step18", "future_step19"]
LOW_CONFIDENCE_VALUES = {"low", "very_low", "mock"}


def load_multi_source_registry(
    path: str | Path = DEFAULT_MULTI_SOURCE_REGISTRY_PATH,
) -> dict[str, Any]:
    """Load the multi-source registry YAML."""

    return _load_yaml_mapping(path, "multi-source registry")


def load_source_priority_config(
    path: str | Path = DEFAULT_SOURCE_PRIORITY_PATH,
) -> dict[str, Any]:
    """Load source priority rules YAML."""

    return _load_yaml_mapping(path, "source priority config")


def validate_multi_source_registry(registry: dict[str, Any]) -> dict[str, Any]:
    """Validate registry shape and required source categories."""

    result = _validation_result()
    if not isinstance(registry, dict):
        result["is_valid"] = False
        result["errors"].append("Registry must be a mapping.")
        return result

    categories = registry.get("supported_source_categories")
    if not isinstance(categories, list) or not categories:
        result["errors"].append("supported_source_categories must be a non-empty list.")
        categories = []

    required = {
        "vnstock",
        "cafef",
        "vietstock",
        "hose",
        "hnx",
        "ssc",
        "manual_csv",
        "manual_xlsx",
        "annual_report_pdf_manual",
    }
    missing_required = sorted(required - {str(item) for item in categories})
    if missing_required:
        result["errors"].append(
            "Missing required source categories: " + ", ".join(missing_required)
        )

    sources = registry.get("sources")
    if not isinstance(sources, list) or not sources:
        result["errors"].append("sources must be a non-empty list.")
        sources = []

    configured_categories = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            result["errors"].append(f"source at index {index} must be a mapping.")
            continue
        category = str(source.get("source_category", "")).strip()
        configured_categories.add(category)
        for field in [
            "source_category",
            "display_name",
            "source_type",
            "reliability_level",
            "priority_tier",
            "live_fetch_allowed_by_default",
            "source_url_required",
            "aliases",
            "supported_datasets",
            "notes",
        ]:
            if field not in source:
                result["errors"].append(f"{category or index}: missing '{field}'.")
        if source.get("live_fetch_allowed_by_default") is not False:
            result["warnings"].append(
                f"{category}: live_fetch_allowed_by_default should be false."
            )

    missing_entries = sorted(set(categories) - configured_categories)
    if missing_entries:
        result["errors"].append(
            "Missing source entries for categories: " + ", ".join(missing_entries)
        )

    _finalize_validation(result)
    return result


def validate_source_priority_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validate source priority and required-field rules."""

    result = _validation_result()
    if not isinstance(config, dict):
        result["is_valid"] = False
        result["errors"].append("Source priority config must be a mapping.")
        return result

    default_priority = config.get("default_source_priority")
    if not isinstance(default_priority, list) or not default_priority:
        result["errors"].append("default_source_priority must be a non-empty list.")

    datasets = config.get("datasets")
    if not isinstance(datasets, dict) or not datasets:
        result["errors"].append("datasets must be a non-empty mapping.")
        datasets = {}

    for dataset_name, settings in datasets.items():
        if not isinstance(settings, dict):
            result["errors"].append(f"{dataset_name}: settings must be a mapping.")
            continue
        for field in ["key_columns", "source_priority", "evidence_fields", "required_fields"]:
            if field not in settings:
                result["errors"].append(f"{dataset_name}: missing '{field}'.")
        for list_field in ["key_columns", "source_priority", "evidence_fields"]:
            if not isinstance(settings.get(list_field), list) or not settings.get(list_field):
                result["errors"].append(
                    f"{dataset_name}: {list_field} must be a non-empty list."
                )
        required_fields = settings.get("required_fields")
        if not isinstance(required_fields, dict):
            result["errors"].append(f"{dataset_name}: required_fields must be a mapping.")
            continue
        for stage in READINESS_STAGES:
            if not isinstance(required_fields.get(stage), list):
                result["errors"].append(
                    f"{dataset_name}: required_fields.{stage} must be a list."
                )

    _finalize_validation(result)
    return result


def run_multi_source_evidence(
    *,
    raw_datasets: dict[str, pd.DataFrame | None],
    requested_tickers: list[str] | None = None,
    source_registry: dict[str, Any] | None = None,
    priority_config: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build field evidence, reconcile source values, and return reports."""

    if not isinstance(raw_datasets, dict):
        raise TypeError("raw_datasets must be a mapping of dataset name to DataFrame.")

    registry = source_registry or load_multi_source_registry()
    priority = priority_config or load_source_priority_config()
    registry_validation = validate_multi_source_registry(registry)
    priority_validation = validate_source_priority_config(priority)
    if not registry_validation["is_valid"]:
        raise ValueError("Invalid multi-source registry: " + "; ".join(registry_validation["errors"]))
    if not priority_validation["is_valid"]:
        raise ValueError("Invalid source priority config: " + "; ".join(priority_validation["errors"]))

    resolved_run_id = run_id or f"multi_source_evidence_{_safe_token(_utc_now_iso())}"
    tickers = _ordered_tickers(requested_tickers) or _infer_tickers(raw_datasets)

    availability = build_source_availability_matrix(
        raw_datasets=raw_datasets,
        registry=registry,
        priority_config=priority,
    )
    field_evidence = build_field_level_evidence(
        raw_datasets=raw_datasets,
        registry=registry,
        priority_config=priority,
    )
    reconciled, conflicts, unresolved = reconcile_field_evidence(
        raw_datasets=raw_datasets,
        field_evidence=field_evidence,
        requested_tickers=tickers,
        priority_config=priority,
    )
    field_evidence = _attach_reconciliation_status(field_evidence, reconciled, conflicts)
    decisions = build_datasource_decisions(
        requested_tickers=tickers,
        availability_matrix=availability,
        field_level_evidence=field_evidence,
        source_conflict_report=conflicts,
        unresolved_required_fields=unresolved,
    )
    summary = build_multi_source_summary(
        run_id=resolved_run_id,
        requested_tickers=tickers,
        availability_matrix=availability,
        field_level_evidence=field_evidence,
        source_conflict_report=conflicts,
        unresolved_required_fields=unresolved,
        decisions=decisions,
    )
    return {
        "run_id": resolved_run_id,
        "requested_tickers": tickers,
        "source_availability_matrix": availability,
        "field_level_evidence": field_evidence,
        "reconciled_fields": reconciled,
        "source_conflict_report": conflicts,
        "unresolved_required_fields": unresolved,
        "decisions": decisions,
        "summary": summary,
    }


def build_source_availability_matrix(
    *,
    raw_datasets: dict[str, pd.DataFrame | None],
    registry: dict[str, Any],
    priority_config: dict[str, Any],
) -> pd.DataFrame:
    """Return dataset/source availability without treating missing rows as clean."""

    dataset_names = list(priority_config.get("datasets", {}))
    categories = _registry_categories(registry)
    rows = []
    for dataset_name in dataset_names:
        df = raw_datasets.get(dataset_name)
        prepared = _prepare_source_frame(df, registry=registry)
        for category in categories:
            category_rows = (
                prepared[prepared["_source_category"] == category]
                if not prepared.empty
                else prepared
            )
            priority_rank = _source_priority_rank(
                priority_config,
                dataset_name=dataset_name,
                field_name="",
                source_category=category,
            )
            source_names = _join_unique(category_rows.get("_source_name", pd.Series(dtype=object)))
            row_count = int(len(category_rows))
            rows.append(
                {
                    "dataset_name": dataset_name,
                    "source_category": category,
                    "source_names": source_names,
                    "configured": category in _dataset_priority(priority_config, dataset_name, ""),
                    "source_priority_rank": priority_rank,
                    "row_count": row_count,
                    "ticker_count": _ticker_count(category_rows),
                    "latest_fetch_time": _latest_fetch_time(category_rows),
                    "has_source_url": _has_any_source_url(category_rows),
                    "availability_status": "AVAILABLE" if row_count else "NO_ROWS",
                    "notes": (
                        "source rows present"
                        if row_count
                        else "no rows from this source; missing data is not clean"
                    ),
                }
            )
    return pd.DataFrame(rows, columns=SOURCE_AVAILABILITY_MATRIX_COLUMNS)


def build_field_level_evidence(
    *,
    raw_datasets: dict[str, pd.DataFrame | None],
    registry: dict[str, Any],
    priority_config: dict[str, Any],
) -> pd.DataFrame:
    """Build one evidence row per non-missing source-provided field value."""

    rows: list[dict[str, Any]] = []
    for dataset_name, settings in priority_config.get("datasets", {}).items():
        df = _prepare_source_frame(raw_datasets.get(dataset_name), registry=registry)
        if df.empty:
            continue
        key_columns = list(settings.get("key_columns", []))
        evidence_fields = list(settings.get("evidence_fields", []))
        for _, row in df.iterrows():
            record_key = _record_key(row, key_columns)
            ticker = _clean_ticker(row.get("ticker"))
            source_category = _clean_text(row.get("_source_category"))
            source_name = _clean_text(row.get("_source_name"))
            for field in evidence_fields:
                value = row.get(field)
                if _is_missing(value):
                    continue
                rows.append(
                    {
                        "dataset_name": dataset_name,
                        "record_key": record_key,
                        "ticker": ticker,
                        "field_name": field,
                        "source_category": source_category,
                        "source_name": source_name,
                        "source_priority_rank": _source_priority_rank(
                            priority_config,
                            dataset_name=dataset_name,
                            field_name=field,
                            source_category=source_category,
                        ),
                        "value": _stringify_value(value),
                        "normalized_value": _normalize_value(value),
                        "source_url": _clean_text(row.get("source_url")),
                        "fetch_time": _clean_text(row.get("fetch_time")),
                        "confidence_raw": _clean_text(row.get("confidence_raw")),
                        "evidence_status": "EVIDENCE_AVAILABLE",
                        "reconciliation_status": "PENDING_RECONCILIATION",
                        "notes": _clean_text(row.get("notes")),
                    }
                )
    return pd.DataFrame(rows, columns=FIELD_LEVEL_EVIDENCE_COLUMNS)


def reconcile_field_evidence(
    *,
    raw_datasets: dict[str, pd.DataFrame | None],
    field_evidence: pd.DataFrame,
    requested_tickers: list[str],
    priority_config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Reconcile required fields deterministically and report gaps/conflicts."""

    reconciled_rows: list[dict[str, Any]] = []
    conflict_rows: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, Any]] = []

    evidence = (
        field_evidence
        if isinstance(field_evidence, pd.DataFrame)
        else pd.DataFrame(columns=FIELD_LEVEL_EVIDENCE_COLUMNS)
    )

    for dataset_name, settings in priority_config.get("datasets", {}).items():
        dataset_evidence = evidence[evidence["dataset_name"] == dataset_name]
        records_to_check = _records_to_check(
            dataset_name=dataset_name,
            raw_df=raw_datasets.get(dataset_name),
            requested_tickers=requested_tickers,
            settings=settings,
        )
        required_by_stage = settings.get("required_fields", {})
        required_fields = _dedupe(
            [
                field
                for stage in READINESS_STAGES
                for field in required_by_stage.get(stage, [])
            ]
        )

        for record in records_to_check:
            if record.get("issue") == "DISCLOSURE_DATA_UNAVAILABLE":
                unresolved_rows.append(
                    _unresolved_row(
                        dataset_name=dataset_name,
                        record_key=record["record_key"],
                        ticker=record["ticker"],
                        field_name="disclosure_status",
                        issue="DISCLOSURE_DATA_UNAVAILABLE",
                        blocked_readiness="l0|step18|future_step19",
                        notes="no disclosure row exists for ticker; absence is unknown/unavailable, not clean",
                    )
                )
                continue

            for field_name in required_fields:
                subset = dataset_evidence[
                    (dataset_evidence["record_key"] == record["record_key"])
                    & (dataset_evidence["field_name"] == field_name)
                ]
                blocked = _blocked_readiness_for_field(required_by_stage, field_name)
                if subset.empty:
                    unresolved_rows.append(
                        _unresolved_row(
                            dataset_name=dataset_name,
                            record_key=record["record_key"],
                            ticker=record["ticker"],
                            field_name=field_name,
                            issue="MISSING_REQUIRED_FIELD",
                            blocked_readiness=blocked,
                            notes="no source evidence for required field; value remains missing",
                        )
                    )
                    continue

                values = list(subset["value"])
                tolerance_pct = float(
                    settings.get(
                        "numeric_tolerance_pct",
                        priority_config.get("default_numeric_tolerance_pct", 0.01),
                    )
                )
                if _has_conflicting_values(values, tolerance_pct):
                    conflict_rows.append(
                        {
                            "dataset_name": dataset_name,
                            "record_key": record["record_key"],
                            "ticker": record["ticker"],
                            "field_name": field_name,
                            "observed_values": _join_unique(subset["value"]),
                            "source_categories": _join_unique(subset["source_category"]),
                            "source_names": _join_unique(subset["source_name"]),
                            "conflict_status": "DATA_CONFLICT_MANUAL_REVIEW",
                            "manual_review_required": True,
                            "notes": "conflicting source values; no silent overwrite applied",
                        }
                    )
                    unresolved_rows.append(
                        _unresolved_row(
                            dataset_name=dataset_name,
                            record_key=record["record_key"],
                            ticker=record["ticker"],
                            field_name=field_name,
                            issue="DATA_CONFLICT",
                            blocked_readiness=blocked,
                            notes="source conflict blocks readiness until manual review",
                        )
                    )
                    continue

                best = _best_evidence_row(subset)
                source_categories = set(subset["source_category"].astype(str))
                confidence = _resolved_confidence(subset)
                reconciled_rows.append(
                    {
                        "dataset_name": dataset_name,
                        "record_key": record["record_key"],
                        "ticker": record["ticker"],
                        "field_name": field_name,
                        "resolved_value": best.get("value", ""),
                        "resolved_source_category": best.get("source_category", ""),
                        "resolved_source_name": best.get("source_name", ""),
                        "source_count": int(len(subset)),
                        "independent_source_category_count": int(len(source_categories)),
                        "reconciliation_status": (
                            "RESOLVED_BY_MULTISOURCE_AGREEMENT"
                            if len(source_categories) > 1
                            else "RESOLVED_BY_SINGLE_SOURCE"
                        ),
                        "confidence": confidence,
                        "manual_review_required": confidence == "low",
                        "notes": (
                            "same value confirmed by multiple source categories"
                            if len(source_categories) > 1
                            else "single-source evidence only"
                        ),
                    }
                )

    reconciled = pd.DataFrame(reconciled_rows, columns=RECONCILED_FIELD_COLUMNS)
    conflicts = pd.DataFrame(conflict_rows, columns=SOURCE_CONFLICT_REPORT_COLUMNS)
    unresolved = pd.DataFrame(
        unresolved_rows,
        columns=UNRESOLVED_REQUIRED_FIELDS_COLUMNS,
    )
    return reconciled, conflicts, unresolved


def build_datasource_decisions(
    *,
    requested_tickers: list[str],
    availability_matrix: pd.DataFrame,
    field_level_evidence: pd.DataFrame,
    source_conflict_report: pd.DataFrame,
    unresolved_required_fields: pd.DataFrame,
) -> dict[str, Any]:
    """Build readiness decisions for finance/disclosure evidence."""

    unresolved = _ensure_frame(unresolved_required_fields, UNRESOLVED_REQUIRED_FIELDS_COLUMNS)
    conflicts = _ensure_frame(source_conflict_report, SOURCE_CONFLICT_REPORT_COLUMNS)
    availability = _ensure_frame(availability_matrix, SOURCE_AVAILABILITY_MATRIX_COLUMNS)

    finance_unresolved = _dataset_count(unresolved, "financial_statement_summary")
    disclosure_unresolved = _dataset_count(unresolved, "disclosure_status")
    finance_conflicts = _dataset_count(conflicts, "financial_statement_summary")
    disclosure_conflicts = _dataset_count(conflicts, "disclosure_status")
    finance_available_sources = _available_source_count(availability, "financial_statement_summary")
    disclosure_available_sources = _available_source_count(availability, "disclosure_status")

    finance_ready = finance_unresolved == 0 and finance_conflicts == 0 and finance_available_sources > 0
    disclosure_ready = (
        disclosure_unresolved == 0
        and disclosure_conflicts == 0
        and disclosure_available_sources > 0
    )
    finance_disclosure_ready = finance_ready and disclosure_ready

    return {
        "requested_ticker_count": int(len(requested_tickers)),
        "finance_ready_for_l0": finance_ready,
        "disclosure_ready_for_l0": disclosure_ready,
        "finance_disclosure_ready_for_l0": finance_disclosure_ready,
        "finance_disclosure_ready_for_step18": finance_disclosure_ready,
        "finance_disclosure_ready_for_future_step19": finance_disclosure_ready,
        "finance_unresolved_required_fields": int(finance_unresolved),
        "disclosure_unresolved_required_fields": int(disclosure_unresolved),
        "finance_conflict_count": int(finance_conflicts),
        "disclosure_conflict_count": int(disclosure_conflicts),
        "manual_review_required": bool(
            finance_unresolved
            or disclosure_unresolved
            or finance_conflicts
            or disclosure_conflicts
        ),
        "step19_implemented": False,
        "next_action": _next_action(
            finance_ready=finance_ready,
            disclosure_ready=disclosure_ready,
            disclosure_available_sources=disclosure_available_sources,
        ),
    }


def build_multi_source_summary(
    *,
    run_id: str,
    requested_tickers: list[str],
    availability_matrix: pd.DataFrame,
    field_level_evidence: pd.DataFrame,
    source_conflict_report: pd.DataFrame,
    unresolved_required_fields: pd.DataFrame,
    decisions: dict[str, Any],
) -> dict[str, Any]:
    """Return an auditable summary dictionary for markdown reports."""

    return {
        "run_id": run_id,
        "run_type": "REAL-DATA-01F_MULTI_SOURCE_EVIDENCE",
        "started_at": "",
        "finished_at": _utc_now_iso(),
        "requested_ticker_count": int(len(requested_tickers)),
        "ticker_list": requested_tickers,
        "source_category_count": int(
            availability_matrix["source_category"].nunique()
            if "source_category" in availability_matrix.columns
            else 0
        ),
        "available_source_dataset_pairs": int(
            (availability_matrix["availability_status"] == "AVAILABLE").sum()
            if "availability_status" in availability_matrix.columns
            else 0
        ),
        "field_level_evidence_rows": int(len(field_level_evidence)),
        "source_conflict_rows": int(len(source_conflict_report)),
        "unresolved_required_field_rows": int(len(unresolved_required_fields)),
        "decisions": decisions,
        "output_contains_mock_sample": False,
        "step19_implemented": False,
    }


def save_multi_source_evidence_reports(
    *,
    result: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, str]:
    """Write required DATA-SOURCE-02 reports."""

    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)

    outputs = {
        "source_availability_matrix": path / "source_availability_matrix.csv",
        "field_level_evidence": path / "field_level_evidence.csv",
        "source_conflict_report": path / "source_conflict_report.csv",
        "unresolved_required_fields": path / "unresolved_required_fields.csv",
        "multi_source_run_summary": path / "multi_source_run_summary.md",
        "datasource_decision_report": path / "datasource_decision_report.md",
    }

    result["source_availability_matrix"].to_csv(
        outputs["source_availability_matrix"], index=False
    )
    result["field_level_evidence"].to_csv(outputs["field_level_evidence"], index=False)
    result["source_conflict_report"].to_csv(outputs["source_conflict_report"], index=False)
    result["unresolved_required_fields"].to_csv(
        outputs["unresolved_required_fields"], index=False
    )
    outputs["multi_source_run_summary"].write_text(
        multi_source_run_summary_markdown(result["summary"]),
        encoding="utf-8",
    )
    outputs["datasource_decision_report"].write_text(
        datasource_decision_report_markdown(result["decisions"]),
        encoding="utf-8",
    )
    return {name: str(report_path) for name, report_path in outputs.items()}


def multi_source_run_summary_markdown(summary: dict[str, Any]) -> str:
    """Render run summary markdown."""

    decisions = summary.get("decisions", {})
    lines = [
        "# Multi-source Evidence Run Summary",
        "",
        f"- run_id: {summary.get('run_id', '')}",
        f"- run_type: {summary.get('run_type', '')}",
        f"- finished_at: {summary.get('finished_at', '')}",
        f"- requested_ticker_count: {summary.get('requested_ticker_count', 0)}",
        f"- ticker_list: {', '.join(summary.get('ticker_list', []))}",
        f"- source_category_count: {summary.get('source_category_count', 0)}",
        f"- available_source_dataset_pairs: {summary.get('available_source_dataset_pairs', 0)}",
        f"- field_level_evidence_rows: {summary.get('field_level_evidence_rows', 0)}",
        f"- source_conflict_rows: {summary.get('source_conflict_rows', 0)}",
        f"- unresolved_required_field_rows: {summary.get('unresolved_required_field_rows', 0)}",
        f"- finance_ready_for_l0: {decisions.get('finance_ready_for_l0', False)}",
        f"- disclosure_ready_for_l0: {decisions.get('disclosure_ready_for_l0', False)}",
        f"- finance_disclosure_ready_for_step18: {decisions.get('finance_disclosure_ready_for_step18', False)}",
        f"- finance_disclosure_ready_for_future_step19: {decisions.get('finance_disclosure_ready_for_future_step19', False)}",
        f"- output_contains_mock_sample: {summary.get('output_contains_mock_sample', False)}",
        f"- step19_implemented: {summary.get('step19_implemented', False)}",
        "",
        "## Guardrails",
        "",
        "- This layer reconciles already-ingested evidence only.",
        "- Missing values remain missing.",
        "- Conflicting values require manual review.",
        "- Missing disclosure rows are unknown/unavailable, not clean.",
        "",
    ]
    return "\n".join(lines)


def datasource_decision_report_markdown(decisions: dict[str, Any]) -> str:
    """Render data-source readiness decisions."""

    lines = [
        "# Data Source Decision Report",
        "",
        f"- requested_ticker_count: {decisions.get('requested_ticker_count', 0)}",
        f"- finance_ready_for_l0: {decisions.get('finance_ready_for_l0', False)}",
        f"- disclosure_ready_for_l0: {decisions.get('disclosure_ready_for_l0', False)}",
        f"- finance_disclosure_ready_for_l0: {decisions.get('finance_disclosure_ready_for_l0', False)}",
        f"- finance_disclosure_ready_for_step18: {decisions.get('finance_disclosure_ready_for_step18', False)}",
        f"- finance_disclosure_ready_for_future_step19: {decisions.get('finance_disclosure_ready_for_future_step19', False)}",
        f"- finance_unresolved_required_fields: {decisions.get('finance_unresolved_required_fields', 0)}",
        f"- disclosure_unresolved_required_fields: {decisions.get('disclosure_unresolved_required_fields', 0)}",
        f"- finance_conflict_count: {decisions.get('finance_conflict_count', 0)}",
        f"- disclosure_conflict_count: {decisions.get('disclosure_conflict_count', 0)}",
        f"- manual_review_required: {decisions.get('manual_review_required', True)}",
        f"- step19_implemented: {decisions.get('step19_implemented', False)}",
        f"- next_action: {decisions.get('next_action', '')}",
        "",
        "## Decision",
        "",
    ]
    if decisions.get("finance_disclosure_ready_for_l0"):
        lines.append("Finance/disclosure evidence is ready for L0 and Step 18 evidence use.")
    else:
        lines.append(
            "Finance/disclosure evidence is not ready for L0, Step 18, or future Step 19."
        )
        lines.append(
            "Use source-backed manual CSV/XLSX for the 20 representative tickers before scaling."
        )
    lines.extend(
        [
            "",
            "No missing financial values were filled. No missing disclosure row was treated as clean.",
            "",
        ]
    )
    return "\n".join(lines)


def has_prohibited_recommendation_columns(df: pd.DataFrame) -> bool:
    """Return True when a generated CSV report contains prohibited columns."""

    normalized_columns = {str(column).strip().lower() for column in df.columns}
    return bool(PROHIBITED_RECOMMENDATION_FIELDS.intersection(normalized_columns))


def _records_to_check(
    *,
    dataset_name: str,
    raw_df: pd.DataFrame | None,
    requested_tickers: list[str],
    settings: dict[str, Any],
) -> list[dict[str, str]]:
    key_columns = list(settings.get("key_columns", []))
    df = raw_df if isinstance(raw_df, pd.DataFrame) else pd.DataFrame()
    records: list[dict[str, str]] = []
    seen_keys = set()
    ticker_rows = set()

    if isinstance(df, pd.DataFrame) and not df.empty:
        for _, row in df.iterrows():
            ticker = _clean_ticker(row.get("ticker"))
            if ticker:
                ticker_rows.add(ticker)
            record_key = _record_key(row, key_columns)
            if record_key in seen_keys:
                continue
            seen_keys.add(record_key)
            records.append({"record_key": record_key, "ticker": ticker})

    if dataset_name == "disclosure_status" and settings.get("requires_evidence_row_per_ticker"):
        for ticker in requested_tickers:
            clean = _clean_ticker(ticker)
            if clean in ticker_rows:
                continue
            records.append(
                {
                    "record_key": f"ticker={clean}",
                    "ticker": clean,
                    "issue": "DISCLOSURE_DATA_UNAVAILABLE",
                }
            )
        return records

    for ticker in requested_tickers:
        clean = _clean_ticker(ticker)
        if clean in ticker_rows:
            continue
        fallback_key = f"ticker={clean}"
        if "period" in key_columns:
            fallback_key += "|period="
        records.append({"record_key": fallback_key, "ticker": clean})

    return records


def _attach_reconciliation_status(
    field_evidence: pd.DataFrame,
    reconciled: pd.DataFrame,
    conflicts: pd.DataFrame,
) -> pd.DataFrame:
    if field_evidence.empty:
        return field_evidence.copy()

    output = field_evidence.copy()
    resolved_keys = {
        (row["dataset_name"], row["record_key"], row["field_name"]): row[
            "reconciliation_status"
        ]
        for _, row in reconciled.iterrows()
    }
    conflict_keys = {
        (row["dataset_name"], row["record_key"], row["field_name"])
        for _, row in conflicts.iterrows()
    }
    statuses = []
    for _, row in output.iterrows():
        key = (row["dataset_name"], row["record_key"], row["field_name"])
        if key in conflict_keys:
            statuses.append("UNRESOLVED_CONFLICT")
        else:
            statuses.append(resolved_keys.get(key, "NOT_REQUIRED_FOR_RECONCILIATION"))
    output["reconciliation_status"] = statuses
    return output


def _best_evidence_row(subset: pd.DataFrame) -> dict[str, Any]:
    sorted_subset = subset.sort_values(
        by=["source_priority_rank", "fetch_time", "source_name"],
        ascending=[True, False, True],
        kind="mergesort",
    )
    return sorted_subset.iloc[0].to_dict()


def _resolved_confidence(subset: pd.DataFrame) -> str:
    raw_values = {str(value).strip().lower() for value in subset["confidence_raw"]}
    if raw_values.intersection(LOW_CONFIDENCE_VALUES):
        return "low"
    if subset["source_category"].nunique() > 1:
        return "high"
    return "medium"


def _unresolved_row(
    *,
    dataset_name: str,
    record_key: str,
    ticker: str,
    field_name: str,
    issue: str,
    blocked_readiness: str,
    notes: str,
) -> dict[str, Any]:
    return {
        "dataset_name": dataset_name,
        "record_key": record_key,
        "ticker": ticker,
        "field_name": field_name,
        "issue": issue,
        "blocked_readiness": blocked_readiness,
        "manual_review_required": True,
        "evidence_status": "UNRESOLVED",
        "notes": notes,
    }


def _blocked_readiness_for_field(required_by_stage: dict[str, list[str]], field_name: str) -> str:
    stages = [
        stage
        for stage in READINESS_STAGES
        if field_name in required_by_stage.get(stage, [])
    ]
    return "|".join(stages)


def _prepare_source_frame(
    df: pd.DataFrame | None,
    *,
    registry: dict[str, Any],
) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    output = df.copy()
    source_names = []
    source_categories = []
    for _, row in output.iterrows():
        source_name = _source_name_from_row(row)
        source_category = infer_source_category(
            source_name=source_name,
            registry=registry,
            explicit_category=row.get("source_category"),
        )
        source_names.append(source_name)
        source_categories.append(source_category)
    output["_source_name"] = source_names
    output["_source_category"] = source_categories
    return output


def infer_source_category(
    *,
    source_name: Any,
    registry: dict[str, Any],
    explicit_category: Any = None,
) -> str:
    """Infer source category from explicit category, aliases, or source text."""

    explicit = _clean_text(explicit_category)
    categories = _registry_categories(registry)
    if explicit in categories:
        return explicit

    source_text = _clean_text(source_name).lower()
    for source in registry.get("sources", []):
        category = _clean_text(source.get("source_category"))
        aliases = [
            _clean_text(alias).lower()
            for alias in source.get("aliases", [])
            if _clean_text(alias)
        ]
        if source_text == category or any(alias and alias in source_text for alias in aliases):
            return category
    return "unknown"


def _source_name_from_row(row: pd.Series) -> str:
    for column in ["source", "data_source", "source_name"]:
        value = row.get(column)
        if not _is_missing(value):
            return _clean_text(value)
    return "unknown"


def _record_key(row: pd.Series, key_columns: list[str]) -> str:
    pairs = []
    for column in key_columns:
        pairs.append(f"{column}={_clean_text(row.get(column))}")
    return "|".join(pairs)


def _source_priority_rank(
    priority_config: dict[str, Any],
    *,
    dataset_name: str,
    field_name: str,
    source_category: str,
) -> int:
    priority = _dataset_priority(priority_config, dataset_name, field_name)
    try:
        return int(priority.index(source_category) + 1)
    except ValueError:
        return 999


def _dataset_priority(
    priority_config: dict[str, Any],
    dataset_name: str,
    field_name: str,
) -> list[str]:
    dataset = priority_config.get("datasets", {}).get(dataset_name, {})
    overrides = dataset.get("field_priority_overrides", {})
    if field_name and isinstance(overrides, dict) and field_name in overrides:
        return list(overrides[field_name])
    if isinstance(dataset.get("source_priority"), list):
        return list(dataset["source_priority"])
    return list(priority_config.get("default_source_priority", []))


def _has_conflicting_values(values: list[Any], tolerance_pct: float) -> bool:
    non_missing = [value for value in values if not _is_missing(value)]
    if len(non_missing) < 2:
        return False
    numeric_values = pd.to_numeric(pd.Series(non_missing), errors="coerce")
    if not numeric_values.isna().any():
        min_value = float(numeric_values.min())
        max_value = float(numeric_values.max())
        denominator = max(abs(max_value), abs(min_value), 1.0)
        return ((max_value - min_value) / denominator) > tolerance_pct
    normalized = {_normalize_value(value) for value in non_missing}
    return len(normalized) > 1


def _normalize_value(value: Any) -> str:
    if _is_missing(value):
        return ""
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if not pd.isna(numeric):
        return f"{float(numeric):.10g}"
    return " ".join(str(value).strip().lower().split())


def _stringify_value(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value)


def _registry_categories(registry: dict[str, Any]) -> list[str]:
    categories = registry.get("supported_source_categories", [])
    return [str(category).strip() for category in categories if str(category).strip()]


def _infer_tickers(raw_datasets: dict[str, pd.DataFrame | None]) -> list[str]:
    tickers: list[str] = []
    for df in raw_datasets.values():
        if not isinstance(df, pd.DataFrame) or "ticker" not in df.columns:
            continue
        for value in df["ticker"]:
            ticker = _clean_ticker(value)
            if ticker and ticker not in tickers:
                tickers.append(ticker)
    return tickers


def _ordered_tickers(values: list[str] | None) -> list[str]:
    tickers: list[str] = []
    for value in values or []:
        ticker = _clean_ticker(value)
        if ticker and ticker not in tickers:
            tickers.append(ticker)
    return tickers


def _ticker_count(df: pd.DataFrame) -> int:
    if not isinstance(df, pd.DataFrame) or df.empty or "ticker" not in df.columns:
        return 0
    values = df["ticker"].map(_clean_ticker)
    return int(values[values != ""].nunique())


def _latest_fetch_time(df: pd.DataFrame) -> str:
    if not isinstance(df, pd.DataFrame) or df.empty or "fetch_time" not in df.columns:
        return ""
    values = [_clean_text(value) for value in df["fetch_time"] if not _is_missing(value)]
    return max(values) if values else ""


def _has_any_source_url(df: pd.DataFrame) -> bool:
    if not isinstance(df, pd.DataFrame) or df.empty or "source_url" not in df.columns:
        return False
    return bool(df["source_url"].map(lambda value: not _is_missing(value)).any())


def _available_source_count(availability: pd.DataFrame, dataset_name: str) -> int:
    if availability.empty:
        return 0
    rows = availability[
        (availability["dataset_name"] == dataset_name)
        & (availability["availability_status"] == "AVAILABLE")
    ]
    return int(len(rows))


def _dataset_count(df: pd.DataFrame, dataset_name: str) -> int:
    if not isinstance(df, pd.DataFrame) or df.empty or "dataset_name" not in df.columns:
        return 0
    return int((df["dataset_name"] == dataset_name).sum())


def _next_action(
    *,
    finance_ready: bool,
    disclosure_ready: bool,
    disclosure_available_sources: int,
) -> str:
    if finance_ready and disclosure_ready:
        return "READY_FOR_MEDIUM_RUN_EVIDENCE_CHECK_ONLY"
    if not disclosure_available_sources:
        return "USE_SOURCE_BACKED_MANUAL_CSV_XLSX_FOR_REPRESENTATIVE_20"
    return "FIX_UNRESOLVED_FINANCE_DISCLOSURE_EVIDENCE_BEFORE_SCALING"


def _ensure_frame(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if isinstance(df, pd.DataFrame):
        return df
    return pd.DataFrame(columns=columns)


def _join_unique(values: Any) -> str:
    if not isinstance(values, pd.Series):
        values = pd.Series(list(values) if isinstance(values, list | tuple | set) else [])
    cleaned = []
    for value in values:
        text = _clean_text(value)
        if text and text not in cleaned:
            cleaned.append(text)
    return "|".join(cleaned)


def _validation_result() -> dict[str, Any]:
    return {"is_valid": True, "errors": [], "warnings": []}


def _finalize_validation(result: dict[str, Any]) -> None:
    result["errors"] = _dedupe(result["errors"])
    result["warnings"] = _dedupe(result["warnings"])
    result["is_valid"] = not result["errors"]


def _load_yaml_mapping(path: str | Path, label: str) -> dict[str, Any]:
    if yaml is None:
        raise ImportError("PyYAML is required to load YAML config files.")
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain a YAML mapping.")
    return data


def _is_missing(value: Any) -> bool:
    if isinstance(value, list) or isinstance(value, tuple) or isinstance(value, set):
        return len(value) == 0
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        return False
    return isinstance(value, str) and not value.strip()


def _clean_ticker(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip().upper()


def _clean_text(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip()


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(values))


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _safe_token(value: Any) -> str:
    token = str(value).replace(":", "").replace("+", "").replace("-", "")
    return "".join(character if character.isalnum() else "_" for character in token)


def to_json(value: Any) -> str:
    """Return stable JSON text for diagnostics and tests."""

    return json.dumps(value, sort_keys=True, ensure_ascii=True)
