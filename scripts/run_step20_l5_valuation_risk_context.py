from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.screening.step20_l5_valuation_risk_context import (  # noqa: E402
    Step20SafeRunBlocked,
    run_step20_l5_valuation_risk_context,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run STEP20 L5 valuation/risk context.")
    parser.add_argument("--config", default="config/step20_l5_valuation_risk_context.yaml")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output-dir", default="data/reports/step20_l5_valuation_risk_context")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--full-universe", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command_used = " ".join(sys.argv)
    try:
        result = run_step20_l5_valuation_risk_context(
            config_path=Path(args.config),
            output_dir=Path(args.output_dir),
            limit=args.limit,
            allow_partial=args.allow_partial,
            request_full_universe=args.full_universe,
            command_used=command_used,
        )
    except Step20SafeRunBlocked as exc:
        print(f"STEP20 blocked safely: {exc}")
        return 2
    summary = result.summary
    print("STEP20 L5 valuation/risk context complete")
    print(f"processed_ticker_count: {summary.get('processed_ticker_count', 0)}")
    print(f"context_ready_count: {summary.get('context_ready_count', 0)}")
    print(f"manual_review_count: {summary.get('manual_review_count', 0)}")
    print(f"insufficient_data_count: {summary.get('insufficient_data_count', 0)}")
    print(f"final_decision: {summary.get('final_decision', '')}")
    print(f"forbidden_terms_found: {summary.get('forbidden_terms_found', [])}")
    print(f"output_dir: {args.output_dir}")
    return 1 if summary.get("final_decision") == "BLOCKED_GUARDRAIL_VIOLATION" else 0


if __name__ == "__main__":
    raise SystemExit(main())
