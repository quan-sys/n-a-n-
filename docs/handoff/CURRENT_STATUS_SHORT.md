# Current Status Short

1. Repo: `quan-sys/n-a-n-`
2. Branch: `codex/vietnam-stock-pipeline`
3. Baseline code head trước handoff: `820ae4f6a6b4d87e2668e101ef4da0bc5e705b6f`
4. Mode hiện tại: `PRIMARY_ONLY_SCREENING_MODE`
5. Dữ liệu market hiện là `PROVISIONAL_PRIMARY_ONLY`
6. Dữ liệu finance hiện là `PROVISIONAL_LOW`
7. Cross-check hiện là `NOT_AVAILABLE`
8. Verification hiện là `NEEDS_MANUAL_BCTC_REVIEW`
9. Pipeline framework đã có tới Step28.
10. Step25 đã scale 1,743 ticker.
11. Step25 xử lý 1,743 ticker, có 16 candidates và 1,727 blocked.
12. Step26 audit xác nhận 1,727 ticker bị `BLOCKED_INSUFFICIENT_MARKET_DATA`.
13. Step26 tạo `first_review_shortlist_50.csv` với 16 dòng.
14. Step26 tạo `manual_bctc_priority_queue_100.csv` với 16 dòng.
15. Step27 probe 166 ticker.
16. Step27 direct fetch OK 17 ticker.
17. Step27 cho thấy có ticker bị Step26 block nhưng vẫn fetch được từ vnstock/VCI.
18. Vì vậy chưa cần kết luận mua dữ liệu market trả phí.
19. Step28 đã được tạo để refresh market snapshot từ vnstock/VCI.
20. Step28 full run đầu tiên đã bị stop vì chạy quá lâu không có progress rõ.
21. Step28 đã được fix progress log, timeout, retry, checkpoint, resume, limit/start/end, UTF-8 safety.
22. Step28 smoke test `--limit 30` đã pass.
23. Smoke result: 30 attempted, 28 OK, 2 failed.
24. Smoke result: 28 Step26-blocked tickers recovered.
25. Step28 full universe sau smoke chưa chạy.
26. Không chạy OCR/PDF/BCTC trong bước kế tiếp.
27. Không tạo khuyến nghị đầu tư, giá mục tiêu, fair value, MoS, hoặc zero-fill.
28. Next action: chạy Step28 full universe không có `--limit`.
29. Exact command:

```powershell
python scripts/run_step28_full_universe_market_snapshot_refresh_vnstock.py --config config/step28_full_universe_market_snapshot_refresh_vnstock.yaml
```

30. Sau khi full run xong, bước kế tiếp là `STEP29_RERUN_AUDIT_AFTER_MARKET_REFRESH`.
