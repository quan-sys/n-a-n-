"""Ingestion contract loading and manual input validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None


DEFAULT_CONTRACTS_PATH = Path("config/ingestion_contracts.yaml")

REQUIRED_DATASETS = {
    "universe",
    "company_profile",
    "market_price",
    "financial_statement_summary",
    "disclosure_status",
    "macro_vietnam",
    "commodity_global",
    "sector_news",
    "company_events",
}

REQUIRED_CONTRACT_FIELDS = [
    "dataset_name",
    "required_columns",
    "optional_columns",
    "primary_keys",
    "date_columns",
    "allowed_frequencies",
    "supported_file_formats",
    "supported_modes",
    "output_raw_path",
    "output_clean_path",
    "missing_data_policy",
    "stale_data_policy",
    "confidence_policy",
    "source_url_required",
    "notes",
]

ALLOWED_FILE_FORMATS = {"csv", "xlsx"}
ALLOWED_MODES = {
    "mock",
    "manual_csv",
    "manual_xlsx",
    "external_vendor_optional",
    "real_adapter",
    "real_exchange_optional",
    "real_vnstock_optional",
    "vendor_file",
}
ALLOWED_FREQUENCIES = {
    "daily",
    "weekly",
    "monthly",
    "quarterly",
    "annual",
    "event_driven",
    "manual",
}

PROHIBITED_RECOMMENDATION_FIELDS = {
    "buy",
    "sell",
    "recommendation",
    "target_price",
    "price_target",
    "entry_price",
    "exit_price",
    "rating",
}


def load_ingestion_contracts(
    path: str | Path = DEFAULT_CONTRACTS_PATH,
) -> dict[str, Any]:
    """Load ingestion contracts from YAML."""

    if yaml is None:
        raise ImportError(
            "PyYAML is required to load ingestion contract YAML files. "
            "Install 'pyyaml' before calling load_ingestion_contracts()."
        )

    contract_path = Path(path)
    with contract_path.open("r", encoding="utf-8") as contract_file:
        contracts = yaml.safe_load(contract_file)

    if not isinstance(contracts, dict):
        raise ValueError("Ingestion contracts file must contain a YAML mapping.")

    return contracts


def validate_ingestion_contracts(contracts: dict[str, Any]) -> dict[str, Any]:
    """Validate contract structure, required datasets, and guarded fields."""

    result: dict[str, Any] = {
        "is_valid": True,
        "errors": [],
        "warnings": [],
        "datasets": [],
    }

    if not isinstance(contracts, dict):
        result["is_valid"] = False
        result["errors"].append("Contracts must be a dictionary.")
        return result

    datasets = contracts.get("datasets")
    if not isinstance(datasets, dict):
        result["is_valid"] = False
        result["errors"].append("Contracts must contain a datasets mapping.")
        return result

    configured_datasets = set(datasets)
    missing_datasets = sorted(REQUIRED_DATASETS - configured_datasets)
    if missing_datasets:
        result["is_valid"] = False
        result["errors"].append(
            "Missing required ingestion datasets: " + ", ".join(missing_datasets)
        )

    for dataset_name, contract in datasets.items():
        result["datasets"].append(dataset_name)
        if not isinstance(contract, dict):
            result["is_valid"] = False
            result["errors"].append(f"{dataset_name}: contract must be a dictionary.")
            continue

        _validate_contract_fields(dataset_name, contract, result)

    result["warnings"] = _dedupe(result["warnings"])
    result["errors"] = _dedupe(result["errors"])
    result["is_valid"] = not result["errors"]
    return result


def list_contract_datasets(contracts: dict[str, Any]) -> list[str]:
    """Return configured ingestion dataset names."""

    datasets = contracts.get("datasets", {}) if isinstance(contracts, dict) else {}
    if not isinstance(datasets, dict):
        return []
    return list(datasets)


def get_contract(contracts: dict[str, Any], dataset_name: str) -> dict[str, Any]:
    """Return one dataset contract or raise a clear unknown-dataset error."""

    datasets = contracts.get("datasets", {}) if isinstance(contracts, dict) else {}
    if not isinstance(datasets, dict) or dataset_name not in datasets:
        raise ValueError(f"Unknown ingestion dataset: {dataset_name}")

    contract = datasets[dataset_name]
    if not isinstance(contract, dict):
        raise ValueError(f"Ingestion contract for {dataset_name} must be a mapping.")

    return contract


def validate_dataset_columns(
    df: Any, dataset_name: str, contracts: dict[str, Any]
) -> dict[str, Any]:
    """Validate a DataFrame-like object against an ingestion contract."""

    contract = get_contract(contracts, dataset_name)
    result = _validation_result(dataset_name)

    if not hasattr(df, "columns"):
        result["is_valid"] = False
        result["errors"].append("Input object must expose a columns attribute.")
        result["data_quality_status"] = "DATA_ERROR"
        return result

    actual_columns = list(df.columns)
    expected_columns = list(contract.get("required_columns", []))
    optional_columns = list(contract.get("optional_columns", []))
    missing_required_columns = [
        column for column in expected_columns if column not in actual_columns
    ]

    if contract.get("source_url_required") is True and "source_url" not in actual_columns:
        missing_required_columns.append("source_url")

    prohibited_columns = [
        column
        for column in actual_columns
        if _normalized_field_name(column) in PROHIBITED_RECOMMENDATION_FIELDS
    ]
    allowed_columns = set(expected_columns + optional_columns)
    extra_columns = [column for column in actual_columns if column not in allowed_columns]

    result["missing_required_columns"] = _dedupe(missing_required_columns)
    result["extra_columns"] = extra_columns
    result["prohibited_columns"] = prohibited_columns

    if result["missing_required_columns"]:
        result["is_valid"] = False
        result["warnings"].append(
            "Missing required columns: "
            + ", ".join(result["missing_required_columns"])
        )

    if prohibited_columns:
        result["is_valid"] = False
        result["errors"].append(
            "Prohibited recommendation or target-price columns present: "
            + ", ".join(prohibited_columns)
        )

    result["data_quality_status"] = "VALID_DATA" if result["is_valid"] else "DATA_ERROR"
    return result


def validate_manual_file(
    input_path: str | Path, dataset_name: str, contracts: dict[str, Any]
) -> dict[str, Any]:
    """Load a local manual CSV/XLSX file and validate its columns."""

    path = Path(input_path)
    contract = get_contract(contracts, dataset_name)
    file_format = _file_format(path)
    result = _validation_result(dataset_name)
    result["input_path"] = str(path)
    result["file_format"] = file_format

    if file_format not in contract.get("supported_file_formats", []):
        result["is_valid"] = False
        result["errors"].append(
            f"{dataset_name}: unsupported file format '{file_format}'."
        )
        result["data_quality_status"] = "DATA_ERROR"
        return result

    if file_format == "csv":
        manual_df = pd.read_csv(path)
    elif file_format == "xlsx":
        manual_df = pd.read_excel(path)
    else:
        result["is_valid"] = False
        result["errors"].append(f"Unsupported manual file format: {file_format}")
        result["data_quality_status"] = "DATA_ERROR"
        return result

    column_result = validate_dataset_columns(manual_df, dataset_name, contracts)
    column_result["input_path"] = str(path)
    column_result["file_format"] = file_format
    column_result["row_count"] = int(len(manual_df))
    column_result["ticker_count"] = _ticker_count(manual_df)
    return column_result


def _validate_contract_fields(
    dataset_name: str, contract: dict[str, Any], result: dict[str, Any]
) -> None:
    for field in REQUIRED_CONTRACT_FIELDS:
        if field not in contract:
            result["errors"].append(f"{dataset_name}: missing contract field '{field}'.")

    declared_name = contract.get("dataset_name")
    if declared_name != dataset_name:
        result["errors"].append(
            f"{dataset_name}: dataset_name must match mapping key '{dataset_name}'."
        )

    for list_field in [
        "required_columns",
        "optional_columns",
        "primary_keys",
        "date_columns",
        "allowed_frequencies",
        "supported_file_formats",
        "supported_modes",
    ]:
        _require_string_list(dataset_name, contract, list_field, result)

    _check_allowed_values(
        dataset_name,
        "supported_file_formats",
        contract.get("supported_file_formats", []),
        ALLOWED_FILE_FORMATS,
        result,
    )
    _check_allowed_values(
        dataset_name,
        "supported_modes",
        contract.get("supported_modes", []),
        ALLOWED_MODES,
        result,
    )
    _check_allowed_values(
        dataset_name,
        "allowed_frequencies",
        contract.get("allowed_frequencies", []),
        ALLOWED_FREQUENCIES,
        result,
    )

    all_columns = [
        *contract.get("required_columns", []),
        *contract.get("optional_columns", []),
    ]
    prohibited = [
        column
        for column in all_columns
        if _normalized_field_name(column) in PROHIBITED_RECOMMENDATION_FIELDS
    ]
    if prohibited:
        result["errors"].append(
            f"{dataset_name}: prohibited recommendation fields configured: "
            + ", ".join(prohibited)
        )

    primary_key_columns = contract.get("primary_keys", [])
    missing_primary_keys = [
        column for column in primary_key_columns if column not in all_columns
    ]
    if missing_primary_keys:
        result["errors"].append(
            f"{dataset_name}: primary keys missing from contract columns: "
            + ", ".join(missing_primary_keys)
        )

    date_columns = contract.get("date_columns", [])
    missing_date_columns = [column for column in date_columns if column not in all_columns]
    if missing_date_columns:
        result["errors"].append(
            f"{dataset_name}: date columns missing from contract columns: "
            + ", ".join(missing_date_columns)
        )

    if not isinstance(contract.get("source_url_required"), bool):
        result["errors"].append(f"{dataset_name}: source_url_required must be boolean.")

    if contract.get("source_url_required") is True and "source_url" not in all_columns:
        result["errors"].append(
            f"{dataset_name}: source_url_required is true but source_url is not configured."
        )

    if "mock" not in contract.get("supported_modes", []):
        result["warnings"].append(f"{dataset_name}: mock mode is not configured.")


def _validation_result(dataset_name: str) -> dict[str, Any]:
    return {
        "dataset_name": dataset_name,
        "is_valid": True,
        "missing_required_columns": [],
        "extra_columns": [],
        "prohibited_columns": [],
        "warnings": [],
        "errors": [],
        "data_quality_status": "VALID_DATA",
    }


def _require_string_list(
    dataset_name: str,
    contract: dict[str, Any],
    field: str,
    result: dict[str, Any],
) -> None:
    value = contract.get(field)
    if not isinstance(value, list):
        result["errors"].append(f"{dataset_name}: {field} must be a list.")
        return

    if field in {"required_columns", "primary_keys", "supported_modes"} and not value:
        result["errors"].append(f"{dataset_name}: {field} must not be empty.")

    non_string_values = [item for item in value if not isinstance(item, str)]
    if non_string_values:
        result["errors"].append(f"{dataset_name}: {field} must contain only strings.")


def _check_allowed_values(
    dataset_name: str,
    field: str,
    values: Any,
    allowed_values: set[str],
    result: dict[str, Any],
) -> None:
    if not isinstance(values, list):
        return

    invalid_values = sorted({value for value in values if value not in allowed_values})
    if invalid_values:
        result["errors"].append(
            f"{dataset_name}: invalid {field}: "
            + ", ".join(invalid_values)
            + ". Allowed values: "
            + ", ".join(sorted(allowed_values))
            + "."
        )


def _file_format(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix == "xls":
        return "xlsx"
    return suffix


def _ticker_count(df: pd.DataFrame) -> int:
    if "ticker" not in df.columns:
        return 0
    return int(df["ticker"].dropna().astype(str).str.strip().replace("", pd.NA).nunique())


def _normalized_field_name(value: Any) -> str:
    return str(value).strip().lower()


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(values))
