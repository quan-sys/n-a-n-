# Multi-source Evidence Run Summary

- run_id: finance_web_sources_01i
- run_type: REAL-DATA-01F_MULTI_SOURCE_EVIDENCE
- finished_at: 2026-06-06T01:15:00+00:00
- requested_ticker_count: 20
- ticker_list: VCB, BID, CTG, MBB, ACB, HPG, HSG, VHM, KDH, NLG, SSI, VND, GAS, PVS, FPT, MWG, VGC, GMD, VHC, TCM
- source_category_count: 12
- available_source_dataset_pairs: 7
- field_level_evidence_rows: 14272
- source_conflict_rows: 80
- unresolved_required_field_rows: 124
- finance_ready_for_l0: False
- disclosure_ready_for_l0: False
- finance_disclosure_ready_for_step18: False
- finance_disclosure_ready_for_future_step19: False
- output_contains_mock_sample: False
- step19_implemented: False

## Guardrails

- This layer reconciles already-ingested evidence only.
- Missing values remain missing.
- Conflicting values require manual review.
- Missing disclosure rows are unknown/unavailable, not clean.
