"""Statement page targeting and table isolation for REAL-DATA-01I-F-PATCH3."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingestion.official_finance_link_extractor import normalize_text
from src.ingestion.official_finance_value_parser import (
    OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF,
    detect_field_name,
    detect_unit,
    extract_numeric_tokens,
    is_usable_candidate_row,
    parse_numeric_value,
)
from src.ingestion.official_pdf_table_normalizer import NormalizedFinanceTableRow
from src.ingestion.official_pdf_text_extractor import ExtractedPdfPage, ExtractedPdfTableCell, short_finance_snippet


STATEMENT_PAGE_CANDIDATE_COLUMNS_01IF_PATCH3 = [
    "ticker",
    "document_id",
    "source_url",
    "local_path",
    "file_hash",
    "page_number",
    "statement_type",
    "statement_title_detected",
    "positive_score",
    "negative_score",
    "numeric_density",
    "table_like_score",
    "unit_detected",
    "selected_for_table_extraction",
    "rejection_reason",
]

STATEMENT_TABLE_CANDIDATE_COLUMNS_01IF_PATCH3 = [
    "ticker",
    "document_id",
    "source_url",
    "local_path",
    "file_hash",
    "page_number",
    "statement_type",
    "table_index",
    "rows_count",
    "cols_count",
    "header_guess",
    "unit_detected",
    "numeric_cell_count",
    "numeric_density",
    "selected_for_value_parse",
    "rejection_reason",
]

PATCH3_EXTRA_CANDIDATE_COLUMNS = ["statement_type", "period_label", "parser_backend"]
PATCH3_CANDIDATE_COLUMNS = [*OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF, *PATCH3_EXTRA_CANDIDATE_COLUMNS]

STATEMENT_TITLES = {
    "balance_sheet": [
        "bang can doi ke toan",
        "balance sheet",
        "statement of financial position",
    ],
    "income_statement": [
        "bao cao ket qua hoat dong kinh doanh",
        "income statement",
        "statement of profit or loss",
    ],
    "cash_flow_statement": [
        "bao cao luu chuyen tien te",
        "cash flow statement",
        "statement of cash flows",
    ],
}

STATEMENT_LINE_ITEMS = [
    "tai san",
    "no phai tra",
    "von chu so huu",
    "doanh thu",
    "loi nhuan",
    "gia von",
    "chi phi ban hang",
    "chi phi quan ly doanh nghiep",
    "luu chuyen tien",
    "tien va tuong duong tien",
    "total assets",
    "total liabilities",
    "equity",
    "revenue",
    "profit",
    "cost of sales",
    "cash flows",
]

TABLE_HEADER_HINTS = [
    "ma so",
    "thuyet minh",
    "nam nay",
    "nam truoc",
    "quy nay",
    "luy ke",
    "current period",
    "previous period",
    "current year",
    "previous year",
]

NEGATIVE_HINTS = [
    "cong van",
    "giai trinh",
    "thong bao",
    "kinh gui",
    "uy ban chung khoan",
    "so giao dich chung khoan",
    "nguoi cong bo thong tin",
    "dia chi",
    "dien thoai",
    "email",
    "website",
    "muc luc",
    "thuyet minh bao cao tai chinh",
    "contact",
    "address",
    "telephone",
    "signature",
]

PATCH3_FIELD_ALIASES = {
    "total_assets": ["tong cong tai san", "tong tai san", "total assets"],
    "current_assets": ["tai san ngan han", "current assets"],
    "cash_and_cash_equivalents": ["tien va cac khoan tuong duong tien", "tien va tuong duong tien", "cash and cash equivalents"],
    "inventory": ["hang ton kho", "inventories", "inventory"],
    "total_liabilities": ["tong cong no phai tra", "tong no phai tra", "no phai tra", "total liabilities"],
    "current_liabilities": ["no ngan han", "current liabilities"],
    "equity": ["von chu so huu", "owner s equity", "owners equity", "shareholders equity", "equity"],
    "retained_earnings": ["loi nhuan sau thue chua phan phoi", "retained earnings"],
    "revenue": ["doanh thu ban hang va cung cap dich vu", "revenue"],
    "net_revenue": ["doanh thu thuan ve ban hang va cung cap dich vu", "doanh thu thuan", "net revenue"],
    "cost_of_goods_sold": ["gia von hang ban", "cost of goods sold", "cost of sales"],
    "gross_profit": ["loi nhuan gop", "gross profit"],
    "selling_expenses": ["chi phi ban hang", "selling expenses"],
    "general_admin_expenses": ["chi phi quan ly doanh nghiep", "general and administrative expenses", "administrative expenses"],
    "operating_profit": ["loi nhuan thuan tu hoat dong kinh doanh", "operating profit", "operating income"],
    "profit_before_tax": ["tong loi nhuan ke toan truoc thue", "loi nhuan truoc thue", "profit before tax"],
    "net_profit": ["loi nhuan sau thue", "net profit after tax", "profit after tax"],
    "parent_company_net_profit": [
        "loi nhuan sau thue cua cong ty me",
        "profit after tax attributable to owners of the parent",
        "profit attributable to owners of the parent",
    ],
    "operating_cash_flow": [
        "luu chuyen tien thuan tu hoat dong kinh doanh",
        "net cash flows from operating activities",
        "cash flows from operating activities",
    ],
    "investing_cash_flow": [
        "luu chuyen tien thuan tu hoat dong dau tu",
        "net cash flows from investing activities",
        "cash flows from investing activities",
    ],
    "financing_cash_flow": [
        "luu chuyen tien thuan tu hoat dong tai chinh",
        "net cash flows from financing activities",
        "cash flows from financing activities",
    ],
    "net_cash_flow": [
        "luu chuyen tien thuan trong ky",
        "luu chuyen tien thuan trong nam",
        "net increase in cash",
        "net cash flow",
    ],
}

STATEMENT_TYPE_FIELD_GROUPS = {
    "balance_sheet": [
        "total_assets",
        "current_assets",
        "cash_and_cash_equivalents",
        "inventory",
        "total_liabilities",
        "current_liabilities",
        "equity",
        "retained_earnings",
    ],
    "income_statement": [
        "revenue",
        "net_revenue",
        "cost_of_goods_sold",
        "gross_profit",
        "selling_expenses",
        "general_admin_expenses",
        "operating_profit",
        "profit_before_tax",
        "net_profit",
        "parent_company_net_profit",
    ],
    "cash_flow_statement": [
        "operating_cash_flow",
        "investing_cash_flow",
        "financing_cash_flow",
        "net_cash_flow",
    ],
}


@dataclass(frozen=True)
class StatementPageCandidate:
    ticker: str
    document_id: str
    source_url: str
    local_path: str
    file_hash: str
    page_number: int
    statement_type: str
    statement_title_detected: str
    positive_score: float
    negative_score: float
    numeric_density: float
    table_like_score: float
    unit_detected: str
    selected_for_table_extraction: bool
    rejection_reason: str


def build_statement_page_candidates(
    *,
    document_row: dict[str, Any] | pd.Series,
    pages: list[ExtractedPdfPage],
) -> pd.DataFrame:
    rows = [_classify_page(document_row=document_row, page=page) for page in pages if page.page_number]
    return pd.DataFrame([row.__dict__ for row in rows], columns=STATEMENT_PAGE_CANDIDATE_COLUMNS_01IF_PATCH3)


def selected_statement_page_numbers(page_candidates: pd.DataFrame) -> set[int]:
    if not isinstance(page_candidates, pd.DataFrame) or page_candidates.empty:
        return set()
    return {
        int(row["page_number"])
        for _, row in page_candidates.iterrows()
        if str(row.get("selected_for_table_extraction", "")).lower() in {"true", "1", "yes"}
    }


def build_statement_table_candidates(
    *,
    document_row: dict[str, Any] | pd.Series,
    table_cells: list[ExtractedPdfTableCell],
    page_candidates: pd.DataFrame,
) -> pd.DataFrame:
    selected_pages = selected_statement_page_numbers(page_candidates)
    page_type = {
        int(row["page_number"]): str(row.get("statement_type", ""))
        for _, row in page_candidates.iterrows()
        if int(row.get("page_number", 0) or 0) in selected_pages
    }
    grouped: dict[tuple[int, int], list[ExtractedPdfTableCell]] = {}
    for cell in table_cells:
        if cell.page_number in selected_pages:
            grouped.setdefault((cell.page_number, cell.table_index), []).append(cell)
    rows = []
    for (page_number, table_index), cells in sorted(grouped.items()):
        row_numbers = {cell.row_index for cell in cells}
        col_numbers = {cell.col_index for cell in cells}
        texts = [str(cell.cell_text or "") for cell in cells]
        numeric_count = sum(1 for text in texts if extract_numeric_tokens(text))
        cell_count = len([text for text in texts if text.strip()])
        numeric_density = numeric_count / cell_count if cell_count else 0.0
        header_guess = _header_guess(cells)
        unit_raw, _, _, unit_status = detect_unit(" ".join([header_guess, " ".join(texts[:20])]))
        selected = len(row_numbers) >= 2 and len(col_numbers) >= 2 and numeric_count >= 1 and not _looks_garbled(" ".join(texts))
        rejection_reason = "" if selected else _table_rejection_reason(row_numbers, col_numbers, numeric_count, " ".join(texts))
        rows.append(
            {
                "ticker": document_row.get("ticker", ""),
                "document_id": _document_id(document_row),
                "source_url": document_row.get("source_url", ""),
                "local_path": document_row.get("local_path", ""),
                "file_hash": document_row.get("file_hash", ""),
                "page_number": page_number,
                "statement_type": page_type.get(page_number, ""),
                "table_index": table_index,
                "rows_count": len(row_numbers),
                "cols_count": len(col_numbers),
                "header_guess": header_guess[:240],
                "unit_detected": unit_raw if unit_status == "UNIT_DETECTED" else "",
                "numeric_cell_count": numeric_count,
                "numeric_density": round(numeric_density, 4),
                "selected_for_value_parse": selected,
                "rejection_reason": rejection_reason,
            }
        )
    return pd.DataFrame(rows, columns=STATEMENT_TABLE_CANDIDATE_COLUMNS_01IF_PATCH3)


def filter_cells_to_selected_statement_tables(
    table_cells: list[ExtractedPdfTableCell],
    table_candidates: pd.DataFrame,
) -> list[ExtractedPdfTableCell]:
    if not isinstance(table_candidates, pd.DataFrame) or table_candidates.empty:
        return []
    selected = {
        (int(row["page_number"]), int(row["table_index"]))
        for _, row in table_candidates.iterrows()
        if str(row.get("selected_for_value_parse", "")).lower() in {"true", "1", "yes"}
    }
    return [cell for cell in table_cells if (cell.page_number, cell.table_index) in selected]


def parse_patch3_statement_rows(
    *,
    document_row: dict[str, Any] | pd.Series,
    normalized_rows: list[NormalizedFinanceTableRow],
    table_candidates: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    table_meta = {
        (int(row["page_number"]), int(row["table_index"])): {
            "statement_type": str(row.get("statement_type", "")),
            "unit_detected": str(row.get("unit_detected", "")),
        }
        for _, row in table_candidates.iterrows()
        if str(row.get("selected_for_value_parse", "")).lower() in {"true", "1", "yes"}
    } if isinstance(table_candidates, pd.DataFrame) and not table_candidates.empty else {}
    rows = []
    fetch_time = datetime.now(UTC).replace(microsecond=0).isoformat()
    for row in normalized_rows:
        key = (int(row.page_number), int(row.table_index))
        if key not in table_meta:
            continue
        meta = table_meta[key]
        field_name = _detect_patch3_field_name(row.label_guess or row.row_text)
        unit_raw, unit_multiplier, currency, unit_status = detect_unit(" ".join([row.unit_context, meta.get("unit_detected", "")]))
        raw_label = row.label_guess
        raw_value = ""
        value_vnd: float | str = ""
        parse_status = "FIELD_PARSED"
        review_reason = ""
        manual_review = False
        period_label = _period_label(row.column_contexts)
        if not field_name:
            parse_status = "FIELD_LABEL_AMBIGUOUS"
            review_reason = "FIELD_LABEL_NOT_EXPLICIT"
            manual_review = True
        elif not raw_label:
            parse_status = "FIELD_LABEL_AMBIGUOUS"
            review_reason = "FIELD_LABEL_NOT_EXPLICIT"
            manual_review = True
        elif not row.numeric_values:
            parse_status = "LABEL_ONLY_NO_VALUE"
            review_reason = "FIELD_VALUE_NOT_FOUND"
            manual_review = True
        elif unit_status != "UNIT_DETECTED":
            parse_status = "UNIT_AMBIGUOUS_MANUAL_REVIEW"
            review_reason = unit_status
            raw_value = "|".join(row.numeric_values)
            manual_review = True
        elif not period_label:
            parse_status = "FIELD_VALUE_AMBIGUOUS"
            review_reason = "PERIOD_LABEL_UNCLEAR"
            raw_value = "|".join(row.numeric_values)
            manual_review = True
        else:
            raw_value = _choose_value(row.numeric_values, row.column_contexts)
            parsed = parse_numeric_value(raw_value)
            if parsed is None:
                parse_status = "FIELD_VALUE_AMBIGUOUS"
                review_reason = "NUMERIC_PARSE_FAILED"
                manual_review = True
            else:
                value_vnd = parsed * unit_multiplier
        rows.append(
            {
                "ticker": document_row.get("ticker", ""),
                "period": document_row.get("period", ""),
                "period_type": "quarter" if "-Q" in str(document_row.get("period", "")).upper() else "annual",
                "field_name": field_name,
                "value_vnd": value_vnd,
                "raw_value": raw_value,
                "unit_raw": unit_raw,
                "unit_multiplier": unit_multiplier if unit_status == "UNIT_DETECTED" else "",
                "currency": currency if unit_status == "UNIT_DETECTED" else "",
                "source_category": "official_company_document",
                "source_name": "official_statement_page_parser_01if_patch3",
                "source_url": document_row.get("source_url", ""),
                "final_url": document_row.get("final_url", ""),
                "local_path": document_row.get("local_path", ""),
                "file_hash": document_row.get("file_hash", ""),
                "page_number": row.page_number,
                "table_index": row.table_index,
                "row_index": row.row_index,
                "raw_label": raw_label,
                "raw_context": row.row_text[:240],
                "parser_name": "statement_table_row_parser_01if_patch3",
                "parse_status": parse_status,
                "confidence_raw": "high" if parse_status == "FIELD_PARSED" else "low",
                "manual_review_required": manual_review,
                "review_reason": review_reason,
                "fetch_time": fetch_time,
                "notes": "statement-page targeted parser; no OCR; no inferred or zero-filled values",
                "statement_type": meta.get("statement_type", ""),
                "period_label": period_label,
                "parser_backend": row.backend,
            }
        )
    frame = pd.DataFrame(rows, columns=PATCH3_CANDIDATE_COLUMNS)
    if frame.empty:
        empty = pd.DataFrame(columns=PATCH3_CANDIDATE_COLUMNS)
        return empty.copy(), empty.copy()
    usable_mask = frame.apply(is_usable_candidate_row, axis=1)
    return frame[usable_mask].copy(), frame[~usable_mask].copy()


def write_statement_audit_files(
    *,
    document_row: dict[str, Any] | pd.Series,
    pages: list[ExtractedPdfPage],
    page_candidates: pd.DataFrame,
    table_candidates: pd.DataFrame,
    normalized_rows: list[NormalizedFinanceTableRow] | None = None,
    output_dir: str | Path,
) -> int:
    selected = page_candidates[page_candidates["selected_for_table_extraction"].astype(bool)] if not page_candidates.empty else pd.DataFrame()
    if page_candidates.empty:
        return 0
    audit_dir = Path(output_dir) / "statement_page_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    page_by_number = {page.page_number: page for page in pages}
    path = audit_dir / f"{str(document_row.get('ticker', '')).lower()}_{str(document_row.get('period', '')).lower().replace('-', '_')}_{_document_id(document_row)}.md"
    lines = [
        f"# Statement page audit {document_row.get('ticker', '')} {document_row.get('period', '')}",
        "",
        f"- document_id: {_document_id(document_row)}",
        f"- source_url: {document_row.get('source_url', '')}",
        f"- local_path: {document_row.get('local_path', '')}",
        f"- file_hash: {document_row.get('file_hash', '')}",
        "",
    ]
    if selected.empty:
        lines.extend(
            [
                "No pages were selected for table extraction.",
                "",
                "## Highest Scoring Rejected Pages",
                "",
            ]
        )
        audit_candidates = page_candidates.sort_values("positive_score", ascending=False).head(8)
    else:
        audit_candidates = selected
    for _, candidate in audit_candidates.iterrows():
        page_number = int(candidate["page_number"])
        page = page_by_number.get(page_number)
        lines.extend(
            [
                f"## Page {page_number}: {candidate.get('statement_type', '')}",
                "",
                f"- title: {candidate.get('statement_title_detected', '')}",
                f"- selected: {candidate.get('selected_for_table_extraction', '')}",
                f"- rejection_reason: {candidate.get('rejection_reason', '')}",
                "",
                short_finance_snippet(page.text if page else "", max_chars=500),
                "",
            ]
        )
    if isinstance(table_candidates, pd.DataFrame) and not table_candidates.empty:
        lines.extend(["## Table Candidates", ""])
        for _, row in table_candidates.head(40).iterrows():
            lines.append(
                f"- p{row.get('page_number', '')} t{row.get('table_index', '')}: "
                f"selected={row.get('selected_for_value_parse', '')}; "
                f"rows={row.get('rows_count', '')}; cols={row.get('cols_count', '')}; "
                f"reason={row.get('rejection_reason', '')}"
            )
    path.write_text("\n".join(lines), encoding="utf-8")
    files_written = 1

    table_audit_dir = Path(output_dir) / "statement_table_audit"
    table_audit_dir.mkdir(parents=True, exist_ok=True)
    table_path = table_audit_dir / path.name
    rows_by_table: dict[tuple[int, int], list[NormalizedFinanceTableRow]] = {}
    for normalized_row in normalized_rows or []:
        rows_by_table.setdefault((normalized_row.page_number, normalized_row.table_index), []).append(normalized_row)
    table_lines = [
        f"# Statement table audit {document_row.get('ticker', '')} {document_row.get('period', '')}",
        "",
        f"- document_id: {_document_id(document_row)}",
        f"- source_url: {document_row.get('source_url', '')}",
        f"- local_path: {document_row.get('local_path', '')}",
        f"- file_hash: {document_row.get('file_hash', '')}",
        "",
    ]
    if isinstance(table_candidates, pd.DataFrame) and not table_candidates.empty:
        for _, candidate in table_candidates.iterrows():
            page_number = int(candidate.get("page_number", 0) or 0)
            table_index = int(candidate.get("table_index", 0) or 0)
            table_lines.extend(
                [
                    f"## Page {page_number} Table {table_index}",
                    "",
                    f"- statement_type: {candidate.get('statement_type', '')}",
                    f"- selected: {candidate.get('selected_for_value_parse', '')}",
                    f"- rows: {candidate.get('rows_count', '')}",
                    f"- cols: {candidate.get('cols_count', '')}",
                    f"- unit: {candidate.get('unit_detected', '')}",
                    f"- rejection_reason: {candidate.get('rejection_reason', '')}",
                    f"- header_guess: {candidate.get('header_guess', '')}",
                    "",
                ]
            )
            for normalized_row in rows_by_table.get((page_number, table_index), [])[:12]:
                table_lines.append(f"- row {normalized_row.row_index}: {normalized_row.row_text[:300]}")
            table_lines.append("")
    else:
        table_lines.extend(["No statement table candidates were isolated.", ""])
    table_path.write_text("\n".join(table_lines), encoding="utf-8")
    files_written += 1
    return files_written


def _classify_page(*, document_row: dict[str, Any] | pd.Series, page: ExtractedPdfPage) -> StatementPageCandidate:
    text = str(page.text or "")
    normalized = normalize_text(text)
    statement_type, title = _statement_type_and_title(normalized)
    explicit_title = bool(title)
    cluster_statement_type, cluster_hits = _infer_statement_type_from_line_items(normalized)
    if not statement_type and cluster_statement_type:
        statement_type = cluster_statement_type
        title = f"line_item_cluster:{cluster_statement_type}"
    line_item_hits = sum(1 for item in STATEMENT_LINE_ITEMS if normalize_text(item) in normalized)
    header_hits = sum(1 for item in TABLE_HEADER_HINTS if normalize_text(item) in normalized)
    negative_hits = sum(1 for item in NEGATIVE_HINTS if normalize_text(item) in normalized)
    numeric_density = _numeric_density(text)
    table_like_score = min(5.0, header_hits + numeric_density * 10)
    unit_raw, _, _, unit_status = detect_unit(text)
    title_score = 8 if explicit_title else 5 if cluster_statement_type else 0
    positive_score = title_score + (line_item_hits + cluster_hits) * 1.5 + table_like_score + (2 if unit_status == "UNIT_DETECTED" else 0)
    negative_score = negative_hits * 3 + (3 if _prose_heavy(text, numeric_density) else 0)
    explicit_selected = bool(explicit_title and statement_type and positive_score >= 8)
    cluster_selected = bool(
        cluster_statement_type
        and positive_score >= 11
        and numeric_density >= 0.08
        and table_like_score >= 2
        and unit_status == "UNIT_DETECTED"
    )
    selected = bool(statement_type and (explicit_selected or cluster_selected) and positive_score > negative_score + 2)
    return StatementPageCandidate(
        ticker=str(document_row.get("ticker", "")),
        document_id=_document_id(document_row),
        source_url=str(document_row.get("source_url", "")),
        local_path=str(document_row.get("local_path", "")),
        file_hash=str(document_row.get("file_hash", "")),
        page_number=int(page.page_number),
        statement_type=statement_type,
        statement_title_detected=title,
        positive_score=round(positive_score, 4),
        negative_score=round(negative_score, 4),
        numeric_density=round(numeric_density, 4),
        table_like_score=round(table_like_score, 4),
        unit_detected=unit_raw if unit_status == "UNIT_DETECTED" else "",
        selected_for_table_extraction=selected,
        rejection_reason="" if selected else _page_rejection_reason(statement_type, positive_score, negative_score, numeric_density),
    )


def _statement_type_and_title(normalized: str) -> tuple[str, str]:
    for statement_type, titles in STATEMENT_TITLES.items():
        for title in titles:
            normalized_title = normalize_text(title)
            if normalized_title and normalized_title in normalized:
                return statement_type, title
    return "", ""


def _infer_statement_type_from_line_items(normalized: str) -> tuple[str, int]:
    hits_by_type: dict[str, int] = {}
    for statement_type, field_names in STATEMENT_TYPE_FIELD_GROUPS.items():
        hits = 0
        for field_name in field_names:
            aliases = PATCH3_FIELD_ALIASES.get(field_name, [])
            if any(normalize_text(alias) in normalized for alias in aliases):
                hits += 1
        minimum_hits = 2 if statement_type == "cash_flow_statement" else 3
        if hits >= minimum_hits:
            hits_by_type[statement_type] = hits
    if not hits_by_type:
        return "", 0
    ordered = sorted(hits_by_type.items(), key=lambda item: item[1], reverse=True)
    if len(ordered) > 1 and ordered[0][1] == ordered[1][1]:
        return "", 0
    return ordered[0]


def _numeric_density(text: str) -> float:
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return 0.0
    numeric_lines = sum(1 for line in lines if extract_numeric_tokens(line))
    return numeric_lines / len(lines)


def _prose_heavy(text: str, numeric_density: float) -> bool:
    words = normalize_text(text).split()
    return len(words) > 180 and numeric_density < 0.08


def _page_rejection_reason(statement_type: str, positive_score: float, negative_score: float, numeric_density: float) -> str:
    if not statement_type:
        return "NO_FORMAL_STATEMENT_TITLE"
    if negative_score >= positive_score:
        return "NEGATIVE_PAGE_SIGNALS_DOMINATE"
    if numeric_density < 0.02:
        return "LOW_NUMERIC_DENSITY"
    return "BELOW_STATEMENT_SELECTION_THRESHOLD"


def _header_guess(cells: list[ExtractedPdfTableCell]) -> str:
    first_rows = sorted({cell.row_index for cell in cells})[:3]
    return " | ".join(cell.cell_text for cell in sorted(cells, key=lambda item: (item.row_index, item.col_index)) if cell.row_index in first_rows)


def _table_rejection_reason(row_numbers: set[int], col_numbers: set[int], numeric_count: int, text: str) -> str:
    if _looks_garbled(text):
        return "GARBLED_PDF_TEXT"
    if len(row_numbers) < 2 or len(col_numbers) < 2:
        return "NOT_TABLE_LIKE"
    if numeric_count < 1:
        return "NO_NUMERIC_CELLS"
    return "TABLE_NOT_SELECTED"


def _looks_garbled(text: str) -> bool:
    return "(cid:" in text


def _period_label(column_contexts: list[str]) -> str:
    if not column_contexts:
        return ""
    for context in column_contexts:
        normalized = normalize_text(context)
        if any(token in normalized for token in ["current", "this period", "this quarter", "nam nay", "quy nay", "luy ke"]):
            return context
    return column_contexts[1] if len(column_contexts) > 1 else ""


def _choose_value(numeric_values: list[str], column_contexts: list[str]) -> str:
    if len(numeric_values) == 1:
        return numeric_values[0]
    if column_contexts:
        return numeric_values[0]
    return ""


def _detect_patch3_field_name(value: Any) -> str:
    normalized = normalize_text(value)
    matches: list[tuple[int, str]] = []
    for field_name, aliases in PATCH3_FIELD_ALIASES.items():
        for alias in aliases:
            normalized_alias = normalize_text(alias)
            if normalized_alias and normalized_alias in normalized:
                matches.append((len(normalized_alias), field_name))
    if not matches:
        return detect_field_name(value)
    matches.sort(reverse=True)
    longest = matches[0][0]
    longest_fields = {field_name for alias_len, field_name in matches if alias_len == longest}
    if len(longest_fields) == 1:
        return next(iter(longest_fields))
    matched_fields = [field_name for _, field_name in matches]
    fallback = detect_field_name(value)
    if fallback and fallback in matched_fields:
        return fallback
    return ""


def _document_id(document_row: dict[str, Any] | pd.Series) -> str:
    return str(document_row.get("file_hash", ""))[:16] or str(document_row.get("local_path", ""))
