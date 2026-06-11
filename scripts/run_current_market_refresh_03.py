from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ingestion.current_market_data_refresh import run_current_market_refresh  # noqa: E402


DEFAULT_RANKING = "data/reports/provisional_crosscheck_02/sector_balanced_ranked_shortlist.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PROVISIONAL-CURRENT-MARKET-03 fresh market refresh.")
    parser.add_argument("--top-n", type=int, default=500)
    parser.add_argument("--max-requests", type=int, default=None)
    parser.add_argument("--sleep-seconds", type=float, default=0.25)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--input-ranking-path", default=DEFAULT_RANKING)
    parser.add_argument("--output-dir", default="data/reports/provisional_current_market_03")
    parser.add_argument("--raw-output-dir", default="data/raw/current_market_03")
    parser.add_argument("--policy", default="config/current_market_data_policy.yaml")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    max_requests = args.max_requests if args.max_requests is not None else args.top_n
    result = run_current_market_refresh(
        ranking_path=Path(args.input_ranking_path),
        output_dir=Path(args.output_dir),
        raw_output_dir=Path(args.raw_output_dir),
        policy_path=Path(args.policy),
        top_n=args.top_n,
        max_requests=max_requests,
        sleep_seconds=args.sleep_seconds,
        allow_partial=args.allow_partial,
        force_refresh=args.force_refresh,
    )
    attempts = result["attempt_log"]
    snapshot = result["snapshot"]
    print(
        {
            "output_dir": args.output_dir,
            "total_requested": int(len(attempts)),
            "fetch_status_counts": attempts["fetch_status"].value_counts().to_dict() if not attempts.empty else {},
            "total_missing_market": int(snapshot["missing_market_flag"].astype(bool).sum()) if not snapshot.empty else 0,
            "total_stale_price": int(snapshot["stale_price_flag"].astype(bool).sum()) if not snapshot.empty else 0,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
