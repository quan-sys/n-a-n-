from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.screening.sector_balanced_evidence_ranker import (  # noqa: E402
    build_sector_balance_diagnostics,
    build_sector_balance_summary,
    create_balanced_ranking,
    load_balance_policy,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create sector-balanced evidence workload ranking.")
    parser.add_argument("--ranking", required=True)
    parser.add_argument("--market-crosscheck", required=True)
    parser.add_argument("--finance-crosscheck", required=True)
    parser.add_argument("--policy", default="config/evidence_queue_balance_policy.yaml")
    parser.add_argument("--output-dir", default="data/reports/provisional_crosscheck_02")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_ranking = pd.read_csv(args.ranking, keep_default_na=False)
    market = pd.read_csv(args.market_crosscheck, keep_default_na=False)
    finance = pd.read_csv(args.finance_crosscheck, keep_default_na=False)
    policy = load_balance_policy(args.policy)
    balanced = create_balanced_ranking(raw_ranking, market, finance, policy)
    diagnostics = build_sector_balance_diagnostics(balanced)
    balanced.to_csv(output_dir / "sector_balanced_ranked_shortlist.csv", index=False)
    diagnostics.to_csv(output_dir / "sector_balance_diagnostics.csv", index=False)
    (output_dir / "sector_balance_summary.md").write_text(
        build_sector_balance_summary(raw_ranking, balanced, policy),
        encoding="utf-8",
    )
    print(
        {
            "output_dir": str(output_dir),
            "balanced_rows": int(len(balanced)),
            "balance_action_counts": balanced["balance_action"].value_counts().to_dict() if not balanced.empty else {},
            "stage_counts": balanced["evidence_stage"].value_counts().to_dict() if not balanced.empty else {},
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
