# REAL-DATA-01I-F-PATCH3-PATCH2 numeric table dump run

## Command run
`python.exe scripts\run_official_finance_parse_01if.py --input-index data\reports\official_finance_documents_01ie\finance_document_index.csv --output-dir data\reports\official_finance_parse_01if_patch3_patch2 --mode official-python-pdf --enable-statement-targeting --enable-numeric-table-dump --no-ocr --limit-documents 20 --allow-partial`

## Documents selected
20

## Text-extractable PDFs
8

## Non-text/scanned PDFs
12

## Numeric pages selected
10

## Numeric tables dumped
2

## Raw table cells exported
166

## Raw table rows exported
59

## Strict usable candidate rows
0

## Status/error rows separated
36

## Rows by field
- none

## Rows by ticker
- none

## Coverage by ticker/period
- FPT 2026-Q1: INSUFFICIENT_PARSE (found=0, missing=12)
- KDH 2026-Q1: INSUFFICIENT_PARSE (found=0, missing=12)
- NLG 2026-Q1: NO_TEXT_EXTRACTED (found=0, missing=12)
- SSI 2026-Q1: NO_TEXT_EXTRACTED (found=0, missing=12)
- NLG 2025-Q4: NO_TEXT_EXTRACTED (found=0, missing=12)
- PVS 2025-Q4: INSUFFICIENT_PARSE (found=0, missing=12)
- SSI 2025-Q4: NO_TEXT_EXTRACTED (found=0, missing=12)
- PVS 2025: NO_TEXT_EXTRACTED (found=0, missing=12)
- PVS 2025: INSUFFICIENT_PARSE (found=0, missing=12)
- PVS 2025: INSUFFICIENT_PARSE (found=0, missing=12)
- NLG 2025-Q3: NO_TEXT_EXTRACTED (found=0, missing=12)
- PVS 2025-Q3: NO_TEXT_EXTRACTED (found=0, missing=12)
- SSI 2025-Q3: NO_TEXT_EXTRACTED (found=0, missing=12)
- NLG 2025-Q2: NO_TEXT_EXTRACTED (found=0, missing=12)
- PVS 2025-Q2: INSUFFICIENT_PARSE (found=0, missing=12)
- PVS 2026-Q1: INSUFFICIENT_PARSE (found=0, missing=12)
- NLG 2025: NO_TEXT_EXTRACTED (found=0, missing=12)
- NLG 2025: INSUFFICIENT_PARSE (found=0, missing=12)
- NLG 2025: NO_TEXT_EXTRACTED (found=0, missing=12)
- SSI 2025: NO_TEXT_EXTRACTED (found=0, missing=12)

## Manual review rows
288

## Extraction diagnostics
- overall SCANNED_OR_IMAGE_ONLY_REVIEW: 12
- pdfplumber NO_TEXT_EXTRACTED: 14
- pdfplumber TEXT_EXTRACTED: 6
- pdfplumber_numeric_table_dump NO_TABLES_EXTRACTED: 14
- pdfplumber_numeric_table_dump TABLES_EXTRACTED: 6
- pymupdf NO_TEXT_EXTRACTED: 12
- pymupdf TEXT_EXTRACTED: 8
- pypdf NO_TEXT_EXTRACTED: 14
- pypdf TEXT_EXTRACTED: 6

## Table statuses
- REJECTED_TABLE: 26
- DUMPED_RAW_EVIDENCE: 2

## Main blockers
- SKIPPED_OLD_PERIOD: 19
- FIELD_NOT_FOUND:gross_profit: 16
- FIELD_NOT_FOUND:operating_profit: 16
- MISSING_REQUIRED_FIELDS: 16
- FIELD_NOT_FOUND:short_term_debt: 16
- FIELD_NOT_FOUND:long_term_debt: 16
- FIELD_NOT_FOUND:operating_cash_flow: 16
- FIELD_NOT_FOUND:revenue: 16
- FIELD_NOT_FOUND:net_profit: 16
- FIELD_NOT_FOUND:equity: 16
- FIELD_NOT_FOUND:total_liabilities: 16
- FIELD_NOT_FOUND:total_assets: 16
- FIELD_NOT_FOUND:inventory: 16
- FIELD_NOT_FOUND:cash: 16
- REVIEW_ONLY_STANDALONE: 15
- MANUAL_REVIEW_REQUIRED: 15
- SKIPPED_UNSUPPORTED_FILE_TYPE: 13
- DOCUMENT_NOT_TEXT_EXTRACTABLE: 12
- TABLE_EXTRACTION_UNAVAILABLE: 5
- FIELD_VALUE_AMBIGUOUS: 1

## Top dumped table examples
- NLG 2025 p6 t3: cells=34, ratio=0.3864, source=data\raw\official_finance_documents\01ie\nlg_2025_financial_statement_f8546e950feec687.pdf
- NLG 2025 p11 t4: cells=5, ratio=0.0641, source=data\raw\official_finance_documents\01ie\nlg_2025_financial_statement_f8546e950feec687.pdf

## Audit files
40

## Next recommended action
Do not run REAL-DATA-02 or Step19. Use numeric table dump evidence to improve semantic row/period/unit mapping or find cleaner official XLSX/text documents.