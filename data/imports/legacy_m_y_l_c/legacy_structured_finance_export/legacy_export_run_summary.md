# Legacy Structured Finance Export Summary

## Run
- generated_at: 2026-06-11T00:49:59+00:00
- mode: cache_only
- live_fetch_used: No

## Counts
- tickers_exported: 1800
- finance_rows_exported: 12435
- market_rows_exported: 1800

## Data Quality Distribution
- CACHE_MISSING: 57
- INSUFFICIENT_DATA: 591
- OK_FOR_PROVISIONAL_SCREEN: 4
- PARTIAL_PROVISIONAL_DATA: 1148

## Safety
- All finance rows are marked provisional_structured.
- Missing finance values were not inferred or zero-filled.
- Buy/sell/target/fair_value/margin_of_safety/timing fields were not exported.
- No OCR, PDF parsing, REAL-DATA-02, Step19, or 01I-G reconciliation was run.
