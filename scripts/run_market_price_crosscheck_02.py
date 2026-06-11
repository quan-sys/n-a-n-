from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ingestion.public_market_data_crosscheck import (  # noqa: E402
    ATTEMPT_LOG_COLUMNS,
    MARKET_CROSSCHECK_COLUMNS,
    compute_market_summary,
    crosscheck_market_row,
    fetch_public_market_csv_with_log,
    load_public_market_source_config,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Targeted public market price/volume cross-check.")
    parser.add_argument("--ranking", required=True)
    parser.add_argument("--legacy-market", required=True)
    parser.add_argument("--top-n", type=int, default=200)
    parser.add_argument("--output-dir", default="data/reports/provisional_crosscheck_02")
    parser.add_argument("--config", default="config/public_market_data_sources.yaml")
    parser.add_argument("--workers", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ranking = pd.read_csv(args.ranking, keep_default_na=False)
    legacy_market = pd.read_csv(args.legacy_market, keep_default_na=False)
    config = load_public_market_source_config(args.config)
    top = ranking.sort_values("rank").head(args.top_n).copy()
    market_by_ticker = {str(row["ticker"]).upper(): row.to_dict() for _, row in legacy_market.iterrows()}

    fetch_results = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(fetch_public_market_csv_with_log, row["ticker"], config): row for _, row in top.iterrows()}
        for future in as_completed(futures):
            row = futures[future]
            fetch_results[str(row["ticker"]).upper()] = (row, future.result())

    cross_rows = []
    attempt_rows = []
    for ticker, (rank_row, fetch_result) in sorted(fetch_results.items(), key=lambda item: int(item[1][0].get("rank", 0))):
        summary = compute_market_summary(fetch_result["frame"])
        legacy_row = market_by_ticker.get(ticker, {"ticker": ticker})
        cross_rows.append(
            crosscheck_market_row(
                legacy_row,
                {**summary, "ticker": ticker},
                rank=int(rank_row.get("rank", 0) or 0),
                fetch_status=fetch_result["attempt_status"],
            )
        )
        attempt_rows.append({column: fetch_result.get(column, "") for column in ATTEMPT_LOG_COLUMNS})

    crosscheck = pd.DataFrame(cross_rows, columns=MARKET_CROSSCHECK_COLUMNS)
    attempts = pd.DataFrame(attempt_rows, columns=ATTEMPT_LOG_COLUMNS)
    crosscheck.to_csv(output_dir / "market_price_crosscheck.csv", index=False)
    attempts.to_csv(output_dir / "market_crosscheck_attempt_log.csv", index=False)
    print(
        {
            "output_dir": str(output_dir),
            "top_n_attempted": len(attempts),
            "attempt_status_counts": attempts["attempt_status"].value_counts().to_dict() if not attempts.empty else {},
            "price_status_counts": crosscheck["price_crosscheck_status"].value_counts().to_dict() if not crosscheck.empty else {},
            "full_repo_downloaded": "No",
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
