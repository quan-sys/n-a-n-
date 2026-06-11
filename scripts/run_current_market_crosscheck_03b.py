from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.validation.current_market_crosscheck_03b import run_market_crosscheck  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PROVISIONAL-CURRENT-MARKET-03B market cross-check.")
    parser.add_argument("--snapshot", default="data/reports/provisional_current_market_03/current_market_snapshot.csv")
    parser.add_argument("--output-dir", default="data/reports/provisional_current_market_03b_crosscheck")
    parser.add_argument("--config", default="config/current_market_crosscheck_03b.yaml")
    parser.add_argument("--legacy-market-path", default=None)
    parser.add_argument("--prior-crosscheck-dir", default=None)
    parser.add_argument("--raw-cache-dir", default="data/raw/current_market_03")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_market_crosscheck(
        snapshot_path=Path(args.snapshot),
        output_dir=Path(args.output_dir),
        config_path=Path(args.config),
        legacy_market_path=Path(args.legacy_market_path) if args.legacy_market_path else None,
        prior_crosscheck_dir=Path(args.prior_crosscheck_dir) if args.prior_crosscheck_dir else None,
        raw_cache_dir=Path(args.raw_cache_dir) if args.raw_cache_dir else None,
        strict=args.strict,
    )
    decision = result.decision
    print("PROVISIONAL-CURRENT-MARKET-03B complete")
    print(f"pilot_ticker_count: {decision.get('pilot_ticker_count', 0)}")
    print(f"primary_missing_count: {decision.get('primary_missing_count', 0)}")
    print(f"primary_stale_count: {decision.get('primary_stale_count', 0)}")
    print(f"reference_sources_found: {decision.get('reference_sources_found', 0)}")
    print(f"manual_review_count: {decision.get('manual_review_count', 0)}")
    print(f"fail_count: {decision.get('fail_count', 0)}")
    print(f"final_decision: {decision.get('final_decision', '')}")
    print(f"outputs: {args.output_dir}")
    return 1 if decision.get("final_decision") == "NO_GO" else 0


if __name__ == "__main__":
    raise SystemExit(main())
