import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

from src.ingestion.contracts import PROHIBITED_RECOMMENDATION_FIELDS
from src.ingestion.multi_source_evidence import (
    load_multi_source_registry,
    load_source_priority_config,
    run_multi_source_evidence,
    save_multi_source_evidence_reports,
    validate_multi_source_registry,
    validate_source_priority_config,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPT = ROOT_DIR / "scripts" / "run_multi_source_evidence.py"


def _complete_finance_rows():
    return pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "period": "2026-Q1",
                "period_type": "quarter",
                "revenue": 100,
                "net_profit": 10,
                "total_assets": 1000,
                "total_liabilities": 400,
                "equity": 600,
                "source": "vnstock:vci:finance",
                "source_url": "https://vnstocks.com/",
                "fetch_time": "2026-06-05T00:00:00Z",
                "confidence_raw": "medium",
                "notes": "source values only",
            }
        ]
    )


def test_multi_source_registry_and_priority_config_are_valid():
    registry = load_multi_source_registry()
    priority = load_source_priority_config()

    registry_result = validate_multi_source_registry(registry)
    priority_result = validate_source_priority_config(priority)

    assert registry_result["is_valid"] is True
    assert priority_result["is_valid"] is True
    assert {
        "vnstock",
        "cafef",
        "vietstock",
        "hose",
        "hnx",
        "ssc",
        "manual_csv",
        "manual_xlsx",
        "annual_report_pdf_manual",
    }.issubset(set(registry["supported_source_categories"]))


def test_missing_financial_values_remain_unresolved_not_fabricated():
    finance = _complete_finance_rows()
    finance["net_profit"] = finance["net_profit"].astype(object)
    finance.loc[0, "net_profit"] = ""

    result = run_multi_source_evidence(
        raw_datasets={"financial_statement_summary": finance, "disclosure_status": pd.DataFrame()},
        requested_tickers=["AAA"],
        run_id="test_missing_finance",
    )

    unresolved = result["unresolved_required_fields"]
    finance_unresolved = unresolved[
        unresolved["dataset_name"] == "financial_statement_summary"
    ]

    assert "net_profit" in set(finance_unresolved["field_name"])
    assert set(finance_unresolved["issue"]).issuperset({"MISSING_REQUIRED_FIELD"})
    assert result["decisions"]["finance_ready_for_l0"] is False
    assert "0" not in set(result["field_level_evidence"]["value"].astype(str))


def test_conflicting_source_values_create_manual_review_without_overwrite():
    finance = pd.concat(
        [
            _complete_finance_rows(),
            _complete_finance_rows().assign(
                revenue=120,
                source="manual_csv",
                source_category="manual_csv",
                source_url="manual://finance/AAA",
            ),
        ],
        ignore_index=True,
    )

    result = run_multi_source_evidence(
        raw_datasets={"financial_statement_summary": finance, "disclosure_status": pd.DataFrame()},
        requested_tickers=["AAA"],
        run_id="test_conflict",
    )

    conflicts = result["source_conflict_report"]
    revenue_conflict = conflicts[
        (conflicts["dataset_name"] == "financial_statement_summary")
        & (conflicts["field_name"] == "revenue")
    ]

    assert not revenue_conflict.empty
    assert revenue_conflict.iloc[0]["conflict_status"] == "DATA_CONFLICT_MANUAL_REVIEW"
    assert bool(revenue_conflict.iloc[0]["manual_review_required"]) is True
    unresolved = result["unresolved_required_fields"]
    assert "DATA_CONFLICT" in set(unresolved["issue"])


def test_matching_values_reconcile_by_priority_without_conflict():
    finance = pd.concat(
        [
            _complete_finance_rows(),
            _complete_finance_rows().assign(
                source="manual_csv",
                source_category="manual_csv",
                source_url="manual://finance/AAA",
            ),
        ],
        ignore_index=True,
    )

    result = run_multi_source_evidence(
        raw_datasets={"financial_statement_summary": finance, "disclosure_status": pd.DataFrame()},
        requested_tickers=["AAA"],
        run_id="test_agreement",
    )

    revenue = result["reconciled_fields"][
        (result["reconciled_fields"]["dataset_name"] == "financial_statement_summary")
        & (result["reconciled_fields"]["field_name"] == "revenue")
    ].iloc[0]

    assert result["source_conflict_report"].empty
    assert revenue["reconciliation_status"] == "RESOLVED_BY_MULTISOURCE_AGREEMENT"
    assert revenue["resolved_source_category"] == "manual_csv"
    assert revenue["confidence"] == "high"


def test_disclosure_zero_rows_are_unavailable_not_clean():
    result = run_multi_source_evidence(
        raw_datasets={
            "financial_statement_summary": _complete_finance_rows(),
            "disclosure_status": pd.DataFrame(
                columns=[
                    "ticker",
                    "event_date",
                    "event_type",
                    "severity",
                    "source",
                    "source_url",
                    "fetch_time",
                    "confidence_raw",
                ]
            ),
        },
        requested_tickers=["AAA"],
        run_id="test_disclosure_missing",
    )

    unresolved = result["unresolved_required_fields"]
    disclosure = unresolved[unresolved["dataset_name"] == "disclosure_status"]

    assert "DISCLOSURE_DATA_UNAVAILABLE" in set(disclosure["issue"])
    assert result["decisions"]["disclosure_ready_for_l0"] is False
    assert result["decisions"]["finance_disclosure_ready_for_future_step19"] is False
    assert "not clean" in disclosure.iloc[0]["notes"]


def test_required_reports_are_written_and_have_no_prohibited_columns(tmp_path):
    result = run_multi_source_evidence(
        raw_datasets={
            "financial_statement_summary": _complete_finance_rows(),
            "disclosure_status": pd.DataFrame(),
        },
        requested_tickers=["AAA"],
        run_id="test_save_reports",
    )

    paths = save_multi_source_evidence_reports(result=result, output_dir=tmp_path)

    for filename in [
        "source_availability_matrix.csv",
        "field_level_evidence.csv",
        "source_conflict_report.csv",
        "unresolved_required_fields.csv",
        "multi_source_run_summary.md",
        "datasource_decision_report.md",
    ]:
        assert (tmp_path / filename).exists()

    for key in [
        "source_availability_matrix",
        "field_level_evidence",
        "source_conflict_report",
        "unresolved_required_fields",
    ]:
        frame = pd.read_csv(paths[key])
        normalized = {column.strip().lower() for column in frame.columns}
        assert PROHIBITED_RECOMMENDATION_FIELDS.isdisjoint(normalized)


def test_cli_writes_multi_source_reports_from_local_raw_files(tmp_path):
    raw_dir = tmp_path / "raw"
    report_dir = tmp_path / "reports"
    raw_dir.mkdir()
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "exchange": "HOSE",
                "company_name": "AAA",
                "listing_status": "LISTED",
                "source": "manual_csv",
                "source_category": "manual_csv",
                "source_url": "manual://universe/AAA",
                "fetch_time": "2026-06-05T00:00:00Z",
                "confidence_raw": "medium",
            }
        ]
    ).to_csv(raw_dir / "universe_raw.csv", index=False)
    _complete_finance_rows().to_csv(
        raw_dir / "financial_statement_summary_raw.csv", index=False
    )
    pd.DataFrame(
        columns=[
            "ticker",
            "event_date",
            "event_type",
            "severity",
            "source",
            "source_url",
            "fetch_time",
            "confidence_raw",
        ]
    ).to_csv(raw_dir / "disclosure_status_raw.csv", index=False)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--raw-dir",
            str(raw_dir),
            "--output-dir",
            str(report_dir),
            "--ticker-list",
            "AAA",
            "--allow-partial",
        ],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    assert (report_dir / "source_availability_matrix.csv").exists()
    assert (report_dir / "datasource_decision_report.md").exists()
    decision = (report_dir / "datasource_decision_report.md").read_text(encoding="utf-8")
    assert "step19_implemented: False" in decision
