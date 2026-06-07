# Project Context Handoff Through REAL-DATA-01I-F

Repository: `https://github.com/quan-sys/n-a-n-`

Branch: `codex/vietnam-stock-pipeline`

This handoff is for starting a fresh Codex chat without losing project state. It summarizes the repo and reports through REAL-DATA-01I-F. It does not add new ingestion or parser logic.

## 1. Project Purpose

This is a Vietnamese stock screening, watchlist, and evidence system.

It is not a buy/sell recommendation system.

The system must not create target prices and must not automatically recommend buying or selling any stock.

The goal is source-backed evidence, confidence status, reject logs, data quality status, manual review queues, weekly review/watchlist outputs, and traceable decisions.

Core integrity rules from `PROJECT_CONTEXT.md` and `AGENTS.md`:

- Do not invent financial data.
- Do not hardcode fake financial data outside tests or mock fixtures.
- Every score must include confidence or data quality status.
- Every rejected stock must have a reject reason.
- Missing, stale, or conflicting data must not be silently ignored.
- Pre-L0 and L0 filters must run before business classification.
- Do not compare companies from unrelated sectors.
- Do not add layers beyond L0-L7.
- Do not fetch real data unless explicitly requested.

## 2. Current Strategic State

The project is blocked by free-data readiness.

`vnstock` is currently usable only as fallback/provisional finance evidence. It must not be treated as high-confidence when it is the only finance source.

The current strategy has pivoted from one-source ingestion toward official/source-backed free documents:

- company investor relations pages
- official company websites
- exchange filings where accessible
- official PDF/XLSX/HTML snapshots
- source-backed manual review where automation cannot parse usable values

Official document discovery and downloads now work partially, but usable official finance value parsing is not ready.

## 3. Layer And Roadmap State

Pipeline layers:

| Layer | Purpose | Current state |
|---|---|---|
| Pre-L0 | Universe and data sanity | Implemented for current contracts/dry runs |
| L0 | Trash/basic investability filter | Implemented for available clean data |
| L1 | Business classification | Implemented with confidence, evidence, warnings, manual review |
| L2 | Indicator registry | Implemented as definitions/mappings, not value calculation |
| L3 | Sector cycle | Implemented through Step 18, no Step 19 logic |
| L4 | Company engine | Not implemented |
| L5 | Valuation/risk | Not implemented |
| L6 | Timing/liquidity | Not implemented |
| L7 | Reports/manual review | Partially present through reports and queues |

Important gates:

- Step19 / L4 Company Engine is not implemented.
- REAL-DATA-02 has not been run.
- Do not scale while finance/disclosure evidence readiness is insufficient.

## 4. Completed Steps And Commits

| Step | Commit | Purpose | Key outputs | Result | Readiness decision |
|---|---|---|---|---|---|
| REAL-DATA-01I | `41d9a3a` / `41d9a3a878b9ea63ea1ff82817ada3918b876f50` | Finance web source probing/reconciliation | `data/reports/finance_web_sources_01i/*` | `vnstock` parsed only; 422 finance rows | Finance partial; do not scale |
| REAL-DATA-01I-B | `e4ffdca` / `e4ffdcad9693769476fae41f8933cf977d065441` | Official finance document seed schema/downloader infrastructure | `data/reports/official_finance_documents_01ib/*` | Dry-run infrastructure ready; 2 example seed rows | No finance parse yet |
| REAL-DATA-01I-B-PATCH1 | `516c7d3` / `516c7d3cfa5b91afab82abeb537a9176776dd2c7` | Fix dry-run document status reporting | Same 01IB report path | Dry-run reporting corrected | Infrastructure only |
| REAL-DATA-01I-C | `2071d7f` / `2071d7fba44e7240d9ab185afbb5cc7fda33eb90` | Verify initial real official seed links | `data/reports/official_finance_documents_01ic/*` | 42 real seed links attempted; no PDF/XLSX downloaded | Seed quality weak |
| REAL-DATA-01I-D | `7bb2d1e` / `7bb2d1e80d5480cf1e578b9f002d0d13ec73afff` | Repair official seed links with HTTPS-first policy | `data/reports/official_finance_documents_01id/*` | 1372 candidate links extracted; 2 reviewable | Candidate discovery partial |
| REAL-DATA-01I-D-PATCH1 | `13585e1` / `13585e1a7ccd6ce4f2c0222557ce1d97d5fb0913` | Calibrate official finance candidate scoring | `data/reports/official_finance_documents_01id_patch1/*` | Reviewable candidates increased to 107; 10 tickers covered | Still no finance values |
| REAL-DATA-01I-E | `52c96ca` / `52c96caa64879aeb22004b5ee40f9431d218436c` | Download verified official finance document candidates | `data/reports/official_finance_documents_01ie/*`, `data/raw/official_finance_documents/01ie/*` | 58 PDFs downloaded, 12 HTML snapshots saved | Official document files partial, parse not ready |
| REAL-DATA-01I-F | `d27e2da` / `d27e2da50c94aa724c582d486a27f02a65e56e4b` | Select official PDFs and attempt parsing | `data/reports/official_finance_parse_01if/*` | 20 selected, 18 parsed, 0 strict usable values | Official finance parse not ready |
| Security hygiene after 01I-F | `b0d37f4` / `b0d37f46173c0ede254dc82a52ab49fa8363590f` | Redact credential-like tokens from public text snapshots | `src/ingestion/secret_redaction.py`, snapshot writers | Public HTML snapshots redacted; history rewritten/pushed | Not finance logic |

## 5. REAL-DATA-01I Result Summary

Report folder: `data/reports/finance_web_sources_01i/`

Command recorded in report:

```powershell
python.exe scripts\run_finance_web_sources_01i.py --tickers VCB,BID,CTG,MBB,ACB,HPG,HSG,VHM,KDH,NLG,SSI,VND,GAS,PVS,FPT,MWG,VGC,GMD,VHC,TCM --sources vnstock,cafef,vietstock,company_ir,annual_report_pdf,exchange_filing --periods 2026-Q1,2025-Q4,2025 --output-dir data\reports\finance_web_sources_01i --raw-snapshot-dir data\raw\source_snapshots\01i --request-sleep-seconds 3.2 --allow-partial
```

Confirmed numbers:

- Tickers requested: 20
- Sources attempted: `vnstock,cafef,vietstock,company_ir,annual_report_pdf,exchange_filing`
- Sources accessible/parsed: `vnstock` only
- Finance candidate rows: 422
- Normalized candidate rows: 422
- Net profit rows: 40
- Operating cash flow rows: 40
- Conflicts: 0
- Unresolved required fields rows: 124
- `finance_ready_for_l0`: `Partial`
- `disclosure_ready_for_l0_from_01h`: `Partial`
- `finance_disclosure_ready_for_step18`: `False`
- `should_run_REAL_DATA_02`: `No`
- `should_implement_Step19_now`: `No`

Conclusion: 01I proved `vnstock` alone is not enough. Finance remains single-source and cannot support high-confidence scaling or Step19.

## 6. Official Document Route Summary

### 01I-B

Report folder: `data/reports/official_finance_documents_01ib/`

- Built seed schema, downloader/index infrastructure, and manual-review queue wiring.
- Dry-run seed rows loaded: 2
- Valid seed rows: 2
- Documents attempted: 0
- Status: `DRY_RUN_VALIDATED`: 2
- Downloaded/HTML saved: 0
- Finance parse: not implemented in 01I-B

### 01I-C

Report folder: `data/reports/official_finance_documents_01ic/`

- Ran 42 real initial seed links for 20 representative tickers.
- Documents attempted: 42
- HTML snapshots: 11
- Blocked/JS: 11
- Failed/unavailable: 20
- Manual review rows: 31
- Downloaded PDF/XLSX: 0
- Conclusion: infrastructure works but initial seed quality was weak.

### 01I-D

Report folder: `data/reports/official_finance_documents_01id/`

- Extracted 1372 candidate links from HTML snapshots.
- HTTPS candidates: 1370
- HTTP candidates: 2
- High-confidence candidates: 0
- Reviewable candidates: 2
- Low-confidence candidates: 100
- Rejected candidates: 1270
- Bad seed rows: 35
- Manual review rows: 1415
- HTTPS-first policy ready: `True`
- No finance values were parsed. HTTPS links remain candidates only.

### 01I-D-PATCH1

Report folder: `data/reports/official_finance_documents_01id_patch1/`

- Calibrated finance candidate scoring.
- Candidates extracted: 1372
- High-confidence candidates: 0
- Reviewable candidates: 107
- Low-confidence candidates: 559
- Rejected candidates: 706
- Refined seed candidates: 103
- Tickers with high/reviewable candidates: 10
- Covered tickers: `FPT,GMD,HSG,KDH,NLG,PVS,SSI,TCM,VGC,VND`
- Still no finance values parsed.

### 01I-E

Report folder: `data/reports/official_finance_documents_01ie/`

Command recorded in report:

```powershell
python.exe scripts\run_official_finance_candidate_download_01ie.py --refined-seed-file data\reports\official_finance_documents_01id_patch1\refined_seed_candidates_01id_patch1.csv --candidate-file data\reports\official_finance_documents_01id_patch1\official_document_link_candidates.csv --output-dir data\reports\official_finance_documents_01ie --raw-output-dir data\raw\official_finance_documents\01ie --request-sleep-seconds 2.5 --timeout-seconds 30 --max-documents 60 --max-depth1-documents-per-page 3 --allow-partial
```

Confirmed numbers:

- Refined seed rows loaded: 103
- Unique tickers: 10
- Direct documents attempted: 50
- HTML pages attempted: 10
- Depth-1 candidates found: 146
- Documents downloaded: 58
- HTML snapshots saved: 12
- PDF: 58
- XLSX/XLS: 0
- Manual review rows: 96
- Depth-1 documents downloaded: 8
- `finance_parse_ready`: `False`

Ticker status:

- Verified official PDF/document file: `FPT,KDH,NLG,PVS,SSI,VGC`
- Blocked/failed: `GMD,HSG`
- Needs manual search: `TCM,VND`

Downloaded files are not finance values until parsed.

### 01I-F

Report folder: `data/reports/official_finance_parse_01if/`

Command recorded in report:

```powershell
python.exe scripts\run_official_finance_parse_01if.py --document-index data\reports\official_finance_documents_01ie\finance_document_index.csv --output-dir data\reports\official_finance_parse_01if --max-documents 40 --target-periods 2026-Q1,2025-Q4,2025,2025-Q3,2025-Q2 --allow-partial
```

Confirmed numbers:

- `selected_documents_for_parse.csv` rows: 75
- Selection statuses: `SELECTED_FOR_PARSE`: 20, `SKIPPED_OLD_PERIOD`: 23, `SKIPPED_UNSUPPORTED_FILE_TYPE`: 17, `REVIEW_ONLY_STANDALONE`: 15
- Documents selected: 20
- Documents parsed: 18
- Documents skipped: 55
- Text-extractable PDFs: 3
- Non-text/scanned PDFs: 17
- Candidate rows parsed: 24
- Strict usable candidate rows: 0
- Rows with detected field but missing value: 7
- `raw_value` nonblank rows: 0
- `value_vnd` nonblank rows: 0
- Coverage rows: 20
- Coverage statuses: `NO_TEXT_EXTRACTED`: 17, `INSUFFICIENT_PARSE`: 3
- Coverage found count: 0 for all ticker/period rows
- Manual review rows: 273
- `official_document_file_ready`: `True`
- `official_finance_parse_ready`: `False`
- `tickers_with_official_parse`: 0
- `finance_disclosure_ready_for_step18`: `False`
- `should_run_REAL_DATA_02`: `No`
- `should_implement_Step19_now`: `No`

Conclusion: 01I-F selected official PDFs successfully but failed to extract usable finance values. Do not proceed to 01I-G reconciliation or broader scaling until 01I-F-PATCH1 creates explicit usable rows.

## 7. Current Blocker

Official PDFs have been downloaded, but the current parser does not extract usable table/value data.

Observed blocker details:

- Many PDFs are scanned/image-only or not text-extractable.
- Table-heavy PDFs are not handled well by the current line-based parser.
- The parser can detect some labels such as revenue/net profit/equity, but `raw_value` and `value_vnd` remain blank.
- Candidate rows with blank values are not usable finance data.
- Downloaded PDFs, HTTPS links, and official domains are evidence of document existence only. They are not finance values.

## 8. Next Recommended Step

Next step:

```text
REAL-DATA-01I-F-PATCH1 - Improve Official PDF Text/Table Extraction Before Reconciliation
```

Patch goals:

- Add multi-backend PDF extraction where available: PyMuPDF, pdfplumber, pypdf, then existing fallback.
- Add table extraction without OCR.
- Improve parser for table rows and nearby numeric cells.
- Add unit detection: VND, thousand VND, million VND, billion VND, dong, nghin dong, trieu dong, ty dong.
- Emit usable candidate rows only when `field_name`, `raw_value`, `value_vnd`, `unit`, and evidence are explicit.
- Keep parse status/error rows separate from usable candidate rows.
- Do not OCR unless explicitly approved later.
- Do not infer missing values.
- Do not zero-fill.
- Do not go to 01I-G until usable rows exist.

## 9. Hard Rules And Safety Constraints

- Do not implement Step19.
- Do not run REAL-DATA-02.
- Do not create buy/sell recommendation logic.
- Do not create target price logic.
- Do not treat `vnstock`-only evidence as high-confidence.
- Do not treat HTTPS alone as finance evidence.
- Do not treat downloaded PDFs as finance values until values are parsed.
- Do not OCR unless explicitly approved later.
- Do not infer or zero-fill missing finance values.
- Do not silently overwrite conflicts.
- Do not hardcode real BCTC values in tests.
- Do not bypass login, paywall, CAPTCHA, anti-bot controls, or private APIs.

## 10. Important Output Files

All requested report folders were found.

| File | Status | Notes |
|---|---|---|
| `data/reports/finance_web_sources_01i/finance_01i_run_summary.md` | found | 01I command and readiness |
| `data/reports/finance_web_sources_01i/datasource_decision_report.md` | found | Do not scale, no Step19 |
| `data/reports/finance_web_sources_01i/finance_normalized_candidate_rows.csv` | found | 422 rows, vnstock only |
| `data/reports/finance_web_sources_01i/unresolved_required_fields.csv` | found | 124 rows |
| `data/reports/official_finance_documents_01ib/finance_document_index.csv` | found | 2 dry-run rows |
| `data/reports/official_finance_documents_01ic/finance_document_index.csv` | found | 42 real seed rows |
| `data/reports/official_finance_documents_01id/official_document_link_candidates.csv` | found | 1372 link candidates |
| `data/reports/official_finance_documents_01id_patch1/refined_seed_candidates_01id_patch1.csv` | found | 103 refined rows |
| `data/reports/official_finance_documents_01ie/finance_document_index.csv` | found | 75 index rows |
| `data/reports/official_finance_documents_01ie/document_download_status_by_ticker.csv` | found | 10 ticker status rows |
| `data/reports/official_finance_parse_01if/selected_documents_for_parse.csv` | found | 75 rows, 20 selected |
| `data/reports/official_finance_parse_01if/official_finance_candidate_rows_01if.csv` | found | 24 parser candidate rows, 0 strict usable |
| `data/reports/official_finance_parse_01if/official_finance_field_coverage_01if.csv` | found | 20 rows, found=0 |
| `data/reports/official_finance_parse_01if/datasource_decision_report.md` | found | Parse not ready |

## 11. Relevant Code Map

Finance web/source probing:

- `src/ingestion/finance_web_source_probe.py`
- `src/ingestion/finance_candidate_normalizer.py`
- `src/ingestion/finance_numeric_reconciliation.py`
- `scripts/run_finance_web_sources_01i.py`

Official document seed/download/discovery:

- `src/ingestion/official_finance_document_seed.py`
- `src/ingestion/official_finance_document_downloader.py`
- `src/ingestion/official_finance_link_extractor.py`
- `src/ingestion/official_finance_seed_repair.py`
- `src/ingestion/official_finance_candidate_downloader.py`
- `src/ingestion/official_finance_html_document_finder.py`
- `src/ingestion/official_finance_document_verifier.py`
- `scripts/run_official_finance_document_seed_01ib.py`
- `scripts/run_official_finance_seed_repair_01id.py`
- `scripts/run_official_finance_candidate_download_01ie.py`

Official parse path:

- `src/ingestion/official_finance_document_selector.py`
- `src/ingestion/official_pdf_text_extractor.py`
- `src/ingestion/official_finance_table_extractor.py`
- `src/ingestion/official_finance_value_parser.py`
- `src/ingestion/official_finance_parse_evidence.py`
- `scripts/run_official_finance_parse_01if.py`

Security/snapshot hygiene:

- `src/ingestion/secret_redaction.py`
- `src/ingestion/source_snapshot.py`
- `src/ingestion/official_finance_document_downloader.py`

## 12. Commands And Tests Status

Commands used for this handoff:

```powershell
git status --short --branch
git log --oneline --decorate -n 30
python -m pytest -q
```

Known test status before creating this handoff:

- Full suite after latest code patch: `434 passed`
- Focused redaction/downloader tests after history rewrite: `9 passed`

This handoff task should run full pytest again before commit/push.

## Suggested First Prompt For New Codex Chat

```text
Read PROJECT_CONTEXT.md, AGENTS.md, and PROJECT_CONTEXT_HANDOFF_01IF.md first. Continue from REAL-DATA-01I-F-PATCH1. Do not run REAL-DATA-02 or implement Step19. The current blocker is official PDF/table extraction: 01I-F selected official PDFs but produced 0 usable parsed finance values. Implement the patch described in the handoff: multi-backend text/table extraction without OCR, table-row parser, unit detection, and usable candidate rows only when value_vnd is explicit.
```
