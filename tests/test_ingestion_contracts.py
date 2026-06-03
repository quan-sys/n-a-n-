from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

from src.ingestion.contracts import (
    PROHIBITED_RECOMMENDATION_FIELDS,
    REQUIRED_CONTRACT_FIELDS,
    REQUIRED_DATASETS,
    get_contract,
    list_contract_datasets,
    load_ingestion_contracts,
    validate_dataset_columns,
    validate_ingestion_contracts,
    validate_manual_file,
)


CONTRACTS_PATH = Path("config/ingestion_contracts.yaml")


def _contracts():
    return load_ingestion_contracts(CONTRACTS_PATH)


def test_contracts_load_successfully():
    contracts = _contracts()

    assert isinstance(contracts, dict)
    assert "datasets" in contracts


def test_required_datasets_exist():
    contracts = _contracts()

    assert REQUIRED_DATASETS.issubset(set(list_contract_datasets(contracts)))


def test_contract_file_validates_without_errors():
    result = validate_ingestion_contracts(_contracts())

    assert result["is_valid"] is True
    assert result["errors"] == []


def test_each_contract_has_required_fields():
    contracts = _contracts()

    for dataset_name in REQUIRED_DATASETS:
        contract = get_contract(contracts, dataset_name)
        assert set(REQUIRED_CONTRACT_FIELDS).issubset(contract)


def test_required_columns_are_enforced():
    contracts = _contracts()
    df = pd.DataFrame(
        [
            {
                "ticker": "MOCK1",
                "company_name": "Mock Company",
                "listing_status": "LISTED",
                "data_source": "mock_sample",
                "last_updated": "2026-01-01",
            }
        ]
    )

    result = validate_dataset_columns(df, "universe", contracts)

    assert result["is_valid"] is False
    assert result["missing_required_columns"] == ["exchange"]
    assert result["data_quality_status"] == "DATA_ERROR"


def test_optional_missing_fields_remain_optional():
    contracts = _contracts()
    df = pd.DataFrame(
        [
            {
                "ticker": "MOCK1",
                "exchange": "HOSE",
                "company_name": "Mock Company",
                "listing_status": "LISTED",
                "data_source": "mock_sample",
                "last_updated": "2026-01-01",
            }
        ]
    )

    result = validate_dataset_columns(df, "universe", contracts)

    assert result["is_valid"] is True
    assert result["missing_required_columns"] == []
    assert result["data_quality_status"] == "VALID_DATA"


def test_source_url_required_contracts_enforce_source_url():
    contracts = _contracts()
    df = pd.DataFrame(
        [
            {
                "ticker": "MOCK1",
                "date": "2026-01-01",
                "event_type": "MOCK_EVENT",
                "source": "mock_sample",
                "fetch_time": "2026-01-01T00:00:00Z",
            }
        ]
    )

    result = validate_dataset_columns(df, "company_events", contracts)

    assert result["is_valid"] is False
    assert "source_url" in result["missing_required_columns"]


def test_unknown_dataset_returns_clear_error():
    with pytest.raises(ValueError, match="Unknown ingestion dataset: unknown_dataset"):
        get_contract(_contracts(), "unknown_dataset")


def test_manual_csv_file_validates_against_contract(tmp_path):
    csv_path = tmp_path / "manual_universe_sample.csv"
    pd.DataFrame(
        [
            {
                "ticker": "MOCK1",
                "exchange": "HOSE",
                "company_name": "Mock Company",
                "listing_status": "LISTED",
                "data_source": "manual_sample",
                "last_updated": "2026-01-01",
            }
        ]
    ).to_csv(csv_path, index=False)

    result = validate_manual_file(csv_path, "universe", _contracts())

    assert result["is_valid"] is True
    assert result["row_count"] == 1
    assert result["ticker_count"] == 1
    assert result["file_format"] == "csv"


def test_manual_file_reports_missing_required_columns(tmp_path):
    csv_path = tmp_path / "manual_market_price_sample.csv"
    pd.DataFrame(
        [
            {
                "ticker": "MOCK1",
                "date": "2026-01-01",
                "close": "sample_close",
                "volume": "sample_volume",
                "source": "manual_sample",
                "source_url": "mock://market_price/MOCK1",
                "fetch_time": "2026-01-01T00:00:00Z",
                "confidence_raw": "sample",
                "notes": "mock/sample market row only",
            }
        ]
    ).to_csv(csv_path, index=False)

    result = validate_manual_file(csv_path, "market_price", _contracts())

    assert result["is_valid"] is False
    assert result["missing_required_columns"] == ["trading_value"]


def test_contract_validation_rejects_recommendation_fields():
    contracts = deepcopy(_contracts())
    contracts["datasets"]["universe"]["optional_columns"].append("target_price")

    result = validate_ingestion_contracts(contracts)

    assert result["is_valid"] is False
    assert any("prohibited recommendation fields" in error for error in result["errors"])


def test_no_contract_defines_buy_sell_or_target_price_fields():
    contracts = _contracts()
    configured_fields = set()
    for contract in contracts["datasets"].values():
        configured_fields.update(contract["required_columns"])
        configured_fields.update(contract["optional_columns"])

    assert PROHIBITED_RECOMMENDATION_FIELDS.isdisjoint(configured_fields)
