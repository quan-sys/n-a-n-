"""Bulk ingestion for universe and company profile raw inputs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingestion.contracts import (
    DEFAULT_CONTRACTS_PATH,
    PROHIBITED_RECOMMENDATION_FIELDS,
    load_ingestion_contracts,
    validate_dataset_columns,
)
from src.ingestion.manifest import (
    create_ingestion_manifest_record,
    save_ingestion_manifest,
)


REAL_SOURCE_UNAVAILABLE = "REAL_SOURCE_UNAVAILABLE"
SUPPORTED_MODES = {"manual_csv", "manual_xlsx", "mock", "real_vnstock_optional"}
ALLOWED_EXCHANGES = {"HOSE", "HNX", "UPCOM"}

DEFAULT_RAW_OUTPUT_DIR = Path("data/raw")
DEFAULT_COVERAGE_OUTPUT_DIR = Path("data/reports/ingestion_coverage")
DEFAULT_MANIFEST_DIR = Path("data/reports/ingestion_manifests")

UNIVERSE_RAW_FILENAME = "universe_raw.csv"
COMPANY_PROFILE_RAW_FILENAME = "company_profile_raw.csv"

UNIVERSE_OUTPUT_COLUMNS = [
    "ticker",
    "exchange",
    "company_name",
    "listing_status",
    "data_source",
    "last_updated",
    "source",
    "source_url",
    "fetch_time",
    "confidence_raw",
    "notes",
]

COMPANY_PROFILE_OUTPUT_COLUMNS = [
    "ticker",
    "company_name",
    "exchange",
    "industry_raw",
    "business_description",
    "source",
    "source_url",
    "last_updated",
    "fetch_time",
    "confidence_raw",
    "notes",
]


def ingest_universe_and_company_profiles(
    *,
    mode: str,
    universe_input_path: str | Path | None = None,
    company_profile_input_path: str | Path | None = None,
    raw_output_dir: str | Path = DEFAULT_RAW_OUTPUT_DIR,
    manifest_dir: str | Path = DEFAULT_MANIFEST_DIR,
    coverage_output_dir: str | Path = DEFAULT_COVERAGE_OUTPUT_DIR,
    contracts_path: str | Path = DEFAULT_CONTRACTS_PATH,
    run_id: str | None = None,
    fetch_time: str | None = None,
) -> dict[str, Any]:
    """Ingest universe and company profile files into raw standardized CSVs."""

    if mode not in SUPPORTED_MODES:
        raise ValueError(
            f"Unsupported universe/profile ingestion mode: {mode}. "
            f"Supported modes: {', '.join(sorted(SUPPORTED_MODES))}."
        )

    resolved_run_id = run_id or _default_run_id()
    resolved_fetch_time = fetch_time or _utc_now_iso()

    if mode == "real_vnstock_optional":
        return _real_source_unavailable_result(
            run_id=resolved_run_id,
            manifest_dir=manifest_dir,
            fetch_time=resolved_fetch_time,
        )

    contracts = load_ingestion_contracts(contracts_path)
    universe_df, profile_df, input_paths = _load_inputs(
        mode=mode,
        universe_input_path=universe_input_path,
        company_profile_input_path=company_profile_input_path,
        fetch_time=resolved_fetch_time,
    )

    validation_results = {
        "universe": validate_dataset_columns(universe_df, "universe", contracts),
        "company_profile": validate_dataset_columns(
            profile_df, "company_profile", contracts
        ),
    }

    invalid_datasets = [
        dataset_name
        for dataset_name, validation in validation_results.items()
        if not validation["is_valid"]
    ]

    if invalid_datasets:
        manifest_paths = _write_validation_manifests(
            run_id=resolved_run_id,
            mode=mode,
            validation_results=validation_results,
            dataframes={"universe": universe_df, "company_profile": profile_df},
            input_paths=input_paths,
            output_paths={},
            manifest_dir=manifest_dir,
            finished_at=resolved_fetch_time,
            notes="validation failed before raw files were written",
        )
        return {
            "status": "DATA_ERROR",
            "run_id": resolved_run_id,
            "mode": mode,
            "raw_output_paths": {},
            "manifest_paths": manifest_paths,
            "coverage_summary_path": "",
            "coverage": {},
            "validation_results": validation_results,
            "errors": [
                f"{dataset_name}: missing required columns "
                + ", ".join(
                    validation_results[dataset_name]["missing_required_columns"]
                )
                for dataset_name in invalid_datasets
            ],
            "warnings": [],
        }

    universe_raw = standardize_universe_raw(universe_df, mode, resolved_fetch_time)
    profile_raw = standardize_company_profile_raw(profile_df, mode, resolved_fetch_time)
    coverage = build_universe_profile_coverage(universe_raw, profile_raw, mode=mode)

    raw_paths = save_universe_profile_raw_outputs(
        universe_raw=universe_raw,
        profile_raw=profile_raw,
        raw_output_dir=raw_output_dir,
    )
    coverage_path = save_coverage_summary(
        coverage=coverage,
        run_id=resolved_run_id,
        coverage_output_dir=coverage_output_dir,
    )
    manifest_paths = _write_success_manifests(
        run_id=resolved_run_id,
        mode=mode,
        universe_raw=universe_raw,
        profile_raw=profile_raw,
        input_paths=input_paths,
        output_paths=raw_paths,
        coverage=coverage,
        manifest_dir=manifest_dir,
        finished_at=resolved_fetch_time,
    )

    all_warnings = _dedupe(
        [
            *coverage["universe"]["warnings"],
            *coverage["company_profile"]["warnings"],
            *coverage["combined"]["warnings"],
        ]
    )
    status = "SUCCESS_WITH_WARNINGS" if all_warnings else "SUCCESS"

    return {
        "status": status,
        "run_id": resolved_run_id,
        "mode": mode,
        "raw_output_paths": raw_paths,
        "manifest_paths": manifest_paths,
        "coverage_summary_path": coverage_path,
        "coverage": coverage,
        "validation_results": validation_results,
        "errors": [],
        "warnings": all_warnings,
    }


def standardize_universe_raw(
    df: pd.DataFrame, mode: str, fetch_time: str | None = None
) -> pd.DataFrame:
    """Return a raw standardized universe frame without fabricating profile data."""

    output = _copy_with_output_columns(df, UNIVERSE_OUTPUT_COLUMNS)
    output["ticker"] = output["ticker"].map(_normalize_ticker)
    output["exchange"] = output["exchange"].map(_clean_text)
    output["company_name"] = output["company_name"].map(_clean_text)
    output["listing_status"] = output["listing_status"].map(_clean_text)
    output["data_source"] = output["data_source"].map(_clean_text)
    output["last_updated"] = output["last_updated"].map(_clean_text)

    output["source"] = _choose_text_series(output["source"], output["data_source"])
    output["source_url"] = output["source_url"].map(_clean_text)
    output["fetch_time"] = _fill_missing_text(output["fetch_time"], fetch_time or _utc_now_iso())
    output["confidence_raw"] = _fill_missing_text(
        output["confidence_raw"], _confidence_for_mode(mode)
    )
    output["notes"] = _fill_missing_text(output["notes"], _notes_for_mode(mode, "universe"))
    return output[UNIVERSE_OUTPUT_COLUMNS]


def standardize_company_profile_raw(
    df: pd.DataFrame, mode: str, fetch_time: str | None = None
) -> pd.DataFrame:
    """Return a raw standardized company profile frame without guessing fields."""

    output = _copy_with_output_columns(df, COMPANY_PROFILE_OUTPUT_COLUMNS)
    output["ticker"] = output["ticker"].map(_normalize_ticker)
    output["company_name"] = output["company_name"].map(_clean_text)
    output["exchange"] = output["exchange"].map(_clean_text)
    output["industry_raw"] = output["industry_raw"].map(_clean_text)
    output["business_description"] = output["business_description"].map(_clean_text)
    output["source"] = output["source"].map(_clean_text)
    output["source_url"] = output["source_url"].map(_clean_text)
    output["last_updated"] = output["last_updated"].map(_clean_text)
    output["fetch_time"] = _fill_missing_text(output["fetch_time"], fetch_time or _utc_now_iso())
    output["confidence_raw"] = _fill_missing_text(
        output["confidence_raw"], _confidence_for_mode(mode)
    )
    output["notes"] = _fill_missing_text(
        output["notes"], _notes_for_mode(mode, "company_profile")
    )
    return output[COMPANY_PROFILE_OUTPUT_COLUMNS]


def build_universe_profile_coverage(
    universe_raw: pd.DataFrame, profile_raw: pd.DataFrame, mode: str
) -> dict[str, Any]:
    """Build coverage summaries for universe/profile ingestion."""

    universe_tickers = _ticker_set(universe_raw)
    profile_tickers = _ticker_set(profile_raw)
    missing_profile_tickers = sorted(universe_tickers - profile_tickers)

    universe_summary = _coverage_for_frame(
        universe_raw,
        source_column="source",
        missing_profile_count=len(missing_profile_tickers),
    )
    profile_summary = _coverage_for_frame(
        profile_raw,
        source_column="source",
        missing_profile_count=_missing_count(profile_raw, "business_description"),
    )

    for ticker in missing_profile_tickers:
        universe_summary["warnings"].append(f"MISSING_PROFILE_FOR_TICKER: {ticker}")

    combined_warnings = _dedupe(
        [*universe_summary["warnings"], *profile_summary["warnings"]]
    )
    return {
        "mode": mode,
        "universe": _finalize_coverage(universe_summary),
        "company_profile": _finalize_coverage(profile_summary),
        "combined": {
            "row_count": int(len(universe_raw) + len(profile_raw)),
            "ticker_count": len(universe_tickers.union(profile_tickers)),
            "missing_profile_count": len(missing_profile_tickers),
            "missing_profile_tickers": missing_profile_tickers,
            "warnings": combined_warnings,
        },
    }


def save_universe_profile_raw_outputs(
    *,
    universe_raw: pd.DataFrame,
    profile_raw: pd.DataFrame,
    raw_output_dir: str | Path = DEFAULT_RAW_OUTPUT_DIR,
) -> dict[str, str]:
    """Save raw universe/profile files and return their output paths."""

    output_dir = Path(raw_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    universe_path = output_dir / UNIVERSE_RAW_FILENAME
    profile_path = output_dir / COMPANY_PROFILE_RAW_FILENAME
    universe_raw.to_csv(universe_path, index=False)
    profile_raw.to_csv(profile_path, index=False)
    return {
        "universe": str(universe_path),
        "company_profile": str(profile_path),
    }


def save_coverage_summary(
    *,
    coverage: dict[str, Any],
    run_id: str,
    coverage_output_dir: str | Path = DEFAULT_COVERAGE_OUTPUT_DIR,
) -> str:
    """Save coverage summary JSON and return the output path."""

    output_dir = Path(coverage_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{_safe_file_token(run_id)}_universe_profile_coverage.json"
    output_path.write_text(
        json.dumps(coverage, indent=2, sort_keys=True), encoding="utf-8"
    )
    return str(output_path)


def _load_inputs(
    *,
    mode: str,
    universe_input_path: str | Path | None,
    company_profile_input_path: str | Path | None,
    fetch_time: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    if mode == "mock":
        return _mock_inputs(fetch_time), _mock_profiles(fetch_time), {
            "universe": "mock",
            "company_profile": "mock",
        }

    if mode in {"manual_csv", "manual_xlsx"}:
        if universe_input_path is None or company_profile_input_path is None:
            raise ValueError(
                "universe_input_path and company_profile_input_path are required "
                f"for {mode} mode."
            )
        return (
            _load_manual_file(universe_input_path, mode),
            _load_manual_file(company_profile_input_path, mode),
            {
                "universe": str(universe_input_path),
                "company_profile": str(company_profile_input_path),
            },
        )

    raise ValueError(f"Unsupported mode: {mode}")


def _load_manual_file(path: str | Path, mode: str) -> pd.DataFrame:
    input_path = Path(path)
    if mode == "manual_csv":
        return pd.read_csv(input_path)
    if mode == "manual_xlsx":
        return pd.read_excel(input_path)
    raise ValueError(f"Unsupported manual mode: {mode}")


def _mock_inputs(fetch_time: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "MOCK1",
                "exchange": "HOSE",
                "company_name": "Mock Company One",
                "listing_status": "LISTED",
                "data_source": "MOCK_SAMPLE",
                "last_updated": "2026-01-01",
                "source": "MOCK_SAMPLE",
                "source_url": "mock://universe/MOCK1",
                "fetch_time": fetch_time,
                "confidence_raw": "mock",
                "notes": "mock/sample data only; not real Vietnamese stock data",
            },
            {
                "ticker": "MOCK2",
                "exchange": "HNX",
                "company_name": "Mock Company Two",
                "listing_status": "LISTED",
                "data_source": "MOCK_SAMPLE",
                "last_updated": "2026-01-01",
                "source": "MOCK_SAMPLE",
                "source_url": "mock://universe/MOCK2",
                "fetch_time": fetch_time,
                "confidence_raw": "mock",
                "notes": "mock/sample data only; not real Vietnamese stock data",
            },
        ]
    )


def _mock_profiles(fetch_time: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "MOCK1",
                "company_name": "Mock Company One",
                "exchange": "HOSE",
                "industry_raw": "MOCK_INDUSTRY",
                "business_description": "Mock profile only; not real company data",
                "source": "MOCK_SAMPLE",
                "source_url": "mock://company_profile/MOCK1",
                "last_updated": "2026-01-01",
                "fetch_time": fetch_time,
                "confidence_raw": "mock",
                "notes": "mock/sample data only; not real Vietnamese stock data",
            },
            {
                "ticker": "MOCK2",
                "company_name": "Mock Company Two",
                "exchange": "HNX",
                "industry_raw": "MOCK_INDUSTRY",
                "business_description": "Mock profile only; not real company data",
                "source": "MOCK_SAMPLE",
                "source_url": "mock://company_profile/MOCK2",
                "last_updated": "2026-01-01",
                "fetch_time": fetch_time,
                "confidence_raw": "mock",
                "notes": "mock/sample data only; not real Vietnamese stock data",
            },
        ]
    )


def _real_source_unavailable_result(
    *,
    run_id: str,
    manifest_dir: str | Path,
    fetch_time: str,
) -> dict[str, Any]:
    manifest_paths: dict[str, str] = {}
    for dataset_name in ["universe", "company_profile"]:
        record = create_ingestion_manifest_record(
            run_id=run_id,
            dataset_name=dataset_name,
            mode="real_vnstock_optional",
            started_at=fetch_time,
            finished_at=fetch_time,
            failed_count=1,
            errors=[REAL_SOURCE_UNAVAILABLE],
            data_quality_status=REAL_SOURCE_UNAVAILABLE,
            notes=(
                "Optional real vnstock adapter is not implemented or unavailable; "
                "no live data was fetched."
            ),
        )
        manifest_paths[dataset_name] = save_ingestion_manifest(
            record, output_dir=manifest_dir
        )

    return {
        "status": REAL_SOURCE_UNAVAILABLE,
        "run_id": run_id,
        "mode": "real_vnstock_optional",
        "raw_output_paths": {},
        "manifest_paths": manifest_paths,
        "coverage_summary_path": "",
        "coverage": {},
        "validation_results": {},
        "errors": [REAL_SOURCE_UNAVAILABLE],
        "warnings": ["Optional real source unavailable; no live data fetched."],
    }


def _write_validation_manifests(
    *,
    run_id: str,
    mode: str,
    validation_results: dict[str, dict[str, Any]],
    dataframes: dict[str, pd.DataFrame],
    input_paths: dict[str, str],
    output_paths: dict[str, str],
    manifest_dir: str | Path,
    finished_at: str,
    notes: str,
) -> dict[str, str]:
    manifest_paths: dict[str, str] = {}
    for dataset_name, validation in validation_results.items():
        record = create_ingestion_manifest_record(
            run_id=run_id,
            dataset_name=dataset_name,
            mode=mode,
            input_path=input_paths.get(dataset_name, ""),
            output_path=output_paths.get(dataset_name, ""),
            started_at=finished_at,
            finished_at=finished_at,
            row_count=int(len(dataframes[dataset_name])),
            ticker_count=len(_ticker_set(dataframes[dataset_name])),
            success_count=0,
            failed_count=1 if not validation["is_valid"] else 0,
            missing_required_columns=validation["missing_required_columns"],
            warnings=validation["warnings"],
            errors=validation["errors"],
            data_quality_status=validation["data_quality_status"],
            notes=notes,
        )
        manifest_paths[dataset_name] = save_ingestion_manifest(
            record, output_dir=manifest_dir
        )
    return manifest_paths


def _write_success_manifests(
    *,
    run_id: str,
    mode: str,
    universe_raw: pd.DataFrame,
    profile_raw: pd.DataFrame,
    input_paths: dict[str, str],
    output_paths: dict[str, str],
    coverage: dict[str, Any],
    manifest_dir: str | Path,
    finished_at: str,
) -> dict[str, str]:
    dataframes = {"universe": universe_raw, "company_profile": profile_raw}
    manifest_paths: dict[str, str] = {}
    for dataset_name, df in dataframes.items():
        dataset_coverage = coverage[dataset_name]
        warnings = dataset_coverage["warnings"]
        record = create_ingestion_manifest_record(
            run_id=run_id,
            dataset_name=dataset_name,
            mode=mode,
            input_path=input_paths.get(dataset_name, ""),
            output_path=output_paths.get(dataset_name, ""),
            started_at=finished_at,
            finished_at=finished_at,
            row_count=int(len(df)),
            ticker_count=dataset_coverage["ticker_count"],
            success_count=int(len(df)),
            failed_count=0,
            warnings=warnings,
            data_quality_status=(
                "MANUAL_REVIEW_REQUIRED" if warnings else "VALID_DATA"
            ),
            notes="raw universe/profile ingestion completed",
        )
        manifest_paths[dataset_name] = save_ingestion_manifest(
            record, output_dir=manifest_dir
        )
    return manifest_paths


def _coverage_for_frame(
    df: pd.DataFrame, source_column: str, missing_profile_count: int
) -> dict[str, Any]:
    summary = {
        "row_count": int(len(df)),
        "ticker_count": len(_ticker_set(df)),
        "missing_ticker_count": _missing_count(df, "ticker"),
        "missing_exchange_count": _missing_count(df, "exchange"),
        "missing_company_name_count": _missing_count(df, "company_name"),
        "missing_profile_count": int(missing_profile_count),
        "duplicate_ticker_count": _duplicate_ticker_count(df),
        "source_count": _source_count(df, source_column),
        "warnings": [],
    }

    if summary["missing_ticker_count"]:
        summary["warnings"].append("MISSING_TICKER")
    if summary["missing_exchange_count"]:
        summary["warnings"].append("MISSING_EXCHANGE")
    if summary["missing_company_name_count"]:
        summary["warnings"].append("MISSING_COMPANY_NAME")
    if summary["duplicate_ticker_count"]:
        summary["warnings"].append("DUPLICATE_TICKER")

    unknown_exchanges = _unknown_exchanges(df)
    for exchange in unknown_exchanges:
        summary["warnings"].append(f"UNKNOWN_EXCHANGE: {exchange}")

    if missing_profile_count:
        summary["warnings"].append("MISSING_PROFILE")

    return summary


def _finalize_coverage(summary: dict[str, Any]) -> dict[str, Any]:
    summary["warnings"] = _dedupe(summary["warnings"])
    return summary


def _copy_with_output_columns(df: pd.DataFrame, output_columns: list[str]) -> pd.DataFrame:
    output = df.copy(deep=True)
    for column in output_columns:
        if column not in output.columns:
            output[column] = ""
    return output[output_columns].copy()


def _choose_text_series(primary: pd.Series, fallback: pd.Series) -> pd.Series:
    primary_clean = primary.map(_clean_text)
    fallback_clean = fallback.map(_clean_text)
    return primary_clean.where(primary_clean.map(bool), fallback_clean)


def _fill_missing_text(series: pd.Series, default: str) -> pd.Series:
    cleaned = series.map(_clean_text)
    return cleaned.where(cleaned.map(bool), default)


def _missing_count(df: pd.DataFrame, column: str) -> int:
    if column not in df.columns:
        return int(len(df))
    return int(df[column].map(_is_missing).sum())


def _duplicate_ticker_count(df: pd.DataFrame) -> int:
    if "ticker" not in df.columns:
        return 0
    tickers = df["ticker"].map(_normalize_ticker)
    counts = tickers[tickers.map(bool)].value_counts()
    return int((counts > 1).sum())


def _source_count(df: pd.DataFrame, source_column: str) -> int:
    if source_column not in df.columns:
        return 0
    sources = df[source_column].map(_clean_text)
    return int(sources[sources.map(bool)].nunique())


def _ticker_set(df: pd.DataFrame) -> set[str]:
    if "ticker" not in df.columns:
        return set()
    return {
        ticker
        for ticker in df["ticker"].map(_normalize_ticker)
        if ticker
    }


def _unknown_exchanges(df: pd.DataFrame) -> list[str]:
    if "exchange" not in df.columns:
        return []
    exchanges = {_clean_text(exchange).upper() for exchange in df["exchange"]}
    return sorted(exchange for exchange in exchanges if exchange and exchange not in ALLOWED_EXCHANGES)


def _confidence_for_mode(mode: str) -> str:
    if mode == "mock":
        return "mock"
    return "medium"


def _notes_for_mode(mode: str, dataset_name: str) -> str:
    if mode == "mock":
        return "mock/sample data only; not real Vietnamese stock data"
    return f"manual {dataset_name} input; requires downstream validation"


def _normalize_ticker(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip().upper()


def _clean_text(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip()


def _is_missing(value: Any) -> bool:
    if value is None or pd.isna(value):
        return True
    return isinstance(value, str) and not value.strip()


def _default_run_id() -> str:
    return f"universe_profile_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _safe_file_token(value: Any) -> str:
    token = str(value).strip().replace("\\", "_").replace("/", "_")
    return "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in token
    )


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(values))


def has_prohibited_recommendation_columns(df: pd.DataFrame) -> bool:
    """Return True if a raw output frame contains prohibited recommendation fields."""

    normalized_columns = {str(column).strip().lower() for column in df.columns}
    return bool(PROHIBITED_RECOMMENDATION_FIELDS.intersection(normalized_columns))
