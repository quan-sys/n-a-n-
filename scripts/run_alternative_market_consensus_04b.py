from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.validation.alternative_market_consensus_04b import run_alternative_market_consensus  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PROVISIONAL-ALT-SOURCE-04B market consensus sandbox.")
    parser.add_argument("--snapshot", default="data/reports/provisional_current_market_03/current_market_snapshot.csv")
    parser.add_argument("--output-dir", default="data/reports/alternative_source_consensus_04b")
    parser.add_argument("--config", default="config/alternative_market_consensus_04b.yaml")
    parser.add_argument("--raw-cache-dir", default="data/raw/current_market_03")
    parser.add_argument("--prior-crosscheck-path", default="data/reports/provisional_current_market_03b_crosscheck/market_crosscheck_20.csv")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_alternative_market_consensus(
        snapshot_path=Path(args.snapshot),
        output_dir=Path(args.output_dir),
        config_path=Path(args.config),
        raw_cache_dir=Path(args.raw_cache_dir) if args.raw_cache_dir else None,
        prior_crosscheck_path=Path(args.prior_crosscheck_path) if args.prior_crosscheck_path else None,
    )
    decision = result.decision
    print("PROVISIONAL-ALT-SOURCE-04B complete")
    print(f"pilot_ticker_count: {decision.get('pilot_ticker_count', 0)}")
    print(f"provider_importable_count: {decision.get('provider_importable_count', 0)}")
    print(f"provider_not_importable_count: {decision.get('provider_not_importable_count', 0)}")
    print(f"independent_current_source_family_count: {decision.get('independent_current_source_family_count', 0)}")
    print(f"tickers_with_independent_match_count: {decision.get('tickers_with_independent_match_count', 0)}")
    print(f"tickers_manual_review_count: {decision.get('tickers_manual_review_count', 0)}")
    print(f"critical_fail_count: {decision.get('critical_fail_count', 0)}")
    print(f"final_decision: {decision.get('final_decision', '')}")
    print(f"outputs: {args.output_dir}")
    return 1 if decision.get("final_decision") == "NO_GO_FIX_ALT_SOURCE_04B" else 0


if __name__ == "__main__":
    raise SystemExit(main())
