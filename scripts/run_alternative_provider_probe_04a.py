from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.providers.alternative.installability_probe_04a import run_alternative_provider_probe  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PROVISIONAL-ALT-SOURCE-04A provider sandbox probe.")
    parser.add_argument("--config", default="config/alternative_provider_registry_04a.yaml")
    parser.add_argument("--output-dir", default="data/reports/alternative_source_probe_04a")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_alternative_provider_probe(config_path=Path(args.config), output_dir=Path(args.output_dir))
    decision = result["decision"]
    print("PROVISIONAL-ALT-SOURCE-04A complete")
    print(f"provider_count: {decision.get('provider_count', 0)}")
    print(f"importable_provider_count: {decision.get('importable_provider_count', 0)}")
    print(f"non_importable_provider_count: {decision.get('non_importable_provider_count', 0)}")
    print(f"source_family_count: {decision.get('source_family_count', 0)}")
    print(f"independent_candidate_family_count: {decision.get('independent_candidate_family_count', 0)}")
    print(f"network_used: {decision.get('network_used', False)}")
    print(f"market_data_fetched: {decision.get('market_data_fetched', False)}")
    print(f"finance_data_fetched: {decision.get('finance_data_fetched', False)}")
    print(f"core_outputs_modified: {decision.get('core_outputs_modified', False)}")
    print(f"final_decision: {decision.get('final_decision', '')}")
    print(f"outputs: {args.output_dir}")
    return 1 if decision.get("final_decision") == "NO_GO" else 0


if __name__ == "__main__":
    raise SystemExit(main())
