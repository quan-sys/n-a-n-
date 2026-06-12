from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.screening.step05a_primary_only_screening import (  # noqa: E402
    Step05ASafeRunBlocked,
    run_step05a_primary_only_screening,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run STEP05A primary-only screening mode.")
    parser.add_argument("--config", default="config/step05a_primary_only_screening.yaml")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output-dir", default="data/reports/step05a_primary_only_screening")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--full-universe", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command_used = " ".join(sys.argv)
    try:
        result = run_step05a_primary_only_screening(
            config_path=Path(args.config),
            output_dir=Path(args.output_dir),
            limit=args.limit,
            allow_partial=args.allow_partial,
            request_full_universe=args.full_universe,
            command_used=command_used,
        )
    except Step05ASafeRunBlocked as exc:
        print(f"STEP05A blocked safely: {exc}")
        return 2
    summary = result.summary
    print("STEP05A primary-only screening complete")
    print(f"processed_ticker_count: {summary.get('processed_ticker_count', 0)}")
    print(f"blocked_count: {summary.get('blocked_count', 0)}")
    print(f"watchlist_candidate_count: {summary.get('watchlist_candidate_count', 0)}")
    print(f"manual_bctc_review_queue_count: {summary.get('manual_bctc_review_queue_count', 0)}")
    print(f"market_source_confidence: {summary.get('market_source_confidence', '')}")
    print(f"finance_source_confidence_default: {summary.get('finance_source_confidence_default', '')}")
    print(f"crosscheck_status: {summary.get('crosscheck_status', '')}")
    print(f"verification_status: {summary.get('verification_status', '')}")
    print(f"final_decision: {summary.get('final_decision', '')}")
    print(f"outputs: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
