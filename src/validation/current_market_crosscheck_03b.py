"""Market cross-check for PROVISIONAL-CURRENT-MARKET-03B.

This module is intentionally local-file only. It does not fetch market data,
expand the pilot ticker set, parse official disclosures, or modify 03 outputs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


REQUIRED_PRIMARY_COLUMNS = [
    "ticker",
    "last_close",
    "last_price_date",
    "avg_volume_20d",
    "avg_volume_60d",
    "trading_days_60d",
    "missing_market_flag",
    "stale_price_flag",
]

CROSSCHECK_COLUMNS = [
    "ticker",
    "primary_last_price_date",
    "primary_last_close",
    "primary_avg_volume_20d",
    "primary_avg_volume_60d",
    "primary_trading_days_60d",
    "reference_source_name",
    "reference_last_price_date",
    "reference_last_close",
    "reference_avg_volume_20d",
    "reference_avg_volume_60d",
    "price_date_gap_days",
    "price_abs_diff",
    "price_pct_diff",
    "volume_60d_pct_diff",
    "reference_is_current_enough",
    "reference_is_stale",
    "comparison_status",
    "comparison_reason",
    "manual_review_flag",
]

DECISION_VALUES = {"PASS_FOR_PILOT", "CONDITIONAL_GO", "NO_GO"}
PRIMARY_FAIL_STATUSES = {"FAIL_PRIMARY_MISSING", "FAIL_PRIMARY_STALE", "FAIL_SCHEMA_MISSING"}
MISMATCH_STATUSES = {"WARN_PRICE_MISMATCH", "WARN_VOLUME_MISMATCH"}


@dataclass
class MarketCrosscheckResult:
    crosscheck: pd.DataFrame
    mismatches: pd.DataFrame
    manual_review: pd.DataFrame
    decision: dict[str, Any]


@dataclass
class ReferencePoint:
    ticker: str
    source_name: str
    last_price_date: str = ""
    last_close: Any = ""
    avg_volume_20d: Any = ""
    avg_volume_60d: Any = ""
    trading_days_60d: Any = ""
    source_path: str = ""
    public_historical: bool = False
    same_source_cache: bool = False


def load_crosscheck_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def run_market_crosscheck(
    *,
    snapshot_path: str | Path,
    output_dir: str | Path,
    config_path: str | Path,
    legacy_market_path: str | Path | None = None,
    prior_crosscheck_dir: str | Path | None = None,
    raw_cache_dir: str | Path | None = None,
    strict: bool = False,
) -> MarketCrosscheckResult:
    snapshot = Path(snapshot_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    config = load_crosscheck_config(config_path)
    comparison_config = config.get("comparison", {})

    if not snapshot.exists():
        result = _empty_failure(snapshot, "missing current_market_snapshot.csv")
        _write_outputs(output, snapshot, result.crosscheck, result.decision)
        return result

    primary = _read_csv(snapshot)
    if primary.empty:
        result = _empty_failure(snapshot, "empty current_market_snapshot.csv")
        _write_outputs(output, snapshot, result.crosscheck, result.decision)
        return result

    primary = _normalize_tickers(primary)
    missing_schema = [column for column in REQUIRED_PRIMARY_COLUMNS if column not in primary.columns]
    tickers = _snapshot_tickers(primary)
    references, source_inventory = discover_reference_points(
        tickers=tickers,
        snapshot_path=snapshot,
        legacy_market_path=Path(legacy_market_path) if legacy_market_path else None,
        prior_crosscheck_dir=Path(prior_crosscheck_dir) if prior_crosscheck_dir else None,
        raw_cache_dir=Path(raw_cache_dir) if raw_cache_dir else None,
        config=config,
    )

    rows: list[dict[str, Any]] = []
    primary_by_ticker = _index_by_ticker(primary)
    if missing_schema:
        for ticker in tickers or [""]:
            row = _primary_values(ticker, primary_by_ticker.get(ticker, {}))
            row.update(
                {
                    "reference_source_name": "SCHEMA_CHECK",
                    "comparison_status": "FAIL_SCHEMA_MISSING",
                    "comparison_reason": f"Missing required primary schema concepts: {','.join(missing_schema)}",
                    "manual_review_flag": True,
                }
            )
            rows.append(_complete_row(row))
    else:
        for ticker in tickers:
            primary_row = primary_by_ticker.get(ticker, {})
            primary_status = _primary_status(primary_row)
            ticker_refs = references.get(ticker, [])
            if primary_status:
                rows.append(_comparison_row(ticker, primary_row, None, primary_status, comparison_config))
                continue
            if not ticker_refs:
                rows.append(_comparison_row(ticker, primary_row, None, "WARN_REFERENCE_MISSING", comparison_config))
                continue
            for reference in ticker_refs:
                rows.append(_comparison_row(ticker, primary_row, reference, "", comparison_config))

    crosscheck = pd.DataFrame(rows, columns=CROSSCHECK_COLUMNS)
    mismatches = _mismatch_frame(crosscheck)
    manual_review = crosscheck[crosscheck["manual_review_flag"].map(_as_bool)].copy() if not crosscheck.empty else pd.DataFrame(columns=CROSSCHECK_COLUMNS)
    decision = build_decision(
        crosscheck=crosscheck,
        snapshot_path=snapshot,
        tickers=tickers,
        missing_schema=missing_schema,
        source_inventory=source_inventory,
        strict=strict,
        comparison_config=comparison_config,
    )
    _write_outputs(output, snapshot, crosscheck, decision, mismatches=mismatches, manual_review=manual_review)
    return MarketCrosscheckResult(crosscheck, mismatches, manual_review, decision)


def discover_reference_points(
    *,
    tickers: list[str],
    snapshot_path: Path,
    legacy_market_path: Path | None,
    prior_crosscheck_dir: Path | None,
    raw_cache_dir: Path | None,
    config: dict[str, Any],
) -> tuple[dict[str, list[ReferencePoint]], dict[str, Any]]:
    repo_root = _repo_root_from_snapshot(snapshot_path)
    legacy_market_path = legacy_market_path or repo_root / "data" / "reports" / "legacy_structured_finance_import_01" / "provisional_market_liquidity.csv"
    prior_crosscheck_dir = prior_crosscheck_dir or repo_root / "data" / "reports" / "provisional_crosscheck_02"
    raw_cache_dir = raw_cache_dir or repo_root / "data" / "raw" / "current_market_03"
    refs: dict[str, list[ReferencePoint]] = {ticker: [] for ticker in tickers}
    source_paths_found: set[str] = set()
    source_names_found: set[str] = set()
    source_paths_missing: list[str] = []

    raw_refs = _load_raw_cache_references(tickers, raw_cache_dir)
    if raw_refs:
        source_paths_found.add(str(raw_cache_dir))
        source_names_found.add("raw_cache_current_market_03")
        _append_refs(refs, raw_refs)
    elif not raw_cache_dir.exists():
        source_paths_missing.append(str(raw_cache_dir))

    if prior_crosscheck_dir.exists():
        market_files = sorted(path for path in prior_crosscheck_dir.glob("*market*.csv") if path.is_file())
        for path in market_files:
            parsed = _load_prior_market_crosscheck(path, tickers, config)
            if parsed:
                source_paths_found.add(str(path))
                source_names_found.update(ref.source_name for ref in parsed)
                _append_refs(refs, parsed)
    else:
        source_paths_missing.append(str(prior_crosscheck_dir))

    if legacy_market_path.exists():
        source_paths_found.add(str(legacy_market_path))
        parsed = _load_legacy_market_liquidity(legacy_market_path, tickers)
        source_names_found.update(ref.source_name for ref in parsed)
        _append_refs(refs, parsed)
    else:
        source_paths_missing.append(str(legacy_market_path))

    processed_dir = repo_root / "data" / "processed"
    if processed_dir.exists():
        for path in sorted(processed_dir.glob("*market*.csv")):
            parsed = _load_generic_market_reference(path, tickers, "processed_market_reference")
            if parsed:
                source_paths_found.add(str(path))
                source_names_found.update(ref.source_name for ref in parsed)
                _append_refs(refs, parsed)

    return refs, {
        "source_paths_found": sorted(source_paths_found),
        "source_names_found": sorted(source_names_found),
        "source_paths_missing": sorted(source_paths_missing),
    }


def build_decision(
    *,
    crosscheck: pd.DataFrame,
    snapshot_path: Path,
    tickers: list[str],
    missing_schema: list[str],
    source_inventory: dict[str, Any],
    strict: bool,
    comparison_config: dict[str, Any],
) -> dict[str, Any]:
    primary_missing_count = _count_status(crosscheck, "FAIL_PRIMARY_MISSING")
    primary_stale_count = _count_status(crosscheck, "FAIL_PRIMARY_STALE")
    schema_missing_count = len(missing_schema)
    reference_missing_count = _count_status(crosscheck, "WARN_REFERENCE_MISSING")
    reference_stale_count = _count_status(crosscheck, "WARN_REFERENCE_STALE")
    price_mismatch_count = _count_status(crosscheck, "WARN_PRICE_MISMATCH")
    volume_mismatch_count = _count_status(crosscheck, "WARN_VOLUME_MISMATCH")
    manual_review_count = int(crosscheck["manual_review_flag"].map(_as_bool).sum()) if not crosscheck.empty else 0
    fail_count = int(crosscheck["comparison_status"].isin(PRIMARY_FAIL_STATUSES).sum()) if not crosscheck.empty else int(bool(missing_schema))
    current_ref_tickers = set(
        crosscheck[
            crosscheck["reference_is_current_enough"].map(_as_bool)
            & ~crosscheck["comparison_status"].isin(PRIMARY_FAIL_STATUSES)
        ]["ticker"].astype(str)
    ) if not crosscheck.empty else set()
    no_current_reference_count = max(0, len(set(tickers)) - len(current_ref_tickers))

    if len(tickers) == 0 or schema_missing_count or primary_missing_count or primary_stale_count or fail_count:
        final_decision = "NO_GO"
    elif strict and (reference_missing_count or reference_stale_count or manual_review_count or no_current_reference_count):
        final_decision = "NO_GO"
    elif manual_review_count or no_current_reference_count:
        final_decision = "CONDITIONAL_GO"
    elif comparison_config.get("conditional_if_any_reference_stale_or_missing", True) and (reference_missing_count or reference_stale_count):
        final_decision = "CONDITIONAL_GO"
    else:
        final_decision = "PASS_FOR_PILOT"

    if final_decision not in DECISION_VALUES:
        raise ValueError(f"Invalid final decision: {final_decision}")
    return {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "input_snapshot_path": str(snapshot_path),
        "pilot_ticker_count": len(tickers),
        "reference_sources_found": len(source_inventory.get("source_names_found", [])),
        "reference_source_names_found": source_inventory.get("source_names_found", []),
        "reference_source_paths_found": source_inventory.get("source_paths_found", []),
        "reference_sources_missing": source_inventory.get("source_paths_missing", []),
        "primary_missing_count": primary_missing_count,
        "primary_stale_count": primary_stale_count,
        "reference_missing_count": reference_missing_count,
        "reference_stale_count": reference_stale_count,
        "price_mismatch_count": price_mismatch_count,
        "volume_mismatch_count": volume_mismatch_count,
        "manual_review_count": manual_review_count,
        "fail_count": fail_count,
        "no_current_reference_count": no_current_reference_count,
        "final_decision": final_decision,
        "allowed_next_step": "PROVISIONAL-CURRENT-MARKET-03C - End-to-End Replay on Same 20 Pilot Tickers" if final_decision in {"PASS_FOR_PILOT", "CONDITIONAL_GO"} else "Fix 03B issues before replay",
        "not_authorized": ["top500_refresh", "full_universe_live_fetch", "REAL-DATA-02", "Step19", "official_pdf_fetch", "OCR"],
    }


def build_summary(decision: dict[str, Any]) -> str:
    source_names = decision.get("reference_source_names_found", [])
    missing_sources = decision.get("reference_sources_missing", [])
    return "\n".join(
        [
            "# PROVISIONAL-CURRENT-MARKET-03B Market Cross-Check Summary",
            "",
            f"- generated_at: {decision.get('generated_at', '')}",
            f"- input_snapshot_path: {decision.get('input_snapshot_path', '')}",
            f"- pilot_ticker_count: {decision.get('pilot_ticker_count', 0)}",
            f"- reference_sources_found: {decision.get('reference_sources_found', 0)}",
            f"- reference_source_names_found: {source_names}",
            f"- reference_sources_missing: {missing_sources}",
            f"- primary_missing_count: {decision.get('primary_missing_count', 0)}",
            f"- primary_stale_count: {decision.get('primary_stale_count', 0)}",
            f"- reference_missing_count: {decision.get('reference_missing_count', 0)}",
            f"- reference_stale_count: {decision.get('reference_stale_count', 0)}",
            f"- price_mismatch_count: {decision.get('price_mismatch_count', 0)}",
            f"- volume_mismatch_count: {decision.get('volume_mismatch_count', 0)}",
            f"- manual_review_count: {decision.get('manual_review_count', 0)}",
            f"- fail_count: {decision.get('fail_count', 0)}",
            f"- final_decision: {decision.get('final_decision', '')}",
            "",
            "## Important Interpretation",
            "- Stale reference rows do not prove the primary market snapshot is wrong.",
            "- The public historical fallback is labeled non-current and is not used as current confirmation.",
            "- Raw cache rows verify local snapshot consistency; they are not an independent vendor check.",
            "- A pass or conditional pass here only supports 03C replay on the same 20 pilot tickers.",
            "- This result does not authorize top-500 refresh, full-universe live refresh, REAL-DATA-02, Step19, PDF fetch, or OCR.",
            "",
            "## Next Step",
            f"- {decision.get('allowed_next_step', '')}",
        ]
    ) + "\n"


def _write_outputs(
    output_dir: Path,
    snapshot_path: Path,
    crosscheck: pd.DataFrame,
    decision: dict[str, Any],
    *,
    mismatches: pd.DataFrame | None = None,
    manual_review: pd.DataFrame | None = None,
) -> None:
    mismatches = mismatches if mismatches is not None else _mismatch_frame(crosscheck)
    manual_review = manual_review if manual_review is not None else pd.DataFrame(columns=CROSSCHECK_COLUMNS)
    crosscheck.to_csv(output_dir / "market_crosscheck_20.csv", index=False)
    mismatches.to_csv(output_dir / "mismatch_cases.csv", index=False)
    manual_review.to_csv(output_dir / "manual_review_cases.csv", index=False)
    (output_dir / "market_crosscheck_summary.md").write_text(build_summary(decision), encoding="utf-8")
    (output_dir / "crosscheck_decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")


def _empty_failure(snapshot_path: Path, reason: str) -> MarketCrosscheckResult:
    crosscheck = pd.DataFrame(columns=CROSSCHECK_COLUMNS)
    decision = {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "input_snapshot_path": str(snapshot_path),
        "pilot_ticker_count": 0,
        "reference_sources_found": 0,
        "reference_source_names_found": [],
        "reference_source_paths_found": [],
        "reference_sources_missing": [],
        "primary_missing_count": 0,
        "primary_stale_count": 0,
        "reference_missing_count": 0,
        "reference_stale_count": 0,
        "price_mismatch_count": 0,
        "volume_mismatch_count": 0,
        "manual_review_count": 0,
        "fail_count": 1,
        "no_current_reference_count": 0,
        "final_decision": "NO_GO",
        "allowed_next_step": "Fix 03B issues before replay",
        "not_authorized": ["top500_refresh", "full_universe_live_fetch", "REAL-DATA-02", "Step19", "official_pdf_fetch", "OCR"],
        "reason": f"FAIL_BLOCK_NEXT_STEP: {reason}",
    }
    return MarketCrosscheckResult(crosscheck, pd.DataFrame(columns=CROSSCHECK_COLUMNS), pd.DataFrame(columns=CROSSCHECK_COLUMNS), decision)


def _comparison_row(ticker: str, primary_row: dict[str, Any], reference: ReferencePoint | None, forced_status: str, config: dict[str, Any]) -> dict[str, Any]:
    row = _primary_values(ticker, primary_row)
    if reference is None:
        row.update(
            {
                "reference_source_name": "NO_REFERENCE_FOUND" if forced_status == "WARN_REFERENCE_MISSING" else "PRIMARY_CHECK",
                "comparison_status": forced_status,
                "comparison_reason": _forced_reason(forced_status),
                "manual_review_flag": forced_status in PRIMARY_FAIL_STATUSES,
            }
        )
        return _complete_row(row)

    row.update(
        {
            "reference_source_name": reference.source_name,
            "reference_last_price_date": reference.last_price_date,
            "reference_last_close": reference.last_close,
            "reference_avg_volume_20d": reference.avg_volume_20d,
            "reference_avg_volume_60d": reference.avg_volume_60d,
        }
    )
    price_date_gap = _date_gap_days(primary_row.get("last_price_date"), reference.last_price_date)
    price_abs_diff = _abs_diff(primary_row.get("last_close"), reference.last_close)
    price_pct_diff = _pct_diff(primary_row.get("last_close"), reference.last_close)
    volume_60d_pct_diff = _pct_diff(primary_row.get("avg_volume_60d"), reference.avg_volume_60d)
    reference_is_current = _reference_is_current_enough(reference, price_date_gap, config)
    reference_is_stale = not reference_is_current
    status, reason, manual = _comparison_status(reference, reference_is_current, price_pct_diff, volume_60d_pct_diff, config)
    row.update(
        {
            "price_date_gap_days": price_date_gap if price_date_gap is not None else "",
            "price_abs_diff": price_abs_diff if price_abs_diff is not None else "",
            "price_pct_diff": price_pct_diff if price_pct_diff is not None else "",
            "volume_60d_pct_diff": volume_60d_pct_diff if volume_60d_pct_diff is not None else "",
            "reference_is_current_enough": reference_is_current,
            "reference_is_stale": reference_is_stale,
            "comparison_status": status,
            "comparison_reason": reason,
            "manual_review_flag": manual,
        }
    )
    return _complete_row(row)


def _comparison_status(
    reference: ReferencePoint,
    reference_is_current: bool,
    price_pct_diff: float | None,
    volume_60d_pct_diff: float | None,
    config: dict[str, Any],
) -> tuple[str, str, bool]:
    if _missing(reference.last_close) or _missing(reference.last_price_date):
        return "WARN_REFERENCE_MISSING", "Reference row exists but lacks last price or date.", False
    if not reference_is_current:
        if reference.public_historical:
            return "WARN_REFERENCE_STALE", "Public historical fallback is stale and not current confirmation.", False
        return "WARN_REFERENCE_STALE", "Reference is stale versus the primary snapshot.", False
    price_threshold = float(config.get("max_price_pct_diff_for_match", 0.03) or 0.03)
    volume_threshold = float(config.get("max_volume_60d_pct_diff_for_match", 0.50) or 0.50)
    if price_pct_diff is not None and abs(price_pct_diff) > price_threshold:
        return "WARN_PRICE_MISMATCH", "Current reference price differs beyond policy tolerance.", True
    if volume_60d_pct_diff is not None and abs(volume_60d_pct_diff) > volume_threshold:
        return "WARN_VOLUME_MISMATCH", "Current reference 60-day volume differs beyond policy tolerance.", True
    return "PASS_MATCH_OR_REFERENCE_STALE_BUT_PRIMARY_FRESH", "Reference check does not show a severe current mismatch.", False


def _primary_status(primary_row: dict[str, Any]) -> str:
    if _as_bool(primary_row.get("missing_market_flag")) or _missing(primary_row.get("last_close")) or _missing(primary_row.get("last_price_date")):
        return "FAIL_PRIMARY_MISSING"
    if _as_bool(primary_row.get("stale_price_flag")):
        return "FAIL_PRIMARY_STALE"
    return ""


def _primary_values(ticker: str, primary_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "primary_last_price_date": primary_row.get("last_price_date", ""),
        "primary_last_close": primary_row.get("last_close", ""),
        "primary_avg_volume_20d": primary_row.get("avg_volume_20d", ""),
        "primary_avg_volume_60d": primary_row.get("avg_volume_60d", ""),
        "primary_trading_days_60d": primary_row.get("trading_days_60d", ""),
    }


def _complete_row(row: dict[str, Any]) -> dict[str, Any]:
    return {column: row.get(column, "") for column in CROSSCHECK_COLUMNS}


def _forced_reason(status: str) -> str:
    reasons = {
        "FAIL_PRIMARY_MISSING": "Primary snapshot has missing market values.",
        "FAIL_PRIMARY_STALE": "Primary snapshot is stale by its own gate flag.",
        "FAIL_SCHEMA_MISSING": "Primary snapshot is missing required schema concepts.",
        "WARN_REFERENCE_MISSING": "No local reference source was found for this pilot ticker.",
    }
    return reasons.get(status, status)


def _mismatch_frame(crosscheck: pd.DataFrame) -> pd.DataFrame:
    if crosscheck.empty:
        return pd.DataFrame(columns=CROSSCHECK_COLUMNS)
    mask = crosscheck["comparison_status"].isin(PRIMARY_FAIL_STATUSES | MISMATCH_STATUSES)
    return crosscheck[mask].copy()


def _load_raw_cache_references(tickers: list[str], raw_cache_dir: Path) -> list[ReferencePoint]:
    refs = []
    if not raw_cache_dir.exists():
        return refs
    for ticker in tickers:
        history_path = raw_cache_dir / f"{ticker}_history.csv"
        if not history_path.exists():
            continue
        recomputed = _recompute_from_history(history_path)
        if not recomputed:
            continue
        refs.append(
            ReferencePoint(
                ticker=ticker,
                source_name="raw_cache_current_market_03",
                source_path=str(history_path),
                same_source_cache=True,
                **recomputed,
            )
        )
    return refs


def _load_prior_market_crosscheck(path: Path, tickers: list[str], config: dict[str, Any]) -> list[ReferencePoint]:
    frame = _read_csv(path)
    if frame.empty or "ticker" not in frame.columns:
        return []
    frame = _normalize_tickers(frame)
    frame = frame[frame["ticker"].isin(tickers)]
    refs: list[ReferencePoint] = []
    public_is_current = bool((config.get("comparison", {}) or {}).get("public_historical_source_is_current_source", False))
    for _, row in frame.iterrows():
        ticker = str(row.get("ticker", "")).upper()
        if "public_last_close" in frame.columns or "public_last_price_date" in frame.columns:
            refs.append(
                ReferencePoint(
                    ticker=ticker,
                    source_name="provisional_crosscheck_02_public_historical",
                    last_price_date=row.get("public_last_price_date", ""),
                    last_close=row.get("public_last_close", ""),
                    avg_volume_20d=row.get("public_avg_volume_20d", ""),
                    avg_volume_60d=row.get("public_avg_volume_60d", ""),
                    source_path=str(path),
                    public_historical=not public_is_current,
                )
            )
        if "legacy_last_close" in frame.columns or "legacy_last_price_date" in frame.columns:
            refs.append(
                ReferencePoint(
                    ticker=ticker,
                    source_name="provisional_crosscheck_02_legacy_market",
                    last_price_date=row.get("legacy_last_price_date", ""),
                    last_close=row.get("legacy_last_close", ""),
                    avg_volume_20d=row.get("legacy_avg_volume_20d", ""),
                    avg_volume_60d=row.get("legacy_avg_volume_60d", ""),
                    source_path=str(path),
                )
            )
    return refs


def _load_legacy_market_liquidity(path: Path, tickers: list[str]) -> list[ReferencePoint]:
    frame = _read_csv(path)
    if frame.empty or "ticker" not in frame.columns:
        return []
    frame = _normalize_tickers(frame)
    frame = frame[frame["ticker"].isin(tickers)]
    refs: list[ReferencePoint] = []
    for _, row in frame.iterrows():
        source = str(row.get("source_name", "") or "legacy_structured_market_liquidity")
        refs.append(
            ReferencePoint(
                ticker=str(row.get("ticker", "")).upper(),
                source_name=source,
                last_price_date=row.get("last_price_date", ""),
                last_close=row.get("last_close", ""),
                avg_volume_20d=row.get("avg_volume_20d", ""),
                avg_volume_60d=row.get("avg_volume_60d", ""),
                trading_days_60d=row.get("trading_days_60d", ""),
                source_path=str(path),
            )
        )
    return refs


def _load_generic_market_reference(path: Path, tickers: list[str], fallback_source_name: str) -> list[ReferencePoint]:
    frame = _read_csv(path)
    if frame.empty or "ticker" not in frame.columns:
        return []
    frame = _normalize_tickers(frame)
    frame = frame[frame["ticker"].isin(tickers)]
    if frame.empty:
        return []
    date_col = _first_column(frame, ["last_price_date", "reference_last_price_date", "date", "time"])
    close_col = _first_column(frame, ["last_close", "reference_last_close", "close", "close_price"])
    if not date_col and not close_col:
        return []
    avg20_col = _first_column(frame, ["avg_volume_20d", "reference_avg_volume_20d"])
    avg60_col = _first_column(frame, ["avg_volume_60d", "reference_avg_volume_60d"])
    days60_col = _first_column(frame, ["trading_days_60d", "reference_trading_days_60d"])
    source_col = _first_column(frame, ["source_name", "market_source"])
    refs = []
    for _, row in frame.iterrows():
        refs.append(
            ReferencePoint(
                ticker=str(row.get("ticker", "")).upper(),
                source_name=str(row.get(source_col, "") or fallback_source_name),
                last_price_date=row.get(date_col, ""),
                last_close=row.get(close_col, ""),
                avg_volume_20d=row.get(avg20_col, "") if avg20_col else "",
                avg_volume_60d=row.get(avg60_col, "") if avg60_col else "",
                trading_days_60d=row.get(days60_col, "") if days60_col else "",
                source_path=str(path),
            )
        )
    return refs


def _recompute_from_history(path: Path) -> dict[str, Any]:
    frame = _read_csv(path)
    if frame.empty:
        return {}
    date_col = _first_column(frame, ["date", "time", "trading_date"])
    close_col = _first_column(frame, ["close", "adjusted_close", "adj_close", "close_price"])
    volume_col = _first_column(frame, ["volume", "vol", "match_volume", "matching_volume"])
    if not date_col or not close_col:
        return {}
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(frame[date_col], errors="coerce"),
            "close": pd.to_numeric(frame[close_col], errors="coerce"),
            "volume": pd.to_numeric(frame[volume_col], errors="coerce") if volume_col else pd.Series(dtype=float),
        }
    ).dropna(subset=["date", "close"]).sort_values("date")
    if out.empty:
        return {}
    volumes = pd.to_numeric(out["volume"], errors="coerce").dropna()
    return {
        "last_price_date": out.iloc[-1]["date"].date().isoformat(),
        "last_close": float(out.iloc[-1]["close"]),
        "avg_volume_20d": round(float(volumes.tail(20).mean()), 4) if not volumes.empty else "",
        "avg_volume_60d": round(float(volumes.tail(60).mean()), 4) if not volumes.empty else "",
        "trading_days_60d": int(min(len(volumes), 60)),
    }


def _reference_is_current_enough(reference: ReferencePoint, price_date_gap: int | None, config: dict[str, Any]) -> bool:
    if reference.public_historical and not bool(config.get("public_historical_source_is_current_source", False)):
        return False
    if _missing(reference.last_close) or _missing(reference.last_price_date):
        return False
    if price_date_gap is None:
        return False
    return abs(price_date_gap) <= int(config.get("max_current_reference_gap_days", 5) or 5)


def _append_refs(refs: dict[str, list[ReferencePoint]], points: list[ReferencePoint]) -> None:
    for point in points:
        if point.ticker in refs:
            refs[point.ticker].append(point)


def _snapshot_tickers(frame: pd.DataFrame) -> list[str]:
    if "ticker" not in frame.columns:
        return []
    return [ticker for ticker in frame["ticker"].astype(str).str.strip().str.upper().drop_duplicates().tolist() if ticker]


def _normalize_tickers(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "ticker" in out.columns:
        out["ticker"] = out["ticker"].astype(str).str.strip().str.upper()
    return out


def _index_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty or "ticker" not in frame.columns:
        return {}
    out = {}
    for _, row in frame.iterrows():
        ticker = str(row.get("ticker", "")).upper()
        if ticker and ticker not in out:
            out[ticker] = row.to_dict()
    return out


def _repo_root_from_snapshot(snapshot_path: Path) -> Path:
    resolved = snapshot_path.resolve()
    for parent in [resolved.parent, *resolved.parents]:
        if (parent / "PROJECT_CONTEXT.md").exists():
            return parent
    return Path.cwd()


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _first_column(frame: pd.DataFrame, candidates: list[str]) -> str:
    lowered = {str(column).strip().lower(): str(column) for column in frame.columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return ""


def _count_status(frame: pd.DataFrame, status: str) -> int:
    if frame.empty or "comparison_status" not in frame.columns:
        return 0
    return int(frame["comparison_status"].eq(status).sum())


def _date_gap_days(left: Any, right: Any) -> int | None:
    left_date = pd.to_datetime(left, errors="coerce")
    right_date = pd.to_datetime(right, errors="coerce")
    if pd.isna(left_date) or pd.isna(right_date):
        return None
    return int((left_date.date() - right_date.date()).days)


def _abs_diff(left: Any, right: Any) -> float | None:
    left_num = _to_float(left)
    right_num = _to_float(right)
    if left_num is None or right_num is None:
        return None
    return round(abs(left_num - right_num), 6)


def _pct_diff(primary: Any, reference: Any) -> float | None:
    primary_num = _to_float(primary)
    reference_num = _to_float(reference)
    if primary_num is None or reference_num is None or reference_num == 0:
        return None
    return round((primary_num - reference_num) / abs(reference_num), 6)


def _to_float(value: Any) -> float | None:
    if _missing(value):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _missing(value: Any) -> bool:
    return value is None or str(value).strip() == "" or str(value).strip().lower() in {"nan", "none", "null"}
