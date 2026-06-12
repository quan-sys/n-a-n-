from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.pipeline.real_data_02_pilot_20 import run_real_data_02_pilot_20  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="REAL-DATA-02-PILOT-20 controlled readiness check.")
    parser.add_argument("--input-replay-dir", default="data/reports/provisional_current_market_03c_replay")
    parser.add_argument("--current-market-dir", default="data/reports/provisional_current_market_03")
    parser.add_argument("--output-dir", default="data/reports/real_data_02_pilot_20")
    parser.add_argument("--policy", default="config/real_data_02_pilot_20_policy.yaml")
    parser.add_argument("--finance-long", default="data/reports/legacy_structured_finance_import_01/provisional_finance_long.csv")
    parser.add_argument("--finance-wide", default="data/reports/legacy_structured_finance_import_01/provisional_finance_latest_wide.csv")
    parser.add_argument("--finance-quality", default="data/reports/legacy_structured_finance_import_01/provisional_data_quality_flags.csv")
    parser.add_argument("--ranking", default=None)
    parser.add_argument("--allow-partial", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_real_data_02_pilot_20(
        input_replay_dir=Path(args.input_replay_dir),
        current_market_dir=Path(args.current_market_dir),
        output_dir=Path(args.output_dir),
        policy_path=Path(args.policy),
        finance_long_path=Path(args.finance_long),
        finance_wide_path=Path(args.finance_wide),
        finance_quality_path=Path(args.finance_quality),
        ranking_path=Path(args.ranking) if args.ranking else None,
        allow_partial=args.allow_partial,
    )
    decision = result.decision
    print("REAL-DATA-02-PILOT-20 complete")
    print(f"pilot_ticker_count: {decision.get('pilot_ticker_count', 0)}")
    print(f"final_decision: {decision.get('final_decision', '')}")
    print(f"critical_fail_count: {decision.get('critical_fail_count', 0)}")
    print(f"warn_count: {decision.get('warn_count', 0)}")
    print(f"source_failure_count: {decision.get('source_failure_count', 0)}")
    print(f"tickers_succeeded: {decision.get('tickers_succeeded', 0)}")
    print(f"tickers_failed: {decision.get('tickers_failed', 0)}")
    print(f"outputs: {args.output_dir}")
    return 1 if decision.get("final_decision") == "NO_GO" else 0


if __name__ == "__main__":
    raise SystemExit(main())
