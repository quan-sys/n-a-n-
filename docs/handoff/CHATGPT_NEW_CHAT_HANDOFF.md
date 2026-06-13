# Handoff cho ChatGPT mới

## Mục tiêu dự án

Dự án `quan-sys/n-a-n-` là pipeline sàng lọc cổ phiếu Việt Nam theo hướng evidence-first. Hệ thống dùng để hỗ trợ con người rà soát watchlist, kiểm tra chất lượng dữ liệu, tạo queue review BCTC/BCTN thủ công, và theo dõi tín hiệu theo layer.

Đây không phải hệ thống khuyến nghị đầu tư. Không được tạo kết luận mua/bán/nắm giữ, giá mục tiêu, giá trị hợp lý, biên an toàn, lợi suất kỳ vọng, hoặc danh sách "cổ phiếu nên mua".

## Repo và nhánh

- Repo: `quan-sys/n-a-n-`
- Branch: `codex/vietnam-stock-pipeline`
- Baseline code head trước gói handoff: `820ae4f6a6b4d87e2668e101ef4da0bc5e705b6f`
- Project mode: `PRIMARY_ONLY_SCREENING_MODE`

## Guardrails bắt buộc

- Không bịa dữ liệu tài chính.
- Không zero-fill trường thiếu.
- Không OCR/PDF/BCTC trong task hiện tại.
- Không thêm logic khuyến nghị hoặc định giá tuyệt đối.
- Không coi dữ liệu `vnstock`/primary-only là high-confidence.
- Missing/stale/conflicting data phải được ghi rõ và làm giảm confidence.
- Mỗi ticker bị loại hoặc bị block phải có lý do.
- Pre-L0 và L0 phải đi trước phân loại sector.
- Không so sánh doanh nghiệp khác ngành không liên quan.

## Trạng thái nguồn dữ liệu

- `market_source_confidence`: `PROVISIONAL_PRIMARY_ONLY`
- `finance_source_confidence_default`: `PROVISIONAL_LOW`
- `crosscheck_status`: `NOT_AVAILABLE`
- `verification_status`: `NEEDS_MANUAL_BCTC_REVIEW`

Các output hiện tại là provisional/evidence context để phục vụ review, chưa phải dữ liệu tài chính official verified.

## Thiết kế layer

- Pre-L0: dựng universe, kiểm tra ticker/exchange/listing/profile/price/volume/finance/disclosure nếu có.
- L0: trash/basic investability filter, loại mã quá thiếu dữ liệu hoặc không đủ điều kiện cơ bản.
- L1: business classification theo micro-sector, archetype, driver, exposure weight.
- L2: indicator registry cho core/archetype/sector-specific indicators.
- L3: sector cycle engine, gồm distress/recovery/overheating/structural/anomaly/confidence.
- L4: company engine trong peer group đúng ngành, gồm survival gate và peer quality context.
- L5: valuation/risk context chỉ khi đủ dữ liệu, không tạo giá mục tiêu.
- L6: timing/liquidity context, không tạo hành động mua/bán/nắm giữ.
- L7: report/manual review/evidence table/reject log/weekly review.

## Tóm tắt Step05A đến Step28

| Step | Commit | Trạng thái chính | Output chính |
|---|---:|---|---|
| Step05A primary-only screening | `169e1f721de21b9fc49255e7c222c79371e5bf81` | 20/20 processed, 20 watchlist candidates, 20 manual BCTC queue, `CONDITIONAL_GO_FOR_MANUAL_BCTC_REVIEW` | `data/reports/step05a_primary_only_screening/` |
| Step20 L5 valuation/risk context | `50e6d57e288306d8fcf205a50239b9126383256b` | 20 processed, 20 manual review, 15 insufficient data, `PASS_WITH_MANUAL_REVIEW_WARNINGS` | `data/reports/step20_l5_valuation_risk_context/` |
| Step21 L6 timing/liquidity context | `374a23b53662aceed9f6ba7d4f6e25546b3cc760` | 20 processed, 20 manual review, timing/liquidity context only, `PASS_TIMING_LIQUIDITY_CONTEXT_WITH_WARNINGS` | `data/reports/step21_l6_timing_liquidity_context/` |
| Step22 L7 weekly report/manual review | `eff8b25c174ce7a708ebe3ab7cd3858996755acf` | 20 processed, 6 watch-only, 14 manual review, no rejects, `PASS_WEEKLY_REPORT_WITH_WARNINGS` | `data/reports/step22_l7_weekly_report_manual_review/` |
| Step23 monitoring/backtest module | `196ea51cf4b1f71f47ee34834e41464d9c96841b` | 20 processed, monitoring CSVs created, no prior trend baseline, `PASS_MONITORING_WITH_WARNINGS` | `data/reports/step23_backtest_monitoring_module/` |
| Step24 integration/readiness | `5a5199b0dd71e27695db03e1ae6e27b9b88b8e17` | 7 required artifacts present, source/manual-review checks passed, `PASS_FINAL_INTEGRATION_WITH_WARNINGS` | `data/reports/step24_final_integration_scale_readiness/` |
| Step25 full universe scale | `d99fb24001c809fa205e015ce9b9ed6cb7b8ede8` | 1,743 processed from 1,800 actual universe; 16 candidates; 1,727 blocked for insufficient market data; 0 failed tickers | `data/reports/step25_full_universe_1743_primary_only_scale/` |
| Step26 output audit + first shortlist | `15e41c68124dcbe134bf67025110a6d418626005` | 1,743 read; 16 first review shortlist; 16 manual BCTC queue; 1,727 data repair priority rows | `data/reports/step26_full_universe_output_audit_first_shortlist/` |
| Step27 data coverage repair probe | `85aad9f80e26f84de8983f33dc21ac4cbba0f7ab` | 166 probe tickers; 17 direct fetch OK; 149 errors; 17 Step26-blocked tickers fetchable; paid market data not yet justified | `data/reports/step27_data_coverage_repair_probe/` |
| Step28 vnstock/VCI market snapshot refresh | `820ae4f6a6b4d87e2668e101ef4da0bc5e705b6f` | Full run was stopped; script fixed; smoke `--limit 30` passed with 28 OK, 2 failed, 28 Step26-blocked recovered | `data/reports/step28_full_universe_market_snapshot_refresh_vnstock/` |

All listed step summaries report `forbidden_terms_found: []`. Step20 through Step28 report `core_outputs_modified: false`.

## Current blocker

Step26 showed 1,727 tickers blocked as `BLOCKED_INSUFFICIENT_MARKET_DATA`. Step27 and Step28 smoke show that some of these tickers can be fetched directly from `vnstock` source `VCI`. The blocker is now market snapshot coverage in the pipeline/cache/fetch layer, not an immediate decision to buy paid market data.

Step28 full universe has not been rerun after the smoke test. Current Step28 outputs only cover 30 attempted tickers.

## Exact next action

Run Step28 full universe from the repo root, without `--limit`:

```powershell
python scripts/run_step28_full_universe_market_snapshot_refresh_vnstock.py --config config/step28_full_universe_market_snapshot_refresh_vnstock.yaml
```

This should resume from the existing smoke checkpoint unless `--force-refresh` is passed. Do not use `--force-refresh` unless the user explicitly wants to re-fetch tickers already recorded in success/failed CSVs.

After Step28 full run completes, planned next step is `STEP29_RERUN_AUDIT_AFTER_MARKET_REFRESH`: rerun/audit the full-universe outputs using refreshed market snapshot coverage, rebuild the review queues, and report recovery impact. Step29 must still avoid recommendations, price targets, OCR, BCTC parsing, and zero-filled finance values.

## How the new assistant should respond

1. Read this handoff first.
2. Use GitHub/repo tools to verify branch, latest HEAD, and whether the handoff commit is present.
3. Read `PROJECT_CONTEXT.md` before implementing anything.
4. Confirm Step28 full run has not already been completed by checking `data/reports/step28_full_universe_market_snapshot_refresh_vnstock/step28_market_refresh_summary.json`.
5. Continue with Step28 full run only if the user asks to proceed.
6. Report counts and output paths, not investment conclusions.

## Warning

The current artifacts are safe for engineering continuation and manual review planning. They are not safe to paste as investment advice and must not be reframed that way.
