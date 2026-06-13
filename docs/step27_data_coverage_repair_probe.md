# STEP27 Data Coverage Repair Probe

STEP27 diagnoses why STEP26 marked most tickers as missing market data. It is a
data-quality probe only. It does not update STEP25 or STEP26 outputs, does not
fetch finance data, and does not produce valuation or trading guidance.

## Inputs

- STEP26 normalized universe rows
- STEP26 first review shortlist
- STEP26 manual BCTC queue
- STEP25 full-universe screening rows, used only for mutation checks

If the configured paths differ from the current repository layout, the runner
searches under `data/reports/` and writes the resolved paths to
`input_resolution_report.json`.

## Probe Method

The runner creates a deterministic sample:

- up to 100 `BLOCKED_INSUFFICIENT_MARKET_DATA` tickers
- up to 20 control tickers from the STEP26 first review shortlist
- up to 50 deterministic random universe tickers using seed `2701`

For each ticker it calls the vnstock market history API through the existing
market refresh wrapper, then compares direct fetch observations against STEP26
status and missing-field evidence.

## Output Classes

- `FETCH_OK_PIPELINE_MISSED`: direct vnstock history had required normalized
  market fields for a ticker previously blocked by STEP26.
- `FETCH_OK_SCHEMA_NORMALIZATION_ISSUE`: raw rows had price-like columns, but
  normalized required fields were incomplete.
- `FETCH_OK_CACHE_OR_SNAPSHOT_STALE`: direct vnstock history was newer than the
  prior snapshot row.
- `FETCH_EMPTY_SOURCE_LIMITATION`: direct vnstock history returned no rows.
- `FETCH_ERROR_SOURCE_OR_TICKER_ISSUE`: direct fetch raised an error.
- `FETCH_SKIPPED_INPUT_INVALID`: ticker input was blank or invalid.
- `FETCH_BLOCKED_BY_CONFIG`: fetch was not attempted because of run limits or
  network policy.

## Required Outputs

All files are written under:

`data/reports/step27_data_coverage_repair_probe/`

- `step27_coverage_probe_summary.json`
- `step27_probe_summary.json`
- `step27_probe_rows.csv`
- `direct_fetch_probe_results.csv`
- `raw_observation_manifest.csv`
- `fetch_success_examples.csv`
- `fetch_failure_examples.csv`
- `fetch_recovered_tickers.csv`
- `fetch_failed_tickers.csv`
- `repair_queue.csv`
- `source_limitation_queue.csv`
- `schema_bug_candidates.csv`
- `pipeline_vs_direct_fetch_gap.csv`
- `input_resolution_report.json`
- `run_manifest.json`

## Run

```powershell
python scripts\run_step27_data_coverage_repair_probe.py --config config\step27_data_coverage_repair_probe.yaml --output-dir data\reports\step27_data_coverage_repair_probe --allow-partial
```

The outputs remain provisional:

- `market_source_confidence = PROVISIONAL_PRIMARY_ONLY`
- `finance_source_confidence = PROVISIONAL_LOW`
- `crosscheck_status = NOT_AVAILABLE`
- `verification_status = NEEDS_MANUAL_BCTC_REVIEW`
