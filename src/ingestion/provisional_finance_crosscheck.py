"""Finance cross-check scaffolding for provisional structured sources."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingestion.legacy_structured_finance_importer import FORBIDDEN_BIAS_FIELDS


FINANCE_CROSSCHECK_COLUMNS = [
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
    "finance_crosscheck_status",
    "confidence_level",
    "manual_review_required",
    "reason",
]

SUMMARY_COLUMNS = ["metric", "value"]


def load_finance_sources(primary_finance: Path | str, optional_source_dir: Path | str) -> tuple[pd.DataFrame, list[str], list[str]]:
    primary_path = Path(primary_finance)
    if not primary_path.exists():
        raise FileNotFoundError(f"Missing primary finance source: {primary_path}")
    frames = [_prepare_source_frame(pd.read_csv(primary_path, keep_default_na=False), primary_path, required=True)]
    optional_root = Path(optional_source_dir)
    present_optional: list[str] = []
    missing_optional: list[str] = []
    for subdir in ["cafef_structured_finance", "vietstock_structured_finance", "manual_finance_uploads"]:
        folder = optional_root / subdir
        files = sorted(folder.glob("*.csv")) if folder.exists() else []
        if not files:
            missing_optional.append(str(folder))
            continue
        for file_path in files:
            frames.append(_prepare_source_frame(pd.read_csv(file_path, keep_default_na=False), file_path, required=False))
            present_optional.append(str(file_path))
    return pd.concat(frames, ignore_index=True), present_optional, missing_optional


def build_finance_crosscheck_matrix(finance_long: pd.DataFrame, tolerance_pct: float = 1.0) -> pd.DataFrame:
    frame = _strip_forbidden(finance_long)
    if frame.empty:
        return pd.DataFrame(columns=FINANCE_CROSSCHECK_COLUMNS)
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
        abs_diff = float(max_value - min_value) if value_count else ""
        rel_diff = _relative_difference_pct(min_value, max_value) if value_count else ""
        if source_count < 2:
            status = "ONE_SOURCE_ONLY"
            confidence = "PROVISIONAL_LOW"
            manual_review = True
            reason = "No second provisional finance source file is available."
        elif value_count < source_count:
            status = "MISSING_VALUE_IN_SOURCES"
            confidence = "PROVISIONAL_LOW"
            manual_review = True
            reason = "At least one source has a missing value; no zero-fill was applied."
        elif float(rel_diff) <= tolerance_pct:
            status = "MULTI_SOURCE_AGREES"
            confidence = "PROVISIONAL_MEDIUM"
            manual_review = False
            reason = "Provisional structured sources agree within tolerance; not official verified."
        else:
            status = "SOURCE_CONFLICT"
            confidence = "PROVISIONAL_LOW"
            manual_review = True
            reason = "Provisional structured sources conflict; manual review required."
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
                "absolute_difference": abs_diff,
                "relative_difference_pct": rel_diff,
                "finance_crosscheck_status": status,
                "confidence_level": confidence,
                "manual_review_required": manual_review,
                "reason": reason,
            }
        )
    return pd.DataFrame(rows, columns=FINANCE_CROSSCHECK_COLUMNS)


def build_finance_crosscheck_summary(matrix: pd.DataFrame, present_optional: list[str], missing_optional: list[str]) -> pd.DataFrame:
    rows = [
        {"metric": "crosscheck_rows", "value": len(matrix)},
        {"metric": "optional_sources_present", "value": len(present_optional)},
        {"metric": "optional_source_paths_present", "value": ";".join(present_optional)},
        {"metric": "optional_source_dirs_missing_or_empty", "value": len(missing_optional)},
    ]
    if not matrix.empty:
        for status, count in Counter(matrix["finance_crosscheck_status"].astype(str)).items():
            rows.append({"metric": f"status_{status}", "value": int(count)})
        for source_count, count in Counter(matrix["source_count"].astype(str)).items():
            rows.append({"metric": f"source_count_{source_count}", "value": int(count)})
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)


def missing_optional_sources_markdown(missing_optional: list[str]) -> str:
    lines = [
        "# Missing optional provisional finance sources",
        "",
        "No aggressive live crawling was run. Optional sources are used only when local CSV files exist.",
        "",
    ]
    if not missing_optional:
        lines.append("- none")
    else:
        for path in missing_optional:
            lines.append(f"- {path}")
    return "\n".join(lines) + "\n"


def _prepare_source_frame(frame: pd.DataFrame, path: Path, *, required: bool) -> pd.DataFrame:
    frame = _strip_forbidden(frame)
    for column in ["ticker", "period", "field_name", "value", "source_name", "source_confidence", "source_layer"]:
        if column not in frame.columns:
            frame[column] = ""
    source_label = "legacy_primary_provisional" if required else f"optional_{path.parent.name}_{path.stem}"
    frame["source_name"] = frame["source_name"].replace("", source_label)
    frame["source_confidence"] = "provisional_structured"
    frame["source_layer"] = "provisional_structured"
    return frame


def _strip_forbidden(frame: pd.DataFrame) -> pd.DataFrame:
    forbidden = [column for column in frame.columns if str(column).strip().lower() in FORBIDDEN_BIAS_FIELDS]
    return frame.drop(columns=forbidden, errors="ignore").copy()


def _relative_difference_pct(min_value: float, max_value: float) -> float:
    denominator = max(abs(min_value), abs(max_value), 1.0)
    return round(abs(max_value - min_value) / denominator * 100, 6)
