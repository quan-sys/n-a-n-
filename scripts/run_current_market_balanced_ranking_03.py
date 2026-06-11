from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.screening.current_market_balanced_ranking import (  # noqa: E402
    build_current_market_balanced_ranking,
    build_current_market_balanced_summary,
)
from src.screening.sector_balanced_evidence_ranker import load_balance_policy  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild balanced ranking and evidence policy after current market gate.")
    parser.add_argument("--ranking", default="data/reports/provisional_crosscheck_02/sector_balanced_ranked_shortlist.csv")
    parser.add_argument("--gate", default="data/reports/provisional_current_market_03/stage2_eligibility_gate.csv")
    parser.add_argument("--market-crosscheck", default="data/reports/provisional_crosscheck_02/market_price_crosscheck.csv")
    parser.add_argument("--finance-crosscheck", default="data/reports/provisional_crosscheck_02/finance_crosscheck_matrix.csv")
    parser.add_argument("--balance-policy", default="config/evidence_queue_balance_policy.yaml")
    parser.add_argument("--output-dir", default="data/reports/provisional_current_market_03")
    parser.add_argument("--evidence-output-dir", default="data/reports/evidence_pack_policy_03_current_market")
    parser.add_argument("--previous-queue", default="data/reports/evidence_pack_policy_02_balanced/evidence_collection_queue.csv")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    evidence_output_dir = Path(args.evidence_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ranking = _read_csv(args.ranking)
    gate = _read_csv(args.gate)
    balanced = build_current_market_balanced_ranking(
        ranking=ranking,
        gate=gate,
        market_crosscheck=_read_csv(args.market_crosscheck),
        finance_crosscheck=_read_csv(args.finance_crosscheck),
        balance_policy=load_balance_policy(args.balance_policy),
    )
    output_path = output_dir / "current_market_balanced_ranked_shortlist.csv"
    balanced.to_csv(output_path, index=False)
    _run_evidence_policy(output_path, evidence_output_dir)
    new_queue = _read_csv(evidence_output_dir / "evidence_collection_queue.csv")
    previous_queue = _read_csv(args.previous_queue) if Path(args.previous_queue).exists() else pd.DataFrame()
    (output_dir / "current_market_balanced_ranking_summary.md").write_text(
        build_current_market_balanced_summary(
            before_ranking=ranking,
            gate=gate,
            after_ranking=balanced,
            previous_queue_rows=len(previous_queue),
            new_queue_rows=len(new_queue),
        ),
        encoding="utf-8",
    )
    print(
        {
            "output_dir": str(output_dir),
            "evidence_output_dir": str(evidence_output_dir),
            "ranked_rows": int(len(balanced)),
            "stage_distribution_after": balanced["evidence_stage"].value_counts().to_dict() if not balanced.empty else {},
            "evidence_queue_rows": int(len(new_queue)),
        }
    )
    return 0


def _run_evidence_policy(input_path: Path, output_dir: Path) -> None:
    command = [
        sys.executable,
        str(ROOT_DIR / "scripts" / "run_evidence_pack_policy_01.py"),
        "--input",
        str(input_path),
        "--output-dir",
        str(output_dir),
    ]
    subprocess.run(command, cwd=ROOT_DIR, check=True)


def _read_csv(path: str | Path) -> pd.DataFrame:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(target)
    return pd.read_csv(target, keep_default_na=False)


if __name__ == "__main__":
    raise SystemExit(main())
