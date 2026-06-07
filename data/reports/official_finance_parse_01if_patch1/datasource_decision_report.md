# Datasource decision report

- official_document_file_ready: True
- official_finance_parse_ready: False
- official_finance_candidate_rows: 0
- usable_official_finance_candidate_rows: 0
- tickers_with_official_parse: 0
- tickers_with_usable_official_parse: 0
- finance_ready_for_l0: unchanged
- finance_disclosure_ready_for_step18: False
- should_run_REAL_DATA_02: No
- should_implement_Step19_now: No

01I-F emits source-backed official parser candidate rows only. Do not run 01I-G reconciliation until usable official value rows exist.