from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.audit.step26_full_universe_output_audit_first_shortlist import (  # noqa: E402
    Step26SafeRunBlocked,
    run_step26_full_universe_output_audit_first_shortlist,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run STEP26 full-universe output audit and first shortlist.")
    parser.add_argument("--config", default="config/step26_full_universe_output_audit_first_shortlist.yaml")
    parser.add_argument("--output-dir", default="data/reports/step26_full_universe_output_audit_first_shortlist")
    parser.add_argument("--allow-partial", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command_used = " ".join(sys.argv)
    try:
        result = run_step26_full_universe_output_audit_first_shortlist(
            config_path=Path(args.config),
            output_dir=Path(args.output_dir),
            allow_partial=args.allow_partial,
            command_used=command_used,
        )
    except Step26SafeRunBlocked as exc:
        print(f"STEP26 blocked safely: {exc}")
        return 2
    summary = result.summary
    print("STEP26 full-universe output audit complete")
    print(f"step25_rows_path: {summary.get('step25_rows_path', '')}")
    print(f"total_universe_rows_read: {summary.get('total_universe_rows_read', 0)}")
    print(f"first_review_shortlist_count: {summary.get('first_review_shortlist_count', 0)}")
    print(f"manual_bctc_priority_queue_count: {summary.get('manual_bctc_priority_queue_count', 0)}")
    print(f"surviving_primary_only_candidate_count: {summary.get('surviving_primary_only_candidate_count', 0)}")
    print(f"data_repair_priority_count: {summary.get('data_repair_priority_count', 0)}")
    print(f"final_decision: {summary.get('final_decision', '')}")
    print(f"forbidden_terms_found: {summary.get('forbidden_terms_found', [])}")
    print(f"output_dir: {args.output_dir}")
    return 1 if str(summary.get("final_decision", "")).startswith("BLOCKED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
