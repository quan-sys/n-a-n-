# REAL-DATA-01I finance web sources run summary

- command: `python.exe scripts\run_finance_web_sources_01i.py --tickers VCB,BID,CTG,MBB,ACB,HPG,HSG,VHM,KDH,NLG,SSI,VND,GAS,PVS,FPT,MWG,VGC,GMD,VHC,TCM --sources vnstock,cafef,vietstock,company_ir,annual_report_pdf,exchange_filing --periods 2026-Q1,2025-Q4,2025 --output-dir data\reports\finance_web_sources_01i --raw-snapshot-dir data\raw\source_snapshots\01i --request-sleep-seconds 3.2 --allow-partial`
- tickers requested: 20
- tickers: VCB,BID,CTG,MBB,ACB,HPG,HSG,VHM,KDH,NLG,SSI,VND,GAS,PVS,FPT,MWG,VGC,GMD,VHC,TCM
- periods requested: 2026-Q1,2025-Q4,2025
- sources attempted: vnstock,cafef,vietstock,company_ir,annual_report_pdf,exchange_filing
- sources accessible: vnstock
- sources parsed: vnstock
- failed/partial diagnostic rows: 5
- candidate rows by source: {'vnstock': 422}
- normalized rows by source: {'vnstock': 422}
- fields covered by source: {'vnstock': 'cash|equity|gross_profit|inventory|long_term_debt|net_profit|operating_cash_flow|operating_profit|revenue|short_term_debt|total_assets|total_liabilities'}
- net_profit rows: 40
- operating_cash_flow rows: 40
- conflicts: 0
- finance_ready_for_l0: Partial
- disclosure_ready_for_l0 from 01H: Partial
- finance_disclosure_ready_for_step18: False

No Step 19 logic, buy/sell logic, or target price logic was implemented.