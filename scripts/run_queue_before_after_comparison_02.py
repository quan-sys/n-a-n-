from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.screening.sector_balanced_evidence_ranker import (  # noqa: E402
    build_queue_before_after_comparison,
    load_balance_policy,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare old vs sector-balanced evidence queues.")
    parser.add_argument("--old-ranking", default="data/reports/provisional_evidence_ranking_01/provisional_ranked_shortlist.csv")
    parser.add_argument("--new-ranking", default="data/reports/provisional_crosscheck_02/sector_balanced_ranked_shortlist.csv")
    parser.add_argument("--old-evidence-dir", default="data/reports/evidence_pack_policy_01_from_legacy")
    parser.add_argument("--new-evidence-dir", default="data/reports/evidence_pack_policy_02_balanced")
    parser.add_argument("--policy", default="config/evidence_queue_balance_policy.yaml")
    parser.add_argument("--output-dir", default="data/reports/provisional_crosscheck_02")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    old_dir = Path(args.old_evidence_dir)
    new_dir = Path(args.new_evidence_dir)
    report = build_queue_before_after_comparison(
        old_ranking=_read_csv(args.old_ranking),
        new_ranking=_read_csv(args.new_ranking),
        old_assignments=_read_csv(old_dir / "candidate_stage_assignments.csv"),
        new_assignments=_read_csv(new_dir / "candidate_stage_assignments.csv"),
        old_queue=_read_csv(old_dir / "evidence_collection_queue.csv"),
        new_queue=_read_csv(new_dir / "evidence_collection_queue.csv"),
        old_manual=_read_csv(old_dir / "manual_seed_requests.csv"),
        new_manual=_read_csv(new_dir / "manual_seed_requests.csv"),
        old_run_summary=_read_text(old_dir / "run_summary.md"),
        new_run_summary=_read_text(new_dir / "run_summary.md"),
        policy=load_balance_policy(args.policy),
    )
    (output_dir / "queue_before_after_comparison.md").write_text(report, encoding="utf-8")
    print({"output_dir": str(output_dir), "report": "queue_before_after_comparison.md"})
    return 0


def _read_csv(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, keep_default_na=False)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


if __name__ == "__main__":
    raise SystemExit(main())
