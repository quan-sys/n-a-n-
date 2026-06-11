from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.validation.current_market_replay_03c import run_current_market_replay  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PROVISIONAL-CURRENT-MARKET-03C local replay.")
    parser.add_argument("--snapshot", default="data/reports/provisional_current_market_03/current_market_snapshot.csv")
    parser.add_argument("--stage2-gate", default="data/reports/provisional_current_market_03/stage2_eligibility_gate.csv")
    parser.add_argument("--ranking", default="data/reports/provisional_current_market_03/current_market_balanced_ranked_shortlist.csv")
    parser.add_argument("--evidence-summary", default="data/reports/evidence_pack_policy_03_current_market/run_summary.md")
    parser.add_argument("--output-dir", default="data/reports/provisional_current_market_03c_replay")
    parser.add_argument("--config", default="config/current_market_replay_03c.yaml")
    parser.add_argument("--base-ranking", default="data/reports/provisional_crosscheck_02/sector_balanced_ranked_shortlist.csv")
    parser.add_argument("--finance-quality", default="data/reports/legacy_structured_finance_import_01/provisional_data_quality_flags.csv")
    parser.add_argument("--finance-long", default="data/reports/legacy_structured_finance_import_01/provisional_finance_long.csv")
    parser.add_argument("--finance-crosscheck", default="data/reports/provisional_crosscheck_02/finance_crosscheck_matrix.csv")
    parser.add_argument("--market-crosscheck", default="data/reports/provisional_crosscheck_02/market_price_crosscheck.csv")
    parser.add_argument("--stage2-policy", default="config/current_market_data_policy.yaml")
    parser.add_argument("--balance-policy", default="config/evidence_queue_balance_policy.yaml")
    parser.add_argument("--evidence-policy", default="config/evidence_pack_policy.yaml")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_current_market_replay(
        snapshot_path=Path(args.snapshot),
        stage2_gate_path=Path(args.stage2_gate),
        ranking_path=Path(args.ranking),
        evidence_summary_path=Path(args.evidence_summary),
        output_dir=Path(args.output_dir),
        config_path=Path(args.config),
        base_ranking_path=Path(args.base_ranking),
        finance_quality_path=Path(args.finance_quality),
        finance_long_path=Path(args.finance_long),
        finance_crosscheck_path=Path(args.finance_crosscheck),
        market_crosscheck_path=Path(args.market_crosscheck),
        stage2_policy_path=Path(args.stage2_policy),
        balance_policy_path=Path(args.balance_policy),
        evidence_policy_path=Path(args.evidence_policy),
    )
    decision = result.decision
    print("PROVISIONAL-CURRENT-MARKET-03C complete")
    print(f"pilot_ticker_count: {decision.get('pilot_ticker_count', 0)}")
    print(f"critical_fail_count: {decision.get('critical_fail_count', 0)}")
    print(f"warn_count: {decision.get('warn_count', 0)}")
    print(f"final_decision: {decision.get('final_decision', '')}")
    print(f"evidence_queue_original: {decision.get('evidence_queue_original', 0)}")
    print(f"evidence_queue_replay: {decision.get('evidence_queue_replay', 0)}")
    print(f"outputs: {args.output_dir}")
    return 1 if decision.get("final_decision") == "NO_GO" else 0


if __name__ == "__main__":
    raise SystemExit(main())
