from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.audit.step29_full_universe_audit_after_market_refresh import (  # noqa: E402
    Step29SafeRunBlocked,
    run_step29_full_universe_audit_after_market_refresh,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run STEP29 full-universe audit after STEP28 market refresh.")
    parser.add_argument("--config", default="config/step29_full_universe_audit_after_market_refresh.yaml")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--pytest-result", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command_used = " ".join(sys.argv)
    try:
        result = run_step29_full_universe_audit_after_market_refresh(
            config_path=Path(args.config),
            output_dir=Path(args.output_dir) if args.output_dir else None,
            command_used=command_used,
            pytest_result=args.pytest_result,
        )
    except Step29SafeRunBlocked as exc:
        print(f"STEP29 blocked safely: {exc}")
        return 2
    summary = result.summary
    print("STEP29 full-universe audit after market refresh complete")
    print(f"total_universe: {summary.get('total_universe', 0)}")
    print(f"market_data_available_after_step28: {summary.get('market_data_available_after_step28', 0)}")
    print(f"still_blocked_insufficient_market_data: {summary.get('still_blocked_insufficient_market_data', 0)}")
    print(f"recovered_from_step26_blocked: {summary.get('recovered_from_step26_blocked', 0)}")
    print(f"watchlist_candidate_count: {summary.get('watchlist_candidate_count', 0)}")
    print(f"manual_review_count: {summary.get('manual_review_count', 0)}")
    print(f"failed_or_insufficient_count: {summary.get('failed_or_insufficient_count', 0)}")
    print(f"final_decision: {summary.get('final_decision', '')}")
    print(f"pytest_result: {summary.get('pytest_result', '')}")
    print(f"forbidden_terms_found: {summary.get('forbidden_terms_found', [])}")
    return 1 if str(summary.get("final_decision", "")).startswith("BLOCKED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
