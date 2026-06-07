# REAL-DATA-01I-F-PATCH3 statement page targeting parse run

## Command run
`python.exe scripts\run_official_finance_parse_01if.py --input-document-index data\reports\official_finance_documents_01ie\finance_document_index.csv --output-dir data\reports\official_finance_parse_01if_patch3 --patch 01if_patch3 --statement-pages-only --emit-markdown-audit --allow-partial`

## Documents selected
20

## Text-extractable PDFs
8

## Non-text/scanned PDFs
12

## Statement pages selected
0

## Statement tables isolated
0

## Table cells extracted from selected pages
0

## Usable candidate rows
0

## Status/error rows separated
32

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
287

## Extraction diagnostics
- overall SCANNED_OR_IMAGE_ONLY_REVIEW: 12
- pdfplumber NO_TEXT_EXTRACTED: 14
- pdfplumber TEXT_EXTRACTED: 6
- pymupdf NO_TEXT_EXTRACTED: 12
- pymupdf TEXT_EXTRACTED: 8
- pypdf NO_TEXT_EXTRACTED: 14
- pypdf TEXT_EXTRACTED: 6

## Main blockers
- MANUAL_REVIEW_REQUIRED: 20
- SKIPPED_OLD_PERIOD: 19
- FIELD_NOT_FOUND:short_term_debt: 16
- FIELD_NOT_FOUND:total_liabilities: 16
- MISSING_REQUIRED_FIELDS: 16
- FIELD_NOT_FOUND:revenue: 16
- FIELD_NOT_FOUND:operating_profit: 16
- FIELD_NOT_FOUND:gross_profit: 16
- FIELD_NOT_FOUND:net_profit: 16
- FIELD_NOT_FOUND:total_assets: 16
- FIELD_NOT_FOUND:operating_cash_flow: 16
- FIELD_NOT_FOUND:long_term_debt: 16
- FIELD_NOT_FOUND:equity: 16
- FIELD_NOT_FOUND:cash: 16
- FIELD_NOT_FOUND:inventory: 16
- REVIEW_ONLY_STANDALONE: 15
- SKIPPED_UNSUPPORTED_FILE_TYPE: 13
- DOCUMENT_NOT_TEXT_EXTRACTABLE: 12

## Audit files
40

## Next recommended action
Do not run REAL-DATA-02 or Step19. Review statement page/table audit outputs and look for cleaner official XLSX/text PDFs if usable rows remain insufficient.