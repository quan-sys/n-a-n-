"""Step 18 sector-cycle scoring utilities.

This module scores micro-sector cycle conditions from already-clean indicator
rows. It does not fetch data, score individual companies, compare peers, run
valuation, produce timing signals, generate reports, or make recommendations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None


DEFAULT_RULES_PATH = "config/sector_cycle_rules.yaml"

REQUIRED_TOP_LEVEL_SECTIONS = ["default_rules", "micro_sector_rules"]
REQUIRED_DEFAULT_RULE_FIELDS = [
    "score_min",
    "score_max",
    "insufficient_data_min_indicator_count",
    "key_indicator_coverage_min_ratio",
    "manual_review_on_data_conflict",
    "manual_review_on_low_confidence",
    "manual_review_on_stale_data",
    "low_confidence_values",
    "stale_data_statuses",
    "conflict_data_statuses",
    "invalid_data_statuses",
    "anomaly_threshold_pct",
    "overheating_threshold_pct",
    "default_score_impact",
    "structural_risk_score_impact",
    "anomaly_score_impact",
    "overheating_score_impact",
    "confidence_rules",
    "missing_data_behavior",
]
REQUIRED_MICRO_SECTOR_RULE_FIELDS = [
    "key_indicators",
    "recovery_when",
    "distress_when",
    "overheating_when",
    "structural_risk_indicators",
    "anomaly_indicators",
]

OUTPUT_FIELDS = [
    "micro_sector",
    "cycle_status",
    "distress_score",
    "recovery_score",
    "overheating_score",
    "structural_risk_score",
    "anomaly_score",
    "cycle_confidence",
    "data_quality_status",
    "evidence",
    "warning_flags",
    "anomaly_alert",
    "suggested_temporary_adjustment",
    "manual_review_required",
    "notes",
]


def load_sector_cycle_rules(path: str | Path = DEFAULT_RULES_PATH) -> dict[str, Any]:
    """Load sector-cycle rules from YAML."""

    if yaml is None:
        raise ImportError(
            "PyYAML is required to load sector cycle rules. Install 'pyyaml' "
            "or provide rules directly."
        )

    rules_path = Path(path)
    with rules_path.open("r", encoding="utf-8") as rules_file:
        rules = yaml.safe_load(rules_file)

    if not isinstance(rules, dict):
        raise ValueError("Sector cycle rules must contain a YAML mapping.")
    return rules


def validate_sector_cycle_rules(rules: dict[str, Any]) -> list[str]:
    """Validate required rule sections and fields."""

    if not isinstance(rules, dict):
        return ["RULES_NOT_MAPPING"]

    errors: list[str] = []
    for section in REQUIRED_TOP_LEVEL_SECTIONS:
        if section not in rules:
            errors.append(f"MISSING_SECTION:{section}")

    default_rules = rules.get("default_rules", {})
    if not isinstance(default_rules, dict):
        errors.append("SECTION_NOT_MAPPING:default_rules")
    else:
        for field in REQUIRED_DEFAULT_RULE_FIELDS:
            if field not in default_rules:
                errors.append(f"default_rules:MISSING_FIELD:{field}")

    micro_sector_rules = rules.get("micro_sector_rules", {})
    if not isinstance(micro_sector_rules, dict):
        errors.append("SECTION_NOT_MAPPING:micro_sector_rules")
    else:
        for micro_sector, config in micro_sector_rules.items():
            if not isinstance(config, dict):
                errors.append(f"{micro_sector}:RULE_NOT_MAPPING")
                continue
            for field in REQUIRED_MICRO_SECTOR_RULE_FIELDS:
                if field not in config:
                    errors.append(f"{micro_sector}:MISSING_FIELD:{field}")

    return _dedupe(errors)


def normalize_score(
    value: float, min_score: float = 0, max_score: float = 100
) -> float:
    """Clamp a score between min_score and max_score."""

    numeric_value = _to_number(value)
    if numeric_value is None:
        numeric_value = min_score
    return round(max(min_score, min(max_score, numeric_value)), 4)


def evaluate_indicator_trend(row: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one indicator row into a normalized trend signal."""

    if not isinstance(row, dict):
        raise TypeError("row must be a dict.")

    trend = _clean_token(row.get("trend"))
    value = _to_number(row.get("value"))
    previous_value = _to_number(row.get("previous_value"))
    pct_change = None

    if value is not None and previous_value is not None and previous_value != 0:
        pct_change = (value - previous_value) / abs(previous_value)
        if not trend:
            if pct_change > 0:
                trend = "up"
            elif pct_change < 0:
                trend = "down"
            else:
                trend = "flat"

    if not trend:
        trend = "unknown"

    direction = "unknown"
    if trend in {"up", "spike_up", "positive", "improving"}:
        direction = "positive"
    elif trend in {"down", "spike_down", "negative", "deteriorating"}:
        direction = "negative"
    elif trend in {"flat", "stable", "neutral"}:
        direction = "mixed"

    return {
        "indicator_id": _clean_value(row.get("indicator_id")),
        "trend": trend,
        "direction": direction,
        "value": value,
        "previous_value": previous_value,
        "pct_change": pct_change,
        "data_quality_status": _clean_value(row.get("data_quality_status")),
        "confidence": _clean_value(row.get("confidence")),
    }


def score_micro_sector_cycle(
    micro_sector: str,
    indicator_rows: list[dict[str, Any]],
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score one micro-sector using indicator rows and deterministic rules."""

    active_rules = rules or load_sector_cycle_rules()
    validation_errors = validate_sector_cycle_rules(active_rules)
    if validation_errors:
        return _result(
            micro_sector=micro_sector,
            cycle_status="SECTOR_MANUAL_REVIEW",
            cycle_confidence="low",
            data_quality_status="INVALID_RULES",
            warning_flags=validation_errors,
            manual_review_required=True,
            notes="Invalid sector cycle rules.",
        )

    default_rules = active_rules["default_rules"]
    min_score = float(default_rules["score_min"])
    max_score = float(default_rules["score_max"])
    normalized_micro_sector = _clean_value(micro_sector)
    rule = active_rules["micro_sector_rules"].get(normalized_micro_sector)
    if not rule or normalized_micro_sector == "unknown":
        return _result(
            micro_sector=normalized_micro_sector,
            cycle_status="INSUFFICIENT_DATA_FOR_SECTOR_CYCLE",
            cycle_confidence="low",
            data_quality_status="UNKNOWN_MICRO_SECTOR",
            warning_flags=["UNKNOWN_MICRO_SECTOR_FOR_SECTOR_CYCLE"],
            manual_review_required=True,
            notes="Unknown micro-sector; sector-cycle scoring requires manual review.",
        )

    rows = [
        dict(row)
        for row in (indicator_rows or [])
        if _clean_value(row.get("micro_sector", normalized_micro_sector))
        in {"", normalized_micro_sector}
        or _clean_value(row.get("micro_sector")) == normalized_micro_sector
    ]
    context = _new_context()
    score_totals = {
        "distress_score": 0.0,
        "recovery_score": 0.0,
        "overheating_score": 0.0,
        "structural_risk_score": 0.0,
        "anomaly_score": 0.0,
    }

    _check_indicator_coverage(rows, rule, default_rules, context)
    for row in rows:
        _score_indicator_row(
            row=row,
            micro_sector=normalized_micro_sector,
            rule=rule,
            default_rules=default_rules,
            score_totals=score_totals,
            context=context,
        )

    normalized_scores = {
        key: normalize_score(value, min_score, max_score)
        for key, value in score_totals.items()
    }
    anomaly_alert = normalized_scores["anomaly_score"] > 0 or bool(
        context["anomaly_alert"]
    )
    if anomaly_alert:
        context["warning_flags"].append("ANOMALY_REVIEW_REQUIRED")
        context["manual_review_required"] = True

    cycle_confidence = _resolve_cycle_confidence(
        rows=rows,
        rule=rule,
        default_rules=default_rules,
        context=context,
    )
    cycle_status = _resolve_cycle_status(
        normalized_scores=normalized_scores,
        context=context,
        default_rules=default_rules,
    )
    data_quality_status = _resolve_data_quality_status(context)
    suggested_adjustment = (
        {
            "type": "temporary_manual_review",
            "reason": "anomaly_detected",
            "permanent_weight_change": False,
        }
        if anomaly_alert
        else None
    )

    return _result(
        micro_sector=normalized_micro_sector,
        cycle_status=cycle_status,
        distress_score=normalized_scores["distress_score"],
        recovery_score=normalized_scores["recovery_score"],
        overheating_score=normalized_scores["overheating_score"],
        structural_risk_score=normalized_scores["structural_risk_score"],
        anomaly_score=normalized_scores["anomaly_score"],
        cycle_confidence=cycle_confidence,
        data_quality_status=data_quality_status,
        evidence=_dedupe_evidence(context["evidence"]),
        warning_flags=_dedupe(context["warning_flags"]),
        anomaly_alert=anomaly_alert,
        suggested_temporary_adjustment=suggested_adjustment,
        manual_review_required=bool(context["manual_review_required"]),
        notes=_notes_for_status(cycle_status, cycle_confidence, context),
    )


def score_all_micro_sectors(
    indicator_rows: list[dict[str, Any]],
    rules: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Group indicator rows by micro-sector and score each group."""

    active_rules = rules or load_sector_cycle_rules()
    rows_by_sector: dict[str, list[dict[str, Any]]] = {}
    for row in indicator_rows or []:
        micro_sector = _clean_value(row.get("micro_sector"))
        if not micro_sector:
            micro_sector = "unknown"
        rows_by_sector.setdefault(micro_sector, []).append(dict(row))

    if not rows_by_sector:
        return [
            score_micro_sector_cycle(
                "unknown",
                [],
                rules=active_rules,
            )
        ]

    return [
        score_micro_sector_cycle(micro_sector, rows, rules=active_rules)
        for micro_sector, rows in rows_by_sector.items()
    ]


def _score_indicator_row(
    *,
    row: dict[str, Any],
    micro_sector: str,
    rule: dict[str, Any],
    default_rules: dict[str, Any],
    score_totals: dict[str, float],
    context: dict[str, Any],
) -> None:
    trend_result = evaluate_indicator_trend(row)
    indicator_id = trend_result["indicator_id"]
    trend = trend_result["trend"]
    if not indicator_id:
        context["warning_flags"].append("UNKNOWN_INDICATOR")
        context["manual_review_required"] = True
        return

    _check_row_quality(row, default_rules, context)

    known_indicators = _known_indicators(rule)
    if indicator_id not in known_indicators:
        context["warning_flags"].append("UNKNOWN_INDICATOR_FOR_MICRO_SECTOR")
        context["manual_review_required"] = True

    default_impact = float(default_rules["default_score_impact"])
    overheating_impact = float(default_rules["overheating_score_impact"])
    structural_impact = float(default_rules["structural_risk_score_impact"])
    anomaly_impact = float(default_rules["anomaly_score_impact"])

    if _matches_trend(indicator_id, trend, rule.get("recovery_when", {})):
        _add_score(
            score_totals,
            context,
            row,
            signal="recovery",
            score_key="recovery_score",
            impact=default_impact,
            direction="positive",
        )
    if _matches_trend(indicator_id, trend, rule.get("distress_when", {})):
        _add_score(
            score_totals,
            context,
            row,
            signal="distress",
            score_key="distress_score",
            impact=default_impact,
            direction="negative",
        )
    if _matches_trend(indicator_id, trend, rule.get("overheating_when", {})):
        _add_score(
            score_totals,
            context,
            row,
            signal="overheating",
            score_key="overheating_score",
            impact=overheating_impact,
            direction="mixed",
        )

    if indicator_id in set(rule.get("structural_risk_indicators", [])):
        structural_risk_active = trend in {
            "up",
            "spike_up",
            "negative",
            "deteriorating",
            "risk",
            "active",
            "yes",
        } or _bool_value(row.get("structural_risk_flag"))
        if structural_risk_active:
            _add_score(
                score_totals,
                context,
                row,
                signal="structural_risk",
                score_key="structural_risk_score",
                impact=structural_impact,
                direction="negative",
            )
            context["manual_review_required"] = True

    if _is_anomaly(row, trend_result, rule, default_rules):
        _add_score(
            score_totals,
            context,
            row,
            signal="anomaly",
            score_key="anomaly_score",
            impact=anomaly_impact,
            direction="unknown",
        )
        context["anomaly_alert"] = True
        context["manual_review_required"] = True

    if not _has_any_scoring_signal(row, context["evidence"]):
        context["evidence"].append(
            _evidence_entry(
                row,
                signal=f"observed_{trend}",
                direction=trend_result["direction"],
                score_impact=0.0,
            )
        )


def _check_indicator_coverage(
    rows: list[dict[str, Any]],
    rule: dict[str, Any],
    default_rules: dict[str, Any],
    context: dict[str, Any],
) -> None:
    present_indicators = {_clean_value(row.get("indicator_id")) for row in rows}
    key_indicators = set(rule.get("key_indicators", []))
    covered_key_indicators = present_indicators.intersection(key_indicators)
    missing_key_indicators = sorted(key_indicators - present_indicators)
    if missing_key_indicators:
        context["warning_flags"].append(
            default_rules["missing_data_behavior"]["missing_key_indicator_warning"]
        )
        context["evidence"].append(
            {
                "indicator_id": "coverage",
                "signal": "missing_key_indicators",
                "direction": "unknown",
                "score_impact": 0.0,
                "source": "",
                "source_url": "",
                "data_quality_status": "MISSING_DATA",
                "confidence": "low",
                "notes": ",".join(missing_key_indicators),
            }
        )

    if len(rows) < int(default_rules["insufficient_data_min_indicator_count"]):
        context["warning_flags"].append("INSUFFICIENT_INDICATOR_COUNT")
        context["manual_review_required"] = True

    coverage_ratio = (
        len(covered_key_indicators) / len(key_indicators) if key_indicators else 0.0
    )
    context["coverage_ratio"] = coverage_ratio
    if coverage_ratio < float(default_rules["key_indicator_coverage_min_ratio"]):
        context["warning_flags"].append("LOW_KEY_INDICATOR_COVERAGE")
        context["manual_review_required"] = True


def _check_row_quality(
    row: dict[str, Any], default_rules: dict[str, Any], context: dict[str, Any]
) -> None:
    data_quality = _clean_value(row.get("data_quality_status")).upper()
    confidence = _clean_value(row.get("confidence")).lower()
    indicator_id = _clean_value(row.get("indicator_id"))

    if not _required_row_fields_present(row):
        context["warning_flags"].append("MISSING_REQUIRED_INDICATOR_FIELDS")
        context["manual_review_required"] = True
        context["evidence"].append(
            _evidence_entry(
                row,
                signal="missing_required_fields",
                direction="unknown",
                score_impact=0.0,
            )
        )

    if data_quality in {value.upper() for value in default_rules["conflict_data_statuses"]}:
        context["warning_flags"].append("DATA_CONFLICT")
        if bool(default_rules["manual_review_on_data_conflict"]):
            context["manual_review_required"] = True
        context["evidence"].append(
            _evidence_entry(
                row,
                signal="data_conflict",
                direction="unknown",
                score_impact=0.0,
            )
        )
    if data_quality in {value.upper() for value in default_rules["stale_data_statuses"]}:
        context["warning_flags"].append("STALE_INDICATOR_DATA")
        if bool(default_rules["manual_review_on_stale_data"]):
            context["manual_review_required"] = True
    if data_quality in {value.upper() for value in default_rules["invalid_data_statuses"]}:
        context["warning_flags"].append("INVALID_INDICATOR_DATA")
        context["manual_review_required"] = True
    if confidence in {
        str(value).lower() for value in default_rules["low_confidence_values"]
    }:
        context["warning_flags"].append("LOW_INDICATOR_CONFIDENCE")
        if bool(default_rules["manual_review_on_low_confidence"]):
            context["manual_review_required"] = True
        context["evidence"].append(
            _evidence_entry(
                row,
                signal="low_indicator_confidence",
                direction="unknown",
                score_impact=0.0,
            )
        )
    if not indicator_id:
        context["warning_flags"].append("UNKNOWN_INDICATOR")
        context["manual_review_required"] = True


def _add_score(
    score_totals: dict[str, float],
    context: dict[str, Any],
    row: dict[str, Any],
    *,
    signal: str,
    score_key: str,
    impact: float,
    direction: str,
) -> None:
    score_totals[score_key] += impact
    context["evidence"].append(
        _evidence_entry(
            row,
            signal=signal,
            direction=direction,
            score_impact=impact,
        )
    )


def _evidence_entry(
    row: dict[str, Any], *, signal: str, direction: str, score_impact: float
) -> dict[str, Any]:
    return {
        "indicator_id": _clean_value(row.get("indicator_id")),
        "signal": signal,
        "direction": direction,
        "score_impact": float(score_impact),
        "source": _clean_value(row.get("source")),
        "source_url": _clean_value(row.get("source_url")),
        "data_quality_status": _clean_value(row.get("data_quality_status")),
        "confidence": _clean_value(row.get("confidence")),
        "notes": _clean_value(row.get("notes")),
    }


def _matches_trend(
    indicator_id: str, trend: str, mapping: dict[str, Any]
) -> bool:
    expected = mapping.get(indicator_id)
    if expected is None:
        return False
    if isinstance(expected, list):
        return trend in {_clean_token(value) for value in expected}
    return trend == _clean_token(expected)


def _is_anomaly(
    row: dict[str, Any],
    trend_result: dict[str, Any],
    rule: dict[str, Any],
    default_rules: dict[str, Any],
) -> bool:
    if _bool_value(row.get("anomaly_flag")):
        return True
    indicator_id = trend_result["indicator_id"]
    if indicator_id not in set(rule.get("anomaly_indicators", [])):
        return False
    if trend_result["trend"] in {"spike_up", "spike_down"}:
        return True
    pct_change = trend_result["pct_change"]
    if pct_change is None:
        return False
    return abs(pct_change) >= float(default_rules["anomaly_threshold_pct"])


def _has_any_scoring_signal(
    row: dict[str, Any], evidence: list[dict[str, Any]]
) -> bool:
    indicator_id = _clean_value(row.get("indicator_id"))
    return any(
        item.get("indicator_id") == indicator_id
        and item.get("score_impact", 0) > 0
        for item in evidence
    )


def _known_indicators(rule: dict[str, Any]) -> set[str]:
    known = set(rule.get("key_indicators", []))
    known.update(rule.get("recovery_when", {}).keys())
    known.update(rule.get("distress_when", {}).keys())
    known.update(rule.get("overheating_when", {}).keys())
    known.update(rule.get("structural_risk_indicators", []))
    known.update(rule.get("anomaly_indicators", []))
    return known


def _resolve_cycle_status(
    *,
    normalized_scores: dict[str, float],
    context: dict[str, Any],
    default_rules: dict[str, Any],
) -> str:
    if "INSUFFICIENT_INDICATOR_COUNT" in context["warning_flags"] or (
        context["coverage_ratio"] < float(default_rules["key_indicator_coverage_min_ratio"])
    ):
        return default_rules["missing_data_behavior"]["insufficient_data_status"]
    if context["anomaly_alert"] or normalized_scores["anomaly_score"] > 0:
        return "SECTOR_ANOMALY_REVIEW"
    if "DATA_CONFLICT" in context["warning_flags"]:
        return "SECTOR_MANUAL_REVIEW"

    ranking = [
        ("SECTOR_STRUCTURAL_RISK", normalized_scores["structural_risk_score"]),
        ("SECTOR_DISTRESS", normalized_scores["distress_score"]),
        ("SECTOR_RECOVERY", normalized_scores["recovery_score"]),
        ("SECTOR_OVERHEATING", normalized_scores["overheating_score"]),
    ]
    best_status, best_score = max(ranking, key=lambda item: item[1])
    if best_score <= 0:
        return "SECTOR_STABLE_OR_MIXED"

    top_scores = [score for _, score in ranking if score == best_score and score > 0]
    if len(top_scores) > 1:
        return "SECTOR_STABLE_OR_MIXED"
    return best_status


def _resolve_cycle_confidence(
    *,
    rows: list[dict[str, Any]],
    rule: dict[str, Any],
    default_rules: dict[str, Any],
    context: dict[str, Any],
) -> str:
    if not rows:
        return "low"
    if context["manual_review_required"] and default_rules["confidence_rules"].get(
        "low_on_manual_review", True
    ):
        return "low"

    key_count = len(rule.get("key_indicators", []))
    coverage_ratio = context["coverage_ratio"] if key_count else 0.0
    if coverage_ratio >= float(default_rules["confidence_rules"]["high_min_coverage_ratio"]):
        return "high"
    if coverage_ratio >= float(
        default_rules["confidence_rules"]["medium_min_coverage_ratio"]
    ):
        return "medium"
    return "low"


def _resolve_data_quality_status(context: dict[str, Any]) -> str:
    warnings = set(context["warning_flags"])
    if warnings.intersection({"DATA_CONFLICT", "INVALID_INDICATOR_DATA"}):
        return "DATA_QUALITY_REVIEW"
    if warnings.intersection(
        {
            "INSUFFICIENT_INDICATOR_COUNT",
            "LOW_KEY_INDICATOR_COVERAGE",
            "MISSING_KEY_INDICATORS",
        }
    ):
        return "INSUFFICIENT_DATA"
    if "STALE_INDICATOR_DATA" in warnings:
        return "STALE_DATA"
    if "LOW_INDICATOR_CONFIDENCE" in warnings:
        return "LOW_CONFIDENCE"
    return "VALID_DATA"


def _notes_for_status(
    cycle_status: str, cycle_confidence: str, context: dict[str, Any]
) -> str:
    if cycle_status == "INSUFFICIENT_DATA_FOR_SECTOR_CYCLE":
        return "Insufficient indicator coverage for sector-cycle scoring."
    if context["anomaly_alert"]:
        return "Anomaly detected; manual review required before any temporary adjustment."
    if context["manual_review_required"]:
        return f"Manual review required with {cycle_confidence} confidence."
    return f"Sector cycle status resolved with {cycle_confidence} confidence."


def _result(
    *,
    micro_sector: str,
    cycle_status: str,
    distress_score: float = 0.0,
    recovery_score: float = 0.0,
    overheating_score: float = 0.0,
    structural_risk_score: float = 0.0,
    anomaly_score: float = 0.0,
    cycle_confidence: str = "low",
    data_quality_status: str = "INSUFFICIENT_DATA",
    evidence: list[dict[str, Any]] | None = None,
    warning_flags: list[str] | None = None,
    anomaly_alert: bool = False,
    suggested_temporary_adjustment: dict[str, Any] | None = None,
    manual_review_required: bool = False,
    notes: str = "",
) -> dict[str, Any]:
    return {
        "micro_sector": _clean_value(micro_sector),
        "cycle_status": cycle_status,
        "distress_score": float(distress_score),
        "recovery_score": float(recovery_score),
        "overheating_score": float(overheating_score),
        "structural_risk_score": float(structural_risk_score),
        "anomaly_score": float(anomaly_score),
        "cycle_confidence": cycle_confidence,
        "data_quality_status": data_quality_status,
        "evidence": evidence or [],
        "warning_flags": warning_flags or [],
        "anomaly_alert": bool(anomaly_alert),
        "suggested_temporary_adjustment": suggested_temporary_adjustment,
        "manual_review_required": bool(manual_review_required),
        "notes": notes,
    }


def _new_context() -> dict[str, Any]:
    return {
        "coverage_ratio": 0.0,
        "evidence": [],
        "warning_flags": [],
        "manual_review_required": False,
        "anomaly_alert": False,
    }


def _required_row_fields_present(row: dict[str, Any]) -> bool:
    required_fields = ["indicator_id", "source", "data_quality_status", "confidence"]
    return all(not _is_missing(row.get(field)) for field in required_fields)


def _to_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "active"}
    return bool(value)


def _clean_value(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip()


def _clean_token(value: Any) -> str:
    return _clean_value(value).lower()


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(values))


def _dedupe_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen = set()
    for item in evidence:
        marker = (
            item.get("indicator_id"),
            item.get("signal"),
            item.get("score_impact"),
            item.get("notes"),
        )
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(item)
    return unique
