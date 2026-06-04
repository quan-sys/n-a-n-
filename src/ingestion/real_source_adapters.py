"""Real-source adapter status and manual template helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pandas as pd


SOURCE_ADAPTER_STATUS_COLUMNS = [
    "adapter_name",
    "dataset_name",
    "status",
    "dependency_available",
    "real_source_available",
    "supported_fields",
    "unsupported_fields",
    "notes",
]

FINANCIAL_TEMPLATE_COLUMNS = [
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

DISCLOSURE_TEMPLATE_COLUMNS = [
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


def dependency_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def build_source_adapter_status(
    *,
    vnstock_available: bool | None = None,
    vnstock_ezchart_available: bool | None = None,
    financial_real_rows: int = 0,
    disclosure_real_rows: int = 0,
) -> pd.DataFrame:
    """Return adapter availability report rows for REAL-DATA-01B."""

    has_vnstock = dependency_available("vnstock") if vnstock_available is None else vnstock_available
    has_ezchart = (
        dependency_available("vnstock_ezchart")
        if vnstock_ezchart_available is None
        else vnstock_ezchart_available
    )
    vnstock_status = "AVAILABLE" if has_vnstock else "DEPENDENCY_UNAVAILABLE"
    rows = [
        _row(
            "vnstock_kbs_listing",
            "universe",
            vnstock_status,
            has_vnstock,
            has_vnstock,
            ["ticker", "exchange", "company_name", "listing_status"],
            ["active_status_confirmed_by_exchange"],
            "Universe selected from live listing source; status inferred from current symbol universe.",
        ),
        _row(
            "vnstock_company_overview",
            "company_profile",
            vnstock_status,
            has_vnstock,
            has_vnstock,
            ["ticker", "company_name", "exchange", "industry_raw_if_source_provides"],
            ["business_description_if_not_exposed_by_source"],
            "No business description is inferred from ticker/name.",
        ),
        _row(
            "vnstock_vci_quote_history",
            "market_price",
            vnstock_status,
            has_vnstock,
            has_vnstock,
            ["ticker", "date", "close", "volume", "trading_value_derived_from_close_volume"],
            ["exchange_confirmed_trading_value_field"],
            "Trading value is derived only when fetched close and volume are present.",
        ),
        _row(
            "vnstock_vci_finance",
            "financial_statement_summary",
            "AVAILABLE_WITH_ROWS" if financial_real_rows else vnstock_status,
            has_vnstock and has_ezchart,
            has_vnstock,
            FINANCIAL_TEMPLATE_COLUMNS,
            ["fields_not_returned_by_source_are_left_blank"],
            "Requires vnstock and optional charting dependency in some environments.",
        ),
        _row(
            "manual_financial_statement_template",
            "financial_statement_summary",
            "TEMPLATE_AVAILABLE",
            True,
            False,
            FINANCIAL_TEMPLATE_COLUMNS,
            [],
            "Manual import path; values must be user/source provided, never fabricated.",
        ),
        _row(
            "vnstock_company_events",
            "disclosure_status",
            "AVAILABLE_WITH_ROWS" if disclosure_real_rows else vnstock_status,
            has_vnstock,
            has_vnstock,
            DISCLOSURE_TEMPLATE_COLUMNS,
            ["clean_disclosure_confirmation"],
            "No rows means unknown/unavailable, not clean.",
        ),
        _row(
            "manual_disclosure_status_template",
            "disclosure_status",
            "TEMPLATE_AVAILABLE",
            True,
            False,
            DISCLOSURE_TEMPLATE_COLUMNS,
            [],
            "Manual import path; no-disclosure cannot be assumed clean.",
        ),
    ]
    return pd.DataFrame(rows, columns=SOURCE_ADAPTER_STATUS_COLUMNS)


def create_manual_templates(
    *,
    financial_template_path: str | Path = "data/templates/financial_statement_summary_template.csv",
    disclosure_template_path: str | Path = "data/templates/disclosure_status_template.csv",
) -> dict[str, str]:
    """Create empty CSV templates for unavailable manual datasets."""

    financial_path = _write_template(financial_template_path, FINANCIAL_TEMPLATE_COLUMNS)
    disclosure_path = _write_template(disclosure_template_path, DISCLOSURE_TEMPLATE_COLUMNS)
    return {
        "financial_statement_summary": str(financial_path),
        "disclosure_status": str(disclosure_path),
    }


def empty_source_adapter_status() -> pd.DataFrame:
    return pd.DataFrame(columns=SOURCE_ADAPTER_STATUS_COLUMNS)


def _write_template(path: str | Path, columns: list[str]) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=columns).to_csv(output_path, index=False)
    return output_path


def _row(
    adapter_name: str,
    dataset_name: str,
    status: str,
    dependency_available_value: bool,
    real_source_available: bool,
    supported_fields: list[str],
    unsupported_fields: list[str],
    notes: str,
) -> dict[str, Any]:
    return {
        "adapter_name": adapter_name,
        "dataset_name": dataset_name,
        "status": status,
        "dependency_available": bool(dependency_available_value),
        "real_source_available": bool(real_source_available),
        "supported_fields": "|".join(supported_fields),
        "unsupported_fields": "|".join(unsupported_fields),
        "notes": notes,
    }
