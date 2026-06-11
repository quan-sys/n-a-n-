from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.screening.stage2_eligibility_gate import (  # noqa: E402
    build_stage2_eligibility_gate,
    build_stage2_eligibility_summary,
    load_stage2_gate_policy,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PROVISIONAL-CURRENT-MARKET-03 stage-2 eligibility gate.")
    parser.add_argument("--ranking", default="data/reports/provisional_crosscheck_02/sector_balanced_ranked_shortlist.csv")
    parser.add_argument("--current-market", default="data/reports/provisional_current_market_03/current_market_snapshot.csv")
    parser.add_argument("--finance-quality", default="data/reports/legacy_structured_finance_import_01/provisional_data_quality_flags.csv")
    parser.add_argument("--finance-long", default="data/reports/legacy_structured_finance_import_01/provisional_finance_long.csv")
    parser.add_argument("--finance-crosscheck", default="data/reports/provisional_crosscheck_02/finance_crosscheck_matrix.csv")
    parser.add_argument("--policy", default="config/current_market_data_policy.yaml")
    parser.add_argument("--output-dir", default="data/reports/provisional_current_market_03")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    policy = load_stage2_gate_policy(args.policy)
    gate = build_stage2_eligibility_gate(
        ranking=_read_csv(args.ranking),
        current_market=_read_csv(args.current_market),
        finance_quality=_read_csv(args.finance_quality),
        finance_long=_read_csv(args.finance_long),
        finance_crosscheck=_read_csv(args.finance_crosscheck),
        policy=policy,
    )
    gate.to_csv(output_dir / "stage2_eligibility_gate.csv", index=False)
    (output_dir / "stage2_eligibility_summary.md").write_text(build_stage2_eligibility_summary(gate), encoding="utf-8")
    print(
        {
            "output_dir": str(output_dir),
            "total_rows": int(len(gate)),
            "eligibility_counts": gate["eligibility_status"].value_counts().to_dict() if not gate.empty else {},
            "demoted_from_stage2_plus_count": int((gate["original_stage"].isin({"stage_2_evidence_candidates", "stage_3_final_watchlist", "stage_4_deep_dive_shortlist"}) & ~gate["original_stage"].eq(gate["new_stage"])).sum()) if not gate.empty else 0,
        }
    )
    return 0


def _read_csv(path: str) -> pd.DataFrame:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(target)
    return pd.read_csv(target, keep_default_na=False)


if __name__ == "__main__":
    raise SystemExit(main())
