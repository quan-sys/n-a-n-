from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.shadow.step19_shadow_20 import run_step19_shadow_20  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="STEP19-SHADOW-20 diagnostic company engine shadow run.")
    parser.add_argument("--config", default="config/step19_shadow_20_policy.yaml")
    parser.add_argument("--output-dir", default="data/reports/step19_shadow_20")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_step19_shadow_20(config_path=Path(args.config), output_dir=Path(args.output_dir))
    decision = result.decision
    print("STEP19-SHADOW-20 complete")
    print(f"pilot_ticker_count: {decision.get('pilot_ticker_count', 0)}")
    print(f"shadow_ready_count: {decision.get('shadow_ready_count', 0)}")
    print(f"shadow_conditional_count: {decision.get('shadow_conditional_count', 0)}")
    print(f"shadow_blocked_count: {decision.get('shadow_blocked_count', 0)}")
    print(f"critical_issue_count: {decision.get('critical_issue_count', 0)}")
    print(f"warning_count: {decision.get('warning_count', 0)}")
    print(f"production_step19_allowed_count: {decision.get('production_step19_allowed_count', 0)}")
    print(f"investment_recommendation_allowed_count: {decision.get('investment_recommendation_allowed_count', 0)}")
    print(f"valuation_allowed_count: {decision.get('valuation_allowed_count', 0)}")
    print(f"final_decision: {decision.get('final_decision', '')}")
    print(f"outputs: {args.output_dir}")
    return 1 if decision.get("final_decision") == "NO_GO_FIX_SHADOW_PIPELINE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
