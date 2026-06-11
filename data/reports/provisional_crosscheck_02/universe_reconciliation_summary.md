# Universe Reconciliation 02

- generated_at: 2026-06-11T01:41:18+00:00
- current_ticker_count: 1800
- old_reference_count_from_prior_snapshot: 1743
- delta_vs_old_reference: 57
- enough_data_for_provisional_screening: 4
- should_exclude_from_stage_2_plus_due_to_missing_market_or_finance: 1539

## Possible Issue Counts
- MISSING_FINANCE_DATA: 799
- MISSING_MARKET_DATA: 727
- OK: 261
- UNKNOWN_EXCHANGE: 13

## 1800 vs 1743 Explanation
- The current count is produced from the available legacy export/import universe, market, and quality files.
- The old 1743 list is not present as a reproducible ticker snapshot in this repo, so it was not fabricated.
- The difference can be explained only as far as local data allows: the current export includes all tickers present in legacy cache/output/universe inputs, including rows with CACHE_MISSING or INSUFFICIENT_DATA.
- Treat tickers with missing market or finance data as lower-priority/manual-review evidence candidates, not clean stage_2+ names.

## Safety
- No finance values were inferred or zero-filled.
- This reconciliation does not create recommendations or official verification.
