"""Auditable dry run from ingested raw data through Step 18 modules."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.classification.archetype_templates import (
    attach_archetype_template_metadata,
    load_archetype_templates,
    validate_archetype_templates,
)
from src.classification.business_classifier import (
    classify_businesses,
    load_business_classification_rules,
    load_micro_sector_taxonomy,
)
from src.features.driver_registry import (
    attach_driver_registry_to_records,
    load_driver_registry,
    validate_driver_registry,
)
from src.features.indicator_registry import (
    load_indicator_registry,
    resolve_indicators,
    validate_indicator_registry,
)
from src.features.raw_to_clean import (
    CLEAN_DATASET_COLUMNS,
    pivot_long_fetch_to_clean_wide,
)
from src.fetchers.base import REQUIRED_FETCH_COLUMNS
from src.ingestion.contracts import PROHIBITED_RECOMMENDATION_FIELDS
from src.ingestion.coverage_report import (
    COVERAGE_REPORT_COLUMNS,
    DEFAULT_COVERAGE_REQUIRED_FIELDS,
    build_data_coverage_report,
    save_data_coverage_report,
)
from src.quality.data_quality import (
    load_data_quality_rules,
    run_data_quality_checks,
)
from src.scoring.l0_basic_investability_filter import (
    run_l0_basic_investability_filter,
)
from src.scoring.l0_trash_filter import run_l0_trash_filter
from src.scoring.sector_cycle_engine import (
    load_sector_cycle_rules,
    score_all_micro_sectors,
    score_micro_sector_cycle,
)
from src.universe.build_universe import build_clean_universe, load_universe_rules


PIPELINE_DATASETS = [
    "universe",
    "company_profile",
    "market_price",
    "financial_statement_summary",
    "disclosure_status",
]

RAW_FILENAMES = {
    "universe": "universe_raw.csv",
    "company_profile": "company_profile_raw.csv",
    "market_price": "market_price_raw.csv",
    "financial_statement_summary": "financial_statement_summary_raw.csv",
    "disclosure_status": "disclosure_status_raw.csv",
}

DRY_RUN_STAGES = [
    "raw_to_clean",
    "data_quality",
    "production_universe_builder",
    "l0_trash_filter",
    "l0_basic_investability_filter",
    "l1_business_classification",
    "archetype_templates",
    "driver_registry",
    "indicator_registry",
    "sector_cycle_engine",
]

RUN_SIZE_LIMITS = {"mini": 20, "medium": 200, "full": None}
RUN_SIZE_MINIMUMS = {"mini": 10, "medium": 100, "full": 0}

ERROR_COLUMNS = [
    "stage",
    "dataset_name",
    "ticker",
    "error_code",
    "message",
    "notes",
]

MANUAL_REVIEW_COLUMNS = [
    "ticker",
    "module",
    "issue",
    "severity",
    "status",
    "evidence",
    "confidence",
    "notes",
]

DRY_RUN_SUMMARY_FIELDS = [
    "run_id",
    "run_size",
    "started_at",
    "finished_at",
    "input_ticker_count",
    "output_ticker_count",
    "module_statuses",
    "pass_counts_by_layer",
    "reject_counts_by_layer",
    "manual_review_count",
    "insufficient_data_count",
    "warning_flags",
    "error_count",
    "next_action_recommendation",
]

INDICATOR_RESOLUTION_COLUMNS = [
    "ticker",
    "indicator_resolution_status",
    "resolved_indicator_ids",
    "core_indicator_ids",
    "archetype_indicator_ids",
    "sector_specific_indicator_ids",
    "unmapped_driver_hints",
    "missing_data_warnings",
    "warning_flags",
    "confidence",
    "manual_review_required",
]


def run_pipeline_dry_run(
    *,
    raw_datasets: dict[str, pd.DataFrame | None] | None = None,
    raw_data_dir: str | Path = "data/raw",
    reports_dir: str | Path = "data/reports",
    run_size: str = "mini",
    run_id: str | None = None,
    reference_date: str | None = None,
    indicator_rows: list[dict[str, Any]] | None = None,
    write_reports: bool = True,
) -> dict[str, Any]:
    """Run a non-production pipeline dry run through available Step 18 modules."""

    if run_size not in RUN_SIZE_LIMITS:
        raise ValueError(
            f"Unsupported run_size: {run_size}. "
            f"Supported values: {', '.join(sorted(RUN_SIZE_LIMITS))}."
        )

    started_at = _utc_now_iso()
    resolved_run_id = run_id or f"pipeline_dry_run_{_safe_token(started_at)}"
    errors: list[dict[str, Any]] = []
    module_status_records: list[dict[str, Any]] = []
    manual_review_rows: list[dict[str, Any]] = []
    warning_flags: list[str] = []

    raw_inputs = _load_raw_inputs(raw_datasets=raw_datasets, raw_data_dir=raw_data_dir)
    selected_tickers, size_warnings = _select_tickers(raw_inputs, run_size)
    warning_flags.extend(size_warnings)
    raw_inputs = _filter_datasets_to_tickers(raw_inputs, selected_tickers)

    clean_datasets, raw_to_clean_status = _run_raw_to_clean_stage(
        raw_inputs=raw_inputs,
        errors=errors,
    )
    module_status_records.append(raw_to_clean_status)
    warning_flags.extend(raw_to_clean_status["warnings"])

    quality_datasets, data_quality_status = _run_data_quality_stage(
        clean_datasets=clean_datasets,
        reference_date=reference_date,
        errors=errors,
    )
    module_status_records.append(data_quality_status)
    warning_flags.extend(data_quality_status["warnings"])

    coverage_inputs = {
        dataset_name: (
            None
            if raw_inputs.get(dataset_name) is None
            else quality_datasets.get(dataset_name)
        )
        for dataset_name in PIPELINE_DATASETS
    }
    coverage_report = build_data_coverage_report(
        coverage_inputs,
        dataset_order=PIPELINE_DATASETS,
        required_fields_by_dataset=DEFAULT_COVERAGE_REQUIRED_FIELDS,
    )
    _extend_manual_review_from_coverage(coverage_report, manual_review_rows)

    universe_df = _run_universe_stage(
        quality_datasets=quality_datasets,
        module_status_records=module_status_records,
        errors=errors,
        warning_flags=warning_flags,
        manual_review_rows=manual_review_rows,
    )
    l0_trash_df = _run_l0_trash_stage(
        universe_df=universe_df,
        quality_datasets=quality_datasets,
        module_status_records=module_status_records,
        errors=errors,
        warning_flags=warning_flags,
        manual_review_rows=manual_review_rows,
    )
    l0_basic_df = _run_l0_basic_stage(
        universe_df=universe_df,
        l0_trash_df=l0_trash_df,
        quality_datasets=quality_datasets,
        module_status_records=module_status_records,
        errors=errors,
        warning_flags=warning_flags,
        manual_review_rows=manual_review_rows,
    )
    classification_df = _run_classification_stage(
        l0_basic_df=l0_basic_df,
        quality_datasets=quality_datasets,
        module_status_records=module_status_records,
        errors=errors,
        warning_flags=warning_flags,
        manual_review_rows=manual_review_rows,
    )
    template_df = _run_archetype_stage(
        classification_df=classification_df,
        module_status_records=module_status_records,
        errors=errors,
        warning_flags=warning_flags,
        manual_review_rows=manual_review_rows,
    )
    driver_df = _run_driver_stage(
        template_df=template_df,
        module_status_records=module_status_records,
        errors=errors,
        warning_flags=warning_flags,
        manual_review_rows=manual_review_rows,
    )
    indicator_df = _run_indicator_stage(
        driver_df=driver_df,
        module_status_records=module_status_records,
        errors=errors,
        warning_flags=warning_flags,
        manual_review_rows=manual_review_rows,
    )
    sector_cycle_df = _run_sector_cycle_stage(
        classification_df=classification_df,
        indicator_rows=indicator_rows,
        module_status_records=module_status_records,
        errors=errors,
        warning_flags=warning_flags,
        manual_review_rows=manual_review_rows,
    )
    _add_missing_disclosure_manual_review(
        universe_df=universe_df,
        disclosure_df=quality_datasets.get("disclosure_status"),
        manual_review_rows=manual_review_rows,
    )

    manual_review_queue = _manual_review_dataframe(manual_review_rows)
    errors_df = pd.DataFrame(errors, columns=ERROR_COLUMNS)
    finished_at = _utc_now_iso()
    summary = _build_summary(
        run_id=resolved_run_id,
        run_size=run_size,
        started_at=started_at,
        finished_at=finished_at,
        input_ticker_count=len(selected_tickers),
        universe_df=universe_df,
        l0_trash_df=l0_trash_df,
        l0_basic_df=l0_basic_df,
        classification_df=classification_df,
        driver_df=driver_df,
        indicator_df=indicator_df,
        sector_cycle_df=sector_cycle_df,
        module_status_records=module_status_records,
        manual_review_queue=manual_review_queue,
        errors_df=errors_df,
        warning_flags=warning_flags,
    )

    report_paths = {}
    if write_reports:
        report_paths = save_pipeline_dry_run_reports(
            reports_dir=reports_dir,
            coverage_report=coverage_report,
            summary=summary,
            errors_df=errors_df,
            manual_review_queue=manual_review_queue,
        )

    return {
        "run_id": resolved_run_id,
        "run_size": run_size,
        "selected_tickers": selected_tickers,
        "raw_datasets": raw_inputs,
        "clean_datasets": clean_datasets,
        "quality_datasets": quality_datasets,
        "coverage_report": coverage_report,
        "universe": universe_df,
        "l0_trash": l0_trash_df,
        "l0_basic": l0_basic_df,
        "classification": classification_df,
        "archetype_templates": template_df,
        "driver_registry": driver_df,
        "indicator_registry": indicator_df,
        "sector_cycle": sector_cycle_df,
        "module_status_records": module_status_records,
        "manual_review_queue": manual_review_queue,
        "errors": errors_df,
        "summary": summary,
        "report_paths": report_paths,
    }


def save_pipeline_dry_run_reports(
    *,
    reports_dir: str | Path,
    coverage_report: pd.DataFrame,
    summary: dict[str, Any],
    errors_df: pd.DataFrame,
    manual_review_queue: pd.DataFrame,
) -> dict[str, str]:
    """Save the required DATA-06 dry-run reports."""

    output_dir = Path(reports_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "coverage_report": save_data_coverage_report(
            coverage_report, output_dir, "data_coverage_report.csv"
        ),
        "ingestion_run_summary": str(output_dir / "ingestion_run_summary.md"),
        "pipeline_dry_run_summary": str(output_dir / "pipeline_dry_run_summary.md"),
        "pipeline_dry_run_errors": str(output_dir / "pipeline_dry_run_errors.csv"),
        "manual_review_queue": "",
    }
    Path(paths["ingestion_run_summary"]).write_text(
        _ingestion_summary_markdown(summary, coverage_report),
        encoding="utf-8",
    )
    Path(paths["pipeline_dry_run_summary"]).write_text(
        _dry_run_summary_markdown(summary),
        encoding="utf-8",
    )
    errors_df.to_csv(paths["pipeline_dry_run_errors"], index=False)
    if not manual_review_queue.empty:
        manual_review_path = output_dir / "manual_review_queue.csv"
        manual_review_queue.to_csv(manual_review_path, index=False)
        paths["manual_review_queue"] = str(manual_review_path)
    return paths


def has_prohibited_recommendation_columns(df: pd.DataFrame) -> bool:
    """Return True if a dry-run output DataFrame contains prohibited fields."""

    normalized_columns = {str(column).strip().lower() for column in df.columns}
    return bool(PROHIBITED_RECOMMENDATION_FIELDS.intersection(normalized_columns))


def _run_raw_to_clean_stage(
    *,
    raw_inputs: dict[str, pd.DataFrame | None],
    errors: list[dict[str, Any]],
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    clean_datasets: dict[str, pd.DataFrame] = {}
    warnings: list[str] = []
    stage_errors: list[str] = []

    for dataset_name in PIPELINE_DATASETS:
        raw_df = raw_inputs.get(dataset_name)
        if raw_df is None:
            warning = f"MISSING_RAW_DATASET:{dataset_name}"
            warnings.append(warning)
            stage_errors.append(warning)
            clean_datasets[dataset_name] = _empty_clean_dataset(dataset_name)
            _append_error(
                errors,
                stage="raw_to_clean",
                dataset_name=dataset_name,
                error_code="MISSING_RAW_DATASET",
                message="Raw dataset is not available.",
                notes="Missing data is not treated as clean.",
            )
            continue
        try:
            clean_df = _raw_dataset_to_clean(dataset_name, raw_df)
            clean_datasets[dataset_name] = clean_df
            result = clean_df.attrs.get("cleaning_result", {})
            warnings.extend(result.get("warnings", []))
            stage_errors.extend(result.get("errors", []))
        except Exception as exc:  # noqa: BLE001 - dry run must record failures.
            error_code = "RAW_TO_CLEAN_FAILED"
            stage_errors.append(f"{dataset_name}:{error_code}")
            clean_datasets[dataset_name] = _empty_clean_dataset(dataset_name)
            _append_error(
                errors,
                stage="raw_to_clean",
                dataset_name=dataset_name,
                error_code=error_code,
                message=str(exc),
            )

    status = _stage_status(warnings=warnings, errors=stage_errors)
    return clean_datasets, _module_status(
        "raw_to_clean",
        status,
        input_count=sum(_row_count(df) for df in raw_inputs.values()),
        output_count=sum(len(df) for df in clean_datasets.values()),
        warnings=warnings,
        errors=stage_errors,
    )


def _run_data_quality_stage(
    *,
    clean_datasets: dict[str, pd.DataFrame],
    reference_date: str | None,
    errors: list[dict[str, Any]],
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    quality_datasets: dict[str, pd.DataFrame] = {}
    warnings: list[str] = []
    stage_errors: list[str] = []

    try:
        rules = load_data_quality_rules("config/data_quality_rules.yaml")
    except Exception as exc:  # noqa: BLE001
        rules = {"datasets": {}}
        stage_errors.append("DATA_QUALITY_RULES_UNAVAILABLE")
        _append_error(
            errors,
            stage="data_quality",
            dataset_name="",
            error_code="DATA_QUALITY_RULES_UNAVAILABLE",
            message=str(exc),
        )

    for dataset_name in PIPELINE_DATASETS:
        clean_df = clean_datasets.get(dataset_name, _empty_clean_dataset(dataset_name))
        if clean_df.empty:
            quality_datasets[dataset_name] = clean_df.copy()
            warnings.append(f"SKIPPED_EMPTY_DATASET:{dataset_name}")
            continue
        try:
            quality_df = run_data_quality_checks(
                clean_df,
                dataset_name,
                rules,
                reference_date=reference_date,
            )
            quality_datasets[dataset_name] = quality_df
            warnings.extend(_quality_warning_flags(quality_df))
        except Exception as exc:  # noqa: BLE001
            stage_errors.append(f"{dataset_name}:DATA_QUALITY_FAILED")
            quality_datasets[dataset_name] = clean_df.copy()
            _append_error(
                errors,
                stage="data_quality",
                dataset_name=dataset_name,
                error_code="DATA_QUALITY_FAILED",
                message=str(exc),
            )

    status = _stage_status(warnings=warnings, errors=stage_errors)
    return quality_datasets, _module_status(
        "data_quality",
        status,
        input_count=sum(len(df) for df in clean_datasets.values()),
        output_count=sum(len(df) for df in quality_datasets.values()),
        warnings=warnings,
        errors=stage_errors,
    )


def _run_universe_stage(
    *,
    quality_datasets: dict[str, pd.DataFrame],
    module_status_records: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    warning_flags: list[str],
    manual_review_rows: list[dict[str, Any]],
) -> pd.DataFrame:
    universe_input = quality_datasets.get("universe", pd.DataFrame())
    if universe_input.empty:
        warning = "MISSING_REQUIRED_INPUT:universe"
        warning_flags.append(warning)
        _append_error(
            errors,
            stage="production_universe_builder",
            dataset_name="universe",
            error_code="MISSING_REQUIRED_INPUT",
            message="Universe input is required for downstream dry-run stages.",
        )
        module_status_records.append(
            _module_status(
                "production_universe_builder",
                "MISSING_REQUIRED_INPUT",
                warnings=[warning],
                errors=[warning],
            )
        )
        return pd.DataFrame()

    try:
        rules = load_universe_rules("config/universe_rules.yaml")
        universe_df = build_clean_universe(
            universe_input,
            company_profile_df=quality_datasets.get("company_profile"),
            market_price_df=quality_datasets.get("market_price"),
            financial_statement_df=quality_datasets.get("financial_statement_summary"),
            disclosure_df=quality_datasets.get("disclosure_status"),
            rules=rules,
        )
        warnings = _list_flags(universe_df, "universe_warnings")
        _extend_manual_review_from_rows(
            universe_df,
            module="production_universe_builder",
            status_column="universe_status",
            issue_column="universe_warnings",
            confidence_column="data_sanity_status",
            manual_review_rows=manual_review_rows,
        )
        module_status_records.append(
            _module_status(
                "production_universe_builder",
                _stage_status(warnings=warnings, errors=[]),
                input_count=len(universe_input),
                output_count=len(universe_df),
                warnings=warnings,
            )
        )
        warning_flags.extend(warnings)
        return universe_df
    except Exception as exc:  # noqa: BLE001
        _append_error(
            errors,
            stage="production_universe_builder",
            dataset_name="universe",
            error_code="UNIVERSE_BUILDER_FAILED",
            message=str(exc),
        )
        module_status_records.append(
            _module_status(
                "production_universe_builder",
                "DATA_ERROR",
                errors=["UNIVERSE_BUILDER_FAILED"],
            )
        )
        return pd.DataFrame()


def _run_l0_trash_stage(
    *,
    universe_df: pd.DataFrame,
    quality_datasets: dict[str, pd.DataFrame],
    module_status_records: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    warning_flags: list[str],
    manual_review_rows: list[dict[str, Any]],
) -> pd.DataFrame:
    if universe_df.empty:
        module_status_records.append(
            _module_status("l0_trash_filter", "SKIPPED_MISSING_REQUIRED_INPUT")
        )
        return pd.DataFrame()

    try:
        l0_df = run_l0_trash_filter(
            universe_df,
            market_price_df=quality_datasets.get("market_price"),
            financial_statement_df=quality_datasets.get("financial_statement_summary"),
            disclosure_df=quality_datasets.get("disclosure_status"),
            rules=_safe_load_mapping("config/l0_trash_filter_rules.yaml"),
        )
        warnings = _list_flags(l0_df, "l0_warning_flags") + _list_flags(
            l0_df, "l0_reject_reasons"
        )
        _extend_manual_review_from_rows(
            l0_df,
            module="l0_trash_filter",
            status_column="l0_status",
            issue_column="l0_reject_reasons",
            confidence_column="confidence",
            manual_review_rows=manual_review_rows,
        )
        module_status_records.append(
            _module_status(
                "l0_trash_filter",
                _stage_status(warnings=warnings, errors=[]),
                input_count=len(universe_df),
                output_count=len(l0_df),
                warnings=warnings,
            )
        )
        warning_flags.extend(warnings)
        return l0_df
    except Exception as exc:  # noqa: BLE001
        _append_error(
            errors,
            stage="l0_trash_filter",
            error_code="L0_TRASH_FILTER_FAILED",
            message=str(exc),
        )
        module_status_records.append(
            _module_status(
                "l0_trash_filter",
                "DATA_ERROR",
                errors=["L0_TRASH_FILTER_FAILED"],
            )
        )
        return pd.DataFrame()


def _run_l0_basic_stage(
    *,
    universe_df: pd.DataFrame,
    l0_trash_df: pd.DataFrame,
    quality_datasets: dict[str, pd.DataFrame],
    module_status_records: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    warning_flags: list[str],
    manual_review_rows: list[dict[str, Any]],
) -> pd.DataFrame:
    if universe_df.empty or l0_trash_df.empty:
        module_status_records.append(
            _module_status(
                "l0_basic_investability_filter",
                "SKIPPED_MISSING_REQUIRED_INPUT",
            )
        )
        return pd.DataFrame()

    try:
        l0_basic_df = run_l0_basic_investability_filter(
            universe_df,
            l0_trash_df,
            market_price_df=quality_datasets.get("market_price"),
            company_profile_df=quality_datasets.get("company_profile"),
            financial_statement_df=quality_datasets.get("financial_statement_summary"),
            disclosure_df=quality_datasets.get("disclosure_status"),
            rules=_safe_load_mapping("config/l0_basic_investability_rules.yaml"),
        )
        warnings = _list_flags(l0_basic_df, "warning_flags") + _list_flags(
            l0_basic_df, "reject_reasons"
        )
        _extend_manual_review_from_rows(
            l0_basic_df,
            module="l0_basic_investability_filter",
            status_column="l0_basic_status",
            issue_column="warning_flags",
            confidence_column="confidence",
            manual_review_rows=manual_review_rows,
        )
        module_status_records.append(
            _module_status(
                "l0_basic_investability_filter",
                _stage_status(warnings=warnings, errors=[]),
                input_count=len(l0_trash_df),
                output_count=len(l0_basic_df),
                warnings=warnings,
            )
        )
        warning_flags.extend(warnings)
        return l0_basic_df
    except Exception as exc:  # noqa: BLE001
        _append_error(
            errors,
            stage="l0_basic_investability_filter",
            error_code="L0_BASIC_FILTER_FAILED",
            message=str(exc),
        )
        module_status_records.append(
            _module_status(
                "l0_basic_investability_filter",
                "DATA_ERROR",
                errors=["L0_BASIC_FILTER_FAILED"],
            )
        )
        return pd.DataFrame()


def _run_classification_stage(
    *,
    l0_basic_df: pd.DataFrame,
    quality_datasets: dict[str, pd.DataFrame],
    module_status_records: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    warning_flags: list[str],
    manual_review_rows: list[dict[str, Any]],
) -> pd.DataFrame:
    if l0_basic_df.empty:
        module_status_records.append(
            _module_status(
                "l1_business_classification",
                "SKIPPED_MISSING_REQUIRED_INPUT",
            )
        )
        return pd.DataFrame()

    try:
        classification_df = classify_businesses(
            l0_basic_df,
            company_profile_df=quality_datasets.get("company_profile"),
            financial_statement_df=quality_datasets.get("financial_statement_summary"),
            taxonomy=load_micro_sector_taxonomy("config/micro_sector_taxonomy.yaml"),
            rules=load_business_classification_rules(
                "config/l1_business_classification_rules.yaml"
            ),
        )
        warnings = _list_flags(classification_df, "warning_flags")
        _extend_manual_review_from_rows(
            classification_df,
            module="l1_business_classification",
            status_column="classification_status",
            issue_column="warning_flags",
            confidence_column="classification_confidence",
            manual_review_rows=manual_review_rows,
        )
        module_status_records.append(
            _module_status(
                "l1_business_classification",
                _stage_status(warnings=warnings, errors=[]),
                input_count=len(l0_basic_df),
                output_count=len(classification_df),
                warnings=warnings,
            )
        )
        warning_flags.extend(warnings)
        return classification_df
    except Exception as exc:  # noqa: BLE001
        _append_error(
            errors,
            stage="l1_business_classification",
            error_code="CLASSIFICATION_FAILED",
            message=str(exc),
        )
        module_status_records.append(
            _module_status(
                "l1_business_classification",
                "DATA_ERROR",
                errors=["CLASSIFICATION_FAILED"],
            )
        )
        return pd.DataFrame()


def _run_archetype_stage(
    *,
    classification_df: pd.DataFrame,
    module_status_records: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    warning_flags: list[str],
    manual_review_rows: list[dict[str, Any]],
) -> pd.DataFrame:
    if classification_df.empty:
        module_status_records.append(
            _module_status("archetype_templates", "SKIPPED_MISSING_REQUIRED_INPUT")
        )
        return pd.DataFrame()

    try:
        config = load_archetype_templates("config/archetype_templates.yaml")
        validation = validate_archetype_templates(config)
        warnings = list(validation.get("warnings", []))
        stage_errors = list(validation.get("errors", []))
        template_df = attach_archetype_template_metadata(classification_df, config)
        warnings.extend(_list_flags(template_df, "archetype_warning_flags"))
        _extend_manual_review_from_rows(
            template_df,
            module="archetype_templates",
            status_column="archetype_template_status",
            issue_column="archetype_warning_flags",
            confidence_column="archetype_template_confidence",
            manual_review_rows=manual_review_rows,
        )
        module_status_records.append(
            _module_status(
                "archetype_templates",
                _stage_status(warnings=warnings, errors=stage_errors),
                input_count=len(classification_df),
                output_count=len(template_df),
                warnings=warnings,
                errors=stage_errors,
            )
        )
        warning_flags.extend(warnings)
        for error in stage_errors:
            _append_error(
                errors,
                stage="archetype_templates",
                error_code="ARCHETYPE_TEMPLATE_VALIDATION_ERROR",
                message=error,
            )
        return template_df
    except Exception as exc:  # noqa: BLE001
        _append_error(
            errors,
            stage="archetype_templates",
            error_code="ARCHETYPE_TEMPLATE_FAILED",
            message=str(exc),
        )
        module_status_records.append(
            _module_status(
                "archetype_templates",
                "DATA_ERROR",
                errors=["ARCHETYPE_TEMPLATE_FAILED"],
            )
        )
        return pd.DataFrame()


def _run_driver_stage(
    *,
    template_df: pd.DataFrame,
    module_status_records: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    warning_flags: list[str],
    manual_review_rows: list[dict[str, Any]],
) -> pd.DataFrame:
    if template_df.empty:
        module_status_records.append(
            _module_status("driver_registry", "SKIPPED_MISSING_REQUIRED_INPUT")
        )
        return pd.DataFrame()

    try:
        registry = load_driver_registry("config/driver_registry.yaml")
        validation = validate_driver_registry(registry)
        stage_errors = list(validation.get("errors", []))
        driver_df = attach_driver_registry_to_records(template_df, registry)
        warnings = _list_flags(driver_df, "warning_flags")
        _extend_manual_review_from_rows(
            driver_df,
            module="driver_registry",
            status_column="driver_resolution_status",
            issue_column="warning_flags",
            confidence_column="driver_resolution_status",
            manual_review_rows=manual_review_rows,
        )
        module_status_records.append(
            _module_status(
                "driver_registry",
                _stage_status(warnings=warnings, errors=stage_errors),
                input_count=len(template_df),
                output_count=len(driver_df),
                warnings=warnings,
                errors=stage_errors,
            )
        )
        warning_flags.extend(warnings)
        for error in stage_errors:
            _append_error(
                errors,
                stage="driver_registry",
                error_code="DRIVER_REGISTRY_VALIDATION_ERROR",
                message=error,
            )
        return driver_df
    except Exception as exc:  # noqa: BLE001
        _append_error(
            errors,
            stage="driver_registry",
            error_code="DRIVER_REGISTRY_FAILED",
            message=str(exc),
        )
        module_status_records.append(
            _module_status(
                "driver_registry",
                "DATA_ERROR",
                errors=["DRIVER_REGISTRY_FAILED"],
            )
        )
        return pd.DataFrame()


def _run_indicator_stage(
    *,
    driver_df: pd.DataFrame,
    module_status_records: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    warning_flags: list[str],
    manual_review_rows: list[dict[str, Any]],
) -> pd.DataFrame:
    if driver_df.empty:
        module_status_records.append(
            _module_status("indicator_registry", "SKIPPED_MISSING_REQUIRED_INPUT")
        )
        return pd.DataFrame(columns=INDICATOR_RESOLUTION_COLUMNS)

    try:
        registry = load_indicator_registry("config/indicator_registry.yaml")
        validation_errors = validate_indicator_registry(registry)
        rows = []
        for _, row in driver_df.iterrows():
            resolution = resolve_indicators(
                drivers=_driver_ids_from_row(row),
                archetype=row.get("archetype"),
                primary_micro_sector=row.get("primary_micro_sector"),
                secondary_micro_sector=row.get("secondary_micro_sector"),
                registry=registry,
            )
            rows.append(
                {
                    "ticker": row.get("ticker", ""),
                    "indicator_resolution_status": resolution[
                        "indicator_resolution_status"
                    ],
                    "resolved_indicator_ids": _indicator_ids(
                        resolution["resolved_indicators"]
                    ),
                    "core_indicator_ids": _indicator_ids(
                        resolution["core_indicators"]
                    ),
                    "archetype_indicator_ids": _indicator_ids(
                        resolution["archetype_indicators"]
                    ),
                    "sector_specific_indicator_ids": _indicator_ids(
                        resolution["sector_specific_indicators"]
                    ),
                    "unmapped_driver_hints": resolution["unmapped_driver_hints"],
                    "missing_data_warnings": resolution["missing_data_warnings"],
                    "warning_flags": resolution["warning_flags"],
                    "confidence": resolution["confidence"],
                    "manual_review_required": resolution["manual_review_required"],
                }
            )
        indicator_df = pd.DataFrame(rows, columns=INDICATOR_RESOLUTION_COLUMNS)
        if not indicator_df.empty:
            indicator_df["manual_review_required"] = indicator_df[
                "manual_review_required"
            ].astype(object)
        warnings = _list_flags(indicator_df, "warning_flags") + _list_flags(
            indicator_df, "missing_data_warnings"
        )
        _extend_manual_review_from_rows(
            indicator_df,
            module="indicator_registry",
            status_column="indicator_resolution_status",
            issue_column="warning_flags",
            confidence_column="confidence",
            manual_review_rows=manual_review_rows,
        )
        module_status_records.append(
            _module_status(
                "indicator_registry",
                _stage_status(warnings=warnings, errors=validation_errors),
                input_count=len(driver_df),
                output_count=len(indicator_df),
                warnings=warnings,
                errors=validation_errors,
            )
        )
        warning_flags.extend(warnings)
        for error in validation_errors:
            _append_error(
                errors,
                stage="indicator_registry",
                error_code="INDICATOR_REGISTRY_VALIDATION_ERROR",
                message=error,
            )
        return indicator_df
    except Exception as exc:  # noqa: BLE001
        _append_error(
            errors,
            stage="indicator_registry",
            error_code="INDICATOR_REGISTRY_FAILED",
            message=str(exc),
        )
        module_status_records.append(
            _module_status(
                "indicator_registry",
                "DATA_ERROR",
                errors=["INDICATOR_REGISTRY_FAILED"],
            )
        )
        return pd.DataFrame(columns=INDICATOR_RESOLUTION_COLUMNS)


def _run_sector_cycle_stage(
    *,
    classification_df: pd.DataFrame,
    indicator_rows: list[dict[str, Any]] | None,
    module_status_records: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    warning_flags: list[str],
    manual_review_rows: list[dict[str, Any]],
) -> pd.DataFrame:
    try:
        rules = load_sector_cycle_rules("config/sector_cycle_rules.yaml")
        if indicator_rows:
            results = score_all_micro_sectors(indicator_rows, rules=rules)
        else:
            sectors = _classified_micro_sectors(classification_df)
            if not sectors:
                sectors = ["unknown"]
            results = [
                score_micro_sector_cycle(sector, [], rules=rules) for sector in sectors
            ]
        sector_df = pd.DataFrame(results)
        warnings = _list_flags(sector_df, "warning_flags")
        if (
            "cycle_status" in sector_df.columns
            and (
                sector_df["cycle_status"]
                == "INSUFFICIENT_DATA_FOR_SECTOR_CYCLE"
            ).any()
        ):
            warnings.append("INSUFFICIENT_DATA_FOR_SECTOR_CYCLE")
        _extend_manual_review_from_sector_cycle(sector_df, manual_review_rows)
        module_status_records.append(
            _module_status(
                "sector_cycle_engine",
                _stage_status(warnings=warnings, errors=[]),
                input_count=len(indicator_rows or []),
                output_count=len(sector_df),
                warnings=warnings,
                notes="Indicator values are required for high-confidence sector-cycle output.",
            )
        )
        warning_flags.extend(warnings)
        return sector_df
    except Exception as exc:  # noqa: BLE001
        _append_error(
            errors,
            stage="sector_cycle_engine",
            error_code="SECTOR_CYCLE_FAILED",
            message=str(exc),
        )
        module_status_records.append(
            _module_status(
                "sector_cycle_engine",
                "DATA_ERROR",
                errors=["SECTOR_CYCLE_FAILED"],
            )
        )
        return pd.DataFrame()


def _load_raw_inputs(
    *,
    raw_datasets: dict[str, pd.DataFrame | None] | None,
    raw_data_dir: str | Path,
) -> dict[str, pd.DataFrame | None]:
    provided = dict(raw_datasets or {})
    output: dict[str, pd.DataFrame | None] = {}
    raw_dir = Path(raw_data_dir)
    for dataset_name in PIPELINE_DATASETS:
        if dataset_name in provided:
            output[dataset_name] = provided[dataset_name]
            continue
        raw_path = raw_dir / RAW_FILENAMES[dataset_name]
        output[dataset_name] = pd.read_csv(raw_path) if raw_path.exists() else None
    return output


def _select_tickers(
    raw_inputs: dict[str, pd.DataFrame | None], run_size: str
) -> tuple[list[str], list[str]]:
    tickers = _ordered_tickers(raw_inputs.get("universe"))
    if not tickers:
        for df in raw_inputs.values():
            tickers = _ordered_tickers(df)
            if tickers:
                break

    limit = RUN_SIZE_LIMITS[run_size]
    selected = tickers[:limit] if limit is not None else tickers
    warnings: list[str] = []
    minimum = RUN_SIZE_MINIMUMS[run_size]
    if len(selected) < minimum:
        warnings.append(
            f"RUN_SIZE_LIMITED_BY_AVAILABLE_TICKERS:{run_size}:{len(selected)}"
        )
    return selected, warnings


def _filter_datasets_to_tickers(
    raw_inputs: dict[str, pd.DataFrame | None], tickers: list[str]
) -> dict[str, pd.DataFrame | None]:
    if not tickers:
        return raw_inputs
    ticker_set = set(tickers)
    output = {}
    for dataset_name, df in raw_inputs.items():
        if not isinstance(df, pd.DataFrame) or "ticker" not in df.columns:
            output[dataset_name] = df
            continue
        mask = df["ticker"].map(lambda value: _clean_ticker(value) in ticker_set)
        output[dataset_name] = df[mask].copy()
    return output


def _raw_dataset_to_clean(dataset_name: str, raw_df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(raw_df, pd.DataFrame):
        raise TypeError(f"{dataset_name} raw input must be a pandas DataFrame.")
    if _is_long_fetch_output(raw_df):
        return pivot_long_fetch_to_clean_wide(raw_df, dataset_name)

    source = raw_df.copy(deep=True)
    if dataset_name == "disclosure_status" and "date" not in source.columns:
        if "event_date" in source.columns:
            source["date"] = source["event_date"]
    if dataset_name == "financial_statement_summary" and "period" not in source.columns:
        if "date" in source.columns:
            source["period"] = source["date"]

    clean_columns = CLEAN_DATASET_COLUMNS[dataset_name]
    for column in clean_columns:
        if column not in source.columns:
            source[column] = pd.NA
    output = source[clean_columns].copy()
    if "ticker" in output.columns:
        output["ticker"] = output["ticker"].map(_clean_ticker)

    result = {
        "dataset_name": dataset_name,
        "is_valid": True,
        "missing_columns": [],
        "missing_fetch_columns": [],
        "extra_fields": [
            column for column in raw_df.columns if column not in set(clean_columns)
        ],
        "duplicate_records": 0,
        "collapsed_records": 0,
        "warnings": [],
        "errors": [],
    }
    for field in DEFAULT_COVERAGE_REQUIRED_FIELDS.get(dataset_name, []):
        if field not in output.columns or output[field].map(_is_missing).all():
            result["is_valid"] = False
            result["missing_columns"].append(field)
            result["warnings"].append(f"MISSING_CLEAN_FIELD:{dataset_name}:{field}")
    output.attrs["cleaning_result"] = result
    return output


def _is_long_fetch_output(df: pd.DataFrame) -> bool:
    return set(REQUIRED_FETCH_COLUMNS).issubset(set(df.columns))


def _empty_clean_dataset(dataset_name: str) -> pd.DataFrame:
    columns = CLEAN_DATASET_COLUMNS.get(dataset_name, [])
    return pd.DataFrame(columns=columns)


def _extend_manual_review_from_coverage(
    coverage_report: pd.DataFrame, manual_review_rows: list[dict[str, Any]]
) -> None:
    for _, row in coverage_report.iterrows():
        if row.get("coverage_status") in {"VALID_DATA", "LOW_CONFIDENCE"}:
            continue
        if row.get("dataset_name") == "disclosure_status":
            continue
        if int(row.get("manual_review_count", 0)) == 0 and row.get(
            "coverage_status"
        ) not in {"MISSING_DATASET", "MISSING_DATA", "EMPTY_DATASET"}:
            continue
        manual_review_rows.append(
            _manual_review_row(
                ticker="",
                module="coverage_report",
                issue=str(row.get("coverage_status", "")),
                severity="MEDIUM",
                evidence=str(row.get("dataset_name", "")),
                confidence="low",
                notes=str(row.get("notes", "")),
            )
        )


def _extend_manual_review_from_rows(
    df: pd.DataFrame,
    *,
    module: str,
    status_column: str,
    issue_column: str,
    confidence_column: str,
    manual_review_rows: list[dict[str, Any]],
) -> None:
    if df.empty:
        return
    for _, row in df.iterrows():
        status = str(row.get(status_column, "")).strip()
        issues = _value_list(row.get(issue_column))
        confidence = str(row.get(confidence_column, "")).strip()
        should_review = _truthy(row.get("manual_review_required")) or _review_status(
            status
        )
        if not should_review:
            continue
        if not issues:
            issues = [status or "MANUAL_REVIEW_REQUIRED"]
        for issue in issues:
            manual_review_rows.append(
                _manual_review_row(
                    ticker=_clean_ticker(row.get("ticker")),
                    module=module,
                    issue=str(issue),
                    severity=_severity_for_issue(str(issue)),
                    status=status or "MANUAL_REVIEW_REQUIRED",
                    evidence=str(row.get("evidence_fields", "")),
                    confidence=confidence,
                    notes=str(row.get("classification_notes", "")),
                )
            )


def _extend_manual_review_from_sector_cycle(
    sector_df: pd.DataFrame, manual_review_rows: list[dict[str, Any]]
) -> None:
    if sector_df.empty:
        return
    for _, row in sector_df.iterrows():
        if not _truthy(row.get("manual_review_required")) and row.get(
            "cycle_status"
        ) != "INSUFFICIENT_DATA_FOR_SECTOR_CYCLE":
            continue
        issues = _value_list(row.get("warning_flags")) or [row.get("cycle_status", "")]
        for issue in issues:
            manual_review_rows.append(
                _manual_review_row(
                    ticker="",
                    module="sector_cycle_engine",
                    issue=str(issue),
                    severity="MEDIUM",
                    status=str(row.get("cycle_status", "")),
                    evidence=str(row.get("micro_sector", "")),
                    confidence=str(row.get("cycle_confidence", "")),
                    notes=str(row.get("notes", "")),
                )
            )


def _add_missing_disclosure_manual_review(
    *,
    universe_df: pd.DataFrame,
    disclosure_df: pd.DataFrame | None,
    manual_review_rows: list[dict[str, Any]],
) -> None:
    if universe_df.empty or "ticker" not in universe_df.columns:
        return
    disclosure_tickers = set(_ordered_tickers(disclosure_df))
    for ticker in _ordered_tickers(universe_df):
        if ticker in disclosure_tickers:
            continue
        manual_review_rows.append(
            _manual_review_row(
                ticker=ticker,
                module="disclosure_status",
                issue="DISCLOSURE_DATA_UNAVAILABLE",
                severity="MEDIUM",
                status="MANUAL_REVIEW_REQUIRED",
                evidence="disclosure_status=missing",
                confidence="low",
                notes="absence of disclosure rows is unknown/unavailable, not clean",
            )
        )


def _manual_review_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    deduped = []
    seen = set()
    for row in rows:
        marker = (row["ticker"], row["module"], row["issue"], row["evidence"])
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(row)
    return pd.DataFrame(deduped, columns=MANUAL_REVIEW_COLUMNS)


def _build_summary(
    *,
    run_id: str,
    run_size: str,
    started_at: str,
    finished_at: str,
    input_ticker_count: int,
    universe_df: pd.DataFrame,
    l0_trash_df: pd.DataFrame,
    l0_basic_df: pd.DataFrame,
    classification_df: pd.DataFrame,
    driver_df: pd.DataFrame,
    indicator_df: pd.DataFrame,
    sector_cycle_df: pd.DataFrame,
    module_status_records: list[dict[str, Any]],
    manual_review_queue: pd.DataFrame,
    errors_df: pd.DataFrame,
    warning_flags: list[str],
) -> dict[str, Any]:
    pass_counts = {
        "pre_l0_universe": _count_status(universe_df, "universe_status", {"PASS_UNIVERSE"}),
        "l0_trash_filter": _count_status(l0_trash_df, "l0_status", {"L0_PASS"}),
        "l0_basic_investability_filter": _count_status(
            l0_basic_df, "l0_basic_status", {"L0_INVESTABLE", "L0_WATCH_ONLY"}
        ),
        "l1_business_classification": _count_status(
            classification_df, "classification_status", {"CLASSIFIED"}
        ),
        "driver_registry": _count_status(
            driver_df, "driver_resolution_status", {"DRIVERS_RESOLVED"}
        ),
        "indicator_registry": _count_status(
            indicator_df, "indicator_resolution_status", {"INDICATORS_RESOLVED"}
        ),
        "sector_cycle_engine": _sector_cycle_non_insufficient_count(sector_cycle_df),
    }
    reject_counts = {
        "pre_l0_universe": _count_status(
            universe_df, "universe_status", {"REJECT_UNIVERSE"}
        ),
        "l0_trash_filter": _count_status(l0_trash_df, "l0_status", {"L0_REJECT"}),
        "l0_basic_investability_filter": _count_status(
            l0_basic_df, "l0_basic_status", {"L0_REJECT"}
        ),
        "l1_business_classification": _count_status(
            classification_df, "classification_status", {"NOT_CLASSIFIED"}
        ),
    }
    module_statuses = {
        record["stage"]: record["status"] for record in module_status_records
    }
    all_warnings = _dedupe(
        warning_flags
        + [
            warning
            for record in module_status_records
            for warning in record.get("warnings", [])
        ]
        + _list_flags(sector_cycle_df, "warning_flags")
    )
    insufficient_count = _insufficient_data_count(
        module_status_records=module_status_records,
        manual_review_queue=manual_review_queue,
        sector_cycle_df=sector_cycle_df,
        l0_trash_df=l0_trash_df,
        l0_basic_df=l0_basic_df,
        classification_df=classification_df,
    )
    error_count = int(len(errors_df))
    summary = {
        "run_id": run_id,
        "run_size": run_size,
        "started_at": started_at,
        "finished_at": finished_at,
        "input_ticker_count": int(input_ticker_count),
        "output_ticker_count": int(_output_ticker_count(l0_basic_df, universe_df)),
        "module_statuses": module_statuses,
        "pass_counts_by_layer": pass_counts,
        "reject_counts_by_layer": reject_counts,
        "manual_review_count": int(len(manual_review_queue)),
        "insufficient_data_count": int(insufficient_count),
        "warning_flags": all_warnings,
        "error_count": error_count,
        "next_action_recommendation": _next_action(
            error_count=error_count,
            insufficient_count=insufficient_count,
            manual_review_count=len(manual_review_queue),
            sector_cycle_df=sector_cycle_df,
        ),
    }
    return {field: summary[field] for field in DRY_RUN_SUMMARY_FIELDS}


def _next_action(
    *,
    error_count: int,
    insufficient_count: int,
    manual_review_count: int,
    sector_cycle_df: pd.DataFrame,
) -> str:
    if (
        error_count
        or insufficient_count
        or manual_review_count
        or _sector_cycle_has_insufficient_data(sector_cycle_df)
    ):
        return "FIX_INGESTION_BEFORE_STEP_19"
    return "READY_FOR_STEP_19_REVIEW"


def _ingestion_summary_markdown(
    summary: dict[str, Any], coverage_report: pd.DataFrame
) -> str:
    status_counts = (
        coverage_report["coverage_status"].value_counts().to_dict()
        if "coverage_status" in coverage_report.columns
        else {}
    )
    return "\n".join(
        [
            "# Ingestion Run Summary",
            "",
            f"- run_id: {summary['run_id']}",
            f"- run_size: {summary['run_size']}",
            f"- input_ticker_count: {summary['input_ticker_count']}",
            f"- coverage_status_counts: {json.dumps(status_counts, sort_keys=True)}",
            f"- next_action_recommendation: {summary['next_action_recommendation']}",
            "",
        ]
    )


def _dry_run_summary_markdown(summary: dict[str, Any]) -> str:
    lines = ["# Pipeline Dry Run Summary", ""]
    for field in DRY_RUN_SUMMARY_FIELDS:
        value = summary[field]
        if isinstance(value, (dict, list)):
            value = json.dumps(value, sort_keys=True)
        lines.append(f"- {field}: {value}")
    lines.append("")
    return "\n".join(lines)


def _module_status(
    stage: str,
    status: str,
    *,
    input_count: int = 0,
    output_count: int = 0,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    return {
        "stage": stage,
        "status": status,
        "input_count": int(input_count),
        "output_count": int(output_count),
        "warnings": _dedupe(warnings or []),
        "errors": _dedupe(errors or []),
        "notes": notes,
    }


def _stage_status(*, warnings: list[str], errors: list[str]) -> str:
    if errors:
        return "DATA_ERROR"
    if warnings:
        return "SUCCESS_WITH_WARNINGS"
    return "SUCCESS"


def _append_error(
    errors: list[dict[str, Any]],
    *,
    stage: str,
    error_code: str,
    message: str,
    dataset_name: str = "",
    ticker: str = "",
    notes: str = "",
) -> None:
    errors.append(
        {
            "stage": stage,
            "dataset_name": dataset_name,
            "ticker": ticker,
            "error_code": error_code,
            "message": message,
            "notes": notes,
        }
    )


def _manual_review_row(
    *,
    ticker: str,
    module: str,
    issue: str,
    severity: str,
    evidence: str,
    confidence: str,
    notes: str,
    status: str = "MANUAL_REVIEW_REQUIRED",
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "module": module,
        "issue": issue,
        "severity": severity,
        "status": status,
        "evidence": evidence,
        "confidence": confidence,
        "notes": notes,
    }


def _safe_load_mapping(path: str) -> dict[str, Any]:
    try:
        import yaml

        with Path(path).open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _quality_warning_flags(df: pd.DataFrame) -> list[str]:
    flags = _list_flags(df, "quality_warnings") + _list_flags(df, "quality_errors")
    if "quality_status" in df.columns:
        flags.extend(
            value
            for value in df["quality_status"].astype(str)
            if value and value != "VALID_DATA"
        )
    return _dedupe(flags)


def _list_flags(df: pd.DataFrame, column: str) -> list[str]:
    if not isinstance(df, pd.DataFrame) or df.empty or column not in df.columns:
        return []
    flags: list[str] = []
    for value in df[column]:
        flags.extend(str(item) for item in _value_list(value) if str(item))
    return _dedupe(flags)


def _ordered_tickers(df: pd.DataFrame | None) -> list[str]:
    if not isinstance(df, pd.DataFrame) or "ticker" not in df.columns:
        return []
    tickers: list[str] = []
    for value in df["ticker"]:
        ticker = _clean_ticker(value)
        if ticker and ticker not in tickers:
            tickers.append(ticker)
    return tickers


def _classified_micro_sectors(classification_df: pd.DataFrame) -> list[str]:
    if classification_df.empty or "primary_micro_sector" not in classification_df.columns:
        return []
    sectors: list[str] = []
    for value in classification_df["primary_micro_sector"]:
        sector = str(value).strip()
        if sector and sector not in {"unknown", "UNKNOWN"} and sector not in sectors:
            sectors.append(sector)
    return sectors


def _driver_ids_from_row(row: pd.Series) -> list[str]:
    driver_ids = []
    for column in ["primary_drivers", "secondary_drivers"]:
        driver_ids.extend(_value_list(row.get(column)))
    for item in _value_list(row.get("resolved_drivers")):
        if isinstance(item, dict):
            driver_ids.append(item.get("driver_id", ""))
        else:
            driver_ids.append(str(item))
    return _dedupe([str(item) for item in driver_ids if str(item).strip()])


def _indicator_ids(indicators: list[dict[str, Any]]) -> list[str]:
    return _dedupe(
        [
            str(indicator.get("indicator_id", "")).strip()
            for indicator in indicators
            if str(indicator.get("indicator_id", "")).strip()
        ]
    )


def _count_status(df: pd.DataFrame, column: str, statuses: set[str]) -> int:
    if df.empty or column not in df.columns:
        return 0
    normalized = {status.upper() for status in statuses}
    return int(df[column].map(lambda value: str(value).strip().upper() in normalized).sum())


def _sector_cycle_non_insufficient_count(sector_cycle_df: pd.DataFrame) -> int:
    if sector_cycle_df.empty or "cycle_status" not in sector_cycle_df.columns:
        return 0
    return int(
        sector_cycle_df["cycle_status"]
        .map(lambda value: str(value).strip() != "INSUFFICIENT_DATA_FOR_SECTOR_CYCLE")
        .sum()
    )


def _sector_cycle_has_insufficient_data(sector_cycle_df: pd.DataFrame) -> bool:
    if sector_cycle_df.empty or "cycle_status" not in sector_cycle_df.columns:
        return True
    return bool(
        (
            sector_cycle_df["cycle_status"]
            == "INSUFFICIENT_DATA_FOR_SECTOR_CYCLE"
        ).any()
    )


def _insufficient_data_count(
    *,
    module_status_records: list[dict[str, Any]],
    manual_review_queue: pd.DataFrame,
    sector_cycle_df: pd.DataFrame,
    l0_trash_df: pd.DataFrame,
    l0_basic_df: pd.DataFrame,
    classification_df: pd.DataFrame,
) -> int:
    count = 0
    for record in module_status_records:
        values = [record.get("status", ""), *record.get("warnings", []), *record.get("errors", [])]
        count += sum("INSUFFICIENT" in str(value) or "MISSING" in str(value) for value in values)
    for df, column in [
        (sector_cycle_df, "cycle_status"),
        (l0_trash_df, "l0_status"),
        (l0_basic_df, "l0_basic_status"),
        (classification_df, "classification_notes"),
    ]:
        if not df.empty and column in df.columns:
            count += int(df[column].map(lambda value: "INSUFFICIENT" in str(value)).sum())
    if not manual_review_queue.empty and "issue" in manual_review_queue.columns:
        count += int(
            manual_review_queue["issue"].map(
                lambda value: "INSUFFICIENT" in str(value) or "UNAVAILABLE" in str(value)
            ).sum()
        )
    return int(count)


def _output_ticker_count(l0_basic_df: pd.DataFrame, universe_df: pd.DataFrame) -> int:
    if not l0_basic_df.empty:
        return len(_ordered_tickers(l0_basic_df))
    return len(_ordered_tickers(universe_df))


def _review_status(status: str) -> bool:
    normalized = status.upper()
    return (
        "MANUAL_REVIEW" in normalized
        or "INSUFFICIENT" in normalized
        or normalized in {"L0_REJECT", "NOT_CLASSIFIED", "REJECT_UNIVERSE"}
    )


def _severity_for_issue(issue: str) -> str:
    normalized = issue.upper()
    if "CRITICAL" in normalized or "REJECT" in normalized:
        return "HIGH"
    if "MISSING" in normalized or "INSUFFICIENT" in normalized:
        return "MEDIUM"
    return "LOW"


def _value_list(value: Any) -> list[Any]:
    if _is_missing(value):
        return []
    if isinstance(value, list):
        return [item for item in value if not _is_missing(item)]
    if isinstance(value, tuple) or isinstance(value, set):
        return [item for item in value if not _is_missing(item)]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped == "[]":
            return []
        if ";" in stripped:
            return [part.strip() for part in stripped.split(";") if part.strip()]
        if "|" in stripped:
            return [part.strip() for part in stripped.split("|") if part.strip()]
        return [stripped]
    return [value]


def _row_count(df: Any) -> int:
    return int(len(df)) if isinstance(df, pd.DataFrame) else 0


def _clean_ticker(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip().upper()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if _is_missing(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


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


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(values))


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _safe_token(value: Any) -> str:
    token = str(value).replace(":", "").replace("+", "").replace("-", "")
    return "".join(character if character.isalnum() else "_" for character in token)
