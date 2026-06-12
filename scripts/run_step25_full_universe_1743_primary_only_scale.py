from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.scale.step25_full_universe_1743_primary_only_scale import (  # noqa: E402
    Step25SafeRunBlocked,
    run_step25_full_universe_1743_primary_only_scale,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run STEP25 full-universe primary-only scale.")
    parser.add_argument("--config", default="config/step25_full_universe_1743_primary_only_scale.yaml")
    parser.add_argument("--max-tickers", type=int, default=1743)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--output-dir", default="data/reports/step25_full_universe_1743_primary_only_scale")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--resume-from-cache", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command_used = " ".join(sys.argv)
    try:
        result = run_step25_full_universe_1743_primary_only_scale(
            config_path=Path(args.config),
            output_dir=Path(args.output_dir),
            max_tickers=args.max_tickers,
            batch_size=args.batch_size,
            allow_partial=args.allow_partial,
            resume_from_cache=args.resume_from_cache,
            command_used=command_used,
        )
    except Step25SafeRunBlocked as exc:
        print(f"STEP25 blocked safely: {exc}")
        return 2
    summary = result.summary
    print("STEP25 full-universe primary-only scale complete")
    print(f"actual_universe_count: {summary.get('actual_universe_count', 0)}")
    print(f"processed_ticker_count: {summary.get('processed_ticker_count', 0)}")
    print(f"batch_count: {summary.get('batch_count', 0)}")
    print(f"watchlist_candidate_count: {summary.get('watchlist_candidate_count', 0)}")
    print(f"manual_bctc_review_queue_count: {summary.get('manual_bctc_review_queue_count', 0)}")
    print(f"blocked_count: {summary.get('blocked_count', 0)}")
    print(f"failed_ticker_count: {summary.get('failed_ticker_count', 0)}")
    print(f"forbidden_terms_found: {summary.get('forbidden_terms_found', [])}")
    print(f"final_decision: {summary.get('final_decision', '')}")
    print(f"output_dir: {args.output_dir}")
    return 1 if summary.get("final_decision") == "BLOCKED_FULL_UNIVERSE_PRIMARY_ONLY" else 0


if __name__ == "__main__":
    raise SystemExit(main())
