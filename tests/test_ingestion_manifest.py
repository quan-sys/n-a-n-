import json

import pytest

from src.ingestion.contracts import load_ingestion_contracts, validate_dataset_columns
from src.ingestion.manifest import (
    MANIFEST_FIELDS,
    create_ingestion_manifest_record,
    create_manifest_from_validation,
    load_ingestion_manifest,
    save_ingestion_manifest,
    validate_manifest_record,
)


def test_manifest_record_contains_all_required_fields():
    record = create_ingestion_manifest_record(
        run_id="run_mock_001",
        dataset_name="universe",
        mode="manual_csv",
        input_path="data/raw/universe/sample.csv",
        output_path="data/clean/universe.csv",
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:01:00Z",
        row_count=1,
        ticker_count=1,
        success_count=1,
        notes="mock/sample manifest only",
    )

    assert set(MANIFEST_FIELDS).issubset(record)
    assert record["data_quality_status"] == "VALID_DATA"


def test_manifest_can_be_saved_and_loaded(tmp_path):
    record = create_ingestion_manifest_record(
        run_id="run_mock_002",
        dataset_name="market_price",
        mode="manual_csv",
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:01:00Z",
        row_count=2,
        ticker_count=1,
        success_count=2,
        notes="mock/sample manifest only",
    )

    path = save_ingestion_manifest(record, output_dir=tmp_path)
    loaded = load_ingestion_manifest(path)

    assert loaded == record
    assert path.endswith("run_mock_002_market_price.json")


def test_save_manifest_writes_json_object(tmp_path):
    record = create_ingestion_manifest_record(
        run_id="run_mock_003",
        dataset_name="company_profile",
        mode="manual_csv",
        started_at="2026-01-01T00:00:00Z",
        row_count=1,
        ticker_count=1,
        success_count=1,
    )

    path = save_ingestion_manifest(record, output_dir=tmp_path)

    with open(path, encoding="utf-8") as manifest_file:
        loaded = json.load(manifest_file)

    assert loaded["run_id"] == "run_mock_003"
    assert loaded["dataset_name"] == "company_profile"


def test_manifest_from_validation_records_missing_required_columns():
    contracts = load_ingestion_contracts("config/ingestion_contracts.yaml")
    validation_result = validate_dataset_columns(
        df=type("ColumnsOnly", (), {"columns": ["ticker", "date", "source"]})(),
        dataset_name="market_price",
        contracts=contracts,
    )

    record = create_manifest_from_validation(
        run_id="run_mock_004",
        dataset_name="market_price",
        mode="manual_csv",
        validation_result=validation_result,
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:01:00Z",
    )

    assert record["data_quality_status"] == "DATA_ERROR"
    assert set(record["missing_required_columns"]) == {
        "close",
        "volume",
        "trading_value",
        "source_url",
        "fetch_time",
        "confidence_raw",
        "notes",
    }
    assert record["failed_count"] == 1


def test_manifest_validation_reports_missing_fields():
    record = create_ingestion_manifest_record(
        run_id="run_mock_005",
        dataset_name="disclosure_status",
        mode="manual_csv",
    )
    record.pop("row_count")

    result = validate_manifest_record(record)

    assert result["is_valid"] is False
    assert result["missing_fields"] == ["row_count"]
    assert any("Missing manifest fields" in error for error in result["errors"])


def test_manifest_validation_rejects_negative_counts():
    record = create_ingestion_manifest_record(
        run_id="run_mock_006",
        dataset_name="universe",
        mode="manual_csv",
        row_count=-1,
    )

    result = validate_manifest_record(record)

    assert result["is_valid"] is False
    assert "row_count must be non-negative." in result["errors"]


def test_save_rejects_invalid_manifest(tmp_path):
    record = create_ingestion_manifest_record(
        run_id="run_mock_007",
        dataset_name="universe",
        mode="manual_csv",
    )
    record["warnings"] = "not-a-list"

    with pytest.raises(ValueError, match="warnings must be a list"):
        save_ingestion_manifest(record, output_dir=tmp_path)


def test_manifest_has_no_buy_sell_or_target_price_fields():
    prohibited = {"buy", "sell", "recommendation", "target_price", "price_target"}

    assert prohibited.isdisjoint(MANIFEST_FIELDS)
