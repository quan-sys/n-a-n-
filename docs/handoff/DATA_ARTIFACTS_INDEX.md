# Data Artifacts Index

This index summarizes important committed artifacts for the current `codex/vietnam-stock-pipeline` branch. Large CSVs are referenced by path and row count only; do not paste raw 1,743-row universe files into ChatGPT.

## Paste Policy

| Artifact type | Paste into ChatGPT? | Notes |
|---|---|---|
| Handoff Markdown files | Yes | These files are compact and safe for continuation. |
| Summary JSON files | Sometimes | Paste selected fields only when debugging counts or status. |
| Large CSVs | No | Reference path, row count, key columns, and a tiny sample only if needed. |
| Raw cache | No | Keep raw cache uncommitted and out of handoff context. |
| Config/script/source/test paths | Reference only | Use repo paths and commit IDs. |

## Step Commit Map

| Step | Commit |
|---|---:|
| STEP05A | `169e1f721de21b9fc49255e7c222c79371e5bf81` |
| STEP20 | `50e6d57e288306d8fcf205a50239b9126383256b` |
| STEP21 | `374a23b53662aceed9f6ba7d4f6e25546b3cc760` |
| STEP22 | `eff8b25c174ce7a708ebe3ab7cd3858996755acf` |
| STEP23 | `196ea51cf4b1f71f47ee34834e41464d9c96841b` |
| STEP24 | `5a5199b0dd71e27695db03e1ae6e27b9b88b8e17` |
| STEP25 | `d99fb24001c809fa205e015ce9b9ed6cb7b8ede8` |
| STEP26 | `15e41c68124dcbe134bf67025110a6d418626005` |
| STEP27 | `85aad9f80e26f84de8983f33dc21ac4cbba0f7ab` |
| STEP28 | `820ae4f6a6b4d87e2668e101ef4da0bc5e705b6f` |

## Code Artifacts

| Step | Type | Path | Commit | Paste? |
|---|---|---|---:|---|
| STEP05A | config | `config/step05a_primary_only_screening.yaml` | `169e1f7` | Reference |
| STEP05A | script | `scripts/run_step05a_primary_only_screening.py` | `169e1f7` | Reference |
| STEP05A | source | `src/screening/step05a_primary_only_screening.py` | `169e1f7` | Reference |
| STEP05A | test | `tests/test_step05a_primary_only_screening.py` | `169e1f7` | Reference |
| STEP20 | config | `config/step20_l5_valuation_risk_context.yaml` | `50e6d57` | Reference |
| STEP20 | script | `scripts/run_step20_l5_valuation_risk_context.py` | `50e6d57` | Reference |
| STEP20 | source | `src/screening/step20_l5_valuation_risk_context.py` | `50e6d57` | Reference |
| STEP20 | test | `tests/test_step20_l5_valuation_risk_context.py` | `50e6d57` | Reference |
| STEP21 | config | `config/step21_l6_timing_liquidity_context.yaml` | `374a23b` | Reference |
| STEP21 | script | `scripts/run_step21_l6_timing_liquidity_context.py` | `374a23b` | Reference |
| STEP21 | source | `src/screening/step21_l6_timing_liquidity_context.py` | `374a23b` | Reference |
| STEP21 | test | `tests/test_step21_l6_timing_liquidity_context.py` | `374a23b` | Reference |
| STEP22 | config | `config/step22_l7_weekly_report_manual_review.yaml` | `eff8b25` | Reference |
| STEP22 | script | `scripts/run_step22_l7_weekly_report_manual_review.py` | `eff8b25` | Reference |
| STEP22 | source | `src/reporting/step22_l7_weekly_report_manual_review.py` | `eff8b25` | Reference |
| STEP22 | test | `tests/test_step22_l7_weekly_report_manual_review.py` | `eff8b25` | Reference |
| STEP23 | config | `config/step23_backtest_monitoring_module.yaml` | `196ea51` | Reference |
| STEP23 | script | `scripts/run_step23_backtest_monitoring_module.py` | `196ea51` | Reference |
| STEP23 | source | `src/monitoring/step23_backtest_monitoring_module.py` | `196ea51` | Reference |
| STEP23 | test | `tests/test_step23_backtest_monitoring_module.py` | `196ea51` | Reference |
| STEP24 | config | `config/step24_final_integration_scale_readiness.yaml` | `5a5199b` | Reference |
| STEP24 | script | `scripts/run_step24_final_integration_scale_readiness.py` | `5a5199b` | Reference |
| STEP24 | source | `src/integration/step24_final_integration_scale_readiness.py` | `5a5199b` | Reference |
| STEP24 | test | `tests/test_step24_final_integration_scale_readiness.py` | `5a5199b` | Reference |
| STEP25 | config | `config/step25_full_universe_1743_primary_only_scale.yaml` | `d99fb24` | Reference |
| STEP25 | script | `scripts/run_step25_full_universe_1743_primary_only_scale.py` | `d99fb24` | Reference |
| STEP25 | source | `src/scale/step25_full_universe_1743_primary_only_scale.py` | `d99fb24` | Reference |
| STEP25 | test | `tests/test_step25_full_universe_1743_primary_only_scale.py` | `d99fb24` | Reference |
| STEP26 | config | `config/step26_full_universe_output_audit_first_shortlist.yaml` | `15e41c6` | Reference |
| STEP26 | script | `scripts/run_step26_full_universe_output_audit_first_shortlist.py` | `15e41c6` | Reference |
| STEP26 | source | `src/audit/step26_full_universe_output_audit_first_shortlist.py` | `15e41c6` | Reference |
| STEP26 | test | `tests/test_step26_full_universe_output_audit_first_shortlist.py` | `15e41c6` | Reference |
| STEP27 | config | `config/step27_data_coverage_repair_probe.yaml` | `85aad9f` | Reference |
| STEP27 | script | `scripts/run_step27_data_coverage_repair_probe.py` | `85aad9f` | Reference |
| STEP27 | source | `src/diagnostics/step27_data_coverage_repair_probe.py` | `85aad9f` | Reference |
| STEP27 | test | `tests/test_step27_data_coverage_repair_probe.py` | `85aad9f` | Reference |
| STEP28 | config | `config/step28_full_universe_market_snapshot_refresh_vnstock.yaml` | `820ae4f` | Reference |
| STEP28 | script | `scripts/run_step28_full_universe_market_snapshot_refresh_vnstock.py` | `820ae4f` | Reference |
| STEP28 | source | `src/ingestion/step28_full_universe_market_snapshot_refresh_vnstock.py` | `820ae4f` | Reference |
| STEP28 | test | `tests/test_step28_full_universe_market_snapshot_refresh_vnstock.py` | `820ae4f` | Reference |

## Summary JSON Artifacts

| Step | Path | Important counts/status | Paste? |
|---|---|---|---|
| STEP05A | `data/reports/step05a_primary_only_screening/primary_only_screening_summary.json` | 20 processed; 20 candidates; final `CONDITIONAL_GO_FOR_MANUAL_BCTC_REVIEW`; forbidden terms empty | Selected fields |
| STEP20 | `data/reports/step20_l5_valuation_risk_context/step20_valuation_risk_summary.json` | 20 processed; 20 manual review; 15 insufficient data; core outputs unmodified | Selected fields |
| STEP21 | `data/reports/step21_l6_timing_liquidity_context/timing_liquidity_context_summary.json` | 20 processed; 20 manual review; timing/liquidity warnings only | Selected fields |
| STEP22 | `data/reports/step22_l7_weekly_report_manual_review/weekly_report_summary.json` | 20 processed; 6 watch-only; 14 manual review; 0 rejected | Selected fields |
| STEP23 | `data/reports/step23_backtest_monitoring_module/monitoring_summary.json` | 20 processed; 0 watchlist changes; no previous trend baseline | Selected fields |
| STEP24 | `data/reports/step24_final_integration_scale_readiness/final_integration_summary.json` | 7 required artifacts; 0 missing; integration ready with warnings | Selected fields |
| STEP25 | `data/reports/step25_full_universe_1743_primary_only_scale/full_universe_scale_summary.json` | 1,743 processed; 16 candidates; 1,727 blocked; 0 failed | Selected fields |
| STEP26 | `data/reports/step26_full_universe_output_audit_first_shortlist/step26_audit_summary.json` | 1,743 rows read; 16 shortlist; 1,727 repair priority rows | Selected fields |
| STEP27 | `data/reports/step27_data_coverage_repair_probe/step27_probe_summary.json` | 166 attempted; 17 OK; 149 errors; 17 repair rows; alternative data not needed yet | Selected fields |
| STEP28 | `data/reports/step28_full_universe_market_snapshot_refresh_vnstock/step28_market_refresh_summary.json` | Smoke only: 30 attempted; 28 OK; 2 failed; 28 Step26 blocked recovered | Selected fields |

## Markdown Report Artifacts

| Step | Path | Type | Notes | Paste? |
|---|---|---|---|---|
| STEP22 | `data/reports/step22_l7_weekly_report_manual_review/weekly_report.md` | report/md | Weekly/manual review report for 20-row pilot context | Reference or short excerpt |
| STEP23 | `data/reports/step23_backtest_monitoring_module/backtest_summary.md` | report/md | Monitoring/backtest summary context | Reference or short excerpt |
| STEP24 | `data/reports/step24_final_integration_scale_readiness/scale_readiness_report.md` | report/md | Final integration/readiness report | Reference or short excerpt |
| STEP26 | `data/reports/step26_full_universe_output_audit_first_shortlist/step26_full_universe_audit_report.md` | report/md | Full-universe audit narrative | Reference or short excerpt |

## CSV Artifact Index

| Step | Path | Rows | Key fields | Paste? |
|---|---|---:|---|---|
| STEP05A | `data/reports/step05a_primary_only_screening/primary_only_screening_rows.csv` | 20 | `ticker`, `screening_status`, confidence labels, missing fields | Reference |
| STEP05A | `data/reports/step05a_primary_only_screening/watchlist_candidates.csv` | 20 | `ticker`, `screening_status`, confidence labels | Reference |
| STEP05A | `data/reports/step05a_primary_only_screening/manual_bctc_review_queue.csv` | 20 | `ticker`, `reason_to_review`, missing fields | Reference |
| STEP05A | `data/reports/step05a_primary_only_screening/blocked_tickers.csv` | 0 | `ticker`, `screening_status`, missing fields | Reference |
| STEP20 | `data/reports/step20_l5_valuation_risk_context/step20_valuation_risk_rows.csv` | 20 | `ticker`, `primary_micro_sector`, `valuation_context`, confidence labels | Reference |
| STEP20 | `data/reports/step20_l5_valuation_risk_context/manual_review_queue_step20.csv` | 20 | `ticker`, `manual_review_reason`, missing fields | Reference |
| STEP20 | `data/reports/step20_l5_valuation_risk_context/risk_flags_by_ticker.csv` | 20 | `ticker`, risk context flags, manual review | Reference |
| STEP20 | `data/reports/step20_l5_valuation_risk_context/peer_context_summary.csv` | 7 | `peer_group_id`, `primary_micro_sector`, counts | Reference |
| STEP20 | `data/reports/step20_l5_valuation_risk_context/valuation_context_by_ticker.csv` | 20 | `ticker`, `peer_group_id`, context status | Reference |
| STEP21 | `data/reports/step21_l6_timing_liquidity_context/timing_liquidity_context_rows.csv` | 20 | `ticker`, timing bucket, liquidity bucket, confidence | Reference |
| STEP21 | `data/reports/step21_l6_timing_liquidity_context/manual_review_queue.csv` | 20 | `ticker`, `manual_review_reason`, warning flags | Reference |
| STEP21 | `data/reports/step21_l6_timing_liquidity_context/timing_warning_flags.csv` | 20 | `ticker`, timing warning flags | Reference |
| STEP21 | `data/reports/step21_l6_timing_liquidity_context/liquidity_warning_flags.csv` | 20 | `ticker`, liquidity warning flags | Reference |
| STEP22 | `data/reports/step22_l7_weekly_report_manual_review/watchlist_candidates.csv` | 20 | `ticker`, `watchlist_status`, evidence, risks, confidence | Reference |
| STEP22 | `data/reports/step22_l7_weekly_report_manual_review/manual_review_queue.csv` | 20 | `ticker`, manual review reason, confidence labels | Reference |
| STEP22 | `data/reports/step22_l7_weekly_report_manual_review/evidence_summary.csv` | 20 | `ticker`, micro-sector, evidence, risks | Reference |
| STEP22 | `data/reports/step22_l7_weekly_report_manual_review/reject_log.csv` | 0 | `ticker`, `reject_reason`, confidence | Reference |
| STEP22 | `data/reports/step22_l7_weekly_report_manual_review/unresolved_fields_report.csv` | 53 | `ticker`, `field_name`, `reason` | Reference |
| STEP22 | `data/reports/step22_l7_weekly_report_manual_review/risk_warning_summary.csv` | 14 | warning flag, affected ticker count | Reference |
| STEP22 | `data/reports/step22_l7_weekly_report_manual_review/sector_cycle_summary.csv` | 7 | micro-sector, cycle status, confidence | Reference |
| STEP22 | `data/reports/step22_l7_weekly_report_manual_review/source_conflict_report.csv` | 20 | `ticker`, crosscheck/conflict status | Reference |
| STEP22 | `data/reports/step22_l7_weekly_report_manual_review/data_quality_summary.csv` | 11 | metric, value | Reference |
| STEP22 | `data/reports/step22_l7_weekly_report_manual_review/company_engine_summary.csv` | 20 | `ticker`, survival/peer/context status | Reference |
| STEP23 | `data/reports/step23_backtest_monitoring_module/watchlist_history.csv` | 20 | snapshot, ticker, status, confidence | Reference |
| STEP23 | `data/reports/step23_backtest_monitoring_module/watchlist_change_log.csv` | 20 | ticker, previous/current status, change type | Reference |
| STEP23 | `data/reports/step23_backtest_monitoring_module/score_change_log.csv` | 20 | ticker, score name, previous/current, confidence | Reference |
| STEP23 | `data/reports/step23_backtest_monitoring_module/company_score_drift.csv` | 20 | ticker, score change, drift status | Reference |
| STEP23 | `data/reports/step23_backtest_monitoring_module/monitoring_dashboard.csv` | 9 | metric, current/previous/change, confidence | Reference |
| STEP23 | `data/reports/step23_backtest_monitoring_module/sector_signal_drift.csv` | 7 | micro-sector, status mix, drift status | Reference |
| STEP23 | `data/reports/step23_backtest_monitoring_module/data_coverage_trend.csv` | 2 | metric, current/previous/change | Reference |
| STEP23 | `data/reports/step23_backtest_monitoring_module/source_conflict_trend.csv` | 2 | metric, current/previous/change | Reference |
| STEP23 | `data/reports/step23_backtest_monitoring_module/manual_review_trend.csv` | 1 | metric, current/previous/change | Reference |
| STEP23 | `data/reports/step23_backtest_monitoring_module/reject_reason_trend.csv` | 1 | reject reason, current/previous/change | Reference |
| STEP24 | `data/reports/step24_final_integration_scale_readiness/artifact_checklist.csv` | 7 | artifact name, path, exists, status | Reference |
| STEP24 | `data/reports/step24_final_integration_scale_readiness/schema_contract_check.csv` | 5 | artifact name, required/missing columns | Reference |
| STEP24 | `data/reports/step24_final_integration_scale_readiness/source_confidence_check.csv` | 6 | confidence labels and status | Reference |
| STEP24 | `data/reports/step24_final_integration_scale_readiness/manual_review_contract_check.csv` | 1 | contract name, row count, missing columns | Reference |
| STEP24 | `data/reports/step24_final_integration_scale_readiness/forbidden_terms_check.csv` | 5 | scanned path, forbidden terms status | Reference |
| STEP25 | `data/raw/step25_full_universe_1743/resolved_universe.csv` | 1,743 | `ticker`, `exchange`, `company_name`, source confidence | Reference |
| STEP25 | `data/reports/step25_full_universe_1743_primary_only_scale/full_universe_screening_rows.csv` | 1,743 | `ticker`, `exchange`, `screening_status`, confidence labels | Reference |
| STEP25 | `data/reports/step25_full_universe_1743_primary_only_scale/blocked_tickers.csv` | 1,727 | `ticker`, `screening_status`, missing fields | Reference |
| STEP25 | `data/reports/step25_full_universe_1743_primary_only_scale/watchlist_candidates.csv` | 16 | `ticker`, `screening_status`, confidence labels | Reference |
| STEP25 | `data/reports/step25_full_universe_1743_primary_only_scale/manual_bctc_review_queue.csv` | 16 | `ticker`, review reason, missing fields | Reference |
| STEP25 | `data/reports/step25_full_universe_1743_primary_only_scale/failed_tickers.csv` | 0 | `ticker`, failure reason | Reference |
| STEP25 | `data/reports/step25_full_universe_1743_primary_only_scale/unresolved_fields_report.csv` | 16,018 | `ticker`, `field_name`, reason, batch | Reference |
| STEP25 | `data/reports/step25_full_universe_1743_primary_only_scale/data_coverage_report.csv` | 9 | metric, value, unit | Reference |
| STEP25 | `data/reports/step25_full_universe_1743_primary_only_scale/source_confidence_summary.csv` | 4 | field, value, ticker count | Reference |
| STEP25 | `data/reports/step25_full_universe_1743_primary_only_scale/batch_run_manifest.csv` | 18 | batch ID, start/end, counts, cache flag | Reference |
| STEP25 | `data/reports/step25_full_universe_1743_primary_only_scale/batches/` | 18 row CSVs + 18 JSON manifests | Per-batch screening artifacts | Reference only |
| STEP26 | `data/reports/step26_full_universe_output_audit_first_shortlist/normalized_universe_rows.csv` | 1,743 | ticker, status, confidence labels, missing/block reasons | Reference |
| STEP26 | `data/reports/step26_full_universe_output_audit_first_shortlist/first_review_shortlist_50.csv` | 16 | ticker, review priority, coverage rank | Reference |
| STEP26 | `data/reports/step26_full_universe_output_audit_first_shortlist/manual_bctc_priority_queue_100.csv` | 16 | ticker, manual BCTC priority, confidence | Reference |
| STEP26 | `data/reports/step26_full_universe_output_audit_first_shortlist/surviving_primary_only_candidates.csv` | 16 | ticker, review status, coverage rank | Reference |
| STEP26 | `data/reports/step26_full_universe_output_audit_first_shortlist/data_repair_priority_queue.csv` | 1,727 | ticker, repair priority, missing fields | Reference |
| STEP26 | `data/reports/step26_full_universe_output_audit_first_shortlist/data_coverage_by_ticker.csv` | 1,743 | ticker, market/finance/sector coverage flags | Reference |
| STEP26 | `data/reports/step26_full_universe_output_audit_first_shortlist/data_gap_report.csv` | 18 | gap type, affected count, details | Reference |
| STEP26 | `data/reports/step26_full_universe_output_audit_first_shortlist/status_distribution.csv` | 13 | status/count/percentage | Reference |
| STEP26 | `data/reports/step26_full_universe_output_audit_first_shortlist/missing_field_distribution.csv` | 11 | field/count/examples | Reference |
| STEP26 | `data/reports/step26_full_universe_output_audit_first_shortlist/block_reason_distribution.csv` | 2 | reason/count/examples | Reference |
| STEP26 | `data/reports/step26_full_universe_output_audit_first_shortlist/reject_reason_distribution.csv` | 1 | reason/count/examples | Reference |
| STEP26 | `data/reports/step26_full_universe_output_audit_first_shortlist/schema_gap_report.csv` | 32 | field, schema presence, blank/missing count | Reference |
| STEP26 | `data/reports/step26_full_universe_output_audit_first_shortlist/source_confidence_distribution.csv` | 4 | confidence field/value/count | Reference |
| STEP26 | `data/reports/step26_full_universe_output_audit_first_shortlist/manual_review_distribution.csv` | 3 | field/value/count | Reference |
| STEP26 | `data/reports/step26_full_universe_output_audit_first_shortlist/sector_candidate_distribution.csv` | 1 | sector counts and common gaps | Reference |
| STEP26 | `data/reports/step26_full_universe_output_audit_first_shortlist/micro_sector_candidate_distribution.csv` | 1 | micro-sector counts and common gaps | Reference |
| STEP26 | `data/reports/step26_full_universe_output_audit_first_shortlist/sector_data_gap_summary.csv` | 1 | sector gap summary | Reference |
| STEP27 | `data/reports/step27_data_coverage_repair_probe/direct_fetch_probe_results.csv` | 166 | ticker, sample group, fetch status, error type, raw/normalized rows | Reference |
| STEP27 | `data/reports/step27_data_coverage_repair_probe/fetch_recovered_tickers.csv` | 17 | ticker, repair action, last date, availability flags | Reference |
| STEP27 | `data/reports/step27_data_coverage_repair_probe/repair_queue.csv` | 17 | ticker, recommended repair action, notes | Reference |
| STEP27 | `data/reports/step27_data_coverage_repair_probe/fetch_failed_tickers.csv` | 149 | ticker, error type/message, row counts | Reference |
| STEP27 | `data/reports/step27_data_coverage_repair_probe/fetch_success_examples.csv` | 17 | successful probe detail | Reference |
| STEP27 | `data/reports/step27_data_coverage_repair_probe/fetch_failure_examples.csv` | 25 | failed probe examples | Reference |
| STEP27 | `data/reports/step27_data_coverage_repair_probe/pipeline_vs_direct_fetch_gap.csv` | 166 | fetchability vs Step26 status | Reference |
| STEP27 | `data/reports/step27_data_coverage_repair_probe/raw_observation_manifest.csv` | 166 | raw columns, raw row count, date range | Reference |
| STEP27 | `data/reports/step27_data_coverage_repair_probe/schema_bug_candidates.csv` | 0 | schema issue candidates | Reference |
| STEP27 | `data/reports/step27_data_coverage_repair_probe/source_limitation_queue.csv` | 0 | source limitation rows | Reference |
| STEP27 | `data/reports/step27_data_coverage_repair_probe/step27_probe_rows.csv` | 166 | probe detail rows | Reference |
| STEP28 | `data/reports/step28_full_universe_market_snapshot_refresh_vnstock/market_snapshot_rows.csv` | 30 | ticker, fetch status, dates, last close/volume, error type | Reference |
| STEP28 | `data/reports/step28_full_universe_market_snapshot_refresh_vnstock/market_snapshot_success.csv` | 28 | successful ticker market snapshot rows | Reference |
| STEP28 | `data/reports/step28_full_universe_market_snapshot_refresh_vnstock/market_snapshot_failed.csv` | 2 | failed ticker rows with error type/message | Reference |
| STEP28 | `data/reports/step28_full_universe_market_snapshot_refresh_vnstock/batch_fetch_manifest.csv` | 30 | ticker index, status, attempt count, duration | Reference |
| STEP28 | `data/reports/step28_full_universe_market_snapshot_refresh_vnstock/step26_blocked_recovered.csv` | 28 | Step26 status, Step28 availability, recovery label | Reference |
| STEP28 | `data/reports/step28_full_universe_market_snapshot_refresh_vnstock/step26_blocked_still_failed.csv` | 2 | failed Step26-blocked rows and error type | Reference |
| STEP28 | `data/reports/step28_full_universe_market_snapshot_refresh_vnstock/step27_repair_queue_recheck.csv` | 17 | Step27 repair queue recheck status | Reference |
| STEP28 | `data/reports/step28_full_universe_market_snapshot_refresh_vnstock/ticker_fetch_error_summary.csv` | 2 | error type, count, examples | Reference |
| STEP28 | `data/reports/step28_full_universe_market_snapshot_refresh_vnstock/missing_market_field_summary.csv` | 5 | missing market field, count, examples | Reference |
| STEP28 | `data/reports/step28_full_universe_market_snapshot_refresh_vnstock/pipeline_vs_step26_repair_impact.csv` | 30 | Step26 status vs Step28 market availability | Reference |

## Raw Cache Note

`data/raw/vnstock_vci_market_history/` is a raw market history cache generated by STEP28. It should remain ignored/uncommitted and should not be pasted into ChatGPT.
