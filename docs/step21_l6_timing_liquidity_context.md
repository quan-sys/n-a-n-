# STEP21 L6 Timing/Liquidity Context

STEP21 creates provisional timing and liquidity context for the existing
watchlist pipeline. It does not create trade instructions or price levels.

The step keeps the current evidence limits:

- market source confidence stays `PROVISIONAL_PRIMARY_ONLY`
- finance source confidence stays `PROVISIONAL_LOW`
- cross-check status stays `NOT_AVAILABLE`
- verification status stays `NEEDS_MANUAL_BCTC_REVIEW`

The engine reads existing Step20, Step05A, and current market artifacts. It does
not fetch new market data, scrape official BCTC files, run OCR, or infer missing
prices or volumes.

Run:

```bash
python scripts/run_step21_l6_timing_liquidity_context.py \
  --config config/step21_l6_timing_liquidity_context.yaml \
  --limit 100 \
  --output-dir data/reports/step21_l6_timing_liquidity_context \
  --allow-partial
```

Outputs:

- `timing_liquidity_context_summary.json`
- `timing_liquidity_context_rows.csv`
- `timing_warning_flags.csv`
- `liquidity_warning_flags.csv`
- `manual_review_queue.csv`
- `evidence_debt_report.json`
- `run_manifest.json`

These files are context inputs for the weekly report layer, not a trading
workflow.
