# Implementation Roadmap

This roadmap corrects the implementation order for the Vietnamese stock
screening pipeline. Production filtering must wait until source registry, real
ingestion, raw-to-clean normalization, and data quality checks exist.

## Corrected Order Summary

1. Project context and structure
2. Base data schemas
3. Mock fetcher interface
4. Data Source Registry
5. Real data ingestion / real fetchers
6. Raw-to-clean data pipeline
7. Data quality checks
8. Universe builder
9. L0 Trash Filter
10. L0 Basic Investability Filter
11. Reject Log
12. L1 Business Classification
13. L2 Indicator Registry
14. L3 Sector Cycle Engine
15. L4 Company Engine
16. L5 Valuation & Risk
17. L6 Timing & Liquidity
18. L7 Weekly Report & Manual Review

## 1. Why Data Ingestion Must Come Before Filtering

The system cannot filter trash stocks without usable market data, financial
data, disclosure data, and company profile data.

L0 filters depend on input data such as price, volume, trading value, market
cap, BCTC fields, listing status, and disclosure or audit warnings. Without
those inputs, the pipeline cannot distinguish a genuinely uninvestable stock
from a ticker with missing, stale, incomplete, or conflicting data.

Therefore, the Data Source Registry and real fetchers must be implemented
before production filtering. Mock data is allowed only for tests and early
interface validation; it must not be treated as production data.

## 2. Correct Implementation Stages

### Stage A - Foundation

- `PROJECT_CONTEXT.md`
- `AGENTS.md`
- `README_PIPELINE.md`
- Base data schemas
- Mock fetcher interface

### Stage B - Data Source Registry

- Define where each dataset should come from
- Define primary source, backup source, expected fields, update frequency, and
  reliability

### Stage C - Real Data Ingestion

- Implement real fetchers gradually
- Start with price/volume and company universe
- Then financial statements
- Then disclosure status
- Then macro and commodity data
- Then news/event data

### Stage D - Raw-to-Clean Pipeline

- Store raw data
- Normalize into clean data
- Validate schema
- Preserve source, source_url, fetch_time, and confidence_raw

### Stage E - Data Quality

- Check missing data
- Check stale data
- Check outliers
- Check invalid values
- Check source conflicts
- Assign confidence

### Stage F - Universe Builder

- Build the clean investable universe candidate list
- Flag missing profile, market data, financial data, or disclosure data

### Stage G - L0 Filters

- Trash Filter
- Basic Investability Filter
- Reject Log

### Stage H - Business and Sector Intelligence

- L1 Business Classification
- L2 Indicator Registry
- L3 Sector Cycle Engine

### Stage I - Company Analysis

- L4 Survival Gate
- L4 Peer Quality Ranking
- L4 Cycle Resilience and Upside Capture

### Stage J - Portfolio Research Support

- L5 Valuation & Risk
- L6 Timing & Liquidity
- L7 Weekly Report & Manual Review

## 3. Data Source Registry Requirements

A future file should be created:

```text
config/data_source_registry.yaml
```

It should eventually define datasets such as:

- `universe`
- `market_price`
- `company_profile`
- `financial_statement_summary`
- `disclosure_status`
- `macro_vietnam`
- `commodity_global`
- `sector_news`
- `company_events`

Each source registry entry should include:

- `dataset_name`
- `source_name`
- `source_type`
- `primary_or_backup`
- `expected_fields`
- `update_frequency`
- `reliability_level`
- `requires_api_key`
- `access_method`
- `notes`
- `legal_or_terms_notes` if relevant

## 4. Production Data Rule

A pipeline output is production-like only if it is built from real fetched data
or manually provided real data.

Mock data can only be used for tests and interface validation. Mock data must
not be treated as production data, used to support investment conclusions, or
used to make filtering decisions in production mode.

## 5. L0 Dependency Rule

L0 Trash Filter and Basic Investability Filter must not run in production mode
unless these datasets exist or are explicitly marked unavailable:

- `universe`
- `market_price`
- `company_profile`
- `financial_statement_summary`
- `disclosure_status` if available

If any required dataset is missing, the pipeline must return:

```text
INSUFFICIENT_DATA_FOR_L0
```

or place affected tickers into:

```text
MANUAL_REVIEW_REQUIRED
```

## 6. Do-Not Rules

- Do not make buy/sell recommendations.
- Do not invent financial data.
- Do not treat mock data as real data.
- Do not silently drop stocks.
- Do not silently ignore source conflicts.
- Do not compare companies across unrelated sectors.
- Do not add layers beyond L0-L7.
- Do not implement filtering before data ingestion is available.
