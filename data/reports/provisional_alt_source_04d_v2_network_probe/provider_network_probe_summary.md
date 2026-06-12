# PROVISIONAL-ALT-SOURCE-04D-V2 Network Probe Summary

- generated_at: 2026-06-12T06:40:50+00:00
- network_allowed: True
- network_used: False
- provider_runtime_count: 2
- provider_importable_count: 0
- provider_not_importable_count: 2
- fetch_ok_count: 0
- independent_current_source_family_count: 0
- tickers_with_independent_match_count: 0
- manual_review_count: 0
- core_outputs_modified: False
- final_decision: CONDITIONAL_GO_PRIMARY_ONLY_CONFIDENCE

## Provider Import Result
- imported_successfully: none
- failed_or_unavailable: vietfin(NOT_IMPORTABLE; NOT_IMPORTABLE); vnquant(NOT_IMPORTABLE; NOT_IMPORTABLE)

## Market Confidence Result
- market_confidence_can_be_upgraded: False
- pipeline_should_remain_PROVISIONAL_PRIMARY_ONLY: True

## Scope
- Diagnostic market-source probe only for the existing 20 pilot tickers.
- Finance confidence is unchanged and no finance statements were fetched.
- Static historical fallback and raw cache rows cannot create independent current confirmation.

## Not authorized
- not_authorized: production Step19
- not_authorized: Step19 output mutation
- not_authorized: top500 refresh
- not_authorized: full universe fetch
- not_authorized: REAL-DATA-02 rerun
- not_authorized: official PDF fetch
- not_authorized: OCR
- not_authorized: valuation
- not_authorized: buy/sell/hold recommendation

## Allowed Next Step
- Continue with explicit PROVISIONAL_PRIMARY_ONLY market confidence warning
