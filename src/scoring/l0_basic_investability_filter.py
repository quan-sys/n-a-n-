"""L0 Basic Investability Filter after the L0 Trash Filter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None


BASIC_INVESTABILITY_OUTPUT_COLUMNS = [
    "ticker",
    "l0_basic_status",
    "basic_investability_score",
    "liquidity_score",
    "market_cap_score",
    "data_coverage_score",
    "disclosure_risk_score",
    "financial_viability_score",
    "warning_flags",
    "reject_reasons",
    "evidence_fields",
    "confidence",
    "manual_review_required",
]

DEFAULT_BASIC_INVESTABILITY_RULES: dict[str, Any] = {
    "component_weights": {
        "liquidity_score": 0.25,
        "market_cap_score": 0.15,
        "data_coverage_score": 0.25,
        "disclosure_risk_score": 0.15,
        "financial_viability_score": 0.20,
    },
    "score_thresholds": {
        "investable_min_score": 75,
        "watch_only_min_score": 55,
        "reject_below_score": 35,
    },
    "confidence_rules": {
        "investable_allowed_confidence": ["high"],
        "low_confidence_score_below": 50,
        "medium_confidence_score_below": 75,
    },
    "input_scope": {
        "hard_reject_statuses": ["L0_REJECT"],
        "caution_statuses": ["L0_MANUAL_REVIEW", "INSUFFICIENT_DATA_FOR_L0"],
    },
    "liquidity": {
        "min_valid_trading_days": 1,
        "avg_trading_value": {
            "excellent": 5000000000,
            "good": 1000000000,
            "minimum": 100000000,
        },
        "avg_volume": {"excellent": 50000, "good": 10000, "minimum": 1000},
        "penalties": {"stale_or_low_quality": 20},
    },
    "market_cap": {
        "column": "market_cap",
        "missing_score": 50,
        "excellent": 1000000000000,
        "adequate": 300000000000,
        "minimum": 100000000000,
        "very_small_status": "L0_REJECT",
    },
    "data_coverage": {
        "required_groups": [
            "company_profile",
            "market_price",
            "financial_statement_summary",
            "disclosure_status",
        ],
        "points_per_group": {
            "company_profile": 25,
            "market_price": 25,
            "financial_statement_summary": 25,
            "disclosure_status": 25,
        },
        "minimum_required_score": 75,
        "clean_disclosure_event_types": [
            "NO_DISCLOSURE_EVENTS",
            "CONFIRMED_CLEAN",
        ],
        "quality_issue_penalty": 15,
    },
    "disclosure_risk": {
        "clean_event_types": ["NO_DISCLOSURE_EVENTS", "CONFIRMED_CLEAN"],
        "severity_scores": {
            "LOW": 90,
            "MEDIUM": 70,
            "HIGH": 25,
            "CRITICAL": 0,
            "UNKNOWN": 50,
        },
        "high_severity_status": "L0_MANUAL_REVIEW",
        "critical_severity_status": "L0_REJECT",
        "critical_event_types": [
            "TRADING_RESTRICTION",
            "SUSPENSION",
            "DELISTING_WARNING",
            "AUDIT_WARNING",
        ],
    },
    "financial_viability": {
        "essential_fields": [
            "equity",
            "total_assets",
            "total_liabilities",
            "net_profit",
            "operating_cash_flow",
        ],
        "negative_equity_status": "L0_REJECT",
        "debt_to_equity_watch_above": 2.0,
        "debt_to_equity_manual_review_above": 3.0,
        "min_periods_for_persistent_checks": 3,
        "persistent_loss_periods": 3,
        "repeated_negative_ocf_periods": 3,
    },
    "manual_review_triggers": [
        "DATA_CONFLICT",
        "UNKNOWN_DISCLOSURE_STATUS",
        "SUSPICIOUS_OUTLIER",
        "LOW_DATA_CONFIDENCE",
        "HIGH_SEVERITY_DISCLOSURE_RISK",
    ],
    "reject_triggers": [
        "FAILED_L0_TRASH_FILTER",
        "NEGATIVE_EQUITY",
        "CRITICAL_DISCLOSURE_RISK",
        "VERY_SMALL_MARKET_CAP",
    ],
}


def load_l0_basic_investability_rules(path: str) -> dict[str, Any]:
    """Load L0 Basic Investability Filter rules from YAML."""

    if yaml is None:
        raise ImportError(
            "PyYAML is required to load YAML rule files. Install 'pyyaml' or "
            "provide rules directly to run_l0_basic_investability_filter()."
        )

    rules_path = Path(path)
    with rules_path.open("r", encoding="utf-8") as rules_file:
        rules = yaml.safe_load(rules_file)

    if not isinstance(rules, dict):
        raise ValueError(
            "L0 basic investability rules must contain a YAML mapping."
        )

    return rules


def run_l0_basic_investability_filter(
    universe_df: pd.DataFrame,
    l0_trash_df: pd.DataFrame,
    market_price_df: pd.DataFrame | None = None,
    company_profile_df: pd.DataFrame | None = None,
    financial_statement_df: pd.DataFrame | None = None,
    disclosure_df: pd.DataFrame | None = None,
    rules: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Score basic investability for tickers that survive the trash filter."""

    if not isinstance(universe_df, pd.DataFrame):
        raise TypeError("universe_df must be a pandas DataFrame.")
    if not isinstance(l0_trash_df, pd.DataFrame):
        raise TypeError("l0_trash_df must be a pandas DataFrame.")

    active_rules = _merge_rules(rules)
    rows: list[dict[str, Any]] = []
    tickers = _ordered_tickers(universe_df, l0_trash_df)

    for ticker in tickers:
        context = _new_context(ticker)
        universe_row = _first_matching_row(universe_df, ticker)
        l0_row = _first_matching_row(l0_trash_df, ticker)
        market_rows = _matching_rows(market_price_df, ticker)
        profile_rows = _matching_rows(company_profile_df, ticker)
        financial_rows = _matching_rows(financial_statement_df, ticker)
        disclosure_rows = _matching_rows(disclosure_df, ticker)

        l0_status = _clean_text(_row_value(l0_row, "l0_status"))
        if _is_hard_l0_reject(l0_status, active_rules):
            rows.append(_hard_reject_result(context, active_rules))
            continue

        context["upstream_caution"] = _is_l0_caution(l0_status, active_rules)
        if context["upstream_caution"]:
            context["warning_flags"].append("UPSTREAM_L0_CAUTION")
            context["evidence_fields"].append(f"l0_status={l0_status}")

        quality_issues = _collect_quality_issues(
            market_rows=market_rows,
            profile_rows=profile_rows,
            financial_rows=financial_rows,
            disclosure_rows=disclosure_rows,
        )
        _apply_quality_issues(context, quality_issues)

        liquidity_score = _score_liquidity(context, market_rows, active_rules)
        market_cap_score = _score_market_cap(
            context, universe_row, market_rows, active_rules
        )
        data_coverage_score = _score_data_coverage(
            context,
            profile_rows,
            market_rows,
            financial_rows,
            disclosure_rows,
            active_rules,
        )
        disclosure_risk_score = _score_disclosure_risk(
            context, disclosure_rows, active_rules
        )
        financial_viability_score = _score_financial_viability(
            context, financial_rows, active_rules
        )

        component_scores = {
            "liquidity_score": liquidity_score,
            "market_cap_score": market_cap_score,
            "data_coverage_score": data_coverage_score,
            "disclosure_risk_score": disclosure_risk_score,
            "financial_viability_score": financial_viability_score,
        }
        final_score = _weighted_score(component_scores, active_rules)
        confidence = _resolve_confidence(final_score, context, active_rules)
        status = _resolve_basic_status(final_score, confidence, context, active_rules)
        manual_review_required = (
            status == "L0_MANUAL_REVIEW"
            or confidence == "low"
            or bool(_manual_review_intersection(context, active_rules))
        )

        rows.append(
            {
                "ticker": ticker,
                "l0_basic_status": status,
                "basic_investability_score": final_score,
                "liquidity_score": liquidity_score,
                "market_cap_score": market_cap_score,
                "data_coverage_score": data_coverage_score,
                "disclosure_risk_score": disclosure_risk_score,
                "financial_viability_score": financial_viability_score,
                "warning_flags": _dedupe(context["warning_flags"]),
                "reject_reasons": _dedupe(context["reject_reasons"]),
                "evidence_fields": _dedupe(context["evidence_fields"]),
                "confidence": confidence,
                "manual_review_required": bool(manual_review_required),
            }
        )

    result = pd.DataFrame(rows, columns=BASIC_INVESTABILITY_OUTPUT_COLUMNS)
    result["manual_review_required"] = result["manual_review_required"].astype(object)
    return result


def serialize_list_columns(
    df: pd.DataFrame,
    list_columns: list[str] | None = None,
    separator: str = ";",
) -> pd.DataFrame:
    """Return a copy with list-valued output columns serialized for CSV."""

    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame.")

    target_columns = list_columns or [
        "warning_flags",
        "reject_reasons",
        "evidence_fields",
    ]
    output = df.copy(deep=True)
    for column in target_columns:
        if column in output.columns:
            output[column] = output[column].map(
                lambda value: separator.join(map(str, value))
                if isinstance(value, list)
                else value
            )
    return output


def _hard_reject_result(
    context: dict[str, Any], rules: dict[str, Any]
) -> dict[str, Any]:
    context["reject_reasons"].append("FAILED_L0_TRASH_FILTER")
    context["evidence_fields"].append("l0_status=L0_REJECT")
    return {
        "ticker": context["ticker"],
        "l0_basic_status": "L0_REJECT",
        "basic_investability_score": 0,
        "liquidity_score": 0,
        "market_cap_score": 0,
        "data_coverage_score": 0,
        "disclosure_risk_score": 0,
        "financial_viability_score": 0,
        "warning_flags": _dedupe(context["warning_flags"]),
        "reject_reasons": _dedupe(context["reject_reasons"]),
        "evidence_fields": _dedupe(context["evidence_fields"]),
        "confidence": "low",
        "manual_review_required": True,
    }


def _score_liquidity(
    context: dict[str, Any], market_rows: pd.DataFrame, rules: dict[str, Any]
) -> int:
    if market_rows.empty:
        context["reject_reasons"].append("INSUFFICIENT_MARKET_DATA")
        context["evidence_fields"].append("market_price=missing")
        return 0

    liquidity_rules = rules["liquidity"]
    valid_days = len(market_rows)
    context["evidence_fields"].append(f"valid_trading_days={valid_days}")
    if valid_days < int(liquidity_rules["min_valid_trading_days"]):
        context["reject_reasons"].append("INSUFFICIENT_MARKET_DATA")
        return 0

    trading_value_score = _threshold_score(
        _numeric_mean(market_rows, "trading_value"),
        liquidity_rules["avg_trading_value"],
    )
    volume_score = _threshold_score(
        _numeric_mean(market_rows, "volume"), liquidity_rules["avg_volume"]
    )
    score = int(round((trading_value_score + volume_score) / 2))

    avg_trading_value = _numeric_mean(market_rows, "trading_value")
    avg_volume = _numeric_mean(market_rows, "volume")
    if avg_trading_value is not None:
        context["evidence_fields"].append(f"avg_trading_value={avg_trading_value:g}")
    if avg_volume is not None:
        context["evidence_fields"].append(f"avg_volume={avg_volume:g}")

    if trading_value_score <= 30 or volume_score <= 30:
        context["reject_reasons"].append("VERY_LOW_LIQUIDITY")
    elif trading_value_score <= 60 or volume_score <= 60:
        context["warning_flags"].append("LOW_LIQUIDITY")

    if _has_quality_issue(market_rows):
        score -= int(liquidity_rules["penalties"]["stale_or_low_quality"])
        context["warning_flags"].append("MARKET_DATA_QUALITY_REVIEW")

    return _clamp_score(score)


def _score_market_cap(
    context: dict[str, Any],
    universe_row: pd.Series,
    market_rows: pd.DataFrame,
    rules: dict[str, Any],
) -> int:
    market_cap_rules = rules["market_cap"]
    market_cap_column = market_cap_rules["column"]
    market_cap = _market_cap_value(universe_row, market_rows, market_cap_column)

    if market_cap is None:
        context["warning_flags"].append("MARKET_CAP_MISSING")
        context["evidence_fields"].append(f"{market_cap_column}=missing")
        return int(market_cap_rules["missing_score"])

    context["evidence_fields"].append(f"{market_cap_column}={market_cap:g}")
    if market_cap >= market_cap_rules["excellent"]:
        return 100
    if market_cap >= market_cap_rules["adequate"]:
        return 80
    if market_cap >= market_cap_rules["minimum"]:
        return 55

    context["reject_reasons"].append("VERY_SMALL_MARKET_CAP")
    return 20


def _score_data_coverage(
    context: dict[str, Any],
    profile_rows: pd.DataFrame,
    market_rows: pd.DataFrame,
    financial_rows: pd.DataFrame,
    disclosure_rows: pd.DataFrame,
    rules: dict[str, Any],
) -> int:
    coverage_rules = rules["data_coverage"]
    points = coverage_rules["points_per_group"]
    score = 0

    if not profile_rows.empty:
        score += int(points["company_profile"])
    else:
        context["warning_flags"].append("MISSING_COMPANY_PROFILE")

    if not market_rows.empty:
        score += int(points["market_price"])
    else:
        context["reject_reasons"].append("INSUFFICIENT_MARKET_DATA")

    if not financial_rows.empty:
        score += int(points["financial_statement_summary"])
    else:
        context["reject_reasons"].append("INSUFFICIENT_FINANCIAL_DATA")

    if _has_confirmed_clean_disclosure(disclosure_rows, coverage_rules):
        score += int(points["disclosure_status"])
    elif not disclosure_rows.empty:
        score += int(points["disclosure_status"])
        if _has_unknown_disclosure(disclosure_rows):
            context["warning_flags"].append("UNKNOWN_DISCLOSURE_STATUS")
    else:
        context["warning_flags"].append("UNKNOWN_DISCLOSURE_STATUS")

    quality_penalty_count = sum(
        int(_has_quality_issue(rows))
        for rows in [profile_rows, market_rows, financial_rows, disclosure_rows]
        if not rows.empty
    )
    if quality_penalty_count:
        score -= int(coverage_rules["quality_issue_penalty"]) * quality_penalty_count

    if score < int(coverage_rules["minimum_required_score"]):
        context["warning_flags"].append("LOW_DATA_COVERAGE")

    return _clamp_score(score)


def _score_disclosure_risk(
    context: dict[str, Any], disclosure_rows: pd.DataFrame, rules: dict[str, Any]
) -> int:
    disclosure_rules = rules["disclosure_risk"]
    if disclosure_rows.empty:
        context["warning_flags"].append("UNKNOWN_DISCLOSURE_STATUS")
        return 40

    clean_event_types = {
        _clean_text(value) for value in disclosure_rules["clean_event_types"]
    }
    event_types = _column_text_values(disclosure_rows, "event_type")
    severities = _column_text_values(disclosure_rows, "severity")
    if event_types and event_types.issubset(clean_event_types):
        return 100

    severity_scores = disclosure_rules["severity_scores"]
    scores = [int(severity_scores.get(severity, 50)) for severity in severities]
    if not scores:
        context["warning_flags"].append("UNKNOWN_DISCLOSURE_STATUS")
        return 50

    critical_event_types = {
        _clean_text(value) for value in disclosure_rules["critical_event_types"]
    }
    if "CRITICAL" in severities or event_types.intersection(critical_event_types):
        context["reject_reasons"].append("CRITICAL_DISCLOSURE_RISK")
    elif "HIGH" in severities:
        context["warning_flags"].append("HIGH_SEVERITY_DISCLOSURE_RISK")
    if "UNKNOWN" in severities:
        context["warning_flags"].append("UNKNOWN_DISCLOSURE_STATUS")

    return _clamp_score(min(scores))


def _score_financial_viability(
    context: dict[str, Any], financial_rows: pd.DataFrame, rules: dict[str, Any]
) -> int:
    if financial_rows.empty:
        context["reject_reasons"].append("INSUFFICIENT_FINANCIAL_DATA")
        return 0

    financial_rules = rules["financial_viability"]
    score = 100
    for field in financial_rules["essential_fields"]:
        if field not in financial_rows.columns or financial_rows[field].map(_is_missing).all():
            context["reject_reasons"].append("INSUFFICIENT_FINANCIAL_DATA")
            context["evidence_fields"].append(f"missing_financial_field={field}")
            score -= 20

    equity_values = _numeric_series(financial_rows, "equity")
    if not equity_values.empty and (equity_values < 0).any():
        context["reject_reasons"].append("NEGATIVE_EQUITY")
        context["evidence_fields"].append("equity<0")
        return 0

    total_liabilities = _last_numeric_value(financial_rows, "total_liabilities")
    equity = _last_numeric_value(financial_rows, "equity")
    if equity is not None and equity > 0 and total_liabilities is not None:
        debt_to_equity = total_liabilities / equity
        context["evidence_fields"].append(f"debt_to_equity={debt_to_equity:g}")
        if debt_to_equity > financial_rules["debt_to_equity_manual_review_above"]:
            context["warning_flags"].append("SEVERE_DEBT_PRESSURE")
            score -= 35
        elif debt_to_equity > financial_rules["debt_to_equity_watch_above"]:
            context["warning_flags"].append("ELEVATED_DEBT_PRESSURE")
            score -= 15

    period_count = len(financial_rows)
    net_profit = _numeric_series(financial_rows, "net_profit")
    operating_cash_flow = _numeric_series(financial_rows, "operating_cash_flow")
    min_periods = int(financial_rules["min_periods_for_persistent_checks"])
    if period_count >= min_periods:
        if (net_profit < 0).sum() >= int(financial_rules["persistent_loss_periods"]):
            context["reject_reasons"].append("PERSISTENT_HEAVY_LOSSES")
            score -= 60
        if (operating_cash_flow < 0).sum() >= int(
            financial_rules["repeated_negative_ocf_periods"]
        ):
            context["warning_flags"].append("REPEATED_NEGATIVE_OPERATING_CASH_FLOW")
            score -= 35
    elif (net_profit < 0).any() or (operating_cash_flow < 0).any():
        context["warning_flags"].append("INSUFFICIENT_FINANCIAL_HISTORY")
        score -= 25

    return _clamp_score(score)


def _weighted_score(component_scores: dict[str, int], rules: dict[str, Any]) -> int:
    weights = rules["component_weights"]
    weighted_total = 0.0
    for column, score in component_scores.items():
        weighted_total += float(weights[column]) * int(score)
    return _clamp_score(round(weighted_total))


def _resolve_basic_status(
    final_score: int,
    confidence: str,
    context: dict[str, Any],
    rules: dict[str, Any],
) -> str:
    reject_reasons = set(context["reject_reasons"])
    warning_flags = set(context["warning_flags"])
    thresholds = rules["score_thresholds"]

    if reject_reasons.intersection(rules["reject_triggers"]):
        return "L0_REJECT"
    if {
        "INSUFFICIENT_MARKET_DATA",
        "INSUFFICIENT_FINANCIAL_DATA",
    }.intersection(reject_reasons):
        return "INSUFFICIENT_DATA_FOR_BASIC_INVESTABILITY"
    if final_score < int(thresholds["reject_below_score"]):
        context["reject_reasons"].append("LOW_BASIC_INVESTABILITY_SCORE")
        return "L0_REJECT"
    if context["upstream_caution"]:
        if confidence == "low" or "LOW_DATA_COVERAGE" in warning_flags:
            return "INSUFFICIENT_DATA_FOR_BASIC_INVESTABILITY"
        return "L0_MANUAL_REVIEW"
    if _manual_review_intersection(context, rules):
        return "L0_MANUAL_REVIEW"
    if (
        final_score >= int(thresholds["investable_min_score"])
        and confidence in rules["confidence_rules"]["investable_allowed_confidence"]
    ):
        return "L0_INVESTABLE"
    if final_score >= int(thresholds["watch_only_min_score"]):
        return "L0_WATCH_ONLY"

    context["reject_reasons"].append("LOW_BASIC_INVESTABILITY_SCORE")
    return "L0_REJECT"


def _resolve_confidence(
    final_score: int, context: dict[str, Any], rules: dict[str, Any]
) -> str:
    if context["reject_reasons"]:
        return "low"

    warnings = set(context["warning_flags"])
    low_confidence_warnings = {
        "LOW_DATA_CONFIDENCE",
        "DATA_CONFLICT",
        "SUSPICIOUS_OUTLIER",
        "UNKNOWN_DISCLOSURE_STATUS",
        "LOW_DATA_COVERAGE",
        "MARKET_DATA_QUALITY_REVIEW",
        "FINANCIAL_DATA_QUALITY_REVIEW",
    }
    if warnings.intersection(low_confidence_warnings):
        return "low"

    confidence_rules = rules["confidence_rules"]
    if final_score < int(confidence_rules["low_confidence_score_below"]):
        return "low"
    if final_score < int(confidence_rules["medium_confidence_score_below"]):
        return "medium"
    if warnings:
        return "medium"
    return "high"


def _collect_quality_issues(
    *,
    market_rows: pd.DataFrame,
    profile_rows: pd.DataFrame,
    financial_rows: pd.DataFrame,
    disclosure_rows: pd.DataFrame,
) -> set[str]:
    issues: set[str] = set()
    for rows in [market_rows, profile_rows, financial_rows, disclosure_rows]:
        if rows.empty:
            continue
        statuses = _column_text_values(rows, "quality_status")
        warnings = _flatten_issue_column(rows, "quality_warnings")
        errors = _flatten_issue_column(rows, "quality_errors")
        confidences = _column_text_values(rows, "final_confidence")
        issues.update(statuses - {"VALID_DATA"})
        issues.update(warnings)
        issues.update(errors)
        if "LOW" in confidences:
            issues.add("LOW_DATA_CONFIDENCE")
    return issues


def _apply_quality_issues(context: dict[str, Any], issues: set[str]) -> None:
    if not issues:
        return

    if "DATA_CONFLICT" in issues:
        context["warning_flags"].append("DATA_CONFLICT")
    if "OUTLIER_REVIEW" in issues:
        context["warning_flags"].append("SUSPICIOUS_OUTLIER")
    if "LOW_DATA_CONFIDENCE" in issues or "LOW_CONFIDENCE_RAW" in issues:
        context["warning_flags"].append("LOW_DATA_CONFIDENCE")
    if "STALE_DATA" in issues:
        context["warning_flags"].append("STALE_DATA")
    if "DATA_ERROR" in issues:
        context["warning_flags"].append("DATA_ERROR")


def _manual_review_intersection(
    context: dict[str, Any], rules: dict[str, Any]
) -> set[str]:
    return set(context["warning_flags"]).intersection(rules["manual_review_triggers"])


def _ordered_tickers(universe_df: pd.DataFrame, l0_trash_df: pd.DataFrame) -> list[str]:
    tickers: list[str] = []
    for df in [universe_df, l0_trash_df]:
        if "ticker" not in df.columns:
            continue
        for ticker in df["ticker"]:
            normalized = _clean_text(ticker)
            if normalized and normalized not in tickers:
                tickers.append(normalized)
    return tickers


def _is_hard_l0_reject(l0_status: str, rules: dict[str, Any]) -> bool:
    return l0_status in {_clean_text(status) for status in rules["input_scope"]["hard_reject_statuses"]}


def _is_l0_caution(l0_status: str, rules: dict[str, Any]) -> bool:
    return l0_status in {_clean_text(status) for status in rules["input_scope"]["caution_statuses"]}


def _threshold_score(value: float | None, thresholds: dict[str, Any]) -> int:
    if value is None:
        return 0
    if value >= thresholds["excellent"]:
        return 100
    if value >= thresholds["good"]:
        return 80
    if value >= thresholds["minimum"]:
        return 55
    return 20


def _market_cap_value(
    universe_row: pd.Series, market_rows: pd.DataFrame, column: str
) -> float | None:
    if column in universe_row.index:
        value = _to_number(universe_row[column])
        if value is not None:
            return value
    return _last_numeric_value(market_rows, column)


def _has_confirmed_clean_disclosure(
    disclosure_rows: pd.DataFrame, coverage_rules: dict[str, Any]
) -> bool:
    if disclosure_rows.empty:
        return False
    clean_event_types = {
        _clean_text(value) for value in coverage_rules["clean_disclosure_event_types"]
    }
    event_types = _column_text_values(disclosure_rows, "event_type")
    return bool(event_types) and event_types.issubset(clean_event_types)


def _has_unknown_disclosure(disclosure_rows: pd.DataFrame) -> bool:
    severities = _column_text_values(disclosure_rows, "severity")
    event_types = _column_text_values(disclosure_rows, "event_type")
    return "UNKNOWN" in severities or "UNKNOWN" in event_types


def _has_quality_issue(rows: pd.DataFrame) -> bool:
    if rows.empty:
        return False
    statuses = _column_text_values(rows, "quality_status")
    if statuses - {"VALID_DATA"}:
        return True
    if _flatten_issue_column(rows, "quality_warnings"):
        return True
    if _flatten_issue_column(rows, "quality_errors"):
        return True
    confidences = _column_text_values(rows, "final_confidence")
    return "LOW" in confidences


def _matching_rows(df: pd.DataFrame | None, ticker: str) -> pd.DataFrame:
    if df is None or df.empty or not ticker or "ticker" not in df.columns:
        return pd.DataFrame()
    return df[df["ticker"].map(_clean_text) == ticker].copy()


def _first_matching_row(df: pd.DataFrame, ticker: str) -> pd.Series:
    if df.empty or "ticker" not in df.columns:
        return pd.Series(dtype=object)
    rows = df[df["ticker"].map(_clean_text) == ticker]
    if rows.empty:
        return pd.Series(dtype=object)
    return rows.iloc[0]


def _row_value(row: pd.Series, column: str) -> Any:
    if column not in row.index:
        return None
    return row[column]


def _numeric_mean(df: pd.DataFrame, column: str) -> float | None:
    values = _numeric_series(df, column)
    if values.empty:
        return None
    return float(values.mean())


def _last_numeric_value(df: pd.DataFrame, column: str) -> float | None:
    values = _numeric_series(df, column)
    if values.empty:
        return None
    return float(values.iloc[-1])


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(dtype="float64")
    return pd.to_numeric(df[column], errors="coerce").dropna()


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


def _to_number(value: Any) -> float | None:
    numeric_value = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric_value):
        return None
    return float(numeric_value)


def _is_missing(value: Any) -> bool:
    if isinstance(value, list):
        return len(value) == 0
    if value is None or pd.isna(value):
        return True
    return isinstance(value, str) and not value.strip()


def _clean_text(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip().upper()


def _clamp_score(value: int | float) -> int:
    return max(0, min(100, int(round(value))))


def _merge_rules(rules: dict[str, Any] | None) -> dict[str, Any]:
    merged = _deep_copy(DEFAULT_BASIC_INVESTABILITY_RULES)
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


def _new_context(ticker: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "warning_flags": [],
        "reject_reasons": [],
        "evidence_fields": [],
        "upstream_caution": False,
    }


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(values))
