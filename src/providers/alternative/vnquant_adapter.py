"""Defensive vnquant market adapter for 04C provider probes."""

from __future__ import annotations

import importlib
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


VNQUANT_SOURCE_MAP = {
    "cafef_structured_or_market": "cafe",
    "vndirect_market": "vnd",
}


def fetch_vnquant_market(
    *,
    module: Any,
    tickers: list[str],
    source_families: list[str],
    cache_dir: str | Path,
    max_requests: int,
    sleep_seconds: float,
) -> list[dict[str, Any]]:
    loader_cls = _loader_class(module)
    if loader_cls is None:
        return [
            _attempt_row(ticker, source_family, "PROVIDER_API_UNSUPPORTED", False, True, "NoSupportedFetcher", "vnquant DataLoader interface was not detected.")
            for ticker in tickers
            for source_family in source_families
        ]
    rows: list[dict[str, Any]] = []
    request_count = 0
    end_date = datetime.now(UTC).date()
    start_date = end_date - timedelta(days=120)
    for source_family in source_families:
        data_source = VNQUANT_SOURCE_MAP.get(source_family)
        if not data_source:
            rows.extend(
                _attempt_row(ticker, source_family, "PROVIDER_API_UNSUPPORTED", False, False, "UnsupportedSourceFamily", f"No vnquant data_source mapping for {source_family}.")
                for ticker in tickers
            )
            continue
        for ticker in tickers:
            if request_count >= max_requests:
                rows.append(_attempt_row(ticker, source_family, "REQUEST_LIMIT_REACHED", False, False, "RequestLimitReached", "04C request limit reached before this ticker."))
                continue
            request_count += 1
            try:
                loader = loader_cls(symbols=ticker, start=start_date.isoformat(), end=end_date.isoformat(), data_source=data_source, minimal=True)
                frame = loader.download()
                cache_path = _write_cache(frame, cache_dir, "vnquant", source_family, ticker)
                normalized = _last_market_point(frame)
                if not normalized:
                    rows.append(_attempt_row(ticker, source_family, "PROVIDER_NO_DATA", True, False, rows_returned=_row_count(frame), raw_cache_path=cache_path))
                else:
                    rows.append(
                        _attempt_row(
                            ticker,
                            source_family,
                            "FETCH_OK",
                            True,
                            True,
                            rows_returned=_row_count(frame),
                            raw_cache_path=cache_path,
                            **normalized,
                        )
                    )
            except Exception as exc:  # noqa: BLE001 - provider failures must be diagnostic rows.
                rows.append(_attempt_row(ticker, source_family, "PROVIDER_ERROR", True, True, type(exc).__name__, str(exc)))
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
    return rows


def _loader_class(module: Any) -> Any:
    loader = getattr(module, "DataLoader", None)
    if hasattr(loader, "DataLoader"):
        return loader.DataLoader
    if loader is not None and callable(loader):
        return loader
    try:
        data_loader_module = importlib.import_module("vnquant.DataLoader")
    except Exception:  # noqa: BLE001
        return None
    return getattr(data_loader_module, "DataLoader", None)


def _last_market_point(frame: Any) -> dict[str, Any]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return {}
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = ["_".join(str(part) for part in column if str(part)) for column in data.columns]
    if isinstance(data.index, pd.DatetimeIndex):
        data = data.reset_index().rename(columns={"index": "date"})
    date_col = _first_column(data, ["date", "time", "trading_date"])
    close_col = _first_column(data, ["close", "close_price"])
    adjusted_col = _first_column(data, ["adjust", "adjusted_close", "adj_close"])
    volume_col = _first_column(data, ["volume", "vol", "match_volume"])
    price_basis = "unadjusted"
    if not close_col and adjusted_col:
        close_col = adjusted_col
        price_basis = "adjusted"
    if not date_col or not close_col:
        return {}
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(data[date_col], errors="coerce"),
            "close": pd.to_numeric(data[close_col], errors="coerce"),
            "volume": pd.to_numeric(data[volume_col], errors="coerce") if volume_col else pd.Series(dtype=float),
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
        "price_basis": price_basis,
    }


def _write_cache(frame: Any, cache_dir: str | Path, provider_name: str, source_family: str, ticker: str) -> str:
    path = Path(cache_dir) / provider_name / source_family / f"{ticker}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(frame, pd.DataFrame):
        frame.to_csv(path, index=True)
        return str(path)
    path.with_suffix(".txt").write_text(str(frame), encoding="utf-8")
    return str(path.with_suffix(".txt"))


def _attempt_row(
    ticker: str,
    source_family: str,
    attempt_status: str,
    fetch_attempted: bool,
    network_used: bool,
    fetch_error_type: str = "",
    fetch_error_message: str = "",
    *,
    rows_returned: int = 0,
    last_price_date: Any = "",
    last_close: Any = "",
    avg_volume_20d: Any = "",
    avg_volume_60d: Any = "",
    raw_cache_path: str = "",
    price_basis: str = "",
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "provider_name": "vnquant",
        "source_family": source_family,
        "attempt_status": attempt_status,
        "network_used": bool(network_used),
        "cache_used": False,
        "fetch_attempted": bool(fetch_attempted),
        "fetch_error_type": fetch_error_type,
        "fetch_error_message": fetch_error_message,
        "rows_returned": rows_returned,
        "last_price_date": last_price_date,
        "last_close": last_close,
        "avg_volume_20d": avg_volume_20d,
        "avg_volume_60d": avg_volume_60d,
        "raw_cache_path": raw_cache_path,
        "price_basis": price_basis,
    }


def _row_count(frame: Any) -> int:
    return int(len(frame)) if isinstance(frame, pd.DataFrame) else 0


def _first_column(frame: pd.DataFrame, candidates: list[str]) -> str:
    lowered = {str(column).strip().lower(): str(column) for column in frame.columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return ""
