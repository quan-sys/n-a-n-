# Pipeline Dry Run Summary

- run_id: real_data_first_20_2026_06_04T02_26_27_00_00
- run_size: mini
- started_at: 2026-06-04T02:28:28+00:00
- finished_at: 2026-06-04T02:28:30+00:00
- input_ticker_count: 20
- output_ticker_count: 20
- module_statuses: {"archetype_templates": "SUCCESS_WITH_WARNINGS", "data_quality": "SUCCESS_WITH_WARNINGS", "driver_registry": "SUCCESS_WITH_WARNINGS", "indicator_registry": "SUCCESS_WITH_WARNINGS", "l0_basic_investability_filter": "SUCCESS_WITH_WARNINGS", "l0_trash_filter": "SUCCESS_WITH_WARNINGS", "l1_business_classification": "SUCCESS_WITH_WARNINGS", "production_universe_builder": "SUCCESS_WITH_WARNINGS", "raw_to_clean": "SUCCESS_WITH_WARNINGS", "sector_cycle_engine": "SUCCESS_WITH_WARNINGS"}
- pass_counts_by_layer: {"driver_registry": 0, "indicator_registry": 0, "l0_basic_investability_filter": 0, "l0_trash_filter": 0, "l1_business_classification": 0, "pre_l0_universe": 0, "sector_cycle_engine": 0}
- reject_counts_by_layer: {"l0_basic_investability_filter": 15, "l0_trash_filter": 15, "l1_business_classification": 20, "pre_l0_universe": 0}
- manual_review_count: 287
- insufficient_data_count: 72
- warning_flags: ["MISSING_CLEAN_FIELD:company_profile:industry_raw", "MISSING_CLEAN_FIELD:company_profile:business_description", "MISSING_CLEAN_FIELD:financial_statement_summary:ticker", "MISSING_CLEAN_FIELD:financial_statement_summary:period", "MISSING_CLEAN_FIELD:financial_statement_summary:revenue", "MISSING_CLEAN_FIELD:financial_statement_summary:net_profit", "MISSING_CLEAN_FIELD:financial_statement_summary:equity", "MISSING_CLEAN_FIELD:financial_statement_summary:total_assets", "MISSING_CLEAN_FIELD:financial_statement_summary:total_liabilities", "MISSING_CLEAN_FIELD:disclosure_status:ticker", "MISSING_CLEAN_FIELD:disclosure_status:date", "MISSING_CLEAN_FIELD:disclosure_status:event_type", "MISSING_CLEAN_FIELD:disclosure_status:severity", "MISSING_INDUSTRY_RAW", "MISSING_BUSINESS_DESCRIPTION", "LOW_CONFIDENCE_RAW", "MISSING_DATA", "STALE_DATA", "OUTLIER_REVIEW", "SKIPPED_EMPTY_DATASET:financial_statement_summary", "SKIPPED_EMPTY_DATASET:disclosure_status", "MISSING_MARKET_DATA", "MISSING_FINANCIAL_DATA", "PROFILE_DATA_QUALITY_REVIEW", "MARKET_DATA_QUALITY_REVIEW", "MARKET_STALE_DATA", "MARKET_LOW_CONFIDENCE", "LOW_LIQUIDITY", "VERY_LOW_LIQUIDITY", "UPSTREAM_L0_CAUTION", "LOW_DATA_CONFIDENCE", "MARKET_CAP_MISSING", "UNKNOWN_DISCLOSURE_STATUS", "LOW_DATA_COVERAGE", "SUSPICIOUS_OUTLIER", "INSUFFICIENT_MARKET_DATA", "INSUFFICIENT_FINANCIAL_DATA", "FAILED_L0_TRASH_FILTER", "INSUFFICIENT_DATA_FOR_CLASSIFICATION", "FAILED_L0_BASIC_INVESTABILITY", "UNKNOWN_ARCHETYPE_TEMPLATE", "NOT_ELIGIBLE_FOR_DRIVER_RESOLUTION", "UNKNOWN_ARCHETYPE_FOR_INDICATOR_MAPPING", "UNKNOWN_MICRO_SECTOR_FOR_INDICATOR_MAPPING", "UNKNOWN_MICRO_SECTOR_FOR_SECTOR_CYCLE", "INSUFFICIENT_DATA_FOR_SECTOR_CYCLE"]
- error_count: 0
- next_action_recommendation: FIX_INGESTION_BEFORE_STEP_19
