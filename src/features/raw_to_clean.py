"""Convert standardized raw fetcher output into clean wide datasets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.fetchers.base import REQUIRED_FETCH_COLUMNS


CLEAN_DATASET_COLUMNS = {
    "universe": [
        "ticker",
        "exchange",
        "company_name",
        "listing_status",
        "data_source",
        "last_updated",
        "source",
        "source_url",
        "fetch_time",
        "confidence_raw",
        "notes",
    ],
    "market_price": [
        "ticker",
        "date",
        "close",
        "volume",
        "trading_value",
        "source",
        "source_url",
        "fetch_time",
        "confidence_raw",
        "notes",
    ],
    "company_profile": [
        "ticker",
        "company_name",
        "exchange",
        "industry_raw",
        "business_description",
        "source",
        "source_url",
        "last_updated",
        "fetch_time",
        "confidence_raw",
        "notes",
    ],
    "financial_statement_summary": [
        "ticker",
        "period",
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
    ],
    "disclosure_status": [
        "ticker",
        "date",
        "event_type",
        "severity",
        "source",
        "source_url",
        "notes",
        "fetch_time",
        "confidence_raw",
    ],
}

ROW_KEY_COLUMNS = {
    "universe": ["ticker", "source"],
    "market_price": ["ticker", "date", "source"],
    "company_profile": ["ticker", "source"],
    "financial_statement_summary": ["ticker", "date", "source"],
    "disclosure_status": ["ticker", "date", "source"],
}

VALUE_FIELDS = {
    "universe": [
        "exchange",
        "company_name",
        "listing_status",
        "data_source",
        "last_updated",
    ],
    "market_price": ["close", "volume", "trading_value"],
    "company_profile": [
        "company_name",
        "exchange",
        "industry_raw",
        "business_description",
        "last_updated",
    ],
    "financial_statement_summary": [
        "period",
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
    ],
    "disclosure_status": ["event_type", "severity", "source_url", "notes"],
}

REQUIRED_VALUE_FIELDS = {
    "universe": [
        "exchange",
        "company_name",
        "listing_status",
        "data_source",
        "last_updated",
    ],
    "market_price": ["close", "volume", "trading_value"],
    "company_profile": [
        "company_name",
        "exchange",
        "industry_raw",
        "business_description",
        "last_updated",
    ],
    "financial_statement_summary": [
        "period",
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
    ],
    "disclosure_status": ["event_type", "severity"],
}

METADATA_COLUMNS = ["source_url", "fetch_time", "confidence_raw", "notes"]


def pivot_long_fetch_to_clean_wide(
    df: pd.DataFrame, dataset_name: str
) -> pd.DataFrame:
    """Pivot one standardized long-format fetcher output into clean wide data."""

    _ensure_supported_dataset(dataset_name)
    result = _cleaning_result(dataset_name)
    empty = _empty_clean_frame(dataset_name, result)

    if not isinstance(df, pd.DataFrame):
        result["is_valid"] = False
        result["errors"].append("Input must be a pandas DataFrame.")
        return empty

    missing_fetch_columns = [
        column for column in REQUIRED_FETCH_COLUMNS if column not in df.columns
    ]
    result["missing_fetch_columns"] = missing_fetch_columns
    if missing_fetch_columns:
        result["is_valid"] = False
        result["warnings"].append(
            "Missing required fetch columns: " + ", ".join(missing_fetch_columns)
        )
        return empty

    dataset_df = df[df["dataset_name"] == dataset_name].copy()
    if dataset_df.empty:
        result["is_valid"] = False
        result["warnings"].append(f"No rows found for dataset: {dataset_name}")
        return empty

    dataset_df["_fetch_sort"] = pd.to_datetime(
        dataset_df["fetch_time"], errors="coerce", utc=True
    )
    dataset_df["_original_order"] = range(len(dataset_df))
    dataset_df = dataset_df.sort_values(
        ["_fetch_sort", "_original_order"], na_position="first"
    )

    dataset_df = _dedupe_exact_records(dataset_df, result)
    dataset_df = _dedupe_clean_field_records(dataset_df, dataset_name, result)

    row_key_columns = ROW_KEY_COLUMNS[dataset_name]
    value_fields = VALUE_FIELDS[dataset_name]
    field_values = set(dataset_df["field"].dropna().map(str))
    extra_fields = sorted(field_values - set(value_fields))
    result["extra_fields"] = extra_fields
    if extra_fields:
        result["warnings"].append(
            "Ignored fields outside clean schema: " + ", ".join(extra_fields)
        )

    metadata = _latest_metadata_by_clean_key(dataset_df, row_key_columns)
    wide_values = _pivot_value_fields(dataset_df, row_key_columns, value_fields)
    clean_df = metadata.merge(wide_values, on=row_key_columns, how="left")
    final_df = _build_final_clean_frame(clean_df, dataset_name)

    _record_missing_required_values(final_df, dataset_name, result)
    final_df.attrs["cleaning_result"] = _finalize_result(result)
    return final_df


def clean_universe_data(df: pd.DataFrame) -> pd.DataFrame:
    """Clean standardized long-format universe data."""

    return pivot_long_fetch_to_clean_wide(df, "universe")


def clean_market_price_data(df: pd.DataFrame) -> pd.DataFrame:
    """Clean standardized long-format market price data."""

    return pivot_long_fetch_to_clean_wide(df, "market_price")


def clean_company_profile_data(df: pd.DataFrame) -> pd.DataFrame:
    """Clean standardized long-format company profile data."""

    return pivot_long_fetch_to_clean_wide(df, "company_profile")


def clean_financial_statement_data(df: pd.DataFrame) -> pd.DataFrame:
    """Clean standardized long-format financial statement summary data."""

    return pivot_long_fetch_to_clean_wide(df, "financial_statement_summary")


def clean_disclosure_status_data(df: pd.DataFrame) -> pd.DataFrame:
    """Clean standardized long-format disclosure status data."""

    return pivot_long_fetch_to_clean_wide(df, "disclosure_status")


def save_clean_dataset(
    df: pd.DataFrame, dataset_name: str, output_dir: str = "data/clean"
) -> str:
    """Save a clean dataset as CSV and return the output path."""

    _ensure_supported_dataset(dataset_name)
    output_path = Path(output_dir) / f"{dataset_name}.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    return str(output_path)


def _dedupe_exact_records(
    dataset_df: pd.DataFrame, result: dict[str, Any]
) -> pd.DataFrame:
    duplicate_key = ["ticker", "date", "field", "source"]
    duplicate_mask = dataset_df.duplicated(subset=duplicate_key, keep=False)
    if duplicate_mask.any():
        result["duplicate_records"] += int(duplicate_mask.sum())
        result["warnings"].append(
            "Duplicate ticker/date/field/source records detected; kept latest "
            "fetch_time."
        )
    return dataset_df.drop_duplicates(subset=duplicate_key, keep="last")


def _dedupe_clean_field_records(
    dataset_df: pd.DataFrame, dataset_name: str, result: dict[str, Any]
) -> pd.DataFrame:
    pivot_key = [*ROW_KEY_COLUMNS[dataset_name], "field"]
    duplicate_mask = dataset_df.duplicated(subset=pivot_key, keep=False)
    if duplicate_mask.any():
        result["collapsed_records"] += int(duplicate_mask.sum())
        result["warnings"].append(
            "Multiple field records mapped to the same clean row; kept latest "
            "fetch_time."
        )
    return dataset_df.drop_duplicates(subset=pivot_key, keep="last")


def _latest_metadata_by_clean_key(
    dataset_df: pd.DataFrame, row_key_columns: list[str]
) -> pd.DataFrame:
    metadata_columns = [
        column for column in METADATA_COLUMNS if column not in row_key_columns
    ]
    latest_rows = dataset_df.groupby(row_key_columns, dropna=False).tail(1)
    metadata = latest_rows[row_key_columns + metadata_columns].copy()
    return metadata.rename(
        columns={column: f"_meta_{column}" for column in metadata_columns}
    )


def _pivot_value_fields(
    dataset_df: pd.DataFrame, row_key_columns: list[str], value_fields: list[str]
) -> pd.DataFrame:
    value_df = dataset_df[dataset_df["field"].isin(value_fields)].copy()
    if value_df.empty:
        return dataset_df[row_key_columns].drop_duplicates().reset_index(drop=True)

    return (
        value_df.set_index([*row_key_columns, "field"])["value"]
        .unstack("field")
        .reset_index()
    )


def _build_final_clean_frame(
    clean_df: pd.DataFrame, dataset_name: str
) -> pd.DataFrame:
    final_columns = CLEAN_DATASET_COLUMNS[dataset_name]
    output = pd.DataFrame(index=clean_df.index)

    for column in final_columns:
        if column == "period" and dataset_name == "financial_statement_summary":
            output[column] = _choose_column(clean_df, "period", "date")
        elif column in clean_df.columns:
            output[column] = clean_df[column]
        elif f"_meta_{column}" in clean_df.columns:
            output[column] = clean_df[f"_meta_{column}"]
        else:
            output[column] = pd.NA

    return output[final_columns]


def _choose_column(
    df: pd.DataFrame, primary_column: str, fallback_column: str
) -> pd.Series:
    if primary_column in df.columns and fallback_column in df.columns:
        return df[primary_column].where(
            ~df[primary_column].map(_is_missing), df[fallback_column]
        )
    if primary_column in df.columns:
        return df[primary_column]
    if fallback_column in df.columns:
        return df[fallback_column]
    return pd.Series([pd.NA] * len(df), index=df.index)


def _record_missing_required_values(
    clean_df: pd.DataFrame, dataset_name: str, result: dict[str, Any]
) -> None:
    for column in REQUIRED_VALUE_FIELDS[dataset_name]:
        if column not in clean_df.columns or clean_df[column].map(_is_missing).all():
            result["is_valid"] = False
            result["missing_columns"].append(column)
            result["warnings"].append(
                f"{dataset_name}: missing required clean field: {column}"
            )


def _empty_clean_frame(
    dataset_name: str, result: dict[str, Any]
) -> pd.DataFrame:
    clean_df = pd.DataFrame(columns=CLEAN_DATASET_COLUMNS[dataset_name])
    clean_df.attrs["cleaning_result"] = result
    return clean_df


def _cleaning_result(dataset_name: str) -> dict[str, Any]:
    return {
        "dataset_name": dataset_name,
        "is_valid": True,
        "missing_columns": [],
        "missing_fetch_columns": [],
        "extra_fields": [],
        "duplicate_records": 0,
        "collapsed_records": 0,
        "warnings": [],
        "errors": [],
    }


def _finalize_result(result: dict[str, Any]) -> dict[str, Any]:
    result["missing_columns"] = _dedupe(result["missing_columns"])
    result["missing_fetch_columns"] = _dedupe(result["missing_fetch_columns"])
    result["extra_fields"] = _dedupe(result["extra_fields"])
    result["warnings"] = _dedupe(result["warnings"])
    result["errors"] = _dedupe(result["errors"])
    return result


def _ensure_supported_dataset(dataset_name: str) -> None:
    if dataset_name not in CLEAN_DATASET_COLUMNS:
        supported = ", ".join(sorted(CLEAN_DATASET_COLUMNS))
        raise ValueError(
            f"Unsupported dataset_name '{dataset_name}'. Supported datasets: "
            f"{supported}."
        )


def _is_missing(value: Any) -> bool:
    if value is None or pd.isna(value):
        return True
    return isinstance(value, str) and not value.strip()


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(values))
