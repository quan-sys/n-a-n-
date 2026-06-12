# STEP05A Primary-Only Screening

STEP05A exists because the alternative-provider probes did not produce usable
independent current market observations in this environment. The pipeline can
still make progress, but it must be honest about the weak evidence.

Primary-only means STEP05A reads existing vnstock-derived market rows and the
existing provisional structured finance layer. It does not fetch official BCTC
files, run OCR, scrape PDFs, or promote any source to verified status.

`crosscheck_status` remains `NOT_AVAILABLE` because no independent current
source family has confirmed the primary market rows. Market confidence remains
`PROVISIONAL_PRIMARY_ONLY`, and finance confidence remains `PROVISIONAL_LOW`.

Every surviving ticker is sent to manual BCTC review. The output is a
provisional work queue for human evidence collection, not investment advice and
not a valuation workflow.

Run:

```bash
python scripts/run_step05a_primary_only_screening.py \
  --config config/step05a_primary_only_screening.yaml \
  --limit 100 \
  --output-dir data/reports/step05a_primary_only_screening \
  --allow-partial
```

Outputs:

- `primary_only_screening_summary.json`
- `primary_only_screening_rows.csv`
- `watchlist_candidates.csv`
- `manual_bctc_review_queue.csv`
- `blocked_tickers.csv`
- `evidence_debt_report.json`
- `run_manifest.json`

The next step should intake manually supplied BCTC evidence for the shortlist
only, then compare it against the provisional structured layer before any deeper
company analysis.
