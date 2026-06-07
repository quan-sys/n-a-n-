"""Strict official finance value parser for REAL-DATA-01I-F."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from src.ingestion.official_finance_link_extractor import normalize_text


CANONICAL_FIELDS_01IF = [
    "revenue",
    "gross_profit",
    "operating_profit",
    "net_profit",
    "total_assets",
    "total_liabilities",
    "equity",
    "cash",
    "short_term_debt",
    "long_term_debt",
    "operating_cash_flow",
    "inventory",
]

OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF = [
    "ticker",
    "period",
    "period_type",
    "field_name",
    "value_vnd",
    "raw_value",
    "unit_raw",
    "unit_multiplier",
    "currency",
    "source_category",
    "source_name",
    "source_url",
    "final_url",
    "local_path",
    "file_hash",
    "page_number",
    "table_index",
    "row_index",
    "raw_label",
    "raw_context",
    "parser_name",
    "parse_status",
    "confidence_raw",
    "manual_review_required",
    "review_reason",
    "fetch_time",
    "notes",
]

FIELD_ALIASES_01IF = {
    "revenue": [
        "doanh thu ban hang va cung cap dich vu",
        "doanh thu thuan",
        "net revenue",
        "revenue",
    ],
    "gross_profit": ["loi nhuan gop", "gross profit"],
    "operating_profit": [
        "loi nhuan thuan tu hoat dong kinh doanh",
        "operating profit",
        "operating income",
    ],
    "net_profit": [
        "loi nhuan sau thue cua cong ty me",
        "loi nhuan sau thue",
        "profit after tax attributable to owners of the parent",
        "net profit after tax",
        "profit after tax",
    ],
    "total_assets": ["tong tai san", "total assets"],
    "total_liabilities": ["tong no phai tra", "no phai tra", "total liabilities"],
    "equity": ["von chu so huu", "owner s equity", "owners equity", "shareholders equity", "equity"],
    "cash": ["tien va tuong duong tien", "cash and cash equivalents"],
    "short_term_debt": ["vay va no thue tai chinh ngan han", "short term borrowings", "short term debt"],
    "long_term_debt": ["vay va no thue tai chinh dai han", "long term borrowings", "long term debt"],
    "operating_cash_flow": [
        "luu chuyen tien thuan tu hoat dong kinh doanh",
        "net cash flows from operating activities",
        "cash flows from operating activities",
    ],
    "inventory": ["hang ton kho", "inventories", "inventory"],
}

UNIT_PATTERNS_01IF = [
    ("billion VND", 1_000_000_000, "VND", ["ty dong", "tỷ đồng", "billion vnd", "vnd in bn", "vnd bn", "vnd in billion", "vnd billion"]),
    ("million VND", 1_000_000, "VND", ["trieu dong", "triệu đồng", "million vnd", "vnd million", "vnd in million"]),
    ("thousand VND", 1_000, "VND", ["nghin dong", "nghìn đồng", "thousand vnd", "000 vnd", "vnd thousand"]),
    ("VND", 1, "VND", ["dong", "đồng", "vnd"]),
]


def parse_official_finance_values_from_pages(
    *,
    document_row: dict[str, Any] | pd.Series,
    pages: list[Any],
    include_status_rows: bool = True,
    usable_only: bool = False,
) -> pd.DataFrame:
    rows = []
    fetch_time = datetime.now(UTC).replace(microsecond=0).isoformat()
    for page in pages:
        text = getattr(page, "text", "")
        if getattr(page, "extraction_status", "") != "TEXT_EXTRACTED":
            continue
        unit_raw, multiplier, currency, unit_status = detect_unit(text)
        lines = [line.strip() for line in str(text).splitlines() if line.strip()]
        for row_index, line in enumerate(lines, start=1):
            field = detect_field_name(line)
            if not field:
                continue
            if is_non_statement_context(line):
                continue
            raw_values = extract_numeric_tokens(line)
            parse_status = "FIELD_PARSED"
            manual_review = False
            review_reason = ""
            raw_value = ""
            value_vnd = ""
            confidence = "high" if str(document_row.get("consolidated_status", "")).lower() == "consolidated" else "medium"
            if not raw_values:
                parse_status = "FIELD_VALUE_AMBIGUOUS"
                manual_review = True
                review_reason = "FIELD_VALUE_NOT_FOUND"
                confidence = "low"
            elif len(raw_values) > 1:
                parse_status = "FIELD_VALUE_AMBIGUOUS"
                manual_review = True
                review_reason = "MULTIPLE_VALUES_IN_ROW"
                raw_value = "|".join(raw_values)
                confidence = "low"
            elif unit_status != "UNIT_DETECTED":
                parse_status = "UNIT_AMBIGUOUS_MANUAL_REVIEW"
                manual_review = True
                review_reason = unit_status
                raw_value = raw_values[0]
                confidence = "low"
            else:
                raw_value = raw_values[0]
                parsed_value = parse_numeric_value(raw_value)
                if parsed_value is None:
                    parse_status = "FIELD_VALUE_AMBIGUOUS"
                    manual_review = True
                    review_reason = "NUMERIC_PARSE_FAILED"
                    confidence = "low"
                else:
                    value_vnd = parsed_value * multiplier
            rows.append(
                _candidate_row(
                    document_row=document_row,
                    field_name=field,
                    value_vnd=value_vnd,
                    raw_value=raw_value,
                    unit_raw=unit_raw,
                    unit_multiplier=multiplier if unit_status == "UNIT_DETECTED" else "",
                    currency=currency if unit_status == "UNIT_DETECTED" else "",
                    page_number=getattr(page, "page_number", ""),
                    table_index="",
                    row_index=row_index,
                    raw_label=line[:180],
                    raw_context=short_context(line),
                    parser_name="official_pdf_text_line_parser_01if",
                    parse_status=parse_status,
                    confidence_raw=confidence,
                    manual_review_required=manual_review,
                    review_reason=review_reason,
                    fetch_time=fetch_time,
                    notes="explicit label/value parser; no missing values inferred",
                )
            )
    frame = pd.DataFrame(rows, columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF)
    if frame.empty:
        return frame
    output = mark_conflicting_duplicate_fields(frame)
    if not include_status_rows:
        output = output[output.apply(is_usable_candidate_row, axis=1)].copy()
    if usable_only:
        output = output[output.apply(is_usable_candidate_row, axis=1)].copy()
    return output[OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF]


def parse_official_finance_values_from_table_rows(
    *,
    document_row: dict[str, Any] | pd.Series,
    table_rows: list[Any],
    pages: list[Any] | None = None,
    include_status_rows: bool = True,
    usable_only: bool = False,
) -> pd.DataFrame:
    rows = []
    fetch_time = datetime.now(UTC).replace(microsecond=0).isoformat()
    page_text = {int(getattr(page, "page_number", 0)): str(getattr(page, "text", "") or "") for page in pages or []}
    for table_row in table_rows:
        cells = [str(cell or "").strip() for cell in getattr(table_row, "cells", []) if str(cell or "").strip()]
        if not cells:
            continue
        row_text = " | ".join(cells)
        field = detect_field_name(row_text)
        if not field:
            continue
        if is_non_statement_context(row_text):
            continue
        raw_label = _explicit_label_from_cells(cells)
        numeric_cells = _numeric_cells(cells)
        page_number = getattr(table_row, "page_number", "")
        unit_context = " ".join(
            [
                str(getattr(table_row, "unit_context", "") or ""),
                page_text.get(int(page_number or 0), "")[:1000],
                row_text,
            ]
        )
        unit_raw, multiplier, currency, unit_status = detect_unit(unit_context)
        parse_status = "FIELD_PARSED"
        manual_review = False
        review_reason = ""
        raw_value = ""
        value_vnd: float | str = ""
        confidence = "high" if str(document_row.get("consolidated_status", "")).lower() == "consolidated" else "medium"
        if not raw_label:
            parse_status = "FIELD_LABEL_AMBIGUOUS"
            manual_review = True
            review_reason = "FIELD_LABEL_NOT_EXPLICIT"
            confidence = "low"
        elif not numeric_cells:
            parse_status = "FIELD_VALUE_AMBIGUOUS"
            manual_review = True
            review_reason = "FIELD_VALUE_NOT_FOUND"
            confidence = "low"
        elif unit_status != "UNIT_DETECTED":
            parse_status = "UNIT_AMBIGUOUS_MANUAL_REVIEW"
            manual_review = True
            review_reason = unit_status
            raw_value = "|".join(value for value, _ in numeric_cells)
            confidence = "low"
        else:
            chosen = _choose_table_numeric_value(
                numeric_cells=numeric_cells,
                column_contexts=list(getattr(table_row, "column_contexts", []) or []),
                document_period=str(document_row.get("period", "")),
            )
            if chosen is None:
                parse_status = "FIELD_VALUE_AMBIGUOUS"
                manual_review = True
                review_reason = "MULTIPLE_VALUES_IN_ROW"
                raw_value = "|".join(value for value, _ in numeric_cells)
                confidence = "low"
            else:
                raw_value = chosen
                parsed_value = parse_numeric_value(raw_value)
                if parsed_value is None:
                    parse_status = "FIELD_VALUE_AMBIGUOUS"
                    manual_review = True
                    review_reason = "NUMERIC_PARSE_FAILED"
                    confidence = "low"
                else:
                    value_vnd = parsed_value * multiplier
        rows.append(
            _candidate_row(
                document_row=document_row,
                field_name=field,
                value_vnd=value_vnd,
                raw_value=raw_value,
                unit_raw=unit_raw,
                unit_multiplier=multiplier if unit_status == "UNIT_DETECTED" else "",
                currency=currency if unit_status == "UNIT_DETECTED" else "",
                page_number=page_number,
                table_index=getattr(table_row, "table_index", ""),
                row_index=getattr(table_row, "row_index", ""),
                raw_label=raw_label[:180] if raw_label else row_text[:180],
                raw_context=short_context(row_text),
                parser_name="official_pdf_table_row_parser_01if_patch1",
                parse_status=parse_status,
                confidence_raw=confidence,
                manual_review_required=manual_review,
                review_reason=review_reason,
                fetch_time=fetch_time,
                notes=f"{getattr(table_row, 'notes', '')}; no missing values inferred or zero-filled".strip("; "),
            )
        )
    frame = pd.DataFrame(rows, columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF)
    if frame.empty:
        return frame
    output = mark_conflicting_duplicate_fields(frame)
    if not include_status_rows:
        output = output[output.apply(is_usable_candidate_row, axis=1)].copy()
    if usable_only:
        output = output[output.apply(is_usable_candidate_row, axis=1)].copy()
    return output[OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF]


def detect_field_name(value: Any) -> str:
    normalized = normalize_text(value)
    matches = []
    for field_name, aliases in FIELD_ALIASES_01IF.items():
        if any(_contains_alias(normalized, alias) for alias in aliases):
            matches.append(field_name)
    matches = _dedupe(matches)
    if len(matches) == 1:
        return matches[0]
    return ""


def detect_unit(text: Any) -> tuple[str, int, str, str]:
    normalized = normalize_text(text)
    if "vnd" in normalized and any(token in normalized for token in ["billion", "bn"]):
        return "billion VND", 1_000_000_000, "VND", "UNIT_DETECTED"
    if "vnd" in normalized and "million" in normalized:
        return "million VND", 1_000_000, "VND", "UNIT_DETECTED"
    if "vnd" in normalized and "thousand" in normalized:
        return "thousand VND", 1_000, "VND", "UNIT_DETECTED"
    for unit_raw, multiplier, currency, aliases in UNIT_PATTERNS_01IF:
        if any(normalize_text(alias) in normalized for alias in aliases):
            return unit_raw, multiplier, currency, "UNIT_DETECTED"
    return "", 0, "", "UNIT_AMBIGUOUS_MANUAL_REVIEW"


def extract_numeric_tokens(line: Any) -> list[str]:
    text = str(line or "")
    candidates = re.findall(r"\(?-?\d[\d., ]{2,}\)?", text)
    cleaned = []
    for candidate in candidates:
        value = candidate.strip()
        if re.fullmatch(r"\d{4}", value):
            continue
        digit_count = len(re.sub(r"\D", "", value))
        if digit_count < 3:
            continue
        if value.endswith(".") and digit_count <= 3:
            continue
        if parse_numeric_value(value) is not None:
            cleaned.append(value)
    return cleaned


def parse_numeric_value(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    cleaned = re.sub(r"[^0-9,.\-]", "", text)
    if not cleaned or cleaned in {"-", ".", ","}:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts[-1]) in {1, 2}:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts) > 2 or len(parts[-1]) == 3:
            cleaned = cleaned.replace(".", "")
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return -number if negative else number


def mark_conflicting_duplicate_fields(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    output = frame.copy()
    parsed = output[output["parse_status"] == "FIELD_PARSED"].copy()
    for key, group in parsed.groupby(["ticker", "period", "file_hash", "field_name"], dropna=False):
        values = {str(value) for value in group["value_vnd"] if str(value).strip()}
        if len(values) <= 1:
            continue
        mask = (
            (output["ticker"] == key[0])
            & (output["period"] == key[1])
            & (output["file_hash"] == key[2])
            & (output["field_name"] == key[3])
        )
        output.loc[mask, "parse_status"] = "FIELD_LABEL_AMBIGUOUS"
        output.loc[mask, "manual_review_required"] = True
        output.loc[mask, "review_reason"] = output.loc[mask, "review_reason"].apply(
            lambda value: _append_reason(value, "CONFLICTING_DUPLICATE_LABELS")
        )
        output.loc[mask, "confidence_raw"] = "low"
    return output[OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF]


def split_usable_and_status_rows(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        empty = pd.DataFrame(columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF)
        return empty.copy(), empty.copy()
    normalized = frame.copy()
    for column in OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF:
        if column not in normalized.columns:
            normalized[column] = ""
    usable_mask = normalized.apply(is_usable_candidate_row, axis=1)
    usable = normalized[usable_mask].copy()
    status = normalized[~usable_mask].copy()
    return usable[OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF], status[OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF]


def filter_usable_candidate_rows(frame: pd.DataFrame) -> pd.DataFrame:
    usable, _ = split_usable_and_status_rows(frame)
    return usable


def is_usable_candidate_row(row: pd.Series | dict[str, Any]) -> bool:
    return all(
        [
            str(row.get("parse_status", "")) == "FIELD_PARSED",
            str(row.get("field_name", "")).strip(),
            str(row.get("value_vnd", "")).strip(),
            str(row.get("raw_value", "")).strip(),
            str(row.get("raw_label", "")).strip(),
            str(row.get("source_url", "")).strip(),
            str(row.get("local_path", "")).strip(),
            str(row.get("file_hash", "")).strip(),
            str(row.get("page_number", "")).strip(),
            str(row.get("unit_raw", "")).strip() or str(row.get("unit_multiplier", "")).strip(),
        ]
    )


def is_non_statement_context(value: Any) -> bool:
    normalized = normalize_text(value)
    blocked_phrases = [
        "giao dich",
        "transactions",
        "signed within the year",
        "35 tong tai san",
        "35 total assets",
        "as per the consolidated financial",
    ]
    return any(phrase in normalized for phrase in blocked_phrases)


def short_context(value: Any, max_chars: int = 240) -> str:
    return " ".join(str(value or "").split())[:max_chars]


def _candidate_row(
    *,
    document_row: dict[str, Any] | pd.Series,
    field_name: str,
    value_vnd: Any,
    raw_value: Any,
    unit_raw: Any,
    unit_multiplier: Any,
    currency: Any,
    page_number: Any,
    table_index: Any,
    row_index: Any,
    raw_label: Any,
    raw_context: Any,
    parser_name: str,
    parse_status: str,
    confidence_raw: str,
    manual_review_required: bool,
    review_reason: str,
    fetch_time: str,
    notes: str,
) -> dict[str, Any]:
    return {
        "ticker": document_row.get("ticker", ""),
        "period": document_row.get("period", ""),
        "period_type": "quarter" if "-Q" in str(document_row.get("period", "")).upper() else "annual",
        "field_name": field_name,
        "value_vnd": value_vnd,
        "raw_value": raw_value,
        "unit_raw": unit_raw,
        "unit_multiplier": unit_multiplier,
        "currency": currency,
        "source_category": "official_company_document",
        "source_name": "official_pdf_parser_01if",
        "source_url": document_row.get("source_url", ""),
        "final_url": document_row.get("final_url", ""),
        "local_path": document_row.get("local_path", ""),
        "file_hash": document_row.get("file_hash", ""),
        "page_number": page_number,
        "table_index": table_index,
        "row_index": row_index,
        "raw_label": raw_label,
        "raw_context": raw_context,
        "parser_name": parser_name,
        "parse_status": parse_status,
        "confidence_raw": confidence_raw,
        "manual_review_required": manual_review_required,
        "review_reason": review_reason,
        "fetch_time": fetch_time,
        "notes": notes,
    }


def _explicit_label_from_cells(cells: list[str]) -> str:
    label_parts = []
    for cell in cells:
        if extract_numeric_tokens(cell):
            break
        text = str(cell or "").strip()
        if text and not re.fullmatch(r"\d{1,3}", text):
            label_parts.append(text)
    candidate = " ".join(label_parts).strip()
    if detect_field_name(candidate):
        return candidate
    full = " ".join(cells).strip()
    return full if detect_field_name(full) else ""


def _numeric_cells(cells: list[str]) -> list[tuple[str, int]]:
    output = []
    for index, cell in enumerate(cells):
        for token in extract_numeric_tokens(cell):
            output.append((token, index))
    return output


def _choose_table_numeric_value(
    *,
    numeric_cells: list[tuple[str, int]],
    column_contexts: list[str],
    document_period: str,
) -> str | None:
    if len(numeric_cells) == 1:
        return numeric_cells[0][0]
    if not column_contexts:
        return None
    normalized_contexts = [normalize_text(context) for context in column_contexts]
    normalized_period = normalize_text(document_period)
    target_year_match = re.search(r"\b(20\d{2})\b", normalized_period)
    target_year = target_year_match.group(1) if target_year_match else ""
    current_terms = ["current", "this period", "this quarter", "ky nay", "quy nay", "period end", "31 03", "31 12", "30 06", "30 09"]
    candidates = []
    for raw_value, col_index in numeric_cells:
        context = normalized_contexts[col_index] if col_index < len(normalized_contexts) else ""
        score = 0
        if any(term in context for term in current_terms):
            score += 3
        if target_year and target_year in context:
            score += 2
        if "previous" in context or "prior" in context or "nam truoc" in context or "ky truoc" in context:
            score -= 3
        if score > 0:
            candidates.append((score, -col_index, raw_value))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    top_score = candidates[0][0]
    top_values = [value for score, _, value in candidates if score == top_score]
    if len(set(top_values)) != 1 and len(top_values) > 1:
        return None
    return candidates[0][2]


def _contains_alias(normalized_text: str, alias: str) -> bool:
    normalized_alias = normalize_text(alias)
    return bool(normalized_alias and normalized_alias in normalized_text)


def _append_reason(existing: Any, reason: str) -> str:
    parts = [part.strip() for part in str(existing or "").split(";") if part.strip()]
    if reason not in parts:
        parts.append(reason)
    return ";".join(parts)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
