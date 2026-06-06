"""REAL-DATA-01I finance web source probing and adapter layer."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingestion.finance_candidate_normalizer import (
    FINANCE_01I_CANDIDATE_COLUMNS,
    load_finance_alias_config,
    normalize_finance_statement_rows,
)
from src.ingestion.source_adapter_contracts import (
    SOURCE_ADAPTER_DIAGNOSTIC_COLUMNS,
    SOURCE_PROBE_COLUMNS,
    SOURCE_SCHEMA_DIAGNOSTIC_COLUMNS,
)
from src.ingestion.source_snapshot import fetch_public_snapshot, probe_status_from_snapshot, snapshot_metadata_row

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def load_finance_web_sources(path: str | Path = "config/finance_web_sources.yaml") -> dict[str, Any]:
    if yaml is None:
        raise ImportError("PyYAML is required to load finance web sources.")
    with Path(path).open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise ValueError("finance web sources config must be a mapping.")
    return data


def run_finance_source_probes(
    *,
    tickers: list[str],
    sources: list[str],
    periods: list[str],
    output_snapshot_dir: str | Path,
    request_sleep_seconds: float = 0,
    vnstock_max_workers: int = 1,
    source_probe_max_workers: int = 4,
    source_config: dict[str, Any] | None = None,
    alias_config: dict[str, Any] | None = None,
) -> dict[str, pd.DataFrame]:
    config = source_config or load_finance_web_sources()
    aliases = alias_config or load_finance_alias_config()
    candidates: list[pd.DataFrame] = []
    probes: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    schemas: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []

    discovery_jobs = []
    for source in [_clean_source(item) for item in sources if _clean_source(item)]:
        settings = dict(config.get("sources", {}).get(source, {}))
        if not settings:
            probes.append(_probe_row(source, source, "SOURCE_SCHEMA_UNKNOWN", "", False, "", "source is not configured"))
            continue
        if source == "vnstock":
            result = _run_vnstock_adapter(
                tickers=tickers,
                periods=periods,
                settings=settings,
                aliases=aliases,
                request_sleep_seconds=request_sleep_seconds,
                max_workers=vnstock_max_workers,
            )
            candidates.append(result["candidates"])
            probes.extend(result["probes"])
            diagnostics.extend(result["diagnostics"])
            schemas.extend(result["schemas"])
            continue
        discovery_jobs.append(settings)

    with ThreadPoolExecutor(max_workers=max(1, int(source_probe_max_workers))) as executor:
        futures = [
            executor.submit(_run_discovery_adapter, tickers=tickers, settings=settings, snapshot_dir=output_snapshot_dir)
            for settings in discovery_jobs
        ]
        for future in as_completed(futures):
            result = future.result()
            probes.extend(result["probes"])
            diagnostics.extend(result["diagnostics"])
            schemas.extend(result["schemas"])
            snapshots.extend(result["snapshots"])

    return {
        "finance_source_probe_matrix": pd.DataFrame(probes, columns=SOURCE_PROBE_COLUMNS),
        "finance_adapter_diagnostics": pd.DataFrame(diagnostics, columns=SOURCE_ADAPTER_DIAGNOSTIC_COLUMNS),
        "finance_schema_diagnostics": pd.DataFrame(schemas, columns=SOURCE_SCHEMA_DIAGNOSTIC_COLUMNS),
        "finance_raw_candidate_rows": _concat_or_empty(candidates, FINANCE_01I_CANDIDATE_COLUMNS),
        "source_snapshot_metadata": pd.DataFrame(snapshots),
    }


def _run_vnstock_adapter(
    *,
    tickers: list[str],
    periods: list[str],
    settings: dict[str, Any],
    aliases: dict[str, Any],
    request_sleep_seconds: float,
    max_workers: int = 1,
) -> dict[str, Any]:
    source_category = str(settings.get("source_category", "vnstock"))
    source_name = str(settings.get("source_name", "vnstock:vci:finance"))
    source_url = str(settings.get("source_url", "https://vnstocks.com/"))
    parser_name = str(settings.get("parser_name", "vnstock_finance_wide_statement"))
    has_vnstock = importlib.util.find_spec("vnstock") is not None
    probes = [
        _probe_row(
            source_name,
            source_category,
            "SOURCE_AVAILABLE" if has_vnstock else "SOURCE_UNAVAILABLE",
            "",
            has_vnstock,
            source_url,
            "vnstock package dependency available" if has_vnstock else "vnstock package dependency unavailable",
        )
    ]
    if not has_vnstock:
        return {"candidates": pd.DataFrame(columns=FINANCE_01I_CANDIDATE_COLUMNS), "probes": probes, "diagnostics": [], "schemas": []}

    candidate_frames = []
    diagnostics = []
    schemas = []
    ordered_tickers = _ordered_tickers(tickers)

    def fetch_one(ticker: str) -> tuple[str, dict[str, Any]]:
        return ticker, _run_vnstock_worker(
            ticker=ticker,
            periods=periods,
            request_sleep_seconds=request_sleep_seconds,
        )

    with ThreadPoolExecutor(max_workers=max(1, int(max_workers))) as executor:
        futures = {executor.submit(fetch_one, ticker): ticker for ticker in ordered_tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                _, worker = future.result()
            except VnstockWorkerError as exc:
                diagnostics.append(_diagnostic_row(source_name, source_category, ticker, exc.status, 0, exc.error, source_url, "vnstock worker failed; missing data remains missing"))
                schemas.append(_schema_row(source_name, source_category, ticker, source_url, exc.status, "", "|".join(_canonical_fields()), "", exc.error))
                continue
            except Exception as exc:  # noqa: BLE001
                status = _status_from_exception(exc)
                error = f"{type(exc).__name__}:{exc}"
                diagnostics.append(_diagnostic_row(source_name, source_category, ticker, status, 0, error, source_url, "vnstock worker raised an unhandled exception"))
                schemas.append(_schema_row(source_name, source_category, ticker, source_url, status, "", "|".join(_canonical_fields()), "", error))
                continue
            candidate_df = pd.DataFrame(worker["candidate_rows"], columns=FINANCE_01I_CANDIDATE_COLUMNS)
            schema_df = pd.DataFrame(worker["schema_rows"])
            candidate_frames.append(candidate_df)
            diagnostics.append(
                _diagnostic_row(
                    source_name,
                    source_category,
                    ticker,
                    "ROWS_PARSED" if not candidate_df.empty else "SOURCE_SCHEMA_UNKNOWN",
                    len(candidate_df),
                    "",
                    source_url,
                    "finance rows parsed from explicit source labels" if not candidate_df.empty else "no requested-period fields mapped",
                )
            )
            schemas.extend(_schema_rows_from_normalizer(schema_df, source_name, source_category, source_url))
    return {
        "candidates": _concat_or_empty(candidate_frames, FINANCE_01I_CANDIDATE_COLUMNS),
        "probes": probes,
        "diagnostics": diagnostics,
        "schemas": schemas,
    }


def _run_discovery_adapter(*, tickers: list[str], settings: dict[str, Any], snapshot_dir: str | Path) -> dict[str, Any]:
    source_category = str(settings.get("source_category", ""))
    source_name = str(settings.get("source_name", source_category))
    template = str(settings.get("source_url_template", ""))
    parser_name = str(settings.get("parser_name", "finance_discovery"))
    probes = []
    diagnostics = []
    schemas = []
    snapshots = []
    if not template:
        probes.append(_probe_row(source_name, source_category, "SOURCE_SCHEMA_UNKNOWN", "", False, "", "no public URL template configured; source-backed manual discovery required"))
        diagnostics.append(_diagnostic_row(source_name, source_category, "", "SOURCE_SCHEMA_UNKNOWN", 0, "", "", "no automated URL template configured"))
        schemas.append(_schema_row(source_name, source_category, "", "", "SOURCE_SCHEMA_UNKNOWN", "", "|".join(_canonical_fields()), "", "no parser can safely extract finance rows yet"))
        return {"probes": probes, "diagnostics": diagnostics, "schemas": schemas, "snapshots": snapshots}

    sample_ticker = _ordered_tickers(tickers)[0] if _ordered_tickers(tickers) else ""
    sample_url = template.format(ticker=sample_ticker)
    result = fetch_public_snapshot(
        url=sample_url,
        snapshot_dir=snapshot_dir,
        source_name=source_name,
        source_category=source_category,
        parser_used=parser_name,
    )
    status = probe_status_from_snapshot(result)
    snapshots.append(
        snapshot_metadata_row(
            result=result,
            source_name=source_name,
            source_category=source_category,
            parser_used=parser_name,
            parse_status=status,
            notes="01I discovery snapshot; no numeric parsing unless schema is deterministic",
        )
    )
    probes.append(_probe_row(source_name, source_category, status, result.status_code or result.error, status == "SOURCE_AVAILABLE", sample_url, "web source probed; schema parser not yet trusted"))
    diagnostics.append(_diagnostic_row(source_name, source_category, sample_ticker, "SOURCE_SCHEMA_UNKNOWN" if status == "SOURCE_AVAILABLE" else status, 0, result.status_code or result.error, sample_url, "source probed but no deterministic finance parser emitted rows"))
    schemas.append(_schema_row(source_name, source_category, sample_ticker, sample_url, "SOURCE_SCHEMA_UNKNOWN" if status == "SOURCE_AVAILABLE" else status, "", "|".join(_canonical_fields()), "", "no candidate finance values parsed"))
    return {"probes": probes, "diagnostics": diagnostics, "schemas": schemas, "snapshots": snapshots}


class VnstockWorkerError(Exception):
    def __init__(self, status: str, error: str) -> None:
        super().__init__(error)
        self.status = status
        self.error = error


def _run_vnstock_worker(*, ticker: str, periods: list[str], request_sleep_seconds: float) -> dict[str, Any]:
    root_dir = Path(__file__).resolve().parents[2]
    command = [
        sys.executable,
        str(root_dir / "scripts" / "vnstock_finance_01i_worker.py"),
        "--ticker",
        ticker,
        "--periods",
        ",".join(periods),
        "--request-sleep-seconds",
        str(request_sleep_seconds),
    ]
    completed = subprocess.run(
        command,
        cwd=root_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(180, int(75 + request_sleep_seconds * 5)),
        check=False,
    )
    combined = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode != 0:
        raise VnstockWorkerError(_status_from_text(combined), combined[-2000:])
    start = combined.find("__01I_JSON_START__")
    end = combined.find("__01I_JSON_END__")
    if start < 0 or end < 0:
        raise VnstockWorkerError(_status_from_text(combined), combined[-2000:])
    json_text = combined[start + len("__01I_JSON_START__") : end].strip()
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise VnstockWorkerError("SOURCE_PARSE_FAILED", f"worker JSON parse failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise VnstockWorkerError("SOURCE_PARSE_FAILED", "worker payload is not a mapping")
    return payload


def _schema_rows_from_normalizer(df: pd.DataFrame, source_name: str, source_category: str, source_url: str) -> list[dict[str, Any]]:
    rows = []
    for _, row in df.iterrows():
        rows.append(
            _schema_row(
                source_name,
                source_category,
                row.get("ticker", ""),
                source_url,
                row.get("schema_status", ""),
                row.get("detected_fields", ""),
                row.get("unsupported_fields", ""),
                row.get("raw_labels", ""),
                row.get("notes", ""),
            )
        )
    return rows


def _probe_row(source_name: str, source_category: str, status: str, error: Any, accessible: bool, sample_url: str, notes: str) -> dict[str, Any]:
    return {
        "source_name": source_name,
        "source_category": source_category,
        "dataset_name": "financial_statement_summary",
        "probe_status": status,
        "http_status_or_error": error,
        "is_accessible": bool(accessible),
        "requires_js": status == "SOURCE_BLOCKED_OR_JS_REQUIRED",
        "requires_login": False,
        "blocked_or_captcha": status == "SOURCE_BLOCKED_OR_JS_REQUIRED",
        "schema_detected": status == "SOURCE_AVAILABLE",
        "supported_fields": "|".join(_canonical_fields()) if accessible else "",
        "unsupported_fields": "missing fields remain missing",
        "sample_url": sample_url,
        "notes": notes,
    }


def _diagnostic_row(source_name: str, source_category: str, ticker: str, status: str, row_count: int, error: Any, source_url: str, notes: str) -> dict[str, Any]:
    return {
        "source_name": source_name,
        "source_category": source_category,
        "dataset_name": "financial_statement_summary",
        "ticker": _clean_ticker(ticker),
        "action": "fetch_finance",
        "status": status,
        "row_count": int(row_count),
        "http_status_or_error": error,
        "source_url": source_url,
        "notes": notes,
    }


def _schema_row(source_name: str, source_category: str, ticker: str, source_url: str, status: str, detected: Any, unsupported: Any, labels: Any, notes: str) -> dict[str, Any]:
    return {
        "source_name": source_name,
        "source_category": source_category,
        "dataset_name": "financial_statement_summary",
        "ticker": _clean_ticker(ticker),
        "source_url": source_url,
        "schema_status": status,
        "detected_fields": detected,
        "unsupported_fields": unsupported,
        "raw_labels": labels,
        "notes": notes,
    }


def _status_from_exception(exc: Exception) -> str:
    text = f"{type(exc).__name__}:{exc}".lower()
    if "rate" in text or "429" in text:
        return "SOURCE_RATE_LIMITED"
    if "charting library" in text or "importerror" in text:
        return "SOURCE_PARSE_FAILED"
    if "empty" in text:
        return "SOURCE_EMPTY_RESPONSE"
    return "SOURCE_PARSE_FAILED"


def _status_from_text(text: str) -> str:
    lower = text.lower()
    if "rate limit" in lower or "gioi han api" in lower or "giới hạn api" in lower or "429" in lower:
        return "SOURCE_RATE_LIMITED"
    if "captcha" in lower or "blocked" in lower:
        return "SOURCE_BLOCKED_OR_JS_REQUIRED"
    if "empty" in lower:
        return "SOURCE_EMPTY_RESPONSE"
    if "schema" in lower:
        return "SOURCE_SCHEMA_UNKNOWN"
    return "SOURCE_PARSE_FAILED"


def _concat_or_empty(frames: list[pd.DataFrame], columns: list[str]) -> pd.DataFrame:
    valid = [frame for frame in frames if isinstance(frame, pd.DataFrame) and not frame.empty]
    if not valid:
        return pd.DataFrame(columns=columns)
    output = pd.concat(valid, ignore_index=True)
    for column in columns:
        if column not in output.columns:
            output[column] = ""
    return output[columns]


def _ordered_tickers(tickers: list[str]) -> list[str]:
    output = []
    for ticker in tickers:
        cleaned = _clean_ticker(ticker)
        if cleaned and cleaned not in output:
            output.append(cleaned)
    return output


def _canonical_fields() -> list[str]:
    return [
        "revenue",
        "gross_profit",
        "operating_profit",
        "net_profit",
        "total_assets",
        "total_liabilities",
        "equity",
        "cash",
        "short_term_debt",
        "long_term_debt",
        "operating_cash_flow",
        "inventory",
    ]


def _clean_source(value: Any) -> str:
    return str(value).strip().lower()


def _clean_ticker(value: Any) -> str:
    return str(value).strip().upper()


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
