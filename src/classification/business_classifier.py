"""Deterministic L1 business classification."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None


CLASSIFICATION_OUTPUT_COLUMNS = [
    "ticker",
    "classification_status",
    "primary_micro_sector",
    "secondary_micro_sector",
    "primary_exposure_weight",
    "secondary_exposure_weight",
    "archetype",
    "drivers",
    "classification_confidence",
    "classification_notes",
    "classification_evidence",
    "warning_flags",
    "manual_review_required",
]


def load_micro_sector_taxonomy(path: str) -> dict[str, Any]:
    """Load the micro-sector taxonomy YAML."""

    return _load_yaml_mapping(path, "Micro-sector taxonomy")


def load_business_classification_rules(path: str) -> dict[str, Any]:
    """Load L1 business classification rules YAML."""

    return _load_yaml_mapping(path, "Business classification rules")


def classify_businesses(
    l0_basic_df: pd.DataFrame,
    company_profile_df: pd.DataFrame | None = None,
    financial_statement_df: pd.DataFrame | None = None,
    segment_df: pd.DataFrame | None = None,
    manual_notes_df: pd.DataFrame | None = None,
    taxonomy: dict[str, Any] | None = None,
    rules: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Classify eligible tickers into micro-sectors and archetype hints."""

    if not isinstance(l0_basic_df, pd.DataFrame):
        raise TypeError("l0_basic_df must be a pandas DataFrame.")

    active_taxonomy = taxonomy or {"micro_sectors": {}}
    active_rules = rules or {}
    rows: list[dict[str, Any]] = []
    for ticker in _ordered_tickers(l0_basic_df):
        l0_row = _first_matching_row(l0_basic_df, ticker)
        profile_rows = _matching_rows(company_profile_df, ticker)
        segment_rows = _matching_rows(segment_df, ticker)
        manual_rows = _matching_rows(manual_notes_df, ticker)
        financial_rows = _matching_rows(financial_statement_df, ticker)

        context = _new_context(ticker)
        l0_status = _clean_text(_row_value(l0_row, "l0_basic_status"))
        if _is_blocked_status(l0_status, active_rules):
            rows.append(_not_classified_result(context, l0_status, active_rules))
            continue

        provisional = _is_provisional_status(l0_status, active_rules)
        if not provisional and not _is_eligible_status(l0_status, active_rules):
            rows.append(_not_classified_result(context, l0_status, active_rules))
            continue

        if provisional:
            context["warning_flags"].append("L0_BASIC_MANUAL_REVIEW")
            context["classification_evidence"].append(f"l0_basic_status={l0_status}")

        _apply_l0_confidence_warning(context, l0_row)
        _apply_profile_quality_warning(context, profile_rows)

        segment_result = _classify_from_segments(
            segment_rows, active_taxonomy, active_rules
        )
        text_result = _classify_from_text(
            profile_rows, manual_rows, active_taxonomy, active_rules
        )

        chosen = _choose_classification_source(
            segment_result, text_result, active_rules
        )
        context["classification_evidence"].extend(chosen["evidence"])
        context["warning_flags"].extend(chosen["warnings"])

        if _segment_text_conflict(segment_result, text_result):
            context["warning_flags"].append("CONFLICTING_CLASSIFICATION_SIGNALS")
            context["classification_evidence"].append(
                "segment classification conflicts with profile text"
            )

        primary = chosen["primary_micro_sector"]
        secondary = chosen["secondary_micro_sector"]
        if primary == "unknown":
            context["warning_flags"].append("UNKNOWN_MICRO_SECTOR")

        if primary == "holding_company":
            context["warning_flags"].append("HOLDING_COMPANY_REVIEW")

        if not _has_business_description(profile_rows):
            context["warning_flags"].append("MISSING_BUSINESS_DESCRIPTION")

        if _has_financial_quality_issue(financial_rows):
            context["warning_flags"].append("FINANCIAL_DATA_QUALITY_REVIEW")

        confidence = _resolve_confidence(
            chosen=chosen,
            warning_flags=context["warning_flags"],
            provisional=provisional,
            rules=active_rules,
        )
        status = _resolve_status(
            primary=primary,
            confidence=confidence,
            warning_flags=context["warning_flags"],
            provisional=provisional,
            rules=active_rules,
        )
        manual_review_required = (
            status in {"MANUAL_REVIEW", "PROVISIONAL_CLASSIFICATION"}
            or confidence == "low"
            or bool(_manual_review_intersection(context, active_rules))
        )
        archetype = _archetype_for_micro_sector(primary, active_taxonomy, active_rules)
        drivers = _drivers_for_micro_sectors(
            [primary, secondary], active_taxonomy
        )

        rows.append(
            {
                "ticker": ticker,
                "classification_status": status,
                "primary_micro_sector": primary,
                "secondary_micro_sector": secondary,
                "primary_exposure_weight": chosen["primary_exposure_weight"],
                "secondary_exposure_weight": chosen["secondary_exposure_weight"],
                "archetype": archetype,
                "drivers": drivers,
                "classification_confidence": confidence,
                "classification_notes": _classification_notes(
                    status, confidence, context["warning_flags"]
                ),
                "classification_evidence": _dedupe(context["classification_evidence"]),
                "warning_flags": _dedupe(context["warning_flags"]),
                "manual_review_required": bool(manual_review_required),
            }
        )

    result = pd.DataFrame(rows, columns=CLASSIFICATION_OUTPUT_COLUMNS)
    result["manual_review_required"] = result["manual_review_required"].astype(object)
    return result


def serialize_classification_output(
    df: pd.DataFrame,
    list_columns: list[str] | None = None,
    separator: str = ";",
) -> pd.DataFrame:
    """Return a copy with list-valued classification columns serialized."""

    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame.")

    target_columns = list_columns or [
        "drivers",
        "classification_evidence",
        "warning_flags",
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


def _classify_from_segments(
    segment_rows: pd.DataFrame,
    taxonomy: dict[str, Any],
    rules: dict[str, Any],
) -> dict[str, Any]:
    result = _empty_classification_result(source="segment")
    if segment_rows.empty:
        return result

    metric_field = _segment_metric_field(segment_rows, rules)
    if not metric_field:
        metric_field = "__equal_weight__"
        segment_rows = segment_rows.copy()
        segment_rows[metric_field] = 1.0

    sector_values: dict[str, float] = {}
    evidence: list[str] = []
    for _, row in segment_rows.iterrows():
        segment_name = str(_row_value(row, "segment_name") or "")
        sector, keyword = _best_keyword_sector(segment_name, taxonomy)
        value = _to_number(_row_value(row, metric_field)) or 0.0
        if sector == "unknown":
            evidence.append(f"segment '{segment_name}' did not match taxonomy")
            continue
        sector_values[sector] = sector_values.get(sector, 0.0) + value
        evidence.append(
            f"segment '{segment_name}' matched {sector}"
            + (f" via '{keyword}'" if keyword else "")
        )

    if not sector_values:
        return result

    total = sum(value for value in sector_values.values() if value > 0)
    if total <= 0:
        total = float(len(sector_values))
        sector_values = {sector: 1.0 for sector in sector_values}

    ranked = sorted(sector_values.items(), key=lambda item: item[1], reverse=True)
    weights = [(sector, value / total) for sector, value in ranked]
    secondary_min_weight = float(
        rules.get("confidence_thresholds", {}).get("secondary_min_weight", 0.20)
    )
    primary_sector, primary_weight = weights[0]
    secondary_sector = "unknown"
    secondary_weight = 0.0
    if len(weights) > 1 and weights[1][1] >= secondary_min_weight:
        secondary_sector, secondary_weight = weights[1]

    result.update(
        {
            "primary_micro_sector": primary_sector,
            "secondary_micro_sector": secondary_sector,
            "primary_exposure_weight": round(primary_weight, 4),
            "secondary_exposure_weight": round(secondary_weight, 4),
            "evidence_strength": int(round(primary_weight * 10)),
            "has_segment_data": True,
            "evidence": [
                *evidence,
                f"segment_metric={metric_field}",
                f"primary_segment_weight={primary_weight:.4f}",
            ],
        }
    )
    if secondary_sector != "unknown":
        result["evidence"].append(f"secondary_segment_weight={secondary_weight:.4f}")
    if len(weights) > 1 and abs(weights[0][1] - weights[1][1]) <= 0.10:
        result["warnings"].append("SIMILAR_MICRO_SECTOR_SCORES")
    return result


def _classify_from_text(
    profile_rows: pd.DataFrame,
    manual_rows: pd.DataFrame,
    taxonomy: dict[str, Any],
    rules: dict[str, Any],
) -> dict[str, Any]:
    result = _empty_classification_result(source="text")
    text_fields = _text_fields(profile_rows, manual_rows)
    if not text_fields:
        return result

    evidence_strengths: dict[str, int] = {}
    field_matches: dict[str, set[str]] = {}
    evidence: list[str] = []
    weights = rules.get("evidence_weights", {})
    for field_name, text in text_fields:
        field_weight = int(weights.get(field_name, 1))
        matches = _keyword_matches_by_sector(text, taxonomy)
        for sector, keywords in matches.items():
            evidence_strengths[sector] = evidence_strengths.get(sector, 0) + field_weight
            field_matches.setdefault(field_name, set()).add(sector)
            evidence.append(
                f"{field_name} matched {sector} via {','.join(sorted(keywords))}"
            )

    if not evidence_strengths:
        return result

    ranked = sorted(evidence_strengths.items(), key=lambda item: item[1], reverse=True)
    primary, primary_strength = ranked[0]
    secondary = "unknown"
    secondary_weight = 0.0
    warnings: list[str] = []
    if len(ranked) > 1:
        strength_delta = primary_strength - ranked[1][1]
        if strength_delta <= int(
            rules.get("confidence_thresholds", {}).get("similar_score_delta", 2)
        ):
            warnings.append("SIMILAR_MICRO_SECTOR_SCORES")
            secondary = ranked[1][0]
            secondary_weight = 0.40

    if _industry_description_conflict(field_matches):
        warnings.append("CONFLICTING_CLASSIFICATION_SIGNALS")

    if _raw_industry_only(text_fields):
        warnings.append("BROAD_INDUSTRY_ONLY")

    result.update(
        {
            "primary_micro_sector": primary,
            "secondary_micro_sector": secondary,
            "primary_exposure_weight": 1.0 if secondary == "unknown" else 0.60,
            "secondary_exposure_weight": secondary_weight,
            "evidence_strength": primary_strength,
            "evidence": evidence,
            "warnings": warnings,
        }
    )
    return result


def _choose_classification_source(
    segment_result: dict[str, Any],
    text_result: dict[str, Any],
    rules: dict[str, Any],
) -> dict[str, Any]:
    if segment_result["primary_micro_sector"] != "unknown":
        chosen = dict(segment_result)
        if text_result["primary_micro_sector"] != "unknown":
            chosen["evidence"].extend(text_result["evidence"])
            chosen["warnings"].extend(text_result["warnings"])
        return chosen
    if text_result["primary_micro_sector"] != "unknown":
        return text_result
    fallback = rules.get("fallback_rules", {})
    result = _empty_classification_result(source="fallback")
    result["primary_micro_sector"] = fallback.get("unknown_micro_sector", "unknown")
    result["archetype"] = fallback.get("unknown_archetype", "unknown")
    result["warnings"].append("UNKNOWN_MICRO_SECTOR")
    result["evidence"].append("no matching segment or text evidence")
    return result


def _not_classified_result(
    context: dict[str, Any], l0_status: str, rules: dict[str, Any]
) -> dict[str, Any]:
    fallback = rules.get("fallback_rules", {})
    reason = (
        fallback.get("not_classified_reason_failed_l0", "FAILED_L0_BASIC_INVESTABILITY")
        if l0_status == "L0_REJECT"
        else fallback.get(
            "not_classified_reason_insufficient",
            "INSUFFICIENT_DATA_FOR_CLASSIFICATION",
        )
    )
    return {
        "ticker": context["ticker"],
        "classification_status": "NOT_CLASSIFIED",
        "primary_micro_sector": fallback.get("unknown_micro_sector", "unknown"),
        "secondary_micro_sector": "unknown",
        "primary_exposure_weight": 0.0,
        "secondary_exposure_weight": 0.0,
        "archetype": fallback.get("unknown_archetype", "unknown"),
        "drivers": [],
        "classification_confidence": "low",
        "classification_notes": reason,
        "classification_evidence": [f"l0_basic_status={l0_status}"],
        "warning_flags": [reason],
        "manual_review_required": True,
    }


def _resolve_confidence(
    chosen: dict[str, Any],
    warning_flags: list[str],
    provisional: bool,
    rules: dict[str, Any],
) -> str:
    if provisional:
        return "low"
    if chosen["primary_micro_sector"] == "unknown":
        return "low"
    warnings = set(warning_flags)
    if warnings.intersection(_manual_review_triggers(rules)):
        return "low"
    thresholds = rules.get("confidence_thresholds", {})
    if chosen.get("has_segment_data") and chosen["primary_exposure_weight"] >= float(
        thresholds.get("high_min_primary_weight", 0.65)
    ):
        return "high"
    if chosen["evidence_strength"] >= int(thresholds.get("medium_min_score", 3)):
        if "BROAD_INDUSTRY_ONLY" in warnings:
            return rules.get("minimum_data_requirements", {}).get(
                "raw_industry_only_confidence", "low"
            )
        return "medium"
    return "low"


def _resolve_status(
    primary: str,
    confidence: str,
    warning_flags: list[str],
    provisional: bool,
    rules: dict[str, Any],
) -> str:
    if primary == "unknown":
        return "MANUAL_REVIEW"
    if provisional:
        return "PROVISIONAL_CLASSIFICATION"
    if set(warning_flags).intersection(_manual_review_triggers(rules)):
        return "MANUAL_REVIEW"
    if confidence == "low":
        return "MANUAL_REVIEW"
    return "CLASSIFIED"


def _classification_notes(
    status: str, confidence: str, warning_flags: list[str]
) -> str:
    if status == "CLASSIFIED":
        return f"classified with {confidence} confidence"
    if status == "PROVISIONAL_CLASSIFICATION":
        return "provisional classification; manual review required"
    if warning_flags:
        return "manual review required: " + ", ".join(_dedupe(warning_flags))
    return "manual review required"


def _segment_metric_field(segment_rows: pd.DataFrame, rules: dict[str, Any]) -> str:
    for field in rules.get("segment_priority", []):
        if field in segment_rows.columns:
            values = pd.to_numeric(segment_rows[field], errors="coerce").fillna(0)
            if values.abs().sum() > 0:
                return field
    return ""


def _best_keyword_sector(text: str, taxonomy: dict[str, Any]) -> tuple[str, str]:
    normalized_text = _normalize_text(text)
    best_sector = "unknown"
    best_keyword = ""
    for sector, keywords in _taxonomy_keywords(taxonomy).items():
        for keyword in keywords:
            normalized_keyword = _normalize_text(keyword)
            if _keyword_in_text(normalized_text, normalized_keyword):
                if len(normalized_keyword) > len(_normalize_text(best_keyword)):
                    best_sector = sector
                    best_keyword = keyword
    return best_sector, best_keyword


def _keyword_matches_by_sector(
    text: str, taxonomy: dict[str, Any]
) -> dict[str, set[str]]:
    normalized_text = _normalize_text(text)
    matches: dict[str, set[str]] = {}
    for sector, keywords in _taxonomy_keywords(taxonomy).items():
        for keyword in keywords:
            normalized_keyword = _normalize_text(keyword)
            if _keyword_in_text(normalized_text, normalized_keyword):
                matches.setdefault(sector, set()).add(keyword)
    return matches


def _taxonomy_keywords(taxonomy: dict[str, Any]) -> dict[str, list[str]]:
    return {
        sector: config.get("keyword_hints", [])
        for sector, config in taxonomy.get("micro_sectors", {}).items()
    }


def _archetype_for_micro_sector(
    micro_sector: str, taxonomy: dict[str, Any], rules: dict[str, Any]
) -> str:
    config = taxonomy.get("micro_sectors", {}).get(micro_sector, {})
    archetypes = config.get("allowed_archetypes", [])
    if archetypes:
        return archetypes[0]
    return rules.get("fallback_rules", {}).get("unknown_archetype", "unknown")


def _drivers_for_micro_sectors(
    micro_sectors: list[str], taxonomy: dict[str, Any]
) -> list[str]:
    drivers: list[str] = []
    for micro_sector in micro_sectors:
        if not micro_sector or micro_sector == "unknown":
            continue
        drivers.extend(
            taxonomy.get("micro_sectors", {})
            .get(micro_sector, {})
            .get("driver_hints", [])
        )
    return _dedupe(drivers)


def _text_fields(
    profile_rows: pd.DataFrame, manual_rows: pd.DataFrame
) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    if not profile_rows.empty:
        row = profile_rows.iloc[0]
        for field in ["business_description", "industry_raw", "company_name"]:
            value = _row_value(row, field)
            if not _is_missing(value):
                fields.append((field, str(value)))
        for field in ["classification_notes", "manual_notes"]:
            value = _row_value(row, field)
            if not _is_missing(value):
                fields.append((field, str(value)))
    if not manual_rows.empty:
        row = manual_rows.iloc[0]
        for field in ["classification_notes", "manual_notes"]:
            value = _row_value(row, field)
            if not _is_missing(value):
                fields.append((field, str(value)))
    return fields


def _industry_description_conflict(field_matches: dict[str, set[str]]) -> bool:
    description_matches = field_matches.get("business_description", set())
    industry_matches = field_matches.get("industry_raw", set())
    if not description_matches or not industry_matches:
        return False
    return description_matches.isdisjoint(industry_matches)


def _segment_text_conflict(
    segment_result: dict[str, Any], text_result: dict[str, Any]
) -> bool:
    segment_sector = segment_result["primary_micro_sector"]
    text_sector = text_result["primary_micro_sector"]
    if segment_sector == "unknown" or text_sector == "unknown":
        return False
    return segment_sector != text_sector


def _raw_industry_only(text_fields: list[tuple[str, str]]) -> bool:
    field_names = {field for field, _ in text_fields}
    return bool(field_names) and field_names.issubset({"industry_raw", "company_name"})


def _has_business_description(profile_rows: pd.DataFrame) -> bool:
    if profile_rows.empty or "business_description" not in profile_rows.columns:
        return False
    return profile_rows["business_description"].map(lambda value: not _is_missing(value)).any()


def _has_financial_quality_issue(financial_rows: pd.DataFrame) -> bool:
    if financial_rows.empty:
        return False
    statuses = _column_text_values(financial_rows, "quality_status")
    if statuses - {"VALID_DATA"}:
        return True
    if _flatten_issue_column(financial_rows, "quality_warnings"):
        return True
    if _flatten_issue_column(financial_rows, "quality_errors"):
        return True
    return False


def _apply_l0_confidence_warning(context: dict[str, Any], l0_row: pd.Series) -> None:
    if _clean_text(_row_value(l0_row, "confidence")) == "LOW":
        context["warning_flags"].append("LOW_L0_BASIC_CONFIDENCE")


def _apply_profile_quality_warning(
    context: dict[str, Any], profile_rows: pd.DataFrame
) -> None:
    if profile_rows.empty:
        context["warning_flags"].append("MISSING_COMPANY_PROFILE")
        return
    if (
        "manual_review_required" in profile_rows.columns
        and profile_rows["manual_review_required"].map(bool).any()
    ):
        context["warning_flags"].append("PROFILE_DATA_QUALITY_REVIEW")
    statuses = _column_text_values(profile_rows, "quality_status")
    if statuses - {"VALID_DATA"}:
        context["warning_flags"].append("PROFILE_DATA_QUALITY_REVIEW")


def _manual_review_intersection(
    context: dict[str, Any], rules: dict[str, Any]
) -> set[str]:
    return set(context["warning_flags"]).intersection(_manual_review_triggers(rules))


def _manual_review_triggers(rules: dict[str, Any]) -> set[str]:
    return set(rules.get("manual_review_triggers", []))


def _is_blocked_status(l0_status: str, rules: dict[str, Any]) -> bool:
    return l0_status in {_clean_text(status) for status in rules.get("blocked_l0_basic_statuses", [])}


def _is_provisional_status(l0_status: str, rules: dict[str, Any]) -> bool:
    return l0_status in {_clean_text(status) for status in rules.get("provisional_l0_basic_statuses", [])}


def _is_eligible_status(l0_status: str, rules: dict[str, Any]) -> bool:
    return l0_status in {_clean_text(status) for status in rules.get("eligible_l0_basic_statuses", [])}


def _ordered_tickers(l0_basic_df: pd.DataFrame) -> list[str]:
    if "ticker" not in l0_basic_df.columns:
        return []
    tickers: list[str] = []
    for ticker in l0_basic_df["ticker"]:
        normalized = _clean_text(ticker)
        if normalized and normalized not in tickers:
            tickers.append(normalized)
    return tickers


def _matching_rows(df: pd.DataFrame | None, ticker: str) -> pd.DataFrame:
    if df is None or df.empty or "ticker" not in df.columns:
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
        elif isinstance(value, str) and value.strip() and value.strip() != "[]":
            issues.add(_clean_text(value))
    return issues


def _empty_classification_result(source: str) -> dict[str, Any]:
    return {
        "source": source,
        "primary_micro_sector": "unknown",
        "secondary_micro_sector": "unknown",
        "primary_exposure_weight": 0.0,
        "secondary_exposure_weight": 0.0,
        "evidence_strength": 0,
        "has_segment_data": False,
        "evidence": [],
        "warnings": [],
    }


def _new_context(ticker: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "classification_evidence": [],
        "warning_flags": [],
    }


def _normalize_text(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).replace("_", " ").strip().lower()


def _keyword_in_text(normalized_text: str, normalized_keyword: str) -> bool:
    if not normalized_keyword:
        return False
    pattern = rf"(?<![a-z0-9]){re.escape(normalized_keyword)}(?![a-z0-9])"
    return re.search(pattern, normalized_text) is not None


def _clean_text(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip().upper()


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


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(values))


def _load_yaml_mapping(path: str, label: str) -> dict[str, Any]:
    if yaml is None:
        raise ImportError(
            f"PyYAML is required to load {label}. Install 'pyyaml' first."
        )
    yaml_path = Path(path)
    with yaml_path.open("r", encoding="utf-8") as yaml_file:
        data = yaml.safe_load(yaml_file)
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain a YAML mapping.")
    return data
