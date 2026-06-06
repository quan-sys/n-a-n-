"""Evidence and reports for REAL-DATA-01I-F official finance parsing."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.ingestion.official_finance_document_selector import SELECTED_DOCUMENT_COLUMNS_01IF
from src.ingestion.official_finance_value_parser import CANONICAL_FIELDS_01IF


FIELD_COVERAGE_COLUMNS_01IF = [
    "ticker",
    "period",
    "document_hash",
    "fields_found",
    "fields_missing",
    "required_fields_found_count",
    "required_fields_missing_count",
    "coverage_status",
    "manual_review_required",
    "notes",
]

UNRESOLVED_FIELDS_COLUMNS_01IF = [
    "ticker",
    "period",
    "field_name",
    "issue",
    "manual_review_required",
    "notes",
]

RAW_TEXT_AUDIT_COLUMNS_01IF = [
    "ticker",
    "period",
    "local_path",
    "file_hash",
    "page_number",
    "text_snippet",
    "detected_unit",
    "notes",
]

MANUAL_REVIEW_COLUMNS_01IF_PARSE = [
    "ticker",
    "period",
    "document_type",
    "source_url",
    "issue",
    "manual_review_required",
    "priority",
    "notes",
]


def build_field_coverage(
    *,
    selected_documents: pd.DataFrame,
    candidate_rows: pd.DataFrame,
    required_fields: list[str] | None = None,
) -> pd.DataFrame:
    required_fields = required_fields or CANONICAL_FIELDS_01IF
    rows = []
    selected_for_parse = selected_documents[selected_documents["selection_status"] == "SELECTED_FOR_PARSE"] if not selected_documents.empty else pd.DataFrame(columns=SELECTED_DOCUMENT_COLUMNS_01IF)
    for _, document in selected_for_parse.iterrows():
        doc_rows = _document_candidate_rows(candidate_rows, document)
        parsed_fields = sorted(
            set(doc_rows.loc[doc_rows["parse_status"].eq("FIELD_PARSED"), "field_name"].astype(str))
        ) if not doc_rows.empty else []
        missing_fields = [field for field in required_fields if field not in parsed_fields]
        if not doc_rows.empty and (doc_rows["parse_status"] == "DOCUMENT_NOT_TEXT_EXTRACTABLE").any():
            status = "NO_TEXT_EXTRACTED"
        elif len(parsed_fields) >= 6 and all(field in parsed_fields for field in ["revenue", "net_profit", "total_assets", "equity"]):
            status = "SUFFICIENT_FOR_RECONCILIATION"
        elif parsed_fields:
            status = "PARTIAL_PARSE"
        else:
            status = "INSUFFICIENT_PARSE"
        manual_review = bool(missing_fields) or bool(doc_rows["manual_review_required"].astype(bool).any()) if not doc_rows.empty else True
        if manual_review and status == "SUFFICIENT_FOR_RECONCILIATION":
            status = "MANUAL_REVIEW_REQUIRED"
        rows.append(
            {
                "ticker": document.get("ticker", ""),
                "period": document.get("period", ""),
                "document_hash": document.get("file_hash", ""),
                "fields_found": "|".join(parsed_fields),
                "fields_missing": "|".join(missing_fields),
                "required_fields_found_count": len(parsed_fields),
                "required_fields_missing_count": len(missing_fields),
                "coverage_status": status,
                "manual_review_required": manual_review,
                "notes": "official parser does not infer missing values",
            }
        )
    return pd.DataFrame(rows, columns=FIELD_COVERAGE_COLUMNS_01IF)


def build_unresolved_fields(
    *,
    selected_documents: pd.DataFrame,
    candidate_rows: pd.DataFrame,
    coverage: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    for _, row in coverage.iterrows():
        for field_name in str(row.get("fields_missing", "")).split("|"):
            if field_name:
                rows.append(
                    {
                        "ticker": row.get("ticker", ""),
                        "period": row.get("period", ""),
                        "field_name": field_name,
                        "issue": "FIELD_NOT_FOUND",
                        "manual_review_required": True,
                        "notes": "missing field was not inferred or zero-filled",
                    }
                )
    if isinstance(candidate_rows, pd.DataFrame) and not candidate_rows.empty:
        unresolved = candidate_rows[candidate_rows["parse_status"] != "FIELD_PARSED"]
        for _, row in unresolved.iterrows():
            rows.append(
                {
                    "ticker": row.get("ticker", ""),
                    "period": row.get("period", ""),
                    "field_name": row.get("field_name", ""),
                    "issue": row.get("parse_status", ""),
                    "manual_review_required": True,
                    "notes": row.get("review_reason", ""),
                }
            )
    review_only = selected_documents[selected_documents["selection_status"] != "SELECTED_FOR_PARSE"] if isinstance(selected_documents, pd.DataFrame) and not selected_documents.empty else pd.DataFrame()
    for _, row in review_only.iterrows():
        rows.append(
            {
                "ticker": row.get("ticker", ""),
                "period": row.get("period", ""),
                "field_name": "",
                "issue": row.get("selection_status", ""),
                "manual_review_required": True,
                "notes": row.get("reason", ""),
            }
        )
    if not rows:
        return pd.DataFrame(columns=UNRESOLVED_FIELDS_COLUMNS_01IF)
    return pd.DataFrame(rows, columns=UNRESOLVED_FIELDS_COLUMNS_01IF).drop_duplicates()


def build_parse_manual_review_queue(
    *,
    selected_documents: pd.DataFrame,
    candidate_rows: pd.DataFrame,
    coverage: pd.DataFrame,
    unresolved_fields: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    for _, row in selected_documents[selected_documents["selection_status"] != "SELECTED_FOR_PARSE"].iterrows():
        rows.append(_manual_row(row, row.get("selection_status", ""), _priority_for_issue(row.get("selection_status", "")), row.get("reason", "")))
    if isinstance(candidate_rows, pd.DataFrame) and not candidate_rows.empty:
        for _, row in candidate_rows[candidate_rows["manual_review_required"].astype(bool)].iterrows():
            rows.append(
                {
                    "ticker": row.get("ticker", ""),
                    "period": row.get("period", ""),
                    "document_type": "",
                    "source_url": row.get("source_url", ""),
                    "issue": row.get("parse_status", ""),
                    "manual_review_required": True,
                    "priority": _priority_for_issue(row.get("parse_status", "")),
                    "notes": row.get("review_reason", ""),
                }
            )
    for _, row in coverage[coverage["manual_review_required"].astype(bool)].iterrows():
        rows.append(
            {
                "ticker": row.get("ticker", ""),
                "period": row.get("period", ""),
                "document_type": "",
                "source_url": "",
                "issue": "MISSING_REQUIRED_FIELDS",
                "manual_review_required": True,
                "priority": "high" if row.get("required_fields_found_count", 0) == 0 else "medium",
                "notes": row.get("fields_missing", ""),
            }
        )
    if isinstance(unresolved_fields, pd.DataFrame) and not unresolved_fields.empty:
        for _, row in unresolved_fields.iterrows():
            if row.get("issue") != "FIELD_NOT_FOUND":
                continue
            rows.append(
                {
                    "ticker": row.get("ticker", ""),
                    "period": row.get("period", ""),
                    "document_type": "",
                    "source_url": "",
                    "issue": f"FIELD_NOT_FOUND:{row.get('field_name', '')}",
                    "manual_review_required": True,
                    "priority": "low",
                    "notes": row.get("notes", ""),
                }
            )
    if not rows:
        return pd.DataFrame(columns=MANUAL_REVIEW_COLUMNS_01IF_PARSE)
    return pd.DataFrame(rows, columns=MANUAL_REVIEW_COLUMNS_01IF_PARSE).drop_duplicates()


def build_01if_decision_report_markdown(
    *,
    selected_documents: pd.DataFrame,
    candidate_rows: pd.DataFrame,
    coverage: pd.DataFrame,
) -> str:
    selected_count = int((selected_documents["selection_status"] == "SELECTED_FOR_PARSE").sum()) if not selected_documents.empty else 0
    parsed_count = int((candidate_rows["parse_status"] == "FIELD_PARSED").sum()) if not candidate_rows.empty else 0
    tickers_with_parse = int(candidate_rows.loc[candidate_rows["parse_status"] == "FIELD_PARSED", "ticker"].nunique()) if parsed_count else 0
    sufficient = int((coverage["coverage_status"] == "SUFFICIENT_FOR_RECONCILIATION").sum()) if not coverage.empty else 0
    parse_ready = "Partial" if parsed_count else "False"
    l0_ready = "Partial" if sufficient >= 2 else "unchanged"
    document_file_ready = "True" if selected_count else "Partial"
    return "\n".join(
        [
            "# Datasource decision report",
            "",
            f"- official_document_file_ready: {document_file_ready}",
            f"- official_finance_parse_ready: {parse_ready}",
            f"- official_finance_candidate_rows: {len(candidate_rows)}",
            f"- tickers_with_official_parse: {tickers_with_parse}",
            f"- finance_ready_for_l0: {l0_ready}",
            "- finance_disclosure_ready_for_step18: False",
            "- should_run_REAL_DATA_02: No",
            "- should_implement_Step19_now: No",
            "",
            "01I-F emits source-backed official parser candidate rows only. Full reconciliation remains 01I-G.",
        ]
    )


def build_01if_run_summary_markdown(
    *,
    command: str,
    selected_documents: pd.DataFrame,
    candidate_rows: pd.DataFrame,
    coverage: pd.DataFrame,
    manual_review_queue: pd.DataFrame,
    text_extractable_pdfs: int,
    non_text_pdfs: int,
) -> str:
    selected_count = int((selected_documents["selection_status"] == "SELECTED_FOR_PARSE").sum()) if not selected_documents.empty else 0
    skipped_count = int(len(selected_documents) - selected_count)
    parsed_docs = int(candidate_rows["file_hash"].nunique()) if not candidate_rows.empty else 0
    return "\n".join(
        [
            "# REAL-DATA-01I-F official finance parse run",
            "",
            "## Command run",
            f"`{command}`",
            "",
            "## Documents selected",
            str(selected_count),
            "",
            "## Documents parsed",
            str(parsed_docs),
            "",
            "## Documents skipped",
            str(skipped_count),
            "",
            "## Text-extractable PDFs",
            str(text_extractable_pdfs),
            "",
            "## Non-text/scanned PDFs",
            str(non_text_pdfs),
            "",
            "## Candidate rows parsed",
            str(len(candidate_rows)),
            "",
            "## Rows by field",
            _format_counts(_counts(candidate_rows, "field_name")),
            "",
            "## Rows by ticker",
            _format_counts(_counts(candidate_rows, "ticker")),
            "",
            "## Coverage by ticker/period",
            _format_coverage(coverage),
            "",
            "## Manual review rows",
            str(len(manual_review_queue)),
            "",
            "## Main blockers",
            _format_counts(_counts(manual_review_queue, "issue")),
            "",
            "## Next recommended action",
            "Review parser evidence and unresolved fields, then implement 01I-G reconciliation before any broader scale-up.",
        ]
    )


def _document_candidate_rows(candidate_rows: pd.DataFrame, document: pd.Series) -> pd.DataFrame:
    if not isinstance(candidate_rows, pd.DataFrame) or candidate_rows.empty:
        return pd.DataFrame(columns=candidate_rows.columns if isinstance(candidate_rows, pd.DataFrame) else [])
    return candidate_rows[
        (candidate_rows["ticker"].astype(str) == str(document.get("ticker", "")))
        & (candidate_rows["period"].astype(str) == str(document.get("period", "")))
        & (candidate_rows["file_hash"].astype(str) == str(document.get("file_hash", "")))
    ].copy()


def _manual_row(row: pd.Series, issue: str, priority: str, notes: Any) -> dict[str, Any]:
    return {
        "ticker": row.get("ticker", ""),
        "period": row.get("period", ""),
        "document_type": row.get("document_type", ""),
        "source_url": row.get("source_url", ""),
        "issue": issue,
        "manual_review_required": True,
        "priority": priority,
        "notes": notes,
    }


def _priority_for_issue(issue: Any) -> str:
    text = str(issue or "")
    if any(token in text for token in ["DOCUMENT_NOT_TEXT", "UNIT_AMBIGUOUS", "FIELD_LABEL_AMBIGUOUS", "MISSING_REQUIRED", "STANDALONE"]):
        return "high"
    if "REVIEW_ONLY" in text or "FIELD_VALUE" in text:
        return "medium"
    return "low"


def _counts(df: pd.DataFrame, column: str) -> dict[str, int]:
    if not isinstance(df, pd.DataFrame) or df.empty or column not in df.columns:
        return {}
    return {str(key): int(value) for key, value in df[column].value_counts(dropna=False).items()}


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "- none"
    return "\n".join(f"- {key}: {value}" for key, value in counts.items())


def _format_coverage(coverage: pd.DataFrame) -> str:
    if not isinstance(coverage, pd.DataFrame) or coverage.empty:
        return "- none"
    return "\n".join(
        f"- {row['ticker']} {row['period']}: {row['coverage_status']} "
        f"(found={row['required_fields_found_count']}, missing={row['required_fields_missing_count']})"
        for _, row in coverage.iterrows()
    )
