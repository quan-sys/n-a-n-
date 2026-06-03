"""Bulk ingestion for disclosure status and warning event raw inputs."""

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
    "real_exchange_optional",
    "external_vendor_optional",
}

SUPPORTED_EVENT_TYPES = {
    "AUDIT_WARNING",
    "DISCLOSURE_VIOLATION",
    "TRADING_RESTRICTION",
    "SUSPENSION",
    "DELISTING_WARNING",
    "LATE_FINANCIAL_REPORT",
    "NEGATIVE_EQUITY_WARNING",
    "REGULATORY_SANCTION",
    "CORPORATE_GOVERNANCE_WARNING",
    "OTHER",
    "UNKNOWN",
}

SUPPORTED_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"}
MANUAL_REVIEW_SEVERITIES = {"HIGH", "CRITICAL"}

DEFAULT_RAW_OUTPUT_DIR = Path("data/raw")
DEFAULT_COVERAGE_OUTPUT_DIR = Path("data/reports/ingestion_coverage")
DEFAULT_MANIFEST_DIR = Path("data/reports/ingestion_manifests")
DEFAULT_MANUAL_REVIEW_DIR = Path("data/reports/manual_review_candidates")

DISCLOSURE_STATUS_RAW_FILENAME = "disclosure_status_raw.csv"

DISCLOSURE_STATUS_OUTPUT_COLUMNS = [
    "ticker",
    "event_date",
    "event_type",
    "severity",
    "title",
    "description",
    "source",
    "source_url",
    "fetch_time",
    "confidence_raw",
    "notes",
]

MANUAL_REVIEW_COLUMNS = [
    "ticker",
    "event_date",
    "event_type",
    "severity",
    "review_reason",
    "title",
    "source",
    "source_url",
    "notes",
]


def ingest_disclosure_warning_data(
    *,
    mode: str,
    input_path: str | Path | None = None,
    requested_tickers: list[str] | None = None,
    raw_output_dir: str | Path = DEFAULT_RAW_OUTPUT_DIR,
    manifest_dir: str | Path = DEFAULT_MANIFEST_DIR,
    coverage_output_dir: str | Path = DEFAULT_COVERAGE_OUTPUT_DIR,
    manual_review_dir: str | Path = DEFAULT_MANUAL_REVIEW_DIR,
    contracts_path: str | Path = DEFAULT_CONTRACTS_PATH,
    run_id: str | None = None,
    fetch_time: str | None = None,
) -> dict[str, Any]:
    """Ingest disclosure/warning rows into raw standardized CSV."""

    if mode not in SUPPORTED_MODES:
        raise ValueError(
            f"Unsupported disclosure ingestion mode: {mode}. "
            f"Supported modes: {', '.join(sorted(SUPPORTED_MODES))}."
        )

    resolved_run_id = run_id or _default_run_id()
    resolved_fetch_time = fetch_time or _utc_now_iso()
    normalized_requested = _normalize_requested_tickers(requested_tickers)

    if mode == "real_exchange_optional":
        return _real_source_unavailable_result(
            run_id=resolved_run_id,
            requested_tickers=normalized_requested,
            manifest_dir=manifest_dir,
            manual_review_dir=manual_review_dir,
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
    validation = validate_dataset_columns(raw_input, "disclosure_status", contracts)

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
            notes="disclosure validation failed before raw output was written",
        )
        return {
            "status": "DATA_ERROR",
            "run_id": resolved_run_id,
            "mode": mode,
            "raw_output_path": "",
            "manifest_path": manifest_path,
            "coverage_report_path": "",
            "manual_review_candidate_path": "",
            "coverage": {},
            "validation_result": validation,
            "errors": validation["errors"],
            "warnings": validation["warnings"],
        }

    disclosure_raw = standardize_disclosure_warning_raw(
        raw_input, mode=mode, fetch_time=resolved_fetch_time
    )
    coverage = build_disclosure_warning_coverage(
        disclosure_raw=disclosure_raw,
        requested_tickers=normalized_requested,
    )
    manual_review_candidates = build_manual_review_candidates(
        disclosure_raw=disclosure_raw,
        requested_tickers=normalized_requested,
    )

    raw_output_path = save_disclosure_warning_raw(
        disclosure_raw=disclosure_raw,
        raw_output_dir=raw_output_dir,
    )
    coverage_report_path = save_coverage_report(
        coverage=coverage,
        run_id=resolved_run_id,
        coverage_output_dir=coverage_output_dir,
    )
    manual_review_candidate_path = save_manual_review_candidates(
        manual_review_candidates=manual_review_candidates,
        run_id=resolved_run_id,
        manual_review_dir=manual_review_dir,
    )
    manifest_path = _write_manifest(
        run_id=resolved_run_id,
        mode=mode,
        input_path=input_label,
        output_path=raw_output_path,
        df=disclosure_raw,
        success_count=coverage["ticker_count_with_disclosure_rows"],
        failed_count=coverage["ticker_count_without_disclosure_rows"],
        missing_required_columns=[],
        warnings=coverage["warnings"],
        errors=[],
        data_quality_status=(
            "MANUAL_REVIEW_REQUIRED" if coverage["warnings"] else "VALID_DATA"
        ),
        manifest_dir=manifest_dir,
        finished_at=resolved_fetch_time,
        notes="raw disclosure/warning ingestion completed",
    )

    status = "SUCCESS_WITH_WARNINGS" if coverage["warnings"] else "SUCCESS"
    return {
        "status": status,
        "run_id": resolved_run_id,
        "mode": mode,
        "raw_output_path": raw_output_path,
        "manifest_path": manifest_path,
        "coverage_report_path": coverage_report_path,
        "manual_review_candidate_path": manual_review_candidate_path,
        "coverage": coverage,
        "validation_result": validation,
        "errors": [],
        "warnings": coverage["warnings"],
    }


def standardize_disclosure_warning_raw(
    df: pd.DataFrame, mode: str, fetch_time: str | None = None
) -> pd.DataFrame:
    """Return standardized disclosure rows while preserving unknown values."""

    output = _copy_with_output_columns(df, DISCLOSURE_STATUS_OUTPUT_COLUMNS)
    output["ticker"] = output["ticker"].map(_normalize_ticker)
    output["event_date"] = output["event_date"].map(_clean_text)
    output["event_type"] = output["event_type"].map(_normalize_event_label)
    output["severity"] = output["severity"].map(_normalize_event_label)
    output["title"] = output["title"].map(_clean_text)
    output["description"] = output["description"].map(_clean_text)
    output["source"] = output["source"].map(_clean_text)
    output["source_url"] = output["source_url"].map(_clean_text)
    output["fetch_time"] = _fill_missing_text(
        output["fetch_time"], fetch_time or _utc_now_iso()
    )
    output["confidence_raw"] = _fill_missing_text(
        output["confidence_raw"], _confidence_for_mode(mode)
    )
    output["notes"] = _fill_missing_text(output["notes"], _notes_for_mode(mode))
    return output[DISCLOSURE_STATUS_OUTPUT_COLUMNS]


def build_disclosure_warning_coverage(
    *,
    disclosure_raw: pd.DataFrame,
    requested_tickers: list[str] | None = None,
) -> dict[str, Any]:
    """Build disclosure coverage and warning summary."""

    normalized_requested = _normalize_requested_tickers(requested_tickers)
    present_tickers = _ticker_set(disclosure_raw)
    requested_set = set(normalized_requested) if normalized_requested else present_tickers
    missing_tickers = sorted(requested_set - present_tickers)
    unknown_event_type_count = _unknown_event_type_count(disclosure_raw)
    unknown_severity_count = _unknown_severity_count(disclosure_raw)

    coverage = {
        "ticker_count_requested": len(requested_set),
        "ticker_count_with_disclosure_rows": len(requested_set.intersection(present_tickers)),
        "ticker_count_without_disclosure_rows": len(missing_tickers),
        "tickers_without_disclosure_rows": missing_tickers,
        "high_severity_count": _severity_count(disclosure_raw, "HIGH"),
        "critical_severity_count": _severity_count(disclosure_raw, "CRITICAL"),
        "unknown_severity_count": unknown_severity_count,
        "unknown_event_type_count": unknown_event_type_count,
        "missing_source_url_count": _missing_count(disclosure_raw, "source_url"),
        "event_type_counts": _event_type_counts(disclosure_raw),
        "row_count": int(len(disclosure_raw)),
        "warnings": [],
    }

    if coverage["ticker_count_without_disclosure_rows"]:
        coverage["warnings"].append("DISCLOSURE_DATA_UNAVAILABLE_FOR_REQUESTED_TICKER")
    if coverage["high_severity_count"]:
        coverage["warnings"].append("HIGH_SEVERITY_DISCLOSURE")
    if coverage["critical_severity_count"]:
        coverage["warnings"].append("CRITICAL_SEVERITY_DISCLOSURE")
    if unknown_severity_count:
        coverage["warnings"].append("UNKNOWN_SEVERITY")
    if unknown_event_type_count:
        coverage["warnings"].append("UNKNOWN_EVENT_TYPE")
    if coverage["missing_source_url_count"]:
        coverage["warnings"].append("MISSING_SOURCE_URL")

    coverage["warnings"] = _dedupe(coverage["warnings"])
    return coverage


def build_manual_review_candidates(
    *,
    disclosure_raw: pd.DataFrame,
    requested_tickers: list[str] | None = None,
) -> pd.DataFrame:
    """Return manual-review candidates from severe, unknown, or absent data."""

    rows: list[dict[str, Any]] = []
    for _, row in disclosure_raw.iterrows():
        reasons: list[str] = []
        severity = _clean_text(row.get("severity")).upper()
        event_type = _clean_text(row.get("event_type")).upper()
        if severity in MANUAL_REVIEW_SEVERITIES:
            reasons.append(f"{severity}_SEVERITY_DISCLOSURE")
        if severity == "UNKNOWN" or severity not in SUPPORTED_SEVERITIES:
            reasons.append("UNKNOWN_SEVERITY")
        if event_type == "UNKNOWN" or event_type not in SUPPORTED_EVENT_TYPES:
            reasons.append("UNKNOWN_EVENT_TYPE")
        if _is_missing(row.get("source_url")):
            reasons.append("MISSING_SOURCE_URL")

        if not reasons:
            continue

        rows.append(
            {
                "ticker": _normalize_ticker(row.get("ticker")),
                "event_date": _clean_text(row.get("event_date")),
                "event_type": event_type,
                "severity": severity,
                "review_reason": "|".join(_dedupe(reasons)),
                "title": _clean_text(row.get("title")),
                "source": _clean_text(row.get("source")),
                "source_url": _clean_text(row.get("source_url")),
                "notes": _clean_text(row.get("notes")),
            }
        )

    present_tickers = _ticker_set(disclosure_raw)
    for ticker in sorted(set(_normalize_requested_tickers(requested_tickers)) - present_tickers):
        rows.append(
            {
                "ticker": ticker,
                "event_date": "",
                "event_type": "UNKNOWN",
                "severity": "UNKNOWN",
                "review_reason": "DISCLOSURE_DATA_UNAVAILABLE",
                "title": "No disclosure rows found",
                "source": "",
                "source_url": "",
                "notes": "absence of disclosure rows is unknown/unavailable, not clean",
            }
        )

    return pd.DataFrame(rows, columns=MANUAL_REVIEW_COLUMNS)


def save_disclosure_warning_raw(
    *,
    disclosure_raw: pd.DataFrame,
    raw_output_dir: str | Path = DEFAULT_RAW_OUTPUT_DIR,
) -> str:
    """Save raw disclosure rows and return the output path."""

    output_dir = Path(raw_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / DISCLOSURE_STATUS_RAW_FILENAME
    disclosure_raw.to_csv(output_path, index=False)
    return str(output_path)


def save_coverage_report(
    *,
    coverage: dict[str, Any],
    run_id: str,
    coverage_output_dir: str | Path = DEFAULT_COVERAGE_OUTPUT_DIR,
) -> str:
    """Save disclosure coverage JSON and return the output path."""

    output_dir = Path(coverage_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{_safe_file_token(run_id)}_disclosure_status_coverage.json"
    output_path.write_text(
        json.dumps(coverage, indent=2, sort_keys=True), encoding="utf-8"
    )
    return str(output_path)


def save_manual_review_candidates(
    *,
    manual_review_candidates: pd.DataFrame,
    run_id: str,
    manual_review_dir: str | Path = DEFAULT_MANUAL_REVIEW_DIR,
) -> str:
    """Save manual-review candidates CSV and return the output path."""

    output_dir = Path(manual_review_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{_safe_file_token(run_id)}_disclosure_manual_review.csv"
    manual_review_candidates.to_csv(output_path, index=False)
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
        return _mock_disclosure_rows(fetch_time, requested_tickers)

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


def _mock_disclosure_rows(fetch_time: str, tickers: list[str]) -> pd.DataFrame:
    requested = tickers or ["MOCK1", "MOCK2"]
    rows: list[dict[str, Any]] = []
    for index, ticker in enumerate(requested, start=1):
        rows.append(
            {
                "ticker": ticker,
                "event_date": "2026-01-01",
                "event_type": "OTHER",
                "severity": "LOW",
                "title": f"Mock disclosure event {index}",
                "description": "Mock/sample disclosure row only; not real event data",
                "source": "MOCK_SAMPLE",
                "source_url": f"mock://disclosure_status/{ticker}",
                "fetch_time": fetch_time,
                "confidence_raw": "mock",
                "notes": "mock/sample disclosure data only; not real Vietnamese disclosure data",
            }
        )
    return pd.DataFrame(rows)


def _real_source_unavailable_result(
    *,
    run_id: str,
    requested_tickers: list[str],
    manifest_dir: str | Path,
    manual_review_dir: str | Path,
    fetch_time: str,
) -> dict[str, Any]:
    manual_review = pd.DataFrame(
        [
            {
                "ticker": ticker,
                "event_date": "",
                "event_type": "UNKNOWN",
                "severity": "UNKNOWN",
                "review_reason": REAL_SOURCE_UNAVAILABLE,
                "title": "Real exchange disclosure source unavailable",
                "source": "",
                "source_url": "",
                "notes": "no live data was fetched",
            }
            for ticker in requested_tickers
        ],
        columns=MANUAL_REVIEW_COLUMNS,
    )
    manual_review_path = save_manual_review_candidates(
        manual_review_candidates=manual_review,
        run_id=run_id,
        manual_review_dir=manual_review_dir,
    )
    manifest = create_ingestion_manifest_record(
        run_id=run_id,
        dataset_name="disclosure_status",
        mode="real_exchange_optional",
        started_at=fetch_time,
        finished_at=fetch_time,
        failed_count=max(1, len(requested_tickers)),
        errors=[REAL_SOURCE_UNAVAILABLE],
        data_quality_status=REAL_SOURCE_UNAVAILABLE,
        notes=(
            "Optional real exchange adapter is not implemented or unavailable; "
            "no live data was fetched."
        ),
    )
    manifest_path = save_ingestion_manifest(manifest, output_dir=manifest_dir)
    return {
        "status": REAL_SOURCE_UNAVAILABLE,
        "run_id": run_id,
        "mode": "real_exchange_optional",
        "raw_output_path": "",
        "manifest_path": manifest_path,
        "coverage_report_path": "",
        "manual_review_candidate_path": manual_review_path,
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
        dataset_name="disclosure_status",
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


def _severity_count(df: pd.DataFrame, severity: str) -> int:
    if "severity" not in df.columns:
        return 0
    severities = df["severity"].map(_normalize_event_label)
    return int((severities == severity).sum())


def _unknown_severity_count(df: pd.DataFrame) -> int:
    if "severity" not in df.columns:
        return int(len(df))
    severities = df["severity"].map(_normalize_event_label)
    return int(((severities == "UNKNOWN") | ~severities.isin(SUPPORTED_SEVERITIES)).sum())


def _unknown_event_type_count(df: pd.DataFrame) -> int:
    if "event_type" not in df.columns:
        return int(len(df))
    event_types = df["event_type"].map(_normalize_event_label)
    return int(((event_types == "UNKNOWN") | ~event_types.isin(SUPPORTED_EVENT_TYPES)).sum())


def _event_type_counts(df: pd.DataFrame) -> dict[str, int]:
    if "event_type" not in df.columns:
        return {}
    counts = df["event_type"].map(_normalize_event_label).value_counts()
    return {str(key): int(value) for key, value in counts.items()}


def _missing_count(df: pd.DataFrame, column: str) -> int:
    if column not in df.columns:
        return int(len(df))
    return int(df[column].map(_is_missing).sum())


def _ticker_set(df: pd.DataFrame) -> set[str]:
    if "ticker" not in df.columns:
        return set()
    return {ticker for ticker in df["ticker"].map(_normalize_ticker) if ticker}


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
        return "mock/sample disclosure data only; not real Vietnamese disclosure data"
    if mode == "external_vendor_optional":
        return "external vendor disclosure file; requires downstream validation"
    return "manual disclosure input; requires downstream validation"


def _normalize_ticker(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip().upper()


def _normalize_event_label(value: Any) -> str:
    if _is_missing(value):
        return "UNKNOWN"
    return str(value).strip().upper().replace("-", "_").replace(" ", "_")


def _clean_text(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip()


def _is_missing(value: Any) -> bool:
    if value is None or pd.isna(value):
        return True
    return isinstance(value, str) and not value.strip()


def _default_run_id() -> str:
    return f"disclosure_status_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"


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
