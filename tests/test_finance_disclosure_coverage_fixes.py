import importlib.util
import sys
import types
from pathlib import Path

import pandas as pd

from src.ingestion.contracts import PROHIBITED_RECOMMENDATION_FIELDS, load_ingestion_contracts
from src.ingestion.disclosure_source_mapper import build_disclosure_coverage_status
from src.ingestion.finance_statement_mapper import (
    build_finance_field_coverage,
    map_financial_statement_summary,
)
from src.ingestion.real_source_adapters import (
    DISCLOSURE_TEMPLATE_COLUMNS,
    FINANCIAL_TEMPLATE_COLUMNS,
)
from src.ingestion.source_rate_limit import SourceRequestTracker


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT_DIR / "scripts" / "run_first_20_real_data_dry_run.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("real_data_dry_run_script_01d", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_dataset_specific_budgets_prevent_finance_disclosure_starvation():
    tracker = SourceRequestTracker(
        max_requests=None,
        dataset_budgets={
            "market_price": 1,
            "financial_statement_summary": 2,
            "disclosure_status": 1,
        },
    )

    tracker.request(source_name="s", dataset_name="market_price", action=lambda: "ok")
    _, market_error = tracker.request(source_name="s", dataset_name="market_price", action=lambda: "skip")
    finance_result, finance_error = tracker.request(
        source_name="s",
        dataset_name="financial_statement_summary",
        action=lambda: "finance_ok",
    )
    disclosure_result, disclosure_error = tracker.request(
        source_name="s",
        dataset_name="disclosure_status",
        action=lambda: "disclosure_ok",
    )
    summary = tracker.to_frame()

    assert market_error == "DATASET_REQUEST_BUDGET_EXHAUSTED:market_price"
    assert finance_result == "finance_ok"
    assert finance_error == ""
    assert disclosure_result == "disclosure_ok"
    assert disclosure_error == ""
    finance_row = summary[summary["dataset_name"] == "financial_statement_summary"].iloc[0]
    assert finance_row["dataset_request_budget"] == 2
    assert finance_row["requests_attempted"] == 1


def test_only_finance_disclosure_retry_does_not_refetch_earlier_datasets(monkeypatch, tmp_path):
    module = _load_script_module()
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "exchange": "HOSE",
                "company_name": "AAA Company",
                "listing_status": "LISTED",
                "data_source": "prior_real_run",
                "last_updated": "2026-06-04",
                "source": "prior",
                "source_url": "manual://prior",
                "fetch_time": "2026-06-04T00:00:00Z",
                "confidence_raw": "medium",
                "notes": "prior context row",
            }
        ]
    ).to_csv(raw_dir / "universe_raw.csv", index=False)

    class ForbiddenListing:
        def __init__(self, *args, **kwargs):
            raise AssertionError("universe should not be refetched")

    class ForbiddenQuote:
        def __init__(self, *args, **kwargs):
            raise AssertionError("market should not be refetched")

    class FakeCompany:
        def __init__(self, source, symbol):
            self.symbol = symbol

        def events(self):
            return pd.DataFrame()

    class FakeFinance:
        def __init__(self, source, symbol, period, get_all):
            self.symbol = symbol

        def income_statement(self):
            return pd.DataFrame([{"item_id": "revenue", "2026-Q1": 100}])

        def balance_sheet(self):
            return pd.DataFrame(
                [
                    {"item_id": "total_assets", "2026-Q1": 1000},
                    {"item_id": "liabilities", "2026-Q1": 400},
                    {"item_id": "owners_equity", "2026-Q1": 600},
                ]
            )

        def cash_flow(self):
            return pd.DataFrame(
                [
                    {
                        "item_id": "net_cash_inflows_outflows_from_operating_activities",
                        "2026-Q1": 50,
                    }
                ]
            )

    fake_vnstock = types.SimpleNamespace(
        Company=FakeCompany,
        Finance=FakeFinance,
        Listing=ForbiddenListing,
        Quote=ForbiddenQuote,
    )
    monkeypatch.setitem(sys.modules, "vnstock", fake_vnstock)

    _, status = module.fetch_real_vnstock_data(
        limit=1,
        started_at="2026-06-04T00:00:00Z",
        start_date=None,
        end_date=None,
        request_pause_seconds=0,
        real_source_max_requests=None,
        ticker_selection="manual_list",
        representative_config="config/real_data_first_20_representative_tickers.yaml",
        ticker_list="AAA",
        input_tickers=None,
        input_financials=None,
        input_disclosure=None,
        market_lookback_days=90,
        market_max_retries=0,
        finance_max_retries=0,
        disclosure_max_retries=0,
        only_datasets={"financial_statement_summary", "disclosure_status"},
        raw_output_dir=raw_dir,
        dataset_budgets={
            "financial_statement_summary": 10,
            "disclosure_status": 10,
        },
    )

    request_summary = status["source_request_summary"]
    assert "universe" not in set(request_summary["dataset_name"])
    assert "market_price" not in set(request_summary["dataset_name"])
    assert {"financial_statement_summary", "disclosure_status"}.issubset(
        set(request_summary["dataset_name"])
    )
    assert status["dataset_status"]["universe"] == "SKIPPED_BY_ONLY_DATASETS"
    assert status["dataset_status"]["market_price"] == "SKIPPED_BY_ONLY_DATASETS"


def test_finance_mapper_preserves_missing_fields_instead_of_zero_fill():
    record, warnings, missing, not_applicable = map_financial_statement_summary(
        ticker="AAA",
        statements={"income": pd.DataFrame([{"item_id": "revenue", "2026-Q1": 100}])},
        fetch_time="2026-06-04T00:00:00Z",
        is_bank=False,
    )

    assert record is not None
    assert record["revenue"] == 100
    assert pd.isna(record["net_profit"])
    assert "net_profit" in missing
    assert "FINANCIAL_PARTIAL_ROW" in warnings
    assert not_applicable == []


def test_bank_partial_schema_does_not_fake_inventory_or_revenue():
    record, warnings, missing, not_applicable = map_financial_statement_summary(
        ticker="VCB",
        statements={
            "balance": pd.DataFrame(
                [
                    {"item_id": "total_assets", "2026-Q1": 1000},
                    {"item_id": "loans_to_customers", "2026-Q1": 500},
                ]
            )
        },
        fetch_time="2026-06-04T00:00:00Z",
        is_bank=True,
    )

    assert record is not None
    assert pd.isna(record["revenue"])
    assert pd.isna(record["inventory"])
    assert "inventory" in not_applicable
    assert "BANK_FINANCIAL_SCHEMA_PARTIAL" in warnings
    assert "revenue" in missing


def test_unknown_financial_schema_creates_warning():
    record, warnings, missing, _ = map_financial_statement_summary(
        ticker="AAA",
        statements={"income": pd.DataFrame([{"unknown": "x"}])},
        fetch_time="2026-06-04T00:00:00Z",
    )

    assert record is None
    assert "FINANCIAL_SOURCE_EMPTY_RESPONSE" in warnings
    assert missing == []


def test_disclosure_empty_response_is_not_treated_as_clean():
    coverage = build_disclosure_coverage_status(
        tickers=["AAA"],
        disclosure_df=pd.DataFrame(),
        failed_rows=[
            {
                "ticker": "AAA",
                "dataset_name": "disclosure_status",
                "status": "DISCLOSURE_SOURCE_EMPTY_RESPONSE",
                "reason": "no rows returned",
            }
        ],
        source_request_summary=pd.DataFrame(
            [
                {
                    "source_name": "s",
                    "dataset_name": "disclosure_status",
                    "requests_attempted": 1,
                    "requests_succeeded": 1,
                    "requests_failed": 0,
                    "requests_skipped_due_to_budget": 0,
                }
            ]
        ),
    )

    row = coverage.iloc[0]
    assert bool(row["treated_as_clean"]) is False
    assert row["status"] == "DISCLOSURE_SOURCE_EMPTY_RESPONSE"
    assert "DISCLOSURE_DATA_UNAVAILABLE" in row["warning_flags"]


def test_finance_and_disclosure_template_columns_match_contract():
    contracts = load_ingestion_contracts()
    financial_required = contracts["datasets"]["financial_statement_summary"]["required_columns"]
    disclosure_required = contracts["datasets"]["disclosure_status"]["required_columns"]

    assert set(financial_required).issubset(FINANCIAL_TEMPLATE_COLUMNS)
    assert set(disclosure_required).issubset(DISCLOSURE_TEMPLATE_COLUMNS)


def test_manual_vs_real_conflict_creates_warning():
    module = _load_script_module()
    real = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "period": "2026-Q1",
                "period_type": "quarter",
                "revenue": 100,
                "source": "real",
                "source_url": "real://source",
                "fetch_time": "2026-06-04T00:00:00Z",
                "confidence_raw": "medium",
                "notes": "real row",
            }
        ]
    )
    manual = real.copy()
    manual.loc[0, "revenue"] = 200
    manual.loc[0, "source"] = "manual"

    _, conflicts = module.merge_manual_with_real(
        dataset_name="financial_statement_summary",
        real_df=real,
        manual_df=manual,
        key_columns=["ticker", "period"],
    )

    assert conflicts
    assert conflicts[0]["status"] == "DATA_CONFLICT_MANUAL_VS_REAL"
    assert "revenue" in conflicts[0]["reason"]


def test_new_coverage_reports_have_no_recommendation_or_target_price_fields():
    finance = build_finance_field_coverage(pd.DataFrame(), tickers=["AAA"])
    disclosure = build_disclosure_coverage_status(
        tickers=["AAA"],
        disclosure_df=pd.DataFrame(),
        failed_rows=[],
        source_request_summary=pd.DataFrame(),
    )
    for frame in [finance, disclosure]:
        normalized = {column.strip().lower() for column in frame.columns}
        assert PROHIBITED_RECOMMENDATION_FIELDS.isdisjoint(normalized)


def test_step19_is_not_implemented_for_01d():
    text = SCRIPT_PATH.read_text(encoding="utf-8").lower()

    assert "step19_implemented" in text
    assert "target_price" not in text
