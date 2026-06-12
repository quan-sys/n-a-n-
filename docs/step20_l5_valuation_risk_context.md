# STEP20 L5 Valuation/Risk Context

STEP20 creates provisional L5 context for the existing watchlist pipeline. It is
not investment advice and it does not create action labels.

The step remains primary-only:

- market source confidence stays `PROVISIONAL_PRIMARY_ONLY`
- finance source confidence stays `PROVISIONAL_LOW`
- cross-check status stays `NOT_AVAILABLE`
- verification status stays `NEEDS_MANUAL_BCTC_REVIEW`

The engine reads existing Step05A, Step19, market, and provisional finance
artifacts. It does not fetch official BCTC files, run OCR, scrape PDFs, or
upgrade any source to verified.

Peer context is only built inside the same micro-sector/archetype group. When
the peer group is too small or required fields are missing, the row is routed to
manual review.

Run:

```bash
python scripts/run_step20_l5_valuation_risk_context.py \
  --config config/step20_l5_valuation_risk_context.yaml \
  --limit 100 \
  --output-dir data/reports/step20_l5_valuation_risk_context \
  --allow-partial
```

Outputs:

- `step20_valuation_risk_summary.json`
- `step20_valuation_risk_rows.csv`
- `valuation_context_by_ticker.csv`
- `risk_flags_by_ticker.csv`
- `manual_review_queue_step20.csv`
- `peer_context_summary.csv`
- `evidence_debt_step20.json`
- `run_manifest.json`

The next step may use this context as cautious input for timing/liquidity
analysis, while preserving all manual BCTC review requirements.
