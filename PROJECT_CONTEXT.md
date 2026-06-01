# Project Context: Vietnamese Stock Screening Pipeline

This file is the project-level source of truth for future Codex tasks in this
repository. All future implementation, review, and documentation work must
follow these rules unless the user explicitly updates this file.

## Project Goal

Build a modular Vietnamese stock screening pipeline that can scan listed
Vietnamese stocks, remove unusable or trash stocks first, classify companies by
business exposure, track sector-specific data, score sector cycles, rank
companies within the correct peer group, and generate weekly review reports.

The system supports human investment review. It must not replace human
investment judgment or produce direct buy/sell recommendations.

## Required Outputs

The system must be able to produce:

- Investable universe files
- Reject logs
- Evidence tables
- Confidence scores
- Sector cycle signals
- Company quality scores
- Watchlists
- Weekly review reports
- Manual review queues

The system must not produce:

- Direct buy/sell recommendations
- Fake financial data
- Target prices without sufficient assumptions
- Conclusions without confidence status
- Silent data conflict handling

## Financial Integrity Rules

1. Never invent financial data.
2. Never hardcode fake financial numbers outside tests or mock fixtures.
3. Every score must include confidence or data quality status.
4. Missing data must reduce confidence.
5. Stale data must reduce confidence.
6. Conflicting data must create a warning or manual review flag.
7. If data is insufficient, return `INSUFFICIENT_DATA`, `LOW_CONFIDENCE`, or
   `MANUAL_REVIEW_REQUIRED`.
8. Every rejected stock must include a clear reject reason.
9. Never compare companies from unrelated sectors.
10. The final output should support human review, not replace human investment
    judgment.

## Pipeline Ordering Rule

Pre-L0 and L0 must run before sector classification.

The pipeline must first build and sanity-check the listed stock universe, then
remove trash, unusable, uninvestable, or data-poor stocks before business
classification, sector cycle scoring, peer ranking, valuation, timing, or
reporting.

No future task should skip directly to classification, scoring, watchlists, or
reports without respecting this order.

## Architecture Overview

The architecture contains Pre-L0 and layers L0 through L7. Do not create new
layers beyond L0-L7 unless the user explicitly updates this context file.

### Pre-L0: Universe and Data Sanity

Purpose: Build the initial listed stock universe and check whether the data is
usable before any filtering.

Checks:

- Ticker exists
- Exchange exists
- Listing status exists
- Company profile exists if available
- Price and volume data exist
- Financial statement data exist if available
- Disclosure data exists if available
- Data freshness
- Missing data
- Stale data
- Obvious data errors
- Outliers

Possible statuses:

- `VALID_DATA`
- `MISSING_DATA`
- `STALE_DATA`
- `DATA_ERROR`
- `MANUAL_REVIEW`

### L0: Trash Filter and Basic Investability Filter

Purpose: Remove stocks that are too risky, too illiquid, too small, too broken,
or too data-poor before sector analysis.

L0.1 Trash Filter should reject severe cases such as:

- Extremely low liquidity
- Missing or broken market data
- Severe disclosure or audit warnings
- Very small and uninvestable market cap
- Missing financial statements
- Negative equity if available
- Persistent unexplained losses
- Trading restrictions if available
- Unreliable data coverage

L0.2 Basic Investability Filter should calculate:

- `liquidity_score`
- `market_cap_score`
- `data_coverage_score`
- `disclosure_risk_score`
- `financial_viability_score`
- `basic_investability_score`

L0 output statuses:

- `PASS`
- `REJECT`
- `WATCH_ONLY`
- `MANUAL_REVIEW`

Every rejected stock must include:

- `ticker`
- `reject_layer`
- `reject_reason`
- `evidence_fields`
- `confidence`

### L1: Business Classification

Purpose: Assign each stock to the correct business classification before sector
cycle scoring.

Each stock should support:

- `primary_micro_sector`
- `secondary_micro_sector`
- `primary_exposure_weight`
- `secondary_exposure_weight`
- `archetype`
- `drivers`
- `classification_confidence`
- `classification_notes`

Definitions:

- Micro-sector: the specific business segment where the company actually earns
  money.
- Archetype: the business model template used to avoid writing 80-100 fully
  separate scoring systems.
- Driver: an external factor that affects the sector, such as interest rates,
  USD/VND, oil price, rubber price, HRC, export demand, public investment,
  credit growth, or real estate policy.
- Exposure weight: how much of the company is economically exposed to each
  business segment.

Business classification must not rely only on revenue. It must consider
business exposure, including:

- Revenue exposure
- Gross profit or EBIT exposure
- Asset or capex exposure
- Business description
- Multi-year business stability
- Manual notes when needed

If a company is multi-sector, do not force it into one sector. Use weighted
exposure.

### L2: Indicator Registry

Purpose: Define what data should be tracked.

Indicators must be organized into:

1. Core indicators
2. Archetype indicators
3. Sector-specific indicators

Core indicators may include:

- Price
- Volume
- Trading value
- Market cap
- Revenue
- Net profit
- Gross margin
- Operating margin
- Operating cash flow
- Debt
- Inventory
- Equity
- ROE/ROA if available

Archetype indicators depend on the business model.

Examples:

- `export_manufacturer`: USD/VND, export demand, order trends, input costs,
  logistics cost, margin, inventory
- `commodity_processor`: input cost, output price, spread, inventory, end
  demand, working capital
- `financial_bank`: NIM, CASA, NPL, group 2 debt, provisioning, credit growth
- `real_estate_developer`: legal status, presales, inventory, debt maturity,
  interest rate
- `utility_regulated`: production volume, input fuel cost, weather/hydrology,
  PPA/regulatory price

Sector-specific indicators are required.

Examples:

- `steel_integrated`: HRC, iron ore, coking coal, steel spread, construction
  demand
- `galvanized_steel`: HRC, export demand, trade defense risk
- `natural_rubber`: rubber price, China demand, oil/synthetic rubber
  relationship
- `tire_manufacturing`: rubber input cost, oil input cost, auto demand, tire
  exports
- `pangasius_export`: pangasius price, US/EU/China demand, anti-dumping tax
  risk, feed cost
- `textile_export`: cotton price, US/EU PMI, order trend, customer inventory
- `residential_real_estate`: legal progress, presales, inventory, bond maturity
- `industrial_park`: FDI, occupancy rate, land bank, rental price
- `commercial_bank`: NIM, CASA, NPL, provisioning, credit growth
- `power_generation`: hydrology, coal/gas price, PPA, electricity output
- `port_logistics`: container volume, export/import activity, freight rate

### L3: Sector Cycle Engine

Purpose: Score each micro-sector separately.

Do not force sectors into only three hard phases. Calculate parallel scores:

- `distress_score`
- `recovery_score`
- `overheating_score`
- `structural_risk_score`
- `anomaly_score`
- `cycle_confidence`

Each micro-sector has its own cycle result. Micro-sectors may inherit logic from
archetypes but must keep their own sector-specific drivers and indicators.

The system must detect anomalies. If something unusual happens outside normal
scoring logic, do not silently adjust permanent weights. Create:

- `anomaly_alert`
- `suggested_temporary_adjustment`
- `manual_review_required`
- `evidence`

### L4: Company Engine

Purpose: Score companies only after the sector and peer group are known.

#### L4A: Survival Gate

Ask whether the company can survive a sector downturn.

Survival metrics may include:

- Debt pressure
- Operating cash flow
- Interest coverage if available
- Gross margin stability
- Inventory risk
- Audit/disclosure risk
- Liquidity risk
- Persistent loss risk

If a company fails the survival gate, it should not proceed to high-confidence
watchlist ranking.

#### L4B: Peer Quality Ranking

Compare companies only within the same primary micro-sector.

Rules:

- Do not compare banks with non-banks.
- Do not compare unrelated industries.
- Use exposure weights for multi-sector companies.

#### L4C: Cycle Resilience and Upside Capture

Evaluate whether the company:

- Loses less than peers in downturns
- Recovers faster than peers in upcycles
- Maintains stronger margins than peers
- Recovers earnings faster than peers
- Has better relative strength than peers
- Avoids financial deterioration during sector stress

### L5: Valuation and Risk

Purpose: Score valuation and risk only when data is sufficient.

Rules:

- Do not use one valuation metric for all industries.
- Banks may use P/B, ROE, NPL, and provisioning.
- Real estate may use RNAV/PB/debt/legal risk if data exists.
- Cyclical commodity companies may use normalized earnings, P/B, or EV/EBITDA
  if available.
- Defensive utilities may use cash flow, dividend, or EV/EBITDA if available.
- If valuation data is insufficient, return low confidence.
- Do not invent target prices.

### L6: Timing and Liquidity

Purpose: Evaluate market timing and liquidity risk without making a buy/sell
recommendation.

Possible metrics:

- Relative strength
- Drawdown
- Volume trend
- Trading value
- Volatility
- Liquidity quality
- Distance from moving averages if implemented later

### L7: Report and Manual Review

Purpose: Generate weekly reports so the human user does not need to manually
review every stock every day.

Reports should include:

- Top improving micro-sectors
- Distressed sectors without recovery signal
- Overheating sectors
- Structural risk warnings
- Anomaly alerts
- Data quality warnings
- Stocks passing survival gate
- Rejected stocks with reasons
- Manual review queue
- Evidence table
- Confidence score

Output principle:

The system may say:

> Sector A has a medium-confidence recovery signal. Companies X/Y/Z have the
> highest survival scores within that sector. Evidence and risks are listed
> below.

The system must not say:

> Buy stock X.

## Supporting Modules

The architecture requires the following supporting modules:

- Data Quality Module
- Evidence Module
- Confidence Module
- Reject Log
- Manual Review Queue
- Backtest/Monitoring Module

## Implementation Guardrails

Future tasks must follow these guardrails:

- Do not modify existing business logic unless the user explicitly requests it.
- Do not refactor the current pipeline unless the user explicitly requests it.
- Do not delete existing files unless the user explicitly requests it.
- Do not fetch real data unless the user explicitly requests it.
- Do not implement scoring until the relevant earlier layers and data-quality
  contracts are defined.
- Do not create layers beyond Pre-L0 and L0-L7.
- Do not make buy/sell recommendations.
- Do not silently handle missing, stale, conflicting, or anomalous data.
- Keep outputs evidence-backed and confidence-aware.

## Step 0 Completion Criteria

Step 0 is complete when:

1. `PROJECT_CONTEXT.md` exists at the project root.
2. The file includes the full Pre-L0 and L0-L7 architecture.
3. The file clearly states that Pre-L0 and L0 must run before sector
   classification.
4. The file includes financial integrity rules.
5. The file defines micro-sector, archetype, driver, and exposure weight.
6. The file states that no buy/sell recommendation should be produced.
7. The file states that every rejected stock needs a reject reason.
8. The file includes the required supporting modules.
9. No other code or business logic is changed.

## Recommended Next Step

The next implementation step should define Pre-L0 contracts and file schemas:

- Listed universe input schema
- Data sanity status schema
- Data freshness rules
- Reject and manual-review record schema
- Evidence and confidence fields required by downstream layers
