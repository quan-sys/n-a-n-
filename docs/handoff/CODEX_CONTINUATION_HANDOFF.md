# Codex Continuation Handoff

## Repository

- Repo: `quan-sys/n-a-n-`
- Branch: `codex/vietnam-stock-pipeline`
- Baseline code HEAD before this handoff package: `820ae4f6a6b4d87e2668e101ef4da0bc5e705b6f`
- Project mode: `PRIMARY_ONLY_SCREENING_MODE`
- Current step: `STEP28-FULL-UNIVERSE-MARKET-SNAPSHOT-REFRESH-VNSTOCK`
- Planned next step: `STEP29_RERUN_AUDIT_AFTER_MARKET_REFRESH`

Always read `PROJECT_CONTEXT.md` before implementing. The project supports human review only. Do not add recommendations, target prices, absolute valuation conclusions, OCR/PDF extraction, official BCTC fetching, fake data, or zero-filled missing fields unless a later task explicitly changes the scope.

## Important Commits

| Step | Commit | Commit subject |
|---|---:|---|
| STEP05A | `169e1f721de21b9fc49255e7c222c79371e5bf81` | `STEP05A add primary-only screening mode` |
| STEP20 | `50e6d57e288306d8fcf205a50239b9126383256b` | `STEP20 add L5 valuation risk context` |
| STEP21 | `374a23b53662aceed9f6ba7d4f6e25546b3cc760` | `STEP21 add L6 timing liquidity context` |
| STEP22 | `eff8b25c174ce7a708ebe3ab7cd3858996755acf` | `STEP22 add L7 weekly manual review report` |
| STEP23 | `196ea51cf4b1f71f47ee34834e41464d9c96841b` | `STEP23 add filter monitoring module` |
| STEP24 | `5a5199b0dd71e27695db03e1ae6e27b9b88b8e17` | `STEP24 add final integration readiness gate` |
| STEP25 | `d99fb24001c809fa205e015ce9b9ed6cb7b8ede8` | `STEP25 add full-universe primary-only scale run` |
| STEP26 | `15e41c68124dcbe134bf67025110a6d418626005` | `STEP26 add full-universe audit shortlist` |
| STEP27 | `85aad9f80e26f84de8983f33dc21ac4cbba0f7ab` | `STEP27 add data coverage repair probe` |
| STEP28 | `820ae4f6a6b4d87e2668e101ef4da0bc5e705b6f` | `STEP28 refresh full-universe market snapshot from vnstock` |

## Current Constraints

- Market data only for STEP28.
- No BCTC, PDF, or OCR work.
- No recommendation language or output fields.
- No target price, fair value, intrinsic value, margin of safety, or expected return logic.
- No mock/sample data in production outputs.
- No zero-fill for missing market or finance fields.
- Every failed ticker must have an error type.
- Treat `vnstock`/VCI outputs as provisional primary-only market data.

## Step Status

| Step | Summary JSON | Key counts | Final decision |
|---|---|---|---|
| STEP05A | `data/reports/step05a_primary_only_screening/primary_only_screening_summary.json` | 20 processed; 20 candidates; 20 manual BCTC review rows | `CONDITIONAL_GO_FOR_MANUAL_BCTC_REVIEW` |
| STEP20 | `data/reports/step20_l5_valuation_risk_context/step20_valuation_risk_summary.json` | 20 processed; 20 manual review; 15 insufficient data | `PASS_WITH_MANUAL_REVIEW_WARNINGS` |
| STEP21 | `data/reports/step21_l6_timing_liquidity_context/timing_liquidity_context_summary.json` | 20 processed; 20 manual review; liquidity low 6, moderate 14 | `PASS_TIMING_LIQUIDITY_CONTEXT_WITH_WARNINGS` |
| STEP22 | `data/reports/step22_l7_weekly_report_manual_review/weekly_report_summary.json` | 20 processed; 6 watch-only; 14 manual review; 0 rejected | `PASS_WEEKLY_REPORT_WITH_WARNINGS` |
| STEP23 | `data/reports/step23_backtest_monitoring_module/monitoring_summary.json` | 20 processed; 0 watchlist changes; no prior trend baseline | `PASS_MONITORING_WITH_WARNINGS` |
| STEP24 | `data/reports/step24_final_integration_scale_readiness/final_integration_summary.json` | 7 required artifacts; 0 missing; source/manual review checks passed | `PASS_FINAL_INTEGRATION_WITH_WARNINGS` |
| STEP25 | `data/reports/step25_full_universe_1743_primary_only_scale/full_universe_scale_summary.json` | 1,743 processed; 16 candidates; 1,727 blocked; 0 failed | `PASS_FULL_UNIVERSE_PRIMARY_ONLY_WITH_WARNINGS` |
| STEP26 | `data/reports/step26_full_universe_output_audit_first_shortlist/step26_audit_summary.json` | 1,743 rows read; 16 shortlist; 16 manual queue; 1,727 repair priority | `PASS_FULL_UNIVERSE_AUDIT_WITH_SHORTLIST` |
| STEP27 | `data/reports/step27_data_coverage_repair_probe/step27_probe_summary.json` | 166 attempted; 17 OK; 149 errors; 17 blocked tickers fetchable | `PASS_REPAIR_NEEDED_PIPELINE_MISSED_DATA` |
| STEP28 | `data/reports/step28_full_universe_market_snapshot_refresh_vnstock/step28_market_refresh_summary.json` | Smoke only: 30 attempted; 28 OK; 2 failed; 28 Step26 blocked recovered | `PASS_MARKET_REFRESH_WITH_PARTIAL_RECOVERY` |

## Expected File Paths

STEP28 config:

```text
config/step28_full_universe_market_snapshot_refresh_vnstock.yaml
```

STEP28 runner:

```text
scripts/run_step28_full_universe_market_snapshot_refresh_vnstock.py
```

STEP28 source module:

```text
src/ingestion/step28_full_universe_market_snapshot_refresh_vnstock.py
```

STEP28 test:

```text
tests/test_step28_full_universe_market_snapshot_refresh_vnstock.py
```

STEP28 output directory:

```text
data/reports/step28_full_universe_market_snapshot_refresh_vnstock/
```

Required STEP28 outputs:

```text
step28_market_refresh_summary.json
market_snapshot_rows.csv
market_snapshot_success.csv
market_snapshot_failed.csv
step26_blocked_recovered.csv
step26_blocked_still_failed.csv
step27_repair_queue_recheck.csv
ticker_fetch_error_summary.csv
missing_market_field_summary.csv
batch_fetch_manifest.csv
pipeline_vs_step26_repair_impact.csv
run_manifest.json
```

The raw cache directory `data/raw/vnstock_vci_market_history/` should remain uncommitted.

## How To Run STEP28

Run the full universe after the smoke test:

```powershell
python scripts/run_step28_full_universe_market_snapshot_refresh_vnstock.py --config config/step28_full_universe_market_snapshot_refresh_vnstock.yaml
```

The default config uses:

- `max_tickers: 1743`
- `retry_count: 2`
- `per_ticker_timeout_seconds: 45`
- `progress_log_every_tickers: 10`
- `resume_from_cache: true`
- `force_refresh: false`
- `request_pause_seconds: 3.2`

Resume behavior: the runner skips tickers already recorded in `market_snapshot_success.csv` or `market_snapshot_failed.csv` unless `--force-refresh` is passed.

Controlled smoke/slice options:

```powershell
python scripts/run_step28_full_universe_market_snapshot_refresh_vnstock.py --config config/step28_full_universe_market_snapshot_refresh_vnstock.yaml --limit 30
python scripts/run_step28_full_universe_market_snapshot_refresh_vnstock.py --config config/step28_full_universe_market_snapshot_refresh_vnstock.yaml --start-index 30 --end-index 80
python scripts/run_step28_full_universe_market_snapshot_refresh_vnstock.py --config config/step28_full_universe_market_snapshot_refresh_vnstock.yaml --force-refresh --limit 30
```

Do not rerun the long full universe job inside a documentation-only task.

## What To Report After STEP28 Full Run

Report these values from `step28_market_refresh_summary.json`:

- total attempted
- fetch OK count
- failed count
- Step26 blocked recovered count
- Step26 blocked still failed count
- Step27 repair queue recovered count
- market coverage after STEP28
- `alternative_paid_data_needed_for_market`
- final decision
- output directory

Also report whether `forbidden_terms_found` is empty and whether `core_outputs_modified` is `false`.

## Planned STEP29

`STEP29_RERUN_AUDIT_AFTER_MARKET_REFRESH` should run only after STEP28 full universe is complete. Its job is to rerun or rebuild the audit/shortlist view using refreshed market coverage, compare against STEP26, and produce updated review queues.

Expected STEP29 behavior:

- Compare old Step26 blocked universe against Step28 refreshed market snapshot.
- Rebuild first review shortlist and manual BCTC priority queue from refreshed coverage.
- Keep finance confidence provisional until official BCTC/BCTN review exists.
- Preserve all guardrails: no recommendations, no target prices, no OCR, no fabricated data, no zero-fill.
