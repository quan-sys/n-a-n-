# REAL-DATA-01I-F-PATCH3-PATCH3 category-first run

## Command run
`python.exe scripts\run_official_finance_parse_01if.py --output-dir data\reports\official_finance_parse_01if_patch3_patch3`

## Documents downloaded / local parse targets
40

## Text-extractable PDFs
13

## Non-text/scanned PDFs
27

## Finance numeric pages selected
0

## Finance numeric tables selected
0

## Raw numeric table cells
0

## Raw numeric table rows
0

## Non-financial numeric table rows
0

## Strict usable candidate rows
0

## Status rows
67

## Table status counts
- NON_FINANCIAL_NUMERIC_TABLE: 28

## Rows by field
- none

## Extraction diagnostics
- overall SCANNED_OR_IMAGE_ONLY_REVIEW: 27
- pdfplumber NO_TEXT_EXTRACTED: 28
- pdfplumber TEXT_EXTRACTED: 12
- pdfplumber_numeric_table_dump NO_TABLES_EXTRACTED: 28
- pdfplumber_numeric_table_dump TABLES_EXTRACTED: 12
- pymupdf NO_TEXT_EXTRACTED: 27
- pymupdf TEXT_EXTRACTED: 13
- pypdf NO_TEXT_EXTRACTED: 28
- pypdf TEXT_EXTRACTED: 12

## Top rejected/non-financial table examples
- PVS 2025 p95 t1: status=NON_FINANCIAL_NUMERIC_TABLE, anchors=2, negative=0, reason=PAGE_NOT_FINANCE_NUMERIC_CANDIDATE
- PVS 2025 p95 t1: status=NON_FINANCIAL_NUMERIC_TABLE, anchors=2, negative=0, reason=PAGE_NOT_FINANCE_NUMERIC_CANDIDATE
- PVS 2025-Q1 p78 t1: status=NON_FINANCIAL_NUMERIC_TABLE, anchors=1, negative=0, reason=PAGE_NOT_FINANCE_NUMERIC_CANDIDATE
- PVS 2026-Q1 p118 t1: status=NON_FINANCIAL_NUMERIC_TABLE, anchors=1, negative=0, reason=PAGE_NOT_FINANCE_NUMERIC_CANDIDATE
- PVS 2025-Q2 p76 t1: status=NON_FINANCIAL_NUMERIC_TABLE, anchors=1, negative=0, reason=PAGE_NOT_FINANCE_NUMERIC_CANDIDATE

## Audit files
120

## Next recommended action
Do not run REAL-DATA-02 or Step19. Improve category source coverage and target true BCTC PDFs/XLSX before reconciliation.