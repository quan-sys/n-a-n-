# REAL-DATA-01 Run Summary

- run_id: real_data_first_20_2026_06_04T04_17_02_00_00
- run_type: REAL-DATA-01
- mode: real
- ticker_selection: manual_list
- data_type: real source data
- run_status: INSUFFICIENT_DATA_FOR_STEP18
- dry_run_status: PIPELINE_DRY_RUN_PARTIAL
- started_at: 2026-06-04T04:17:02+00:00
- finished_at: 2026-06-04T04:26:43+00:00
- tickers_requested: 20
- tickers_ingested: 20
- ticker_list: VCB, BID, CTG, MBB, ACB, HPG, HSG, VHM, KDH, NLG, SSI, VND, GAS, PVS, FPT, MWG, VGC, GMD, VHC, TCM
- datasets_attempted: universe, company_profile, market_price, financial_statement_summary, disclosure_status
- datasets_succeeded: 
- datasets_failed_or_partial: universe, company_profile, market_price, financial_statement_summary, disclosure_status
- row_counts_by_dataset: {"company_profile": 20, "disclosure_status": 0, "financial_statement_summary": 20, "market_price": 1340, "universe": 20}
- dataset_status: {"company_profile": "SKIPPED_BY_ONLY_DATASETS", "disclosure_status": "REAL_DATA_NOT_AVAILABLE", "financial_statement_summary": "PARTIAL_REAL_DATA_INGESTED", "market_price": "SKIPPED_BY_ONLY_DATASETS", "universe": "SKIPPED_BY_ONLY_DATASETS"}
- output_contains_mock_sample: False
- step19_implemented: False
- manual_template_paths: {"disclosure_status": "data\\templates\\disclosure_status_template.csv", "financial_statement_summary": "data\\templates\\financial_statement_summary_template.csv"}
- next_recommended_action: fix real/manual data source availability first

## Pipeline Stages Through Step 18
- raw_to_clean: SUCCESS_WITH_WARNINGS (input=1400, output=1400)
- data_quality: SUCCESS_WITH_WARNINGS (input=1400, output=1400)
- production_universe_builder: SUCCESS_WITH_WARNINGS (input=20, output=20)
- l0_trash_filter: SUCCESS_WITH_WARNINGS (input=20, output=20)
- l0_basic_investability_filter: SUCCESS_WITH_WARNINGS (input=20, output=20)
- l1_business_classification: SUCCESS_WITH_WARNINGS (input=20, output=20)
- archetype_templates: SUCCESS_WITH_WARNINGS (input=20, output=20)
- driver_registry: SUCCESS_WITH_WARNINGS (input=20, output=20)
- indicator_registry: SUCCESS_WITH_WARNINGS (input=20, output=20)
- sector_cycle_engine: SUCCESS_WITH_WARNINGS (input=0, output=1)

## Errors
- none
