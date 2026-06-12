from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.integration.step24_final_integration_scale_readiness import (  # noqa: E402
    Step24SafeRunBlocked,
    run_step24_final_integration_scale_readiness,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run STEP24 final integration and scale readiness gate.")
    parser.add_argument("--config", default="config/step24_final_integration_scale_readiness.yaml")
    parser.add_argument("--output-dir", default="data/reports/step24_final_integration_scale_readiness")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--full-universe", action="store_true")
    parser.add_argument("--scale-1743", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command_used = " ".join(sys.argv)
    try:
        result = run_step24_final_integration_scale_readiness(
            config_path=Path(args.config),
            output_dir=Path(args.output_dir),
            allow_partial=args.allow_partial,
            request_full_universe=args.full_universe,
            request_scale_1743=args.scale_1743,
            command_used=command_used,
        )
    except Step24SafeRunBlocked as exc:
        print(f"STEP24 blocked safely: {exc}")
        return 2
    summary = result.summary
    print("STEP24 final integration gate complete")
    print(f"missing_artifact_count: {summary.get('missing_artifact_count', 0)}")
    print(f"schema_check_passed: {summary.get('schema_check_passed', False)}")
    print(f"source_confidence_check_passed: {summary.get('source_confidence_check_passed', False)}")
    print(f"manual_review_contract_passed: {summary.get('manual_review_contract_passed', False)}")
    print(f"forbidden_terms_found: {summary.get('forbidden_terms_found', [])}")
    print(f"full_universe_readiness: {summary.get('full_universe_readiness', '')}")
    print(f"final_decision: {summary.get('final_decision', '')}")
    print(f"output_dir: {args.output_dir}")
    return 1 if summary.get("final_decision") == "BLOCKED_FINAL_INTEGRATION" else 0


if __name__ == "__main__":
    raise SystemExit(main())
