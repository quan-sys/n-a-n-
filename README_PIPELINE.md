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
- L2: Indicator Registry. Define core, archetype, and sector-specific
  indicators that should be tracked.
- L3: Sector Cycle Engine. Score each micro-sector separately using
  sector-specific drivers and confidence-aware cycle signals.
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
- `data/rejects/`: Reject logs and evidence for stocks removed by Pre-L0 or L0.
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
