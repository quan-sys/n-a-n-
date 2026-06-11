# PROVISIONAL-CURRENT-MARKET-03B Market Cross-Check Summary

- generated_at: 2026-06-11T13:57:41+00:00
- input_snapshot_path: data\reports\provisional_current_market_03\current_market_snapshot.csv
- pilot_ticker_count: 20
- reference_sources_found: 4
- reference_source_names_found: ['legacy_cafef_vnstock_cache', 'provisional_crosscheck_02_legacy_market', 'provisional_crosscheck_02_public_historical', 'raw_cache_current_market_03']
- reference_sources_missing: []
- primary_missing_count: 0
- primary_stale_count: 0
- reference_missing_count: 40
- reference_stale_count: 20
- price_mismatch_count: 0
- volume_mismatch_count: 0
- manual_review_count: 0
- fail_count: 0
- final_decision: CONDITIONAL_GO

## Important Interpretation
- Stale reference rows do not prove the primary market snapshot is wrong.
- The public historical fallback is labeled non-current and is not used as current confirmation.
- Raw cache rows verify local snapshot consistency; they are not an independent vendor check.
- A pass or conditional pass here only supports 03C replay on the same 20 pilot tickers.
- This result does not authorize top-500 refresh, full-universe live refresh, REAL-DATA-02, Step19, PDF fetch, or OCR.

## Next Step
- PROVISIONAL-CURRENT-MARKET-03C - End-to-End Replay on Same 20 Pilot Tickers
