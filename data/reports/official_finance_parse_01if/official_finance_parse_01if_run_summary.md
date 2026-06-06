# REAL-DATA-01I-F official finance parse run

## Command run
`python.exe scripts\run_official_finance_parse_01if.py --document-index data\reports\official_finance_documents_01ie\finance_document_index.csv --output-dir data\reports\official_finance_parse_01if --max-documents 40 --target-periods 2026-Q1,2025-Q4,2025,2025-Q3,2025-Q2 --allow-partial`

## Documents selected
20

## Documents parsed
18

## Documents skipped
55

## Text-extractable PDFs
3

## Non-text/scanned PDFs
17

## Candidate rows parsed
24

## Rows by field
- : 17
- revenue: 4
- net_profit: 2
- equity: 1

## Rows by ticker
- NLG: 13
- PVS: 5
- SSI: 4
- FPT: 1
- KDH: 1

## Coverage by ticker/period
- FPT 2026-Q1: NO_TEXT_EXTRACTED (found=0, missing=12)
- KDH 2026-Q1: NO_TEXT_EXTRACTED (found=0, missing=12)
- NLG 2026-Q1: NO_TEXT_EXTRACTED (found=0, missing=12)
- SSI 2026-Q1: NO_TEXT_EXTRACTED (found=0, missing=12)
- NLG 2025-Q4: NO_TEXT_EXTRACTED (found=0, missing=12)
- PVS 2025-Q4: NO_TEXT_EXTRACTED (found=0, missing=12)
- SSI 2025-Q4: NO_TEXT_EXTRACTED (found=0, missing=12)
- PVS 2025: NO_TEXT_EXTRACTED (found=0, missing=12)
- PVS 2025: NO_TEXT_EXTRACTED (found=0, missing=12)
- PVS 2025: NO_TEXT_EXTRACTED (found=0, missing=12)
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
273

## Main blockers
- SKIPPED_OLD_PERIOD: 19
- DOCUMENT_NOT_TEXT_EXTRACTABLE: 17
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
- FIELD_VALUE_AMBIGUOUS: 1

## Next recommended action
Review parser evidence and unresolved fields, then implement 01I-G reconciliation before any broader scale-up.