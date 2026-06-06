from __future__ import annotations

import pandas as pd

from src.ingestion.finance_candidate_normalizer import (
    FINANCE_01I_CANDIDATE_COLUMNS,
    load_finance_alias_config,
    normalize_finance_statement_rows,
)
from src.ingestion.finance_numeric_reconciliation import reconcile_numeric_candidates


def test_01i_maps_vnstock_bank_profit_and_cash_flow_aliases_without_fabricating_missing_values():
    aliases = load_finance_alias_config()
    income = pd.DataFrame(
        [
            {"item_id": "attributable_to_parent_company", "item": "Co dong cua Cong ty me", "item_en": "Attributable to parent company", "2025-Q4": 1200},
            {"item_id": "interest_and_similar_income", "item": "Thu nhap lai", "item_en": "Interest and similar income", "2025-Q4": 3000},
        ]
    )
    balance = pd.DataFrame(
        [
            {"item_id": "cash_and_precious_metals", "item": "Tien mat vang bac da quy", "item_en": "Cash and precious metals", "2025-Q4": 500},
            {"item_id": "total_assets", "item": "Tong tai san", "item_en": "Total assets", "2025-Q4": 9000},
            {"item_id": "liabilities", "item": "No phai tra", "item_en": "Liabilities", "2025-Q4": 7000},
            {"item_id": "owners_equity", "item": "Von chu so huu", "item_en": "Owners equity", "2025-Q4": 2000},
        ]
    )
    cash_flow = pd.DataFrame(
        [
            {"item_id": "net_cash_from_operating_activities", "item": "Luu chuyen tien thuan tu HDKD", "item_en": "Net cash from operating activities", "2025-Q4": 800}
        ]
    )

    candidates, schema = normalize_finance_statement_rows(
        ticker="VCB",
        statements={"income": income, "balance": balance, "cash_flow": cash_flow},
        aliases_config=aliases,
        source_category="vnstock",
        source_name="vnstock:vci:finance",
        source_url="https://vnstocks.com/",
        fetch_time="2026-06-06T00:00:00+00:00",
        parser_name="test",
        requested_periods=["2025-Q4"],
    )

    assert list(candidates.columns) == FINANCE_01I_CANDIDATE_COLUMNS
    assert set(candidates["field_name"]) == {
        "cash",
        "equity",
        "net_profit",
        "operating_cash_flow",
        "revenue",
        "total_assets",
        "total_liabilities",
    }
    assert "inventory" not in set(candidates["field_name"])
    assert "short_term_debt" not in set(candidates["field_name"])
    assert "BANK_CASH_SCHEMA_EXPLICITLY_MAPPED" in "|".join(candidates["notes"].astype(str))
    assert schema.iloc[0]["schema_status"] == "SCHEMA_DETECTED"


def test_01i_numeric_conflicts_send_cross_source_variance_to_manual_review():
    rows = pd.DataFrame(
        [
            {"ticker": "HPG", "period": "2025-Q4", "field_name": "net_profit", "value": 100, "source_category": "cafef", "source_name": "cafef"},
            {"ticker": "HPG", "period": "2025-Q4", "field_name": "net_profit", "value": 140, "source_category": "vietstock", "source_name": "vietstock"},
        ]
    )

    conflicts = reconcile_numeric_candidates(rows, tolerance_pct=0.01, minor_variance_tolerance_pct=0.03)

    assert len(conflicts) == 1
    assert conflicts.iloc[0]["conflict_status"] == "FIELD_CONFLICT_BETWEEN_SOURCES"
    assert bool(conflicts.iloc[0]["manual_review_required"]) is True

