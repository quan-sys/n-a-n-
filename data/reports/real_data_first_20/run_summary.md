# REAL-DATA-01 Run Summary

- run_id: real_data_first_20_2026_06_04T02_26_27_00_00
- run_type: REAL-DATA-01
- mode: real
- data_type: real source data
- run_status: INSUFFICIENT_DATA_FOR_STEP18
- dry_run_status: PIPELINE_DRY_RUN_PARTIAL
- started_at: 2026-06-04T02:26:27+00:00
- finished_at: 2026-06-04T02:28:30+00:00
- tickers_requested: 20
- tickers_ingested: 20
- ticker_list: DPP, SDA, CLH, DND, DBT, CCR, NOS, DPH, DSN, WSS, STC, CFM, VPG, DST, DCV, MBN, HPG, VGC, VCS, HT1
- datasets_attempted: universe, company_profile, market_price, financial_statement_summary, disclosure_status
- datasets_succeeded: universe
- datasets_failed_or_partial: company_profile, market_price, financial_statement_summary, disclosure_status
- row_counts_by_dataset: {"company_profile": 20, "disclosure_status": 0, "financial_statement_summary": 0, "market_price": 576, "universe": 20}
- dataset_status: {"company_profile": "PARTIAL_REAL_DATA_INGESTED", "disclosure_status": "REAL_DATA_NOT_AVAILABLE", "financial_statement_summary": "REAL_DATA_NOT_AVAILABLE", "market_price": "PARTIAL_REAL_DATA_INGESTED", "universe": "REAL_DATA_INGESTED"}
- output_contains_mock_sample: False
- step19_implemented: False
- next_recommended_action: fix real/manual data source availability first

## Pipeline Stages Through Step 18
- raw_to_clean: SUCCESS_WITH_WARNINGS (input=616, output=616)
- data_quality: SUCCESS_WITH_WARNINGS (input=616, output=616)
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
