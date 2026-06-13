from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.diagnostics.step27_data_coverage_repair_probe import (  # noqa: E402
    Step27SafeRunBlocked,
    run_step27_data_coverage_repair_probe,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run STEP27 data coverage repair probe.")
    parser.add_argument("--config", default="config/step27_data_coverage_repair_probe.yaml")
    parser.add_argument("--output-dir", default="data/reports/step27_data_coverage_repair_probe")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--max-total-probe-tickers", type=int, default=None)
    parser.add_argument("--max-requests", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command_used = " ".join(sys.argv)
    try:
        result = run_step27_data_coverage_repair_probe(
            config_path=Path(args.config),
            output_dir=Path(args.output_dir),
            allow_partial=args.allow_partial,
            command_used=command_used,
            max_total_probe_tickers=args.max_total_probe_tickers,
            max_requests=args.max_requests,
        )
    except Step27SafeRunBlocked as exc:
        print(f"STEP27 blocked safely: {exc}")
        return 2
    summary = result.summary
    print("STEP27 data coverage repair probe complete")
    print(f"total_probe_tickers: {summary.get('total_probe_tickers', 0)}")
    print(f"direct_fetch_ok_count: {summary.get('direct_fetch_ok_count', 0)}")
    print(f"direct_fetch_empty_count: {summary.get('direct_fetch_empty_count', 0)}")
    print(f"direct_fetch_error_count: {summary.get('direct_fetch_error_count', 0)}")
    print(f"step26_blocked_fetchable_count: {summary.get('step26_blocked_fetchable_count', 0)}")
    print(f"repair_queue_count: {summary.get('repair_queue_count', 0)}")
    print(f"source_limitation_queue_count: {summary.get('source_limitation_queue_count', 0)}")
    print(f"schema_bug_candidate_count: {summary.get('schema_bug_candidate_count', 0)}")
    print(f"final_decision: {summary.get('final_decision', '')}")
    print(f"forbidden_terms_found: {summary.get('forbidden_terms_found', [])}")
    print(f"output_dir: {args.output_dir}")
    return 1 if str(summary.get("final_decision", "")).startswith("BLOCKED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
