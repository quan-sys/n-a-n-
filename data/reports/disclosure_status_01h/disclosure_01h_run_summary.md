# REAL-DATA-01H Disclosure Status Run Summary

- command: python.exe scripts\run_disclosure_status_01h.py --representative-tickers VCB,BID,CTG,MBB,ACB,HPG,HSG,VHM,KDH,NLG,SSI,VND,GAS,PVS,FPT,MWG,VGC,GMD,VHC,TCM --sources hose,hnx,ssc,cafef,vietstock,vnstock --output-dir data\reports\disclosure_status_01h --raw-snapshot-dir data\raw\source_snapshots\01h --request-sleep-seconds 3.2 --allow-partial
- sources_attempted: hose, hnx, ssc, cafef, vietstock, vnstock
- sources_accessible: hose
- sources_parsed: hose
- source_failures: hnx:WARNING_LIST:SOURCE_SSL_FAILED/SOURCE_SSL_FAILED; hnx:TRADING_RESTRICTION_LIST:SOURCE_SSL_FAILED/SOURCE_SSL_FAILED; hnx:CONTROL_LIST:SOURCE_SSL_FAILED/SOURCE_SSL_FAILED; ssc:SSC_SANCTION_LIST:SOURCE_BLOCKED_OR_JS_REQUIRED/SOURCE_BLOCKED_OR_JS_REQUIRED; cafef:DISCLOSURE_VIOLATION_LIST:SOURCE_BLOCKED_OR_JS_REQUIRED/SOURCE_BLOCKED_OR_JS_REQUIRED; vietstock:DISCLOSURE_VIOLATION_LIST:SOURCE_BLOCKED_OR_JS_REQUIRED/SOURCE_BLOCKED_OR_JS_REQUIRED; vnstock:DISCLOSURE_VIOLATION_LIST:SOURCE_BLOCKED_OR_JS_REQUIRED/SOURCE_BLOCKED_OR_JS_REQUIRED
- positive_control_tickers: 20
- positive_control_warning_rows: 74
- disclosure_candidate_rows: 129
- source_checked_no_warning_rows: 320
- unavailable_or_schema_failed_rows: 80
- evidence_layer_disclosure_ready_for_l0: False
- disclosure_ready_for_l0: Partial
- finance_disclosure_ready_for_step18: False
- step19_implemented: False

Source-checked not found rows are not a guarantee of clean disclosure.
Source failure rows are not treated as no-warning.
