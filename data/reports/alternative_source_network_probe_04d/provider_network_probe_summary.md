# PROVISIONAL-ALT-SOURCE-04D Network Probe Summary

- generated_at: 2026-06-12T06:24:03+00:00
- pilot_ticker_count: 20
- network_used: False
- optional_install_used: False
- provider_count_attempted: 0
- provider_count_fetch_ok: 0
- independent_current_source_family_count: 0
- tickers_with_independent_match_count: 0
- tickers_with_independent_mismatch_count: 0
- manual_review_count: 0
- critical_fail_count: 0
- core_outputs_modified: False
- final_decision: CONDITIONAL_GO_FOR_SCALE_DECISION_WITH_PRIMARY_ONLY_MARKET_CONFIDENCE

## Interpretation
- This is only a controlled provider network probe for the existing 20 pilot tickers.
- It can improve market source-family confidence only if independent current observations match primary data.
- It does not change finance confidence and does not fetch finance statements.
- Static historical fallback and same-source-family rows do not count as current independent confirmation.

## Not authorized
- not_authorized: production Step19
- not_authorized: top500 refresh
- not_authorized: full universe fetch
- not_authorized: REAL-DATA-02 rerun
- not_authorized: official PDF fetch
- not_authorized: OCR
- not_authorized: valuation
- not_authorized: buy/sell/hold recommendation

## Allowed Next Step
- SCALE-DECISION-05A with explicit primary-only warning
