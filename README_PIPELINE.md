# Vietnamese Stock Screening Pipeline

## Purpose

This project is a Vietnamese stock screening pipeline. It is intended to produce
watchlists, evidence tables, confidence scores, reject logs, manual review
queues, and weekly review reports.

The system supports human review. It must not produce automatic buy/sell
recommendations.

## Data Flow

Data ingestion comes before filtering. Production L0 filtering must wait until
the source registry, real fetchers, raw-to-clean normalization, and data quality
checks exist.

```text
raw source registry
-> ingestion contracts and manifests
-> real fetchers
-> raw data
-> clean data
-> data quality
-> universe builder
-> L0 Trash Filter
-> L0 Basic Investability Filter
-> classification
-> driver registry
-> indicator registry
-> sector cycle
-> company scoring
-> valuation/timing
-> report/review
```

## Layer Overview

- Pre-L0: Universe + Data Sanity. Build the listed stock universe and validate
  whether each record has usable data before filtering.
- L0: Trash Filter + Basic Investability Filter. First remove hard trash
  stocks, then apply a rule-based basic investability screen using liquidity,
  market cap if available, data coverage, disclosure risk, and basic financial
  viability. This is not a buy/sell recommendation and does not perform sector
  classification or peer comparison.
- L1: Business Classification. Classify companies by business exposure,
  micro-sector, archetype, drivers, and exposure weights after L0 Basic
  Investability. L1 may flag provisional or manual-review classifications when
  segment, profile, or upstream L0 evidence is weak or conflicting. It does not
  run sector-cycle scoring, peer ranking, valuation, or recommendations.
  Archetype templates define what later analysis should pay attention to for a
  business model, without producing scores or recommendations.
- Driver Registry: Defines and attaches economic/business drivers after
  Archetype Templates, preserving upstream warnings and manual-review flags. It
  prepares inputs for the Indicator Registry and does not fetch data, calculate
  indicators, score cycles, rank peers, value stocks, or make recommendations.
- L2: Indicator Registry. Defines a fixed registry and resolver for core,
  archetype, and sector-specific indicators. It maps drivers, archetypes, and
  micro-sectors to indicator metadata, required datasets/fields, stale-data
  policy, confidence rules, and manual-review triggers. It does not fetch data,
  calculate sector/company/valuation scores, or produce recommendation output.
  Step 18 will use this registry later for the Sector Cycle Engine.
- L3: Sector Cycle Engine. Scores each micro-sector separately from already
  available indicator inputs and evidence. It outputs distress, recovery,
  overheating, structural risk, anomaly, confidence, data-quality, warning, and
  manual-review fields. It does not fetch live data, score individual
  companies, perform valuation, or produce recommendation/target-price output.
  Step 19 will later implement the Company Engine.
- L4: Company Engine. Evaluate company survival, peer quality, and cycle
  resilience only after the sector and peer group are known.
- L5: Valuation & Risk. Assess valuation and risk only when data is sufficient,
  using industry-appropriate metrics.
- L6: Timing & Liquidity. Evaluate market timing and liquidity risk without
  making buy/sell recommendations.
- L7: Report & Manual Review. Generate weekly reports, reject logs, evidence
  tables, confidence scores, and manual review queues.

## Folder Structure

- `config/`: Configuration files for pipeline settings, thresholds, schemas,
  and environment-independent defaults.
- `data/raw/`: Raw input files before cleaning or normalization.
- `data/clean/`: Cleaned data after validation, normalization, and sanity
  checks.
- `data/features/`: Derived feature datasets used by downstream classification,
  scoring, and reporting steps.
- `data/reports/`: Generated weekly review reports and other human-readable
  outputs.
- `data/reports/ingestion_manifests/`: JSON run manifests for ingestion
  attempts, including missing columns, counts, warnings, errors, and data
  quality status.
- `data/rejects/`: Reject logs and evidence for stocks removed by Pre-L0 or L0.
- `src/ingestion/`: DATA-01 ingestion contracts and manifest helpers. This
  layer validates manual/mock-ready inputs and records ingestion attempts, but
  does not fetch live data. DATA-02 adds bulk universe/company-profile ingestion
  for `manual_csv`, `manual_xlsx`, and `mock` modes, writing
  `data/raw/universe_raw.csv`, `data/raw/company_profile_raw.csv`, ingestion
  manifests, and coverage summaries. DATA-03 adds bulk market price/volume
  ingestion for `manual_csv`, `manual_xlsx`, and `mock` modes, writing
  `data/raw/market_price_raw.csv`, ingestion manifests, market coverage
  reports, and ticker-level success/failure logs. DATA-04 adds bulk financial
  statement ingestion for `manual_csv`, `manual_xlsx`, `mock`, and
  user-provided `external_vendor_optional` modes, writing
  `data/raw/financial_statement_summary_raw.csv`, ingestion manifests,
  financial coverage reports, and missing-data reports without fabricating BCTC
  values. DATA-05 adds bulk disclosure/warning ingestion for `manual_csv`,
  `manual_xlsx`, `mock`, optional `real_exchange_optional`, and user-provided
  `external_vendor_optional` modes, writing
  `data/raw/disclosure_status_raw.csv`, ingestion manifests, disclosure
  coverage reports, and manual-review candidate files. Missing disclosure rows
  are treated as unknown/unavailable, not clean, unless a source explicitly
  confirms clean status. DATA-06 adds an auditable raw-to-clean coverage and
  pipeline dry run through available Step 18 modules, writing
  `data/reports/data_coverage_report.csv`,
  `data/reports/ingestion_run_summary.md`,
  `data/reports/pipeline_dry_run_summary.md`,
  `data/reports/pipeline_dry_run_errors.csv`, and
  `data/reports/manual_review_queue.csv` when review rows exist. This remains a
  validation pass only; it does not implement Step 19, recommendations, or
  target prices.
- `src/fetchers/`: Data fetching adapters. These must not fetch real data unless
  a task explicitly requests implementation.
- `src/universe/`: Pre-L0 universe construction and data sanity modules.
- `src/classification/`: L1 business classification modules.
- `src/quality/`: Data quality, confidence, evidence, and manual review support
  modules.
- `src/features/`: L2 indicator registry and feature preparation modules.
- `src/scoring/`: L3-L6 scoring modules once upstream contracts are defined.
- `src/reports/`: L7 report, watchlist, reject-log, and manual-review output
  modules.
- `tests/`: Tests, mock fixtures, and validation cases.

## Important Rule

Pre-L0 and L0 must be implemented before L1/L2/L3.

The system must remove unusable data and trash stocks before sector cycle
analysis. No task should skip directly to classification, sector scoring,
watchlists, or reports without preserving this ordering.

Production filtering must not run before real or clean input data exists. Mock
data is only for tests and early interface validation; it must not be treated as
production data.

## REAL-DATA-01B Source Coverage

`scripts/run_first_20_real_data_dry_run.py` supports a source-coverage repair
batch before scaling:

```powershell
python scripts\run_first_20_real_data_dry_run.py `
  --limit 20 `
  --mode real `
  --ticker-selection representative `
  --request-sleep-seconds 3.2 `
  --real-source-max-requests 80 `
  --market-lookback-days 90 `
  --output-dir data\reports\real_data_first_20 `
  --raw-output-dir data\raw `
  --allow-partial
```

The representative ticker config is
`config/real_data_first_20_representative_tickers.yaml`. It is only for
engineering source-coverage testing.

The run writes `source_request_summary.csv` and `source_adapter_status.csv` in
`data/reports/real_data_first_20/`. If financial statement or disclosure sources
are unavailable, use the empty manual templates in `data/templates/` and pass
`--input-financials` or `--input-disclosure`. Missing disclosure remains
unknown/unavailable, not clean.

Some `vnstock` finance/profile paths may require optional charting support in
the local environment. Install only if needed:

```powershell
python -m pip install vnstock_ezchart
```
