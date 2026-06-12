from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.providers.alternative.network_probe_04d_v2 import run_network_probe_04d_v2  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PROVISIONAL-ALT-SOURCE-04D-V2 actual controlled network probe.")
    parser.add_argument("--snapshot", default="data/reports/provisional_current_market_03/current_market_snapshot.csv")
    parser.add_argument("--config", default="config/alternative_provider_network_probe_04d_v2.yaml")
    parser.add_argument("--output-dir", default="data/reports/provisional_alt_source_04d_v2_network_probe")
    parser.add_argument("--cache-dir", default="data/raw/provisional_alt_source_04d_v2_network_probe")
    parser.add_argument("--allow-network", action="store_true", default=None)
    parser.add_argument("--allow-partial", action="store_true", default=None)
    parser.add_argument("--max-requests", type=int, default=None)
    parser.add_argument("--sleep-seconds", type=float, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_network_probe_04d_v2(
        config_path=Path(args.config),
        snapshot_path=Path(args.snapshot),
        output_dir=Path(args.output_dir),
        cache_dir=Path(args.cache_dir),
        allow_network=args.allow_network,
        allow_partial=args.allow_partial,
        max_requests=args.max_requests,
        sleep_seconds=args.sleep_seconds,
    )
    decision = result.decision
    print("PROVISIONAL-ALT-SOURCE-04D-V2 complete")
    print(f"pilot_ticker_count: {decision.get('pilot_ticker_count', 0)}")
    print(f"network_allowed: {decision.get('network_allowed', False)}")
    print(f"network_used: {decision.get('network_used', False)}")
    print(f"provider_runtime_count: {decision.get('provider_runtime_count', 0)}")
    print(f"provider_importable_count: {decision.get('provider_importable_count', 0)}")
    print(f"provider_not_importable_count: {decision.get('provider_not_importable_count', 0)}")
    print(f"fetch_ok_count: {decision.get('fetch_ok_count', 0)}")
    print(f"fetch_error_count: {decision.get('fetch_error_count', 0)}")
    print(f"independent_current_source_family_count: {decision.get('independent_current_source_family_count', 0)}")
    print(f"tickers_with_independent_match_count: {decision.get('tickers_with_independent_match_count', 0)}")
    print(f"manual_review_count: {decision.get('manual_review_count', 0)}")
    print(f"critical_fail_count: {decision.get('critical_fail_count', 0)}")
    print(f"core_outputs_modified: {decision.get('core_outputs_modified', False)}")
    print(f"final_decision: {decision.get('final_decision', '')}")
    print(f"outputs: {args.output_dir}")
    return 1 if decision.get("final_decision") == "NO_GO_FIX_PROVIDER_PROBE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
