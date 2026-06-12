from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.providers.alternative.network_probe_04d import run_network_probe_04d  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PROVISIONAL-ALT-SOURCE-04D controlled network probe.")
    parser.add_argument("--config", default="config/alternative_provider_network_probe_04d.yaml")
    parser.add_argument("--output-dir", default="data/reports/alternative_source_network_probe_04d")
    parser.add_argument("--cache-dir", default="data/raw/alternative_source_network_probe_04d")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-optional-install", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--max-requests", type=int, default=40)
    parser.add_argument("--sleep-seconds", type=float, default=0.5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_network_probe_04d(
        config_path=Path(args.config),
        output_dir=Path(args.output_dir),
        cache_dir=Path(args.cache_dir),
        allow_network=args.allow_network,
        allow_optional_install=args.allow_optional_install,
        allow_partial=args.allow_partial,
        max_requests=args.max_requests,
        sleep_seconds=args.sleep_seconds,
    )
    decision = result.decision
    print("PROVISIONAL-ALT-SOURCE-04D complete")
    print(f"pilot_ticker_count: {decision.get('pilot_ticker_count', 0)}")
    print(f"network_used: {decision.get('network_used', False)}")
    print(f"optional_install_used: {decision.get('optional_install_used', False)}")
    print(f"provider_count_attempted: {decision.get('provider_count_attempted', 0)}")
    print(f"provider_count_fetch_ok: {decision.get('provider_count_fetch_ok', 0)}")
    print(f"independent_current_source_family_count: {decision.get('independent_current_source_family_count', 0)}")
    print(f"tickers_with_independent_match_count: {decision.get('tickers_with_independent_match_count', 0)}")
    print(f"tickers_with_independent_mismatch_count: {decision.get('tickers_with_independent_mismatch_count', 0)}")
    print(f"manual_review_count: {decision.get('manual_review_count', 0)}")
    print(f"critical_fail_count: {decision.get('critical_fail_count', 0)}")
    print(f"final_decision: {decision.get('final_decision', '')}")
    print(f"outputs: {args.output_dir}")
    return 1 if decision.get("final_decision") == "NO_GO_FIX_PROVIDER_PROBE_BEFORE_ANY_SCALE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
