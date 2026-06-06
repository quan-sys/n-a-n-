from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ingestion.official_finance_document_selector import (  # noqa: E402
    SELECTED_DOCUMENT_COLUMNS_01IF,
    select_documents_for_official_parse,
)
from src.ingestion.official_finance_parse_evidence import (  # noqa: E402
    FIELD_COVERAGE_COLUMNS_01IF,
    MANUAL_REVIEW_COLUMNS_01IF_PARSE,
    RAW_TEXT_AUDIT_COLUMNS_01IF,
    UNRESOLVED_FIELDS_COLUMNS_01IF,
    build_01if_decision_report_markdown,
    build_01if_run_summary_markdown,
    build_field_coverage,
    build_parse_manual_review_queue,
    build_unresolved_fields,
)
from src.ingestion.official_finance_table_extractor import RAW_TABLE_AUDIT_COLUMNS_01IF, build_raw_table_audit_rows  # noqa: E402
from src.ingestion.official_finance_value_parser import (  # noqa: E402
    OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF,
    detect_unit,
    parse_official_finance_values_from_pages,
)
from src.ingestion.official_pdf_text_extractor import build_raw_text_audit_rows, extract_pdf_text_pages  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="REAL-DATA-01I-F parse verified official finance PDFs.")
    parser.add_argument("--document-index", default="data/reports/official_finance_documents_01ie/finance_document_index.csv")
    parser.add_argument("--output-dir", default="data/reports/official_finance_parse_01if")
    parser.add_argument("--max-documents", type=int, default=40)
    parser.add_argument("--target-periods", default="2026-Q1,2025-Q4,2025,2025-Q3,2025-Q2")
    parser.add_argument("--tickers", default="")
    parser.add_argument("--parse-annual-reports", action="store_true")
    parser.add_argument("--skip-standalone", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--max-pages-per-document", type=int, default=25)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    document_index = pd.read_csv(args.document_index, keep_default_na=False)
    selected_documents = select_documents_for_official_parse(
        document_index,
        target_periods=parse_csv(args.target_periods),
        tickers=parse_csv(args.tickers),
        parse_annual_reports=args.parse_annual_reports,
        skip_standalone=args.skip_standalone,
    )
    selected_documents.to_csv(output_dir / "selected_documents_for_parse.csv", index=False)

    if args.dry_run:
        empty_candidates = pd.DataFrame(columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF)
        empty_coverage = pd.DataFrame(columns=FIELD_COVERAGE_COLUMNS_01IF)
        empty_unresolved = pd.DataFrame(columns=UNRESOLVED_FIELDS_COLUMNS_01IF)
        empty_text = pd.DataFrame(columns=RAW_TEXT_AUDIT_COLUMNS_01IF)
        empty_table = pd.DataFrame(columns=RAW_TABLE_AUDIT_COLUMNS_01IF)
        manual = build_parse_manual_review_queue(
            selected_documents=selected_documents,
            candidate_rows=empty_candidates,
            coverage=empty_coverage,
            unresolved_fields=empty_unresolved,
        )
        write_outputs(
            output_dir=output_dir,
            candidate_rows=empty_candidates,
            coverage=empty_coverage,
            unresolved=empty_unresolved,
            raw_text=empty_text,
            raw_table=empty_table,
            manual=manual,
            selected_documents=selected_documents,
            command=command_string(),
            text_extractable_pdfs=0,
            non_text_pdfs=0,
        )
        print_summary(args, selected_documents, empty_candidates, empty_coverage, manual, 0, 0)
        return 0

    parse_targets = selected_documents[selected_documents["selection_status"] == "SELECTED_FOR_PARSE"].copy()
    if args.max_documents:
        parse_targets = parse_targets.head(args.max_documents)
    if parse_targets.empty and not args.allow_partial:
        raise SystemExit("No documents selected for parse. Pass --allow-partial to write reports only.")

    candidate_frames = []
    raw_text_rows = []
    raw_table_rows = []
    text_extractable_pdfs = 0
    non_text_pdfs = 0
    for _, document in parse_targets.iterrows():
        if document["detected_file_type"] != "pdf":
            candidate_frames.append(pd.DataFrame([_failed_parse_row(document, "TABLE_EXTRACTION_FAILED", "XLSX_XLS_PARSE_NOT_IMPLEMENTED_YET")], columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF))
            continue
        pages = extract_pdf_text_pages(document["local_path"], max_pages=args.max_pages_per_document)
        has_text = any(getattr(page, "extraction_status", "") == "TEXT_EXTRACTED" for page in pages)
        if has_text:
            text_extractable_pdfs += 1
        else:
            non_text_pdfs += 1
            candidate_frames.append(pd.DataFrame([_failed_parse_row(document, "DOCUMENT_NOT_TEXT_EXTRACTABLE", "NO_TEXT_EXTRACTED_NO_OCR")], columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF))
        unit_by_page = {}
        for page in pages:
            unit_raw, _, _, unit_status = detect_unit(getattr(page, "text", ""))
            unit_by_page[getattr(page, "page_number", 0)] = unit_raw if unit_status == "UNIT_DETECTED" else ""
        raw_text_rows.extend(build_raw_text_audit_rows(document_row=document, pages=pages, detected_unit_by_page=unit_by_page))
        raw_table_rows.extend(build_raw_table_audit_rows(document_row=document, pages=pages))
        parsed = parse_official_finance_values_from_pages(document_row=document, pages=pages)
        if not parsed.empty:
            candidate_frames.append(parsed)

    candidate_rows = (
        pd.concat(candidate_frames, ignore_index=True)[OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF]
        if candidate_frames
        else pd.DataFrame(columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF)
    )
    coverage = build_field_coverage(selected_documents=selected_documents, candidate_rows=candidate_rows)
    unresolved = build_unresolved_fields(selected_documents=selected_documents, candidate_rows=candidate_rows, coverage=coverage)
    manual = build_parse_manual_review_queue(
        selected_documents=selected_documents,
        candidate_rows=candidate_rows,
        coverage=coverage,
        unresolved_fields=unresolved,
    )
    raw_text = pd.DataFrame(raw_text_rows, columns=RAW_TEXT_AUDIT_COLUMNS_01IF)
    raw_table = pd.DataFrame(raw_table_rows, columns=RAW_TABLE_AUDIT_COLUMNS_01IF)
    write_outputs(
        output_dir=output_dir,
        candidate_rows=candidate_rows,
        coverage=coverage,
        unresolved=unresolved,
        raw_text=raw_text,
        raw_table=raw_table,
        manual=manual,
        selected_documents=selected_documents,
        command=command_string(),
        text_extractable_pdfs=text_extractable_pdfs,
        non_text_pdfs=non_text_pdfs,
    )
    print_summary(args, selected_documents, candidate_rows, coverage, manual, text_extractable_pdfs, non_text_pdfs)
    return 0


def write_outputs(
    *,
    output_dir: Path,
    candidate_rows: pd.DataFrame,
    coverage: pd.DataFrame,
    unresolved: pd.DataFrame,
    raw_text: pd.DataFrame,
    raw_table: pd.DataFrame,
    manual: pd.DataFrame,
    selected_documents: pd.DataFrame,
    command: str,
    text_extractable_pdfs: int,
    non_text_pdfs: int,
) -> None:
    candidate_rows.to_csv(output_dir / "official_finance_candidate_rows_01if.csv", index=False)
    coverage.to_csv(output_dir / "official_finance_field_coverage_01if.csv", index=False)
    unresolved.to_csv(output_dir / "official_finance_unresolved_fields_01if.csv", index=False)
    raw_text.to_csv(output_dir / "official_finance_raw_text_audit_01if.csv", index=False)
    raw_table.to_csv(output_dir / "official_finance_raw_table_audit_01if.csv", index=False)
    manual.to_csv(output_dir / "manual_review_queue.csv", index=False)
    (output_dir / "datasource_decision_report.md").write_text(
        build_01if_decision_report_markdown(
            selected_documents=selected_documents,
            candidate_rows=candidate_rows,
            coverage=coverage,
        ),
        encoding="utf-8",
    )
    (output_dir / "official_finance_parse_01if_run_summary.md").write_text(
        build_01if_run_summary_markdown(
            command=command,
            selected_documents=selected_documents,
            candidate_rows=candidate_rows,
            coverage=coverage,
            manual_review_queue=manual,
            text_extractable_pdfs=text_extractable_pdfs,
            non_text_pdfs=non_text_pdfs,
        ),
        encoding="utf-8",
    )


def _failed_parse_row(document: pd.Series, status: str, reason: str) -> dict[str, Any]:
    return {
        "ticker": document.get("ticker", ""),
        "period": document.get("period", ""),
        "period_type": "quarter" if "-Q" in str(document.get("period", "")).upper() else "annual",
        "field_name": "",
        "value_vnd": "",
        "raw_value": "",
        "unit_raw": "",
        "unit_multiplier": "",
        "currency": "",
        "source_category": "official_company_document",
        "source_name": "official_pdf_parser_01if",
        "source_url": document.get("source_url", ""),
        "final_url": document.get("final_url", ""),
        "local_path": document.get("local_path", ""),
        "file_hash": document.get("file_hash", ""),
        "page_number": "",
        "table_index": "",
        "row_index": "",
        "raw_label": "",
        "raw_context": "",
        "parser_name": "official_pdf_text_line_parser_01if",
        "parse_status": status,
        "confidence_raw": "low",
        "manual_review_required": True,
        "review_reason": reason,
        "fetch_time": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "notes": "no values inferred or fabricated",
    }


def print_summary(
    args: argparse.Namespace,
    selected_documents: pd.DataFrame,
    candidate_rows: pd.DataFrame,
    coverage: pd.DataFrame,
    manual: pd.DataFrame,
    text_extractable_pdfs: int,
    non_text_pdfs: int,
) -> None:
    selected_count = int((selected_documents["selection_status"] == "SELECTED_FOR_PARSE").sum()) if not selected_documents.empty else 0
    parsed_count = int((candidate_rows["parse_status"] == "FIELD_PARSED").sum()) if not candidate_rows.empty else 0
    print(
        {
            "output_dir": args.output_dir,
            "documents_selected": selected_count,
            "documents_parsed": int(candidate_rows["file_hash"].nunique()) if not candidate_rows.empty else 0,
            "text_extractable_pdfs": text_extractable_pdfs,
            "scanned_unextractable_pdfs": non_text_pdfs,
            "official_finance_candidate_rows": int(len(candidate_rows)),
            "field_parsed_rows": parsed_count,
            "manual_review_rows": int(len(manual)),
            "finance_parse_ready": "Partial" if parsed_count else False,
            "should_run_REAL_DATA_02": "No",
            "should_implement_Step19_now": "No",
        }
    )


def command_string() -> str:
    return " ".join([Path(sys.executable).name, *sys.argv])


def parse_csv(value: str) -> list[str]:
    return [item.strip().upper() for item in str(value or "").split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
