from pathlib import Path

import pandas as pd

from src.ingestion.legacy_structured_finance_importer import (
    PROVISIONAL_CONFIDENCE,
    forbidden_bias_columns,
    import_legacy_structured_finance,
)


def test_imported_data_is_provisional_and_forbidden_fields_are_ignored(tmp_path: Path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    _write_minimal_legacy_export(input_dir)
    long = pd.read_csv(input_dir / "legacy_structured_finance_long.csv")
    long["fair_value"] = 999
    long.to_csv(input_dir / "legacy_structured_finance_long.csv", index=False)

    summary = import_legacy_structured_finance(input_dir, output_dir)

    imported = pd.read_csv(output_dir / "provisional_structured_finance_long.csv", keep_default_na=False)
    assert summary["imported_finance_long_rows"] == 1
    assert imported["source_confidence"].eq(PROVISIONAL_CONFIDENCE).all()
    assert imported["source_layer"].eq(PROVISIONAL_CONFIDENCE).all()
    assert forbidden_bias_columns(imported.columns) == []


def test_missing_values_are_preserved_not_zero_filled(tmp_path: Path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    _write_minimal_legacy_export(input_dir, include_finance_value=False)

    import_legacy_structured_finance(input_dir, output_dir)

    wide = pd.read_csv(output_dir / "provisional_finance_latest_wide.csv", keep_default_na=False)
    assert wide.iloc[0]["net_income"] == ""
    assert wide.iloc[0]["missing_fields"] == "net_income"
    assert "0" not in set(wide[["net_income"]].astype(str).stack())


def _write_minimal_legacy_export(input_dir: Path, include_finance_value: bool = True) -> None:
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "period": "2025",
                "period_type": "year",
                "fiscal_year": "2025",
                "field_name": "net_income",
                "raw_value": 10 if include_finance_value else "",
                "value": 10 if include_finance_value else "",
                "unit_raw": "legacy",
                "currency": "",
                "source_name": "vnstock_finance_v1",
                "source_type": "structured_legacy_cache",
                "source_confidence": "medium",
                "source_url": "",
                "fetched_at": "2026-01-01T00:00:00Z",
                "cache_key": "AAA/l4.json",
                "legacy_function": "fetch_vnstock_financial_statements",
                "missing_flag": not include_finance_value,
                "parse_status": "PARSED_FROM_LEGACY_CACHE",
                "notes": "",
            }
        ]
    ).to_csv(input_dir / "legacy_structured_finance_long.csv", index=False)
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "exchange": "HOSE",
                "company_name": "AAA",
                "sector_raw": "Sector",
                "industry_raw": "Industry",
                "period": "2025",
                "period_type": "year",
                "fiscal_year": "2025",
                "revenue": 100 if include_finance_value else "",
                "gross_profit": 20 if include_finance_value else "",
                "net_income": 10 if include_finance_value else "",
                "total_assets": 200 if include_finance_value else "",
                "total_liabilities": 80 if include_finance_value else "",
                "equity": 120 if include_finance_value else "",
                "cfo": 12 if include_finance_value else "",
                "capex": -4 if include_finance_value else "",
                "source_name": "vnstock_finance_v1",
                "source_confidence": "medium",
                "provisional_only": True,
                "fetched_at": "2026-01-01T00:00:00Z",
                "finance_completeness_score": 1 if include_finance_value else 0,
                "missing_fields": "" if include_finance_value else "net_income",
                "source_count": 1 if include_finance_value else 0,
            }
        ]
    ).to_csv(input_dir / "legacy_structured_finance_latest_wide.csv", index=False)
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "exchange": "HOSE",
                "company_name": "AAA",
                "sector_raw": "Sector",
                "industry_raw": "Industry",
                "last_close": 10,
                "last_price_date": "",
                "avg_volume_20d": "",
                "avg_volume_60d": 1000,
                "trading_days_60d": "",
                "source_name": "legacy_market",
                "source_confidence": "medium",
                "fetched_at": "2026-01-01T00:00:00Z",
                "stale_price_flag": True,
                "missing_price_flag": False,
                "low_liquidity_flag": False,
            }
        ]
    ).to_csv(input_dir / "legacy_market_liquidity.csv", index=False)
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "has_income_statement": include_finance_value,
                "has_balance_sheet": include_finance_value,
                "has_cash_flow": include_finance_value,
                "has_market_price": True,
                "has_volume": True,
                "finance_field_count": 8 if include_finance_value else 0,
                "missing_required_fields": "" if include_finance_value else "net_income",
                "legacy_cache_status": "L4_CACHE_PRESENT",
                "export_status": "OK_FOR_PROVISIONAL_SCREEN" if include_finance_value else "PARTIAL_PROVISIONAL_DATA",
                "notes": "test",
            }
        ]
    ).to_csv(input_dir / "legacy_data_quality_flags.csv", index=False)
