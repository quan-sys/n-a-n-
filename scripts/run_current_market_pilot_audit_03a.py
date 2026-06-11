from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.validation.current_market_pilot_audit_03a import run_pilot_audit  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PROVISIONAL-CURRENT-MARKET-03A pilot audit.")
    parser.add_argument("--input-dir", default="data/reports/provisional_current_market_03")
    parser.add_argument("--evidence-dir", default="data/reports/evidence_pack_policy_03_current_market")
    parser.add_argument("--output-dir", default="data/reports/provisional_current_market_03a")
    parser.add_argument("--policy", default="config/current_market_pilot_audit_policy.yaml")
    parser.add_argument("--raw-dir", default="data/raw/current_market_03")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--fail-on-blocker", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_pilot_audit(
        input_dir=Path(args.input_dir),
        evidence_dir=Path(args.evidence_dir),
        output_dir=Path(args.output_dir),
        policy_path=Path(args.policy),
        raw_dir=Path(args.raw_dir),
        strict=args.strict,
    )
    print(
        {
            "output_dir": args.output_dir,
            "overall_status": result.overall_status,
            "go_no_go": result.go_no_go,
            "checks": int(len(result.checks)),
            "mismatch_cases": int(len(result.mismatches)),
        }
    )
    if args.fail_on_blocker and result.go_no_go == "NO_GO":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
