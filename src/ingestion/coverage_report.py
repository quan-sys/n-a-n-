"""Coverage reporting for ingested and clean pipeline datasets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.ingestion.contracts import PROHIBITED_RECOMMENDATION_FIELDS


COVERAGE_REPORT_COLUMNS = [
    "dataset_name",
    "row_count",
    "ticker_count",
    "period_count",
    "min_date",
    "max_date",
    "missing_required_field_count",
    "stale_data_count",
    "data_conflict_count",
    "low_confidence_count",
    "manual_review_count",
    "coverage_status",
    "notes",
]

DEFAULT_COVERAGE_REQUIRED_FIELDS = {
    "universe": ["ticker", "exchange", "company_name", "listing_status"],
    "company_profile": [
        "ticker",
        "company_name",
        "exchange",
        "industry_raw",
        "business_description",
    ],
    "market_price": ["ticker", "date", "close", "volume", "trading_value"],
    "financial_statement_summary": [
        "ticker",
        "period",
        "revenue",
        "net_profit",
        "equity",
        "total_assets",
        "total_liabilities",
    ],
    "disclosure_status": ["ticker", "date", "event_type", "severity"],
}

DATE_COLUMN_CANDIDATES = {
    "universe": ["last_updated", "fetch_time"],
    "company_profile": ["last_updated", "fetch_time"],
    "market_price": ["date", "fetch_time"],
    "financial_statement_summary": ["period", "date", "fetch_time"],
    "disclosure_status": ["date", "event_date", "fetch_time"],
}

PERIOD_COLUMN_CANDIDATES = {
    "financial_statement_summary": ["period", "date"],
    "market_price": ["date"],
    "disclosure_status": ["date", "event_date"],
    "universe": ["last_updated"],
    "company_profile": ["last_updated"],
}

LOW_CONFIDENCE_VALUES = {"low", "very_low", "mock"}


def build_data_coverage_report(
    datasets: dict[str, pd.DataFrame | None],
    *,
    dataset_order: list[str] | None = None,
    required_fields_by_dataset: dict[str, list[str]] | None = None,
    reference_date: str | None = None,
    stale_after_days_by_dataset: dict[str, int] | None = None,
) -> pd.DataFrame:
    """Build a coverage report for available and missing datasets."""

    if not isinstance(datasets, dict):
        raise TypeError("datasets must be a mapping of dataset_name to DataFrame.")

    required_fields = required_fields_by_dataset or DEFAULT_COVERAGE_REQUIRED_FIELDS
    names = dataset_order or list(datasets)
    rows = [
        _coverage_row(
            dataset_name=name,
            df=datasets.get(name),
            required_fields=required_fields.get(name, []),
            reference_date=reference_date,
            stale_after_days=(stale_after_days_by_dataset or {}).get(name),
        )
        for name in names
    ]
    return pd.DataFrame(rows, columns=COVERAGE_REPORT_COLUMNS)


def save_data_coverage_report(
    report_df: pd.DataFrame,
    output_dir: str | Path = "data/reports",
    filename: str = "data_coverage_report.csv",
) -> str:
    """Save a coverage report CSV and return the path."""

    if not isinstance(report_df, pd.DataFrame):
        raise TypeError("report_df must be a pandas DataFrame.")

    output_path = Path(output_dir) / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_df.to_csv(output_path, index=False)
    return str(output_path)


def has_prohibited_recommendation_columns(df: pd.DataFrame) -> bool:
    """Return True when output columns include recommendation or target fields."""

    normalized_columns = {str(column).strip().lower() for column in df.columns}
    return bool(PROHIBITED_RECOMMENDATION_FIELDS.intersection(normalized_columns))


def _coverage_row(
    *,
    dataset_name: str,
    df: pd.DataFrame | None,
    required_fields: list[str],
    reference_date: str | None,
    stale_after_days: int | None,
) -> dict[str, Any]:
    if df is None:
        return {
            "dataset_name": dataset_name,
            "row_count": 0,
            "ticker_count": 0,
            "period_count": 0,
            "min_date": "",
            "max_date": "",
            "missing_required_field_count": len(required_fields),
            "stale_data_count": 0,
            "data_conflict_count": 0,
            "low_confidence_count": 0,
            "manual_review_count": 0,
            "coverage_status": "MISSING_DATASET",
            "notes": "dataset not available; missing data is not treated as clean",
        }

    if not isinstance(df, pd.DataFrame):
        return {
            "dataset_name": dataset_name,
            "row_count": 0,
            "ticker_count": 0,
            "period_count": 0,
            "min_date": "",
            "max_date": "",
            "missing_required_field_count": len(required_fields),
            "stale_data_count": 0,
            "data_conflict_count": 0,
            "low_confidence_count": 0,
            "manual_review_count": 0,
            "coverage_status": "DATA_ERROR",
            "notes": f"dataset object is not a DataFrame: {type(df).__name__}",
        }

    row_count = int(len(df))
    date_values = _date_values(dataset_name, df)
    stale_count = _quality_issue_count(df, "STALE_DATA")
    if reference_date and stale_after_days is not None:
        stale_count = max(
            stale_count,
            _reference_stale_count(
                dataset_name=dataset_name,
                df=df,
                reference_date=reference_date,
                stale_after_days=stale_after_days,
            ),
        )
    missing_count = _missing_required_field_count(df, required_fields)
    conflict_count = _quality_issue_count(df, "DATA_CONFLICT")
    low_confidence_count = _low_confidence_count(df)
    manual_review_count = _manual_review_count(dataset_name, df)
    status = _coverage_status(
        row_count=row_count,
        missing_count=missing_count,
        stale_count=stale_count,
        conflict_count=conflict_count,
        low_confidence_count=low_confidence_count,
        manual_review_count=manual_review_count,
    )

    return {
        "dataset_name": dataset_name,
        "row_count": row_count,
        "ticker_count": _ticker_count(df),
        "period_count": _period_count(dataset_name, df),
        "min_date": date_values[0],
        "max_date": date_values[1],
        "missing_required_field_count": missing_count,
        "stale_data_count": stale_count,
        "data_conflict_count": conflict_count,
        "low_confidence_count": low_confidence_count,
        "manual_review_count": manual_review_count,
        "coverage_status": status,
        "notes": _coverage_notes(
            required_fields=required_fields,
            missing_count=missing_count,
            stale_count=stale_count,
            conflict_count=conflict_count,
            low_confidence_count=low_confidence_count,
            manual_review_count=manual_review_count,
        ),
    }


def _ticker_count(df: pd.DataFrame) -> int:
    if "ticker" not in df.columns:
        return 0
    values = df["ticker"].dropna().astype(str).str.strip()
    return int(values[values != ""].str.upper().nunique())


def _period_count(dataset_name: str, df: pd.DataFrame) -> int:
    for column in PERIOD_COLUMN_CANDIDATES.get(dataset_name, []):
        if column in df.columns:
            values = df[column].dropna().astype(str).str.strip()
            return int(values[values != ""].nunique())
    return 0


def _date_values(dataset_name: str, df: pd.DataFrame) -> tuple[str, str]:
    for column in DATE_COLUMN_CANDIDATES.get(dataset_name, []):
        if column not in df.columns:
            continue
        values = [str(value).strip() for value in df[column] if not _is_missing(value)]
        if not values:
            continue
        return min(values), max(values)
    return "", ""


def _missing_required_field_count(df: pd.DataFrame, required_fields: list[str]) -> int:
    missing_count = 0
    row_count = max(1, int(len(df)))
    for field in required_fields:
        if field not in df.columns:
            missing_count += row_count
            continue
        missing_count += int(df[field].map(_is_missing).sum())
    return int(missing_count)


def _quality_issue_count(df: pd.DataFrame, issue: str) -> int:
    issue_upper = issue.upper()
    count = 0
    if "quality_status" in df.columns:
        count = max(
            count,
            int(df["quality_status"].map(lambda value: _clean_upper(value) == issue_upper).sum()),
        )
    for column in ["quality_warnings", "quality_errors", "warning_flags"]:
        if column in df.columns:
            count = max(count, int(df[column].map(lambda value: _contains_issue(value, issue_upper)).sum()))
    return int(count)


def _reference_stale_count(
    *,
    dataset_name: str,
    df: pd.DataFrame,
    reference_date: str,
    stale_after_days: int,
) -> int:
    date_column = ""
    for candidate in DATE_COLUMN_CANDIDATES.get(dataset_name, []):
        if candidate in df.columns:
            date_column = candidate
            break
    if not date_column:
        return 0

    reference_ts = pd.to_datetime(reference_date, errors="coerce")
    if pd.isna(reference_ts):
        return 0
    reference_ts = _timezone_naive(reference_ts)
    observed = pd.to_datetime(df[date_column], errors="coerce")
    count = 0
    for value in observed:
        if pd.isna(value):
            continue
        if (_timezone_naive(value) - reference_ts).days > 0:
            continue
        if (reference_ts - _timezone_naive(value)).days > int(stale_after_days):
            count += 1
    return int(count)


def _low_confidence_count(df: pd.DataFrame) -> int:
    flags = pd.Series([False] * len(df), index=df.index)
    for column in ["final_confidence", "confidence", "confidence_raw"]:
        if column not in df.columns:
            continue
        flags = flags | df[column].map(
            lambda value: _clean_lower(value) in LOW_CONFIDENCE_VALUES
        )
    if "quality_warnings" in df.columns:
        flags = flags | df["quality_warnings"].map(
            lambda value: _contains_issue(value, "LOW_CONFIDENCE_RAW")
        )
    return int(flags.sum())


def _manual_review_count(dataset_name: str, df: pd.DataFrame) -> int:
    flags = pd.Series([False] * len(df), index=df.index)
    if "manual_review_required" in df.columns:
        flags = flags | df["manual_review_required"].map(_truthy)
    if dataset_name == "disclosure_status" and "severity" in df.columns:
        flags = flags | df["severity"].map(
            lambda value: _clean_upper(value) in {"HIGH", "CRITICAL", "UNKNOWN"}
        )
    return int(flags.sum())


def _coverage_status(
    *,
    row_count: int,
    missing_count: int,
    stale_count: int,
    conflict_count: int,
    low_confidence_count: int,
    manual_review_count: int,
) -> str:
    if row_count == 0:
        return "EMPTY_DATASET"
    if missing_count:
        return "MISSING_DATA"
    if conflict_count:
        return "DATA_CONFLICT"
    if manual_review_count:
        return "MANUAL_REVIEW"
    if stale_count:
        return "STALE_DATA"
    if low_confidence_count:
        return "LOW_CONFIDENCE"
    return "VALID_DATA"


def _coverage_notes(
    *,
    required_fields: list[str],
    missing_count: int,
    stale_count: int,
    conflict_count: int,
    low_confidence_count: int,
    manual_review_count: int,
) -> str:
    notes: list[str] = []
    if required_fields:
        notes.append("required_fields=" + ",".join(required_fields))
    if missing_count:
        notes.append("missing required values present")
    if stale_count:
        notes.append("stale data present")
    if conflict_count:
        notes.append("data conflicts present")
    if low_confidence_count:
        notes.append("low confidence rows present")
    if manual_review_count:
        notes.append("manual review rows present")
    return "; ".join(notes)


def _contains_issue(value: Any, issue_upper: str) -> bool:
    if isinstance(value, list):
        return issue_upper in {_clean_upper(item) for item in value}
    if isinstance(value, tuple) or isinstance(value, set):
        return issue_upper in {_clean_upper(item) for item in value}
    if _is_missing(value):
        return False
    text = str(value).upper()
    return issue_upper in text


def _timezone_naive(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        return timestamp.tz_convert(None)
    return timestamp


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if _is_missing(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _clean_upper(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip().upper()


def _clean_lower(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip().lower()


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
