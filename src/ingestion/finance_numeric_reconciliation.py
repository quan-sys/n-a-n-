"""Numeric conflict checks for REAL-DATA-01I finance candidates."""

from __future__ import annotations

from itertools import combinations
from typing import Any

import pandas as pd


FINANCE_NUMERIC_CONFLICT_COLUMNS = [
    "ticker",
    "period",
    "field_name",
    "source_a",
    "value_a",
    "source_b",
    "value_b",
    "absolute_difference",
    "relative_difference",
    "conflict_status",
    "manual_review_required",
    "notes",
]


def reconcile_numeric_candidates(
    candidates: pd.DataFrame,
    *,
    tolerance_pct: float = 0.01,
    minor_variance_tolerance_pct: float = 0.03,
) -> pd.DataFrame:
    """Return pairwise source conflicts; single-source values are not confirmed."""

    if not isinstance(candidates, pd.DataFrame) or candidates.empty:
        return pd.DataFrame(columns=FINANCE_NUMERIC_CONFLICT_COLUMNS)
    rows: list[dict[str, Any]] = []
    group_columns = ["ticker", "period", "field_name"]
    for key, group in candidates.groupby(group_columns, dropna=False):
        ticker, period, field_name = key
        usable = group.dropna(subset=["value"])
        if usable["source_category"].nunique() < 2:
            continue
        for (_, left), (_, right) in combinations(usable.iterrows(), 2):
            value_a = float(left["value"])
            value_b = float(right["value"])
            absolute = abs(value_a - value_b)
            denominator = max(abs(value_a), abs(value_b), 1.0)
            relative = absolute / denominator
            if relative <= tolerance_pct:
                status = "FIELD_CONFIRMED_BY_MULTI_SOURCE"
                review = False
            elif relative <= minor_variance_tolerance_pct:
                status = "MINOR_SOURCE_VARIANCE_REVIEW"
                review = True
            else:
                status = "FIELD_CONFLICT_BETWEEN_SOURCES"
                review = True
            rows.append(
                {
                    "ticker": ticker,
                    "period": period,
                    "field_name": field_name,
                    "source_a": _source_id(left),
                    "value_a": value_a,
                    "source_b": _source_id(right),
                    "value_b": value_b,
                    "absolute_difference": absolute,
                    "relative_difference": relative,
                    "conflict_status": status,
                    "manual_review_required": review,
                    "notes": "conflicting finance evidence requires manual review" if review else "values within tolerance",
                }
            )
    return pd.DataFrame(rows, columns=FINANCE_NUMERIC_CONFLICT_COLUMNS)


def _source_id(row: pd.Series) -> str:
    return f"{row.get('source_category', '')}:{row.get('source_name', '')}"

