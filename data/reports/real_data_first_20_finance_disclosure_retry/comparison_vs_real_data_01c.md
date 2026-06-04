# Comparison vs REAL-DATA-01C

Baseline report folder: `data/reports/real_data_first_20_rerun/`

Current report folder: `data/reports/real_data_first_20_finance_disclosure_retry/`

## Command

```powershell
python scripts\run_first_20_real_data_dry_run.py --limit 20 --mode real --ticker-selection manual_list --ticker-list VCB,BID,CTG,MBB,ACB,HPG,HSG,VHM,KDH,NLG,SSI,VND,GAS,PVS,FPT,MWG,VGC,GMD,VHC,TCM --only-datasets financial_statement_summary,disclosure_status --finance-request-budget 120 --disclosure-request-budget 60 --request-sleep-seconds 3.2 --finance-max-retries 1 --disclosure-max-retries 1 --output-dir data\reports\real_data_first_20_finance_disclosure_retry --raw-output-dir data\raw --allow-partial
```

Equivalent flags were used in the existing dry-run script. No separate retry script existed.

## Coverage Comparison

| Metric | REAL-DATA-01C | REAL-DATA-01E | Result |
| --- | ---: | ---: | --- |
| finance rows | 6 | 20 | improved |
| finance ticker count | 6 | 20 | improved |
| finance missing required field count | 11 | 25 | worsened in aggregate because more partial rows were captured |
| disclosure rows | 0 | 0 | unchanged |
| disclosure ticker count | 0 | 0 | unchanged |
| disclosure unknown/unavailable count | 20 | 20 | unchanged |
| requests skipped due to budget | 62 | 0 | improved |
| rate limit errors | 0 | 0 | unchanged |
| dependency errors | 0 | 1 | worsened |
| Step 18 status | INSUFFICIENT_DATA_FOR_STEP18 | INSUFFICIENT_DATA_FOR_STEP18 | unchanged |

## Source Request Comparison

| Dataset | REAL-DATA-01C attempted/succeeded/failed/skipped | REAL-DATA-01E attempted/succeeded/failed/skipped | Notes |
| --- | --- | --- | --- |
| financial_statement_summary | 18 / 18 / 0 / 42 | 61 / 60 / 1 / 0 | 20 ticker rows now exist, but all rows remain partial/low confidence. |
| disclosure_status | 0 / 0 / 0 / 20 | 40 / 40 / 0 / 0 | Adapter attempted real requests; source returned no disclosure rows. |

## Finance Field Coverage

- finance_field_coverage rows: 20
- rows with total_assets: 20
- rows with total_liabilities: 20
- rows with equity: 20
- rows with revenue: 15
- rows with net_profit: 0
- rows with confidence_raw=low: 20
- total missing-field entries across coverage rows: 42

Missing financial fields remain blank. No missing values were filled or inferred.

## Disclosure Coverage

- disclosure_coverage_status rows: 20
- source_attempted=True rows: 20
- treated_as_clean=True rows: 0
- treated_as_clean=False rows: 20
- DISCLOSURE_DATA_UNAVAILABLE rows: 20

`source_request_summary.csv` shows 40 disclosure requests attempted and 0 requests skipped due to budget. The disclosure coverage file still uses a generic unavailable/budget warning string because no disclosure rows were returned, but the request tracker evidence shows the adapter was not skipped by budget in this run.

## Output Files

- `data/raw/financial_statement_summary_raw.csv`: 20 rows
- `data/raw/disclosure_status_raw.csv`: 0 rows
- `data/reports/real_data_first_20_finance_disclosure_retry/run_summary.md`
- `data/reports/real_data_first_20_finance_disclosure_retry/source_request_summary.csv`
- `data/reports/real_data_first_20_finance_disclosure_retry/source_adapter_status.csv`
- `data/reports/real_data_first_20_finance_disclosure_retry/finance_field_coverage.csv`
- `data/reports/real_data_first_20_finance_disclosure_retry/disclosure_coverage_status.csv`
- `data/reports/real_data_first_20_finance_disclosure_retry/failed_tickers.csv`
- `data/reports/real_data_first_20_finance_disclosure_retry/pipeline_errors.csv`

## Decision

Do not scale to REAL-DATA-02 yet.

Recommended option: Use manual CSV/XLSX templates for BCTC/disclosure before scaling.

Reason: finance coverage improved to 20 tickers but remains partial/low confidence, disclosure real requests were attempted but still produced 0 rows, and Step 18 remains insufficient.
