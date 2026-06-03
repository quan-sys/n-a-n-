"""Ingestion manifest helpers for deterministic run logging."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_MANIFEST_DIR = Path("data/reports/ingestion_manifests")

MANIFEST_FIELDS = [
    "run_id",
    "dataset_name",
    "mode",
    "input_path",
    "output_path",
    "started_at",
    "finished_at",
    "row_count",
    "ticker_count",
    "success_count",
    "failed_count",
    "missing_required_columns",
    "warnings",
    "errors",
    "data_quality_status",
    "notes",
]

LIST_FIELDS = ["missing_required_columns", "warnings", "errors"]
COUNT_FIELDS = ["row_count", "ticker_count", "success_count", "failed_count"]

PROHIBITED_MANIFEST_FIELDS = {
    "buy",
    "sell",
    "recommendation",
    "target_price",
    "price_target",
}


def create_ingestion_manifest_record(
    *,
    run_id: str,
    dataset_name: str,
    mode: str,
    input_path: str = "",
    output_path: str = "",
    started_at: str | None = None,
    finished_at: str | None = None,
    row_count: int = 0,
    ticker_count: int = 0,
    success_count: int = 0,
    failed_count: int = 0,
    missing_required_columns: list[str] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    data_quality_status: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Create a manifest record with all required fields present."""

    normalized_missing = list(missing_required_columns or [])
    normalized_warnings = list(warnings or [])
    normalized_errors = list(errors or [])
    resolved_status = data_quality_status or _resolve_quality_status(
        missing_required_columns=normalized_missing,
        errors=normalized_errors,
        failed_count=failed_count,
    )

    return {
        "run_id": run_id,
        "dataset_name": dataset_name,
        "mode": mode,
        "input_path": input_path,
        "output_path": output_path,
        "started_at": started_at or _utc_now_iso(),
        "finished_at": finished_at or "",
        "row_count": int(row_count),
        "ticker_count": int(ticker_count),
        "success_count": int(success_count),
        "failed_count": int(failed_count),
        "missing_required_columns": normalized_missing,
        "warnings": normalized_warnings,
        "errors": normalized_errors,
        "data_quality_status": resolved_status,
        "notes": notes,
    }


def create_manifest_from_validation(
    *,
    run_id: str,
    dataset_name: str,
    mode: str,
    validation_result: dict[str, Any],
    input_path: str = "",
    output_path: str = "",
    started_at: str | None = None,
    finished_at: str | None = None,
    row_count: int | None = None,
    ticker_count: int | None = None,
    success_count: int | None = None,
    failed_count: int | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Build a manifest record from a contract validation result."""

    missing = list(validation_result.get("missing_required_columns", []))
    warnings = list(validation_result.get("warnings", []))
    errors = list(validation_result.get("errors", []))
    inferred_failed_count = 0 if validation_result.get("is_valid") else 1

    return create_ingestion_manifest_record(
        run_id=run_id,
        dataset_name=dataset_name,
        mode=mode,
        input_path=input_path,
        output_path=output_path,
        started_at=started_at,
        finished_at=finished_at,
        row_count=(
            int(row_count)
            if row_count is not None
            else int(validation_result.get("row_count", 0))
        ),
        ticker_count=(
            int(ticker_count)
            if ticker_count is not None
            else int(validation_result.get("ticker_count", 0))
        ),
        success_count=int(success_count) if success_count is not None else 0,
        failed_count=(
            int(failed_count)
            if failed_count is not None
            else inferred_failed_count
        ),
        missing_required_columns=missing,
        warnings=warnings,
        errors=errors,
        data_quality_status=validation_result.get("data_quality_status"),
        notes=notes,
    )


def validate_manifest_record(record: dict[str, Any]) -> dict[str, Any]:
    """Validate manifest shape without writing it."""

    result = {"is_valid": True, "missing_fields": [], "errors": [], "warnings": []}
    if not isinstance(record, dict):
        result["is_valid"] = False
        result["errors"].append("Manifest record must be a dictionary.")
        return result

    missing_fields = [field for field in MANIFEST_FIELDS if field not in record]
    result["missing_fields"] = missing_fields
    if missing_fields:
        result["is_valid"] = False
        result["errors"].append(
            "Missing manifest fields: " + ", ".join(missing_fields)
        )

    prohibited = [
        field for field in record if field.strip().lower() in PROHIBITED_MANIFEST_FIELDS
    ]
    if prohibited:
        result["is_valid"] = False
        result["errors"].append(
            "Prohibited recommendation or target-price manifest fields present: "
            + ", ".join(prohibited)
        )

    for field in LIST_FIELDS:
        if field in record and not isinstance(record[field], list):
            result["is_valid"] = False
            result["errors"].append(f"{field} must be a list.")

    for field in COUNT_FIELDS:
        if field not in record:
            continue
        try:
            value = int(record[field])
        except (TypeError, ValueError):
            result["is_valid"] = False
            result["errors"].append(f"{field} must be an integer.")
            continue
        if value < 0:
            result["is_valid"] = False
            result["errors"].append(f"{field} must be non-negative.")

    result["errors"] = _dedupe(result["errors"])
    result["warnings"] = _dedupe(result["warnings"])
    result["is_valid"] = not result["errors"]
    return result


def save_ingestion_manifest(
    record: dict[str, Any],
    output_dir: str | Path = DEFAULT_MANIFEST_DIR,
) -> str:
    """Save one manifest record as JSON and return the file path."""

    validation = validate_manifest_record(record)
    if not validation["is_valid"]:
        raise ValueError("; ".join(validation["errors"]))

    manifest_dir = Path(output_dir)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / _manifest_filename(record)
    path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    return str(path)


def load_ingestion_manifest(path: str | Path) -> dict[str, Any]:
    """Read a saved ingestion manifest JSON file."""

    manifest_path = Path(path)
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _manifest_filename(record: dict[str, Any]) -> str:
    run_id = _safe_file_token(record.get("run_id", "run"))
    dataset_name = _safe_file_token(record.get("dataset_name", "dataset"))
    return f"{run_id}_{dataset_name}.json"


def _resolve_quality_status(
    *,
    missing_required_columns: list[str],
    errors: list[str],
    failed_count: int,
) -> str:
    if missing_required_columns or errors or failed_count:
        return "DATA_ERROR"
    return "VALID_DATA"


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _safe_file_token(value: Any) -> str:
    token = str(value).strip().replace("\\", "_").replace("/", "_")
    return "".join(character if character.isalnum() or character in "-_" else "_" for character in token)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
