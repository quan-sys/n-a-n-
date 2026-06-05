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

### Manual financial/disclosure fallback

If real-source coverage is still insufficient, provide source-backed manual
files instead of fabricating missing values:

```powershell
python scripts\run_first_20_real_data_dry_run.py `
  --mode real `
  --ticker-selection representative `
  --only-datasets financial_statement_summary,disclosure_status `
  --input-financials data\manual\financial_statement_summary.csv `
  --input-disclosure data\manual\disclosure_status.csv `
  --finance-request-budget 120 `
  --disclosure-request-budget 60 `
  --output-dir data\reports\real_data_first_20_finance_disclosure_retry `
  --raw-output-dir data\raw `
  --allow-partial
```

Use the templates:

- `data/templates/financial_statement_summary_template.csv`
- `data/templates/disclosure_status_template.csv`

Manual rows must preserve `source`, `source_url`, `fetch_time`, and confidence.
If manual and real rows conflict, the pipeline logs
`DATA_CONFLICT_MANUAL_VS_REAL` and keeps the record in manual review instead of
silently overwriting source-provided values.

## REAL-DATA-01F Multi-source Evidence

`scripts/run_multi_source_evidence.py` builds a field-level evidence and
cross-check layer from already-ingested local files. It does not fetch live data
and does not implement Step 19.

```powershell
python scripts\run_multi_source_evidence.py `
  --raw-dir data\raw `
  --output-dir data\reports\multi_source_evidence_01f `
  --ticker-list VCB,BID,CTG,MBB,ACB,HPG,HSG,VHM,KDH,NLG,SSI,VND,GAS,PVS,FPT,MWG,VGC,GMD,VHC,TCM `
  --allow-partial
```

The source categories and priority rules are defined in:

- `config/multi_source_registry.yaml`
- `config/source_priority.yaml`

The run writes:

- `source_availability_matrix.csv`
- `field_level_evidence.csv`
- `source_conflict_report.csv`
- `unresolved_required_fields.csv`
- `multi_source_run_summary.md`
- `datasource_decision_report.md`

If finance/disclosure evidence is not ready, use source-backed manual CSV/XLSX
files for the representative 20 tickers. Missing finance values remain missing,
conflicting values go to manual review, and missing disclosure rows remain
unknown/unavailable rather than clean.

## REAL-DATA-01G Automated Multi-source Probing

`scripts/run_multi_source_probe_01g.py` actively probes configured finance and
disclosure sources, runs source adapters where safe, writes candidate rows, and
feeds parsed rows into the existing 01F evidence reconciliation layer.

```powershell
python scripts\run_multi_source_probe_01g.py `
  --tickers VCB,BID,CTG,MBB,ACB,HPG,HSG,VHM,KDH,NLG,SSI,VND,GAS,PVS,FPT,MWG,VGC,GMD,VHC,TCM `
  --datasets financial_statement_summary,disclosure_status `
  --sources vnstock,cafef,vietstock,hose,hnx,ssc `
  --output-dir data\reports\multi_source_probe_01g `
  --raw-output-dir data\raw `
  --request-sleep-seconds 3.2 `
  --allow-partial
```

The probe/adapters report source failures explicitly as
`SOURCE_UNAVAILABLE`, `SOURCE_SCHEMA_UNKNOWN`,
`SOURCE_BLOCKED_OR_JS_REQUIRED`, `SOURCE_PARSE_FAILED`,
`SOURCE_RATE_LIMITED`, or `SOURCE_EMPTY_RESPONSE`. They do not bypass
login walls, CAPTCHAs, JS-only pages, private APIs, or robots restrictions.

Manual CSV/XLSX remains a source-backed fallback and override path, not the main
data-entry strategy. No source row does not mean clean: missing disclosure stays
unknown/unavailable unless an explicit source-backed checked row exists. Step 19
remains blocked until finance/disclosure readiness improves enough for L0 and
Step 18 evidence use.

## REAL-DATA-01H Official Disclosure Status-list Ingestion

`scripts/run_disclosure_status_01h.py` shifts disclosure-risk ingestion away
from per-company `vnstock` events and toward official/public status lists from
exchanges and regulators. This matters because L0 disclosure risk needs warning,
control, restriction, suspension, delisting, late-report, audit, and sanction
status lists rather than generic company event feeds.

```powershell
python scripts\run_disclosure_status_01h.py `
  --representative-tickers VCB,BID,CTG,MBB,ACB,HPG,HSG,VHM,KDH,NLG,SSI,VND,GAS,PVS,FPT,MWG,VGC,GMD,VHC,TCM `
  --sources hose,hnx,ssc,cafef,vietstock,vnstock `
  --output-dir data\reports\disclosure_status_01h `
  --raw-snapshot-dir data\raw\source_snapshots\01h `
  --request-sleep-seconds 3.2 `
  --allow-partial
```

The run discovers/probes source-list URLs, records safe raw snapshot metadata,
parses accessible official/public lists, creates positive-control tickers from
the parsed warning/status rows, and then checks both the representative 20 and
the positive-control tickers. A representative ticker that is absent from a
successfully parsed list receives `SOURCE_CHECKED_NOT_FOUND`, not a clean bill
of health. A failed source receives `SOURCE_UNAVAILABLE`,
`SOURCE_SSL_FAILED`, `SOURCE_SCHEMA_UNKNOWN`, `SOURCE_PARSE_FAILED`, or related
failure status and must remain manual-review evidence.

The run writes:

- `disclosure_source_probe_matrix.csv`
- `disclosure_list_parse_diagnostics.csv`
- `disclosure_status_lists_raw_index.csv`
- `disclosure_positive_control_tickers.csv`
- `disclosure_status_by_ticker.csv`
- `disclosure_candidate_rows.csv`
- `disclosure_coverage_by_source.csv`
- `disclosure_source_checked_no_warning.csv`
- `source_availability_matrix.csv`
- `field_level_evidence.csv`
- `source_conflict_report.csv`
- `unresolved_required_fields.csv`
- `comparison_vs_01g.md`
- `disclosure_01h_run_summary.md`
- `datasource_decision_report.md`

Positive-control is the guardrail against falsely concluding that the disclosure
adapter works just because the representative 20 have no warning rows. If parsed
official lists produce positive-control warning rows while representative
tickers produce source-checked not-found rows, the adapter is working for those
parsed lists. If no official/public list can be parsed, the run reports
`POSITIVE_CONTROL_UNAVAILABLE`. If positive-control tickers exist but matching
does not produce warning rows, it reports
`DISCLOSURE_ADAPTER_FAILED_POSITIVE_CONTROL`.

REAL-DATA-01H still does not implement Step 19 and does not run REAL-DATA-02.
Absence from parsed official lists is not guaranteed clean disclosure, and
finance evidence remains a separate blocker for Step 18 and future Step 19
readiness.
