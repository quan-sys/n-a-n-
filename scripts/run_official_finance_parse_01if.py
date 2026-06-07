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
from src.ingestion.official_finance_numeric_table_dump import (  # noqa: E402
    NUMERIC_PAGE_CANDIDATE_COLUMNS_01IF_PATCH3_PATCH2,
    NUMERIC_TABLE_CANDIDATE_COLUMNS_01IF_PATCH3_PATCH2,
    NUMERIC_TABLE_CELL_COLUMNS_01IF_PATCH3_PATCH2,
    NUMERIC_TABLE_DUMP_INDEX_COLUMNS_01IF_PATCH3_PATCH2,
    NUMERIC_TABLE_ROW_COLUMNS_01IF_PATCH3_PATCH2,
    build_line_fallback_table_cells,
    build_numeric_page_candidates,
    build_numeric_table_dump_frames,
    coverage_candidate_rows,
    selected_numeric_page_numbers,
    write_numeric_audit_files,
)
from src.ingestion.official_pdf_backend_registry import (  # noqa: E402
    PDF_BACKEND_AVAILABILITY_COLUMNS_01IF_PATCH2,
    build_pdf_backend_availability_rows,
    get_pdf_backend_availability,
)
from src.ingestion.official_finance_statement_targeter import (  # noqa: E402
    PATCH3_CANDIDATE_COLUMNS,
    STATEMENT_PAGE_CANDIDATE_COLUMNS_01IF_PATCH3,
    STATEMENT_TABLE_CANDIDATE_COLUMNS_01IF_PATCH3,
    build_statement_page_candidates,
    build_statement_table_candidates,
    filter_cells_to_selected_statement_tables,
    parse_patch3_statement_rows,
    selected_statement_page_numbers,
    write_statement_audit_files,
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
    extract_pdfplumber_all_tables_for_pages,
    extract_pdfplumber_tables_for_pages,
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
    parser.add_argument("--input-index", default="")
    parser.add_argument("--input-document-index", default="")
    parser.add_argument("--output-dir", default="data/reports/official_finance_parse_01if")
    parser.add_argument("--patch", default="")
    parser.add_argument("--mode", default="")
    parser.add_argument("--max-documents", type=int, default=40)
    parser.add_argument("--limit-documents", type=int, default=0)
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
    parser.add_argument("--statement-pages-only", action="store_true")
    parser.add_argument("--enable-statement-targeting", action="store_true")
    parser.add_argument("--enable-numeric-table-dump", action="store_true")
    parser.add_argument("--no-ocr", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.input_index and not args.input_document_index:
        args.input_document_index = args.input_index
    if args.limit_documents:
        args.max_documents = args.limit_documents
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    document_index_path = args.input_document_index or args.document_index
    document_index = pd.read_csv(document_index_path, keep_default_na=False)
    selected_documents = select_documents_for_official_parse(
        document_index,
        target_periods=parse_csv(args.target_periods),
        tickers=parse_csv(args.tickers),
        parse_annual_reports=args.parse_annual_reports,
        skip_standalone=args.skip_standalone,
    )
    selected_documents.to_csv(output_dir / "selected_documents_for_parse.csv", index=False)
    patch_suffix = output_suffix(output_dir)
    patch3_patch2_mode = (
        args.enable_numeric_table_dump
        or args.patch.lower() in {"01if_patch3_patch2", "patch3_patch2"}
        or patch_suffix == "_01if_patch3_patch2"
    )
    patch2_mode = args.use_python_pdf_backends or patch_suffix == "_01if_patch2"
    patch3_mode = args.patch.lower() == "01if_patch3" or args.statement_pages_only or args.enable_statement_targeting or patch_suffix == "_01if_patch3"
    if patch3_patch2_mode:
        return run_patch3_patch2_numeric_table_dump(
            args=args,
            output_dir=output_dir,
            selected_documents=selected_documents,
            command=command_string(),
        )
    if patch3_mode:
        return run_patch3_statement_page_parse(
            args=args,
            output_dir=output_dir,
            selected_documents=selected_documents,
            command=command_string(),
        )
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


def run_patch3_statement_page_parse(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    selected_documents: pd.DataFrame,
    command: str,
) -> int:
    parse_targets = selected_documents[selected_documents["selection_status"] == "SELECTED_FOR_PARSE"].copy()
    if args.max_documents:
        parse_targets = parse_targets.head(args.max_documents)
    backend_availability = pd.DataFrame(
        build_pdf_backend_availability_rows(get_pdf_backend_availability()),
        columns=PDF_BACKEND_AVAILABILITY_COLUMNS_01IF_PATCH2,
    )
    candidate_frames = []
    status_frames = []
    page_candidate_frames = []
    table_candidate_frames = []
    table_cell_rows = []
    normalized_table_frames = []
    diagnostics_rows = []
    page_audit_rows = []
    statement_audit_files = 0
    text_extractable_pdfs = 0
    non_text_pdfs = 0

    for _, document in parse_targets.iterrows():
        if document["detected_file_type"] != "pdf":
            status_frames.append(
                pd.DataFrame(
                    [_failed_parse_row(document, "TABLE_EXTRACTION_FAILED", "XLSX_XLS_PARSE_NOT_IMPLEMENTED_YET", patch_label="01if_patch3")],
                    columns=PATCH3_CANDIDATE_COLUMNS,
                )
            )
            continue
        extraction = extract_pdf_with_python_backends(
            document["local_path"],
            max_pages=args.max_pages_per_document,
            use_table_extraction=False,
        )
        pages = extraction.pages
        diagnostics_rows.extend(build_python_pdf_diagnostic_rows(document_row=document, diagnostics=extraction.diagnostics))
        page_audit_rows.extend(build_python_page_text_audit_rows(document_row=document, pages=pages))
        has_text = any(getattr(page, "extraction_status", "") == "TEXT_EXTRACTED" for page in pages)
        if has_text:
            text_extractable_pdfs += 1
        else:
            non_text_pdfs += 1
            status_frames.append(
                pd.DataFrame(
                    [_failed_parse_row(document, "DOCUMENT_NOT_TEXT_EXTRACTABLE", "NO_TEXT_EXTRACTED_NO_OCR", patch_label="01if_patch3")],
                    columns=PATCH3_CANDIDATE_COLUMNS,
                )
            )

        page_candidates = build_statement_page_candidates(document_row=document, pages=pages)
        if not page_candidates.empty:
            page_candidate_frames.append(page_candidates)
        selected_pages = selected_statement_page_numbers(page_candidates)
        if not selected_pages:
            status_frames.append(
                pd.DataFrame(
                    [_failed_parse_row(document, "MANUAL_REVIEW_REQUIRED", "NO_FORMAL_STATEMENT_PAGE_SELECTED", patch_label="01if_patch3")],
                    columns=PATCH3_CANDIDATE_COLUMNS,
                )
            )
            if args.emit_markdown_audit:
                statement_audit_files += write_statement_audit_files(
                    document_row=document,
                    pages=pages,
                    page_candidates=page_candidates,
                    table_candidates=pd.DataFrame(columns=STATEMENT_TABLE_CANDIDATE_COLUMNS_01IF_PATCH3),
                    normalized_rows=[],
                    output_dir=output_dir,
                )
            continue
        page_text_hints = {int(page.page_number): str(page.text or "") for page in pages}
        table_cells, table_diagnostic = extract_pdfplumber_tables_for_pages(
            document["local_path"],
            selected_page_numbers=selected_pages,
            page_text_hints=page_text_hints,
        )
        diagnostics_rows.extend(build_python_pdf_diagnostic_rows(document_row=document, diagnostics=[table_diagnostic]))
        table_cell_rows.extend(build_python_table_cell_rows(document_row=document, table_cells=table_cells))
        table_candidates = build_statement_table_candidates(
            document_row=document,
            table_cells=table_cells,
            page_candidates=page_candidates,
        )
        if not table_candidates.empty:
            table_candidate_frames.append(table_candidates)
        selected_cells = filter_cells_to_selected_statement_tables(table_cells, table_candidates)
        if not selected_cells:
            status_frames.append(
                pd.DataFrame(
                    [_failed_parse_row(document, "TABLE_EXTRACTION_FAILED", "NO_STATEMENT_TABLE_SELECTED_FOR_VALUE_PARSE", patch_label="01if_patch3")],
                    columns=PATCH3_CANDIDATE_COLUMNS,
                )
            )
        normalized_rows, normalized_frame = normalize_finance_table_rows(
            document_row=document,
            pages=pages,
            table_cells=selected_cells,
        )
        if not normalized_frame.empty:
            normalized_table_frames.append(normalized_frame)
        usable, status = parse_patch3_statement_rows(
            document_row=document,
            normalized_rows=normalized_rows,
            table_candidates=table_candidates,
        )
        if not usable.empty:
            candidate_frames.append(usable)
        if not status.empty:
            status_frames.append(status)
        if args.emit_markdown_audit:
            statement_audit_files += write_statement_audit_files(
                document_row=document,
                pages=pages,
                page_candidates=page_candidates,
                table_candidates=table_candidates,
                normalized_rows=normalized_rows,
                output_dir=output_dir,
            )

    candidate_rows = (
        pd.concat(candidate_frames, ignore_index=True)[PATCH3_CANDIDATE_COLUMNS]
        if candidate_frames
        else pd.DataFrame(columns=PATCH3_CANDIDATE_COLUMNS)
    )
    status_rows = (
        pd.concat(status_frames, ignore_index=True)[PATCH3_CANDIDATE_COLUMNS]
        if status_frames
        else pd.DataFrame(columns=PATCH3_CANDIDATE_COLUMNS)
    )
    page_candidates = (
        pd.concat(page_candidate_frames, ignore_index=True)[STATEMENT_PAGE_CANDIDATE_COLUMNS_01IF_PATCH3]
        if page_candidate_frames
        else pd.DataFrame(columns=STATEMENT_PAGE_CANDIDATE_COLUMNS_01IF_PATCH3)
    )
    table_candidates = (
        pd.concat(table_candidate_frames, ignore_index=True)[STATEMENT_TABLE_CANDIDATE_COLUMNS_01IF_PATCH3]
        if table_candidate_frames
        else pd.DataFrame(columns=STATEMENT_TABLE_CANDIDATE_COLUMNS_01IF_PATCH3)
    )
    normalized_table_rows = (
        pd.concat(normalized_table_frames, ignore_index=True)[NORMALIZED_TABLE_ROW_COLUMNS_01IF_PATCH2]
        if normalized_table_frames
        else pd.DataFrame(columns=NORMALIZED_TABLE_ROW_COLUMNS_01IF_PATCH2)
    )
    diagnostics = pd.DataFrame(diagnostics_rows, columns=PDF_EXTRACTION_DIAGNOSTIC_COLUMNS_01IF_PATCH2)
    page_audit = pd.DataFrame(page_audit_rows, columns=PAGE_TEXT_AUDIT_COLUMNS_01IF_PATCH2)
    table_cells = pd.DataFrame(table_cell_rows, columns=TABLE_CELL_COLUMNS_01IF_PATCH2)
    coverage = build_field_coverage(selected_documents=selected_documents, candidate_rows=candidate_rows, status_rows=status_rows)
    unresolved = build_unresolved_fields(selected_documents=selected_documents, candidate_rows=candidate_rows, coverage=coverage, status_rows=status_rows)
    manual = build_parse_manual_review_queue(
        selected_documents=selected_documents,
        candidate_rows=candidate_rows,
        coverage=coverage,
        unresolved_fields=unresolved,
        status_rows=status_rows,
    )

    candidate_rows.to_csv(output_dir / "official_finance_candidate_rows_01if_patch3.csv", index=False)
    status_rows.to_csv(output_dir / "official_finance_parse_status_rows_01if_patch3.csv", index=False)
    coverage.to_csv(output_dir / "official_finance_field_coverage_01if_patch3.csv", index=False)
    unresolved.to_csv(output_dir / "official_finance_unresolved_fields_01if_patch3.csv", index=False)
    manual.to_csv(output_dir / "manual_review_queue.csv", index=False)
    backend_availability.to_csv(output_dir / "pdf_backend_availability_01if_patch3.csv", index=False)
    diagnostics.to_csv(output_dir / "pdf_extraction_diagnostics_01if_patch3.csv", index=False)
    page_audit.to_csv(output_dir / "official_finance_page_text_audit_01if_patch3.csv", index=False)
    table_cells.to_csv(output_dir / "official_finance_table_cells_01if_patch3.csv", index=False)
    normalized_table_rows.to_csv(output_dir / "official_finance_normalized_table_rows_01if_patch3.csv", index=False)
    page_candidates.to_csv(output_dir / "statement_page_candidates_01if_patch3.csv", index=False)
    table_candidates.to_csv(output_dir / "statement_table_candidates_01if_patch3.csv", index=False)
    (output_dir / "datasource_decision_report.md").write_text(
        build_patch3_decision_report(
            selected_documents=selected_documents,
            candidate_rows=candidate_rows,
            backend_availability=backend_availability,
            page_candidates=page_candidates,
            table_candidates=table_candidates,
        ),
        encoding="utf-8",
    )
    (output_dir / "official_finance_parse_01if_patch3_run_summary.md").write_text(
        build_patch3_run_summary(
            command=command,
            selected_documents=selected_documents,
            candidate_rows=candidate_rows,
            status_rows=status_rows,
            coverage=coverage,
            manual=manual,
            diagnostics=diagnostics,
            page_candidates=page_candidates,
            table_candidates=table_candidates,
            table_cells=table_cells,
            statement_audit_files=statement_audit_files,
            text_extractable_pdfs=text_extractable_pdfs,
            non_text_pdfs=non_text_pdfs,
        ),
        encoding="utf-8",
    )
    print_summary(args, selected_documents, candidate_rows, coverage, manual, text_extractable_pdfs, non_text_pdfs)
    return 0


def run_patch3_patch2_numeric_table_dump(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    selected_documents: pd.DataFrame,
    command: str,
) -> int:
    parse_targets = selected_documents[selected_documents["selection_status"] == "SELECTED_FOR_PARSE"].copy()
    if args.max_documents:
        parse_targets = parse_targets.head(args.max_documents)
    if parse_targets.empty and not args.allow_partial:
        raise SystemExit("No documents selected for numeric table dump. Pass --allow-partial to write reports only.")

    backend_availability = pd.DataFrame(
        build_pdf_backend_availability_rows(get_pdf_backend_availability()),
        columns=PDF_BACKEND_AVAILABILITY_COLUMNS_01IF_PATCH2,
    )
    page_candidate_frames = []
    table_candidate_frames = []
    table_cell_frames = []
    table_row_frames = []
    dump_index_frames = []
    candidate_frames = []
    status_frames = []
    diagnostics_rows = []
    text_extractable_pdfs = 0
    non_text_pdfs = 0
    audit_files = 0

    for _, document in parse_targets.iterrows():
        if document["detected_file_type"] != "pdf":
            status_frames.append(
                pd.DataFrame(
                    [_numeric_dump_status_row(document, "TABLE_EXTRACTION_FAILED", "XLSX_XLS_PARSE_NOT_IMPLEMENTED_YET")],
                    columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF,
                )
            )
            continue

        extraction = extract_pdf_with_python_backends(
            document["local_path"],
            max_pages=args.max_pages_per_document,
            use_table_extraction=False,
        )
        pages = extraction.pages
        diagnostics_rows.extend(build_python_pdf_diagnostic_rows(document_row=document, diagnostics=extraction.diagnostics))
        has_text = any(getattr(page, "extraction_status", "") == "TEXT_EXTRACTED" for page in pages)
        if has_text:
            text_extractable_pdfs += 1
        else:
            non_text_pdfs += 1
            status_frames.append(
                pd.DataFrame(
                    [_numeric_dump_status_row(document, "DOCUMENT_NOT_TEXT_EXTRACTABLE", "NO_TEXT_EXTRACTED_NO_OCR")],
                    columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF,
                )
            )

        page_text_hints = {int(page.page_number): str(page.text or "") for page in pages if int(page.page_number or 0)}
        preliminary_pages = build_numeric_page_candidates(document_row=document, pages=pages)
        preliminary_selected_pages = selected_numeric_page_numbers(preliminary_pages)
        page_limit = extraction.page_count or len([page for page in pages if int(page.page_number or 0)])
        if args.max_pages_per_document and page_limit:
            page_limit = min(page_limit, args.max_pages_per_document)
        target_pages = set(range(1, page_limit + 1)) if page_limit else preliminary_selected_pages
        table_cells, table_diagnostic = extract_pdfplumber_all_tables_for_pages(
            document["local_path"],
            selected_page_numbers=target_pages,
            page_text_hints=page_text_hints,
        )
        diagnostics_rows.extend(build_python_pdf_diagnostic_rows(document_row=document, diagnostics=[table_diagnostic]))
        if not table_cells and preliminary_selected_pages:
            table_cells = build_line_fallback_table_cells(
                pages=pages,
                selected_page_numbers=preliminary_selected_pages,
            )

        frames = build_numeric_table_dump_frames(
            document_row=document,
            pages=pages,
            table_cells=table_cells,
        )
        if not frames.page_candidates.empty:
            page_candidate_frames.append(frames.page_candidates)
        if not frames.table_candidates.empty:
            table_candidate_frames.append(frames.table_candidates)
        if not frames.table_cells.empty:
            table_cell_frames.append(frames.table_cells)
        if not frames.table_rows.empty:
            table_row_frames.append(frames.table_rows)
        if not frames.dump_index.empty:
            dump_index_frames.append(frames.dump_index)
        if not frames.candidate_rows.empty:
            candidate_frames.append(frames.candidate_rows)
        if not frames.status_rows.empty:
            status_frames.append(frames.status_rows)

        selected_pages = selected_numeric_page_numbers(frames.page_candidates)
        dumped_tables = int(len(frames.dump_index))
        if not selected_pages:
            status_frames.append(
                pd.DataFrame(
                    [_numeric_dump_status_row(document, "MANUAL_REVIEW_REQUIRED", "NO_NUMERIC_HEAVY_PAGES_FOUND")],
                    columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF,
                )
            )
        if selected_pages and not dumped_tables:
            status_frames.append(
                pd.DataFrame(
                    [_numeric_dump_status_row(document, "TABLE_EXTRACTION_UNAVAILABLE", "NO_TABLES_EXTRACTED_FROM_NUMERIC_PAGES")],
                    columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF,
                )
            )
        if dumped_tables and frames.candidate_rows.empty:
            status_frames.append(
                pd.DataFrame(
                    [_numeric_dump_status_row(document, "MANUAL_REVIEW_REQUIRED", "TABLE_DUMP_ONLY_NOT_SEMANTICALLY_PARSED")],
                    columns=OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF,
                )
            )
        audit_files += write_numeric_audit_files(
            document_row=document,
            pages=pages,
            page_candidates=frames.page_candidates,
            table_candidates=frames.table_candidates,
            table_rows=frames.table_rows,
            output_dir=output_dir,
        )

    page_candidates = _concat_or_empty(page_candidate_frames, NUMERIC_PAGE_CANDIDATE_COLUMNS_01IF_PATCH3_PATCH2)
    table_candidates = _concat_or_empty(table_candidate_frames, NUMERIC_TABLE_CANDIDATE_COLUMNS_01IF_PATCH3_PATCH2)
    table_cells = _concat_or_empty(table_cell_frames, NUMERIC_TABLE_CELL_COLUMNS_01IF_PATCH3_PATCH2)
    table_rows = _concat_or_empty(table_row_frames, NUMERIC_TABLE_ROW_COLUMNS_01IF_PATCH3_PATCH2)
    dump_index = _concat_or_empty(dump_index_frames, NUMERIC_TABLE_DUMP_INDEX_COLUMNS_01IF_PATCH3_PATCH2)
    candidate_rows = _concat_or_empty(candidate_frames, OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF)
    status_rows = _concat_or_empty(status_frames, OFFICIAL_FINANCE_CANDIDATE_ROW_COLUMNS_01IF)
    diagnostics = pd.DataFrame(diagnostics_rows, columns=PDF_EXTRACTION_DIAGNOSTIC_COLUMNS_01IF_PATCH2)
    coverage_input = coverage_candidate_rows(candidate_rows)
    coverage = build_field_coverage(selected_documents=selected_documents, candidate_rows=coverage_input, status_rows=status_rows)
    unresolved = build_unresolved_fields(selected_documents=selected_documents, candidate_rows=coverage_input, coverage=coverage, status_rows=status_rows)
    manual = build_parse_manual_review_queue(
        selected_documents=selected_documents,
        candidate_rows=coverage_input,
        coverage=coverage,
        unresolved_fields=unresolved,
        status_rows=status_rows,
    )

    page_candidates.to_csv(output_dir / "numeric_page_candidates_01if_patch3_patch2.csv", index=False)
    table_candidates.to_csv(output_dir / "numeric_table_candidates_01if_patch3_patch2.csv", index=False)
    table_cells.to_csv(output_dir / "numeric_table_cells_01if_patch3_patch2.csv", index=False)
    table_rows.to_csv(output_dir / "numeric_table_rows_01if_patch3_patch2.csv", index=False)
    dump_index.to_csv(output_dir / "numeric_table_dump_index_01if_patch3_patch2.csv", index=False)
    candidate_rows.to_csv(output_dir / "official_finance_candidate_rows_01if_patch3_patch2.csv", index=False)
    status_rows.to_csv(output_dir / "official_finance_parse_status_rows_01if_patch3_patch2.csv", index=False)
    coverage.to_csv(output_dir / "official_finance_field_coverage_01if_patch3_patch2.csv", index=False)
    unresolved.to_csv(output_dir / "official_finance_unresolved_fields_01if_patch3_patch2.csv", index=False)
    manual.to_csv(output_dir / "manual_review_queue.csv", index=False)
    backend_availability.to_csv(output_dir / "pdf_backend_availability_01if_patch3_patch2.csv", index=False)
    diagnostics.to_csv(output_dir / "pdf_extraction_diagnostics_01if_patch3_patch2.csv", index=False)
    (output_dir / "datasource_decision_report.md").write_text(
        build_patch3_patch2_decision_report(
            selected_documents=selected_documents,
            candidate_rows=candidate_rows,
            backend_availability=backend_availability,
            page_candidates=page_candidates,
            dump_index=dump_index,
            table_cells=table_cells,
            table_rows=table_rows,
        ),
        encoding="utf-8",
    )
    (output_dir / "official_finance_parse_01if_patch3_patch2_run_summary.md").write_text(
        build_patch3_patch2_run_summary(
            command=command,
            selected_documents=selected_documents,
            candidate_rows=candidate_rows,
            status_rows=status_rows,
            coverage=coverage,
            manual=manual,
            diagnostics=diagnostics,
            page_candidates=page_candidates,
            table_candidates=table_candidates,
            table_cells=table_cells,
            table_rows=table_rows,
            dump_index=dump_index,
            audit_files=audit_files,
            text_extractable_pdfs=text_extractable_pdfs,
            non_text_pdfs=non_text_pdfs,
        ),
        encoding="utf-8",
    )
    print_numeric_dump_summary(
        args,
        selected_documents,
        candidate_rows,
        page_candidates,
        dump_index,
        table_cells,
        table_rows,
        manual,
        text_extractable_pdfs,
        non_text_pdfs,
    )
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


def build_patch3_decision_report(
    *,
    selected_documents: pd.DataFrame,
    candidate_rows: pd.DataFrame,
    backend_availability: pd.DataFrame,
    page_candidates: pd.DataFrame,
    table_candidates: pd.DataFrame,
) -> str:
    selected_count = int((selected_documents["selection_status"] == "SELECTED_FOR_PARSE").sum()) if not selected_documents.empty else 0
    usable_count = int(len(candidate_rows))
    tickers_with_parse = int(candidate_rows["ticker"].nunique()) if not candidate_rows.empty else 0
    backend_ready = _backend_ready(backend_availability)
    selected_pages = int(page_candidates["selected_for_table_extraction"].astype(bool).sum()) if not page_candidates.empty else 0
    selected_tables = int(table_candidates["selected_for_value_parse"].astype(bool).sum()) if not table_candidates.empty else 0
    return "\n".join(
        [
            "# Datasource decision report",
            "",
            f"- official_document_file_ready: {'True' if selected_count else 'False'}",
            f"- pdf_python_backend_ready: {backend_ready}",
            f"- statement_page_targeting_ready: {'True' if selected_pages else 'False'}",
            f"- statement_tables_isolated: {'True' if selected_tables else 'False'}",
            f"- official_finance_parse_ready: {'Partial' if usable_count else 'False'}",
            f"- usable_official_finance_candidate_rows: {usable_count}",
            f"- tickers_with_usable_official_parse: {tickers_with_parse}",
            f"- finance_ready_for_l0: {'Partial' if usable_count else 'unchanged'}",
            "- finance_disclosure_ready_for_step18: False",
            "- should_run_REAL_DATA_02: No",
            "- should_implement_Step19_now: No",
            "",
            "PATCH3 targets formal statement pages and does not treat downloaded PDFs, HTTPS links, labels, or rejected tables as finance values.",
        ]
    )


def build_patch3_run_summary(
    *,
    command: str,
    selected_documents: pd.DataFrame,
    candidate_rows: pd.DataFrame,
    status_rows: pd.DataFrame,
    coverage: pd.DataFrame,
    manual: pd.DataFrame,
    diagnostics: pd.DataFrame,
    page_candidates: pd.DataFrame,
    table_candidates: pd.DataFrame,
    table_cells: pd.DataFrame,
    statement_audit_files: int,
    text_extractable_pdfs: int,
    non_text_pdfs: int,
) -> str:
    selected_count = int((selected_documents["selection_status"] == "SELECTED_FOR_PARSE").sum()) if not selected_documents.empty else 0
    selected_pages = int(page_candidates["selected_for_table_extraction"].astype(bool).sum()) if not page_candidates.empty else 0
    selected_tables = int(table_candidates["selected_for_value_parse"].astype(bool).sum()) if not table_candidates.empty else 0
    return "\n".join(
        [
            "# REAL-DATA-01I-F-PATCH3 statement page targeting parse run",
            "",
            "## Command run",
            f"`{command}`",
            "",
            "## Documents selected",
            str(selected_count),
            "",
            "## Text-extractable PDFs",
            str(text_extractable_pdfs),
            "",
            "## Non-text/scanned PDFs",
            str(non_text_pdfs),
            "",
            "## Statement pages selected",
            str(selected_pages),
            "",
            "## Statement tables isolated",
            str(selected_tables),
            "",
            "## Table cells extracted from selected pages",
            str(len(table_cells)),
            "",
            "## Usable candidate rows",
            str(len(candidate_rows)),
            "",
            "## Status/error rows separated",
            str(len(status_rows)),
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
            str(len(manual)),
            "",
            "## Extraction diagnostics",
            _format_grouped_counts(diagnostics, ["backend", "extract_status"]),
            "",
            "## Main blockers",
            _format_counts(_counts(manual, "issue")),
            "",
            "## Audit files",
            str(statement_audit_files),
            "",
            "## Next recommended action",
            "Do not run REAL-DATA-02 or Step19. Review statement page/table audit outputs and look for cleaner official XLSX/text PDFs if usable rows remain insufficient.",
        ]
    )


def build_patch3_patch2_decision_report(
    *,
    selected_documents: pd.DataFrame,
    candidate_rows: pd.DataFrame,
    backend_availability: pd.DataFrame,
    page_candidates: pd.DataFrame,
    dump_index: pd.DataFrame,
    table_cells: pd.DataFrame,
    table_rows: pd.DataFrame,
) -> str:
    selected_count = int((selected_documents["selection_status"] == "SELECTED_FOR_PARSE").sum()) if not selected_documents.empty else 0
    usable_count = int(len(candidate_rows))
    tickers_with_parse = int(candidate_rows["ticker"].nunique()) if not candidate_rows.empty else 0
    numeric_pages = _numeric_pages_selected(page_candidates)
    numeric_tables = int(len(dump_index))
    return "\n".join(
        [
            "# Datasource decision report",
            "",
            f"- official_document_file_ready: {'True' if selected_count else 'False'}",
            f"- pdf_python_backend_ready: {_backend_ready(backend_availability)}",
            f"- numeric_table_dump_ready: {'True' if numeric_tables else 'False'}",
            f"- strict_finance_candidate_rows_ready: {'True' if usable_count else 'False'}",
            f"- official_finance_parse_ready: {'Partial' if usable_count else 'False'}",
            f"- usable_official_finance_candidate_rows: {usable_count}",
            f"- tickers_with_usable_official_parse: {tickers_with_parse}",
            f"- numeric_tables_dumped: {numeric_tables}",
            f"- numeric_pages_selected: {numeric_pages}",
            f"- numeric_table_cells_exported: {len(table_cells)}",
            f"- numeric_table_rows_exported: {len(table_rows)}",
            "- finance_disclosure_ready_for_step18: False",
            "- should_run_REAL_DATA_02: No",
            "- should_implement_Step19_now: No",
            "",
            "PATCH3-PATCH2 dumps numeric-heavy tables as raw evidence only. A dumped table is not treated as a confirmed finance field.",
        ]
    )


def build_patch3_patch2_run_summary(
    *,
    command: str,
    selected_documents: pd.DataFrame,
    candidate_rows: pd.DataFrame,
    status_rows: pd.DataFrame,
    coverage: pd.DataFrame,
    manual: pd.DataFrame,
    diagnostics: pd.DataFrame,
    page_candidates: pd.DataFrame,
    table_candidates: pd.DataFrame,
    table_cells: pd.DataFrame,
    table_rows: pd.DataFrame,
    dump_index: pd.DataFrame,
    audit_files: int,
    text_extractable_pdfs: int,
    non_text_pdfs: int,
) -> str:
    selected_count = int((selected_documents["selection_status"] == "SELECTED_FOR_PARSE").sum()) if not selected_documents.empty else 0
    return "\n".join(
        [
            "# REAL-DATA-01I-F-PATCH3-PATCH2 numeric table dump run",
            "",
            "## Command run",
            f"`{command}`",
            "",
            "## Documents selected",
            str(selected_count),
            "",
            "## Text-extractable PDFs",
            str(text_extractable_pdfs),
            "",
            "## Non-text/scanned PDFs",
            str(non_text_pdfs),
            "",
            "## Numeric pages selected",
            str(_numeric_pages_selected(page_candidates)),
            "",
            "## Numeric tables dumped",
            str(len(dump_index)),
            "",
            "## Raw table cells exported",
            str(len(table_cells)),
            "",
            "## Raw table rows exported",
            str(len(table_rows)),
            "",
            "## Strict usable candidate rows",
            str(len(candidate_rows)),
            "",
            "## Status/error rows separated",
            str(len(status_rows)),
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
            str(len(manual)),
            "",
            "## Extraction diagnostics",
            _format_grouped_counts(diagnostics, ["backend", "extract_status"]),
            "",
            "## Table statuses",
            _format_counts(_counts(table_candidates, "table_status")),
            "",
            "## Main blockers",
            _format_counts(_counts(manual, "issue")),
            "",
            "## Top dumped table examples",
            _format_dump_examples(dump_index),
            "",
            "## Audit files",
            str(audit_files),
            "",
            "## Next recommended action",
            "Do not run REAL-DATA-02 or Step19. Use numeric table dump evidence to improve semantic row/period/unit mapping or find cleaner official XLSX/text documents.",
        ]
    )


def print_numeric_dump_summary(
    args: argparse.Namespace,
    selected_documents: pd.DataFrame,
    candidate_rows: pd.DataFrame,
    page_candidates: pd.DataFrame,
    dump_index: pd.DataFrame,
    table_cells: pd.DataFrame,
    table_rows: pd.DataFrame,
    manual: pd.DataFrame,
    text_extractable_pdfs: int,
    non_text_pdfs: int,
) -> None:
    selected_count = int((selected_documents["selection_status"] == "SELECTED_FOR_PARSE").sum()) if not selected_documents.empty else 0
    print(
        {
            "output_dir": args.output_dir,
            "documents_selected": selected_count,
            "text_extractable_pdfs": text_extractable_pdfs,
            "scanned_unextractable_pdfs": non_text_pdfs,
            "numeric_pages_selected": _numeric_pages_selected(page_candidates),
            "numeric_tables_dumped": int(len(dump_index)),
            "numeric_table_cells": int(len(table_cells)),
            "numeric_table_rows": int(len(table_rows)),
            "strict_usable_finance_candidate_rows": int(len(candidate_rows)),
            "manual_review_rows": int(len(manual)),
            "numeric_table_dump_ready": bool(len(dump_index)),
            "finance_parse_ready": "Partial" if len(candidate_rows) else False,
            "should_run_REAL_DATA_02": "No",
            "should_implement_Step19_now": "No",
        }
    )


def _numeric_dump_status_row(document: pd.Series, status: str, reason: str) -> dict[str, Any]:
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
        "source_name": "official_numeric_table_dump_01if_patch3_patch2",
        "source_url": document.get("source_url", ""),
        "final_url": document.get("final_url", ""),
        "local_path": document.get("local_path", ""),
        "file_hash": document.get("file_hash", ""),
        "page_number": "",
        "table_index": "",
        "row_index": "",
        "raw_label": "",
        "raw_context": "",
        "parser_name": "numeric_table_dump_01if_patch3_patch2",
        "parse_status": status,
        "confidence_raw": "low",
        "manual_review_required": True,
        "review_reason": reason,
        "fetch_time": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "notes": "numeric table dump status; no OCR; no inferred or zero-filled values",
    }


def _failed_parse_row(document: pd.Series, status: str, reason: str, *, patch2_mode: bool = False, patch_label: str = "") -> dict[str, Any]:
    if patch_label == "01if_patch3":
        source_name = "official_statement_page_parser_01if_patch3"
        parser_name = "statement_page_targeter_01if_patch3"
        notes = "statement-page targeted parser; no OCR; no values inferred or fabricated"
    else:
        source_name = "official_python_pdf_parser_01if_patch2" if patch2_mode else "official_pdf_parser_01if"
        parser_name = "official_python_pdf_text_line_parser_01if_patch2" if patch2_mode else "official_pdf_text_line_parser_01if"
        notes = "no values inferred or fabricated"
    row = {
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
        "notes": notes,
    }
    if patch_label == "01if_patch3":
        row.update({"statement_type": "", "period_label": "", "parser_backend": ""})
    return row


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
    if "patch3_patch2" in lowered:
        return "_01if_patch3_patch2"
    if "patch3" in lowered:
        return "_01if_patch3"
    if "patch2" in lowered:
        return "_01if_patch2"
    if "patch1" in lowered:
        return "_01if_patch1"
    return "_01if"


def _backend_ready(backend_availability: pd.DataFrame) -> str:
    if not isinstance(backend_availability, pd.DataFrame) or backend_availability.empty:
        return "False"
    installed = {
        str(row.get("backend", "")): str(row.get("installed", "")).lower() in {"true", "1", "yes"}
        for _, row in backend_availability.iterrows()
    }
    return "True" if installed.get("pymupdf") and installed.get("pdfplumber") else "Partial" if any(installed.values()) else "False"


def _counts(df: pd.DataFrame, column: str) -> dict[str, int]:
    if not isinstance(df, pd.DataFrame) or df.empty or column not in df.columns:
        return {}
    return {str(key): int(value) for key, value in df[column].value_counts(dropna=False).items()}


def _concat_or_empty(frames: list[pd.DataFrame], columns: list[str]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame(columns=columns)
    return pd.concat(frames, ignore_index=True)[columns]


def _numeric_pages_selected(page_candidates: pd.DataFrame) -> int:
    if not isinstance(page_candidates, pd.DataFrame) or page_candidates.empty:
        return 0
    return int(
        page_candidates["candidate_status"]
        .astype(str)
        .isin(["SELECTED_NUMERIC_PAGE", "SELECTED_BY_TABLE_EVIDENCE"])
        .sum()
    )


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "- none"
    return "\n".join(f"- {key}: {value}" for key, value in counts.items())


def _format_dump_examples(dump_index: pd.DataFrame, *, limit: int = 5) -> str:
    if not isinstance(dump_index, pd.DataFrame) or dump_index.empty:
        return "- none"
    lines = []
    ordered = dump_index.sort_values(["numeric_cell_count", "numeric_cell_ratio"], ascending=False).head(limit)
    for _, row in ordered.iterrows():
        lines.append(
            f"- {row.get('ticker', '')} {row.get('period', '')} "
            f"p{row.get('page_number', '')} t{row.get('table_index', '')}: "
            f"cells={row.get('numeric_cell_count', '')}, ratio={row.get('numeric_cell_ratio', '')}, "
            f"source={row.get('local_path', '')}"
        )
    return "\n".join(lines)


def _format_coverage(coverage: pd.DataFrame) -> str:
    if not isinstance(coverage, pd.DataFrame) or coverage.empty:
        return "- none"
    return "\n".join(
        f"- {row['ticker']} {row['period']}: {row['coverage_status']} "
        f"(found={row['required_fields_found_count']}, missing={row['required_fields_missing_count']})"
        for _, row in coverage.iterrows()
    )


def _format_grouped_counts(df: pd.DataFrame, columns: list[str]) -> str:
    if not isinstance(df, pd.DataFrame) or df.empty or any(column not in df.columns for column in columns):
        return "- none"
    counts = df.groupby(columns, dropna=False).size().reset_index(name="count")
    return "\n".join(
        f"- {' '.join(str(row[column]) for column in columns)}: {int(row['count'])}"
        for _, row in counts.iterrows()
    )


def parse_csv(value: str) -> list[str]:
    return [item.strip().upper() for item in str(value or "").split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
