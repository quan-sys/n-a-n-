# Finance/Disclosure Retry Summary

- ticker_count: 20
- finance_coverage_rows: 20
- finance_rows_with_total_assets: 20
- disclosure_coverage_rows: 20
- disclosure_rows_treated_as_clean_false: 20
- failed_ticker_records: 40
- step19_implemented: False
- output_contains_prohibited_recommendation_fields: False

## Source Requests
- financial_statement_summary via vnstock:vci: attempted=61, succeeded=60, failed=1, skipped=0
- disclosure_status via vnstock:kbs: attempted=40, succeeded=40, failed=0, skipped=0

## Notes
- Missing financial fields remain blank; no zeros or inferred values are generated.
- Missing disclosure remains unavailable/unknown and is not treated as clean.
