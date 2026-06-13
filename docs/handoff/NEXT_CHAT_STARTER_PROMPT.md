# Next Chat Starter Prompt

Read this handoff context first.

You are continuing the Vietnamese stock screener/evidence pipeline repo `quan-sys/n-a-n-` on branch `codex/vietnam-stock-pipeline`.

Before giving status or implementing anything:

1. Use GitHub/repo tools to verify the current branch, latest HEAD, and recent commits.
2. Read `PROJECT_CONTEXT.md`.
3. Read these handoff files:
   - `docs/handoff/CHATGPT_NEW_CHAT_HANDOFF.md`
   - `docs/handoff/CODEX_CONTINUATION_HANDOFF.md`
   - `docs/handoff/DATA_ARTIFACTS_INDEX.md`
   - `docs/handoff/CURRENT_STATUS_SHORT.md`
   - `docs/handoff/handoff_state.json`

Project goal: build a modular Vietnamese stock screening pipeline for human review. It must produce evidence tables, confidence/data-quality status, reject reasons, manual review queues, and reports. It must not produce investment recommendations.

Hard guardrails:

- Do not make buy/sell/hold recommendations.
- Do not create target price, fair value, intrinsic value, margin of safety, or expected return logic.
- Do not fabricate financial data.
- Do not zero-fill missing fields.
- Do not OCR or parse PDFs unless explicitly approved in a later task.
- Do not treat `vnstock`/primary-only data as high-confidence.
- Missing/stale/conflicting data must reduce confidence or create manual review flags.
- Every blocked/rejected ticker must have a reason.
- Pre-L0 and L0 must run before sector classification.

Current status:

- Pipeline framework is built through Step28.
- Step25 scaled to 1,743 tickers.
- Step26 found 1,727 tickers blocked as `BLOCKED_INSUFFICIENT_MARKET_DATA` and only 16 first-review candidates.
- Step27 proved 17 blocked/sample tickers could be fetched directly from `vnstock`/VCI, so paid market data is not yet justified.
- Step28 was created to refresh full-universe market snapshot from `vnstock`/VCI.
- The first Step28 full run was stopped because it ran too long without visible progress.
- Step28 was fixed with visible progress logs, strict per-ticker timeout, retry cap, per-ticker checkpointing, resume support, smoke controls, and UTF-8-safe logging.
- Step28 smoke test with `--limit 30` passed: 30 attempted, 28 OK, 2 failed, 28 Step26-blocked recovered.
- Step28 full universe has not been rerun after the smoke test.

Next action:

Run Step28 full universe from repo root, without `--limit`:

```powershell
python scripts/run_step28_full_universe_market_snapshot_refresh_vnstock.py --config config/step28_full_universe_market_snapshot_refresh_vnstock.yaml
```

This should resume from the existing smoke checkpoint unless `--force-refresh` is passed.

After Step28 full run completes, continue with `STEP29_RERUN_AUDIT_AFTER_MARKET_REFRESH`: rebuild/audit the shortlist and manual review queues using refreshed market coverage. Keep finance data provisional until official BCTC/BCTN review exists.

When responding to the user, report engineering status, counts, output paths, validation, and next command. Do not present the outputs as investment advice.
