# REAL-DATA-01I-E official finance document download run

## Command run
`python.exe scripts\run_official_finance_candidate_download_01ie.py --refined-seed-file data\reports\official_finance_documents_01id_patch1\refined_seed_candidates_01id_patch1.csv --candidate-file data\reports\official_finance_documents_01id_patch1\official_document_link_candidates.csv --output-dir data\reports\official_finance_documents_01ie --raw-output-dir data\raw\official_finance_documents\01ie --request-sleep-seconds 2.5 --timeout-seconds 30 --max-documents 60 --max-depth1-documents-per-page 3 --allow-partial`

## Refined seed rows loaded
103

## Unique tickers
10

## Direct documents attempted
50

## HTML pages attempted
10

## Depth-1 candidates found
146

## Documents downloaded
58

## HTML snapshots saved
12

## PDF/XLSX/XLS count
- pdf: 58
- xlsx: 0
- xls: 0

## Standalone vs consolidated count
- consolidated: 35
- standalone: 22

## Manual review rows
96

## Status by ticker
- FPT: HAS_VERIFIED_OFFICIAL_DOCUMENT_FILE (files=9, html=6, manual=True)
- GMD: ONLY_FAILED_OR_BLOCKED (files=0, html=0, manual=True)
- HSG: ONLY_FAILED_OR_BLOCKED (files=0, html=0, manual=True)
- KDH: HAS_VERIFIED_OFFICIAL_DOCUMENT_FILE (files=2, html=0, manual=True)
- NLG: HAS_VERIFIED_OFFICIAL_DOCUMENT_FILE (files=17, html=0, manual=True)
- PVS: HAS_VERIFIED_OFFICIAL_DOCUMENT_FILE (files=19, html=0, manual=True)
- SSI: HAS_VERIFIED_OFFICIAL_DOCUMENT_FILE (files=9, html=0, manual=True)
- TCM: NEEDS_MANUAL_SEARCH (files=0, html=0, manual=True)
- VGC: HAS_VERIFIED_OFFICIAL_DOCUMENT_FILE (files=2, html=6, manual=True)
- VND: NEEDS_MANUAL_SEARCH (files=0, html=0, manual=True)

## Main blockers
- SOURCE_BLOCKED_OR_JS_REQUIRED: 5

## Next recommended action
Review failed, standalone, and HTML-only documents before adding a parsing contract. Do not run REAL-DATA-02 or Step19 yet.

- depth1 documents downloaded: 8
- finance_parse_ready: False