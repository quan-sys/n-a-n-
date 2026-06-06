from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ingestion.finance_candidate_normalizer import load_finance_alias_config, normalize_finance_statement_rows  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Isolated vnstock finance worker for REAL-DATA-01I.")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--periods", default="")
    parser.add_argument("--request-sleep-seconds", type=float, default=3.2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    periods = [item.strip() for item in args.periods.split(",") if item.strip()]
    from vnstock import Finance  # type: ignore

    finance = Finance(source="VCI", symbol=args.ticker, period="quarter", get_all=True)
    statements = {}
    for index, method_name in enumerate(["income_statement", "balance_sheet", "cash_flow"]):
        if index and args.request_sleep_seconds:
            time.sleep(args.request_sleep_seconds)
        try:
            value = getattr(finance, method_name)()
        except Exception:
            value = pd.DataFrame()
        statements[method_name] = value if isinstance(value, pd.DataFrame) else pd.DataFrame()

    candidates, schema = normalize_finance_statement_rows(
        ticker=args.ticker,
        statements=statements,
        aliases_config=load_finance_alias_config(),
        source_category="vnstock",
        source_name="vnstock:vci:finance",
        source_url="https://vnstocks.com/",
        fetch_time=datetime.now(UTC).replace(microsecond=0).isoformat(),
        parser_name="vnstock_finance_wide_statement",
        confidence_raw="medium",
        source_unit="VND",
        requested_periods=periods,
    )
    payload = {
        "candidate_rows": candidates.to_dict(orient="records"),
        "schema_rows": schema.to_dict(orient="records"),
    }
    print("__01I_JSON_START__")
    print(json.dumps(payload, ensure_ascii=True))
    print("__01I_JSON_END__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

