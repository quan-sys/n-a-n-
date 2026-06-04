import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

from src.ingestion.contracts import PROHIBITED_RECOMMENDATION_FIELDS


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPT = ROOT_DIR / "scripts" / "run_first_20_real_data_dry_run.py"


def _run_cli(args, *, check=True):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *[str(arg) for arg in args]],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"Command failed with {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, keep_default_na=False)


def _valid_manual_universe(path: Path) -> None:
    pd.DataFrame(
        [
            {
                "ticker": "SAMPLE1",
                "exchange": "HOSE",
                "company_name": "Sample Manual Company",
                "listing_status": "LISTED",
                "data_source": "manual_test",
                "last_updated": "2026-06-03",
                "source": "manual_test",
                "source_url": "manual://universe/SAMPLE1",
                "fetch_time": "2026-06-03T00:00:00Z",
                "confidence_raw": "manual",
                "notes": "manual test universe row; not real-source data",
            }
        ]
    ).to_csv(path, index=False)


def test_real_mode_dry_source_unavailable_writes_honest_failure_reports(tmp_path):
    reports_dir = tmp_path / "reports"
    raw_dir = tmp_path / "raw"

    _run_cli(
        [
            "--mode",
            "real",
            "--limit",
            "20",
            "--dry-source-unavailable",
            "--output-dir",
            reports_dir,
            "--raw-output-dir",
            raw_dir,
        ]
    )

    summary = (reports_dir / "run_summary.md").read_text(encoding="utf-8")
    assert "REAL_SOURCE_UNAVAILABLE" in summary
    assert "- tickers_requested: 20" in summary
    assert "- tickers_ingested: 0" in summary
    assert "- output_contains_mock_sample: False" in summary
    assert "- step19_implemented: False" in summary
    assert not (raw_dir / "universe_raw.csv").exists()
    assert (reports_dir / "pipeline_errors.csv").exists()
    assert (reports_dir / "failed_tickers.csv").exists()


def test_manual_universe_missing_required_columns_fails_validation(tmp_path):
    reports_dir = tmp_path / "reports"
    raw_dir = tmp_path / "raw"
    bad_universe = tmp_path / "bad_universe.csv"
    pd.DataFrame(
        [
            {
                "ticker": "SAMPLE1",
                "company_name": "Sample Manual Company",
                "listing_status": "LISTED",
                "data_source": "manual_test",
                "last_updated": "2026-06-03",
            }
        ]
    ).to_csv(bad_universe, index=False)

    _run_cli(
        [
            "--mode",
            "manual_csv",
            "--limit",
            "20",
            "--input-universe",
            bad_universe,
            "--output-dir",
            reports_dir,
            "--raw-output-dir",
            raw_dir,
        ]
    )

    failed = _read_csv(reports_dir / "failed_tickers.csv")
    assert not failed.empty
    assert set(failed["dataset_name"]) == {"universe"}
    assert set(failed["status"]) == {"FAILED"}
    assert "exchange" in failed.iloc[0]["reason"]
    assert "FAILED" in (reports_dir / "run_summary.md").read_text(encoding="utf-8")


def test_manual_universe_only_reports_missing_bctc_and_disclosure_as_not_clean(tmp_path):
    reports_dir = tmp_path / "reports"
    raw_dir = tmp_path / "raw"
    universe = tmp_path / "universe.csv"
    _valid_manual_universe(universe)

    _run_cli(
        [
            "--mode",
            "manual_csv",
            "--limit",
            "1",
            "--input-universe",
            universe,
            "--output-dir",
            reports_dir,
            "--raw-output-dir",
            raw_dir,
            "--allow-partial",
        ]
    )

    failed = _read_csv(reports_dir / "failed_tickers.csv")
    failed_pairs = set(zip(failed["dataset_name"], failed["status"]))
    assert ("financial_statement_summary", "MANUAL_FILE_NOT_PROVIDED") in failed_pairs
    assert ("disclosure_status", "MANUAL_FILE_NOT_PROVIDED") in failed_pairs

    manual_review = _read_csv(reports_dir / "manual_review_queue.csv")
    disclosure_review = manual_review[
        manual_review["module"].astype(str) == "disclosure_status"
    ]
    assert not disclosure_review.empty
    assert set(disclosure_review["issue"]) == {"DISCLOSURE_DATA_UNAVAILABLE"}
    assert set(disclosure_review["confidence"]) == {"low"}

    coverage = _read_csv(reports_dir / "data_coverage_report.csv")
    disclosure_coverage = coverage[
        coverage["dataset_name"] == "disclosure_status"
    ].iloc[0]
    assert disclosure_coverage["coverage_status"] != "VALID_DATA"
    assert (raw_dir / "universe_raw.csv").exists()
    assert (raw_dir / "financial_statement_summary_raw.csv").exists()


def test_real_data_01_outputs_have_no_recommendation_or_target_price_fields(tmp_path):
    reports_dir = tmp_path / "reports"
    raw_dir = tmp_path / "raw"
    universe = tmp_path / "universe.csv"
    _valid_manual_universe(universe)

    _run_cli(
        [
            "--mode",
            "manual_csv",
            "--limit",
            "1",
            "--input-universe",
            universe,
            "--output-dir",
            reports_dir,
            "--raw-output-dir",
            raw_dir,
        ]
    )

    for csv_path in list(reports_dir.glob("*.csv")) + list(raw_dir.glob("*.csv")):
        frame = _read_csv(csv_path)
        normalized_columns = {column.strip().lower() for column in frame.columns}
        assert PROHIBITED_RECOMMENDATION_FIELDS.isdisjoint(normalized_columns), csv_path


def test_mock_mode_cannot_be_mislabeled_as_real(tmp_path):
    result = _run_cli(
        [
            "--mode",
            "mock",
            "--output-dir",
            tmp_path / "reports",
            "--raw-output-dir",
            tmp_path / "raw",
        ],
        check=False,
    )

    assert result.returncode != 0
    assert "invalid choice" in result.stderr
