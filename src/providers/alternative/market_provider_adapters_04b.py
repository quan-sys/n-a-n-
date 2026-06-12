"""Provider adapters for the 04B alternative market consensus sandbox."""

from __future__ import annotations

import importlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd


OBSERVATION_COLUMNS = [
    "ticker",
    "source_provider_id",
    "source_family",
    "observation_status",
    "last_price_date",
    "last_close",
    "avg_volume_20d",
    "avg_volume_60d",
    "trading_days_60d",
    "price_basis",
    "is_current_enough",
    "is_independent_current_candidate",
    "is_historical_fallback_only",
    "error_type",
    "error_message",
    "price_date_gap_days",
    "price_pct_diff",
    "volume_60d_pct_diff",
    "price_match_status",
    "volume_match_status",
    "manual_review_flag",
]

RUNTIME_STATUS_COLUMNS = [
    "provider_id",
    "package_name",
    "source_families",
    "runtime_status",
    "import_status",
    "provider_importable",
    "attempted_market_fetch",
    "network_used",
    "market_data_fetched",
    "finance_data_fetched",
    "usable_observation_count",
    "error_type",
    "error_message",
]

PRIMARY_SNAPSHOT_PROVIDER_ID = "vnstock_primary_reference"
PRIMARY_SOURCE_FAMILY = "vnstock_vci"
RAW_CACHE_PROVIDER_ID = "raw_cache_current_market_03"
STATIC_FALLBACK_PROVIDER_ID = "vnstock_market_data_historical_fallback"
STATIC_FALLBACK_SOURCE_FAMILY = "static_github_historical"


@dataclass
class ProviderAdapterResult:
    runtime_status: pd.DataFrame
    observations: pd.DataFrame


ProviderFetcher = Callable[[Any, list[str], list[str], dict[str, Any]], pd.DataFrame | list[dict[str, Any]]]


def build_primary_snapshot_observations(snapshot: pd.DataFrame, config: dict[str, Any]) -> ProviderAdapterResult:
    rows = []
    for _, row in _normalize_tickers(snapshot).iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        status = "PRIMARY_OK"
        if _as_bool(row.get("missing_market_flag")) or _is_missing(row.get("last_close")) or _is_missing(row.get("last_price_date")):
            status = "PRIMARY_MISSING"
        elif _as_bool(row.get("stale_price_flag")):
            status = "REFERENCE_STALE"
        rows.append(
            observation_row(
                ticker=ticker,
                source_provider_id=PRIMARY_SNAPSHOT_PROVIDER_ID,
                source_family=_primary_family(config),
                observation_status=status,
                last_price_date=row.get("last_price_date", ""),
                last_close=row.get("last_close", ""),
                avg_volume_20d=row.get("avg_volume_20d", ""),
                avg_volume_60d=row.get("avg_volume_60d", ""),
                trading_days_60d=row.get("trading_days_60d", ""),
                price_basis="unadjusted",
                is_current_enough=status == "PRIMARY_OK",
                is_independent_current_candidate=False,
                is_historical_fallback_only=False,
            )
        )
    runtime = runtime_row(
        provider_id=PRIMARY_SNAPSHOT_PROVIDER_ID,
        package_name="",
        source_families=[_primary_family(config)],
        runtime_status="PRIMARY_SNAPSHOT_AVAILABLE" if rows else "PRIMARY_MISSING",
        import_status="LOCAL_FILE",
        provider_importable=True,
        attempted_market_fetch=False,
        network_used=False,
        market_data_fetched=False,
        finance_data_fetched=False,
        usable_observation_count=sum(1 for row in rows if row["observation_status"] == "PRIMARY_OK"),
    )
    return ProviderAdapterResult(
        runtime_status=pd.DataFrame([runtime], columns=RUNTIME_STATUS_COLUMNS),
        observations=pd.DataFrame(rows, columns=OBSERVATION_COLUMNS),
    )


def build_raw_cache_observations(
    *,
    tickers: list[str],
    raw_cache_dir: str | Path | None,
    primary_observations: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    if raw_cache_dir is None:
        return pd.DataFrame(columns=OBSERVATION_COLUMNS)
    cache_dir = Path(raw_cache_dir)
    if not cache_dir.exists():
        return pd.DataFrame(columns=OBSERVATION_COLUMNS)
    primary_by_ticker = _index_by_ticker(primary_observations)
    rows = []
    for ticker in tickers:
        history_path = cache_dir / f"{ticker}_history.csv"
        if not history_path.exists():
            continue
        parsed = _recompute_from_history(history_path)
        if not parsed:
            continue
        primary = primary_by_ticker.get(ticker, {})
        current_enough = _within_gap(primary.get("last_price_date"), parsed.get("last_price_date"), config)
        rows.append(
            observation_row(
                ticker=ticker,
                source_provider_id=RAW_CACHE_PROVIDER_ID,
                source_family=_primary_family(config),
                observation_status="NOT_INDEPENDENT_SAME_SOURCE_FAMILY",
                last_price_date=parsed.get("last_price_date", ""),
                last_close=parsed.get("last_close", ""),
                avg_volume_20d=parsed.get("avg_volume_20d", ""),
                avg_volume_60d=parsed.get("avg_volume_60d", ""),
                trading_days_60d=parsed.get("trading_days_60d", ""),
                price_basis="unadjusted",
                is_current_enough=current_enough,
                is_independent_current_candidate=False,
                is_historical_fallback_only=False,
            )
        )
    return pd.DataFrame(rows, columns=OBSERVATION_COLUMNS)


def build_static_historical_fallback_observations(
    *,
    tickers: list[str],
    prior_crosscheck_path: str | Path | None,
    config: dict[str, Any],
) -> ProviderAdapterResult:
    path = Path(prior_crosscheck_path) if prior_crosscheck_path else None
    rows = []
    if path and path.exists():
        frame = _read_csv(path)
        if not frame.empty and "ticker" in frame.columns:
            frame = _normalize_tickers(frame)
            frame = frame[frame["ticker"].isin(set(tickers))].copy()
            if "reference_source_name" in frame.columns:
                frame = frame[frame["reference_source_name"].astype(str).eq("provisional_crosscheck_02_public_historical")]
            for _, row in frame.iterrows():
                rows.append(
                    observation_row(
                        ticker=str(row.get("ticker", "")).upper(),
                        source_provider_id=STATIC_FALLBACK_PROVIDER_ID,
                        source_family=STATIC_FALLBACK_SOURCE_FAMILY,
                        observation_status="HISTORICAL_FALLBACK_ONLY",
                        last_price_date=row.get("reference_last_price_date", ""),
                        last_close=row.get("reference_last_close", ""),
                        avg_volume_20d=row.get("reference_avg_volume_20d", ""),
                        avg_volume_60d=row.get("reference_avg_volume_60d", ""),
                        trading_days_60d=row.get("reference_trading_days_60d", ""),
                        price_basis="unknown",
                        is_current_enough=False
                        if not _static_historical_is_current_confirmation(config)
                        else _not_missing(row.get("reference_last_price_date")) and _not_missing(row.get("reference_last_close")),
                        is_independent_current_candidate=False,
                        is_historical_fallback_only=True,
                    )
                )
    runtime = runtime_row(
        provider_id=STATIC_FALLBACK_PROVIDER_ID,
        package_name="",
        source_families=[STATIC_FALLBACK_SOURCE_FAMILY],
        runtime_status="HISTORICAL_FALLBACK_ONLY" if rows else "PROVIDER_NO_DATA",
        import_status="NO_PACKAGE",
        provider_importable=False,
        attempted_market_fetch=False,
        network_used=False,
        market_data_fetched=False,
        finance_data_fetched=False,
        usable_observation_count=0,
        error_type="" if rows else "NoLocalStaticFallback",
        error_message="" if rows else "No local static historical fallback rows were found for the pilot tickers.",
    )
    return ProviderAdapterResult(
        runtime_status=pd.DataFrame([runtime], columns=RUNTIME_STATUS_COLUMNS),
        observations=pd.DataFrame(rows, columns=OBSERVATION_COLUMNS),
    )


def run_optional_market_provider(
    *,
    provider_id: str,
    package_name: str,
    source_families: list[str],
    tickers: list[str],
    config: dict[str, Any],
    import_module_func: Callable[[str], Any] | None = None,
    fetcher_func: ProviderFetcher | None = None,
) -> ProviderAdapterResult:
    importer = import_module_func or importlib.import_module
    try:
        module = importer(package_name)
    except Exception as exc:  # noqa: BLE001 - missing optional package is an expected 04B path.
        runtime = runtime_row(
            provider_id=provider_id,
            package_name=package_name,
            source_families=source_families,
            runtime_status="PROVIDER_NOT_IMPORTABLE",
            import_status="NOT_IMPORTABLE",
            provider_importable=False,
            attempted_market_fetch=False,
            network_used=False,
            market_data_fetched=False,
            finance_data_fetched=False,
            usable_observation_count=0,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        observations = _unavailable_observations(tickers, provider_id, source_families, "PROVIDER_NOT_IMPORTABLE", type(exc).__name__, str(exc))
        return ProviderAdapterResult(pd.DataFrame([runtime], columns=RUNTIME_STATUS_COLUMNS), observations)

    runtime_status = "PROVIDER_NO_DATA"
    error_type = ""
    error_message = ""
    market_data_fetched = False
    observations = pd.DataFrame(columns=OBSERVATION_COLUMNS)
    network_used = bool(((config.get("run_policy") or {}).get("allow_network_fetch", False)))
    try:
        fetcher = fetcher_func or _default_fetcher(provider_id)
        if fetcher is None:
            error_type = "NoSupportedFetcher"
            error_message = "Package importable, but no supported 04B market fetch interface was detected."
        else:
            raw_rows = fetcher(module, tickers, source_families, config)
            observations = normalize_provider_market_rows(
                raw_rows,
                provider_id=provider_id,
                fallback_source_family=source_families[0] if source_families else "",
            )
            market_data_fetched = not observations.empty
            runtime_status = "PROVIDER_OK" if market_data_fetched else "PROVIDER_NO_DATA"
    except Exception as exc:  # noqa: BLE001 - provider errors must not fail the full run.
        runtime_status = "PROVIDER_ERROR"
        error_type = type(exc).__name__
        error_message = str(exc)
        observations = _unavailable_observations(tickers, provider_id, source_families, "PROVIDER_ERROR", error_type, error_message)

    if observations.empty and runtime_status == "PROVIDER_NO_DATA":
        observations = _unavailable_observations(tickers, provider_id, source_families, "PROVIDER_NO_DATA", error_type, error_message)
    usable = int(
        observations["last_close"].map(_not_missing).sum()
        if not observations.empty and "last_close" in observations.columns
        else 0
    )
    runtime = runtime_row(
        provider_id=provider_id,
        package_name=package_name,
        source_families=source_families,
        runtime_status=runtime_status,
        import_status="IMPORT_OK",
        provider_importable=True,
        attempted_market_fetch=True,
        network_used=network_used and market_data_fetched,
        market_data_fetched=market_data_fetched,
        finance_data_fetched=False,
        usable_observation_count=usable,
        error_type=error_type,
        error_message=error_message,
    )
    sleep_seconds = float(((config.get("run_policy") or {}).get("sleep_seconds_between_provider_calls", 0) or 0))
    if sleep_seconds > 0 and market_data_fetched:
        time.sleep(sleep_seconds)
    return ProviderAdapterResult(pd.DataFrame([runtime], columns=RUNTIME_STATUS_COLUMNS), observations)


def normalize_provider_market_rows(
    rows: pd.DataFrame | list[dict[str, Any]],
    *,
    provider_id: str,
    fallback_source_family: str,
) -> pd.DataFrame:
    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=OBSERVATION_COLUMNS)
    frame = _normalize_tickers(frame)
    out_rows = []
    for _, row in frame.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        source_family = str(row.get("source_family", "") or fallback_source_family)
        last_close = _first_value(row, ["last_close", "close", "close_price"])
        adjusted_close = _first_value(row, ["adjusted_close", "adj_close"])
        price_basis = str(row.get("price_basis", "") or "unadjusted")
        if _is_missing(last_close) and _not_missing(adjusted_close):
            last_close = adjusted_close
            price_basis = "adjusted"
        last_date = _first_value(row, ["last_price_date", "date", "trading_date", "time"])
        avg_volume_20d = _first_value(row, ["avg_volume_20d", "volume_20d", "avg_vol_20d"])
        avg_volume_60d = _first_value(row, ["avg_volume_60d", "volume_60d", "avg_vol_60d"])
        out_rows.append(
            observation_row(
                ticker=ticker,
                source_provider_id=provider_id,
                source_family=source_family,
                observation_status="PROVIDER_OK",
                last_price_date=_date_label(last_date),
                last_close=last_close,
                avg_volume_20d=avg_volume_20d,
                avg_volume_60d=avg_volume_60d,
                trading_days_60d=_first_value(row, ["trading_days_60d", "days_60d"]),
                price_basis=price_basis,
                is_current_enough=_not_missing(last_date) and _not_missing(last_close),
                is_independent_current_candidate=source_family in {"cafef", "vndirect"},
                is_historical_fallback_only=False,
            )
        )
    return pd.DataFrame(out_rows, columns=OBSERVATION_COLUMNS)


def runtime_row(
    *,
    provider_id: str,
    package_name: str,
    source_families: list[str],
    runtime_status: str,
    import_status: str,
    provider_importable: bool,
    attempted_market_fetch: bool,
    network_used: bool,
    market_data_fetched: bool,
    finance_data_fetched: bool,
    usable_observation_count: int,
    error_type: str = "",
    error_message: str = "",
) -> dict[str, Any]:
    return {
        "provider_id": provider_id,
        "package_name": package_name,
        "source_families": ";".join(source_families),
        "runtime_status": runtime_status,
        "import_status": import_status,
        "provider_importable": provider_importable,
        "attempted_market_fetch": attempted_market_fetch,
        "network_used": network_used,
        "market_data_fetched": market_data_fetched,
        "finance_data_fetched": finance_data_fetched,
        "usable_observation_count": usable_observation_count,
        "error_type": error_type,
        "error_message": error_message,
    }


def observation_row(
    *,
    ticker: str,
    source_provider_id: str,
    source_family: str,
    observation_status: str,
    last_price_date: Any = "",
    last_close: Any = "",
    avg_volume_20d: Any = "",
    avg_volume_60d: Any = "",
    trading_days_60d: Any = "",
    price_basis: str = "",
    is_current_enough: bool = False,
    is_independent_current_candidate: bool = False,
    is_historical_fallback_only: bool = False,
    error_type: str = "",
    error_message: str = "",
    price_date_gap_days: Any = "",
    price_pct_diff: Any = "",
    volume_60d_pct_diff: Any = "",
    price_match_status: str = "",
    volume_match_status: str = "",
    manual_review_flag: bool = False,
) -> dict[str, Any]:
    return {
        "ticker": str(ticker).strip().upper(),
        "source_provider_id": source_provider_id,
        "source_family": source_family,
        "observation_status": observation_status,
        "last_price_date": _date_label(last_price_date),
        "last_close": last_close,
        "avg_volume_20d": avg_volume_20d,
        "avg_volume_60d": avg_volume_60d,
        "trading_days_60d": trading_days_60d,
        "price_basis": price_basis,
        "is_current_enough": bool(is_current_enough),
        "is_independent_current_candidate": bool(is_independent_current_candidate),
        "is_historical_fallback_only": bool(is_historical_fallback_only),
        "error_type": error_type,
        "error_message": error_message,
        "price_date_gap_days": price_date_gap_days,
        "price_pct_diff": price_pct_diff,
        "volume_60d_pct_diff": volume_60d_pct_diff,
        "price_match_status": price_match_status,
        "volume_match_status": volume_match_status,
        "manual_review_flag": bool(manual_review_flag),
    }


def _default_fetcher(provider_id: str) -> ProviderFetcher | None:
    if provider_id == "vnquant_secondary_candidate":
        return _fetch_vnquant_if_supported
    return None


def _fetch_vnquant_if_supported(module: Any, tickers: list[str], source_families: list[str], config: dict[str, Any]) -> pd.DataFrame:
    loader_cls = getattr(module, "DataLoader", None)
    if loader_cls is None:
        return pd.DataFrame()
    end_date = datetime.now(UTC).date()
    start_date = end_date - timedelta(days=120)
    rows = []
    family_to_source = {"cafef": "cafe", "vndirect": "vnd"}
    for family in source_families:
        data_source = family_to_source.get(family)
        if not data_source:
            continue
        for ticker in tickers:
            loader = loader_cls(symbols=ticker, start=start_date.isoformat(), end=end_date.isoformat(), data_source=data_source, minimal=True)
            frame = loader.download()
            normalized = _last_market_point(frame, ticker=ticker, source_family=family)
            if normalized:
                rows.append(normalized)
    return pd.DataFrame(rows)


def _last_market_point(frame: Any, *, ticker: str, source_family: str) -> dict[str, Any]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return {}
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = ["_".join(str(part) for part in column if str(part)) for column in data.columns]
    date_col = _first_column(data, ["date", "time", "trading_date"])
    close_col = _first_column(data, ["close", "close_price", "adjust", "adjusted_close", "adj_close"])
    volume_col = _first_column(data, ["volume", "vol", "match_volume"])
    if not date_col and isinstance(data.index, pd.DatetimeIndex):
        data = data.reset_index().rename(columns={"index": "date"})
        date_col = "date"
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
        "ticker": ticker,
        "source_family": source_family,
        "last_price_date": out.iloc[-1]["date"].date().isoformat(),
        "last_close": float(out.iloc[-1]["close"]),
        "avg_volume_20d": round(float(volumes.tail(20).mean()), 4) if not volumes.empty else "",
        "avg_volume_60d": round(float(volumes.tail(60).mean()), 4) if not volumes.empty else "",
        "trading_days_60d": int(min(len(volumes), 60)),
        "price_basis": "unadjusted",
    }


def _unavailable_observations(tickers: list[str], provider_id: str, source_families: list[str], status: str, error_type: str, error_message: str) -> pd.DataFrame:
    rows = [
        observation_row(
            ticker=ticker,
            source_provider_id=provider_id,
            source_family=family,
            observation_status=status,
            error_type=error_type,
            error_message=error_message,
        )
        for ticker in tickers
        for family in source_families
    ]
    return pd.DataFrame(rows, columns=OBSERVATION_COLUMNS)


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


def _primary_family(config: dict[str, Any]) -> str:
    rules = config.get("source_family_rules") or {}
    return str(rules.get("primary_source_family") or PRIMARY_SOURCE_FAMILY)


def _static_historical_is_current_confirmation(config: dict[str, Any]) -> bool:
    rules = config.get("source_family_rules") or {}
    return bool(rules.get("static_github_historical_is_current_confirmation", False))


def _within_gap(left: Any, right: Any, config: dict[str, Any]) -> bool:
    gap = _date_gap_days(left, right)
    if gap is None:
        return False
    threshold = int(((config.get("comparison") or {}).get("max_current_reference_gap_days", 5) or 5))
    return abs(gap) <= threshold


def _date_gap_days(left: Any, right: Any) -> int | None:
    left_date = pd.to_datetime(left, errors="coerce")
    right_date = pd.to_datetime(right, errors="coerce")
    if pd.isna(left_date) or pd.isna(right_date):
        return None
    return int((left_date.date() - right_date.date()).days)


def _index_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty or "ticker" not in frame.columns:
        return {}
    return {str(row.get("ticker", "")).upper(): row.to_dict() for _, row in frame.iterrows()}


def _normalize_tickers(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "ticker" in out.columns:
        out["ticker"] = out["ticker"].astype(str).str.strip().str.upper()
    return out


def _read_csv(path: str | Path) -> pd.DataFrame:
    target = Path(path)
    if not target.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(target, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _first_column(frame: pd.DataFrame, candidates: list[str]) -> str:
    lowered = {str(column).strip().lower(): str(column) for column in frame.columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return ""


def _first_value(row: pd.Series, candidates: list[str]) -> Any:
    lowered = {str(key).strip().lower(): key for key in row.index}
    for candidate in candidates:
        key = lowered.get(candidate.lower())
        if key is not None and _not_missing(row.get(key)):
            return row.get(key)
    return ""


def _date_label(value: Any) -> str:
    if _is_missing(value):
        return ""
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return parsed.date().isoformat()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _is_missing(value: Any) -> bool:
    return value is None or str(value).strip() == "" or str(value).strip().lower() in {"nan", "none", "null"}


def _not_missing(value: Any) -> bool:
    return not _is_missing(value)
