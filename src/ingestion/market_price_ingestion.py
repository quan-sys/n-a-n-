"""Bulk ingestion for market price, volume, and trading value raw inputs."""

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

DEFAULT_RAW_OUTPUT_DIR = Path("data/raw")
DEFAULT_COVERAGE_OUTPUT_DIR = Path("data/reports/ingestion_coverage")
DEFAULT_MANIFEST_DIR = Path("data/reports/ingestion_manifests")
DEFAULT_TICKER_LOG_DIR = Path("data/reports/ingestion_ticker_logs")

MARKET_PRICE_RAW_FILENAME = "market_price_raw.csv"

MARKET_PRICE_OUTPUT_COLUMNS = [
    "ticker",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trading_value",
    "source",
    "source_url",
    "fetch_time",
    "confidence_raw",
    "notes",
]

TICKER_LOG_COLUMNS = [
    "ticker",
    "status",
    "row_count",
    "failure_reason",
    "warnings",
]


def ingest_market_price_data(
    *,
    mode: str,
    input_path: str | Path | None = None,
    requested_tickers: list[str] | None = None,
    raw_output_dir: str | Path = DEFAULT_RAW_OUTPUT_DIR,
    manifest_dir: str | Path = DEFAULT_MANIFEST_DIR,
    coverage_output_dir: str | Path = DEFAULT_COVERAGE_OUTPUT_DIR,
    ticker_log_dir: str | Path = DEFAULT_TICKER_LOG_DIR,
    contracts_path: str | Path = DEFAULT_CONTRACTS_PATH,
    run_id: str | None = None,
    fetch_time: str | None = None,
    stale_reference_date: str | None = None,
    stale_after_days: int = 370,
) -> dict[str, Any]:
    """Ingest market price rows into a raw standardized CSV."""

    if mode not in SUPPORTED_MODES:
        raise ValueError(
            f"Unsupported market price ingestion mode: {mode}. "
            f"Supported modes: {', '.join(sorted(SUPPORTED_MODES))}."
        )

    resolved_run_id = run_id or _default_run_id()
    resolved_fetch_time = fetch_time or _utc_now_iso()
    normalized_requested = _normalize_requested_tickers(requested_tickers)

    if mode == "real_vnstock_optional":
        return _real_source_unavailable_result(
            run_id=resolved_run_id,
            requested_tickers=normalized_requested,
            manifest_dir=manifest_dir,
            ticker_log_dir=ticker_log_dir,
            fetch_time=resolved_fetch_time,
        )

    contracts = load_ingestion_contracts(contracts_path)
    raw_input = _load_input(
        mode=mode,
        input_path=input_path,
        fetch_time=resolved_fetch_time,
        requested_tickers=normalized_requested,
    )
    input_label = "mock" if mode == "mock" else str(input_path)
    validation = validate_dataset_columns(raw_input, "market_price", contracts)

    if not validation["is_valid"]:
        manifest_path = _write_manifest(
            run_id=resolved_run_id,
            mode=mode,
            input_path=input_label,
            output_path="",
            df=raw_input,
            success_count=0,
            failed_count=max(1, len(normalized_requested)),
            missing_required_columns=validation["missing_required_columns"],
            warnings=validation["warnings"],
            errors=validation["errors"],
            data_quality_status=validation["data_quality_status"],
            manifest_dir=manifest_dir,
            finished_at=resolved_fetch_time,
            notes="market price validation failed before raw output was written",
        )
        ticker_log = build_market_price_ticker_log(
            market_raw=standardize_market_price_raw(
                raw_input, mode=mode, fetch_time=resolved_fetch_time
            ),
            requested_tickers=normalized_requested,
            coverage=None,
            validation_failed=True,
        )
        ticker_log_path = save_ticker_log(
            ticker_log=ticker_log,
            run_id=resolved_run_id,
            ticker_log_dir=ticker_log_dir,
        )
        return {
            "status": "DATA_ERROR",
            "run_id": resolved_run_id,
            "mode": mode,
            "raw_output_path": "",
            "manifest_path": manifest_path,
            "coverage_report_path": "",
            "ticker_log_path": ticker_log_path,
            "coverage": {},
            "validation_result": validation,
            "errors": validation["errors"],
            "warnings": validation["warnings"],
        }

    market_raw = standardize_market_price_raw(
        raw_input, mode=mode, fetch_time=resolved_fetch_time
    )
    coverage = build_market_price_coverage(
        market_raw=market_raw,
        requested_tickers=normalized_requested,
        stale_reference_date=stale_reference_date,
        stale_after_days=stale_after_days,
    )
    ticker_log = build_market_price_ticker_log(
        market_raw=market_raw,
        requested_tickers=normalized_requested,
        coverage=coverage,
        validation_failed=False,
    )

    raw_output_path = save_market_price_raw(
        market_raw=market_raw, raw_output_dir=raw_output_dir
    )
    coverage_report_path = save_coverage_report(
        coverage=coverage,
        run_id=resolved_run_id,
        coverage_output_dir=coverage_output_dir,
    )
    ticker_log_path = save_ticker_log(
        ticker_log=ticker_log,
        run_id=resolved_run_id,
        ticker_log_dir=ticker_log_dir,
    )

    manifest_path = _write_manifest(
        run_id=resolved_run_id,
        mode=mode,
        input_path=input_label,
        output_path=raw_output_path,
        df=market_raw,
        success_count=coverage["ticker_count_success"],
        failed_count=coverage["ticker_count_failed"],
        missing_required_columns=[],
        warnings=coverage["warnings"],
        errors=[],
        data_quality_status=(
            "MANUAL_REVIEW_REQUIRED" if coverage["warnings"] else "VALID_DATA"
        ),
        manifest_dir=manifest_dir,
        finished_at=resolved_fetch_time,
        notes="raw market price ingestion completed",
    )

    status = "SUCCESS_WITH_WARNINGS" if coverage["warnings"] else "SUCCESS"
    return {
        "status": status,
        "run_id": resolved_run_id,
        "mode": mode,
        "raw_output_path": raw_output_path,
        "manifest_path": manifest_path,
        "coverage_report_path": coverage_report_path,
        "ticker_log_path": ticker_log_path,
        "coverage": coverage,
        "validation_result": validation,
        "errors": [],
        "warnings": coverage["warnings"],
    }


def standardize_market_price_raw(
    df: pd.DataFrame, mode: str, fetch_time: str | None = None
) -> pd.DataFrame:
    """Return standardized market raw data without filling missing prices."""

    output = _copy_with_output_columns(df, MARKET_PRICE_OUTPUT_COLUMNS)
    output["ticker"] = output["ticker"].map(_normalize_ticker)
    output["date"] = output["date"].map(_clean_text)

    for column in ["open", "high", "low", "close", "volume", "trading_value"]:
        output[column] = pd.to_numeric(output[column], errors="coerce")

    output["source"] = output["source"].map(_clean_text)
    output["source_url"] = output["source_url"].map(_clean_text)
    output["fetch_time"] = _fill_missing_text(
        output["fetch_time"], fetch_time or _utc_now_iso()
    )
    output["confidence_raw"] = _fill_missing_text(
        output["confidence_raw"], _confidence_for_mode(mode)
    )
    output["notes"] = _fill_missing_text(
        output["notes"], _notes_for_mode(mode)
    )
    return output[MARKET_PRICE_OUTPUT_COLUMNS]


def build_market_price_coverage(
    *,
    market_raw: pd.DataFrame,
    requested_tickers: list[str] | None = None,
    stale_reference_date: str | None = None,
    stale_after_days: int = 370,
) -> dict[str, Any]:
    """Build coverage and warning summary for market ingestion."""

    normalized_requested = _normalize_requested_tickers(requested_tickers)
    present_tickers = _ticker_set(market_raw)
    requested_set = set(normalized_requested) if normalized_requested else present_tickers
    failed_tickers = sorted(requested_set - present_tickers)
    stale_tickers = _stale_tickers(
        market_raw=market_raw,
        reference_date=stale_reference_date,
        stale_after_days=stale_after_days,
    )

    coverage = {
        "ticker_count_requested": len(requested_set),
        "ticker_count_success": len(requested_set.intersection(present_tickers)),
        "ticker_count_failed": len(failed_tickers),
        "failed_tickers": failed_tickers,
        "row_count": int(len(market_raw)),
        "min_date": _min_date(market_raw),
        "max_date": _max_date(market_raw),
        "missing_close_count": _missing_count(market_raw, "close"),
        "missing_volume_count": _missing_count(market_raw, "volume"),
        "missing_trading_value_count": _missing_count(market_raw, "trading_value"),
        "stale_ticker_count": len(stale_tickers),
        "stale_tickers": stale_tickers,
        "duplicate_row_count": _duplicate_ticker_date_count(market_raw),
        "negative_volume_count": _negative_count(market_raw, "volume"),
        "negative_trading_value_count": _negative_count(market_raw, "trading_value"),
        "invalid_price_count": _invalid_price_count(market_raw),
        "warnings": [],
    }

    if coverage["ticker_count_failed"]:
        coverage["warnings"].append("FAILED_TICKERS_PRESENT")
    if coverage["missing_close_count"]:
        coverage["warnings"].append("MISSING_CLOSE")
    if coverage["missing_volume_count"]:
        coverage["warnings"].append("MISSING_VOLUME")
    if coverage["missing_trading_value_count"]:
        coverage["warnings"].append("MISSING_TRADING_VALUE")
    if coverage["duplicate_row_count"]:
        coverage["warnings"].append("DUPLICATE_TICKER_DATE")
    if coverage["negative_volume_count"]:
        coverage["warnings"].append("NEGATIVE_VOLUME")
    if coverage["negative_trading_value_count"]:
        coverage["warnings"].append("NEGATIVE_TRADING_VALUE")
    if coverage["invalid_price_count"]:
        coverage["warnings"].append("INVALID_PRICE")
    if coverage["stale_ticker_count"]:
        coverage["warnings"].append("STALE_DATA")

    coverage["warnings"] = _dedupe(coverage["warnings"])
    return coverage


def build_market_price_ticker_log(
    *,
    market_raw: pd.DataFrame,
    requested_tickers: list[str] | None = None,
    coverage: dict[str, Any] | None = None,
    validation_failed: bool = False,
) -> pd.DataFrame:
    """Return ticker-level success/failure/manual-review log."""

    normalized_requested = _normalize_requested_tickers(requested_tickers)
    present_tickers = _ticker_set(market_raw)
    ticker_order = normalized_requested or sorted(present_tickers)
    if not ticker_order:
        ticker_order = sorted(present_tickers)

    stale_tickers = set((coverage or {}).get("stale_tickers", []))
    failed_tickers = set((coverage or {}).get("failed_tickers", []))
    rows: list[dict[str, Any]] = []

    for ticker in ticker_order:
        ticker_rows = _rows_for_ticker(market_raw, ticker)
        warnings = _warnings_for_ticker(ticker_rows)
        if ticker in stale_tickers:
            warnings.append("STALE_DATA")

        if validation_failed:
            status = "FAILED"
            failure_reason = "VALIDATION_FAILED"
        elif ticker in failed_tickers or ticker_rows.empty:
            status = "FAILED"
            failure_reason = "NO_ROWS_FOR_REQUESTED_TICKER"
        elif warnings:
            status = "MANUAL_REVIEW"
            failure_reason = ""
        else:
            status = "SUCCESS"
            failure_reason = ""

        rows.append(
            {
                "ticker": ticker,
                "status": status,
                "row_count": int(len(ticker_rows)),
                "failure_reason": failure_reason,
                "warnings": "|".join(_dedupe(warnings)),
            }
        )

    return pd.DataFrame(rows, columns=TICKER_LOG_COLUMNS)


def save_market_price_raw(
    *,
    market_raw: pd.DataFrame,
    raw_output_dir: str | Path = DEFAULT_RAW_OUTPUT_DIR,
) -> str:
    """Save raw market price rows and return the output path."""

    output_dir = Path(raw_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / MARKET_PRICE_RAW_FILENAME
    market_raw.to_csv(output_path, index=False)
    return str(output_path)


def save_coverage_report(
    *,
    coverage: dict[str, Any],
    run_id: str,
    coverage_output_dir: str | Path = DEFAULT_COVERAGE_OUTPUT_DIR,
) -> str:
    """Save market coverage JSON and return the output path."""

    output_dir = Path(coverage_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{_safe_file_token(run_id)}_market_price_coverage.json"
    output_path.write_text(
        json.dumps(coverage, indent=2, sort_keys=True), encoding="utf-8"
    )
    return str(output_path)


def save_ticker_log(
    *,
    ticker_log: pd.DataFrame,
    run_id: str,
    ticker_log_dir: str | Path = DEFAULT_TICKER_LOG_DIR,
) -> str:
    """Save ticker-level success/failure log and return the output path."""

    output_dir = Path(ticker_log_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{_safe_file_token(run_id)}_market_price_ticker_log.csv"
    ticker_log.to_csv(output_path, index=False)
    return str(output_path)


def has_prohibited_recommendation_columns(df: pd.DataFrame) -> bool:
    """Return True if raw market output contains prohibited recommendation fields."""

    normalized_columns = {str(column).strip().lower() for column in df.columns}
    return bool(PROHIBITED_RECOMMENDATION_FIELDS.intersection(normalized_columns))


def _load_input(
    *,
    mode: str,
    input_path: str | Path | None,
    fetch_time: str,
    requested_tickers: list[str],
) -> pd.DataFrame:
    if mode == "mock":
        return _mock_market_price_rows(fetch_time=fetch_time, tickers=requested_tickers)

    if input_path is None:
        raise ValueError(f"input_path is required for {mode} mode.")

    path = Path(input_path)
    if mode == "manual_csv":
        return pd.read_csv(path)
    if mode == "manual_xlsx":
        return pd.read_excel(path)

    raise ValueError(f"Unsupported mode: {mode}")


def _mock_market_price_rows(fetch_time: str, tickers: list[str]) -> pd.DataFrame:
    requested = tickers or ["MOCK1", "MOCK2"]
    rows: list[dict[str, Any]] = []
    for index, ticker in enumerate(requested, start=1):
        base_price = 100 + index
        volume = 1000 * index
        rows.append(
            {
                "ticker": ticker,
                "date": "2026-01-01",
                "open": base_price - 1,
                "high": base_price + 1,
                "low": base_price - 2,
                "close": base_price,
                "volume": volume,
                "trading_value": base_price * volume,
                "source": "MOCK_SAMPLE",
                "source_url": f"mock://market_price/{ticker}",
                "fetch_time": fetch_time,
                "confidence_raw": "mock",
                "notes": "mock/sample data only; not real Vietnamese stock data",
            }
        )
    return pd.DataFrame(rows)


def _real_source_unavailable_result(
    *,
    run_id: str,
    requested_tickers: list[str],
    manifest_dir: str | Path,
    ticker_log_dir: str | Path,
    fetch_time: str,
) -> dict[str, Any]:
    ticker_log = pd.DataFrame(
        [
            {
                "ticker": ticker,
                "status": "FAILED",
                "row_count": 0,
                "failure_reason": REAL_SOURCE_UNAVAILABLE,
                "warnings": REAL_SOURCE_UNAVAILABLE,
            }
            for ticker in requested_tickers
        ],
        columns=TICKER_LOG_COLUMNS,
    )
    ticker_log_path = save_ticker_log(
        ticker_log=ticker_log,
        run_id=run_id,
        ticker_log_dir=ticker_log_dir,
    )
    manifest = create_ingestion_manifest_record(
        run_id=run_id,
        dataset_name="market_price",
        mode="real_vnstock_optional",
        started_at=fetch_time,
        finished_at=fetch_time,
        failed_count=max(1, len(requested_tickers)),
        errors=[REAL_SOURCE_UNAVAILABLE],
        data_quality_status=REAL_SOURCE_UNAVAILABLE,
        notes=(
            "Optional real vnstock adapter is not implemented or unavailable; "
            "no live data was fetched."
        ),
    )
    manifest_path = save_ingestion_manifest(manifest, output_dir=manifest_dir)
    return {
        "status": REAL_SOURCE_UNAVAILABLE,
        "run_id": run_id,
        "mode": "real_vnstock_optional",
        "raw_output_path": "",
        "manifest_path": manifest_path,
        "coverage_report_path": "",
        "ticker_log_path": ticker_log_path,
        "coverage": {},
        "validation_result": {},
        "errors": [REAL_SOURCE_UNAVAILABLE],
        "warnings": ["Optional real source unavailable; no live data fetched."],
    }


def _write_manifest(
    *,
    run_id: str,
    mode: str,
    input_path: str,
    output_path: str,
    df: pd.DataFrame,
    success_count: int,
    failed_count: int,
    missing_required_columns: list[str],
    warnings: list[str],
    errors: list[str],
    data_quality_status: str,
    manifest_dir: str | Path,
    finished_at: str,
    notes: str,
) -> str:
    record = create_ingestion_manifest_record(
        run_id=run_id,
        dataset_name="market_price",
        mode=mode,
        input_path=input_path,
        output_path=output_path,
        started_at=finished_at,
        finished_at=finished_at,
        row_count=int(len(df)),
        ticker_count=len(_ticker_set(df)),
        success_count=success_count,
        failed_count=failed_count,
        missing_required_columns=missing_required_columns,
        warnings=warnings,
        errors=errors,
        data_quality_status=data_quality_status,
        notes=notes,
    )
    return save_ingestion_manifest(record, output_dir=manifest_dir)


def _warnings_for_ticker(ticker_rows: pd.DataFrame) -> list[str]:
    if ticker_rows.empty:
        return []

    warnings: list[str] = []
    if _missing_count(ticker_rows, "close"):
        warnings.append("MISSING_CLOSE")
    if _missing_count(ticker_rows, "volume"):
        warnings.append("MISSING_VOLUME")
    if _missing_count(ticker_rows, "trading_value"):
        warnings.append("MISSING_TRADING_VALUE")
    if _duplicate_ticker_date_count(ticker_rows):
        warnings.append("DUPLICATE_TICKER_DATE")
    if _negative_count(ticker_rows, "volume"):
        warnings.append("NEGATIVE_VOLUME")
    if _negative_count(ticker_rows, "trading_value"):
        warnings.append("NEGATIVE_TRADING_VALUE")
    if _invalid_price_count(ticker_rows):
        warnings.append("INVALID_PRICE")
    return warnings


def _rows_for_ticker(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if "ticker" not in df.columns:
        return pd.DataFrame(columns=df.columns)
    return df[df["ticker"].map(_normalize_ticker) == ticker].copy()


def _stale_tickers(
    *,
    market_raw: pd.DataFrame,
    reference_date: str | None,
    stale_after_days: int,
) -> list[str]:
    if not reference_date or "date" not in market_raw.columns or market_raw.empty:
        return []

    reference = pd.to_datetime(reference_date, errors="coerce")
    if pd.isna(reference):
        return []

    stale: list[str] = []
    for ticker, rows in market_raw.groupby("ticker", dropna=False):
        normalized_ticker = _normalize_ticker(ticker)
        if not normalized_ticker:
            continue
        dates = pd.to_datetime(rows["date"], errors="coerce").dropna()
        if dates.empty:
            stale.append(normalized_ticker)
            continue
        age_days = (reference - dates.max()).days
        if age_days > stale_after_days:
            stale.append(normalized_ticker)
    return sorted(stale)


def _missing_count(df: pd.DataFrame, column: str) -> int:
    if column not in df.columns:
        return int(len(df))
    return int(df[column].map(_is_missing).sum())


def _negative_count(df: pd.DataFrame, column: str) -> int:
    if column not in df.columns:
        return 0
    numeric = pd.to_numeric(df[column], errors="coerce")
    return int((numeric < 0).sum())


def _invalid_price_count(df: pd.DataFrame) -> int:
    count = 0
    for column in ["open", "high", "low", "close"]:
        if column not in df.columns:
            continue
        numeric = pd.to_numeric(df[column], errors="coerce")
        count += int((numeric.dropna() <= 0).sum())
    return count


def _duplicate_ticker_date_count(df: pd.DataFrame) -> int:
    if not {"ticker", "date"}.issubset(df.columns):
        return 0
    normalized = df.copy()
    normalized["ticker"] = normalized["ticker"].map(_normalize_ticker)
    normalized["date"] = normalized["date"].map(_clean_text)
    duplicate_mask = normalized.duplicated(subset=["ticker", "date"], keep=False)
    return int(duplicate_mask.sum())


def _ticker_set(df: pd.DataFrame) -> set[str]:
    if "ticker" not in df.columns:
        return set()
    return {ticker for ticker in df["ticker"].map(_normalize_ticker) if ticker}


def _min_date(df: pd.DataFrame) -> str:
    if "date" not in df.columns or df.empty:
        return ""
    dates = pd.to_datetime(df["date"], errors="coerce").dropna()
    if dates.empty:
        return ""
    return str(dates.min().date())


def _max_date(df: pd.DataFrame) -> str:
    if "date" not in df.columns or df.empty:
        return ""
    dates = pd.to_datetime(df["date"], errors="coerce").dropna()
    if dates.empty:
        return ""
    return str(dates.max().date())


def _copy_with_output_columns(df: pd.DataFrame, output_columns: list[str]) -> pd.DataFrame:
    output = df.copy(deep=True)
    for column in output_columns:
        if column not in output.columns:
            output[column] = pd.NA
    return output[output_columns].copy()


def _fill_missing_text(series: pd.Series, default: str) -> pd.Series:
    cleaned = series.map(_clean_text)
    return cleaned.where(cleaned.map(bool), default)


def _normalize_requested_tickers(tickers: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for ticker in tickers or []:
        normalized_ticker = _normalize_ticker(ticker)
        if normalized_ticker and normalized_ticker not in normalized:
            normalized.append(normalized_ticker)
    return normalized


def _confidence_for_mode(mode: str) -> str:
    if mode == "mock":
        return "mock"
    return "medium"


def _notes_for_mode(mode: str) -> str:
    if mode == "mock":
        return "mock/sample data only; not real Vietnamese stock data"
    return "manual market price input; requires downstream validation"


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
    return f"market_price_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"


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
