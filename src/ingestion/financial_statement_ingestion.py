"""Bulk ingestion for financial statement summary raw inputs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingestion.contracts import (
    DEFAULT_CONTRACTS_PATH,
    PROHIBITED_RECOMMENDATION_FIELDS,
    load_ingestion_contracts,
    validate_dataset_columns,
)
from src.ingestion.manifest import (
    create_ingestion_manifest_record,
    save_ingestion_manifest,
)


REAL_SOURCE_UNAVAILABLE = "REAL_SOURCE_UNAVAILABLE"
SUPPORTED_MODES = {
    "manual_csv",
    "manual_xlsx",
    "mock",
    "real_vnstock_optional",
    "external_vendor_optional",
}

DEFAULT_RAW_OUTPUT_DIR = Path("data/raw")
DEFAULT_COVERAGE_OUTPUT_DIR = Path("data/reports/ingestion_coverage")
DEFAULT_MANIFEST_DIR = Path("data/reports/ingestion_manifests")
DEFAULT_MISSING_REPORT_DIR = Path("data/reports/ingestion_missing_data")

FINANCIAL_STATEMENT_RAW_FILENAME = "financial_statement_summary_raw.csv"

FINANCIAL_STATEMENT_OUTPUT_COLUMNS = [
    "ticker",
    "period",
    "period_type",
    "statement_type",
    "fiscal_year",
    "quarter",
    "currency",
    "unit_scale",
    "revenue",
    "gross_profit",
    "operating_profit",
    "net_profit",
    "total_assets",
    "total_liabilities",
    "equity",
    "cash",
    "short_term_debt",
    "long_term_debt",
    "operating_cash_flow",
    "inventory",
    "source",
    "source_url",
    "fetch_time",
    "confidence_raw",
    "notes",
]

FINANCIAL_NUMERIC_COLUMNS = [
    "revenue",
    "gross_profit",
    "operating_profit",
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

MISSING_REPORT_COLUMNS = [
    "ticker",
    "period",
    "field",
    "issue",
    "source",
    "source_url",
    "notes",
]


def ingest_financial_statement_data(
    *,
    mode: str,
    input_path: str | Path | None = None,
    requested_tickers: list[str] | None = None,
    raw_output_dir: str | Path = DEFAULT_RAW_OUTPUT_DIR,
    manifest_dir: str | Path = DEFAULT_MANIFEST_DIR,
    coverage_output_dir: str | Path = DEFAULT_COVERAGE_OUTPUT_DIR,
    missing_report_dir: str | Path = DEFAULT_MISSING_REPORT_DIR,
    contracts_path: str | Path = DEFAULT_CONTRACTS_PATH,
    run_id: str | None = None,
    fetch_time: str | None = None,
) -> dict[str, Any]:
    """Ingest financial statement rows into raw standardized CSV."""

    if mode not in SUPPORTED_MODES:
        raise ValueError(
            f"Unsupported financial statement ingestion mode: {mode}. "
            f"Supported modes: {', '.join(sorted(SUPPORTED_MODES))}."
        )

    resolved_run_id = run_id or _default_run_id()
    resolved_fetch_time = fetch_time or _utc_now_iso()
    normalized_requested = _normalize_requested_tickers(requested_tickers)

    if mode == "real_vnstock_optional":
        return _real_source_unavailable_result(
            run_id=resolved_run_id,
            requested_tickers=normalized_requested,
            manifest_dir=manifest_dir,
            fetch_time=resolved_fetch_time,
        )

    contracts = load_ingestion_contracts(contracts_path)
    raw_input = _load_input(
        mode=mode,
        input_path=input_path,
        fetch_time=resolved_fetch_time,
        requested_tickers=normalized_requested,
    )
    input_label = "mock" if mode == "mock" else str(input_path)
    validation = validate_dataset_columns(
        raw_input, "financial_statement_summary", contracts
    )

    if not validation["is_valid"]:
        manifest_path = _write_manifest(
            run_id=resolved_run_id,
            mode=mode,
            input_path=input_label,
            output_path="",
            df=raw_input,
            success_count=0,
            failed_count=max(1, len(normalized_requested)),
            missing_required_columns=validation["missing_required_columns"],
            warnings=validation["warnings"],
            errors=validation["errors"],
            data_quality_status=validation["data_quality_status"],
            manifest_dir=manifest_dir,
            finished_at=resolved_fetch_time,
            notes="financial statement validation failed before raw output was written",
        )
        return {
            "status": "DATA_ERROR",
            "run_id": resolved_run_id,
            "mode": mode,
            "raw_output_path": "",
            "manifest_path": manifest_path,
            "coverage_report_path": "",
            "missing_data_report_path": "",
            "coverage": {},
            "validation_result": validation,
            "errors": validation["errors"],
            "warnings": validation["warnings"],
        }

    financial_raw = standardize_financial_statement_raw(
        raw_input, mode=mode, fetch_time=resolved_fetch_time
    )
    coverage = build_financial_statement_coverage(
        financial_raw=financial_raw,
        requested_tickers=normalized_requested,
    )
    missing_report = build_financial_missing_data_report(
        financial_raw=financial_raw,
        requested_tickers=normalized_requested,
    )

    raw_output_path = save_financial_statement_raw(
        financial_raw=financial_raw,
        raw_output_dir=raw_output_dir,
    )
    coverage_report_path = save_coverage_report(
        coverage=coverage,
        run_id=resolved_run_id,
        coverage_output_dir=coverage_output_dir,
    )
    missing_report_path = save_missing_data_report(
        missing_report=missing_report,
        run_id=resolved_run_id,
        missing_report_dir=missing_report_dir,
    )
    manifest_path = _write_manifest(
        run_id=resolved_run_id,
        mode=mode,
        input_path=input_label,
        output_path=raw_output_path,
        df=financial_raw,
        success_count=coverage["ticker_count_with_financials"],
        failed_count=coverage["ticker_count_missing_financials"],
        missing_required_columns=[],
        warnings=coverage["warnings"],
        errors=[],
        data_quality_status=(
            "MANUAL_REVIEW_REQUIRED" if coverage["warnings"] else "VALID_DATA"
        ),
        manifest_dir=manifest_dir,
        finished_at=resolved_fetch_time,
        notes="raw financial statement ingestion completed",
    )

    status = "SUCCESS_WITH_WARNINGS" if coverage["warnings"] else "SUCCESS"
    return {
        "status": status,
        "run_id": resolved_run_id,
        "mode": mode,
        "raw_output_path": raw_output_path,
        "manifest_path": manifest_path,
        "coverage_report_path": coverage_report_path,
        "missing_data_report_path": missing_report_path,
        "coverage": coverage,
        "validation_result": validation,
        "errors": [],
        "warnings": coverage["warnings"],
    }


def standardize_financial_statement_raw(
    df: pd.DataFrame, mode: str, fetch_time: str | None = None
) -> pd.DataFrame:
    """Return standardized financial data without filling missing BCTC values."""

    output = _copy_with_output_columns(df, FINANCIAL_STATEMENT_OUTPUT_COLUMNS)
    output["ticker"] = output["ticker"].map(_normalize_ticker)
    output["period"] = output["period"].map(_clean_text)
    output["period_type"] = output["period_type"].map(_clean_text)
    output["statement_type"] = output["statement_type"].map(_clean_text)
    output["fiscal_year"] = output["fiscal_year"].map(_clean_text)
    output["quarter"] = output["quarter"].map(_clean_text)
    output["currency"] = output["currency"].map(_clean_text)
    output["unit_scale"] = output["unit_scale"].map(_clean_text)

    for column in FINANCIAL_NUMERIC_COLUMNS:
        output[column] = pd.to_numeric(output[column], errors="coerce")

    output["source"] = output["source"].map(_clean_text)
    output["source_url"] = output["source_url"].map(_clean_text)
    output["fetch_time"] = _fill_missing_text(
        output["fetch_time"], fetch_time or _utc_now_iso()
    )
    output["confidence_raw"] = _fill_missing_text(
        output["confidence_raw"], _confidence_for_mode(mode)
    )
    output["notes"] = _fill_missing_text(output["notes"], _notes_for_mode(mode))
    return output[FINANCIAL_STATEMENT_OUTPUT_COLUMNS]


def build_financial_statement_coverage(
    *,
    financial_raw: pd.DataFrame,
    requested_tickers: list[str] | None = None,
) -> dict[str, Any]:
    """Build financial statement coverage and warning summary."""

    normalized_requested = _normalize_requested_tickers(requested_tickers)
    present_tickers = _ticker_set(financial_raw)
    requested_set = set(normalized_requested) if normalized_requested else present_tickers
    missing_tickers = sorted(requested_set - present_tickers)
    source_conflicts = _source_conflicts(financial_raw)

    coverage = {
        "ticker_count_requested": len(requested_set),
        "ticker_count_with_financials": len(requested_set.intersection(present_tickers)),
        "ticker_count_missing_financials": len(missing_tickers),
        "missing_financial_tickers": missing_tickers,
        "period_count": _period_count(financial_raw),
        "min_period": _min_period(financial_raw),
        "max_period": _max_period(financial_raw),
        "missing_revenue_count": _missing_count(financial_raw, "revenue"),
        "missing_net_profit_count": _missing_count(financial_raw, "net_profit"),
        "missing_equity_count": _missing_count(financial_raw, "equity"),
        "missing_cfo_count": _missing_count(financial_raw, "operating_cash_flow"),
        "negative_equity_count": _negative_equity_count(financial_raw),
        "duplicate_ticker_period_count": _duplicate_ticker_period_count(financial_raw),
        "source_count": _source_count(financial_raw),
        "source_conflict_count": len(source_conflicts),
        "source_conflicts": source_conflicts,
        "row_count": int(len(financial_raw)),
        "warnings": [],
    }

    if coverage["ticker_count_missing_financials"]:
        coverage["warnings"].append("MISSING_FINANCIALS_FOR_REQUESTED_TICKER")
    if coverage["missing_revenue_count"]:
        coverage["warnings"].append("MISSING_REVENUE")
    if coverage["missing_net_profit_count"]:
        coverage["warnings"].append("MISSING_NET_PROFIT")
    if coverage["missing_equity_count"]:
        coverage["warnings"].append("MISSING_EQUITY")
    if coverage["missing_cfo_count"]:
        coverage["warnings"].append("MISSING_OPERATING_CASH_FLOW")
    if coverage["negative_equity_count"]:
        coverage["warnings"].append("NEGATIVE_EQUITY")
    if coverage["duplicate_ticker_period_count"]:
        coverage["warnings"].append("DUPLICATE_TICKER_PERIOD")
    if coverage["source_conflict_count"]:
        coverage["warnings"].append("DATA_CONFLICT")

    coverage["warnings"] = _dedupe(coverage["warnings"])
    return coverage


def build_financial_missing_data_report(
    *,
    financial_raw: pd.DataFrame,
    requested_tickers: list[str] | None = None,
) -> pd.DataFrame:
    """Return row-level missing/negative/conflict report without changing values."""

    rows: list[dict[str, Any]] = []
    for _, row in financial_raw.iterrows():
        for field in [
            "revenue",
            "net_profit",
            "equity",
            "operating_cash_flow",
        ]:
            if _is_missing(row.get(field)):
                rows.append(_missing_report_row(row, field, f"MISSING_{field.upper()}"))

        equity = pd.to_numeric(row.get("equity"), errors="coerce")
        if not pd.isna(equity) and equity < 0:
            rows.append(_missing_report_row(row, "equity", "NEGATIVE_EQUITY"))

    for conflict in _source_conflicts(financial_raw):
        rows.append(
            {
                "ticker": conflict["ticker"],
                "period": conflict["period"],
                "field": conflict["field"],
                "issue": "DATA_CONFLICT",
                "source": "|".join(conflict["sources"]),
                "source_url": "",
                "notes": "conflicting values from multiple sources",
            }
        )

    present_tickers = _ticker_set(financial_raw)
    for ticker in sorted(set(_normalize_requested_tickers(requested_tickers)) - present_tickers):
        rows.append(
            {
                "ticker": ticker,
                "period": "",
                "field": "financial_statement_summary",
                "issue": "MISSING_FINANCIALS_FOR_REQUESTED_TICKER",
                "source": "",
                "source_url": "",
                "notes": "requested ticker has no financial statement rows",
            }
        )

    return pd.DataFrame(rows, columns=MISSING_REPORT_COLUMNS)


def save_financial_statement_raw(
    *,
    financial_raw: pd.DataFrame,
    raw_output_dir: str | Path = DEFAULT_RAW_OUTPUT_DIR,
) -> str:
    """Save raw financial statement rows and return the output path."""

    output_dir = Path(raw_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / FINANCIAL_STATEMENT_RAW_FILENAME
    financial_raw.to_csv(output_path, index=False)
    return str(output_path)


def save_coverage_report(
    *,
    coverage: dict[str, Any],
    run_id: str,
    coverage_output_dir: str | Path = DEFAULT_COVERAGE_OUTPUT_DIR,
) -> str:
    """Save financial coverage JSON and return the output path."""

    output_dir = Path(coverage_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (
        output_dir
        / f"{_safe_file_token(run_id)}_financial_statement_summary_coverage.json"
    )
    output_path.write_text(
        json.dumps(coverage, indent=2, sort_keys=True), encoding="utf-8"
    )
    return str(output_path)


def save_missing_data_report(
    *,
    missing_report: pd.DataFrame,
    run_id: str,
    missing_report_dir: str | Path = DEFAULT_MISSING_REPORT_DIR,
) -> str:
    """Save missing-data report CSV and return the output path."""

    output_dir = Path(missing_report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (
        output_dir
        / f"{_safe_file_token(run_id)}_financial_statement_missing_data.csv"
    )
    missing_report.to_csv(output_path, index=False)
    return str(output_path)


def has_prohibited_recommendation_columns(df: pd.DataFrame) -> bool:
    """Return True if raw output contains prohibited recommendation fields."""

    normalized_columns = {str(column).strip().lower() for column in df.columns}
    return bool(PROHIBITED_RECOMMENDATION_FIELDS.intersection(normalized_columns))


def _load_input(
    *,
    mode: str,
    input_path: str | Path | None,
    fetch_time: str,
    requested_tickers: list[str],
) -> pd.DataFrame:
    if mode == "mock":
        return _mock_financial_statement_rows(fetch_time, requested_tickers)

    if input_path is None:
        raise ValueError(f"input_path is required for {mode} mode.")

    path = Path(input_path)
    if mode == "manual_csv":
        return pd.read_csv(path)
    if mode == "manual_xlsx":
        return pd.read_excel(path)
    if mode == "external_vendor_optional":
        if path.suffix.lower() == ".csv":
            return pd.read_csv(path)
        if path.suffix.lower() in {".xlsx", ".xls"}:
            return pd.read_excel(path)
        raise ValueError("external_vendor_optional requires a CSV or XLSX file.")

    raise ValueError(f"Unsupported mode: {mode}")


def _mock_financial_statement_rows(fetch_time: str, tickers: list[str]) -> pd.DataFrame:
    requested = tickers or ["MOCK1", "MOCK2"]
    rows: list[dict[str, Any]] = []
    for index, ticker in enumerate(requested, start=1):
        base_value = index * 1000
        rows.append(
            {
                "ticker": ticker,
                "period": "2026Q1",
                "period_type": "quarter",
                "statement_type": "summary",
                "fiscal_year": "2026",
                "quarter": "Q1",
                "currency": "MOCK_CURRENCY",
                "unit_scale": "mock_unit",
                "revenue": base_value,
                "gross_profit": base_value * 0.3,
                "operating_profit": base_value * 0.2,
                "net_profit": base_value * 0.1,
                "total_assets": base_value * 5,
                "total_liabilities": base_value * 2,
                "equity": base_value * 3,
                "cash": base_value * 0.5,
                "short_term_debt": base_value * 0.2,
                "long_term_debt": base_value * 0.4,
                "operating_cash_flow": base_value * 0.15,
                "inventory": base_value * 0.25,
                "source": "MOCK_SAMPLE",
                "source_url": f"mock://financial_statement_summary/{ticker}",
                "fetch_time": fetch_time,
                "confidence_raw": "mock",
                "notes": "mock/sample financial data only; not real Vietnamese BCTC",
            }
        )
    return pd.DataFrame(rows)


def _real_source_unavailable_result(
    *,
    run_id: str,
    requested_tickers: list[str],
    manifest_dir: str | Path,
    fetch_time: str,
) -> dict[str, Any]:
    manifest = create_ingestion_manifest_record(
        run_id=run_id,
        dataset_name="financial_statement_summary",
        mode="real_vnstock_optional",
        started_at=fetch_time,
        finished_at=fetch_time,
        failed_count=max(1, len(requested_tickers)),
        errors=[REAL_SOURCE_UNAVAILABLE],
        data_quality_status=REAL_SOURCE_UNAVAILABLE,
        notes=(
            "Optional real vnstock adapter is not implemented or unavailable; "
            "no live data was fetched."
        ),
    )
    manifest_path = save_ingestion_manifest(manifest, output_dir=manifest_dir)
    return {
        "status": REAL_SOURCE_UNAVAILABLE,
        "run_id": run_id,
        "mode": "real_vnstock_optional",
        "raw_output_path": "",
        "manifest_path": manifest_path,
        "coverage_report_path": "",
        "missing_data_report_path": "",
        "coverage": {},
        "validation_result": {},
        "errors": [REAL_SOURCE_UNAVAILABLE],
        "warnings": ["Optional real source unavailable; no live data fetched."],
    }


def _write_manifest(
    *,
    run_id: str,
    mode: str,
    input_path: str,
    output_path: str,
    df: pd.DataFrame,
    success_count: int,
    failed_count: int,
    missing_required_columns: list[str],
    warnings: list[str],
    errors: list[str],
    data_quality_status: str,
    manifest_dir: str | Path,
    finished_at: str,
    notes: str,
) -> str:
    record = create_ingestion_manifest_record(
        run_id=run_id,
        dataset_name="financial_statement_summary",
        mode=mode,
        input_path=input_path,
        output_path=output_path,
        started_at=finished_at,
        finished_at=finished_at,
        row_count=int(len(df)),
        ticker_count=len(_ticker_set(df)),
        success_count=success_count,
        failed_count=failed_count,
        missing_required_columns=missing_required_columns,
        warnings=warnings,
        errors=errors,
        data_quality_status=data_quality_status,
        notes=notes,
    )
    return save_ingestion_manifest(record, output_dir=manifest_dir)


def _missing_report_row(row: pd.Series, field: str, issue: str) -> dict[str, Any]:
    return {
        "ticker": _normalize_ticker(row.get("ticker")),
        "period": _clean_text(row.get("period")),
        "field": field,
        "issue": issue,
        "source": _clean_text(row.get("source")),
        "source_url": _clean_text(row.get("source_url")),
        "notes": _clean_text(row.get("notes")),
    }


def _source_conflicts(financial_raw: pd.DataFrame) -> list[dict[str, Any]]:
    if not {"ticker", "period", "source"}.issubset(financial_raw.columns):
        return []

    conflicts: list[dict[str, Any]] = []
    for (ticker, period), group in financial_raw.groupby(["ticker", "period"], dropna=False):
        if group["source"].map(_clean_text).nunique() < 2:
            continue
        for field in FINANCIAL_NUMERIC_COLUMNS:
            values = pd.to_numeric(group[field], errors="coerce").dropna()
            if values.nunique() > 1:
                conflicts.append(
                    {
                        "ticker": _normalize_ticker(ticker),
                        "period": _clean_text(period),
                        "field": field,
                        "sources": sorted(group["source"].map(_clean_text).unique()),
                    }
                )
    return conflicts


def _missing_count(df: pd.DataFrame, column: str) -> int:
    if column not in df.columns:
        return int(len(df))
    return int(df[column].map(_is_missing).sum())


def _negative_equity_count(df: pd.DataFrame) -> int:
    if "equity" not in df.columns:
        return 0
    equity = pd.to_numeric(df["equity"], errors="coerce")
    return int((equity < 0).sum())


def _duplicate_ticker_period_count(df: pd.DataFrame) -> int:
    if not {"ticker", "period"}.issubset(df.columns):
        return 0
    normalized = df.copy()
    normalized["ticker"] = normalized["ticker"].map(_normalize_ticker)
    normalized["period"] = normalized["period"].map(_clean_text)
    duplicate_mask = normalized.duplicated(subset=["ticker", "period"], keep=False)
    return int(duplicate_mask.sum())


def _source_count(df: pd.DataFrame) -> int:
    if "source" not in df.columns:
        return 0
    sources = df["source"].map(_clean_text)
    return int(sources[sources.map(bool)].nunique())


def _ticker_set(df: pd.DataFrame) -> set[str]:
    if "ticker" not in df.columns:
        return set()
    return {ticker for ticker in df["ticker"].map(_normalize_ticker) if ticker}


def _period_count(df: pd.DataFrame) -> int:
    if "period" not in df.columns:
        return 0
    periods = df["period"].map(_clean_text)
    return int(periods[periods.map(bool)].nunique())


def _min_period(df: pd.DataFrame) -> str:
    periods = _sorted_periods(df)
    return periods[0] if periods else ""


def _max_period(df: pd.DataFrame) -> str:
    periods = _sorted_periods(df)
    return periods[-1] if periods else ""


def _sorted_periods(df: pd.DataFrame) -> list[str]:
    if "period" not in df.columns:
        return []
    return sorted({period for period in df["period"].map(_clean_text) if period})


def _copy_with_output_columns(df: pd.DataFrame, output_columns: list[str]) -> pd.DataFrame:
    output = df.copy(deep=True)
    for column in output_columns:
        if column not in output.columns:
            output[column] = pd.NA
    return output[output_columns].copy()


def _fill_missing_text(series: pd.Series, default: str) -> pd.Series:
    cleaned = series.map(_clean_text)
    return cleaned.where(cleaned.map(bool), default)


def _normalize_requested_tickers(tickers: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for ticker in tickers or []:
        normalized_ticker = _normalize_ticker(ticker)
        if normalized_ticker and normalized_ticker not in normalized:
            normalized.append(normalized_ticker)
    return normalized


def _confidence_for_mode(mode: str) -> str:
    if mode == "mock":
        return "mock"
    if mode == "external_vendor_optional":
        return "vendor_file"
    return "medium"


def _notes_for_mode(mode: str) -> str:
    if mode == "mock":
        return "mock/sample financial data only; not real Vietnamese BCTC"
    if mode == "external_vendor_optional":
        return "external vendor financial file; requires downstream validation"
    return "manual financial statement input; requires downstream validation"


def _normalize_ticker(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip().upper()


def _clean_text(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip()


def _is_missing(value: Any) -> bool:
    if value is None or pd.isna(value):
        return True
    return isinstance(value, str) and not value.strip()


def _default_run_id() -> str:
    return f"financial_statement_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _safe_file_token(value: Any) -> str:
    token = str(value).strip().replace("\\", "_").replace("/", "_")
    return "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in token
    )


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(values))
