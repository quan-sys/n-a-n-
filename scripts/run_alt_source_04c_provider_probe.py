from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.providers.alternative.provider_probe_04c import run_provider_probe_04c  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PROVISIONAL-ALT-SOURCE-04C provider importability and 20-ticker probe.")
    parser.add_argument("--config", default="config/alternative_provider_probe_04c.yaml")
    parser.add_argument("--pilot-snapshot", default="data/reports/provisional_current_market_03/current_market_snapshot.csv")
    parser.add_argument("--output-dir", default="data/reports/provisional_alt_source_04c_provider_probe")
    parser.add_argument("--cache-dir", default="data/raw/provisional_alt_source_04c")
    parser.add_argument("--max-requests", type=int, default=20)
    parser.add_argument("--sleep-seconds", type=float, default=0.5)
    parser.add_argument("--allow-network", choices=["true", "false"], default="false")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_provider_probe_04c(
        config_path=Path(args.config),
        pilot_snapshot_path=Path(args.pilot_snapshot),
        output_dir=Path(args.output_dir),
        cache_dir=Path(args.cache_dir),
        max_requests=args.max_requests,
        sleep_seconds=args.sleep_seconds,
        allow_network=args.allow_network.lower() == "true",
    )
    decision = result.decision
    print("PROVISIONAL-ALT-SOURCE-04C complete")
    print(f"pilot_ticker_count: {decision.get('pilot_ticker_count', 0)}")
    print(f"providers_registered: {decision.get('providers_registered', 0)}")
    print(f"provider_importable_count: {decision.get('provider_importable_count', 0)}")
    print(f"provider_not_importable_count: {decision.get('provider_not_importable_count', 0)}")
    print(f"network_used: {decision.get('network_used', False)}")
    print(f"provider_fetch_attempt_count: {decision.get('provider_fetch_attempt_count', 0)}")
    print(f"independent_current_source_family_count: {decision.get('independent_current_source_family_count', 0)}")
    print(f"tickers_with_independent_confirmation_count: {decision.get('tickers_with_independent_confirmation_count', 0)}")
    print(f"manual_review_count: {decision.get('manual_review_count', 0)}")
    print(f"critical_fail_count: {decision.get('critical_fail_count', 0)}")
    print(f"final_decision: {decision.get('final_decision', '')}")
    print(f"outputs: {args.output_dir}")
    return 1 if decision.get("final_decision") == "NO_GO_PROVIDER_PROBE_BROKEN" else 0


if __name__ == "__main__":
    raise SystemExit(main())
