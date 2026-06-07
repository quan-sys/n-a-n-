# REAL-DATA-01I-F official finance parse run

## Command run
`python.exe scripts\run_official_finance_parse_01if.py --document-index data\reports\official_finance_documents_01ie\finance_document_index.csv --output-dir data\reports\official_finance_parse_01if_patch2 --max-documents 40 --target-periods 2026-Q1,2025-Q4,2025,2025-Q3,2025-Q2 --use-python-pdf-backends --use-table-extraction --prefer-table-values --emit-markdown-audit --allow-partial`

## Backend availability
- pymupdf: installed 1.27.2.3
- pdfplumber: installed 0.11.9
- pypdf: installed 6.12.1

## Documents selected
20

## Documents parsed
0

## Extraction backend diagnostics
- overall SCANNED_OR_IMAGE_ONLY_REVIEW: 12
- pdfplumber NO_TEXT_EXTRACTED: 14
- pdfplumber TABLES_EXTRACTED: 6
- pymupdf NO_TEXT_EXTRACTED: 12
- pymupdf TEXT_EXTRACTED: 8
- pypdf NO_TEXT_EXTRACTED: 14
- pypdf TEXT_EXTRACTED: 6

## Documents skipped
55

## Text-extractable PDFs
3 -> 8

## Non-text/scanned PDFs
12

## Tables extracted
14

## Normalized table rows
40

## Markdown audit files
6

## Usable candidate rows
0

## Status/error rows separated
37

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
286

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
- TABLE_EXTRACTION_UNAVAILABLE: 14
- SKIPPED_UNSUPPORTED_FILE_TYPE: 13
- DOCUMENT_NOT_TEXT_EXTRACTABLE: 12
- FIELD_VALUE_AMBIGUOUS: 4
- FIELD_LABEL_AMBIGUOUS: 1

## Next recommended action
Do not run 01I-G yet; current official PDFs still lack explicit parseable label/value/unit rows under non-OCR extraction, so use manual review or find cleaner official XLSX/text PDFs before rerunning this parse step.