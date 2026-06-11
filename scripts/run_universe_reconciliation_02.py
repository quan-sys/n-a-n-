from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ingestion.universe_reconciliation import (  # noqa: E402
    build_universe_reconciliation,
    build_universe_reconciliation_summary,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reconcile provisional universe counts and data availability.")
    parser.add_argument("--legacy-quality", required=True)
    parser.add_argument("--ranking", required=True)
    parser.add_argument("--legacy-market", required=True)
    parser.add_argument("--output-dir", default="data/reports/provisional_crosscheck_02")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    reconciliation = build_universe_reconciliation(
        pd.read_csv(args.legacy_quality, keep_default_na=False),
        pd.read_csv(args.ranking, keep_default_na=False),
        pd.read_csv(args.legacy_market, keep_default_na=False),
    )
    reconciliation.to_csv(output_dir / "universe_reconciliation.csv", index=False)
    (output_dir / "universe_reconciliation_summary.md").write_text(
        build_universe_reconciliation_summary(reconciliation),
        encoding="utf-8",
    )
    print(
        {
            "output_dir": str(output_dir),
            "current_ticker_count": int(reconciliation["ticker"].nunique()),
            "issue_counts": reconciliation["possible_issue"].value_counts().to_dict(),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
