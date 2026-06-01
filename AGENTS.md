# Codex Instructions

Before implementing anything, always read `PROJECT_CONTEXT.md` and follow it
strictly.

Core rules for future Codex tasks:

- Preserve existing functionality unless the task explicitly says otherwise.
- Do not make buy/sell recommendations.
- Do not invent financial data.
- Do not hardcode fake financial data outside tests or mock fixtures.
- Every score must include confidence or data quality status.
- Every rejected stock must have a reject reason.
- Pre-L0 and L0 filters must run before sector classification.
- Do not compare companies from unrelated sectors.
- Do not silently ignore missing, stale, or conflicting data.
- Do not add layers beyond L0-L7.
- Do not fetch real data unless the task explicitly requests it.
- Do not implement scoring logic before the required upstream contracts exist.
- Before implementing any filter or scoring layer, verify that the required
  upstream data ingestion and clean data assumptions are already implemented. If
  not, stop and implement the missing upstream step first.
