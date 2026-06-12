# REAL-DATA-02-PILOT-20 Summary

- generated_at: 2026-06-11T15:33:05+00:00
- pilot_ticker_count: 20
- final_decision: CONDITIONAL_GO_FOR_STEP19_SHADOW_20
- critical_fail_count: 0
- warn_count: 13
- source_failure_count: 0
- tickers_succeeded: 20
- tickers_failed: 0
- missing_market_count: 0
- stale_market_count: 0
- finance_one_source_only_count: 20
- finance_missing_count: 0
- forbidden_terms_found: 0

## What passed
- Market rows passing readiness: 20
- Pilot tickers retained in readiness table: 20
- Structured finance remained provisional and was not upgraded to official verification.

## Warnings
- VSC structured_finance: FINANCE_FIELD_MISSING - Missing provisional finance fields: net_income.
- VGI structured_finance: FINANCE_FIELD_MISSING - Missing provisional finance fields: net_income.
- VCG structured_finance: FINANCE_FIELD_MISSING - Missing provisional finance fields: net_income.
- VNM structured_finance: FINANCE_FIELD_MISSING - Missing provisional finance fields: net_income.
- TVN structured_finance: FINANCE_FIELD_MISSING - Missing provisional finance fields: net_income.
- VJC structured_finance: FINANCE_FIELD_MISSING - Missing provisional finance fields: net_income.
- VTZ structured_finance: FINANCE_FIELD_MISSING - Missing provisional finance fields: net_income.
- YEG structured_finance: FINANCE_FIELD_MISSING - Missing provisional finance fields: net_income.
- VRE structured_finance: FINANCE_FIELD_MISSING - Missing provisional finance fields: net_income.
- VNE structured_finance: FINANCE_FIELD_MISSING - Missing provisional finance fields: net_income.
- VOS structured_finance: FINANCE_FIELD_MISSING - Missing provisional finance fields: net_income.
- VTP structured_finance: FINANCE_FIELD_MISSING - Missing provisional finance fields: net_income.
- TLH structured_finance: FINANCE_FIELD_MISSING - Missing provisional finance fields: net_income.

## Failures
- none

## Safety Boundary
- This pilot only permits Step19-SHADOW-20 if final_decision is PASS or CONDITIONAL_GO.
- This does not permit top-500 refresh, full-universe live fetch, official PDF fetch, OCR, valuation, target price, or recommendations.

## Next Step
- If PASS or CONDITIONAL_GO: STEP19-SHADOW-20.
- If NO_GO: fix listed issues before Step19 shadow.
