"""Safe financial statement mapping for real-source raw statements."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd


CANONICAL_FINANCIAL_COLUMNS = [
    "ticker",
    "period",
    "period_type",
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

FINANCE_FIELD_COVERAGE_COLUMNS = [
    "ticker",
    "period",
    "period_type",
    "has_revenue",
    "has_net_profit",
    "has_total_assets",
    "has_total_liabilities",
    "has_equity",
    "has_cash",
    "has_operating_cash_flow",
    "has_inventory",
    "missing_fields",
    "not_applicable_fields",
    "source",
    "confidence_raw",
    "notes",
]

FIELD_ALIASES = {
    "revenue": ["revenue", "sales", "net_sales", "net_revenue", "doanh_thu"],
    "gross_profit": ["gross_profit", "gross_margin", "loi_nhuan_gop"],
    "operating_profit": ["operating_profit", "operating_income", "operating_profit_loss"],
    "net_profit": ["post_tax_profit", "net_profit", "net_profit_after_tax", "profit_after_tax"],
    "total_assets": ["total_assets", "assets"],
    "total_liabilities": ["liabilities", "total_liabilities"],
    "equity": ["owners_equity", "equity", "shareholders_equity"],
    "cash": ["cash_and_cash_equivalents", "cash"],
    "short_term_debt": ["short_term_borrowings", "short_term_debt"],
    "long_term_debt": ["long_term_borrowings", "long_term_debt"],
    "operating_cash_flow": [
        "net_cash_inflows_outflows_from_operating_activities",
        "cash_flows_from_operating_activities",
        "operating_cash_flow",
    ],
    "inventory": ["inventories_net", "inventories", "inventory"],
}

BANK_NOT_APPLICABLE_FIELDS = {"gross_profit", "inventory"}
BANK_SCHEMA_MARKERS = {
    "interest",
    "loan",
    "loans",
    "credit",
    "deposit",
    "provision",
    "npl",
    "nim",
}


def map_financial_statement_summary(
    *,
    ticker: str,
    statements: dict[str, pd.DataFrame],
    fetch_time: str,
    source: str = "vnstock:vci:finance",
    source_url: str = "https://vnstocks.com/",
    period_type: str = "quarter",
    is_bank: bool | None = None,
) -> tuple[dict[str, Any] | None, list[str], list[str], list[str]]:
    """Map source-provided financial data to canonical fields without fabrication."""

    normalized = normalize_statement_records(statements)
    if not normalized:
        return None, ["FINANCIAL_SOURCE_EMPTY_RESPONSE"], [], []

    bank_schema = detect_bank_schema(normalized) if is_bank is None else bool(is_bank)
    period = latest_period([record["period"] for record in normalized])
    if not period:
        return None, ["FINANCIAL_SOURCE_SCHEMA_UNKNOWN"], [], []

    period_records = [record for record in normalized if record["period"] == period]
    record: dict[str, Any] = {
        "ticker": clean_ticker(ticker),
        "period": period,
        "period_type": period_type,
        "source": source,
        "source_url": source_url,
        "fetch_time": fetch_time,
        "confidence_raw": "medium",
    }
    warnings: list[str] = []
    not_applicable = sorted(BANK_NOT_APPLICABLE_FIELDS) if bank_schema else []
    missing_fields: list[str] = []

    for field, aliases in FIELD_ALIASES.items():
        value = find_financial_value(period_records, aliases)
        if not is_missing(value):
            record[field] = value
            continue
        record[field] = pd.NA
        if field in not_applicable:
            continue
        missing_fields.append(field)
        warnings.append(f"FINANCIAL_FIELD_UNMAPPED:{field}")

    if missing_fields or not_applicable:
        warnings.append("FINANCIAL_PARTIAL_ROW")
        warnings.append(
            "BANK_FINANCIAL_SCHEMA_PARTIAL"
            if bank_schema
            else "NON_BANK_FINANCIAL_SCHEMA_PARTIAL"
        )

    record["confidence_raw"] = "low" if missing_fields else "medium"
    notes = []
    if missing_fields:
        notes.append("MISSING_FINANCIAL_FIELD:" + ",".join(missing_fields))
    if not_applicable:
        notes.append("NOT_APPLICABLE:" + ",".join(not_applicable))
    notes.append("source values mapped only when explicitly present; no missing values fabricated")
    record["notes"] = "; ".join(notes)
    return record, dedupe(warnings), missing_fields, not_applicable


def normalize_statement_records(statements: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for statement_type, df in statements.items():
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        if "period" in df.columns and "value" in df.columns:
            records.extend(_normalize_long_statement(df, statement_type))
        else:
            records.extend(_normalize_wide_statement(df, statement_type))
    return records


def build_finance_field_coverage(
    financial_df: pd.DataFrame,
    *,
    tickers: list[str],
) -> pd.DataFrame:
    rows = []
    source_by_ticker = {}
    if isinstance(financial_df, pd.DataFrame) and not financial_df.empty and "ticker" in financial_df.columns:
        for _, row in financial_df.iterrows():
            source_by_ticker[clean_ticker(row.get("ticker"))] = row
    for ticker in tickers:
        row = source_by_ticker.get(clean_ticker(ticker))
        if row is None:
            rows.append(
                {
                    "ticker": clean_ticker(ticker),
                    "period": "",
                    "period_type": "",
                    "has_revenue": False,
                    "has_net_profit": False,
                    "has_total_assets": False,
                    "has_total_liabilities": False,
                    "has_equity": False,
                    "has_cash": False,
                    "has_operating_cash_flow": False,
                    "has_inventory": False,
                    "missing_fields": "financial_statement_summary",
                    "not_applicable_fields": "",
                    "source": "",
                    "confidence_raw": "low",
                    "notes": "FINANCIAL_STATEMENT_DATA_UNAVAILABLE",
                }
            )
            continue
        missing = []
        for field in [
            "revenue",
            "net_profit",
            "total_assets",
            "total_liabilities",
            "equity",
            "cash",
            "operating_cash_flow",
            "inventory",
        ]:
            if is_missing(row.get(field)):
                missing.append(field)
        rows.append(
            {
                "ticker": clean_ticker(ticker),
                "period": clean_text(row.get("period")),
                "period_type": clean_text(row.get("period_type")),
                "has_revenue": not is_missing(row.get("revenue")),
                "has_net_profit": not is_missing(row.get("net_profit")),
                "has_total_assets": not is_missing(row.get("total_assets")),
                "has_total_liabilities": not is_missing(row.get("total_liabilities")),
                "has_equity": not is_missing(row.get("equity")),
                "has_cash": not is_missing(row.get("cash")),
                "has_operating_cash_flow": not is_missing(row.get("operating_cash_flow")),
                "has_inventory": not is_missing(row.get("inventory")),
                "missing_fields": ",".join(missing),
                "not_applicable_fields": _not_applicable_from_notes(row.get("notes")),
                "source": clean_text(row.get("source")),
                "confidence_raw": clean_text(row.get("confidence_raw")),
                "notes": clean_text(row.get("notes")),
            }
        )
    return pd.DataFrame(rows, columns=FINANCE_FIELD_COVERAGE_COLUMNS)


def detect_bank_schema(records: list[dict[str, Any]]) -> bool:
    joined = " ".join(
        clean_text(record.get("item_id")) + " " + clean_text(record.get("item_name"))
        for record in records
    ).lower()
    return any(marker in joined for marker in BANK_SCHEMA_MARKERS)


def find_financial_value(records: list[dict[str, Any]], aliases: list[str]) -> Any:
    normalized_aliases = {normalize_key(alias) for alias in aliases}
    for record in records:
        keys = {
            normalize_key(record.get("item_id")),
            normalize_key(record.get("item_name")),
            normalize_key(record.get("item_en")),
        }
        if normalized_aliases.intersection(keys) and not is_missing(record.get("value")):
            return record["value"]
    return pd.NA


def latest_period(periods: list[Any]) -> str:
    valid = [clean_text(period) for period in periods if clean_text(period)]
    if not valid:
        return ""
    return sorted(valid, key=period_sort_key, reverse=True)[0]


def period_sort_key(period: str) -> tuple[int, int]:
    match = re.search(r"(?P<year>\d{4})\D*Q(?P<quarter>[1-4])", period.upper())
    if match:
        return int(match.group("year")), int(match.group("quarter"))
    match = re.search(r"(?P<year>\d{4})", period)
    if match:
        return int(match.group("year")), 0
    return 0, 0


def _normalize_wide_statement(df: pd.DataFrame, statement_type: str) -> list[dict[str, Any]]:
    item_id_col = first_existing_column(df, ["item_id", "code", "field", "metric"])
    item_name_col = first_existing_column(df, ["item", "item_name", "name", "item_vn"])
    item_en_col = first_existing_column(df, ["item_en", "english_name"])
    period_columns = [column for column in df.columns if is_period_column(column)]
    if not period_columns or not (item_id_col or item_name_col):
        return []
    records = []
    for _, row in df.iterrows():
        for period in period_columns:
            records.append(
                {
                    "statement_type": statement_type,
                    "period": clean_text(period),
                    "item_id": row.get(item_id_col) if item_id_col else "",
                    "item_name": row.get(item_name_col) if item_name_col else "",
                    "item_en": row.get(item_en_col) if item_en_col else "",
                    "value": row.get(period),
                }
            )
    return records


def _normalize_long_statement(df: pd.DataFrame, statement_type: str) -> list[dict[str, Any]]:
    item_id_col = first_existing_column(df, ["item_id", "code", "field", "metric"])
    item_name_col = first_existing_column(df, ["item", "item_name", "name", "item_vn"])
    item_en_col = first_existing_column(df, ["item_en", "english_name"])
    records = []
    for _, row in df.iterrows():
        records.append(
            {
                "statement_type": statement_type,
                "period": clean_text(row.get("period")),
                "item_id": row.get(item_id_col) if item_id_col else "",
                "item_name": row.get(item_name_col) if item_name_col else "",
                "item_en": row.get(item_en_col) if item_en_col else "",
                "value": row.get("value"),
            }
        )
    return records


def is_period_column(value: Any) -> bool:
    text = clean_text(value)
    return bool(re.search(r"^\d{4}(\D*Q[1-4])?$", text.upper()))


def first_existing_column(df: pd.DataFrame, columns: list[str]) -> str:
    for column in columns:
        if column in df.columns:
            return column
    return ""


def normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", clean_text(value).lower()).strip("_")


def _not_applicable_from_notes(value: Any) -> str:
    text = clean_text(value)
    marker = "NOT_APPLICABLE:"
    if marker not in text:
        return ""
    return text.split(marker, 1)[1].split(";", 1)[0].strip()


def clean_ticker(value: Any) -> str:
    if is_missing(value):
        return ""
    return str(value).strip().upper()


def clean_text(value: Any) -> str:
    if is_missing(value):
        return ""
    return str(value).strip()


def is_missing(value: Any) -> bool:
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


def dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(values))
