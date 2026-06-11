"""Import legacy structured finance as provisional evidence input.

The legacy data is useful for prioritizing official evidence collection, but it
is not official verified BCTC/BCTN data. This module preserves missing values,
strips old decision fields, and keeps one-source data at provisional confidence.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd


PROVISIONAL_CONFIDENCE = "provisional_structured"

FORBIDDEN_BIAS_FIELDS = {
    "buy_candidate",
    "fair_value",
    "margin_of_safety",
    "mos",
    "target_price",
    "valuation_score",
    "timing_score",
    "rr",
    "rsi_14",
    "composite_score",
    "sector_rank",
    "tier",
    "reason_code",
    "layer_failed",
    "investment_score",
    "buy_score",
    "sell_score",
    "upside",
    "watch_candidate",
}

LONG_COLUMNS = [
    "ticker",
    "period",
    "period_type",
    "fiscal_year",
    "field_name",
    "raw_value",
    "value",
    "unit_raw",
    "currency",
    "source_name",
    "source_type",
    "source_confidence",
    "source_url",
    "fetched_at",
    "cache_key",
    "legacy_function",
    "missing_flag",
    "parse_status",
    "notes",
    "source_layer",
]

WIDE_COLUMNS = [
    "ticker",
    "exchange",
    "company_name",
    "sector_raw",
    "industry_raw",
    "period",
    "period_type",
    "fiscal_year",
    "revenue",
    "gross_profit",
    "net_income",
    "total_assets",
    "total_liabilities",
    "equity",
    "cfo",
    "capex",
    "source_name",
    "source_confidence",
    "source_layer",
    "provisional_only",
    "fetched_at",
    "finance_completeness_score",
    "missing_fields",
    "source_count",
]

MARKET_COLUMNS = [
    "ticker",
    "exchange",
    "company_name",
    "sector_raw",
    "industry_raw",
    "last_close",
    "last_price_date",
    "avg_volume_10d",
    "avg_volume_20d",
    "avg_volume_60d",
    "trading_days_60d",
    "source_name",
    "source_confidence",
    "source_layer",
    "fetched_at",
    "stale_price_flag",
    "missing_price_flag",
    "low_liquidity_flag",
]

QUALITY_COLUMNS = [
    "ticker",
    "has_income_statement",
    "has_balance_sheet",
    "has_cash_flow",
    "has_market_price",
    "has_volume",
    "finance_field_count",
    "missing_required_fields",
    "legacy_cache_status",
    "export_status",
    "notes",
    "source_layer",
]

CROSSCHECK_COLUMNS = [
    "ticker",
    "period",
    "field_name",
    "source_count",
    "source_names",
    "value_count",
    "min_value",
    "max_value",
    "absolute_difference",
    "relative_difference_pct",
    "crosscheck_status",
    "confidence_level",
    "manual_review_required",
    "reason",
]


def import_legacy_structured_finance(input_dir: Path | str, output_dir: Path | str) -> dict[str, Any]:
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    long_frame = _normalize_long(_read_csv(input_path / "legacy_structured_finance_long.csv"))
    wide_frame = _normalize_wide(_read_csv(input_path / "legacy_structured_finance_latest_wide.csv"))
    market_frame = _normalize_market(_read_csv(input_path / "legacy_market_liquidity.csv"))
    quality_frame = _normalize_quality(_read_csv(input_path / "legacy_data_quality_flags.csv"))
    crosscheck = build_source_crosscheck_matrix(long_frame)

    long_frame.to_csv(output_path / "provisional_structured_finance_long.csv", index=False)
    long_frame.to_csv(output_path / "provisional_finance_long.csv", index=False)
    wide_frame.to_csv(output_path / "provisional_finance_latest_wide.csv", index=False)
    market_frame.to_csv(output_path / "provisional_market_liquidity.csv", index=False)
    quality_frame.to_csv(output_path / "provisional_data_quality_flags.csv", index=False)
    crosscheck.to_csv(output_path / "source_crosscheck_matrix.csv", index=False)

    summary = {
        "imported_finance_long_rows": int(len(long_frame)),
        "imported_finance_wide_rows": int(len(wide_frame)),
        "imported_market_rows": int(len(market_frame)),
        "quality_rows": int(len(quality_frame)),
        "crosscheck_rows": int(len(crosscheck)),
        "crosscheck_status_counts": _value_counts(crosscheck, "crosscheck_status"),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    (output_path / "legacy_import_run_summary.md").write_text(_summary_markdown(summary), encoding="utf-8")
    return summary


def build_source_crosscheck_matrix(long_frame: pd.DataFrame, tolerance_pct: float = 1.0) -> pd.DataFrame:
    frame = _strip_forbidden_columns(long_frame)
    if frame.empty:
        return pd.DataFrame(columns=CROSSCHECK_COLUMNS)
    for column in ["ticker", "period", "field_name", "source_name", "value"]:
        if column not in frame.columns:
            frame[column] = ""
    rows: list[dict[str, Any]] = []
    grouped = frame.groupby(["ticker", "period", "field_name"], dropna=False, sort=True)
    for (ticker, period, field_name), group in grouped:
        source_names = sorted({str(value).strip() for value in group["source_name"] if str(value).strip()})
        values = pd.to_numeric(group["value"], errors="coerce").dropna()
        source_count = len(source_names)
        value_count = int(len(values))
        min_value = float(values.min()) if value_count else ""
        max_value = float(values.max()) if value_count else ""
        absolute_difference = float(max_value - min_value) if value_count else ""
        relative_difference_pct = _relative_difference_pct(min_value, max_value) if value_count else ""
        if source_count < 2:
            status = "ONE_SOURCE_ONLY"
            confidence = "PROVISIONAL_LOW"
            manual_review = True
            reason = "Single structured legacy source; cannot be high confidence."
        elif value_count < source_count:
            status = "MISSING_VALUE_IN_SOURCES"
            confidence = "PROVISIONAL_LOW"
            manual_review = True
            reason = "At least one source lacks a numeric value."
        elif float(relative_difference_pct) <= tolerance_pct:
            status = "MULTI_SOURCE_AGREES"
            confidence = "PROVISIONAL_MEDIUM"
            manual_review = False
            reason = "Structured sources agree within tolerance, still not official verified."
        else:
            status = "SOURCE_CONFLICT"
            confidence = "PROVISIONAL_LOW"
            manual_review = True
            reason = "Structured sources conflict; manual review required."
        rows.append(
            {
                "ticker": ticker,
                "period": period,
                "field_name": field_name,
                "source_count": source_count,
                "source_names": ";".join(source_names),
                "value_count": value_count,
                "min_value": min_value,
                "max_value": max_value,
                "absolute_difference": absolute_difference,
                "relative_difference_pct": relative_difference_pct,
                "crosscheck_status": status,
                "confidence_level": confidence,
                "manual_review_required": manual_review,
                "reason": reason,
            }
        )
    return pd.DataFrame(rows, columns=CROSSCHECK_COLUMNS)


def forbidden_bias_columns(columns: list[str] | pd.Index) -> list[str]:
    return [column for column in columns if str(column).strip().lower() in FORBIDDEN_BIAS_FIELDS]


def _normalize_long(frame: pd.DataFrame) -> pd.DataFrame:
    frame = _strip_forbidden_columns(frame)
    frame = _ensure_columns(frame, [column for column in LONG_COLUMNS if column != "source_layer"])
    frame["source_confidence"] = PROVISIONAL_CONFIDENCE
    frame["source_layer"] = PROVISIONAL_CONFIDENCE
    return frame[LONG_COLUMNS]


def _normalize_wide(frame: pd.DataFrame) -> pd.DataFrame:
    frame = _strip_forbidden_columns(frame)
    frame = _ensure_columns(frame, [column for column in WIDE_COLUMNS if column != "source_layer"])
    frame["source_confidence"] = PROVISIONAL_CONFIDENCE
    frame["source_layer"] = PROVISIONAL_CONFIDENCE
    frame["provisional_only"] = True
    return frame[WIDE_COLUMNS]


def _normalize_market(frame: pd.DataFrame) -> pd.DataFrame:
    frame = _strip_forbidden_columns(frame)
    frame = _ensure_columns(frame, [column for column in MARKET_COLUMNS if column != "source_layer"])
    frame["source_confidence"] = PROVISIONAL_CONFIDENCE
    frame["source_layer"] = PROVISIONAL_CONFIDENCE
    return frame[MARKET_COLUMNS]


def _normalize_quality(frame: pd.DataFrame) -> pd.DataFrame:
    frame = _strip_forbidden_columns(frame)
    frame = _ensure_columns(frame, [column for column in QUALITY_COLUMNS if column != "source_layer"])
    frame["source_layer"] = PROVISIONAL_CONFIDENCE
    return frame[QUALITY_COLUMNS]


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, keep_default_na=False)


def _strip_forbidden_columns(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame() if not isinstance(frame, pd.DataFrame) else frame.copy()
    columns_to_drop = forbidden_bias_columns(frame.columns)
    return frame.drop(columns=columns_to_drop, errors="ignore").copy()


def _ensure_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    frame = frame.copy()
    for column in columns:
        if column not in frame.columns:
            frame[column] = ""
    return frame


def _relative_difference_pct(min_value: float, max_value: float) -> float:
    denominator = max(abs(min_value), abs(max_value), 1.0)
    return round(abs(max_value - min_value) / denominator * 100, 6)


def _value_counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame.columns:
        return {}
    counts = Counter(frame[column].astype(str))
    return dict(sorted((key, int(value)) for key, value in counts.items()))


def _summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Legacy Structured Finance Import 01",
        "",
        "## Counts",
        f"- imported_finance_long_rows: {summary['imported_finance_long_rows']}",
        f"- imported_finance_wide_rows: {summary['imported_finance_wide_rows']}",
        f"- imported_market_rows: {summary['imported_market_rows']}",
        f"- quality_rows: {summary['quality_rows']}",
        f"- crosscheck_rows: {summary['crosscheck_rows']}",
        "",
        "## Cross-Check Status",
    ]
    for status, count in summary["crosscheck_status_counts"].items():
        lines.append(f"- {status}: {count}")
    lines.extend(
        [
            "",
            "## Safety",
            "- Imported finance rows are provisional_structured only.",
            "- Missing values are preserved and not zero-filled.",
            "- Forbidden legacy valuation/timing/recommendation fields are dropped.",
            "- No official verification, OCR, PDF parsing, REAL-DATA-02, Step19, or 01I-G was run.",
            "",
            f"_Generated at {summary['generated_at']}._",
        ]
    )
    return "\n".join(lines) + "\n"
