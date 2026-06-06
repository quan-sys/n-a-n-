"""REAL-DATA-01I finance candidate normalization.

The functions here map source-provided finance labels to canonical fields. They
do not infer missing values and do not convert absent rows to zero.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingestion.source_adapter_contracts import FINANCE_CANONICAL_FIELDS

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


FINANCE_01I_CANDIDATE_COLUMNS = [
    "ticker",
    "period",
    "period_type",
    "field_name",
    "value",
    "unit",
    "currency",
    "source_category",
    "source_name",
    "source_url",
    "fetch_time",
    "confidence_raw",
    "raw_label",
    "raw_value",
    "raw_period",
    "parser_name",
    "parse_status",
    "notes",
]

BANK_SCHEMA_MARKERS = {
    "interest",
    "loan",
    "credit",
    "deposit",
    "provision",
    "npl",
    "nim",
    "customer_deposits",
    "cash_and_precious_metals",
}


def load_finance_alias_config(path: str | Path = "config/finance_field_aliases_vi_en.yaml") -> dict[str, Any]:
    if yaml is None:
        raise ImportError("PyYAML is required to load finance aliases.")
    with Path(path).open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict) or not isinstance(data.get("fields"), dict):
        raise ValueError("finance alias config must contain fields mapping.")
    return data


def normalize_finance_statement_rows(
    *,
    ticker: str,
    statements: dict[str, pd.DataFrame],
    aliases_config: dict[str, Any],
    source_category: str,
    source_name: str,
    source_url: str,
    fetch_time: str,
    parser_name: str,
    confidence_raw: str = "medium",
    source_unit: str = "VND",
    requested_periods: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return long-form candidate rows plus schema diagnostics."""

    normalized_records = _normalize_statement_records(statements)
    schema_rows = []
    if not normalized_records:
        return (
            pd.DataFrame(columns=FINANCE_01I_CANDIDATE_COLUMNS),
            pd.DataFrame(
                [
                    {
                        "ticker": _clean_ticker(ticker),
                        "schema_status": "SOURCE_EMPTY_RESPONSE",
                        "detected_fields": "",
                        "unsupported_fields": "|".join(FINANCE_CANONICAL_FIELDS),
                        "raw_labels": "",
                        "notes": "source returned no statement rows",
                    }
                ]
            ),
        )

    bank_schema = detect_bank_schema(normalized_records)
    wanted_periods = {_clean_text(period) for period in requested_periods or [] if _clean_text(period)}
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    unsupported = set(FINANCE_CANONICAL_FIELDS)
    raw_labels: list[str] = []
    for record in normalized_records:
        period = _normalize_period(record.get("period"))
        if wanted_periods and period not in wanted_periods:
            continue
        label_candidates = [record.get("item_id"), record.get("item_en"), record.get("item_name")]
        raw_label = " | ".join(_clean_text(label) for label in label_candidates if _clean_text(label))
        if raw_label:
            raw_labels.append(raw_label)
        field_name, parse_status = detect_finance_field(label_candidates, aliases_config)
        if not field_name or parse_status != "FIELD_MAPPED":
            continue
        value = parse_numeric_value(record.get("value"))
        if pd.isna(value):
            continue
        key = (period, field_name)
        if key in selected:
            continue
        unsupported.discard(field_name)
        unit = source_unit or detect_unit(raw_label)
        notes = ["source value explicitly mapped; missing values remain missing"]
        field_config = aliases_config.get("fields", {}).get(field_name, {})
        if bank_schema and field_config.get("bank_notes"):
            notes.append(str(field_config["bank_notes"]))
        selected[key] = {
            "ticker": _clean_ticker(ticker),
            "period": period,
            "period_type": "quarter" if "-Q" in period else "annual",
            "field_name": field_name,
            "value": value,
            "unit": unit,
            "currency": "VND",
            "source_category": source_category,
            "source_name": source_name,
            "source_url": source_url,
            "fetch_time": fetch_time,
            "confidence_raw": confidence_raw if field_name not in {"short_term_debt", "long_term_debt"} else "low",
            "raw_label": raw_label,
            "raw_value": record.get("value"),
            "raw_period": record.get("period"),
            "parser_name": parser_name,
            "parse_status": parse_status,
            "notes": "; ".join(notes),
        }

    candidates = pd.DataFrame(list(selected.values()), columns=FINANCE_01I_CANDIDATE_COLUMNS)
    schema_status = "SCHEMA_DETECTED" if not candidates.empty else "SOURCE_SCHEMA_UNKNOWN"
    schema_rows.append(
        {
            "ticker": _clean_ticker(ticker),
            "schema_status": schema_status,
            "detected_fields": "|".join(sorted(set(candidates["field_name"]))) if not candidates.empty else "",
            "unsupported_fields": "|".join(sorted(unsupported)),
            "raw_labels": "|".join(raw_labels[:80]),
            "notes": "bank_schema_detected" if bank_schema else "non_bank_or_unknown_schema",
        }
    )
    return candidates, pd.DataFrame(schema_rows)


def detect_finance_field(labels: list[Any], aliases_config: dict[str, Any]) -> tuple[str, str]:
    tokens = {_normalize_key(label) for label in labels if _clean_text(label)}
    tokens.discard("")
    if not tokens:
        return "", "FIELD_LABEL_UNMAPPED"
    matches = []
    for field_name, field_config in aliases_config.get("fields", {}).items():
        aliases = {_normalize_key(alias) for alias in field_config.get("aliases", [])}
        if tokens.intersection(aliases):
            matches.append(str(field_name))
    if len(matches) == 1:
        return matches[0], "FIELD_MAPPED"
    if len(matches) > 1:
        return "", "FIELD_LABEL_AMBIGUOUS"
    return "", "FIELD_LABEL_UNMAPPED"


def detect_bank_schema(records: list[dict[str, Any]]) -> bool:
    joined = " ".join(
        f"{_normalize_key(record.get('item_id'))} {_normalize_key(record.get('item_name'))} {_normalize_key(record.get('item_en'))}"
        for record in records
    )
    return any(marker in joined for marker in BANK_SCHEMA_MARKERS)


def parse_numeric_value(value: Any) -> float:
    if value is None:
        return float("nan")
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if not text:
        return float("nan")
    negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[^0-9,.\-]", "", text.strip("()"))
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", "")
    try:
        number = float(cleaned)
    except ValueError:
        return float("nan")
    return -number if negative else number


def detect_unit(text: Any) -> str:
    normalized = _normalize_key(text)
    if "billion" in normalized or "ty_dong" in normalized:
        return "billion VND"
    if "million" in normalized or "trieu_dong" in normalized:
        return "million VND"
    if "thousand" in normalized or "nghin_dong" in normalized:
        return "thousand VND"
    return "VND"


def build_finance_field_coverage_by_source(candidates: pd.DataFrame) -> pd.DataFrame:
    columns = ["source_category", "source_name", "field_name", "row_count", "ticker_count", "period_count", "notes"]
    if not isinstance(candidates, pd.DataFrame) or candidates.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for key, group in candidates.groupby(["source_category", "source_name", "field_name"], dropna=False):
        category, name, field_name = key
        rows.append(
            {
                "source_category": category,
                "source_name": name,
                "field_name": field_name,
                "row_count": int(len(group)),
                "ticker_count": int(group["ticker"].nunique()),
                "period_count": int(group["period"].nunique()),
                "notes": "01I normalized source-provided candidate values only",
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _normalize_statement_records(statements: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for statement_type, df in statements.items():
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        id_columns = [column for column in ["item_id", "item", "item_name", "item_en"] if column in df.columns]
        period_columns = [column for column in df.columns if _looks_like_period(column)]
        for _, row in df.iterrows():
            item_id = row.get("item_id", "")
            item_name = row.get("item", row.get("item_name", ""))
            item_en = row.get("item_en", "")
            for period_column in period_columns:
                records.append(
                    {
                        "statement_type": statement_type,
                        "period": period_column,
                        "item_id": item_id,
                        "item_name": item_name,
                        "item_en": item_en,
                        "value": row.get(period_column),
                    }
                )
        if not period_columns and {"period", "value"}.issubset(set(df.columns)):
            for _, row in df.iterrows():
                records.append(
                    {
                        "statement_type": statement_type,
                        "period": row.get("period"),
                        "item_id": row.get("item_id", ""),
                        "item_name": row.get("item", row.get("item_name", "")),
                        "item_en": row.get("item_en", ""),
                        "value": row.get("value"),
                    }
                )
    return records


def _looks_like_period(value: Any) -> bool:
    text = _clean_text(value)
    return bool(re.match(r"^\d{4}(-Q[1-4])?$", text))


def _normalize_period(value: Any) -> str:
    text = _clean_text(value).upper()
    match = re.match(r"^(\d{4})[-_ ]?Q([1-4])$", text)
    if match:
        return f"{match.group(1)}-Q{match.group(2)}"
    match = re.match(r"^(\d{4})$", text)
    if match:
        return match.group(1)
    return text


def _normalize_key(value: Any) -> str:
    text = _clean_text(value).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _clean_ticker(value: Any) -> str:
    return _clean_text(value).upper()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()

