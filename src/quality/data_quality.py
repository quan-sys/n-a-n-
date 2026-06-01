"""Reusable data quality and data sanity checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None


QUALITY_COLUMNS = [
    "quality_status",
    "quality_warnings",
    "quality_errors",
    "final_confidence",
    "manual_review_required",
]

LOW_CONFIDENCE_WARNINGS = {
    "DATA_CONFLICT",
    "HIGH_SEVERITY_DISCLOSURE_FLAG",
    "LOW_CONFIDENCE_RAW",
    "MISSING_CLOSE",
    "MISSING_EQUITY",
    "MISSING_FINANCIAL_DATA",
    "MISSING_MARKET_DATA",
    "NEGATIVE_EQUITY",
    "OUTLIER_REVIEW",
    "STALE_DATA",
}

MANUAL_REVIEW_STATUSES = {"DATA_ERROR", "DATA_CONFLICT", "OUTLIER_REVIEW"}
DEFAULT_LOW_CONFIDENCE_VALUES = {"LOW", "VERY_LOW", "MOCK"}


def load_data_quality_rules(path: str) -> dict[str, Any]:
    """Load data quality rules from YAML."""

    if yaml is None:
        raise ImportError(
            "PyYAML is required to load YAML rule files. Install 'pyyaml' or "
            "provide rules directly to run_data_quality_checks()."
        )

    rules_path = Path(path)
    with rules_path.open("r", encoding="utf-8") as rules_file:
        rules = yaml.safe_load(rules_file)

    if not isinstance(rules, dict):
        raise ValueError("Data quality rules must contain a YAML mapping.")

    return rules


def check_missing_values(
    df: pd.DataFrame,
    required_fields: list[str],
    warning_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Check missing required fields without dropping rows."""

    result = _empty_check_result()
    if not isinstance(df, pd.DataFrame):
        result["errors"].append("Input must be a pandas DataFrame.")
        return result

    for field in required_fields:
        warning = (warning_names or {}).get(field, _missing_warning_name(field))
        if field not in df.columns:
            result["missing_columns"].append(field)
            result["warnings"].append(warning)
            for index in df.index:
                result["row_warnings"].setdefault(index, []).append(warning)
            continue

        missing_mask = df[field].map(_is_missing_value)
        for index in df.index[missing_mask]:
            result["row_warnings"].setdefault(index, []).append(warning)
            result["warnings"].append(warning)

    result["warnings"] = _dedupe(result["warnings"])
    return result


def check_stale_data(
    df: pd.DataFrame,
    date_col: str,
    max_age_days: int,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Flag rows whose freshness date is older than the configured threshold."""

    result = _empty_check_result()
    if not isinstance(df, pd.DataFrame):
        result["errors"].append("Input must be a pandas DataFrame.")
        return result

    if date_col not in df.columns:
        warning = f"MISSING_{date_col.upper()}"
        result["missing_columns"].append(date_col)
        result["warnings"].append(warning)
        for index in df.index:
            result["row_warnings"].setdefault(index, []).append(warning)
        return result

    reference_ts = pd.to_datetime(reference_date or pd.Timestamp.utcnow(), errors="coerce")
    if pd.isna(reference_ts):
        result["errors"].append("Invalid reference_date.")
        return result
    reference_ts = _to_timezone_naive(reference_ts)

    date_values = pd.to_datetime(df[date_col], errors="coerce")
    for index, observed_ts in date_values.items():
        if pd.isna(observed_ts):
            warning = f"MISSING_{date_col.upper()}"
            result["warnings"].append(warning)
            result["row_warnings"].setdefault(index, []).append(warning)
            continue

        observed_ts = _to_timezone_naive(observed_ts)
        age_days = (reference_ts - observed_ts).days
        if age_days > max_age_days:
            result["warnings"].append("STALE_DATA")
            result["row_warnings"].setdefault(index, []).append("STALE_DATA")

    result["warnings"] = _dedupe(result["warnings"])
    return result


def check_invalid_values(
    df: pd.DataFrame, dataset_name: str, rules: dict[str, Any]
) -> dict[str, Any]:
    """Apply dataset-specific invalid-value checks."""

    result = _empty_check_result()
    if not isinstance(df, pd.DataFrame):
        result["errors"].append("Input must be a pandas DataFrame.")
        return result

    dataset_rules = _dataset_rules(rules, dataset_name)
    invalid_rules = dataset_rules.get("invalid_values", {})
    for field, field_rule in invalid_rules.items():
        if field not in df.columns:
            continue

        numeric_values = pd.to_numeric(df[field], errors="coerce")
        for index, value in numeric_values.items():
            if pd.isna(value):
                continue

            if _violates_min_rule(value, field_rule):
                issue_name = field_rule.get("error") or field_rule.get("warning")
                if not issue_name:
                    continue
                target = "row_errors" if field_rule.get("error") else "row_warnings"
                aggregate = "errors" if field_rule.get("error") else "warnings"
                result[target].setdefault(index, []).append(issue_name)
                result[aggregate].append(issue_name)

    if dataset_name == "disclosure_status":
        _check_disclosure_severity(df, dataset_rules, result)

    result["warnings"] = _dedupe(result["warnings"])
    result["errors"] = _dedupe(result["errors"])
    return result


def check_outliers(
    df: pd.DataFrame, value_cols: list[str], method: str = "iqr"
) -> dict[str, Any]:
    """Flag abnormal numeric values for manual review."""

    result = _empty_check_result()
    if not isinstance(df, pd.DataFrame):
        result["errors"].append("Input must be a pandas DataFrame.")
        return result
    if method != "iqr":
        result["errors"].append(f"Unsupported outlier method: {method}")
        return result

    for column in value_cols:
        if column not in df.columns:
            continue

        values = pd.to_numeric(df[column], errors="coerce")
        non_missing = values.dropna()
        if len(non_missing) < 4:
            continue

        q1 = non_missing.quantile(0.25)
        q3 = non_missing.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue

        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr
        outlier_mask = (values < lower_bound) | (values > upper_bound)
        for index in df.index[outlier_mask.fillna(False)]:
            result["warnings"].append("OUTLIER_REVIEW")
            result["row_warnings"].setdefault(index, []).append("OUTLIER_REVIEW")

    result["warnings"] = _dedupe(result["warnings"])
    return result


def check_source_conflict(
    df: pd.DataFrame,
    key_cols: list[str],
    value_col: str,
    source_col: str = "source",
    tolerance_pct: float = 0.05,
) -> dict[str, Any]:
    """Detect conflicting values reported by different sources for the same key."""

    result = _empty_check_result()
    if not isinstance(df, pd.DataFrame):
        result["errors"].append("Input must be a pandas DataFrame.")
        return result

    required_cols = [*key_cols, value_col, source_col]
    missing_cols = [column for column in required_cols if column not in df.columns]
    if missing_cols:
        result["missing_columns"] = missing_cols
        return result

    for _, group in df.groupby(key_cols, dropna=False):
        if group[source_col].nunique(dropna=True) < 2:
            continue

        values = group[value_col]
        if _has_numeric_conflict(values, tolerance_pct) or _has_text_conflict(values):
            result["warnings"].append("DATA_CONFLICT")
            for index in group.index:
                result["row_warnings"].setdefault(index, []).append("DATA_CONFLICT")

    result["warnings"] = _dedupe(result["warnings"])
    return result


def check_low_confidence_raw(
    df: pd.DataFrame,
    confidence_col: str = "confidence_raw",
    low_values: list[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Flag rows that carry low raw source confidence."""

    result = _empty_check_result()
    if not isinstance(df, pd.DataFrame):
        result["errors"].append("Input must be a pandas DataFrame.")
        return result

    if confidence_col not in df.columns:
        return result

    low_confidence_values = {
        str(value).strip().upper()
        for value in (low_values or DEFAULT_LOW_CONFIDENCE_VALUES)
    }
    for index, value in df[confidence_col].items():
        if _is_missing_value(value):
            continue
        if str(value).strip().upper() in low_confidence_values:
            result["warnings"].append("LOW_CONFIDENCE_RAW")
            result["row_warnings"].setdefault(index, []).append(
                "LOW_CONFIDENCE_RAW"
            )

    result["warnings"] = _dedupe(result["warnings"])
    return result


def assign_data_confidence(warnings: list[str], errors: list[str]) -> str:
    """Assign a simple confidence label from quality warnings and errors."""

    if errors:
        return "low"
    if LOW_CONFIDENCE_WARNINGS.intersection(warnings):
        return "low"
    if warnings:
        return "medium"
    return "high"


def run_data_quality_checks(
    df: pd.DataFrame,
    dataset_name: str,
    rules: dict[str, Any],
    reference_date: str | None = None,
) -> pd.DataFrame:
    """Return input rows with quality status, warnings, errors, and confidence."""

    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame.")

    result_df = df.copy(deep=True)
    row_warnings = {index: [] for index in result_df.index}
    row_errors = {index: [] for index in result_df.index}

    dataset_rules = _dataset_rules(rules, dataset_name)
    required_fields = dataset_rules.get("required_fields", [])
    _merge_check_result(
        check_missing_values(
            result_df,
            required_fields,
            warning_names=dataset_rules.get("missing_warnings"),
        ),
        row_warnings,
        row_errors,
    )

    freshness_threshold = rules.get("freshness_threshold_days", {}).get(dataset_name)
    date_col = dataset_rules.get("date_col")
    if freshness_threshold is not None and date_col:
        _merge_check_result(
            check_stale_data(
                result_df,
                date_col=date_col,
                max_age_days=int(freshness_threshold),
                reference_date=reference_date,
            ),
            row_warnings,
            row_errors,
        )

    _merge_check_result(
        check_invalid_values(result_df, dataset_name, rules), row_warnings, row_errors
    )

    _merge_check_result(
        check_low_confidence_raw(
            result_df,
            low_values=rules.get("low_confidence_values"),
        ),
        row_warnings,
        row_errors,
    )

    outlier_fields = dataset_rules.get("outlier_fields", [])
    if outlier_fields:
        _merge_check_result(
            check_outliers(result_df, outlier_fields), row_warnings, row_errors
        )

    source_conflict_rules = dataset_rules.get("source_conflict", {})
    for value_col in source_conflict_rules.get("value_cols", []):
        _merge_check_result(
            check_source_conflict(
                result_df,
                key_cols=source_conflict_rules.get("key_cols", []),
                value_col=value_col,
                source_col=source_conflict_rules.get("source_col", "source"),
                tolerance_pct=float(source_conflict_rules.get("tolerance_pct", 0.05)),
            ),
            row_warnings,
            row_errors,
        )

    quality_statuses: list[str] = []
    confidence_values: list[str] = []
    manual_review_flags: list[bool] = []

    for index in result_df.index:
        warnings = _dedupe(row_warnings[index])
        errors = _dedupe(row_errors[index])
        status = _resolve_quality_status(warnings, errors)
        confidence = assign_data_confidence(warnings, errors)
        manual_review = _manual_review_required(status, warnings, confidence)

        row_warnings[index] = warnings
        row_errors[index] = errors
        quality_statuses.append(status)
        confidence_values.append(confidence)
        manual_review_flags.append(manual_review)

    result_df["quality_status"] = quality_statuses
    result_df["quality_warnings"] = [row_warnings[index] for index in result_df.index]
    result_df["quality_errors"] = [row_errors[index] for index in result_df.index]
    result_df["final_confidence"] = confidence_values
    result_df["manual_review_required"] = manual_review_flags

    result_df["manual_review_required"] = result_df["manual_review_required"].astype(
        object
    )
    return result_df


def _empty_check_result() -> dict[str, Any]:
    return {
        "missing_columns": [],
        "warnings": [],
        "errors": [],
        "row_warnings": {},
        "row_errors": {},
    }


def _dataset_rules(rules: dict[str, Any], dataset_name: str) -> dict[str, Any]:
    return rules.get("datasets", {}).get(dataset_name, {})


def _missing_warning_name(field: str) -> str:
    return f"MISSING_{field.upper()}"


def _is_missing_value(value: Any) -> bool:
    if value is None or pd.isna(value):
        return True
    return isinstance(value, str) and not value.strip()


def _to_timezone_naive(value: pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        return timestamp.tz_convert(None)
    return timestamp


def _violates_min_rule(value: float, field_rule: dict[str, Any]) -> bool:
    if "min_exclusive" in field_rule and value <= field_rule["min_exclusive"]:
        return True
    if "min_inclusive" in field_rule and value < field_rule["min_inclusive"]:
        return True
    if (
        "min_exclusive_if_available" in field_rule
        and value <= field_rule["min_exclusive_if_available"]
    ):
        return True
    if (
        "max_exclusive_if_available" in field_rule
        and value < field_rule["max_exclusive_if_available"]
    ):
        return True
    return False


def _check_disclosure_severity(
    df: pd.DataFrame, dataset_rules: dict[str, Any], result: dict[str, Any]
) -> None:
    if "severity" not in df.columns:
        return

    high_values = {
        str(value).strip().upper()
        for value in dataset_rules.get("high_severity_values", [])
    }
    warning = dataset_rules.get(
        "high_severity_warning", "HIGH_SEVERITY_DISCLOSURE_FLAG"
    )
    for index, value in df["severity"].items():
        if str(value).strip().upper() in high_values:
            result["warnings"].append(warning)
            result["row_warnings"].setdefault(index, []).append(warning)


def _has_numeric_conflict(values: pd.Series, tolerance_pct: float) -> bool:
    numeric_values = pd.to_numeric(values, errors="coerce").dropna()
    if len(numeric_values) != len(values.dropna()) or len(numeric_values) < 2:
        return False

    min_value = numeric_values.min()
    max_value = numeric_values.max()
    denominator = max(abs(max_value), abs(min_value), 1.0)
    return ((max_value - min_value) / denominator) > tolerance_pct


def _has_text_conflict(values: pd.Series) -> bool:
    if not values.map(lambda value: isinstance(value, str)).all():
        return False
    normalized_values = {
        value.strip().upper() for value in values.dropna() if value.strip()
    }
    return len(normalized_values) > 1


def _merge_check_result(
    check_result: dict[str, Any],
    row_warnings: dict[Any, list[str]],
    row_errors: dict[Any, list[str]],
) -> None:
    for index, warnings in check_result.get("row_warnings", {}).items():
        row_warnings.setdefault(index, []).extend(warnings)
    for index, errors in check_result.get("row_errors", {}).items():
        row_errors.setdefault(index, []).extend(errors)


def _resolve_quality_status(warnings: list[str], errors: list[str]) -> str:
    if errors:
        return "DATA_ERROR"
    if "DATA_CONFLICT" in warnings:
        return "DATA_CONFLICT"
    if "OUTLIER_REVIEW" in warnings:
        return "OUTLIER_REVIEW"
    if "STALE_DATA" in warnings:
        return "STALE_DATA"
    if any(warning.startswith("MISSING_") for warning in warnings):
        return "MISSING_DATA"
    if "NEGATIVE_EQUITY" in warnings or "HIGH_SEVERITY_DISCLOSURE_FLAG" in warnings:
        return "MANUAL_REVIEW"
    return "VALID_DATA"


def _manual_review_required(
    status: str, warnings: list[str], final_confidence: str
) -> bool:
    return (
        status in MANUAL_REVIEW_STATUSES
        or "NEGATIVE_EQUITY" in warnings
        or "HIGH_SEVERITY_DISCLOSURE_FLAG" in warnings
        or final_confidence == "low"
    )


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
