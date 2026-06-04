import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

from src.ingestion.contracts import PROHIBITED_RECOMMENDATION_FIELDS
from src.ingestion.real_source_adapters import (
    create_manual_templates,
    build_source_adapter_status,
)
from src.ingestion.source_rate_limit import SourceRequestTracker


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT_DIR / "scripts" / "run_first_20_real_data_dry_run.py"
REPRESENTATIVE_CONFIG = ROOT_DIR / "config" / "real_data_first_20_representative_tickers.yaml"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("real_data_dry_run_script", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run_cli(args):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *[str(arg) for arg in args]],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
        check=False,
    )


def test_representative_ticker_config_loads_as_engineering_only():
    module = _load_script_module()

    config = module.load_representative_ticker_config(REPRESENTATIVE_CONFIG)

    assert len(config["tickers"]) == 20
    assert config["tickers"][:5] == ["VCB", "BID", "CTG", "MBB", "ACB"]
    assert "engineering" in config["purpose"]
    assert "advice" in config["purpose"]


def test_representative_selection_uses_real_universe_members_only():
    module = _load_script_module()
    listing = pd.DataFrame(
        [
            {"symbol": "VCB", "exchange": "HOSE", "organ_name": "Bank A", "type": "stock"},
            {"symbol": "HPG", "exchange": "HOSE", "organ_name": "Steel A", "type": "stock"},
            {"symbol": "FPT", "exchange": "HOSE", "organ_name": "Tech A", "type": "stock"},
        ]
    )

    selected, warnings = module.select_listing_universe(
        listing,
        limit=20,
        fetch_time="2026-06-04T00:00:00Z",
        ticker_selection="representative",
        representative_config=REPRESENTATIVE_CONFIG,
        ticker_list=None,
        input_tickers=None,
    )

    assert selected["ticker"].tolist() == ["VCB", "HPG", "FPT"]
    assert any("REQUESTED_TICKERS_NOT_IN_REAL_UNIVERSE" in warning for warning in warnings)
    assert set(selected["data_source"]) == {"vnstock:kbs:symbols_by_exchange"}


def test_request_budget_accounting_records_skipped_requests():
    tracker = SourceRequestTracker(max_requests=1)

    result, error = tracker.request(
        source_name="source",
        dataset_name="market_price",
        action=lambda: "ok",
        pause_seconds=0,
    )
    skipped_result, skipped_error = tracker.request(
        source_name="source",
        dataset_name="market_price",
        action=lambda: "should_not_run",
        pause_seconds=0,
    )

    frame = tracker.to_frame().iloc[0]
    assert result == "ok"
    assert error == ""
    assert skipped_result is None
    assert skipped_error == "REAL_SOURCE_REQUEST_BUDGET_EXHAUSTED"
    assert frame["requests_attempted"] == 1
    assert frame["requests_succeeded"] == 1
    assert frame["requests_skipped_due_to_budget"] == 1


def test_rate_limit_error_is_captured_without_crashing():
    tracker = SourceRequestTracker(max_requests=3)

    result, error = tracker.request(
        source_name="vnstock:vci",
        dataset_name="market_price",
        action=lambda: (_ for _ in ()).throw(RuntimeError("Rate Limit Exceeded")),
        pause_seconds=0,
    )

    frame = tracker.to_frame().iloc[0]
    assert result is None
    assert "Rate Limit Exceeded" in error
    assert frame["requests_failed"] == 1
    assert frame["rate_limit_errors"] == 1


def test_missing_profile_fields_create_partial_profile_warnings():
    module = _load_script_module()

    class FakeCompany:
        def __init__(self, source, symbol):
            self.source = source
            self.symbol = symbol

        def overview(self):
            return pd.DataFrame([{"organ_name": "Profile Only Company"}])

    universe = pd.DataFrame(
        [
            {
                "ticker": "VCB",
                "exchange": "HOSE",
                "company_name": "Profile Only Company",
            }
        ]
    )
    rows, failed = module.fetch_company_profiles(
        Company=FakeCompany,
        universe_df=universe,
        started_at="2026-06-04T00:00:00Z",
        request_pause_seconds=0,
        request_tracker=SourceRequestTracker(max_requests=4),
    )

    assert rows[0]["confidence_raw"] == "low"
    assert failed[0]["status"] == "PARTIAL_PROFILE_DATA"
    assert "MISSING_INDUSTRY_RAW" in failed[0]["reason"]
    assert "MISSING_BUSINESS_DESCRIPTION" in failed[0]["reason"]


def test_missing_financial_source_creates_template_and_unavailable_status(tmp_path):
    module = _load_script_module()

    class FakeFinance:
        def __init__(self, source, symbol, period, get_all):
            pass

        def income_statement(self):
            return pd.DataFrame()

        def balance_sheet(self):
            return pd.DataFrame()

        def cash_flow(self):
            return pd.DataFrame()

    template_paths = create_manual_templates(
        financial_template_path=tmp_path / "financial_template.csv",
        disclosure_template_path=tmp_path / "disclosure_template.csv",
    )
    rows, failed = module.fetch_financial_summaries(
        Finance=FakeFinance,
        tickers=["VCB"],
        started_at="2026-06-04T00:00:00Z",
        request_pause_seconds=0,
        request_tracker=SourceRequestTracker(max_requests=10),
    )

    assert rows == []
    assert failed[0]["status"] == "FINANCIAL_STATEMENT_DATA_UNAVAILABLE"
    assert Path(template_paths["financial_statement_summary"]).exists()
    assert pd.read_csv(template_paths["financial_statement_summary"]).empty


def test_missing_disclosure_source_creates_template_and_is_not_clean(tmp_path):
    module = _load_script_module()

    class FakeCompany:
        def __init__(self, source, symbol):
            pass

        def events(self):
            return pd.DataFrame()

    template_paths = create_manual_templates(
        financial_template_path=tmp_path / "financial_template.csv",
        disclosure_template_path=tmp_path / "disclosure_template.csv",
    )
    rows, failed = module.fetch_disclosures(
        Company=FakeCompany,
        tickers=["VCB"],
        started_at="2026-06-04T00:00:00Z",
        request_pause_seconds=0,
        request_tracker=SourceRequestTracker(max_requests=3),
    )

    assert rows == []
    assert failed[0]["status"] == "DISCLOSURE_DATA_UNAVAILABLE"
    assert "unknown, not clean" in failed[0]["reason"]
    assert Path(template_paths["disclosure_status"]).exists()


def test_failure_path_writes_source_reports_and_templates(tmp_path):
    reports_dir = tmp_path / "reports"
    raw_dir = tmp_path / "raw"
    result = _run_cli(
        [
            "--mode",
            "real",
            "--dry-source-unavailable",
            "--output-dir",
            reports_dir,
            "--raw-output-dir",
            raw_dir,
            "--financial-template-output",
            tmp_path / "financial_template.csv",
            "--disclosure-template-output",
            tmp_path / "disclosure_template.csv",
        ]
    )

    assert result.returncode == 0
    assert (reports_dir / "source_request_summary.csv").exists()
    assert (reports_dir / "source_adapter_status.csv").exists()
    assert (tmp_path / "financial_template.csv").exists()
    assert (tmp_path / "disclosure_template.csv").exists()


def test_source_reports_have_no_recommendation_or_target_price_fields():
    adapter_status = build_source_adapter_status(
        vnstock_available=True,
        vnstock_ezchart_available=True,
    )
    tracker = SourceRequestTracker(max_requests=1)
    tracker.request(
        source_name="source",
        dataset_name="universe",
        action=lambda: "ok",
        pause_seconds=0,
    )
    for frame in [adapter_status, tracker.to_frame()]:
        normalized = {column.strip().lower() for column in frame.columns}
        assert PROHIBITED_RECOMMENDATION_FIELDS.isdisjoint(normalized)


def test_step19_is_not_implemented_in_real_data_01b_script():
    script_text = SCRIPT_PATH.read_text(encoding="utf-8").lower()

    assert "step19_implemented" in script_text
    assert "target_price" not in script_text
