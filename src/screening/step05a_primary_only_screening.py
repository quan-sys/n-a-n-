"""STEP05A primary-only screening mode.

This step is intentionally conservative: it reads existing primary market and
provisional structured finance artifacts, applies basic availability filters,
and exports a manual BCTC review queue. It does not fetch new data.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


STEP_ID = "STEP05A-PRIMARY-ONLY-SCREENING-MODE"
MODE = "primary_only_screening"

SCREENING_STATUSES = {
    "BLOCKED_INSUFFICIENT_MARKET_DATA",
    "BLOCKED_STALE_MARKET_DATA",
    "BLOCKED_TOO_ILLIQUID",
    "BLOCKED_MISSING_MINIMUM_FINANCE",
    "PASS_PRELIMINARY_FILTER",
    "WATCHLIST_CANDIDATE",
    "NEEDS_MANUAL_BCTC_REVIEW",
}

CONFIDENCE_VALUES = {
    "PROVISIONAL_PRIMARY_ONLY",
    "PROVISIONAL_LOW",
    "NOT_AVAILABLE",
    "NEEDS_MANUAL_BCTC_REVIEW",
}

FINAL_DECISIONS = {
    "PASS_PRIMARY_ONLY_SCREENING_WITH_WARNINGS",
    "CONDITIONAL_GO_FOR_MANUAL_BCTC_REVIEW",
    "BLOCKED_NO_USABLE_PRIMARY_DATA",
}

FORBIDDEN_FINAL_DECISIONS = {
    "PASS_FOR_INVESTMENT",
    "PASS_FOR_VALUATION",
    "PASS_FOR_RECOMMENDATION",
}

FORBIDDEN_TERMS = [
    "buy",
    "sell",
    "hold",
    "target price",
    "fair value",
    "margin of safety",
    "undervalued",
    "overvalued",
    "cheap",
    "expensive",
    "recommendation",
    "investment-ready",
    "valuation",
    "expected return",
    "upside",
    "downside",
]

DEFAULT_FINANCE_FIELDS = [
    "revenue",
    "gross_profit",
    "net_income",
    "total_assets",
    "total_liabilities",
    "equity",
    "cfo",
    "capex",
]

ROW_COLUMNS = [
    "ticker",
    "screening_status",
    "market_source_confidence",
    "finance_source_confidence",
    "crosscheck_status",
    "verification_status",
    "manual_review_required",
    "manual_bctc_required",
    "independent_market_crosscheck_required_later",
    "finance_crosscheck_required_later",
    "evidence_debt_reason",
    "missing_fields",
    "block_reasons",
    "reason_to_review",
    "last_price_date",
    "last_close",
    "avg_volume_20d",
    "avg_volume_60d",
    "last_volume",
    "stale_days",
    "trading_days_60d",
    "recent_trading_value",
    "market_fetch_status",
    "finance_missing_fields",
    "finance_quality_status",
    "finance_source_layer",
]

QUEUE_COLUMNS = [
    "ticker",
    "screening_status",
    "reason_to_review",
    "missing_fields",
    "market_source_confidence",
    "finance_source_confidence",
    "crosscheck_status",
    "verification_status",
    "manual_bctc_required",
    "evidence_debt_reason",
]


class Step05ASafeRunBlocked(RuntimeError):
    """Raised when a requested run violates STEP05A scope controls."""


@dataclass
class Step05AResult:
    rows: pd.DataFrame
    watchlist_candidates: pd.DataFrame
    manual_bctc_review_queue: pd.DataFrame
    blocked_tickers: pd.DataFrame
    evidence_debt_report: dict[str, Any]
    run_manifest: dict[str, Any]
    summary: dict[str, Any]


def load_step05a_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("STEP05A config must be a mapping.")
    return data


def run_step05a_primary_only_screening(
    *,
    config_path: str | Path,
    output_dir: str | Path | None = None,
    limit: int | None = None,
    allow_partial: bool | None = None,
    request_full_universe: bool = False,
    command_used: str = "",
    core_output_paths: list[str | Path] | None = None,
) -> Step05AResult:
    config = load_step05a_config(config_path)
    validate_step05a_config(config)
    output = Path(output_dir or ((config.get("exports") or {}).get("output_dir") or "data/reports/step05a_primary_only_screening"))
    output.mkdir(parents=True, exist_ok=True)

    limits = config.get("limits") or {}
    if request_full_universe and not _as_bool(limits.get("full_universe_allowed", False)):
        raise Step05ASafeRunBlocked("Full-universe STEP05A run is blocked by config.")
    if _as_bool(limits.get("top500_allowed", False)):
        raise Step05ASafeRunBlocked("STEP05A config unexpectedly allows top500; keep this step capped.")

    max_tickers = int(limits.get("max_tickers", 100) or 100)
    requested_limit = max_tickers if limit is None else int(limit)
    effective_limit = min(requested_limit, max_tickers)
    warnings = []
    if requested_limit > max_tickers:
        warnings.append(f"Requested limit {requested_limit} capped to configured max {max_tickers}.")

    run_policy = config.get("run") or {}
    if allow_partial is not None:
        run_policy = dict(run_policy)
        run_policy["allow_partial"] = bool(allow_partial)

    core_paths = [Path(path) for path in (core_output_paths or config.get("core_output_watchlist", []))]
    before_hashes = _hashes(core_paths)
    inputs = config.get("inputs") or {}
    market = _read_csv(inputs.get("market_snapshot", ""))
    finance_wide = _read_csv(inputs.get("finance_latest_wide", ""))
    finance_quality = _read_csv(inputs.get("finance_quality_flags", ""))

    ticker_universe = _resolve_tickers(market, effective_limit)
    rows = build_primary_only_screening_rows(
        tickers=ticker_universe,
        market=market,
        finance_wide=finance_wide,
        finance_quality=finance_quality,
        config=config,
    )
    watchlist = rows[rows["screening_status"].eq("WATCHLIST_CANDIDATE")].copy() if not rows.empty else pd.DataFrame(columns=ROW_COLUMNS)
    manual_queue = rows[rows["manual_bctc_required"].map(_as_bool)].copy() if not rows.empty else pd.DataFrame(columns=ROW_COLUMNS)
    blocked = rows[rows["screening_status"].astype(str).str.startswith("BLOCKED_")].copy() if not rows.empty else pd.DataFrame(columns=ROW_COLUMNS)

    core_outputs_modified = before_hashes != _hashes(core_paths)
    output_files = write_step05a_outputs(
        output_dir=output,
        rows=rows,
        watchlist=watchlist,
        manual_queue=manual_queue,
        blocked=blocked,
        config=config,
        config_path=Path(config_path),
        requested_ticker_count=min(len(_market_tickers(market)), requested_limit),
        processed_ticker_count=len(rows),
        effective_limit=effective_limit,
        allow_partial=_as_bool(run_policy.get("allow_partial", True)),
        command_used=command_used,
        warnings=warnings,
        core_outputs_modified=core_outputs_modified,
    )
    forbidden_hits = scan_forbidden_terms(output)
    summary = build_summary(
        config=config,
        requested_ticker_count=min(len(_market_tickers(market)), requested_limit),
        rows=rows,
        watchlist=watchlist,
        manual_queue=manual_queue,
        blocked=blocked,
        warnings=warnings,
        forbidden_hits=forbidden_hits,
        core_outputs_modified=core_outputs_modified,
    )
    evidence_debt = build_evidence_debt_report(rows, summary)
    manifest = build_run_manifest(
        config=config,
        config_path=Path(config_path),
        output_dir=output,
        effective_limit=effective_limit,
        allow_partial=_as_bool(run_policy.get("allow_partial", True)),
        command_used=command_used,
        core_outputs_modified=core_outputs_modified,
        output_files=output_files,
    )
    _write_json(output / "primary_only_screening_summary.json", summary)
    _write_json(output / "evidence_debt_report.json", evidence_debt)
    _write_json(output / "run_manifest.json", manifest)
    forbidden_hits = scan_forbidden_terms(output)
    if forbidden_hits != summary["forbidden_terms_found"]:
        summary = build_summary(
            config=config,
            requested_ticker_count=min(len(_market_tickers(market)), requested_limit),
            rows=rows,
            watchlist=watchlist,
            manual_queue=manual_queue,
            blocked=blocked,
            warnings=warnings,
            forbidden_hits=forbidden_hits,
            core_outputs_modified=core_outputs_modified,
        )
        _write_json(output / "primary_only_screening_summary.json", summary)
    return Step05AResult(rows, watchlist, manual_queue, blocked, evidence_debt, manifest, summary)


def validate_step05a_config(config: dict[str, Any]) -> None:
    if config.get("step_id") != STEP_ID:
        raise ValueError(f"STEP05A config step_id must be {STEP_ID}.")
    safety = config.get("safety") if isinstance(config.get("safety"), dict) else {}
    required_safety = [
        "no_recommendation",
        "no_valuation",
        "no_target_price",
        "no_fair_value",
        "no_margin_of_safety",
        "no_zero_fill",
        "no_missing_finance_inference",
        "no_pdf_ocr",
        "no_official_bctc_scrape",
        "no_core_output_mutation",
        "no_stage_promotion_to_investment_ready",
    ]
    missing = [key for key in required_safety if safety.get(key) is not True]
    if missing:
        raise ValueError(f"STEP05A safety flags must be true: {','.join(missing)}")


def build_primary_only_screening_rows(
    *,
    tickers: list[str],
    market: pd.DataFrame,
    finance_wide: pd.DataFrame,
    finance_quality: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    market_by_ticker = _index_by_ticker(market)
    finance_by_ticker = _index_by_ticker(finance_wide)
    quality_by_ticker = _index_by_ticker(finance_quality)
    confidence = config.get("source_confidence") or {}
    filters = config.get("filters") or {}
    rows = []
    for ticker in tickers:
        market_row = market_by_ticker.get(ticker, {})
        finance_row = finance_by_ticker.get(ticker, {})
        quality_row = quality_by_ticker.get(ticker, {})
        missing_market_fields = _missing_market_fields(market_row)
        finance_missing = _finance_missing_fields(finance_row)
        status, block_reasons = _screening_status(market_row, finance_row, missing_market_fields, finance_missing, filters)
        is_candidate = status == "WATCHLIST_CANDIDATE"
        missing_fields = sorted(set(missing_market_fields + finance_missing))
        evidence_debt = [
            "No independent current market source-family confirmation.",
            "Financial data not checked against official BCTC.",
            "Primary-only screening result; human review required before later analysis.",
        ]
        reason_to_review = (
            "Survived primary-only preliminary filters; official BCTC/manual finance verification still required."
            if is_candidate
            else "; ".join(block_reasons)
        )
        rows.append(
            {
                "ticker": ticker,
                "screening_status": status,
                "market_source_confidence": confidence.get("market_source_confidence", "PROVISIONAL_PRIMARY_ONLY"),
                "finance_source_confidence": confidence.get("finance_source_confidence_default", "PROVISIONAL_LOW"),
                "crosscheck_status": confidence.get("crosscheck_status", "NOT_AVAILABLE"),
                "verification_status": confidence.get("verification_status", "NEEDS_MANUAL_BCTC_REVIEW"),
                "manual_review_required": bool(is_candidate),
                "manual_bctc_required": bool(is_candidate),
                "independent_market_crosscheck_required_later": True,
                "finance_crosscheck_required_later": True,
                "evidence_debt_reason": _json_list(evidence_debt),
                "missing_fields": _json_list(missing_fields),
                "block_reasons": _json_list(block_reasons),
                "reason_to_review": reason_to_review,
                "last_price_date": market_row.get("last_price_date", ""),
                "last_close": market_row.get("last_close", ""),
                "avg_volume_20d": market_row.get("avg_volume_20d", ""),
                "avg_volume_60d": market_row.get("avg_volume_60d", ""),
                "last_volume": market_row.get("last_volume", ""),
                "stale_days": market_row.get("stale_days", ""),
                "trading_days_60d": market_row.get("trading_days_60d", ""),
                "recent_trading_value": _recent_trading_value(market_row),
                "market_fetch_status": market_row.get("fetch_status", ""),
                "finance_missing_fields": _json_list(finance_missing),
                "finance_quality_status": quality_row.get("export_status", finance_row.get("source_confidence", "")),
                "finance_source_layer": finance_row.get("source_layer", ""),
            }
        )
    return pd.DataFrame(rows, columns=ROW_COLUMNS)


def write_step05a_outputs(
    *,
    output_dir: Path,
    rows: pd.DataFrame,
    watchlist: pd.DataFrame,
    manual_queue: pd.DataFrame,
    blocked: pd.DataFrame,
    config: dict[str, Any],
    config_path: Path,
    requested_ticker_count: int,
    processed_ticker_count: int,
    effective_limit: int,
    allow_partial: bool,
    command_used: str,
    warnings: list[str],
    core_outputs_modified: bool,
) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows.to_csv(output_dir / "primary_only_screening_rows.csv", index=False)
    watchlist.to_csv(output_dir / "watchlist_candidates.csv", index=False)
    manual_queue.reindex(columns=QUEUE_COLUMNS).to_csv(output_dir / "manual_bctc_review_queue.csv", index=False)
    blocked.to_csv(output_dir / "blocked_tickers.csv", index=False)
    summary = build_summary(
        config=config,
        requested_ticker_count=requested_ticker_count,
        rows=rows,
        watchlist=watchlist,
        manual_queue=manual_queue,
        blocked=blocked,
        warnings=warnings,
        forbidden_hits=[],
        core_outputs_modified=core_outputs_modified,
    )
    evidence_debt = build_evidence_debt_report(rows, summary)
    manifest = build_run_manifest(
        config=config,
        config_path=config_path,
        output_dir=output_dir,
        effective_limit=effective_limit,
        allow_partial=allow_partial,
        command_used=command_used,
        core_outputs_modified=core_outputs_modified,
        output_files=[],
    )
    _write_json(output_dir / "primary_only_screening_summary.json", summary)
    _write_json(output_dir / "evidence_debt_report.json", evidence_debt)
    _write_json(output_dir / "run_manifest.json", manifest)
    return [
        "primary_only_screening_summary.json",
        "primary_only_screening_rows.csv",
        "watchlist_candidates.csv",
        "manual_bctc_review_queue.csv",
        "blocked_tickers.csv",
        "evidence_debt_report.json",
        "run_manifest.json",
    ]


def build_summary(
    *,
    config: dict[str, Any],
    requested_ticker_count: int,
    rows: pd.DataFrame,
    watchlist: pd.DataFrame,
    manual_queue: pd.DataFrame,
    blocked: pd.DataFrame,
    warnings: list[str],
    forbidden_hits: list[str],
    core_outputs_modified: bool,
) -> dict[str, Any]:
    confidence = config.get("source_confidence") or {}
    if core_outputs_modified:
        final_decision = "BLOCKED_NO_USABLE_PRIMARY_DATA"
    elif rows.empty or len(watchlist) == 0:
        final_decision = "BLOCKED_NO_USABLE_PRIMARY_DATA"
    else:
        final_decision = "CONDITIONAL_GO_FOR_MANUAL_BCTC_REVIEW"
    if final_decision in FORBIDDEN_FINAL_DECISIONS:
        raise ValueError(f"Forbidden STEP05A final decision: {final_decision}")
    summary_warnings = list(warnings)
    summary_warnings.extend(
        [
            "Primary-only mode; no independent current source-family confirmation.",
            "Manual official BCTC review required before deeper company analysis.",
            "Finance layer remains provisional low.",
        ]
    )
    if core_outputs_modified:
        summary_warnings.append("Core output hash changed during STEP05A run.")
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "mode": MODE,
        "requested_ticker_count": int(requested_ticker_count),
        "processed_ticker_count": int(len(rows)),
        "blocked_count": int(len(blocked)),
        "watchlist_candidate_count": int(len(watchlist)),
        "manual_bctc_review_queue_count": int(len(manual_queue)),
        "market_source_confidence": confidence.get("market_source_confidence", "PROVISIONAL_PRIMARY_ONLY"),
        "finance_source_confidence_default": confidence.get("finance_source_confidence_default", "PROVISIONAL_LOW"),
        "crosscheck_status": confidence.get("crosscheck_status", "NOT_AVAILABLE"),
        "verification_status": confidence.get("verification_status", "NEEDS_MANUAL_BCTC_REVIEW"),
        "final_decision": final_decision,
        "warnings": summary_warnings,
        "safety_flags": {
            "no_trade_advice_label": True,
            "no_value_estimate": True,
            "no_price_objective": True,
            "no_missing_fill": True,
            "no_pdf_or_ocr": True,
            "no_stage_promotion": True,
        },
        "forbidden_terms_found": forbidden_hits,
    }


def build_evidence_debt_report(rows: pd.DataFrame, summary: dict[str, Any]) -> dict[str, Any]:
    missing_counter: dict[str, int] = {}
    for value in rows.get("missing_fields", pd.Series(dtype=str)).astype(str):
        for field in _parse_json_list(value):
            missing_counter[field] = missing_counter.get(field, 0) + 1
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "limitations": [
            "No independent current market source-family confirmation.",
            "Financial data not checked against official BCTC.",
            "Manual BCTC review required for surviving candidates.",
            "No trade-advice or value-estimate output produced.",
        ],
        "processed_ticker_count": int(summary.get("processed_ticker_count", 0)),
        "watchlist_candidate_count": int(summary.get("watchlist_candidate_count", 0)),
        "manual_bctc_review_queue_count": int(summary.get("manual_bctc_review_queue_count", 0)),
        "missing_field_counts": dict(sorted(missing_counter.items())),
        "crosscheck_status": summary.get("crosscheck_status", "NOT_AVAILABLE"),
        "market_source_confidence": summary.get("market_source_confidence", "PROVISIONAL_PRIMARY_ONLY"),
        "finance_source_confidence_default": summary.get("finance_source_confidence_default", "PROVISIONAL_LOW"),
    }


def build_run_manifest(
    *,
    config: dict[str, Any],
    config_path: Path,
    output_dir: Path,
    effective_limit: int,
    allow_partial: bool,
    command_used: str,
    core_outputs_modified: bool,
    output_files: list[str],
) -> dict[str, Any]:
    limits = config.get("limits") or {}
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "commit_hash": _git_commit_hash(),
        "command_used": command_used,
        "config_path": str(config_path),
        "output_dir": str(output_dir),
        "max_tickers": int(effective_limit),
        "allow_partial": bool(allow_partial),
        "full_universe_allowed": _as_bool(limits.get("full_universe_allowed", False)),
        "top500_allowed": _as_bool(limits.get("top500_allowed", False)),
        "network_usage_if_known": "none",
        "core_outputs_modified": bool(core_outputs_modified),
        "previous_step_outputs_mutated": bool(core_outputs_modified),
        "output_files": output_files,
    }


def scan_forbidden_terms(output_dir: Path) -> list[str]:
    hits = []
    for path in sorted(output_dir.glob("*")):
        if path.suffix.lower() not in {".csv", ".json", ".md", ".txt"}:
            continue
        text = _scan_text(path)
        for line_no, line in enumerate(text.splitlines(), start=1):
            lower = line.lower()
            for term in FORBIDDEN_TERMS:
                if term in lower:
                    hits.append(f"{path.name}:{line_no}:{term}")
    return hits


def _screening_status(
    market_row: dict[str, Any],
    finance_row: dict[str, Any],
    missing_market_fields: list[str],
    finance_missing: list[str],
    filters: dict[str, Any],
) -> tuple[str, list[str]]:
    block_reasons = []
    if not market_row or missing_market_fields or _as_bool(market_row.get("missing_market_flag", False)) or str(market_row.get("fetch_status", "")).upper() not in {"", "FETCH_OK"}:
        block_reasons.append("Primary market data missing or incomplete.")
        return "BLOCKED_INSUFFICIENT_MARKET_DATA", block_reasons
    stale_days = _to_float(market_row.get("stale_days"))
    stale_limit = float(filters.get("stale_price_max_days", 10) or 10)
    if _as_bool(market_row.get("stale_price_flag", False)) or (stale_days is not None and stale_days > stale_limit):
        block_reasons.append("Primary market data is stale.")
        return "BLOCKED_STALE_MARKET_DATA", block_reasons
    recent_volume = _first_number(market_row, ["avg_volume_20d", "last_volume", "avg_volume_60d"])
    min_volume = float(filters.get("min_recent_volume", 1) or 1)
    recent_value = _recent_trading_value(market_row)
    min_value = float(filters.get("min_recent_trading_value", 1) or 1)
    if recent_volume is None or recent_volume < min_volume or recent_value == "" or float(recent_value) < min_value:
        block_reasons.append("Primary market liquidity is below the configured floor.")
        return "BLOCKED_TOO_ILLIQUID", block_reasons
    if _as_bool(filters.get("require_minimum_finance_presence", False)):
        present_count = len(DEFAULT_FINANCE_FIELDS) - len(finance_missing)
        if not finance_row or present_count <= 0:
            block_reasons.append("Minimum provisional finance presence is missing.")
            return "BLOCKED_MISSING_MINIMUM_FINANCE", block_reasons
    return "WATCHLIST_CANDIDATE", block_reasons


def _missing_market_fields(row: dict[str, Any]) -> list[str]:
    required = ["ticker", "last_price_date", "last_close"]
    return [field for field in required if field not in row or _is_missing(row.get(field))]


def _finance_missing_fields(row: dict[str, Any]) -> list[str]:
    if not row:
        return list(DEFAULT_FINANCE_FIELDS)
    declared = _split_fields(row.get("missing_fields", ""))
    inferred = [field for field in DEFAULT_FINANCE_FIELDS if field not in row or _is_missing(row.get(field))]
    return sorted(set(declared + inferred))


def _resolve_tickers(market: pd.DataFrame, limit: int) -> list[str]:
    return _market_tickers(market)[:limit]


def _market_tickers(market: pd.DataFrame) -> list[str]:
    if market.empty or "ticker" not in market.columns:
        return []
    return [ticker for ticker in market["ticker"].astype(str).str.strip().str.upper().drop_duplicates().tolist() if ticker]


def _index_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty or "ticker" not in frame.columns:
        return {}
    out = {}
    for _, row in frame.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        if ticker and ticker not in out:
            out[ticker] = row.to_dict()
    return out


def _recent_trading_value(row: dict[str, Any]) -> float | str:
    close = _to_float(row.get("last_close"))
    volume = _first_number(row, ["avg_volume_20d", "last_volume", "avg_volume_60d"])
    if close is None or volume is None:
        return ""
    return round(close * volume, 4)


def _first_number(row: dict[str, Any], columns: list[str]) -> float | None:
    for column in columns:
        value = _to_float(row.get(column))
        if value is not None:
            return value
    return None


def _to_float(value: Any) -> float | None:
    if _is_missing(value):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _split_fields(value: Any) -> list[str]:
    if _is_missing(value):
        return []
    text = str(value)
    if text.strip().startswith("["):
        return _parse_json_list(text)
    return [field.strip() for field in text.replace(";", ",").split(",") if field.strip()]


def _json_list(values: list[Any]) -> str:
    return json.dumps([str(value) for value in values if not _is_missing(value)], ensure_ascii=False)


def _parse_json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return _split_fields(value) if value and not value.strip().startswith("[") else []
    if isinstance(parsed, list):
        return [str(item) for item in parsed if not _is_missing(item)]
    return []


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _is_missing(value: Any) -> bool:
    return value is None or str(value).strip() == "" or str(value).strip().lower() in {"nan", "none", "null", "na"}


def _read_csv(path: str | Path) -> pd.DataFrame:
    if not path:
        return pd.DataFrame()
    target = Path(path)
    if not target.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(target, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _hashes(paths: list[Path]) -> dict[str, str]:
    return {str(path): _hash_file(path) for path in paths if path.exists()}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit_hash() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:  # noqa: BLE001
        return ""
    return completed.stdout.strip()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _scan_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() != ".json":
        return text
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(data, dict):
        data = dict(data)
        data.pop("forbidden_terms_found", None)
    return json.dumps(data, ensure_ascii=False, indent=2)
