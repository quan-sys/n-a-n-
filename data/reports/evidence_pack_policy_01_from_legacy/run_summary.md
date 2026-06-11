# REAL-DATA-EVIDENCE-PACK-01 run summary

## Command
`python.exe scripts\run_evidence_pack_policy_01.py --input data\reports\provisional_evidence_ranking_01\provisional_ranked_shortlist.csv --output-dir data\reports\evidence_pack_policy_01_from_legacy`

## Input status
- ranked_input_status: LOADED:data\reports\provisional_evidence_ranking_01\provisional_ranked_shortlist.csv
- document_index_status: LOADED:data/reports/official_finance_documents_01ie/finance_document_index.csv
- template_only: False
- MISSING_RANKING_INPUT: No
- Ranking was used only to assign evidence workload stage, not an investment recommendation.

## Stage policy
- stage_0_full_universe: target_max_tickers=1743, official_files_per_ticker=0-0
- stage_1_provisional_shortlist: target_max_tickers=500, official_files_per_ticker=0-0
- stage_2_evidence_candidates: target_max_tickers=200, official_files_per_ticker=1-2
- stage_3_final_watchlist: target_max_tickers=50, official_files_per_ticker=2-3
- stage_4_deep_dive_shortlist: target_max_tickers=10, official_files_per_ticker=5-8
- stage_5_full_historical_research: target_max_tickers=3, official_files_per_ticker=10-15

## Required evidence per stage
- stage_0_full_universe: none
- stage_1_provisional_shortlist: none
- stage_2_evidence_candidates: P0_latest_consolidated_financial_statement, P1_latest_audited_annual_financial_statement
- stage_3_final_watchlist: P0_latest_consolidated_financial_statement, P1_latest_audited_annual_financial_statement, P2_latest_annual_report
- stage_4_deep_dive_shortlist: P0_latest_consolidated_financial_statement, P1_latest_audited_annual_financial_statement, P2_latest_annual_report, P3_same_period_previous_year_financial_statement, P4_three_year_audited_annual_statements
- stage_5_full_historical_research: P0_latest_consolidated_financial_statement, P1_latest_audited_annual_financial_statement, P2_latest_annual_report, P3_same_period_previous_year_financial_statement, P4_three_year_audited_annual_statements, P5_full_history

## Outputs
- candidate_stage_assignments.csv
- evidence_collection_queue.csv
- document_discovery_plan.csv
- manual_seed_requests.csv
- evidence_pack_status.csv
- evidence_workload_budget_estimate.csv
- data_readiness_gate.md
- run_summary.md

## Workload
- assignment_estimated_files_min: 280
- assignment_estimated_files_max: 500
- evidence_collection_queue_rows: 470
- stage_3_final_watchlist: estimated_files=100-150, manual_hours=3.33-12.5
- stage_4_deep_dive_shortlist: estimated_files=50-80, manual_hours=1.67-6.67
- stage_5_full_historical_research: estimated_files=30-45, manual_hours=1.0-3.75

## Why staged collection matters
- Collecting 10-15 official files for 20-50 names would mean roughly 200-750 files before parsing even starts.
- Stage 3 caps final-watchlist evidence at 2-3 files per ticker, keeping the initial official evidence pack to 40-150 files for a 20-50 name watchlist.
- Deep 5-8 file packs are reserved for 5-10 names, and 10-15 file history is reserved for 1-3 names.

## Evidence status counts
- NO_OFFICIAL_EVIDENCE_NEEDED_YET: 1600
- EVIDENCE_QUEUE_CREATED: 199
- MINIMUM_EVIDENCE_PACK_READY: 1

## Scope validation
- validation_issues: 0
- none

## Safety
- forbidden_buy_sell_target_columns: none
- REAL-DATA-02 remains blocked.
- Step19 remains blocked.
- This run did not fetch PDFs, OCR, infer values, zero-fill values, or create target price/buy/sell logic.

_Generated at 2026-06-11T00:50:54+00:00._