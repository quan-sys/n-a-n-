# REAL-DATA-01G Source Probe Summary

- command: python.exe scripts\run_multi_source_probe_01g.py --tickers VCB,BID,CTG,MBB,ACB,HPG,HSG,VHM,KDH,NLG,SSI,VND,GAS,PVS,FPT,MWG,VGC,GMD,VHC,TCM --datasets financial_statement_summary,disclosure_status --sources vnstock,cafef,vietstock,hose,hnx,ssc --output-dir data\reports\multi_source_probe_01g --raw-output-dir data\raw --request-sleep-seconds 3.2 --allow-partial
- source_categories_attempted: cafef, hnx, hose, ssc, vietstock, vnstock
- accessible_or_schema_unknown_sources: hose, vnstock
- blocked_or_js_required_sources: cafef, ssc, vietstock
- parse_failed_sources: vnstock
- finance_candidate_rows: 145
- disclosure_candidate_rows: 0
- finance_ready_for_l0: False
- disclosure_ready_for_l0: False
- finance_disclosure_ready_for_step18: False
- step19_implemented: False

Missing finance fields remain missing. Missing disclosure rows are not clean.
