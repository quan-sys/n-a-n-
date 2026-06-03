import json
from pathlib import Path

import pandas as pd
import pytest

from src.ingestion.universe_profile_ingestion import (
    COMPANY_PROFILE_RAW_FILENAME,
    REAL_SOURCE_UNAVAILABLE,
    UNIVERSE_RAW_FILENAME,
    has_prohibited_recommendation_columns,
    ingest_universe_and_company_profiles,
)


FETCH_TIME = "2026-01-01T00:00:00Z"


def _universe_rows(*, duplicate: bool = False):
    rows = [
        {
            "ticker": "MOCK1",
            "exchange": "HOSE",
            "company_name": "Mock Company One",
            "listing_status": "LISTED",
            "data_source": "manual_sample",
            "last_updated": "2026-01-01",
        },
        {
            "ticker": "MOCK2",
            "exchange": "HNX",
            "company_name": "Mock Company Two",
            "listing_status": "LISTED",
            "data_source": "manual_sample",
            "last_updated": "2026-01-01",
        },
    ]
    if duplicate:
        rows.append(
            {
                "ticker": "MOCK1",
                "exchange": "HOSE",
                "company_name": "Mock Company One Duplicate",
                "listing_status": "LISTED",
                "data_source": "manual_sample",
                "last_updated": "2026-01-01",
            }
        )
    return rows


def _profile_rows(*, missing_mock2: bool = False):
    rows = [
        {
            "ticker": "MOCK1",
            "company_name": "Mock Company One",
            "exchange": "HOSE",
            "industry_raw": "Mock Industry",
            "business_description": "Mock profile only; not real company data",
            "source": "manual_sample",
            "source_url": "mock://company_profile/MOCK1",
            "last_updated": "2026-01-01",
        }
    ]
    if not missing_mock2:
        rows.append(
            {
                "ticker": "MOCK2",
                "company_name": "Mock Company Two",
                "exchange": "HNX",
                "industry_raw": "Mock Industry",
                "business_description": "Mock profile only; not real company data",
                "source": "manual_sample",
                "source_url": "mock://company_profile/MOCK2",
                "last_updated": "2026-01-01",
            }
        )
    return rows


def _write_csv_inputs(tmp_path, universe_rows=None, profile_rows=None):
    universe_path = tmp_path / "universe.csv"
    profile_path = tmp_path / "profiles.csv"
    pd.DataFrame(universe_rows or _universe_rows()).to_csv(universe_path, index=False)
    pd.DataFrame(profile_rows or _profile_rows()).to_csv(profile_path, index=False)
    return universe_path, profile_path


def _run_ingestion(tmp_path, mode, universe_path=None, profile_path=None, run_id="run_mock"):
    return ingest_universe_and_company_profiles(
        mode=mode,
        universe_input_path=universe_path,
        company_profile_input_path=profile_path,
        raw_output_dir=tmp_path / "raw",
        manifest_dir=tmp_path / "manifests",
        coverage_output_dir=tmp_path / "coverage",
        run_id=run_id,
        fetch_time=FETCH_TIME,
    )


def test_manual_csv_ingestion_writes_raw_outputs_and_coverage(tmp_path):
    universe_path, profile_path = _write_csv_inputs(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        universe_path=universe_path,
        profile_path=profile_path,
    )

    assert result["status"] == "SUCCESS"
    assert Path(result["raw_output_paths"]["universe"]).name == UNIVERSE_RAW_FILENAME
    assert (
        Path(result["raw_output_paths"]["company_profile"]).name
        == COMPANY_PROFILE_RAW_FILENAME
    )
    assert Path(result["coverage_summary_path"]).exists()
    assert result["coverage"]["universe"]["row_count"] == 2
    assert result["coverage"]["combined"]["missing_profile_count"] == 0


def test_manual_csv_output_preserves_metadata_defaults(tmp_path):
    universe_path, profile_path = _write_csv_inputs(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        universe_path=universe_path,
        profile_path=profile_path,
    )
    universe_raw = pd.read_csv(result["raw_output_paths"]["universe"])
    profile_raw = pd.read_csv(result["raw_output_paths"]["company_profile"])

    assert set(universe_raw["confidence_raw"]) == {"medium"}
    assert set(profile_raw["fetch_time"]) == {FETCH_TIME}
    assert set(profile_raw["source_url"]) == {
        "mock://company_profile/MOCK1",
        "mock://company_profile/MOCK2",
    }


def test_manual_xlsx_ingestion_works_when_dependency_available(tmp_path):
    pytest.importorskip("openpyxl")
    universe_path = tmp_path / "universe.xlsx"
    profile_path = tmp_path / "profiles.xlsx"
    pd.DataFrame(_universe_rows()).to_excel(universe_path, index=False)
    pd.DataFrame(_profile_rows()).to_excel(profile_path, index=False)

    result = _run_ingestion(
        tmp_path,
        "manual_xlsx",
        universe_path=universe_path,
        profile_path=profile_path,
    )

    assert result["status"] == "SUCCESS"
    assert Path(result["raw_output_paths"]["universe"]).exists()
    assert Path(result["raw_output_paths"]["company_profile"]).exists()


def test_missing_required_columns_fail_validation_and_skip_raw_output(tmp_path):
    bad_universe = _universe_rows()
    for row in bad_universe:
        row.pop("exchange")
    universe_path, profile_path = _write_csv_inputs(
        tmp_path, universe_rows=bad_universe
    )

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        universe_path=universe_path,
        profile_path=profile_path,
    )

    assert result["status"] == "DATA_ERROR"
    assert result["raw_output_paths"] == {}
    assert result["validation_results"]["universe"]["missing_required_columns"] == [
        "exchange"
    ]
    assert Path(result["manifest_paths"]["universe"]).exists()


def test_company_profile_source_url_is_required(tmp_path):
    bad_profiles = _profile_rows()
    for row in bad_profiles:
        row.pop("source_url")
    universe_path, profile_path = _write_csv_inputs(
        tmp_path, profile_rows=bad_profiles
    )

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        universe_path=universe_path,
        profile_path=profile_path,
    )

    assert result["status"] == "DATA_ERROR"
    assert "source_url" in result["validation_results"]["company_profile"][
        "missing_required_columns"
    ]


def test_duplicate_ticker_is_flagged(tmp_path):
    universe_path, profile_path = _write_csv_inputs(
        tmp_path, universe_rows=_universe_rows(duplicate=True)
    )

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        universe_path=universe_path,
        profile_path=profile_path,
    )

    assert result["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["coverage"]["universe"]["duplicate_ticker_count"] == 1
    assert "DUPLICATE_TICKER" in result["coverage"]["universe"]["warnings"]


def test_missing_profile_is_flagged_without_fabricating_profile_data(tmp_path):
    universe_path, profile_path = _write_csv_inputs(
        tmp_path, profile_rows=_profile_rows(missing_mock2=True)
    )

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        universe_path=universe_path,
        profile_path=profile_path,
    )
    profile_raw = pd.read_csv(result["raw_output_paths"]["company_profile"])

    assert result["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["coverage"]["combined"]["missing_profile_count"] == 1
    assert result["coverage"]["combined"]["missing_profile_tickers"] == ["MOCK2"]
    assert set(profile_raw["ticker"]) == {"MOCK1"}


def test_unknown_exchange_is_warning_not_guessed(tmp_path):
    universe_rows = _universe_rows()
    universe_rows[0]["exchange"] = "UNKNOWN_EXCHANGE"
    universe_path, profile_path = _write_csv_inputs(
        tmp_path, universe_rows=universe_rows
    )

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        universe_path=universe_path,
        profile_path=profile_path,
    )
    universe_raw = pd.read_csv(result["raw_output_paths"]["universe"])

    assert result["status"] == "SUCCESS_WITH_WARNINGS"
    assert "UNKNOWN_EXCHANGE: UNKNOWN_EXCHANGE" in result["coverage"]["universe"][
        "warnings"
    ]
    assert "UNKNOWN_EXCHANGE" in set(universe_raw["exchange"])


def test_mock_mode_labels_data_as_mock_sample(tmp_path):
    result = _run_ingestion(tmp_path, "mock")
    universe_raw = pd.read_csv(result["raw_output_paths"]["universe"])
    profile_raw = pd.read_csv(result["raw_output_paths"]["company_profile"])

    assert result["status"] == "SUCCESS"
    assert set(universe_raw["confidence_raw"]) == {"mock"}
    assert set(profile_raw["confidence_raw"]) == {"mock"}
    assert universe_raw["notes"].str.contains("mock/sample").all()
    assert profile_raw["notes"].str.contains("mock/sample").all()


def test_real_unavailable_returns_status_and_manifest(tmp_path):
    result = _run_ingestion(tmp_path, "real_vnstock_optional")

    assert result["status"] == REAL_SOURCE_UNAVAILABLE
    assert result["errors"] == [REAL_SOURCE_UNAVAILABLE]
    assert result["raw_output_paths"] == {}
    assert Path(result["manifest_paths"]["universe"]).exists()
    assert Path(result["manifest_paths"]["company_profile"]).exists()


def test_manifest_is_written_for_successful_ingestion(tmp_path):
    universe_path, profile_path = _write_csv_inputs(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        universe_path=universe_path,
        profile_path=profile_path,
        run_id="run_manifest",
    )

    with open(result["manifest_paths"]["universe"], encoding="utf-8") as manifest_file:
        universe_manifest = json.load(manifest_file)

    assert universe_manifest["run_id"] == "run_manifest"
    assert universe_manifest["dataset_name"] == "universe"
    assert universe_manifest["row_count"] == 2
    assert universe_manifest["data_quality_status"] == "VALID_DATA"


def test_coverage_summary_has_required_fields(tmp_path):
    universe_path, profile_path = _write_csv_inputs(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        universe_path=universe_path,
        profile_path=profile_path,
    )
    with open(result["coverage_summary_path"], encoding="utf-8") as coverage_file:
        coverage = json.load(coverage_file)

    required_coverage_fields = {
        "row_count",
        "ticker_count",
        "missing_ticker_count",
        "missing_exchange_count",
        "missing_company_name_count",
        "missing_profile_count",
        "duplicate_ticker_count",
        "source_count",
        "warnings",
    }
    assert required_coverage_fields.issubset(coverage["universe"])
    assert required_coverage_fields.issubset(coverage["company_profile"])


def test_raw_outputs_have_no_buy_sell_or_target_price_fields(tmp_path):
    universe_path, profile_path = _write_csv_inputs(tmp_path)

    result = _run_ingestion(
        tmp_path,
        "manual_csv",
        universe_path=universe_path,
        profile_path=profile_path,
    )
    universe_raw = pd.read_csv(result["raw_output_paths"]["universe"])
    profile_raw = pd.read_csv(result["raw_output_paths"]["company_profile"])

    assert not has_prohibited_recommendation_columns(universe_raw)
    assert not has_prohibited_recommendation_columns(profile_raw)

