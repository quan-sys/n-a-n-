from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.monitoring.step23_backtest_monitoring_module import (  # noqa: E402
    Step23SafeRunBlocked,
    run_step23_backtest_monitoring_module,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run STEP23 filter monitoring module.")
    parser.add_argument("--config", default="config/step23_backtest_monitoring_module.yaml")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output-dir", default="data/reports/step23_backtest_monitoring_module")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--full-universe", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command_used = " ".join(sys.argv)
    try:
        result = run_step23_backtest_monitoring_module(
            config_path=Path(args.config),
            output_dir=Path(args.output_dir),
            limit=args.limit,
            allow_partial=args.allow_partial,
            request_full_universe=args.full_universe,
            command_used=command_used,
        )
    except Step23SafeRunBlocked as exc:
        print(f"STEP23 blocked safely: {exc}")
        return 2
    summary = result.summary
    print("STEP23 filter monitoring complete")
    print(f"snapshot_created: {summary.get('snapshot_created', False)}")
    print(f"previous_snapshot_found: {summary.get('previous_snapshot_found', False)}")
    print(f"processed_ticker_count: {summary.get('processed_ticker_count', 0)}")
    print(f"watchlist_change_count: {summary.get('watchlist_change_count', 0)}")
    print(f"manual_review_trend_available: {summary.get('manual_review_trend_available', False)}")
    print(f"data_coverage_trend_available: {summary.get('data_coverage_trend_available', False)}")
    print(f"source_conflict_trend_available: {summary.get('source_conflict_trend_available', False)}")
    print(f"final_decision: {summary.get('final_decision', '')}")
    print(f"forbidden_terms_found: {summary.get('forbidden_terms_found', [])}")
    print(f"output_dir: {args.output_dir}")
    return 1 if summary.get("final_decision") == "BLOCKED_MONITORING_MODULE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
