from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.reporting.step22_l7_weekly_report_manual_review import (  # noqa: E402
    Step22SafeRunBlocked,
    run_step22_l7_weekly_report_manual_review,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run STEP22 L7 weekly report/manual review pack.")
    parser.add_argument("--config", default="config/step22_l7_weekly_report_manual_review.yaml")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output-dir", default="data/reports/step22_l7_weekly_report_manual_review")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--full-universe", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command_used = " ".join(sys.argv)
    try:
        result = run_step22_l7_weekly_report_manual_review(
            config_path=Path(args.config),
            output_dir=Path(args.output_dir),
            limit=args.limit,
            allow_partial=args.allow_partial,
            request_full_universe=args.full_universe,
            command_used=command_used,
        )
    except Step22SafeRunBlocked as exc:
        print(f"STEP22 blocked safely: {exc}")
        return 2
    summary = result.summary
    print("STEP22 L7 weekly report/manual review complete")
    print(f"processed_ticker_count: {summary.get('processed_ticker_count', 0)}")
    print(f"watchlist_status_counts: {summary.get('watchlist_status_counts', {})}")
    print(f"manual_review_count: {summary.get('manual_review_count', 0)}")
    print(f"rejected_count: {summary.get('rejected_count', 0)}")
    print(f"missing_input_files: {summary.get('missing_input_files', [])}")
    print(f"final_decision: {summary.get('final_decision', '')}")
    print(f"forbidden_terms_found: {summary.get('forbidden_terms_found', [])}")
    print(f"output_dir: {args.output_dir}")
    return 1 if summary.get("final_decision") == "BLOCKED_WEEKLY_REPORT" else 0


if __name__ == "__main__":
    raise SystemExit(main())
