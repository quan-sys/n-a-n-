"""Diagnostics and report helpers for REAL-DATA-01G source adapters."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingestion.finance_statement_mapper import CANONICAL_FINANCIAL_COLUMNS
from src.ingestion.real_source_adapters import DISCLOSURE_TEMPLATE_COLUMNS
from src.ingestion.source_adapter_contracts import (
    DISCLOSURE_CANDIDATE_COLUMNS,
    FINANCE_CANDIDATE_COLUMNS,
    FINANCE_CANONICAL_FIELDS,
    SOURCE_ADAPTER_DIAGNOSTIC_COLUMNS,
    SOURCE_PROBE_COLUMNS,
    SOURCE_SCHEMA_DIAGNOSTIC_COLUMNS,
    empty_disclosure_candidates,
    empty_finance_candidates,
)

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None


DEFAULT_ADAPTER_REGISTRY_PATH = Path("config/source_adapter_registry.yaml")


def load_source_adapter_registry(
    path: str | Path = DEFAULT_ADAPTER_REGISTRY_PATH,
) -> dict[str, Any]:
    """Load source adapter registry YAML."""

    if yaml is None:
        raise ImportError("PyYAML is required to load adapter registry.")
    registry_path = Path(path)
    with registry_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise ValueError("source adapter registry must contain a YAML mapping.")
    return data


def validate_source_adapter_registry(registry: dict[str, Any]) -> dict[str, Any]:
    result = {"is_valid": True, "errors": [], "warnings": []}
    adapters = registry.get("adapters") if isinstance(registry, dict) else None
    if not isinstance(adapters, list) or not adapters:
        result["errors"].append("adapters must be a non-empty list.")
        result["is_valid"] = False
        return result
    for index, adapter in enumerate(adapters):
        if not isinstance(adapter, dict):
            result["errors"].append(f"adapter at index {index} must be a mapping.")
            continue
        for field in [
            "adapter_name",
            "class_path",
            "source_category",
            "supported_datasets",
            "live_fetch_allowed_when_explicit",
            "notes",
        ]:
            if field not in adapter:
                result["errors"].append(f"{adapter.get('adapter_name', index)}: missing {field}.")
        if adapter.get("live_fetch_allowed_when_explicit") is not True:
            result["warnings"].append(
                f"{adapter.get('adapter_name', index)}: live fetch is not explicitly enabled."
            )
    result["errors"] = list(dict.fromkeys(result["errors"]))
    result["warnings"] = list(dict.fromkeys(result["warnings"]))
    result["is_valid"] = not result["errors"]
    return result


def instantiate_adapters(
    *,
    adapter_registry: dict[str, Any],
    probe_targets: dict[str, Any],
    source_names: list[str],
    http_get: Any,
    request_sleep_seconds: float,
) -> list[Any]:
    """Instantiate requested adapters from registry and target config."""

    target_sources = probe_targets.get("sources", {}) if isinstance(probe_targets, dict) else {}
    request_defaults = probe_targets.get("request_defaults", {}) if isinstance(probe_targets, dict) else {}
    adapters = []
    requested = {source.strip().lower() for source in source_names if source.strip()}
    for adapter_config in adapter_registry.get("adapters", []):
        adapter_name = str(adapter_config.get("adapter_name", "")).strip().lower()
        if requested and adapter_name not in requested:
            continue
        class_path = str(adapter_config.get("class_path", "")).strip()
        cls = _load_class(class_path)
        source_config = dict(target_sources.get(adapter_name, {}))
        source_config["request_defaults"] = request_defaults
        adapters.append(
            cls(
                config=source_config,
                http_get=http_get,
                request_sleep_seconds=request_sleep_seconds,
            )
        )
    return adapters


def finance_candidates_to_wide(finance_candidates: pd.DataFrame) -> pd.DataFrame:
    """Convert long-form finance candidate rows to 01F wide raw rows."""

    if not isinstance(finance_candidates, pd.DataFrame) or finance_candidates.empty:
        return pd.DataFrame(columns=[*CANONICAL_FINANCIAL_COLUMNS, "source_category", "source_name"])
    rows = []
    group_columns = ["ticker", "period", "period_type", "source_category", "source_name", "source_url"]
    for key, group in finance_candidates.groupby(group_columns, dropna=False):
        ticker, period, period_type, source_category, source_name, source_url = key
        row = {
            "ticker": ticker,
            "period": period,
            "period_type": period_type,
            "source": source_name,
            "source_category": source_category,
            "source_name": source_name,
            "source_url": source_url,
            "fetch_time": _latest(group, "fetch_time"),
            "confidence_raw": _confidence(group),
            "notes": "candidate rows parsed by REAL-DATA-01G; missing fields remain missing",
        }
        for field_name in FINANCE_CANONICAL_FIELDS:
            field_rows = group[group["field_name"] == field_name]
            row[field_name] = pd.NA if field_rows.empty else field_rows.iloc[0]["value"]
        rows.append(row)
    columns = [*CANONICAL_FINANCIAL_COLUMNS, "source_category", "source_name"]
    return pd.DataFrame(rows, columns=columns)


def disclosure_candidates_to_raw(disclosure_candidates: pd.DataFrame) -> pd.DataFrame:
    """Convert disclosure candidate rows to 01F raw disclosure schema."""

    if not isinstance(disclosure_candidates, pd.DataFrame) or disclosure_candidates.empty:
        return pd.DataFrame(columns=[*DISCLOSURE_TEMPLATE_COLUMNS, "source_category", "source_name"])
    output = disclosure_candidates.copy()
    output["source"] = output["source_name"]
    output["notes"] = output["notes"].astype(str)
    columns = [*DISCLOSURE_TEMPLATE_COLUMNS, "source_category", "source_name"]
    for column in columns:
        if column not in output.columns:
            output[column] = ""
    return output[columns]


def build_finance_field_coverage_by_source(finance_candidates: pd.DataFrame) -> pd.DataFrame:
    """Summarize finance candidate field coverage by source."""

    columns = [
        "source_category",
        "source_name",
        "field_name",
        "row_count",
        "ticker_count",
        "period_count",
        "notes",
    ]
    if not isinstance(finance_candidates, pd.DataFrame) or finance_candidates.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for (category, name, field), group in finance_candidates.groupby(
        ["source_category", "source_name", "field_name"],
        dropna=False,
    ):
        rows.append(
            {
                "source_category": category,
                "source_name": name,
                "field_name": field,
                "row_count": int(len(group)),
                "ticker_count": int(group["ticker"].nunique()),
                "period_count": int(group["period"].nunique()),
                "notes": "source-provided candidate values only",
            }
        )
    return pd.DataFrame(rows, columns=columns)


def build_disclosure_coverage_by_source(disclosure_candidates: pd.DataFrame) -> pd.DataFrame:
    """Summarize disclosure candidate coverage by source."""

    columns = [
        "source_category",
        "source_name",
        "event_type",
        "severity",
        "row_count",
        "ticker_count",
        "notes",
    ]
    if not isinstance(disclosure_candidates, pd.DataFrame) or disclosure_candidates.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for (category, name, event_type, severity), group in disclosure_candidates.groupby(
        ["source_category", "source_name", "event_type", "severity"],
        dropna=False,
    ):
        rows.append(
            {
                "source_category": category,
                "source_name": name,
                "event_type": event_type,
                "severity": severity,
                "row_count": int(len(group)),
                "ticker_count": int(group["ticker"].nunique()),
                "notes": "regulatory/warning candidate rows only",
            }
        )
    return pd.DataFrame(rows, columns=columns)


def build_comparison_vs_01f(
    *,
    previous_dir: str | Path,
    current_dir: str | Path,
    current_decisions: dict[str, Any],
) -> str:
    """Build markdown comparison between 01F and current 01G evidence reports."""

    prev = _load_report_metrics(Path(previous_dir))
    current = _load_report_metrics(Path(current_dir))
    lines = [
        "# Comparison vs REAL-DATA-01F",
        "",
        f"- previous_dir: {previous_dir}",
        f"- current_dir: {current_dir}",
        "",
        "| Metric | 01F | 01G |",
        "| --- | ---: | ---: |",
        f"| source categories with >0 rows | {prev['source_categories_with_rows']} | {current['source_categories_with_rows']} |",
        f"| finance source categories with >0 rows | {prev['finance_source_categories_with_rows']} | {current['finance_source_categories_with_rows']} |",
        f"| disclosure source categories with >0 rows | {prev['disclosure_source_categories_with_rows']} | {current['disclosure_source_categories_with_rows']} |",
        f"| field_level_evidence row count | {prev['field_level_evidence_rows']} | {current['field_level_evidence_rows']} |",
        f"| source_conflict row count | {prev['source_conflict_rows']} | {current['source_conflict_rows']} |",
        f"| unresolved_required_fields row count | {prev['unresolved_required_fields_rows']} | {current['unresolved_required_fields_rows']} |",
        f"| finance unresolved count | {prev['finance_unresolved_count']} | {current['finance_unresolved_count']} |",
        f"| disclosure unresolved count | {prev['disclosure_unresolved_count']} | {current['disclosure_unresolved_count']} |",
        "",
        "## Readiness",
        "",
        f"- finance_ready_for_l0 before/after: {prev['finance_ready_for_l0']} -> {current_decisions.get('finance_ready_for_l0', False)}",
        f"- disclosure_ready_for_l0 before/after: {prev['disclosure_ready_for_l0']} -> {current_decisions.get('disclosure_ready_for_l0', False)}",
        f"- finance_disclosure_ready_for_step18 before/after: {prev['finance_disclosure_ready_for_step18']} -> {current_decisions.get('finance_disclosure_ready_for_step18', False)}",
        "- step19_implemented: False",
        "",
    ]
    return "\n".join(lines)


def source_probe_summary_markdown(
    *,
    command: str,
    probe_matrix: pd.DataFrame,
    adapter_diagnostics: pd.DataFrame,
    finance_candidates: pd.DataFrame,
    disclosure_candidates: pd.DataFrame,
    decisions: dict[str, Any],
) -> str:
    """Render 01G probe summary."""

    attempted = sorted(set(probe_matrix["source_category"])) if not probe_matrix.empty else []
    accessible = sorted(
        set(
            probe_matrix.loc[
                probe_matrix["probe_status"].isin(["SOURCE_AVAILABLE", "SOURCE_SCHEMA_UNKNOWN"]),
                "source_category",
            ]
        )
    ) if not probe_matrix.empty else []
    blocked = sorted(
        set(probe_matrix.loc[probe_matrix["probe_status"] == "SOURCE_BLOCKED_OR_JS_REQUIRED", "source_category"])
    ) if not probe_matrix.empty else []
    parse_failed = sorted(
        set(adapter_diagnostics.loc[adapter_diagnostics["status"] == "SOURCE_PARSE_FAILED", "source_category"])
    ) if not adapter_diagnostics.empty else []
    lines = [
        "# REAL-DATA-01G Source Probe Summary",
        "",
        f"- command: {command}",
        f"- source_categories_attempted: {', '.join(attempted)}",
        f"- accessible_or_schema_unknown_sources: {', '.join(accessible)}",
        f"- blocked_or_js_required_sources: {', '.join(blocked)}",
        f"- parse_failed_sources: {', '.join(parse_failed)}",
        f"- finance_candidate_rows: {len(finance_candidates)}",
        f"- disclosure_candidate_rows: {len(disclosure_candidates)}",
        f"- finance_ready_for_l0: {decisions.get('finance_ready_for_l0', False)}",
        f"- disclosure_ready_for_l0: {decisions.get('disclosure_ready_for_l0', False)}",
        f"- finance_disclosure_ready_for_step18: {decisions.get('finance_disclosure_ready_for_step18', False)}",
        "- step19_implemented: False",
        "",
        "Missing finance fields remain missing. Missing disclosure rows are not clean.",
        "",
    ]
    return "\n".join(lines)


def empty_all_adapter_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return (
        pd.DataFrame(columns=SOURCE_PROBE_COLUMNS),
        pd.DataFrame(columns=SOURCE_ADAPTER_DIAGNOSTIC_COLUMNS),
        pd.DataFrame(columns=SOURCE_SCHEMA_DIAGNOSTIC_COLUMNS),
        empty_finance_candidates(),
    )


def _load_class(class_path: str) -> type:
    module_path, _, class_name = class_path.rpartition(".")
    if not module_path or not class_name:
        raise ValueError(f"Invalid class_path: {class_path}")
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _load_report_metrics(report_dir: Path) -> dict[str, Any]:
    availability = _read_csv(report_dir / "source_availability_matrix.csv")
    evidence = _read_csv(report_dir / "field_level_evidence.csv")
    conflicts = _read_csv(report_dir / "source_conflict_report.csv")
    unresolved = _read_csv(report_dir / "unresolved_required_fields.csv")
    decision_text = _read_text(report_dir / "datasource_decision_report.md")
    return {
        "source_categories_with_rows": _category_count(availability),
        "finance_source_categories_with_rows": _category_count(availability, "financial_statement_summary"),
        "disclosure_source_categories_with_rows": _category_count(availability, "disclosure_status"),
        "field_level_evidence_rows": int(len(evidence)),
        "source_conflict_rows": int(len(conflicts)),
        "unresolved_required_fields_rows": int(len(unresolved)),
        "finance_unresolved_count": _dataset_count(unresolved, "financial_statement_summary"),
        "disclosure_unresolved_count": _dataset_count(unresolved, "disclosure_status"),
        "finance_ready_for_l0": _markdown_value(decision_text, "finance_ready_for_l0"),
        "disclosure_ready_for_l0": _markdown_value(decision_text, "disclosure_ready_for_l0"),
        "finance_disclosure_ready_for_step18": _markdown_value(decision_text, "finance_disclosure_ready_for_step18"),
    }


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, keep_default_na=False) if path.exists() else pd.DataFrame()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _category_count(df: pd.DataFrame, dataset_name: str | None = None) -> int:
    if df.empty or "source_category" not in df.columns:
        return 0
    rows = df
    if dataset_name and "dataset_name" in rows.columns:
        rows = rows[rows["dataset_name"] == dataset_name]
    if "row_count" in rows.columns:
        rows = rows[pd.to_numeric(rows["row_count"], errors="coerce").fillna(0) > 0]
    return int(rows["source_category"].nunique())


def _dataset_count(df: pd.DataFrame, dataset_name: str) -> int:
    if df.empty or "dataset_name" not in df.columns:
        return 0
    return int((df["dataset_name"] == dataset_name).sum())


def _markdown_value(text: str, key: str) -> str:
    marker = f"- {key}:"
    for line in text.splitlines():
        if line.startswith(marker):
            return line.split(":", 1)[1].strip()
    return ""


def _latest(group: pd.DataFrame, column: str) -> str:
    if column not in group.columns:
        return ""
    values = [str(value).strip() for value in group[column] if str(value).strip()]
    return max(values) if values else ""


def _confidence(group: pd.DataFrame) -> str:
    if "confidence_raw" not in group.columns:
        return "low"
    values = {str(value).strip().lower() for value in group["confidence_raw"]}
    if "low" in values:
        return "low"
    if "medium" in values:
        return "medium"
    return next(iter(values), "low")
