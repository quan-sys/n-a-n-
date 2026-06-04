# Pipeline Dry Run Summary

- run_id: real_data_first_20_2026_06_04T04_17_02_00_00
- run_size: mini
- started_at: 2026-06-04T04:26:39+00:00
- finished_at: 2026-06-04T04:26:42+00:00
- input_ticker_count: 20
- output_ticker_count: 20
- module_statuses: {"archetype_templates": "SUCCESS_WITH_WARNINGS", "data_quality": "SUCCESS_WITH_WARNINGS", "driver_registry": "SUCCESS_WITH_WARNINGS", "indicator_registry": "SUCCESS_WITH_WARNINGS", "l0_basic_investability_filter": "SUCCESS_WITH_WARNINGS", "l0_trash_filter": "SUCCESS_WITH_WARNINGS", "l1_business_classification": "SUCCESS_WITH_WARNINGS", "production_universe_builder": "SUCCESS_WITH_WARNINGS", "raw_to_clean": "SUCCESS_WITH_WARNINGS", "sector_cycle_engine": "SUCCESS_WITH_WARNINGS"}
- pass_counts_by_layer: {"driver_registry": 0, "indicator_registry": 0, "l0_basic_investability_filter": 0, "l0_trash_filter": 0, "l1_business_classification": 0, "pre_l0_universe": 0, "sector_cycle_engine": 0}
- reject_counts_by_layer: {"l0_basic_investability_filter": 5, "l0_trash_filter": 5, "l1_business_classification": 20, "pre_l0_universe": 0}
- manual_review_count: 400
- insufficient_data_count: 122
- warning_flags: ["MISSING_CLEAN_FIELD:financial_statement_summary:net_profit", "MISSING_CLEAN_FIELD:disclosure_status:ticker", "MISSING_CLEAN_FIELD:disclosure_status:date", "MISSING_CLEAN_FIELD:disclosure_status:event_type", "MISSING_CLEAN_FIELD:disclosure_status:severity", "STALE_DATA", "OUTLIER_REVIEW", "MISSING_REVENUE", "MISSING_NET_PROFIT", "MISSING_OPERATING_CASH_FLOW", "MISSING_INVENTORY", "LOW_CONFIDENCE_RAW", "MISSING_DATA", "SKIPPED_EMPTY_DATASET:disclosure_status", "MISSING_FINANCIAL_DATA", "MARKET_DATA_QUALITY_REVIEW", "FINANCIAL_DATA_QUALITY_REVIEW", "MARKET_STALE_DATA", "MARKET_LOW_CONFIDENCE", "FINANCIAL_LOW_CONFIDENCE", "LOW_LIQUIDITY", "SEVERE_DEBT_PRESSURE", "INSUFFICIENT_FINANCIAL_HISTORY", "MISSING_ESSENTIAL_FINANCIAL_FIELD_NET_PROFIT", "MISSING_ESSENTIAL_FINANCIAL_FIELD_OPERATING_CASH_FLOW", "VERY_LOW_LIQUIDITY", "UPSTREAM_L0_CAUTION", "SUSPICIOUS_OUTLIER", "LOW_DATA_CONFIDENCE", "MARKET_CAP_MISSING", "UNKNOWN_DISCLOSURE_STATUS", "LOW_DATA_COVERAGE", "ELEVATED_DEBT_PRESSURE", "INSUFFICIENT_FINANCIAL_DATA", "FAILED_L0_TRASH_FILTER", "INSUFFICIENT_DATA_FOR_CLASSIFICATION", "FAILED_L0_BASIC_INVESTABILITY", "UNKNOWN_ARCHETYPE_TEMPLATE", "NOT_ELIGIBLE_FOR_DRIVER_RESOLUTION", "UNKNOWN_ARCHETYPE_FOR_INDICATOR_MAPPING", "UNKNOWN_MICRO_SECTOR_FOR_INDICATOR_MAPPING", "UNKNOWN_MICRO_SECTOR_FOR_SECTOR_CYCLE", "INSUFFICIENT_DATA_FOR_SECTOR_CYCLE"]
- error_count: 0
- next_action_recommendation: FIX_INGESTION_BEFORE_STEP_19
