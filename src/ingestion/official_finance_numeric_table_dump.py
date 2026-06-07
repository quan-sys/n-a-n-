"""Numeric-heavy table dump for REAL-DATA-01I-F-PATCH3-PATCH2.

This module preserves raw numeric table evidence from public BCTC documents
without treating dumped tables as confirmed finance values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingestion.official_finance_link_extractor import normalize_text
from src.ingestion.official_finance_value_parser import (
    OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF,
    detect_unit,
    extract_numeric_tokens,
    parse_numeric_value,
)
from src.ingestion.official_pdf_text_extractor import ExtractedPdfPage, ExtractedPdfTableCell, short_finance_snippet


NUMERIC_PAGE_CANDIDATE_COLUMNS_01IF_PATCH3_PATCH2 = [
    "ticker",
    "period",
    "period_type",
    "source_document_type",
    "source_url",
    "final_url",
    "local_path",
    "file_hash",
    "page_number",
    "text_length",
    "normalized_text_length",
    "digit_count",
    "numeric_token_count",
    "numeric_density",
    "money_unit_hits",
    "finance_keyword_hits",
    "negative_keyword_hits",
    "candidate_score",
    "candidate_status",
    "reject_reason",
    "text_preview",
]

NUMERIC_TABLE_CANDIDATE_COLUMNS_01IF_PATCH3_PATCH2 = [
    "ticker",
    "period",
    "period_type",
    "source_document_type",
    "source_url",
    "final_url",
    "local_path",
    "file_hash",
    "page_number",
    "table_index",
    "row_count",
    "col_count",
    "numeric_cell_count",
    "numeric_cell_ratio",
    "finance_anchor_hits",
    "money_unit_hits",
    "table_score",
    "table_status",
    "reject_reason",
    "table_preview",
]

NUMERIC_TABLE_CELL_COLUMNS_01IF_PATCH3_PATCH2 = [
    "ticker",
    "period",
    "period_type",
    "source_document_type",
    "source_url",
    "final_url",
    "local_path",
    "file_hash",
    "page_number",
    "table_index",
    "row_index",
    "col_index",
    "raw_cell",
    "normalized_cell",
    "is_numeric",
    "numeric_value_raw",
    "unit_hint",
    "currency_hint",
]

NUMERIC_TABLE_ROW_COLUMNS_01IF_PATCH3_PATCH2 = [
    "ticker",
    "period",
    "period_type",
    "source_document_type",
    "source_url",
    "final_url",
    "local_path",
    "file_hash",
    "page_number",
    "table_index",
    "row_index",
    "raw_row_text",
    "normalized_row_text",
    "numeric_values_found",
    "finance_anchor_hits",
    "row_status",
    "notes",
]

NUMERIC_TABLE_DUMP_INDEX_COLUMNS_01IF_PATCH3_PATCH2 = [
    "ticker",
    "period",
    "period_type",
    "source_document_type",
    "source_url",
    "final_url",
    "local_path",
    "file_hash",
    "page_number",
    "table_index",
    "row_count",
    "col_count",
    "numeric_cell_count",
    "numeric_cell_ratio",
    "table_status",
    "notes",
]

ANCHOR_FIELD_ALIASES = {
    "total_assets": ["tong cong tai san", "tong tai san", "total assets"],
    "total_liabilities": ["tong cong no phai tra", "tong no phai tra", "no phai tra", "total liabilities"],
    "equity": ["von chu so huu", "shareholders equity", "owners equity", "equity"],
    "cash": ["tien va cac khoan tuong duong tien", "tien va tuong duong tien", "cash and cash equivalents"],
    "inventory": ["hang ton kho", "inventories", "inventory"],
    "revenue": ["doanh thu thuan", "doanh thu ban hang", "net revenue", "revenue"],
    "gross_profit": ["loi nhuan gop", "gross profit"],
    "operating_profit": ["loi nhuan thuan tu hoat dong kinh doanh", "operating profit", "operating income"],
    "net_profit": ["loi nhuan sau thue", "profit after tax", "net profit"],
    "operating_cash_flow": [
        "luu chuyen tien thuan tu hoat dong kinh doanh",
        "net cash flows from operating activities",
        "operating cash flow",
    ],
}

BCTC_DOCUMENT_KEYWORDS = [
    "bctc",
    "bao cao tai chinh",
    "financial statement",
    "financial statements",
    "annual report",
    "consolidated financial statements",
    "separate financial statements",
    "audited financial statements",
    "reviewed financial statements",
    "interim financial statements",
    "hop nhat",
    "cong ty me",
    "kiem toan",
    "soat xet",
]

FINANCE_PAGE_KEYWORDS = [
    "tai san",
    "no phai tra",
    "von chu so huu",
    "doanh thu",
    "loi nhuan",
    "gia von",
    "hang ton kho",
    "luu chuyen tien",
    "total assets",
    "total liabilities",
    "equity",
    "revenue",
    "profit",
    "cash flows",
    "inventory",
]

NEGATIVE_PAGE_KEYWORDS = [
    "cong van",
    "giai trinh",
    "kinh gui",
    "dia chi",
    "dien thoai",
    "email",
    "website",
    "muc luc",
    "contact",
    "address",
    "telephone",
    "signature",
    "shareholder",
    "governance",
    "personnel",
    "esg",
]

MONEY_UNIT_KEYWORDS = [
    "don vi tinh",
    "dong",
    "nghin dong",
    "trieu dong",
    "ty dong",
    "vnd",
    "million vnd",
    "vnd million",
    "thousand vnd",
]

CURRENT_PERIOD_HINTS = [
    "current period",
    "this period",
    "current year",
    "this year",
    "nam nay",
    "quy nay",
    "luy ke",
]


@dataclass(frozen=True)
class NumericTableDumpConfig:
    min_page_numeric_tokens: int = 8
    min_page_score: float = 6.0
    min_table_rows: int = 3
    min_table_cols: int = 2
    min_numeric_cell_count: int = 8
    min_numeric_cell_ratio: float = 0.25
    min_anchor_hits_for_table: int = 2


@dataclass(frozen=True)
class NumericTableDumpFrames:
    page_candidates: pd.DataFrame
    table_candidates: pd.DataFrame
    table_cells: pd.DataFrame
    table_rows: pd.DataFrame
    dump_index: pd.DataFrame
    candidate_rows: pd.DataFrame
    status_rows: pd.DataFrame


def build_numeric_page_candidates(
    *,
    document_row: dict[str, Any] | pd.Series,
    pages: list[ExtractedPdfPage],
    config: NumericTableDumpConfig | None = None,
) -> pd.DataFrame:
    config = config or NumericTableDumpConfig()
    rows = []
    doc_is_financial = is_financial_document_candidate(document_row)
    for page in pages:
        if not getattr(page, "page_number", 0):
            continue
        text = str(getattr(page, "text", "") or "")
        normalized = normalize_text(text)
        numeric_tokens = extract_numeric_tokens(text)
        word_count = max(1, len(normalized.split()))
        unit_hits = _keyword_hits(normalized, MONEY_UNIT_KEYWORDS)
        finance_hits = _keyword_hits(normalized, FINANCE_PAGE_KEYWORDS)
        negative_hits = _keyword_hits(normalized, NEGATIVE_PAGE_KEYWORDS)
        numeric_density = len(numeric_tokens) / word_count
        candidate_score = (
            len(numeric_tokens) * 0.35
            + unit_hits * 2.0
            + finance_hits * 1.25
            + (1.0 if doc_is_financial else 0.0)
            - negative_hits * 1.5
        )
        selected = bool(
            doc_is_financial
            and len(numeric_tokens) >= config.min_page_numeric_tokens
            and candidate_score >= config.min_page_score
            and negative_hits <= max(2, finance_hits + unit_hits)
        )
        rows.append(
            {
                **_document_fields(document_row),
                "page_number": int(page.page_number),
                "text_length": len(text),
                "normalized_text_length": len(normalized),
                "digit_count": sum(1 for char in text if char.isdigit()),
                "numeric_token_count": len(numeric_tokens),
                "numeric_density": round(numeric_density, 4),
                "money_unit_hits": unit_hits,
                "finance_keyword_hits": finance_hits,
                "negative_keyword_hits": negative_hits,
                "candidate_score": round(candidate_score, 4),
                "candidate_status": "SELECTED_NUMERIC_PAGE" if selected else "REJECTED_PAGE",
                "reject_reason": "" if selected else _page_reject_reason(doc_is_financial, len(numeric_tokens), candidate_score, negative_hits),
                "text_preview": short_finance_snippet(text, max_chars=360),
            }
        )
    return pd.DataFrame(rows, columns=NUMERIC_PAGE_CANDIDATE_COLUMNS_01IF_PATCH3_PATCH2)


def selected_numeric_page_numbers(page_candidates: pd.DataFrame) -> set[int]:
    if not isinstance(page_candidates, pd.DataFrame) or page_candidates.empty:
        return set()
    return {
        int(row["page_number"])
        for _, row in page_candidates.iterrows()
        if str(row.get("candidate_status", "")) in {"SELECTED_NUMERIC_PAGE", "SELECTED_BY_TABLE_EVIDENCE"}
    }


def build_numeric_table_candidates(
    *,
    document_row: dict[str, Any] | pd.Series,
    table_cells: list[ExtractedPdfTableCell],
    pages: list[ExtractedPdfPage],
    config: NumericTableDumpConfig | None = None,
) -> pd.DataFrame:
    config = config or NumericTableDumpConfig()
    page_text = {int(page.page_number): str(page.text or "") for page in pages}
    grouped = _group_cells_by_table(table_cells)
    rows = []
    for (page_number, table_index), cells in sorted(grouped.items()):
        row_count = len({cell.row_index for cell in cells})
        col_count = len({cell.col_index for cell in cells})
        texts = [str(cell.cell_text or "") for cell in cells if str(cell.cell_text or "").strip()]
        table_text = " | ".join(texts)
        numeric_cell_count = sum(1 for text in texts if extract_numeric_tokens(text))
        numeric_cell_ratio = numeric_cell_count / len(texts) if texts else 0.0
        finance_anchor_hits = _anchor_hit_count(table_text)
        unit_hits = _keyword_hits(normalize_text(" ".join([table_text, page_text.get(page_number, "")[:1200]])), MONEY_UNIT_KEYWORDS)
        negative_hits = _keyword_hits(normalize_text(table_text), NEGATIVE_PAGE_KEYWORDS)
        table_score = numeric_cell_count + numeric_cell_ratio * 10 + finance_anchor_hits * 3 + unit_hits * 2 - negative_hits * 1.5
        selected = bool(
            row_count >= config.min_table_rows
            and col_count >= config.min_table_cols
            and (
                (numeric_cell_count >= config.min_numeric_cell_count and numeric_cell_ratio >= config.min_numeric_cell_ratio)
                or (finance_anchor_hits >= config.min_anchor_hits_for_table and numeric_cell_count >= 2)
            )
            and "(cid:" not in table_text
        )
        status = "DUMPED_RAW_EVIDENCE"
        if selected and negative_hits and finance_anchor_hits == 0:
            status = "DUMPED_RAW_EVIDENCE_REVIEW"
        if not selected:
            status = "REJECTED_TABLE"
        rows.append(
            {
                **_document_fields(document_row),
                "page_number": page_number,
                "table_index": table_index,
                "row_count": row_count,
                "col_count": col_count,
                "numeric_cell_count": numeric_cell_count,
                "numeric_cell_ratio": round(numeric_cell_ratio, 4),
                "finance_anchor_hits": finance_anchor_hits,
                "money_unit_hits": unit_hits,
                "table_score": round(table_score, 4),
                "table_status": status,
                "reject_reason": "" if selected else _table_reject_reason(row_count, col_count, numeric_cell_count, numeric_cell_ratio, table_text),
                "table_preview": " | ".join(texts[:18])[:500],
            }
        )
    return pd.DataFrame(rows, columns=NUMERIC_TABLE_CANDIDATE_COLUMNS_01IF_PATCH3_PATCH2)


def promote_pages_with_dumped_tables(page_candidates: pd.DataFrame, table_candidates: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(page_candidates, pd.DataFrame) or page_candidates.empty:
        return pd.DataFrame(columns=NUMERIC_PAGE_CANDIDATE_COLUMNS_01IF_PATCH3_PATCH2)
    if not isinstance(table_candidates, pd.DataFrame) or table_candidates.empty:
        return page_candidates
    pages_with_tables = {
        int(row["page_number"])
        for _, row in table_candidates.iterrows()
        if str(row.get("table_status", "")).startswith("DUMPED_RAW_EVIDENCE")
    }
    output = page_candidates.copy()
    mask = output["page_number"].astype(int).isin(pages_with_tables) & output["candidate_status"].eq("REJECTED_PAGE")
    output.loc[mask, "candidate_status"] = "SELECTED_BY_TABLE_EVIDENCE"
    output.loc[mask, "reject_reason"] = ""
    output.loc[mask, "candidate_score"] = output.loc[mask, "candidate_score"].astype(float) + 2.0
    return output[NUMERIC_PAGE_CANDIDATE_COLUMNS_01IF_PATCH3_PATCH2]


def filter_cells_to_dumped_tables(
    table_cells: list[ExtractedPdfTableCell],
    table_candidates: pd.DataFrame,
) -> list[ExtractedPdfTableCell]:
    if not isinstance(table_candidates, pd.DataFrame) or table_candidates.empty:
        return []
    selected = {
        (int(row["page_number"]), int(row["table_index"]))
        for _, row in table_candidates.iterrows()
        if str(row.get("table_status", "")).startswith("DUMPED_RAW_EVIDENCE")
    }
    return [cell for cell in table_cells if (int(cell.page_number), int(cell.table_index)) in selected]


def build_numeric_table_cell_rows(
    *,
    document_row: dict[str, Any] | pd.Series,
    table_cells: list[ExtractedPdfTableCell],
) -> pd.DataFrame:
    rows = []
    for cell in table_cells:
        raw_cell = str(cell.cell_text or "")
        numeric_tokens = extract_numeric_tokens(raw_cell)
        unit_raw, _, currency, unit_status = detect_unit(raw_cell)
        rows.append(
            {
                **_document_fields(document_row),
                "page_number": int(cell.page_number),
                "table_index": int(cell.table_index),
                "row_index": int(cell.row_index),
                "col_index": int(cell.col_index),
                "raw_cell": raw_cell,
                "normalized_cell": normalize_text(raw_cell),
                "is_numeric": bool(numeric_tokens),
                "numeric_value_raw": numeric_tokens[0] if numeric_tokens else "",
                "unit_hint": unit_raw if unit_status == "UNIT_DETECTED" else "",
                "currency_hint": currency if unit_status == "UNIT_DETECTED" else "",
            }
        )
    return pd.DataFrame(rows, columns=NUMERIC_TABLE_CELL_COLUMNS_01IF_PATCH3_PATCH2)


def build_numeric_table_row_dump(
    *,
    document_row: dict[str, Any] | pd.Series,
    table_cells: list[ExtractedPdfTableCell],
) -> pd.DataFrame:
    rows = []
    for (page_number, table_index, row_index), cells in sorted(_group_cells_by_row(table_cells).items()):
        ordered_cells = [str(cell.cell_text or "") for cell in sorted(cells, key=lambda item: item.col_index)]
        raw_row_text = " | ".join(ordered_cells)
        normalized = normalize_text(raw_row_text)
        numeric_values = []
        for cell_text in ordered_cells:
            numeric_values.extend(extract_numeric_tokens(cell_text))
        anchor_hits = _anchor_hit_count(raw_row_text)
        rows.append(
            {
                **_document_fields(document_row),
                "page_number": page_number,
                "table_index": table_index,
                "row_index": row_index,
                "raw_row_text": raw_row_text,
                "normalized_row_text": normalized,
                "numeric_values_found": "|".join(numeric_values),
                "finance_anchor_hits": anchor_hits,
                "row_status": "ANCHOR_FIELD_REVIEW" if anchor_hits else "RAW_EVIDENCE_ONLY",
                "notes": "raw numeric table dump; no inferred finance values",
            }
        )
    return pd.DataFrame(rows, columns=NUMERIC_TABLE_ROW_COLUMNS_01IF_PATCH3_PATCH2)


def build_numeric_table_dump_index(table_candidates: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(table_candidates, pd.DataFrame) or table_candidates.empty:
        return pd.DataFrame(columns=NUMERIC_TABLE_DUMP_INDEX_COLUMNS_01IF_PATCH3_PATCH2)
    selected = table_candidates[table_candidates["table_status"].astype(str).str.startswith("DUMPED_RAW_EVIDENCE")].copy()
    if selected.empty:
        return pd.DataFrame(columns=NUMERIC_TABLE_DUMP_INDEX_COLUMNS_01IF_PATCH3_PATCH2)
    selected["notes"] = "dumped as raw numeric evidence; not a parsed finance field"
    return selected[NUMERIC_TABLE_DUMP_INDEX_COLUMNS_01IF_PATCH3_PATCH2]


def parse_anchor_field_candidates_from_dumped_tables(
    *,
    document_row: dict[str, Any] | pd.Series,
    pages: list[ExtractedPdfPage],
    table_cells: list[ExtractedPdfTableCell],
    table_candidates: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    selected_keys = {
        (int(row["page_number"]), int(row["table_index"]))
        for _, row in table_candidates.iterrows()
        if str(row.get("table_status", "")).startswith("DUMPED_RAW_EVIDENCE")
    } if isinstance(table_candidates, pd.DataFrame) and not table_candidates.empty else set()
    page_text = {int(page.page_number): str(page.text or "") for page in pages}
    table_groups = _group_cells_by_table(table_cells)
    candidate_rows = []
    status_rows = []
    fetch_time = datetime.now(UTC).replace(microsecond=0).isoformat()

    for key, cells in sorted(table_groups.items()):
        if key not in selected_keys:
            continue
        page_number, table_index = key
        headers_by_col = _current_period_headers_by_col(cells)
        table_text = " | ".join(str(cell.cell_text or "") for cell in cells)
        unit_context = " ".join([page_text.get(page_number, "")[:1600], table_text[:1600]])
        unit_raw, multiplier, currency, unit_status = detect_unit(unit_context)
        for row_key, row_cells in sorted(_group_cells_by_row(cells).items()):
            _, _, row_index = row_key
            ordered = sorted(row_cells, key=lambda item: item.col_index)
            row_text = " | ".join(str(cell.cell_text or "") for cell in ordered)
            field_name = detect_anchor_field_name(row_text)
            if not field_name:
                continue
            raw_label = _label_from_cells(ordered)
            numeric_cells = [
                (token, cell.col_index)
                for cell in ordered
                for token in extract_numeric_tokens(str(cell.cell_text or ""))
            ]
            raw_value = ""
            value_vnd: float | str = ""
            parse_status = "USABLE_VALUE_PARSED"
            review_reason = ""
            manual_review = False
            if not raw_label:
                parse_status = "FIELD_LABEL_AMBIGUOUS"
                review_reason = "FIELD_LABEL_NOT_EXPLICIT"
                manual_review = True
            elif not numeric_cells:
                parse_status = "FIELD_VALUE_AMBIGUOUS"
                review_reason = "FIELD_VALUE_NOT_FOUND"
                manual_review = True
            elif unit_status != "UNIT_DETECTED":
                parse_status = "UNIT_AMBIGUOUS_MANUAL_REVIEW"
                review_reason = "MISSING_UNIT_FOR_VALUE_VND"
                raw_value = "|".join(value for value, _ in numeric_cells)
                manual_review = True
            else:
                chosen = _choose_anchor_value(numeric_cells=numeric_cells, current_period_cols=headers_by_col)
                if chosen is None:
                    parse_status = "FIELD_VALUE_AMBIGUOUS"
                    review_reason = "AMBIGUOUS_PERIOD_COLUMNS"
                    raw_value = "|".join(value for value, _ in numeric_cells)
                    manual_review = True
                else:
                    raw_value = chosen
                    parsed = parse_numeric_value(raw_value)
                    if parsed is None:
                        parse_status = "FIELD_VALUE_AMBIGUOUS"
                        review_reason = "NUMERIC_PARSE_FAILED"
                        manual_review = True
                    else:
                        value_vnd = parsed * multiplier
            row = _candidate_row(
                document_row=document_row,
                field_name=field_name,
                value_vnd=value_vnd,
                raw_value=raw_value,
                unit_raw=unit_raw,
                unit_multiplier=multiplier if unit_status == "UNIT_DETECTED" else "",
                currency=currency if unit_status == "UNIT_DETECTED" else "",
                page_number=page_number,
                table_index=table_index,
                row_index=row_index,
                raw_label=raw_label,
                raw_context=row_text[:240],
                parse_status=parse_status,
                confidence_raw="high" if parse_status == "USABLE_VALUE_PARSED" else "low",
                manual_review_required=manual_review,
                review_reason=review_reason,
                fetch_time=fetch_time,
            )
            if parse_status == "USABLE_VALUE_PARSED":
                candidate_rows.append(row)
            else:
                status_rows.append(row)
    return (
        pd.DataFrame(candidate_rows, columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF),
        pd.DataFrame(status_rows, columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF),
    )


def build_numeric_table_dump_frames(
    *,
    document_row: dict[str, Any] | pd.Series,
    pages: list[ExtractedPdfPage],
    table_cells: list[ExtractedPdfTableCell],
    config: NumericTableDumpConfig | None = None,
) -> NumericTableDumpFrames:
    config = config or NumericTableDumpConfig()
    page_candidates = build_numeric_page_candidates(document_row=document_row, pages=pages, config=config)
    table_candidates = build_numeric_table_candidates(document_row=document_row, table_cells=table_cells, pages=pages, config=config)
    page_candidates = promote_pages_with_dumped_tables(page_candidates, table_candidates)
    dumped_cells = filter_cells_to_dumped_tables(table_cells, table_candidates)
    cell_rows = build_numeric_table_cell_rows(document_row=document_row, table_cells=dumped_cells)
    row_dump = build_numeric_table_row_dump(document_row=document_row, table_cells=dumped_cells)
    dump_index = build_numeric_table_dump_index(table_candidates)
    candidates, status_rows = parse_anchor_field_candidates_from_dumped_tables(
        document_row=document_row,
        pages=pages,
        table_cells=dumped_cells,
        table_candidates=table_candidates,
    )
    return NumericTableDumpFrames(
        page_candidates=page_candidates,
        table_candidates=table_candidates,
        table_cells=cell_rows,
        table_rows=row_dump,
        dump_index=dump_index,
        candidate_rows=candidates,
        status_rows=status_rows,
    )


def build_line_fallback_table_cells(
    *,
    pages: list[ExtractedPdfPage],
    selected_page_numbers: set[int],
) -> list[ExtractedPdfTableCell]:
    cells: list[ExtractedPdfTableCell] = []
    for page in pages:
        page_number = int(page.page_number)
        if page_number not in selected_page_numbers:
            continue
        table_index = 9000 + page_number
        row_index = 0
        for line in str(page.text or "").splitlines():
            if len(extract_numeric_tokens(line)) < 2:
                continue
            row_index += 1
            parts = [part.strip() for part in line.replace("\t", " | ").split("|") if part.strip()]
            if len(parts) < 2:
                parts = [part.strip() for part in line.split("  ") if part.strip()]
            if len(parts) < 2:
                parts = [line.strip()]
            for col_index, value in enumerate(parts, start=1):
                cells.append(
                    ExtractedPdfTableCell(
                        page_number=page_number,
                        backend="text_line_numeric_table_dump",
                        table_index=table_index,
                        row_index=row_index,
                        col_index=col_index,
                        cell_text=value,
                        notes="line fallback numeric dump; no OCR",
                    )
                )
    return cells


def write_numeric_audit_files(
    *,
    document_row: dict[str, Any] | pd.Series,
    pages: list[ExtractedPdfPage],
    page_candidates: pd.DataFrame,
    table_candidates: pd.DataFrame,
    table_rows: pd.DataFrame,
    output_dir: str | Path,
) -> int:
    if not isinstance(page_candidates, pd.DataFrame) or page_candidates.empty:
        return 0
    output = Path(output_dir)
    page_dir = output / "numeric_page_audit"
    table_dir = output / "numeric_table_audit"
    page_dir.mkdir(parents=True, exist_ok=True)
    table_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _audit_file_name(document_row)
    page_by_number = {int(page.page_number): page for page in pages}
    selected_pages = page_candidates[
        page_candidates["candidate_status"].astype(str).isin(["SELECTED_NUMERIC_PAGE", "SELECTED_BY_TABLE_EVIDENCE"])
    ]
    page_lines = [
        f"# Numeric page audit {document_row.get('ticker', '')} {document_row.get('period', '')}",
        "",
        f"- source_url: {document_row.get('source_url', '')}",
        f"- final_url: {document_row.get('final_url', '')}",
        f"- local_path: {document_row.get('local_path', '')}",
        f"- file_hash: {document_row.get('file_hash', '')}",
        "",
        f"- selected_numeric_pages: {len(selected_pages)}",
        "",
    ]
    audit_pages = selected_pages if not selected_pages.empty else page_candidates.sort_values("candidate_score", ascending=False).head(8)
    for _, row in audit_pages.iterrows():
        page_number = int(row.get("page_number", 0) or 0)
        page = page_by_number.get(page_number)
        page_lines.extend(
            [
                f"## Page {page_number}",
                "",
                f"- status: {row.get('candidate_status', '')}",
                f"- score: {row.get('candidate_score', '')}",
                f"- numeric_tokens: {row.get('numeric_token_count', '')}",
                f"- reject_reason: {row.get('reject_reason', '')}",
                "",
                short_finance_snippet(page.text if page else row.get("text_preview", ""), max_chars=500),
                "",
            ]
        )
    (page_dir / safe_name).write_text("\n".join(page_lines), encoding="utf-8")

    selected_tables = table_candidates[
        table_candidates["table_status"].astype(str).str.startswith("DUMPED_RAW_EVIDENCE")
    ] if isinstance(table_candidates, pd.DataFrame) and not table_candidates.empty else pd.DataFrame()
    table_lines = [
        f"# Numeric table audit {document_row.get('ticker', '')} {document_row.get('period', '')}",
        "",
        f"- source_url: {document_row.get('source_url', '')}",
        f"- local_path: {document_row.get('local_path', '')}",
        f"- file_hash: {document_row.get('file_hash', '')}",
        "",
        f"- dumped_numeric_tables: {len(selected_tables)}",
        "",
    ]
    if not selected_tables.empty:
        for _, table in selected_tables.head(20).iterrows():
            page_number = int(table.get("page_number", 0) or 0)
            table_index = int(table.get("table_index", 0) or 0)
            table_lines.extend(
                [
                    f"## Page {page_number} Table {table_index}",
                    "",
                    f"- status: {table.get('table_status', '')}",
                    f"- numeric_cell_count: {table.get('numeric_cell_count', '')}",
                    f"- numeric_cell_ratio: {table.get('numeric_cell_ratio', '')}",
                    f"- finance_anchor_hits: {table.get('finance_anchor_hits', '')}",
                    f"- preview: {table.get('table_preview', '')}",
                    "",
                ]
            )
            if isinstance(table_rows, pd.DataFrame) and not table_rows.empty:
                sample = table_rows[
                    (table_rows["page_number"].astype(int) == page_number)
                    & (table_rows["table_index"].astype(int) == table_index)
                ].head(8)
                for _, sample_row in sample.iterrows():
                    table_lines.append(f"- row {sample_row.get('row_index', '')}: {sample_row.get('raw_row_text', '')[:300]}")
                table_lines.append("")
    else:
        table_lines.append("No numeric-heavy tables were dumped.")
    (table_dir / safe_name).write_text("\n".join(table_lines), encoding="utf-8")
    return 2


def detect_anchor_field_name(value: Any) -> str:
    normalized = normalize_text(value)
    matches: list[tuple[int, str]] = []
    for field_name, aliases in ANCHOR_FIELD_ALIASES.items():
        for alias in aliases:
            normalized_alias = normalize_text(alias)
            if normalized_alias and normalized_alias in normalized:
                matches.append((len(normalized_alias), field_name))
    if not matches:
        return ""
    matches.sort(reverse=True)
    longest = matches[0][0]
    longest_fields = {field_name for alias_len, field_name in matches if alias_len == longest}
    if len(longest_fields) == 1:
        return next(iter(longest_fields))
    return ""


def is_financial_document_candidate(document_row: dict[str, Any] | pd.Series) -> bool:
    text = " ".join(
        [
            str(document_row.get("document_type", "")),
            str(document_row.get("source_url", "")),
            str(document_row.get("final_url", "")),
            str(document_row.get("local_path", "")),
            str(document_row.get("title", "")),
        ]
    )
    normalized = normalize_text(text)
    if str(document_row.get("detected_file_type", "")).lower() not in {"pdf", "xlsx", "xls", ""}:
        return False
    return any(normalize_text(keyword) in normalized for keyword in BCTC_DOCUMENT_KEYWORDS)


def coverage_candidate_rows(candidate_rows: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(candidate_rows, pd.DataFrame) or candidate_rows.empty:
        return pd.DataFrame(columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF)
    output = candidate_rows.copy()
    output["parse_status"] = output["parse_status"].replace({"USABLE_VALUE_PARSED": "FIELD_PARSED"})
    return output[OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF]


def _document_fields(document_row: dict[str, Any] | pd.Series) -> dict[str, Any]:
    period = str(document_row.get("period", ""))
    return {
        "ticker": document_row.get("ticker", ""),
        "period": period,
        "period_type": "quarter" if "-Q" in period.upper() else "annual",
        "source_document_type": _source_document_type(document_row),
        "source_url": document_row.get("source_url", ""),
        "final_url": document_row.get("final_url", ""),
        "local_path": document_row.get("local_path", ""),
        "file_hash": document_row.get("file_hash", ""),
    }


def _source_document_type(document_row: dict[str, Any] | pd.Series) -> str:
    value = normalize_text(
        " ".join(
            [
                str(document_row.get("document_type", "")),
                str(document_row.get("source_url", "")),
                str(document_row.get("local_path", "")),
            ]
        )
    )
    if "annual report" in value or "year report" in value or "bao cao thuong nien" in value:
        return "annual_report"
    return "financial_statement"


def _keyword_hits(normalized: str, keywords: list[str]) -> int:
    return sum(1 for keyword in keywords if normalize_text(keyword) in normalized)


def _anchor_hit_count(value: Any) -> int:
    normalized = normalize_text(value)
    fields = set()
    for field_name, aliases in ANCHOR_FIELD_ALIASES.items():
        if any(normalize_text(alias) in normalized for alias in aliases):
            fields.add(field_name)
    return len(fields)


def _page_reject_reason(doc_is_financial: bool, numeric_tokens: int, candidate_score: float, negative_hits: int) -> str:
    if not doc_is_financial:
        return "DOCUMENT_NOT_FINANCIAL_CANDIDATE"
    if negative_hits > 2:
        return "NEGATIVE_PAGE_SIGNALS"
    if numeric_tokens == 0:
        return "TEXT_TOO_SPARSE_FOR_NUMERIC_TABLE_DUMP"
    if numeric_tokens < 8:
        return "LOW_NUMERIC_TOKEN_COUNT"
    if candidate_score < 6:
        return "LOW_NUMERIC_PAGE_SCORE"
    return "REJECTED_PAGE"


def _table_reject_reason(row_count: int, col_count: int, numeric_count: int, numeric_ratio: float, table_text: str) -> str:
    if "(cid:" in table_text:
        return "GARBLED_PDF_TEXT"
    if row_count < 3 or col_count < 2:
        return "NOT_TABLE_LIKE"
    if numeric_count < 8:
        return "LOW_NUMERIC_CELL_COUNT"
    if numeric_ratio < 0.25:
        return "LOW_NUMERIC_CELL_RATIO"
    return "REJECTED_TABLE"


def _group_cells_by_table(table_cells: list[ExtractedPdfTableCell]) -> dict[tuple[int, int], list[ExtractedPdfTableCell]]:
    grouped: dict[tuple[int, int], list[ExtractedPdfTableCell]] = {}
    for cell in table_cells:
        if not str(cell.cell_text or "").strip():
            continue
        grouped.setdefault((int(cell.page_number), int(cell.table_index)), []).append(cell)
    return grouped


def _group_cells_by_row(table_cells: list[ExtractedPdfTableCell]) -> dict[tuple[int, int, int], list[ExtractedPdfTableCell]]:
    grouped: dict[tuple[int, int, int], list[ExtractedPdfTableCell]] = {}
    for cell in table_cells:
        if not str(cell.cell_text or "").strip():
            continue
        grouped.setdefault((int(cell.page_number), int(cell.table_index), int(cell.row_index)), []).append(cell)
    return grouped


def _current_period_headers_by_col(cells: list[ExtractedPdfTableCell]) -> set[int]:
    header_rows = sorted({cell.row_index for cell in cells})[:3]
    current_cols = set()
    for cell in cells:
        if cell.row_index not in header_rows:
            continue
        normalized = normalize_text(cell.cell_text)
        if any(normalize_text(hint) in normalized for hint in CURRENT_PERIOD_HINTS):
            current_cols.add(int(cell.col_index))
    return current_cols


def _label_from_cells(cells: list[ExtractedPdfTableCell]) -> str:
    parts = []
    for cell in sorted(cells, key=lambda item: item.col_index):
        text = str(cell.cell_text or "").strip()
        if extract_numeric_tokens(text):
            break
        if text:
            parts.append(text)
    return " ".join(parts).strip()[:180]


def _choose_anchor_value(numeric_cells: list[tuple[str, int]], current_period_cols: set[int]) -> str | None:
    if len(numeric_cells) == 1:
        return numeric_cells[0][0]
    matching = [value for value, col_index in numeric_cells if col_index in current_period_cols]
    if len(matching) == 1:
        return matching[0]
    return None


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
    parse_status: str,
    confidence_raw: str,
    manual_review_required: bool,
    review_reason: str,
    fetch_time: str,
) -> dict[str, Any]:
    period = str(document_row.get("period", ""))
    return {
        "ticker": document_row.get("ticker", ""),
        "period": period,
        "period_type": "quarter" if "-Q" in period.upper() else "annual",
        "field_name": field_name,
        "value_vnd": value_vnd,
        "raw_value": raw_value,
        "unit_raw": unit_raw,
        "unit_multiplier": unit_multiplier,
        "currency": currency,
        "source_category": "official_company_document",
        "source_name": "official_numeric_table_dump_01if_patch3_patch2",
        "source_url": document_row.get("source_url", ""),
        "final_url": document_row.get("final_url", ""),
        "local_path": document_row.get("local_path", ""),
        "file_hash": document_row.get("file_hash", ""),
        "page_number": page_number,
        "table_index": table_index,
        "row_index": row_index,
        "raw_label": raw_label,
        "raw_context": raw_context,
        "parser_name": "numeric_table_anchor_parser_01if_patch3_patch2",
        "parse_status": parse_status,
        "confidence_raw": confidence_raw,
        "manual_review_required": manual_review_required,
        "review_reason": review_reason,
        "fetch_time": fetch_time,
        "notes": "strict anchor candidate from numeric table dump; no OCR; no inferred or zero-filled values",
    }


def _audit_file_name(document_row: dict[str, Any] | pd.Series) -> str:
    ticker = str(document_row.get("ticker", "")).lower() or "unknown"
    period = str(document_row.get("period", "")).lower().replace("-", "_") or "unknown"
    short_hash = str(document_row.get("file_hash", ""))[:16] or "nohash"
    return f"{ticker}_{period}_{short_hash}.md"
