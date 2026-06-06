# REAL-DATA-01IC official finance document seed run

## Command run
`python.exe scripts\run_official_finance_document_seed_01ib.py --seed-file data\seeds\official_finance_document_seed.real_20_initial_01ic.csv --output-dir data\reports\official_finance_documents_01ic --raw-output-dir data\raw\official_finance_documents\01ic --request-sleep-seconds 2.5 --timeout-seconds 25 --allow-partial`

## Seed rows loaded
42

## Valid seed rows
42

## Invalid seed rows
0

## Documents attempted
42

## Downloaded / HTML saved / failed / manual review
- dry-run validated: 0
- downloaded: 0
- html snapshots: 11
- blocked/js: 11
- failed: 20
- manual review: 31

## Rows by source_type
- company_ir: 42

## Rows by document_type
- ir_page: 22
- financial_statement: 19
- annual_report: 1

## Rows by status
- SOURCE_UNAVAILABLE: 20
- HTML_SNAPSHOT_SAVED: 11
- SOURCE_BLOCKED_OR_JS_REQUIRED: 11

## Main blockers
Official document infrastructure is ready for seed validation, but finance parsing is not implemented in 01I-B.

## Next recommended action
Populate a real source-backed seed CSV for 20 representative tickers, then run non-dry-run with a small max document limit.