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
from src.ingestion.official_pdf_backend_registry import (  # noqa: E402
    PDF_BACKEND_AVAILABILITY_COLUMNS_01IF_PATCH2,
    build_pdf_backend_availability_rows,
    get_pdf_backend_availability,
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
from src.ingestion.official_finance_table_extractor import (  # noqa: E402
    RAW_TABLE_AUDIT_COLUMNS_01IF,
    TABLE_CELL_COLUMNS_01IF_PATCH1,
    build_finance_table_rows,
    build_raw_table_audit_rows,
    build_table_cell_audit_rows,
)
from src.ingestion.official_finance_value_parser import (  # noqa: E402
    OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF,
    detect_unit,
    mark_conflicting_duplicate_fields,
    parse_official_finance_values_from_pages,
    parse_official_finance_values_from_table_rows,
    split_usable_and_status_rows,
)
from src.ingestion.official_pdf_text_extractor import (  # noqa: E402
    PAGE_TEXT_AUDIT_COLUMNS_01IF_PATCH1,
    PDF_EXTRACTION_DIAGNOSTIC_COLUMNS_01IF_PATCH1,
    build_page_text_audit_rows,
    build_pdf_extraction_diagnostic_rows,
    build_raw_text_audit_rows,
    extract_pdf_document_content,
    extract_pdf_text_pages,
)
from src.ingestion.official_pdf_python_extractor import (  # noqa: E402
    PAGE_TEXT_AUDIT_COLUMNS_01IF_PATCH2,
    PDF_EXTRACTION_DIAGNOSTIC_COLUMNS_01IF_PATCH2,
    TABLE_CELL_COLUMNS_01IF_PATCH2,
    build_python_page_text_audit_rows,
    build_python_pdf_diagnostic_rows,
    build_python_table_cell_rows,
    extract_pdf_with_python_backends,
    write_markdown_audit,
)
from src.ingestion.official_pdf_table_normalizer import (  # noqa: E402
    NORMALIZED_TABLE_ROW_COLUMNS_01IF_PATCH2,
    normalize_finance_table_rows,
)


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
    parser.add_argument("--max-pages-per-document", type=int, default=120)
    parser.add_argument("--use-table-extraction", action="store_true")
    parser.add_argument("--prefer-table-values", action="store_true")
    parser.add_argument("--diagnose-only", action="store_true")
    parser.add_argument("--use-python-pdf-backends", action="store_true")
    parser.add_argument("--emit-markdown-audit", action="store_true")
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
    patch2_mode = args.use_python_pdf_backends or output_suffix(output_dir) == "_01if_patch2"
    backend_availability = pd.DataFrame(
        build_pdf_backend_availability_rows(get_pdf_backend_availability()),
        columns=PDF_BACKEND_AVAILABILITY_COLUMNS_01IF_PATCH2,
    ) if patch2_mode else pd.DataFrame(columns=PDF_BACKEND_AVAILABILITY_COLUMNS_01IF_PATCH2)

    if args.dry_run:
        empty_candidates = pd.DataFrame(columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF)
        empty_coverage = pd.DataFrame(columns=FIELD_COVERAGE_COLUMNS_01IF)
        empty_unresolved = pd.DataFrame(columns=UNRESOLVED_FIELDS_COLUMNS_01IF)
        empty_text = pd.DataFrame(columns=RAW_TEXT_AUDIT_COLUMNS_01IF)
        empty_table = pd.DataFrame(columns=RAW_TABLE_AUDIT_COLUMNS_01IF)
        empty_status = pd.DataFrame(columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF)
        empty_diagnostics = pd.DataFrame(columns=PDF_EXTRACTION_DIAGNOSTIC_COLUMNS_01IF_PATCH1)
        empty_page_audit = pd.DataFrame(columns=PAGE_TEXT_AUDIT_COLUMNS_01IF_PATCH1)
        empty_table_cells = pd.DataFrame(columns=TABLE_CELL_COLUMNS_01IF_PATCH1)
        empty_normalized_table_rows = pd.DataFrame(columns=NORMALIZED_TABLE_ROW_COLUMNS_01IF_PATCH2)
        manual = build_parse_manual_review_queue(
            selected_documents=selected_documents,
            candidate_rows=empty_candidates,
            coverage=empty_coverage,
            unresolved_fields=empty_unresolved,
            status_rows=empty_status,
        )
        write_outputs(
            output_dir=output_dir,
            candidate_rows=empty_candidates,
            status_rows=empty_status,
            coverage=empty_coverage,
            unresolved=empty_unresolved,
            raw_text=empty_text,
            raw_table=empty_table,
            diagnostics=empty_diagnostics,
            page_audit=empty_page_audit,
            table_cells=empty_table_cells,
            normalized_table_rows=empty_normalized_table_rows,
            backend_availability=backend_availability,
            markdown_audit_files=0,
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
    status_frames = []
    raw_text_rows = []
    raw_table_rows = []
    diagnostics_rows = []
    page_audit_rows = []
    table_cell_rows = []
    normalized_table_frames = []
    text_extractable_pdfs = 0
    non_text_pdfs = 0
    markdown_audit_files = 0
    for _, document in parse_targets.iterrows():
        if document["detected_file_type"] != "pdf":
            status_frames.append(pd.DataFrame([_failed_parse_row(document, "TABLE_EXTRACTION_FAILED", "XLSX_XLS_PARSE_NOT_IMPLEMENTED_YET", patch2_mode=patch2_mode)], columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF))
            continue
        if patch2_mode:
            extraction = extract_pdf_with_python_backends(
                document["local_path"],
                max_pages=args.max_pages_per_document,
                use_table_extraction=args.use_table_extraction,
            )
            pages = extraction.pages
            table_cells_from_pdf = extraction.table_cells
            diagnostics_rows.extend(build_python_pdf_diagnostic_rows(document_row=document, diagnostics=extraction.diagnostics))
        elif args.use_table_extraction or args.diagnose_only:
            extraction = extract_pdf_document_content(
                document["local_path"],
                max_pages=args.max_pages_per_document,
                use_table_extraction=args.use_table_extraction,
            )
            pages = extraction.pages
            table_cells_from_pdf = extraction.table_cells
            diagnostics_rows.extend(build_pdf_extraction_diagnostic_rows(document_row=document, diagnostics=extraction.diagnostics))
        else:
            pages = extract_pdf_text_pages(document["local_path"], max_pages=args.max_pages_per_document)
            table_cells_from_pdf = []
        has_text = any(getattr(page, "extraction_status", "") == "TEXT_EXTRACTED" for page in pages)
        has_tables = bool(table_cells_from_pdf)
        if has_text:
            text_extractable_pdfs += 1
        if not has_text and not has_tables:
            non_text_pdfs += 1
            status_frames.append(pd.DataFrame([_failed_parse_row(document, "DOCUMENT_NOT_TEXT_EXTRACTABLE", "NO_TEXT_EXTRACTED_NO_OCR", patch2_mode=patch2_mode)], columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF))
        unit_by_page = {}
        for page in pages:
            unit_raw, _, _, unit_status = detect_unit(getattr(page, "text", ""))
            unit_by_page[getattr(page, "page_number", 0)] = unit_raw if unit_status == "UNIT_DETECTED" else ""
        raw_text_rows.extend(build_raw_text_audit_rows(document_row=document, pages=pages, detected_unit_by_page=unit_by_page))
        if patch2_mode:
            page_audit_rows.extend(build_python_page_text_audit_rows(document_row=document, pages=pages))
        else:
            page_audit_rows.extend(build_page_text_audit_rows(document_row=document, pages=pages, detected_unit_by_page=unit_by_page))
        raw_table_rows.extend(build_raw_table_audit_rows(document_row=document, pages=pages))
        if patch2_mode:
            table_cell_rows.extend(build_python_table_cell_rows(document_row=document, table_cells=table_cells_from_pdf))
            normalized_table_rows, normalized_table_frame = normalize_finance_table_rows(
                document_row=document,
                pages=pages,
                table_cells=table_cells_from_pdf,
            )
            if not normalized_table_frame.empty:
                normalized_table_frames.append(normalized_table_frame)
            if args.emit_markdown_audit:
                audit_path = write_markdown_audit(
                    document_row=document,
                    pages=pages,
                    normalized_rows=normalized_table_frame,
                    output_dir=output_dir,
                )
                if audit_path:
                    markdown_audit_files += 1
        else:
            table_cell_rows.extend(build_table_cell_audit_rows(document_row=document, table_cells=table_cells_from_pdf, pages=pages))
            normalized_table_rows = build_finance_table_rows(document_row=document, pages=pages, table_cells=table_cells_from_pdf)
        if args.diagnose_only:
            continue
        parsed_frames = []
        if args.use_table_extraction:
            table_rows = normalized_table_rows if patch2_mode else build_finance_table_rows(document_row=document, pages=pages, table_cells=table_cells_from_pdf)
            parsed_table = parse_official_finance_values_from_table_rows(
                document_row=document,
                table_rows=table_rows,
                pages=pages,
                source_name="official_python_pdf_parser_01if_patch2" if patch2_mode else "official_pdf_parser_01if",
                parser_name="official_python_pdf_table_row_parser_01if_patch2" if patch2_mode else "official_pdf_table_row_parser_01if_patch1",
            )
            if not parsed_table.empty:
                parsed_frames.append(parsed_table)
            if args.use_table_extraction and not table_cells_from_pdf:
                status_frames.append(
                    pd.DataFrame(
                        [_failed_parse_row(document, "TABLE_EXTRACTION_UNAVAILABLE", "NO_TABLE_BACKEND_OR_NO_TABLES_EXTRACTED", patch2_mode=patch2_mode)],
                        columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF,
                    )
                )
        if not args.prefer_table_values:
            parsed_line = parse_official_finance_values_from_pages(
                document_row=document,
                pages=pages,
                source_name="official_python_pdf_parser_01if_patch2" if patch2_mode else "official_pdf_parser_01if",
                parser_name="official_python_pdf_text_line_parser_01if_patch2" if patch2_mode else "official_pdf_text_line_parser_01if",
            )
            if not parsed_line.empty:
                parsed_frames.append(parsed_line)
        elif not parsed_frames:
            parsed_line = parse_official_finance_values_from_pages(
                document_row=document,
                pages=pages,
                source_name="official_python_pdf_parser_01if_patch2" if patch2_mode else "official_pdf_parser_01if",
                parser_name="official_python_pdf_text_line_parser_01if_patch2" if patch2_mode else "official_pdf_text_line_parser_01if",
            )
            if not parsed_line.empty:
                _, line_status = split_usable_and_status_rows(parsed_line)
                if not line_status.empty:
                    status_frames.append(line_status)
        if parsed_frames:
            combined = mark_conflicting_duplicate_fields(pd.concat(parsed_frames, ignore_index=True))
            usable, status = split_usable_and_status_rows(combined)
            if not usable.empty:
                candidate_frames.append(usable)
            if not status.empty:
                status_frames.append(status)

    candidate_rows = (
        pd.concat(candidate_frames, ignore_index=True)[OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF]
        if candidate_frames
        else pd.DataFrame(columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF)
    )
    status_rows = (
        pd.concat(status_frames, ignore_index=True)[OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF]
        if status_frames
        else pd.DataFrame(columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF)
    )
    coverage = build_field_coverage(selected_documents=selected_documents, candidate_rows=candidate_rows, status_rows=status_rows)
    unresolved = build_unresolved_fields(selected_documents=selected_documents, candidate_rows=candidate_rows, coverage=coverage, status_rows=status_rows)
    manual = build_parse_manual_review_queue(
        selected_documents=selected_documents,
        candidate_rows=candidate_rows,
        coverage=coverage,
        unresolved_fields=unresolved,
        status_rows=status_rows,
    )
    raw_text = pd.DataFrame(raw_text_rows, columns=RAW_TEXT_AUDIT_COLUMNS_01IF)
    raw_table = pd.DataFrame(raw_table_rows, columns=RAW_TABLE_AUDIT_COLUMNS_01IF)
    diagnostics = pd.DataFrame(diagnostics_rows, columns=PDF_EXTRACTION_DIAGNOSTIC_COLUMNS_01IF_PATCH1)
    page_audit = pd.DataFrame(page_audit_rows, columns=PAGE_TEXT_AUDIT_COLUMNS_01IF_PATCH1)
    table_cells = pd.DataFrame(table_cell_rows, columns=TABLE_CELL_COLUMNS_01IF_PATCH1)
    if patch2_mode:
        diagnostics = pd.DataFrame(diagnostics_rows, columns=PDF_EXTRACTION_DIAGNOSTIC_COLUMNS_01IF_PATCH2)
        page_audit = pd.DataFrame(page_audit_rows, columns=PAGE_TEXT_AUDIT_COLUMNS_01IF_PATCH2)
        table_cells = pd.DataFrame(table_cell_rows, columns=TABLE_CELL_COLUMNS_01IF_PATCH2)
    normalized_table_rows_frame = (
        pd.concat(normalized_table_frames, ignore_index=True)[NORMALIZED_TABLE_ROW_COLUMNS_01IF_PATCH2]
        if normalized_table_frames
        else pd.DataFrame(columns=NORMALIZED_TABLE_ROW_COLUMNS_01IF_PATCH2)
    )
    write_outputs(
        output_dir=output_dir,
        candidate_rows=candidate_rows,
        status_rows=status_rows,
        coverage=coverage,
        unresolved=unresolved,
        raw_text=raw_text,
        raw_table=raw_table,
        diagnostics=diagnostics,
        page_audit=page_audit,
        table_cells=table_cells,
        normalized_table_rows=normalized_table_rows_frame,
        backend_availability=backend_availability,
        markdown_audit_files=markdown_audit_files,
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
    status_rows: pd.DataFrame,
    coverage: pd.DataFrame,
    unresolved: pd.DataFrame,
    raw_text: pd.DataFrame,
    raw_table: pd.DataFrame,
    diagnostics: pd.DataFrame,
    page_audit: pd.DataFrame,
    table_cells: pd.DataFrame,
    normalized_table_rows: pd.DataFrame,
    backend_availability: pd.DataFrame,
    markdown_audit_files: int,
    manual: pd.DataFrame,
    selected_documents: pd.DataFrame,
    command: str,
    text_extractable_pdfs: int,
    non_text_pdfs: int,
) -> None:
    suffix = output_suffix(output_dir)
    candidate_rows.to_csv(output_dir / f"official_finance_candidate_rows{suffix}.csv", index=False)
    status_rows.to_csv(output_dir / f"official_finance_parse_status_rows{suffix}.csv", index=False)
    coverage.to_csv(output_dir / f"official_finance_field_coverage{suffix}.csv", index=False)
    unresolved.to_csv(output_dir / f"official_finance_unresolved_fields{suffix}.csv", index=False)
    raw_text.to_csv(output_dir / "official_finance_raw_text_audit_01if.csv", index=False)
    raw_table.to_csv(output_dir / "official_finance_raw_table_audit_01if.csv", index=False)
    if suffix == "_01if_patch1":
        diagnostics.to_csv(output_dir / "pdf_extraction_diagnostics_01if_patch1.csv", index=False)
        page_audit.to_csv(output_dir / "official_finance_page_text_audit_01if_patch1.csv", index=False)
        table_cells.to_csv(output_dir / "official_finance_table_cells_01if_patch1.csv", index=False)
    if suffix == "_01if_patch2":
        backend_availability.to_csv(output_dir / "pdf_backend_availability_01if_patch2.csv", index=False)
        diagnostics.to_csv(output_dir / "pdf_extraction_diagnostics_01if_patch2.csv", index=False)
        page_audit.to_csv(output_dir / "official_finance_page_text_audit_01if_patch2.csv", index=False)
        table_cells.to_csv(output_dir / "official_finance_table_cells_01if_patch2.csv", index=False)
        normalized_table_rows.to_csv(output_dir / "official_finance_normalized_table_rows_01if_patch2.csv", index=False)
    manual.to_csv(output_dir / "manual_review_queue.csv", index=False)
    (output_dir / "datasource_decision_report.md").write_text(
        build_01if_decision_report_markdown(
            selected_documents=selected_documents,
            candidate_rows=candidate_rows,
            coverage=coverage,
            backend_availability=backend_availability if suffix == "_01if_patch2" else None,
        ),
        encoding="utf-8",
    )
    if suffix == "_01if_patch2":
        summary_name = "official_finance_parse_01if_patch2_run_summary.md"
    elif suffix == "_01if_patch1":
        summary_name = "official_finance_parse_01if_patch1_run_summary.md"
    else:
        summary_name = "official_finance_parse_01if_run_summary.md"
    (output_dir / summary_name).write_text(
        build_01if_run_summary_markdown(
            command=command,
            selected_documents=selected_documents,
            candidate_rows=candidate_rows,
            coverage=coverage,
            manual_review_queue=manual,
            text_extractable_pdfs=text_extractable_pdfs,
            non_text_pdfs=non_text_pdfs,
            diagnostics=diagnostics,
            table_cells=table_cells,
            status_rows=status_rows,
            backend_availability=backend_availability if suffix == "_01if_patch2" else None,
            normalized_table_rows=normalized_table_rows,
            markdown_audit_files=markdown_audit_files,
            text_extractable_before=3 if suffix == "_01if_patch2" else None,
        ),
        encoding="utf-8",
    )


def _failed_parse_row(document: pd.Series, status: str, reason: str, *, patch2_mode: bool = False) -> dict[str, Any]:
    source_name = "official_python_pdf_parser_01if_patch2" if patch2_mode else "official_pdf_parser_01if"
    parser_name = "official_python_pdf_text_line_parser_01if_patch2" if patch2_mode else "official_pdf_text_line_parser_01if"
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
        "source_name": source_name,
        "source_url": document.get("source_url", ""),
        "final_url": document.get("final_url", ""),
        "local_path": document.get("local_path", ""),
        "file_hash": document.get("file_hash", ""),
        "page_number": "",
        "table_index": "",
        "row_index": "",
        "raw_label": "",
        "raw_context": "",
        "parser_name": parser_name,
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


def output_suffix(output_dir: Path) -> str:
    lowered = str(output_dir).lower()
    if "patch2" in lowered:
        return "_01if_patch2"
    if "patch1" in lowered:
        return "_01if_patch1"
    return "_01if"


def parse_csv(value: str) -> list[str]:
    return [item.strip().upper() for item in str(value or "").split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
