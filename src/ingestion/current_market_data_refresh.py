"""Fresh current market data refresh with per-ticker cache.

The data produced here is market-only and provisional. It is used to gate
evidence workload stages, not to produce recommendations.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yaml


SNAPSHOT_COLUMNS = [
    "ticker",
    "market_source",
    "fetch_status",
    "fetch_error",
    "last_close",
    "last_price_date",
    "last_volume",
    "avg_volume_20d",
    "avg_volume_60d",
    "trading_days_20d",
    "trading_days_60d",
    "lookback_start",
    "lookback_end",
    "missing_market_flag",
    "stale_price_flag",
    "stale_days",
    "raw_rows",
    "cache_used",
    "created_at",
]

ATTEMPT_LOG_COLUMNS = [
    "ticker",
    "rank",
    "fetch_status",
    "fetch_error",
    "cache_used",
    "raw_rows",
    "created_at",
]

FETCH_OK = "FETCH_OK"
FETCH_EMPTY = "FETCH_EMPTY"
FETCH_ERROR = "FETCH_ERROR"
FETCH_SKIPPED_EXISTING_CACHE = "FETCH_SKIPPED_EXISTING_CACHE"
FETCH_PARTIAL = "FETCH_PARTIAL"


def load_current_market_policy(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def select_refresh_tickers(ranking: pd.DataFrame, top_n: int, max_requests: int) -> pd.DataFrame:
    if not isinstance(ranking, pd.DataFrame) or ranking.empty or "ticker" not in ranking.columns:
        return pd.DataFrame(columns=["ticker", "rank"])
    frame = ranking.copy()
    rank_col = _first_column(frame, ["balanced_rank", "rank", "raw_rank"])
    if rank_col:
        frame["_refresh_rank"] = pd.to_numeric(frame[rank_col], errors="coerce")
    else:
        frame["_refresh_rank"] = range(1, len(frame) + 1)
    frame = frame.sort_values(["_refresh_rank", "ticker"]).head(min(top_n, max_requests)).copy()
    fallback_rank = pd.Series(range(1, len(frame) + 1), index=frame.index)
    frame["rank"] = frame["_refresh_rank"].where(frame["_refresh_rank"].notna(), fallback_rank).astype(int)
    return frame[["ticker", "rank"]]


def normalize_quote_history(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame(columns=["ticker", "date", "close", "volume"])
    date_col = _first_column(frame, ["time", "date", "trading_date", "tradingDate"])
    close_col = _first_column(frame, ["close", "adjusted_close", "adj_close", "close_price"])
    volume_col = _first_column(frame, ["volume", "vol", "match_volume", "matching_volume"])
    if not date_col or not close_col:
        return pd.DataFrame(columns=["ticker", "date", "close", "volume"])
    out = pd.DataFrame(
        {
            "ticker": str(ticker).upper(),
            "date": pd.to_datetime(frame[date_col], errors="coerce"),
            "close": pd.to_numeric(frame[close_col], errors="coerce"),
            "volume": pd.to_numeric(frame[volume_col], errors="coerce") if volume_col else pd.Series(dtype=float),
        }
    )
    return out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)


def compute_market_snapshot(
    *,
    ticker: str,
    normalized_history: pd.DataFrame,
    policy: dict[str, Any],
    fetch_status: str,
    fetch_error: str = "",
    cache_used: bool = False,
    run_date: datetime | None = None,
    raw_rows: int | None = None,
) -> dict[str, Any]:
    run_date = run_date or datetime.now(UTC)
    market_policy = policy.get("market_refresh", policy)
    stale_threshold = int(market_policy.get("max_stale_calendar_days", 14) or 14)
    lookback_end = run_date.date().isoformat()
    lookback_start = (run_date - timedelta(days=int(market_policy.get("lookback_calendar_days", 120) or 120))).date().isoformat()
    frame = normalized_history.copy() if isinstance(normalized_history, pd.DataFrame) else pd.DataFrame()
    raw_rows = int(raw_rows if raw_rows is not None else len(frame))
    if frame.empty:
        return _empty_snapshot(
            ticker=ticker,
            market_source=market_policy.get("source_name", "vnstock_quote_vci_history"),
            fetch_status=fetch_status if fetch_status != FETCH_OK else FETCH_EMPTY,
            fetch_error=fetch_error,
            lookback_start=lookback_start,
            lookback_end=lookback_end,
            cache_used=cache_used,
            raw_rows=raw_rows,
            created_at=run_date,
        )
    valid = frame.dropna(subset=["date", "close"]).sort_values("date").copy()
    if valid.empty:
        return _empty_snapshot(
            ticker=ticker,
            market_source=market_policy.get("source_name", "vnstock_quote_vci_history"),
            fetch_status=FETCH_PARTIAL if fetch_status == FETCH_OK else fetch_status,
            fetch_error=fetch_error,
            lookback_start=lookback_start,
            lookback_end=lookback_end,
            cache_used=cache_used,
            raw_rows=raw_rows,
            created_at=run_date,
        )
    last = valid.iloc[-1]
    last_date = pd.to_datetime(last["date"]).date()
    stale_days = max(0, (run_date.date() - last_date).days)
    volumes = pd.to_numeric(valid.get("volume", pd.Series(dtype=float)), errors="coerce").dropna()
    last_volume = _last_valid_number(valid.get("volume"))
    return {
        "ticker": str(ticker).upper(),
        "market_source": market_policy.get("source_name", "vnstock_quote_vci_history"),
        "fetch_status": fetch_status,
        "fetch_error": fetch_error,
        "last_close": _to_float(last.get("close")),
        "last_price_date": last_date.isoformat(),
        "last_volume": last_volume if last_volume is not None else "",
        "avg_volume_20d": _mean_last(volumes, 20),
        "avg_volume_60d": _mean_last(volumes, 60),
        "trading_days_20d": int(min(len(volumes), 20)),
        "trading_days_60d": int(min(len(volumes), 60)),
        "lookback_start": lookback_start,
        "lookback_end": lookback_end,
        "missing_market_flag": False,
        "stale_price_flag": stale_days > stale_threshold,
        "stale_days": stale_days,
        "raw_rows": raw_rows,
        "cache_used": cache_used,
        "created_at": run_date.replace(microsecond=0).isoformat(),
    }


def run_current_market_refresh(
    *,
    ranking_path: Path,
    output_dir: Path,
    raw_output_dir: Path,
    policy_path: Path,
    top_n: int,
    max_requests: int,
    sleep_seconds: float,
    allow_partial: bool,
    force_refresh: bool,
    fetcher: Callable[[str, datetime, datetime, dict[str, Any]], pd.DataFrame] | None = None,
) -> dict[str, Any]:
    policy = load_current_market_policy(policy_path)
    ranking = pd.read_csv(ranking_path, keep_default_na=False)
    requested = select_refresh_tickers(ranking, top_n=top_n, max_requests=max_requests)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_output_dir.mkdir(parents=True, exist_ok=True)
    fetcher = fetcher or fetch_quote_history_vnstock
    run_date = datetime.now(UTC)
    market_policy = policy.get("market_refresh", {})
    lookback_days = int(market_policy.get("lookback_calendar_days", 120) or 120)
    start = run_date - timedelta(days=lookback_days)
    snapshots: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []

    for _, item in requested.iterrows():
        ticker = str(item["ticker"]).upper()
        rank = int(item["rank"])
        try:
            snapshot, history = load_cached_snapshot(ticker, raw_output_dir, policy, force_refresh=force_refresh, run_date=run_date)
            if snapshot:
                snapshots.append(snapshot)
                attempts.append(_attempt_from_snapshot(snapshot, rank))
                continue
            raw = fetcher(ticker, start, run_date, policy)
            normalized = normalize_quote_history(raw, ticker)
            status = FETCH_OK if not normalized.empty else FETCH_EMPTY
            snapshot = compute_market_snapshot(
                ticker=ticker,
                normalized_history=normalized,
                policy=policy,
                fetch_status=status,
                cache_used=False,
                run_date=run_date,
                raw_rows=len(raw) if isinstance(raw, pd.DataFrame) else 0,
            )
            write_ticker_cache(ticker, raw_output_dir, normalized, snapshot)
        except Exception as exc:
            snapshot = compute_market_snapshot(
                ticker=ticker,
                normalized_history=pd.DataFrame(),
                policy=policy,
                fetch_status=FETCH_ERROR,
                fetch_error=str(exc),
                cache_used=False,
                run_date=run_date,
                raw_rows=0,
            )
            if not allow_partial:
                raise
        snapshots.append(snapshot)
        attempts.append(_attempt_from_snapshot(snapshot, rank))
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    snapshot_frame = pd.DataFrame(snapshots, columns=SNAPSHOT_COLUMNS)
    attempt_frame = pd.DataFrame(attempts, columns=ATTEMPT_LOG_COLUMNS)
    snapshot_frame.to_csv(output_dir / "current_market_snapshot.csv", index=False)
    attempt_frame.to_csv(output_dir / "current_market_refresh_attempt_log.csv", index=False)
    summary = build_refresh_summary(snapshot_frame, attempt_frame)
    (output_dir / "current_market_refresh_summary.md").write_text(summary, encoding="utf-8")
    return {
        "snapshot": snapshot_frame,
        "attempt_log": attempt_frame,
        "summary": summary,
    }


def fetch_quote_history_vnstock(ticker: str, start: datetime, end: datetime, policy: dict[str, Any]) -> pd.DataFrame:
    market_policy = policy.get("market_refresh", {})
    quote_source = market_policy.get("quote_source", "VCI")
    try:
        from vnstock import Quote  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on local env
        raise RuntimeError(f"LIVE_FETCH_NOT_AVAILABLE_IN_ENV: vnstock import failed: {exc}") from exc
    try:
        quote = Quote(symbol=str(ticker).upper(), source=quote_source)
        try:
            return quote.history(start=start.date().isoformat(), end=end.date().isoformat(), interval="1D")
        except TypeError:
            return quote.history(start=start.date().isoformat(), end=end.date().isoformat())
    except Exception as exc:  # pragma: no cover - depends on upstream API/network
        raise RuntimeError(f"LIVE_FETCH_NOT_AVAILABLE_IN_ENV: {exc}") from exc


def load_cached_snapshot(
    ticker: str,
    raw_output_dir: Path,
    policy: dict[str, Any],
    *,
    force_refresh: bool,
    run_date: datetime,
) -> tuple[dict[str, Any] | None, pd.DataFrame]:
    if force_refresh:
        return None, pd.DataFrame()
    snapshot_path = raw_output_dir / f"{ticker.upper()}_snapshot.json"
    history_path = raw_output_dir / f"{ticker.upper()}_history.csv"
    if not snapshot_path.exists():
        return None, pd.DataFrame()
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception:
        return None, pd.DataFrame()
    cache_hours = float((policy.get("market_refresh", {}) or {}).get("cache_max_age_hours", 24) or 24)
    created_at = pd.to_datetime(snapshot.get("created_at"), errors="coerce", utc=True)
    if pd.isna(created_at) or (run_date - created_at.to_pydatetime()).total_seconds() > cache_hours * 3600:
        return None, pd.DataFrame()
    history = pd.read_csv(history_path, keep_default_na=False) if history_path.exists() else pd.DataFrame()
    snapshot = dict(snapshot)
    snapshot["fetch_status"] = FETCH_SKIPPED_EXISTING_CACHE
    snapshot["cache_used"] = True
    return snapshot, history


def write_ticker_cache(ticker: str, raw_output_dir: Path, history: pd.DataFrame, snapshot: dict[str, Any]) -> None:
    raw_output_dir.mkdir(parents=True, exist_ok=True)
    history.to_csv(raw_output_dir / f"{ticker.upper()}_history.csv", index=False)
    (raw_output_dir / f"{ticker.upper()}_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


def build_refresh_summary(snapshot: pd.DataFrame, attempts: pd.DataFrame) -> str:
    total_requested = len(attempts)
    status_counts = attempts["fetch_status"].value_counts().to_dict() if not attempts.empty else {}
    missing = int(snapshot["missing_market_flag"].astype(bool).sum()) if not snapshot.empty else 0
    stale = int(snapshot["stale_price_flag"].astype(bool).sum()) if not snapshot.empty else 0
    fresh_enough = int((~snapshot["missing_market_flag"].astype(bool) & ~snapshot["stale_price_flag"].astype(bool)).sum()) if not snapshot.empty else 0
    dates = pd.to_datetime(snapshot.get("last_price_date", pd.Series(dtype=str)), errors="coerce").dropna()
    oldest = dates.min().date().isoformat() if not dates.empty else ""
    newest = dates.max().date().isoformat() if not dates.empty else ""
    return "\n".join(
        [
            "# Current Market Refresh 03",
            "",
            f"- total_requested: {total_requested}",
            f"- total_fetch_ok: {int(status_counts.get(FETCH_OK, 0))}",
            f"- total_cache_used: {int(status_counts.get(FETCH_SKIPPED_EXISTING_CACHE, 0))}",
            f"- total_fetch_empty: {int(status_counts.get(FETCH_EMPTY, 0))}",
            f"- total_fetch_error: {int(status_counts.get(FETCH_ERROR, 0))}",
            f"- total_missing_market: {missing}",
            f"- total_stale_price: {stale}",
            f"- fresh_enough_count: {fresh_enough}",
            f"- oldest_last_price_date: {oldest}",
            f"- newest_last_price_date: {newest}",
            "",
            "## Safety",
            "- Market data refresh only; no finance values were inferred or zero-filled.",
            "- No official PDFs, OCR, Step19, REAL-DATA-02, valuation, target price, or buy/sell logic was run.",
        ]
    ) + "\n"


def _empty_snapshot(
    *,
    ticker: str,
    market_source: str,
    fetch_status: str,
    fetch_error: str,
    lookback_start: str,
    lookback_end: str,
    cache_used: bool,
    raw_rows: int,
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "ticker": str(ticker).upper(),
        "market_source": market_source,
        "fetch_status": fetch_status,
        "fetch_error": fetch_error,
        "last_close": "",
        "last_price_date": "",
        "last_volume": "",
        "avg_volume_20d": "",
        "avg_volume_60d": "",
        "trading_days_20d": 0,
        "trading_days_60d": 0,
        "lookback_start": lookback_start,
        "lookback_end": lookback_end,
        "missing_market_flag": True,
        "stale_price_flag": True,
        "stale_days": "",
        "raw_rows": raw_rows,
        "cache_used": cache_used,
        "created_at": created_at.replace(microsecond=0).isoformat(),
    }


def _attempt_from_snapshot(snapshot: dict[str, Any], rank: int) -> dict[str, Any]:
    return {
        "ticker": snapshot.get("ticker", ""),
        "rank": rank,
        "fetch_status": snapshot.get("fetch_status", ""),
        "fetch_error": snapshot.get("fetch_error", ""),
        "cache_used": snapshot.get("cache_used", False),
        "raw_rows": snapshot.get("raw_rows", 0),
        "created_at": snapshot.get("created_at", ""),
    }


def _first_column(frame: pd.DataFrame, candidates: list[str]) -> str:
    lowered = {str(column).strip().lower(): str(column) for column in frame.columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return ""


def _mean_last(values: pd.Series, count: int) -> float | str:
    if values.empty:
        return ""
    return round(float(values.tail(count).mean()), 4)


def _last_valid_number(series: pd.Series | None) -> float | None:
    if series is None:
        return None
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.iloc[-1]) if not values.empty else None


def _to_float(value: Any) -> float | str:
    if value is None or value == "":
        return ""
    try:
        return float(value)
    except (TypeError, ValueError):
        return ""
