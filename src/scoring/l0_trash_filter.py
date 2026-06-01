"""L0 Trash Filter for data-poor, risky, or unusable stocks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None


L0_OUTPUT_COLUMNS = [
    "ticker",
    "l0_status",
    "l0_score",
    "l0_reject_reasons",
    "l0_warning_flags",
    "evidence_fields",
    "confidence",
    "manual_review_required",
]

L0_REJECT_LOG_COLUMNS = [
    "ticker",
    "reject_layer",
    "reject_reason",
    "evidence_fields",
    "confidence",
]

DEFAULT_L0_RULES: dict[str, Any] = {
    "status_priority": [
        "L0_REJECT",
        "INSUFFICIENT_DATA_FOR_L0",
        "L0_MANUAL_REVIEW",
        "L0_WATCH_ONLY",
        "L0_PASS",
    ],
    "scoring": {
        "starting_score": 100,
        "minimum_score": 0,
        "penalties": {
            "missing_ticker": 100,
            "missing_market_data": 60,
            "missing_financial_data": 60,
            "low_data_confidence": 30,
            "source_conflict": 40,
            "data_error": 70,
            "stale_price_data": 20,
            "very_low_liquidity": 50,
            "low_liquidity": 25,
            "market_cap_missing": 10,
            "market_cap_extremely_small": 40,
            "negative_equity": 70,
            "persistent_losses": 60,
            "debt_pressure": 40,
            "negative_operating_cash_flow": 40,
            "critical_disclosure": 80,
        },
    },
    "data_availability": {
        "missing_ticker_status": "L0_REJECT",
        "missing_market_data_status": "INSUFFICIENT_DATA_FOR_L0",
        "missing_financial_data_status": "INSUFFICIENT_DATA_FOR_L0",
        "low_confidence_status": "L0_MANUAL_REVIEW",
        "source_conflict_status": "L0_MANUAL_REVIEW",
        "data_error_status": "L0_REJECT",
        "stale_data_status": "L0_MANUAL_REVIEW",
    },
    "liquidity": {
        "avg_trading_value_reject_below": 100000000,
        "avg_trading_value_watch_below": 1000000000,
        "avg_volume_reject_below": 1000,
        "avg_volume_watch_below": 10000,
        "max_zero_volume_day_ratio": 0.5,
        "very_low_liquidity_status": "L0_REJECT",
        "low_liquidity_status": "L0_WATCH_ONLY",
        "stale_price_status": "L0_MANUAL_REVIEW",
    },
    "market_size": {
        "require_market_cap": False,
        "market_cap_column": "market_cap",
        "market_cap_missing_status": "L0_WATCH_ONLY",
        "market_cap_extremely_small_below": 100000000000,
        "market_cap_extremely_small_status": "L0_WATCH_ONLY",
    },
    "financial_red_flags": {
        "negative_equity_status": "L0_REJECT",
        "min_periods_for_persistent_checks": 3,
        "persistent_loss_periods": 3,
        "persistent_losses_status": "L0_REJECT",
        "negative_ocf_periods": 3,
        "negative_ocf_status": "L0_MANUAL_REVIEW",
        "debt_to_equity_manual_review_above": 3.0,
        "debt_pressure_status": "L0_MANUAL_REVIEW",
        "missing_essential_fields_status": "INSUFFICIENT_DATA_FOR_L0",
        "essential_fields": [
            "equity",
            "total_assets",
            "total_liabilities",
            "net_profit",
            "operating_cash_flow",
        ],
    },
    "disclosure_red_flags": {
        "critical_severities": ["CRITICAL", "HIGH"],
        "critical_event_types": [
            "TRADING_RESTRICTION",
            "SUSPENSION",
            "DELISTING_WARNING",
            "AUDIT_WARNING",
        ],
        "disclosure_violation_event_type": "DISCLOSURE_VIOLATION",
        "repeated_disclosure_violation_count": 2,
        "critical_disclosure_status": "L0_REJECT",
        "repeated_disclosure_status": "L0_MANUAL_REVIEW",
    },
}

REJECT_STATUSES = {"L0_REJECT"}
MANUAL_REVIEW_STATUSES = {
    "L0_MANUAL_REVIEW",
    "INSUFFICIENT_DATA_FOR_L0",
    "L0_REJECT",
}


def load_l0_rules(path: str) -> dict[str, Any]:
    """Load L0 Trash Filter rules from YAML."""

    if yaml is None:
        raise ImportError(
            "PyYAML is required to load YAML rule files. Install 'pyyaml' or "
            "provide rules directly to run_l0_trash_filter()."
        )

    rules_path = Path(path)
    with rules_path.open("r", encoding="utf-8") as rules_file:
        rules = yaml.safe_load(rules_file)

    if not isinstance(rules, dict):
        raise ValueError("L0 rules must contain a YAML mapping at the top level.")

    return rules


def run_l0_trash_filter(
    universe_df: pd.DataFrame,
    market_price_df: pd.DataFrame | None = None,
    financial_statement_df: pd.DataFrame | None = None,
    disclosure_df: pd.DataFrame | None = None,
    rules: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Run a conservative rule-based L0 Trash Filter without dropping rows."""

    if not isinstance(universe_df, pd.DataFrame):
        raise TypeError("universe_df must be a pandas DataFrame.")

    active_rules = _merge_rules(rules)
    rows: list[dict[str, Any]] = []
    for _, universe_row in universe_df.iterrows():
        context = _empty_l0_context(_clean_text(_row_value(universe_row, "ticker")))
        _check_universe_availability(context, universe_row, active_rules)

        ticker = context["ticker"]
        market_rows = _matching_rows(market_price_df, ticker)
        financial_rows = _matching_rows(financial_statement_df, ticker)
        disclosure_rows = _matching_rows(disclosure_df, ticker)

        _check_dataset_presence(context, market_rows, financial_rows, active_rules)

        _check_data_quality(context, market_rows, "market", active_rules)
        _check_data_quality(context, financial_rows, "financial", active_rules)
        _check_data_quality(context, disclosure_rows, "disclosure", active_rules)
        _check_liquidity(context, market_rows, active_rules)
        _check_market_size(context, universe_row, market_rows, active_rules)
        _check_financial_red_flags(context, financial_rows, active_rules)
        _check_disclosure_red_flags(context, disclosure_rows, active_rules)

        status = _resolve_status(context["candidate_statuses"], active_rules)
        score = _resolve_score(context["penalties"], active_rules)
        confidence = _resolve_confidence(status, context)
        manual_review_required = (
            status in MANUAL_REVIEW_STATUSES or confidence == "low"
        )

        rows.append(
            {
                "ticker": ticker,
                "l0_status": status,
                "l0_score": score,
                "l0_reject_reasons": _dedupe(context["reject_reasons"]),
                "l0_warning_flags": _dedupe(context["warning_flags"]),
                "evidence_fields": _dedupe(context["evidence_fields"]),
                "confidence": confidence,
                "manual_review_required": bool(manual_review_required),
            }
        )

    result = pd.DataFrame(rows, columns=L0_OUTPUT_COLUMNS)
    result["manual_review_required"] = result["manual_review_required"].astype(object)
    return result


def build_l0_reject_log(l0_result_df: pd.DataFrame) -> pd.DataFrame:
    """Build a reject log with one row per rejected stock."""

    if not isinstance(l0_result_df, pd.DataFrame):
        raise TypeError("l0_result_df must be a pandas DataFrame.")

    if l0_result_df.empty:
        return pd.DataFrame(columns=L0_REJECT_LOG_COLUMNS)

    rejected = l0_result_df[l0_result_df["l0_status"] == "L0_REJECT"]
    rows: list[dict[str, Any]] = []
    for _, row in rejected.iterrows():
        reasons = row.get("l0_reject_reasons", [])
        rows.append(
            {
                "ticker": row.get("ticker", ""),
                "reject_layer": "L0_TRASH_FILTER",
                "reject_reason": "; ".join(reasons) if reasons else "UNSPECIFIED_L0_REJECT",
                "evidence_fields": row.get("evidence_fields", []),
                "confidence": row.get("confidence", "low"),
            }
        )

    return pd.DataFrame(rows, columns=L0_REJECT_LOG_COLUMNS)


def save_l0_reject_log(
    reject_log_df: pd.DataFrame,
    output_path: str = "data/rejects/l0_reject_log.csv",
) -> str:
    """Save the L0 reject log and return the output path."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    reject_log_df.to_csv(path, index=False)
    return str(path)


def _check_universe_availability(
    context: dict[str, Any], universe_row: pd.Series, rules: dict[str, Any]
) -> None:
    data_rules = rules["data_availability"]
    ticker = context["ticker"]
    if not ticker:
        _add_reject(
            context,
            "MISSING_TICKER",
            data_rules["missing_ticker_status"],
            "missing_ticker",
            "ticker",
        )
        return

    if _is_false(_row_value(universe_row, "has_market_data")):
        _add_reject(
            context,
            "MISSING_MARKET_DATA",
            data_rules["missing_market_data_status"],
            "missing_market_data",
            "has_market_data",
        )

    if _is_false(_row_value(universe_row, "has_financial_data")):
        _add_reject(
            context,
            "MISSING_FINANCIAL_DATA",
            data_rules["missing_financial_data_status"],
            "missing_financial_data",
            "has_financial_data",
        )

    if _clean_text(_row_value(universe_row, "universe_status")) == "REJECT_UNIVERSE":
        _add_reject(
            context,
            "UNIVERSE_REJECTED_PRE_L0",
            "L0_REJECT",
            "data_error",
            "universe_status",
        )


def _check_dataset_presence(
    context: dict[str, Any],
    market_rows: pd.DataFrame,
    financial_rows: pd.DataFrame,
    rules: dict[str, Any],
) -> None:
    if not context["ticker"]:
        return

    data_rules = rules["data_availability"]
    if market_rows.empty:
        _add_reject(
            context,
            "MISSING_MARKET_DATA",
            data_rules["missing_market_data_status"],
            "missing_market_data",
            "market_price",
        )
    if financial_rows.empty:
        _add_reject(
            context,
            "MISSING_FINANCIAL_DATA",
            data_rules["missing_financial_data_status"],
            "missing_financial_data",
            "financial_statement_summary",
        )


def _check_data_quality(
    context: dict[str, Any],
    rows: pd.DataFrame,
    label: str,
    rules: dict[str, Any],
) -> None:
    if rows.empty:
        return

    data_rules = rules["data_availability"]
    quality_statuses = _column_text_values(rows, "quality_status")
    quality_warnings = _flatten_issue_column(rows, "quality_warnings")
    quality_errors = _flatten_issue_column(rows, "quality_errors")
    confidences = _column_text_values(rows, "final_confidence")

    if "DATA_ERROR" in quality_statuses or quality_errors:
        _add_reject(
            context,
            f"{label.upper()}_DATA_ERROR",
            data_rules["data_error_status"],
            "data_error",
            f"{label}:quality_errors",
        )
    if "DATA_CONFLICT" in quality_statuses or "DATA_CONFLICT" in quality_warnings:
        _add_warning(
            context,
            f"{label.upper()}_SOURCE_CONFLICT",
            data_rules["source_conflict_status"],
            "source_conflict",
            f"{label}:quality_status",
        )
    if "STALE_DATA" in quality_statuses or "STALE_DATA" in quality_warnings:
        _add_warning(
            context,
            f"{label.upper()}_STALE_DATA",
            data_rules["stale_data_status"],
            "stale_price_data",
            f"{label}:quality_status",
        )
    if "LOW" in confidences or "LOW_CONFIDENCE_RAW" in quality_warnings:
        _add_warning(
            context,
            f"{label.upper()}_LOW_CONFIDENCE",
            data_rules["low_confidence_status"],
            "low_data_confidence",
            f"{label}:final_confidence",
        )


def _check_liquidity(
    context: dict[str, Any], market_rows: pd.DataFrame, rules: dict[str, Any]
) -> None:
    if market_rows.empty:
        return

    liquidity_rules = rules["liquidity"]
    avg_trading_value = _numeric_mean(market_rows, "trading_value")
    avg_volume = _numeric_mean(market_rows, "volume")
    zero_volume_ratio = _zero_ratio(market_rows, "volume")

    if avg_trading_value is not None:
        context["evidence_fields"].append(f"avg_trading_value={avg_trading_value:g}")
    if avg_volume is not None:
        context["evidence_fields"].append(f"avg_volume={avg_volume:g}")
    if zero_volume_ratio is not None:
        context["evidence_fields"].append(f"zero_volume_day_ratio={zero_volume_ratio:g}")

    very_low = (
        avg_trading_value is not None
        and avg_trading_value < liquidity_rules["avg_trading_value_reject_below"]
    ) or (
        avg_volume is not None
        and avg_volume < liquidity_rules["avg_volume_reject_below"]
    ) or (
        zero_volume_ratio is not None
        and zero_volume_ratio > liquidity_rules["max_zero_volume_day_ratio"]
    )
    if very_low:
        _add_reject(
            context,
            "VERY_LOW_LIQUIDITY",
            liquidity_rules["very_low_liquidity_status"],
            "very_low_liquidity",
            "market_price:volume,trading_value",
        )
        return

    low = (
        avg_trading_value is not None
        and avg_trading_value < liquidity_rules["avg_trading_value_watch_below"]
    ) or (
        avg_volume is not None
        and avg_volume < liquidity_rules["avg_volume_watch_below"]
    )
    if low:
        _add_warning(
            context,
            "LOW_LIQUIDITY",
            liquidity_rules["low_liquidity_status"],
            "low_liquidity",
            "market_price:volume,trading_value",
        )


def _check_market_size(
    context: dict[str, Any],
    universe_row: pd.Series,
    market_rows: pd.DataFrame,
    rules: dict[str, Any],
) -> None:
    market_size_rules = rules["market_size"]
    if not market_size_rules.get("require_market_cap", False):
        return

    market_cap_column = market_size_rules.get("market_cap_column", "market_cap")
    market_cap = _first_numeric_value(market_rows, market_cap_column)
    if market_cap is None and market_cap_column in universe_row.index:
        market_cap = _to_number(universe_row[market_cap_column])

    if market_cap is None:
        _add_warning(
            context,
            "MARKET_CAP_MISSING",
            market_size_rules["market_cap_missing_status"],
            "market_cap_missing",
            market_cap_column,
        )
        return

    context["evidence_fields"].append(f"market_cap={market_cap:g}")
    if market_cap < market_size_rules["market_cap_extremely_small_below"]:
        _add_warning(
            context,
            "MARKET_CAP_EXTREMELY_SMALL",
            market_size_rules["market_cap_extremely_small_status"],
            "market_cap_extremely_small",
            market_cap_column,
        )


def _check_financial_red_flags(
    context: dict[str, Any], financial_rows: pd.DataFrame, rules: dict[str, Any]
) -> None:
    if financial_rows.empty:
        return

    financial_rules = rules["financial_red_flags"]
    for field in financial_rules["essential_fields"]:
        if field not in financial_rows.columns or financial_rows[field].map(_is_missing).all():
            _add_reject(
                context,
                f"MISSING_ESSENTIAL_FINANCIAL_FIELD_{field.upper()}",
                financial_rules["missing_essential_fields_status"],
                "missing_financial_data",
                f"financial_statement_summary:{field}",
            )

    equity_values = _numeric_series(financial_rows, "equity")
    if not equity_values.empty and (equity_values < 0).any():
        _add_reject(
            context,
            "NEGATIVE_EQUITY",
            financial_rules["negative_equity_status"],
            "negative_equity",
            "financial_statement_summary:equity",
        )

    total_liabilities = _first_numeric_value(financial_rows, "total_liabilities")
    equity = _first_numeric_value(financial_rows, "equity")
    if equity is not None and equity > 0 and total_liabilities is not None:
        debt_to_equity = total_liabilities / equity
        context["evidence_fields"].append(f"debt_to_equity={debt_to_equity:g}")
        if debt_to_equity > financial_rules["debt_to_equity_manual_review_above"]:
            _add_warning(
                context,
                "SEVERE_DEBT_PRESSURE",
                financial_rules["debt_pressure_status"],
                "debt_pressure",
                "financial_statement_summary:total_liabilities,equity",
            )

    min_periods = int(financial_rules["min_periods_for_persistent_checks"])
    period_count = len(financial_rows)
    net_profit = _numeric_series(financial_rows, "net_profit")
    ocf = _numeric_series(financial_rows, "operating_cash_flow")

    if period_count >= min_periods:
        if (net_profit < 0).sum() >= int(financial_rules["persistent_loss_periods"]):
            _add_reject(
                context,
                "PERSISTENT_LOSSES",
                financial_rules["persistent_losses_status"],
                "persistent_losses",
                "financial_statement_summary:net_profit",
            )
        if (ocf < 0).sum() >= int(financial_rules["negative_ocf_periods"]):
            _add_warning(
                context,
                "REPEATED_NEGATIVE_OPERATING_CASH_FLOW",
                financial_rules["negative_ocf_status"],
                "negative_operating_cash_flow",
                "financial_statement_summary:operating_cash_flow",
            )
    elif (net_profit < 0).any() or (ocf < 0).any():
        _add_warning(
            context,
            "INSUFFICIENT_FINANCIAL_HISTORY",
            "L0_MANUAL_REVIEW",
            "low_data_confidence",
            "financial_statement_summary:period",
        )


def _check_disclosure_red_flags(
    context: dict[str, Any], disclosure_rows: pd.DataFrame, rules: dict[str, Any]
) -> None:
    if disclosure_rows.empty:
        return

    disclosure_rules = rules["disclosure_red_flags"]
    critical_severities = {
        _clean_text(value) for value in disclosure_rules["critical_severities"]
    }
    critical_event_types = {
        _clean_text(value) for value in disclosure_rules["critical_event_types"]
    }
    severities = _column_text_values(disclosure_rows, "severity")
    event_types = _column_text_values(disclosure_rows, "event_type")

    if severities.intersection(critical_severities) or event_types.intersection(
        critical_event_types
    ):
        _add_reject(
            context,
            "CRITICAL_DISCLOSURE_EVENT",
            disclosure_rules["critical_disclosure_status"],
            "critical_disclosure",
            "disclosure_status:event_type,severity",
        )

    violation_type = _clean_text(disclosure_rules["disclosure_violation_event_type"])
    violation_count = sum(1 for event_type in event_types if event_type == violation_type)
    if violation_count >= int(disclosure_rules["repeated_disclosure_violation_count"]):
        _add_warning(
            context,
            "REPEATED_DISCLOSURE_VIOLATIONS",
            disclosure_rules["repeated_disclosure_status"],
            "critical_disclosure",
            "disclosure_status:event_type",
        )


def _add_reject(
    context: dict[str, Any],
    reason: str,
    status: str,
    penalty_key: str,
    evidence: str,
) -> None:
    context["reject_reasons"].append(reason)
    _add_status_and_evidence(context, status, penalty_key, evidence)


def _add_warning(
    context: dict[str, Any],
    warning: str,
    status: str,
    penalty_key: str,
    evidence: str,
) -> None:
    context["warning_flags"].append(warning)
    _add_status_and_evidence(context, status, penalty_key, evidence)


def _add_status_and_evidence(
    context: dict[str, Any], status: str, penalty_key: str, evidence: str
) -> None:
    context["candidate_statuses"].append(status)
    context["penalties"].append(penalty_key)
    context["evidence_fields"].append(evidence)


def _resolve_status(candidate_statuses: list[str], rules: dict[str, Any]) -> str:
    statuses = set(candidate_statuses)
    if not statuses:
        return "L0_PASS"

    for status in rules["status_priority"]:
        if status in statuses:
            return status
    return "L0_MANUAL_REVIEW"


def _resolve_score(penalty_keys: list[str], rules: dict[str, Any]) -> int:
    scoring_rules = rules["scoring"]
    penalties = scoring_rules["penalties"]
    score = int(scoring_rules["starting_score"])
    for penalty_key in _dedupe(penalty_keys):
        score -= int(penalties.get(penalty_key, 0))
    return max(int(scoring_rules["minimum_score"]), score)


def _resolve_confidence(status: str, context: dict[str, Any]) -> str:
    if status in {"L0_REJECT", "INSUFFICIENT_DATA_FOR_L0"}:
        return "low"
    serious_warnings = {
        "MARKET_SOURCE_CONFLICT",
        "FINANCIAL_SOURCE_CONFLICT",
        "DISCLOSURE_SOURCE_CONFLICT",
        "MARKET_LOW_CONFIDENCE",
        "FINANCIAL_LOW_CONFIDENCE",
        "DISCLOSURE_LOW_CONFIDENCE",
        "INSUFFICIENT_FINANCIAL_HISTORY",
    }
    if serious_warnings.intersection(context["warning_flags"]):
        return "low"
    if context["warning_flags"]:
        return "medium"
    return "high"


def _merge_rules(rules: dict[str, Any] | None) -> dict[str, Any]:
    merged = _deep_copy(DEFAULT_L0_RULES)
    if not rules:
        return merged

    for key, value in rules.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_nested_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _merge_nested_dicts(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_nested_dicts(result[key], value)
        else:
            result[key] = value
    return result


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _deep_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_copy(item) for item in value]
    return value


def _empty_l0_context(ticker: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "candidate_statuses": [],
        "reject_reasons": [],
        "warning_flags": [],
        "evidence_fields": [],
        "penalties": [],
    }


def _matching_rows(df: pd.DataFrame | None, ticker: str) -> pd.DataFrame:
    if df is None or df.empty or not ticker or "ticker" not in df.columns:
        return pd.DataFrame()
    return df[df["ticker"].map(_clean_text) == ticker].copy()


def _row_value(row: pd.Series, column: str) -> Any:
    if column not in row.index:
        return None
    return row[column]


def _numeric_mean(df: pd.DataFrame, column: str) -> float | None:
    values = _numeric_series(df, column)
    if values.empty:
        return None
    return float(values.mean())


def _zero_ratio(df: pd.DataFrame, column: str) -> float | None:
    values = _numeric_series(df, column)
    if values.empty:
        return None
    return float((values == 0).sum() / len(values))


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(dtype="float64")
    return pd.to_numeric(df[column], errors="coerce").dropna()


def _first_numeric_value(df: pd.DataFrame, column: str) -> float | None:
    values = _numeric_series(df, column)
    if values.empty:
        return None
    return float(values.iloc[-1])


def _to_number(value: Any) -> float | None:
    numeric_value = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric_value):
        return None
    return float(numeric_value)


def _column_text_values(df: pd.DataFrame, column: str) -> set[str]:
    if column not in df.columns:
        return set()
    return {_clean_text(value) for value in df[column] if not _is_missing(value)}


def _flatten_issue_column(df: pd.DataFrame, column: str) -> set[str]:
    if column not in df.columns:
        return set()

    issues: set[str] = set()
    for value in df[column]:
        if isinstance(value, list):
            issues.update(_clean_text(item) for item in value if not _is_missing(item))
        elif isinstance(value, str):
            stripped = value.strip()
            if stripped and stripped != "[]":
                issues.add(_clean_text(stripped))
    return issues


def _is_missing(value: Any) -> bool:
    if value is None or pd.isna(value):
        return True
    return isinstance(value, str) and not value.strip()


def _is_false(value: Any) -> bool:
    if isinstance(value, bool):
        return value is False
    if isinstance(value, str):
        return value.strip().upper() in {"FALSE", "0", "NO"}
    if pd.isna(value):
        return False
    return bool(value) is False


def _clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip().upper()


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(values))
