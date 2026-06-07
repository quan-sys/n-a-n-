"""Finance-specific numeric page/table scoring for 01IF PATCH3-PATCH3."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.ingestion.official_finance_link_extractor import normalize_text


FINANCE_NUMERIC_PAGE_COLUMNS_01IF_PATCH3_PATCH3 = [
    "ticker",
    "period",
    "period_type",
    "source_document_type",
    "source_url",
    "final_url",
    "local_path",
    "file_hash",
    "page_number",
    "numeric_density",
    "numeric_token_count",
    "finance_anchor_hits",
    "negative_keyword_hits",
    "prose_ratio",
    "finance_page_score",
    "page_status",
    "reject_reason",
    "text_preview",
]

FINANCE_NUMERIC_TABLE_COLUMNS_01IF_PATCH3_PATCH3 = [
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
    "negative_keyword_hits",
    "finance_table_score",
    "table_status",
    "reject_reason",
    "table_preview",
]

FINANCE_ANCHORS = [
    "tong tai san",
    "total assets",
    "no phai tra",
    "liabilities",
    "total liabilities",
    "von chu so huu",
    "equity",
    "owners equity",
    "shareholders equity",
    "doanh thu thuan",
    "doanh thu",
    "net revenue",
    "revenue",
    "loi nhuan gop",
    "gross profit",
    "loi nhuan sau thue",
    "profit after tax",
    "net profit",
    "tien va tuong duong tien",
    "cash and cash equivalents",
    "hang ton kho",
    "inventory",
    "luu chuyen tien thuan tu hoat dong kinh doanh",
    "net cash flows from operating activities",
    "operating cash flow",
]

NEGATIVE_NUMERIC_TABLE_SIGNALS = [
    "supply",
    "absorption",
    "absorption rate",
    "market",
    "market overview",
    "hanoi",
    "hcmc",
    "ho chi minh",
    "new launch",
    "real estate market",
    "employee",
    "headcount",
    "shareholder structure",
    "agenda",
    "dividend plan",
    "esg",
    "environment",
    "carbon",
    "training",
    "salary",
    "board remuneration",
]

MIN_FINANCE_PAGE_NUMERIC_DENSITY = 0.05
MAX_FINANCE_PAGE_PROSE_RATIO = 0.85


def build_finance_numeric_page_candidates(page_candidates: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(page_candidates, pd.DataFrame) or page_candidates.empty:
        return pd.DataFrame(columns=FINANCE_NUMERIC_PAGE_COLUMNS_01IF_PATCH3_PATCH3)
    rows = []
    for _, row in page_candidates.iterrows():
        text = " ".join([str(row.get("text_preview", "")), str(row.get("source_url", "")), str(row.get("local_path", ""))])
        normalized = normalize_text(text)
        anchor_hits = _keyword_hits(normalized, FINANCE_ANCHORS)
        negative_hits = int(row.get("negative_keyword_hits", 0) or 0) + _keyword_hits(normalized, NEGATIVE_NUMERIC_TABLE_SIGNALS)
        numeric_density = _to_float(row.get("numeric_density", 0))
        numeric_tokens = _to_int(row.get("numeric_token_count", 0))
        prose_ratio = _prose_ratio(normalized, numeric_tokens)
        score = numeric_tokens * 0.25 + numeric_density * 8 + anchor_hits * 4 - negative_hits * 3 - prose_ratio * 2
        selected = bool(
            anchor_hits >= 2
            and numeric_tokens >= 3
            and numeric_density >= MIN_FINANCE_PAGE_NUMERIC_DENSITY
            and prose_ratio <= MAX_FINANCE_PAGE_PROSE_RATIO
            and score >= 6
            and negative_hits == 0
        )
        rows.append(
            {
                "ticker": row.get("ticker", ""),
                "period": row.get("period", ""),
                "period_type": row.get("period_type", ""),
                "source_document_type": row.get("source_document_type", ""),
                "source_url": row.get("source_url", ""),
                "final_url": row.get("final_url", ""),
                "local_path": row.get("local_path", ""),
                "file_hash": row.get("file_hash", ""),
                "page_number": row.get("page_number", ""),
                "numeric_density": numeric_density,
                "numeric_token_count": numeric_tokens,
                "finance_anchor_hits": anchor_hits,
                "negative_keyword_hits": negative_hits,
                "prose_ratio": round(prose_ratio, 4),
                "finance_page_score": round(score, 4),
                "page_status": "FINANCE_NUMERIC_PAGE_CANDIDATE" if selected else "NON_FINANCE_NUMERIC_PAGE",
                "reject_reason": "" if selected else _page_reject_reason(anchor_hits, numeric_tokens, negative_hits, numeric_density, prose_ratio),
                "text_preview": row.get("text_preview", ""),
            }
        )
    return pd.DataFrame(rows, columns=FINANCE_NUMERIC_PAGE_COLUMNS_01IF_PATCH3_PATCH3)


def build_finance_numeric_table_candidates(table_candidates: pd.DataFrame, finance_pages: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(table_candidates, pd.DataFrame) or table_candidates.empty:
        return pd.DataFrame(columns=FINANCE_NUMERIC_TABLE_COLUMNS_01IF_PATCH3_PATCH3)
    page_keys = {
        (str(row.get("file_hash", "")), int(row.get("page_number", 0) or 0))
        for _, row in finance_pages.iterrows()
        if str(row.get("page_status", "")) == "FINANCE_NUMERIC_PAGE_CANDIDATE"
    } if isinstance(finance_pages, pd.DataFrame) and not finance_pages.empty else set()
    rows = []
    for _, row in table_candidates.iterrows():
        preview = str(row.get("table_preview", ""))
        normalized = normalize_text(preview)
        anchor_hits = max(_to_int(row.get("finance_anchor_hits", 0)), _keyword_hits(normalized, FINANCE_ANCHORS))
        negative_hits = _keyword_hits(normalized, NEGATIVE_NUMERIC_TABLE_SIGNALS)
        numeric_count = _to_int(row.get("numeric_cell_count", 0))
        numeric_ratio = _to_float(row.get("numeric_cell_ratio", 0))
        page_key = (str(row.get("file_hash", "")), int(row.get("page_number", 0) or 0))
        score = numeric_count * 0.5 + numeric_ratio * 12 + anchor_hits * 5 - negative_hits * 6
        selected = bool(
            page_key in page_keys
            and anchor_hits >= 2
            and numeric_count >= 2
            and negative_hits == 0
            and str(row.get("table_status", "")).startswith("DUMPED_RAW_EVIDENCE")
        )
        rows.append(
            {
                "ticker": row.get("ticker", ""),
                "period": row.get("period", ""),
                "period_type": row.get("period_type", ""),
                "source_document_type": row.get("source_document_type", ""),
                "source_url": row.get("source_url", ""),
                "final_url": row.get("final_url", ""),
                "local_path": row.get("local_path", ""),
                "file_hash": row.get("file_hash", ""),
                "page_number": row.get("page_number", ""),
                "table_index": row.get("table_index", ""),
                "row_count": row.get("row_count", ""),
                "col_count": row.get("col_count", ""),
                "numeric_cell_count": numeric_count,
                "numeric_cell_ratio": numeric_ratio,
                "finance_anchor_hits": anchor_hits,
                "negative_keyword_hits": negative_hits,
                "finance_table_score": round(score, 4),
                "table_status": "FINANCE_NUMERIC_TABLE_CANDIDATE" if selected else "NON_FINANCIAL_NUMERIC_TABLE",
                "reject_reason": "" if selected else _table_reject_reason(anchor_hits, negative_hits, page_key in page_keys),
                "table_preview": preview,
            }
        )
    return pd.DataFrame(rows, columns=FINANCE_NUMERIC_TABLE_COLUMNS_01IF_PATCH3_PATCH3)


def split_numeric_table_layers(
    *,
    finance_table_candidates: pd.DataFrame,
    raw_cells: pd.DataFrame,
    raw_rows: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    finance_keys = _table_keys(finance_table_candidates, status="FINANCE_NUMERIC_TABLE_CANDIDATE")
    raw_cells_out = raw_cells.copy() if isinstance(raw_cells, pd.DataFrame) else pd.DataFrame()
    raw_rows_out = raw_rows.copy() if isinstance(raw_rows, pd.DataFrame) else pd.DataFrame()
    non_finance_cells = _filter_by_keys(raw_cells_out, finance_keys, keep=False)
    non_finance_rows = _filter_by_keys(raw_rows_out, finance_keys, keep=False)
    return raw_rows_out, raw_cells_out, non_finance_rows, non_finance_cells


def finance_table_keys(finance_table_candidates: pd.DataFrame) -> set[tuple[str, int, int]]:
    return _table_keys(finance_table_candidates, status="FINANCE_NUMERIC_TABLE_CANDIDATE")


def _table_keys(frame: pd.DataFrame, *, status: str) -> set[tuple[str, int, int]]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return set()
    return {
        (str(row.get("file_hash", "")), int(row.get("page_number", 0) or 0), int(row.get("table_index", 0) or 0))
        for _, row in frame.iterrows()
        if str(row.get("table_status", "")) == status
    }


def _filter_by_keys(frame: pd.DataFrame, keys: set[tuple[str, int, int]], *, keep: bool) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return frame
    mask = frame.apply(
        lambda row: (str(row.get("file_hash", "")), int(row.get("page_number", 0) or 0), int(row.get("table_index", 0) or 0)) in keys,
        axis=1,
    )
    return frame[mask if keep else ~mask].copy()


def _keyword_hits(normalized: str, keywords: list[str]) -> int:
    return sum(1 for keyword in keywords if normalize_text(keyword) in normalized)


def _to_int(value: Any) -> int:
    try:
        return int(float(str(value or "0")))
    except ValueError:
        return 0


def _to_float(value: Any) -> float:
    try:
        return float(str(value or "0"))
    except ValueError:
        return 0.0


def _prose_ratio(normalized: str, numeric_tokens: int) -> float:
    words = len(str(normalized or "").split())
    if words <= 0:
        return 0.0
    return max(0.0, (words - numeric_tokens) / words)


def _page_reject_reason(
    anchor_hits: int,
    numeric_tokens: int,
    negative_hits: int,
    numeric_density: float,
    prose_ratio: float,
) -> str:
    if negative_hits:
        return "NEGATIVE_FINANCE_PAGE_SIGNALS"
    if anchor_hits < 2:
        return "INSUFFICIENT_FINANCE_ANCHORS"
    if numeric_tokens < 3:
        return "LOW_NUMERIC_TOKEN_COUNT"
    if numeric_density < MIN_FINANCE_PAGE_NUMERIC_DENSITY:
        return "LOW_NUMERIC_DENSITY"
    if prose_ratio > MAX_FINANCE_PAGE_PROSE_RATIO:
        return "HIGH_PROSE_RATIO"
    return "LOW_FINANCE_PAGE_SCORE"


def _table_reject_reason(anchor_hits: int, negative_hits: int, page_selected: bool) -> str:
    if negative_hits:
        return "NEGATIVE_FINANCE_TABLE_SIGNALS"
    if not page_selected:
        return "PAGE_NOT_FINANCE_NUMERIC_CANDIDATE"
    if anchor_hits < 2:
        return "INSUFFICIENT_FINANCE_ANCHORS"
    return "LOW_FINANCE_TABLE_SCORE"
