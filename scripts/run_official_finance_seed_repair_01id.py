from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ingestion.official_finance_seed_repair import run_official_finance_seed_repair_01id  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="REAL-DATA-01I-D HTTPS-first official seed repair.")
    parser.add_argument("--seed-file", default="data/seeds/official_finance_document_seed.real_20_initial_01ic.csv")
    parser.add_argument("--index-file", default="data/reports/official_finance_documents_01ic/finance_document_index.csv")
    parser.add_argument("--raw-snapshot-dir", default="data/raw/official_finance_documents/01ic")
    parser.add_argument("--output-dir", default="data/reports/official_finance_documents_01id")
    parser.add_argument("--previous-candidates-file", default="data/reports/official_finance_documents_01id/official_document_link_candidates.csv")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--min-reviewable-score", type=int, default=50)
    parser.add_argument("--min-high-confidence-score", type=int, default=80)
    parser.add_argument("--target-years", default="2026,2025")
    parser.add_argument("--target-periods", default="2026-Q1,2025-Q4,2025")
    parser.add_argument("--https-first", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_official_finance_seed_repair_01id(
        seed_file=args.seed_file,
        index_file=args.index_file,
        raw_snapshot_dir=args.raw_snapshot_dir,
        output_dir=args.output_dir,
        min_reviewable_score=args.min_reviewable_score,
        min_high_confidence_score=args.min_high_confidence_score,
        target_years=parse_csv(args.target_years),
        target_periods=parse_csv(args.target_periods),
        https_first=args.https_first,
        previous_candidates_file=args.previous_candidates_file,
    )
    candidates = result["official_document_link_candidates"]
    bad_seed = result["bad_seed_url_report"]
    manual_review = result["manual_review_queue"]
    print(
        {
            "output_dir": str(args.output_dir),
            "candidates_extracted": int(len(candidates)),
            "https_candidates": int(candidates["candidate_is_https"].astype(bool).sum()) if not candidates.empty else 0,
            "http_candidates": int((~candidates["candidate_is_https"].astype(bool)).sum()) if not candidates.empty else 0,
            "bad_seed_rows": int(len(bad_seed)),
            "manual_review_rows": int(len(manual_review)),
            "finance_parse_ready": False,
            "step19_implemented": False,
        }
    )
    return 0


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value).split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
