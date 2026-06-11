"""Targeted public OHLCV cross-check for provisional market data.

This module fetches per-ticker raw CSV files from a public GitHub repository.
It never clones the repository and never treats public market data as official
financial-statement evidence.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd
import yaml


MARKET_CROSSCHECK_COLUMNS = [
    "ticker",
    "rank",
    "exchange",
    "sector_raw",
    "legacy_last_close",
    "public_last_close",
    "legacy_last_price_date",
    "public_last_price_date",
    "legacy_avg_volume_20d",
    "public_avg_volume_20d",
    "legacy_avg_volume_60d",
    "public_avg_volume_60d",
    "price_abs_diff",
    "price_relative_diff_pct",
    "volume_60d_relative_diff_pct",
    "price_crosscheck_status",
    "volume_crosscheck_status",
    "manual_review_required",
    "reason",
]

ATTEMPT_LOG_COLUMNS = [
    "ticker",
    "rank",
    "url",
    "attempt_status",
    "http_status",
    "row_count",
    "error",
]

DEFAULT_THRESHOLDS = {
    "price_minor_diff_pct": 2.0,
    "price_major_diff_pct": 5.0,
    "volume_minor_diff_pct": 20.0,
    "volume_major_diff_pct": 50.0,
    "stale_days_threshold": 10,
}


def load_public_market_source_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    source = (config.get("sources") or {}).get("vnstock_market_data_github") or {}
    if not source.get("raw_url_template"):
        raise ValueError("Missing raw_url_template for vnstock_market_data_github")
    return source


def build_public_market_csv_url(ticker: str, config: dict[str, Any]) -> str:
    template = str(config.get("raw_url_template") or "")
    return template.format(ticker=str(ticker).upper().strip())


def fetch_public_market_csv_for_ticker(ticker: str, config: dict[str, Any], timeout: int = 20) -> pd.DataFrame:
    result = fetch_public_market_csv_with_log(ticker, config, timeout=timeout)
    if result["attempt_status"] != "FETCHED":
        raise FileNotFoundError(result.get("error") or result["attempt_status"])
    return result["frame"]


def fetch_public_market_csv_with_log(ticker: str, config: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    url = build_public_market_csv_url(ticker, config)
    request = Request(url, headers={"User-Agent": "n-a-n-provisional-crosscheck-02"})
    try:
        with urlopen(request, timeout=timeout) as response:
            content = response.read()
            frame = pd.read_csv(io.BytesIO(content), keep_default_na=False)
            normalized = normalize_public_market_ohlcv(frame, ticker)
            return {
                "ticker": str(ticker).upper(),
                "url": url,
                "attempt_status": "FETCHED",
                "http_status": int(getattr(response, "status", 200)),
                "row_count": int(len(normalized)),
                "error": "",
                "frame": normalized,
            }
    except HTTPError as exc:
        status = "PUBLIC_FILE_MISSING" if exc.code == 404 else "FETCH_FAILED"
        return _fetch_error(ticker, url, status, exc.code, str(exc))
    except (URLError, TimeoutError, OSError, ValueError, pd.errors.ParserError) as exc:
        return _fetch_error(ticker, url, "FETCH_FAILED", "", str(exc))


def normalize_public_market_ohlcv(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame(columns=["ticker", "date", "close", "volume"])
    frame = df.copy()
    date_col = _first_column(frame, ["time", "date", "trading_date", "tradingDate"])
    close_col = _first_column(frame, ["close", "close_price", "closePrice", "match_price"])
    volume_col = _first_column(frame, ["volume", "vol", "match_volume", "matching_volume"])
    if not date_col or not close_col:
        raise ValueError("Public market CSV is missing date or close column")
    out = pd.DataFrame(
        {
            "ticker": str(ticker).upper(),
            "date": pd.to_datetime(frame[date_col], errors="coerce"),
            "close": pd.to_numeric(frame[close_col], errors="coerce"),
            "volume": pd.to_numeric(frame[volume_col], errors="coerce") if volume_col else pd.Series(dtype=float),
        }
    )
    out = out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    return out


def compute_market_summary(df: pd.DataFrame) -> dict[str, Any]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return {
            "public_last_close": "",
            "public_last_price_date": "",
            "public_avg_volume_20d": "",
            "public_avg_volume_60d": "",
            "public_row_count": 0,
        }
    frame = df.sort_values("date").copy()
    last = frame.iloc[-1]
    return {
        "public_last_close": _to_float(last.get("close")),
        "public_last_price_date": pd.to_datetime(last.get("date")).date().isoformat(),
        "public_avg_volume_20d": _mean_last(frame.get("volume"), 20),
        "public_avg_volume_60d": _mean_last(frame.get("volume"), 60),
        "public_row_count": int(len(frame)),
    }


def crosscheck_market_row(
    legacy_row: dict[str, Any],
    public_summary: dict[str, Any],
    *,
    rank: int = 0,
    thresholds: dict[str, float] | None = None,
    fetch_status: str = "FETCHED",
    current_date: datetime | None = None,
) -> dict[str, Any]:
    thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    ticker = str(legacy_row.get("ticker") or public_summary.get("ticker") or "").upper()
    current_date = current_date or datetime.now(UTC)

    legacy_last_close = _to_float(legacy_row.get("last_close"))
    public_last_close = _to_float(public_summary.get("public_last_close"))
    legacy_volume_20d = _to_float(legacy_row.get("avg_volume_20d"))
    legacy_volume_60d = _to_float(legacy_row.get("avg_volume_60d"))
    public_volume_20d = _to_float(public_summary.get("public_avg_volume_20d"))
    public_volume_60d = _to_float(public_summary.get("public_avg_volume_60d"))
    legacy_date = str(legacy_row.get("last_price_date") or "").strip()
    public_date = str(public_summary.get("public_last_price_date") or "").strip()

    reason_parts: list[str] = []
    manual_review = False
    if fetch_status == "PUBLIC_FILE_MISSING":
        price_status = volume_status = "PUBLIC_FILE_MISSING"
        manual_review = True
        reason_parts.append("Public raw CSV missing for ticker.")
    elif fetch_status != "FETCHED":
        price_status = volume_status = "FETCH_FAILED"
        manual_review = True
        reason_parts.append("Public raw CSV fetch failed.")
    elif legacy_last_close is None:
        price_status = volume_status = "LEGACY_MARKET_MISSING"
        manual_review = True
        reason_parts.append("Legacy market row has no last_close.")
    else:
        price_abs_diff, price_diff_pct, unit_note = _best_price_difference(legacy_last_close, public_last_close)
        price_status = _diff_status(price_diff_pct, thresholds["price_minor_diff_pct"], thresholds["price_major_diff_pct"])
        volume_diff_pct = _relative_diff_pct(legacy_volume_60d, public_volume_60d)
        volume_status = _diff_status(volume_diff_pct, thresholds["volume_minor_diff_pct"], thresholds["volume_major_diff_pct"])
        if volume_diff_pct == "":
            volume_status = "LEGACY_MARKET_MISSING" if legacy_volume_60d is None else "PUBLIC_FILE_MISSING"
        if price_status in {"MAJOR_DIFF"} or volume_status in {"MAJOR_DIFF", "LEGACY_MARKET_MISSING", "PUBLIC_FILE_MISSING"}:
            manual_review = True
        if unit_note:
            reason_parts.append(unit_note)

    legacy_stale = _is_stale(legacy_date, current_date, int(thresholds["stale_days_threshold"]))
    public_stale = _is_stale(public_date, current_date, int(thresholds["stale_days_threshold"]))
    if legacy_stale:
        manual_review = True
        reason_parts.append("STALE_LEGACY_DATA")
    if public_stale:
        manual_review = True
        reason_parts.append("STALE_PUBLIC_DATA")

    if "price_abs_diff" not in locals():
        price_abs_diff = ""
        price_diff_pct = ""
    if "volume_diff_pct" not in locals():
        volume_diff_pct = ""

    return {
        "ticker": ticker,
        "rank": rank,
        "exchange": legacy_row.get("exchange", ""),
        "sector_raw": legacy_row.get("sector_raw", ""),
        "legacy_last_close": legacy_last_close if legacy_last_close is not None else "",
        "public_last_close": public_last_close if public_last_close is not None else "",
        "legacy_last_price_date": legacy_date,
        "public_last_price_date": public_date,
        "legacy_avg_volume_20d": legacy_volume_20d if legacy_volume_20d is not None else "",
        "public_avg_volume_20d": public_volume_20d if public_volume_20d is not None else "",
        "legacy_avg_volume_60d": legacy_volume_60d if legacy_volume_60d is not None else "",
        "public_avg_volume_60d": public_volume_60d if public_volume_60d is not None else "",
        "price_abs_diff": price_abs_diff,
        "price_relative_diff_pct": price_diff_pct,
        "volume_60d_relative_diff_pct": volume_diff_pct,
        "price_crosscheck_status": price_status,
        "volume_crosscheck_status": volume_status,
        "manual_review_required": manual_review,
        "reason": "; ".join(reason_parts) if reason_parts else "Targeted public market cross-check completed.",
    }


def _fetch_error(ticker: str, url: str, status: str, http_status: Any, error: str) -> dict[str, Any]:
    return {
        "ticker": str(ticker).upper(),
        "url": url,
        "attempt_status": status,
        "http_status": http_status,
        "row_count": 0,
        "error": error,
        "frame": pd.DataFrame(columns=["ticker", "date", "close", "volume"]),
    }


def _first_column(frame: pd.DataFrame, candidates: list[str]) -> str:
    lowered = {str(column).strip().lower(): column for column in frame.columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return str(lowered[candidate.lower()])
    return ""


def _mean_last(series: pd.Series | None, count: int) -> float | str:
    if series is None:
        return ""
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return ""
    return round(float(values.tail(count).mean()), 4)


def _best_price_difference(legacy_value: float | None, public_value: float | None) -> tuple[float | str, float | str, str]:
    if legacy_value is None or public_value is None:
        return "", "", ""
    candidates = [
        (legacy_value, public_value, ""),
        (legacy_value * 1000, public_value, "price_compared_after_legacy_x1000_unit_alignment"),
        (legacy_value, public_value * 1000, "price_compared_after_public_x1000_unit_alignment"),
    ]
    best = min(candidates, key=lambda item: _relative_diff_pct(item[0], item[1]) if _relative_diff_pct(item[0], item[1]) != "" else float("inf"))
    diff = abs(best[0] - best[1])
    return round(float(diff), 6), _relative_diff_pct(best[0], best[1]), best[2]


def _relative_diff_pct(left: float | None, right: float | None) -> float | str:
    if left is None or right is None:
        return ""
    denominator = max(abs(left), abs(right), 1.0)
    return round(abs(left - right) / denominator * 100, 6)


def _diff_status(diff_pct: float | str, minor: float, major: float) -> str:
    if diff_pct == "":
        return "PUBLIC_FILE_MISSING"
    if float(diff_pct) <= minor:
        return "AGREE"
    if float(diff_pct) <= major:
        return "MINOR_DIFF"
    return "MAJOR_DIFF"


def _is_stale(date_text: str, current_date: datetime, threshold_days: int) -> bool:
    if not date_text:
        return True
    parsed = pd.to_datetime(date_text, errors="coerce")
    if pd.isna(parsed):
        return True
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    return (current_date - parsed.to_pydatetime()).days > threshold_days


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None
