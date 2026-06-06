"""Seed validation for REAL-DATA-01I-B official finance documents."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


SEED_COLUMNS = [
    "ticker",
    "exchange",
    "company_name",
    "period",
    "document_type",
    "source_type",
    "source_name",
    "source_url",
    "official_domain",
    "expected_file_type",
    "consolidated_status",
    "language",
    "confidence_seed",
    "notes",
]

SEED_VALIDATION_COLUMNS = [
    *SEED_COLUMNS,
    "is_valid",
    "validation_status",
    "validation_errors",
    "is_duplicate",
    "dedupe_key",
]

DUPLICATE_SEED_COLUMNS = [*SEED_COLUMNS, "dedupe_key", "issue"]

DEFAULT_SCHEMA_PATH = Path("config/official_finance_document_schema.yaml")


def load_document_seed_schema(path: str | Path = DEFAULT_SCHEMA_PATH) -> dict[str, Any]:
    if yaml is None:
        raise ImportError("PyYAML is required to load official document schema.")
    with Path(path).open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise ValueError("official finance document schema must be a mapping.")
    return data


def load_document_seed_csv(path: str | Path) -> pd.DataFrame:
    seed_path = Path(path)
    if not seed_path.exists():
        raise FileNotFoundError(f"Seed file not found: {seed_path}")
    df = pd.read_csv(seed_path, keep_default_na=False)
    for column in SEED_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    return df[SEED_COLUMNS]


def validate_document_seed_rows(
    seed_df: pd.DataFrame,
    schema: dict[str, Any] | None = None,
) -> dict[str, pd.DataFrame]:
    """Validate seed rows and deduplicate by ticker/period/document_type/source_url."""

    config = schema or load_document_seed_schema()
    required_columns = list(config.get("required_columns", SEED_COLUMNS))
    allowed_values = config.get("allowed_values", {})
    dedupe_columns = list(config.get("dedupe_key", ["ticker", "period", "document_type", "source_url"]))

    rows = []
    seen: set[str] = set()
    duplicate_rows = []
    for _, raw_row in seed_df.iterrows():
        row = {column: _clean_text(raw_row.get(column)) for column in SEED_COLUMNS}
        row["ticker"] = row["ticker"].upper()
        row["exchange"] = row["exchange"].upper() or "UNKNOWN"
        row["expected_file_type"] = row["expected_file_type"].lower() or "unknown"
        row["document_type"] = row["document_type"].lower()
        row["source_type"] = row["source_type"].lower()
        row["consolidated_status"] = row["consolidated_status"].lower() or "unknown"
        row["language"] = row["language"].lower() or "unknown"
        row["confidence_seed"] = row["confidence_seed"].lower() or "low"

        errors = []
        for column in required_columns:
            if not row.get(column):
                errors.append(f"MISSING_REQUIRED_FIELD:{column}")
        if row["ticker"] and not re.match(r"^[A-Z0-9]{1,12}$", row["ticker"]):
            errors.append("INVALID_TICKER")
        if row["period"] and row["period"].upper() != "DISCOVERY" and not re.match(r"^\d{4}(-Q[1-4])?$", row["period"]):
            errors.append("INVALID_PERIOD")
        for column, allowed in allowed_values.items():
            if row.get(column) and row[column] not in set(allowed):
                errors.append(f"INVALID_{column.upper()}:{row[column]}")
        if not _is_public_http_url(row["source_url"]):
            errors.append("SOURCE_URL_INVALID")

        dedupe_key = "|".join(row.get(column, "") for column in dedupe_columns)
        is_duplicate = dedupe_key in seen
        if is_duplicate:
            errors.append("DUPLICATE_SEED_ROW")
            duplicate_rows.append({**row, "dedupe_key": dedupe_key, "issue": "DUPLICATE_SEED_ROW"})
        seen.add(dedupe_key)

        is_valid = not errors and not is_duplicate
        rows.append(
            {
                **row,
                "is_valid": is_valid,
                "validation_status": "VALID" if is_valid else "INVALID",
                "validation_errors": ";".join(errors),
                "is_duplicate": is_duplicate,
                "dedupe_key": dedupe_key,
            }
        )

    validation = pd.DataFrame(rows, columns=SEED_VALIDATION_COLUMNS)
    valid = validation[validation["is_valid"]].drop_duplicates(subset=dedupe_columns, keep="first")
    invalid = validation[~validation["is_valid"]]
    return {
        "validation": validation,
        "valid_seed_rows": valid[SEED_COLUMNS].reset_index(drop=True),
        "invalid_seed_rows": invalid.reset_index(drop=True),
        "duplicate_seed_rows": pd.DataFrame(duplicate_rows, columns=DUPLICATE_SEED_COLUMNS),
    }


def _is_public_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()
