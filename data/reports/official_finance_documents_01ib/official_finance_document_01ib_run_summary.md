# REAL-DATA-01I-B official finance document seed run

## Command run
`python.exe scripts\run_official_finance_document_seed_01ib.py --seed-file data\seeds\official_finance_document_seed.example.csv --output-dir data\reports\official_finance_documents_01ib --raw-output-dir data\raw\official_finance_documents\01ib --dry-run --allow-partial`

## Seed rows loaded
2

## Valid seed rows
2

## Invalid seed rows
0

## Documents attempted
0

## Downloaded / HTML saved / failed / manual review
- downloaded: 2
- html snapshots: 0
- failed: 0
- manual review: 0

## Rows by source_type
- exchange_filing: 1
- company_ir: 1

## Rows by document_type
- financial_statement: 1
- annual_report: 1

## Rows by status
- DOWNLOADED: 2

## Main blockers
Official document infrastructure is ready for seed validation, but finance parsing is not implemented in 01I-B.

## Next recommended action
Populate a real source-backed seed CSV for 20 representative tickers, then run non-dry-run with a small max document limit.