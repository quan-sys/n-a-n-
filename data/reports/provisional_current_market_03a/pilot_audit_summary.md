# PROVISIONAL-CURRENT-MARKET-03A Pilot Audit Summary

- generated_at: 2026-06-11T13:16:56+00:00
- input_report_dir: data\reports\provisional_current_market_03
- evidence_report_dir: data\reports\evidence_pack_policy_03_current_market
- pilot_ticker_count: 20
- pass_count: 34
- warn_count: 0
- fail_count: 0
- blocker_count: 0
- overall_status: PASS

## Key Findings
- check_status_counts: {'PASS': 34}
- mismatch_cases: 0
- No failing audit checks.

## Stage/Gate Consistency
- gate_status_counts: {'STAGE2_ELIGIBLE': 20}
- The 20-ticker pilot is intentionally not a top-500 or full-universe refresh.
- Large BLOCKED_MISSING_MARKET counts outside the 20 fetched tickers mean not refreshed in pilot, not a market-data conclusion.

## Evidence Queue Consistency
- Evidence queue rows are checked against the gate; blocked tickers in stage_2+ are treated as BLOCKER failures.

## Safety Checks
- Audit does not fetch new tickers or mutate 03 outputs.
- Safety keyword scan ignores explicit negative-policy lines such as no_target_price: true.
- No official BCTC/PDF/OCR/Step19/REAL-DATA-02 checks are executed.

## Blockers Before Next Step
- none
