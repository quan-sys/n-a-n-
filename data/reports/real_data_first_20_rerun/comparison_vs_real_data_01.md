# Comparison vs REAL-DATA-01

- current_run: REAL-DATA-01C rerun after source coverage fixes
- command: `python scripts\run_first_20_real_data_dry_run.py --limit 20 --mode real --ticker-selection representative --output-dir data\reports\real_data_first_20_rerun --raw-output-dir data\raw --allow-partial --real-source-max-requests 80 --request-sleep-seconds 3.2`
- step19_implemented: False
- mock_sample_used: False
- final_recommendation: Fix financial statement ingestion before scaling

## Ticker Selection

- REAL-DATA-01: first 20 from real universe source: DPP, SDA, CLH, DND, DBT, CCR, NOS, DPH, DSN, WSS, STC, CFM, VPG, DST, DCV, MBN, HPG, VGC, VCS, HT1
- REAL-DATA-01C: representative engineering coverage list: VCB, BID, CTG, MBB, ACB, HPG, HSG, VHM, KDH, NLG, SSI, VND, GAS, PVS, FPT, MWG, VGC, GMD, VHC, TCM

## Coverage Comparison

| Dataset | REAL-DATA-01 | REAL-DATA-01C | Change |
| --- | ---: | ---: | --- |
| universe rows | 20 | 20 | unchanged |
| universe ticker count | 20 | 20 | unchanged |
| company_profile rows | 20 | 20 | unchanged rows; coverage improved to VALID_DATA |
| company_profile failed ticker count | 20 | 0 | improved |
| market_price rows | 576 | 1340 | improved |
| market_price ticker count | 16 | 20 | improved |
| market_price failed ticker count | 4 | 0 | improved |
| financial_statement_summary rows | 0 | 6 | partial improvement |
| financial_statement_summary ticker count | 0 | 6 | partial improvement |
| financial_statement_summary failed ticker count | 20 | 20 | still blocker because rows are partial and 14 tickers remain unavailable |
| disclosure_status rows | 0 | 0 | no improvement |
| disclosure_status ticker count | 0 | 0 | no improvement |
| disclosure_status failed ticker count | 20 | 20 | still unavailable; missing disclosure is unknown, not clean |

## Pipeline Comparison

- REAL-DATA-01 run_status: INSUFFICIENT_DATA_FOR_STEP18
- REAL-DATA-01C run_status: INSUFFICIENT_DATA_FOR_STEP18
- REAL-DATA-01 manual review tickers: 20
- REAL-DATA-01C manual review tickers: 20
- REAL-DATA-01 failed_tickers.csv rows: 64
- REAL-DATA-01C failed_tickers.csv rows: 40
- REAL-DATA-01 sector cycle status: INSUFFICIENT_DATA_FOR_SECTOR_CYCLE for 20 tickers
- REAL-DATA-01C sector cycle status: INSUFFICIENT_DATA_FOR_SECTOR_CYCLE for 20 tickers

## Source And Rate Limit

- REAL-DATA-01 had rate-limit risk during early real-source attempts and no detailed source_request_summary report.
- REAL-DATA-01C source_request_summary.csv reports 0 rate_limit_errors.
- REAL-DATA-01C source_request_summary.csv reports 1 dependency_error on market_price: `ImportError: No charting library available. Please install one of:...`
- REAL-DATA-01C request budget was exhausted before disclosure requests: financial_statement_summary skipped 42 requests and disclosure_status skipped 20 requests.

## Decision

Do not proceed to REAL-DATA-02 medium run yet.

Required final decision from the prompt: **Fix financial statement ingestion before scaling**.

Reason: representative ticker selection fixed profile and market coverage, but financial statements are still only 6/20 tickers with partial fields and disclosure remains 0 rows. Step 18 still has insufficient sector-cycle data.
