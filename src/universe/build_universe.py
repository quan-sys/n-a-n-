"""Build the initial clean universe before filtering or scoring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None


OUTPUT_COLUMNS = [
    "ticker",
    "exchange",
    "company_name",
    "listing_status",
    "is_active",
    "has_basic_profile",
    "has_market_data",
    "has_financial_data",
    "has_disclosure_data",
    "universe_status",
    "universe_warnings",
    "data_sanity_status",
    "manual_review_required",
]

DEFAULT_UNIVERSE_RULES = {
    "allowed_exchanges": ["HOSE", "HNX", "UPCOM"],
    "active_listing_statuses": ["ACTIVE", "LISTED", "TRADING"],
    "warning_listing_statuses": [
        "UNKNOWN",
        "SUSPENDED",
        "RESTRICTED",
        "DELISTING_WARNING",
    ],
    "required_data_groups": [
        "universe",
        "market_price",
        "company_profile",
        "financial_statement_summary",
    ],
    "optional_data_groups": ["disclosure_status"],
    "required_profile_fields": ["ticker", "company_name", "exchange"],
    "required_market_fields": ["ticker", "date", "close", "volume", "trading_value"],
    "required_financial_fields": [
        "ticker",
        "period",
        "revenue",
        "net_profit",
        "equity",
        "total_assets",
        "total_liabilities",
    ],
}

SERIOUS_WARNING_FLAGS = {
    "MISSING_TICKER",
    "EXCHANGE_NOT_ALLOWED",
    "UNKNOWN_LISTING_STATUS",
    "MISSING_PROFILE",
    "MISSING_MARKET_DATA",
    "MISSING_FINANCIAL_DATA",
}


def load_universe_rules(path: str) -> dict[str, Any]:
    """Load universe-builder rules from YAML."""

    if yaml is None:
        raise ImportError(
            "PyYAML is required to load YAML rule files. Install 'pyyaml' or "
            "provide rules directly to build_clean_universe()."
        )

    rules_path = Path(path)
    with rules_path.open("r", encoding="utf-8") as rules_file:
        rules = yaml.safe_load(rules_file)

    if not isinstance(rules, dict):
        raise ValueError("Universe rules must contain a YAML mapping at the top level.")

    return rules


def build_clean_universe(
    universe_df: pd.DataFrame,
    company_profile_df: pd.DataFrame | None = None,
    market_price_df: pd.DataFrame | None = None,
    financial_statement_df: pd.DataFrame | None = None,
    disclosure_df: pd.DataFrame | None = None,
    rules: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Build a clean initial universe with availability and status flags."""

    if not isinstance(universe_df, pd.DataFrame):
        raise TypeError("universe_df must be a pandas DataFrame.")

    active_rules = _merge_rules(rules)
    allowed_exchanges = _normalized_set(active_rules["allowed_exchanges"])
    active_listing_statuses = _normalized_set(active_rules["active_listing_statuses"])
    warning_listing_statuses = _normalized_set(active_rules["warning_listing_statuses"])

    rows: list[dict[str, Any]] = []
    for _, source_row in universe_df.iterrows():
        ticker = _clean_text(_row_value(source_row, "ticker"))
        exchange = _clean_text(_row_value(source_row, "exchange"))
        listing_status = _clean_text(_row_value(source_row, "listing_status"))
        company_name = _clean_text(_row_value(source_row, "company_name"))
        if not company_name and ticker:
            company_name = _first_matching_value(
                company_profile_df, ticker, "company_name"
            )

        warnings: list[str] = []
        if not ticker:
            warnings.append("MISSING_TICKER")

        exchange_allowed = bool(exchange) and exchange in allowed_exchanges
        if not exchange_allowed:
            warnings.append("EXCHANGE_NOT_ALLOWED")

        is_active = bool(listing_status) and listing_status in active_listing_statuses
        is_warning_listing_status = (
            bool(listing_status) and listing_status in warning_listing_statuses
        )
        if not listing_status or listing_status == "UNKNOWN":
            warnings.append("UNKNOWN_LISTING_STATUS")
        elif not is_active and not is_warning_listing_status:
            warnings.append("UNKNOWN_LISTING_STATUS")

        has_basic_profile = _has_required_row(
            company_profile_df,
            ticker,
            active_rules["required_profile_fields"],
        )
        has_market_data = _has_required_row(
            market_price_df,
            ticker,
            active_rules["required_market_fields"],
        )
        has_financial_data = _has_required_row(
            financial_statement_df,
            ticker,
            active_rules["required_financial_fields"],
        )
        has_disclosure_data = _has_ticker_record(disclosure_df, ticker)
        quality_warnings = _quality_warnings_for_ticker(
            ticker=ticker,
            company_profile_df=company_profile_df,
            market_price_df=market_price_df,
            financial_statement_df=financial_statement_df,
            disclosure_df=disclosure_df,
        )

        if ticker and not has_basic_profile:
            warnings.append("MISSING_PROFILE")
        if ticker and not has_market_data:
            warnings.append("MISSING_MARKET_DATA")
        if ticker and not has_financial_data:
            warnings.append("MISSING_FINANCIAL_DATA")
        if has_disclosure_data:
            warnings.append("HAS_DISCLOSURE_RECORDS")
        warnings.extend(quality_warnings)

        universe_status = _resolve_universe_status(
            ticker=ticker,
            exchange_allowed=exchange_allowed,
            is_active=is_active,
            is_warning_listing_status=is_warning_listing_status,
            has_basic_profile=has_basic_profile,
            has_market_data=has_market_data,
            has_financial_data=has_financial_data,
            has_quality_review_warning=bool(quality_warnings),
        )
        data_sanity_status = _resolve_data_sanity_status(
            universe_status=universe_status,
            warnings=warnings,
            is_active=is_active,
            is_warning_listing_status=is_warning_listing_status,
        )
        manual_review_required = universe_status == "MANUAL_REVIEW" or bool(
            SERIOUS_WARNING_FLAGS.intersection(warnings)
        )

        rows.append(
            {
                "ticker": ticker,
                "exchange": exchange,
                "company_name": company_name,
                "listing_status": listing_status,
                "is_active": bool(is_active),
                "has_basic_profile": bool(has_basic_profile),
                "has_market_data": bool(has_market_data),
                "has_financial_data": bool(has_financial_data),
                "has_disclosure_data": bool(has_disclosure_data),
                "universe_status": universe_status,
                "universe_warnings": warnings,
                "data_sanity_status": data_sanity_status,
                "manual_review_required": bool(manual_review_required),
            }
        )

    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    for column in [
        "is_active",
        "has_basic_profile",
        "has_market_data",
        "has_financial_data",
        "has_disclosure_data",
        "manual_review_required",
    ]:
        result[column] = result[column].astype(object)

    return result


def _merge_rules(rules: dict[str, Any] | None) -> dict[str, Any]:
    merged = {key: list(value) for key, value in DEFAULT_UNIVERSE_RULES.items()}
    if rules:
        for key, value in rules.items():
            merged[key] = value
    return merged


def _normalized_set(values: list[Any]) -> set[str]:
    return {_clean_text(value) for value in values if _clean_text(value)}


def _clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip().upper()


def _row_value(row: pd.Series, column: str) -> Any:
    if column not in row.index:
        return None
    return row[column]


def _has_required_row(
    df: pd.DataFrame | None, ticker: str, required_fields: list[str]
) -> bool:
    if df is None or df.empty or not ticker or "ticker" not in df.columns:
        return False

    if any(field not in df.columns for field in required_fields):
        return False

    matching_rows = df[df["ticker"].map(_clean_text) == ticker]
    if matching_rows.empty:
        return False

    for _, row in matching_rows.iterrows():
        if all(_has_value(row[field]) for field in required_fields):
            return True

    return False


def _has_ticker_record(df: pd.DataFrame | None, ticker: str) -> bool:
    if df is None or df.empty or not ticker or "ticker" not in df.columns:
        return False
    return bool((df["ticker"].map(_clean_text) == ticker).any())


def _first_matching_value(
    df: pd.DataFrame | None, ticker: str, column: str
) -> str:
    if df is None or df.empty or not ticker or column not in df.columns:
        return ""

    matching_rows = df[df["ticker"].map(_clean_text) == ticker]
    if matching_rows.empty:
        return ""

    value = matching_rows.iloc[0][column]
    if not _has_value(value):
        return ""
    return str(value).strip()


def _quality_warnings_for_ticker(
    *,
    ticker: str,
    company_profile_df: pd.DataFrame | None,
    market_price_df: pd.DataFrame | None,
    financial_statement_df: pd.DataFrame | None,
    disclosure_df: pd.DataFrame | None,
) -> list[str]:
    if not ticker:
        return []

    warnings: list[str] = []
    quality_sources = [
        ("company_profile", company_profile_df, "PROFILE_DATA_QUALITY_REVIEW"),
        ("market_price", market_price_df, "MARKET_DATA_QUALITY_REVIEW"),
        (
            "financial_statement_summary",
            financial_statement_df,
            "FINANCIAL_DATA_QUALITY_REVIEW",
        ),
        ("disclosure_status", disclosure_df, "DISCLOSURE_DATA_QUALITY_REVIEW"),
    ]
    for _, df, warning_name in quality_sources:
        if _ticker_has_quality_review_flag(df, ticker):
            warnings.append(warning_name)

    return _dedupe(warnings)


def _ticker_has_quality_review_flag(df: pd.DataFrame | None, ticker: str) -> bool:
    if df is None or df.empty or "ticker" not in df.columns:
        return False

    matching_rows = df[df["ticker"].map(_clean_text) == ticker]
    if matching_rows.empty:
        return False

    if (
        "manual_review_required" in matching_rows.columns
        and matching_rows["manual_review_required"].map(bool).any()
    ):
        return True

    if "quality_status" in matching_rows.columns:
        statuses = {
            _clean_text(value)
            for value in matching_rows["quality_status"]
            if _has_value(value)
        }
        if statuses - {"VALID_DATA"}:
            return True

    if "final_confidence" in matching_rows.columns:
        confidences = {
            _clean_text(value)
            for value in matching_rows["final_confidence"]
            if _has_value(value)
        }
        if "LOW" in confidences:
            return True

    if "quality_errors" in matching_rows.columns:
        if matching_rows["quality_errors"].map(_has_non_empty_issue_list).any():
            return True

    return False


def _has_value(value: Any) -> bool:
    if value is None or pd.isna(value):
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def _resolve_universe_status(
    *,
    ticker: str,
    exchange_allowed: bool,
    is_active: bool,
    is_warning_listing_status: bool,
    has_basic_profile: bool,
    has_market_data: bool,
    has_financial_data: bool,
    has_quality_review_warning: bool,
) -> str:
    if not ticker or not exchange_allowed:
        return "REJECT_UNIVERSE"
    if not has_basic_profile or not has_market_data or not has_financial_data:
        return "MANUAL_REVIEW"
    if has_quality_review_warning:
        return "MANUAL_REVIEW"
    if not is_active or is_warning_listing_status:
        return "WATCH_UNIVERSE"
    return "PASS_UNIVERSE"


def _resolve_data_sanity_status(
    *,
    universe_status: str,
    warnings: list[str],
    is_active: bool,
    is_warning_listing_status: bool,
) -> str:
    if universe_status == "REJECT_UNIVERSE":
        return "DATA_ERROR"
    if any(
        warning in warnings
        for warning in [
            "MISSING_PROFILE",
            "MISSING_MARKET_DATA",
            "MISSING_FINANCIAL_DATA",
        ]
    ):
        return "MISSING_DATA"
    if any(warning.endswith("_DATA_QUALITY_REVIEW") for warning in warnings):
        return "MANUAL_REVIEW"
    if not is_active or is_warning_listing_status:
        return "MANUAL_REVIEW"
    return "VALID_DATA"


def _has_non_empty_issue_list(value: Any) -> bool:
    if isinstance(value, list):
        return bool(value)
    if isinstance(value, str):
        stripped = value.strip()
        return bool(stripped) and stripped not in {"[]", ""}
    return False


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
