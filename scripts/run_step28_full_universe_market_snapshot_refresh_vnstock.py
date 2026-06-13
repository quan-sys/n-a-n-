from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ingestion.step28_full_universe_market_snapshot_refresh_vnstock import (  # noqa: E402
    Step28SafeRunBlocked,
    run_step28_full_universe_market_snapshot_refresh_vnstock,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run STEP28 full-universe vnstock/VCI market snapshot refresh.")
    parser.add_argument("--config", default="config/step28_full_universe_market_snapshot_refresh_vnstock.yaml")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--max-tickers", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start-index", type=int, default=None)
    parser.add_argument("--end-index", type=int, default=None)
    parser.add_argument("--request-pause-seconds", type=float, default=None)
    parser.add_argument("--force-refresh", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command_used = " ".join(sys.argv)
    try:
        result = run_step28_full_universe_market_snapshot_refresh_vnstock(
            config_path=Path(args.config),
            output_dir=Path(args.output_dir) if args.output_dir else None,
            command_used=command_used,
            max_tickers=args.max_tickers,
            limit=args.limit,
            start_index=args.start_index,
            end_index=args.end_index,
            request_pause_seconds=args.request_pause_seconds,
            force_refresh=True if args.force_refresh else None,
        )
    except Step28SafeRunBlocked as exc:
        print(f"STEP28 blocked safely: {exc}")
        return 2
    summary = result.summary
    print("STEP28 full-universe market snapshot refresh complete")
    print(f"total_tickers_attempted: {summary.get('total_tickers_attempted', 0)}")
    print(f"fetch_ok_count: {summary.get('fetch_ok_count', 0)}")
    print(f"fetch_failed_count: {summary.get('fetch_failed_count', 0)}")
    print(f"step26_blocked_recovered_count: {summary.get('step26_blocked_recovered_count', 0)}")
    print(f"market_coverage_after_step28: {summary.get('market_coverage_after_step28', 0)}")
    print(f"alternative_paid_data_needed_for_market: {summary.get('alternative_paid_data_needed_for_market', None)}")
    print(f"final_decision: {summary.get('final_decision', '')}")
    print(f"forbidden_terms_found: {summary.get('forbidden_terms_found', [])}")
    return 1 if str(summary.get("final_decision", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
