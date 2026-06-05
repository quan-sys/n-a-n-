from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ingestion.multi_source_evidence import (  # noqa: E402
    load_multi_source_registry,
    load_source_priority_config,
    run_multi_source_evidence,
    save_multi_source_evidence_reports,
)


RAW_FILENAMES = {
    "universe": "universe_raw.csv",
    "company_profile": "company_profile_raw.csv",
    "market_price": "market_price_raw.csv",
    "financial_statement_summary": "financial_statement_summary_raw.csv",
    "disclosure_status": "disclosure_status_raw.csv",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build multi-source evidence reports from already-ingested local data."
    )
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--output-dir", default="data/reports/multi_source_evidence_01f")
    parser.add_argument("--source-registry", default="config/multi_source_registry.yaml")
    parser.add_argument("--source-priority-config", default="config/source_priority.yaml")
    parser.add_argument("--ticker-list", default="")
    parser.add_argument("--input-financials", default="")
    parser.add_argument("--input-disclosure", default="")
    parser.add_argument("--input-annual-report-financials", default="")
    parser.add_argument("--allow-partial", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_datasets = load_raw_datasets(Path(args.raw_dir))

    if args.input_financials:
        _append_manual_source(
            raw_datasets,
            dataset_name="financial_statement_summary",
            input_path=Path(args.input_financials),
            source_category=_manual_category_from_path(Path(args.input_financials)),
        )
    if args.input_annual_report_financials:
        _append_manual_source(
            raw_datasets,
            dataset_name="financial_statement_summary",
            input_path=Path(args.input_annual_report_financials),
            source_category="annual_report_pdf_manual",
        )
    if args.input_disclosure:
        _append_manual_source(
            raw_datasets,
            dataset_name="disclosure_status",
            input_path=Path(args.input_disclosure),
            source_category=_manual_category_from_path(Path(args.input_disclosure)),
        )

    registry = load_multi_source_registry(args.source_registry)
    priority = load_source_priority_config(args.source_priority_config)
    tickers = parse_ticker_list(args.ticker_list) or infer_tickers(raw_datasets)

    if not tickers and not args.allow_partial:
        raise SystemExit(
            "No tickers found. Provide --ticker-list or existing data/raw/universe_raw.csv."
        )

    result = run_multi_source_evidence(
        raw_datasets=raw_datasets,
        requested_tickers=tickers,
        source_registry=registry,
        priority_config=priority,
    )
    report_paths = save_multi_source_evidence_reports(
        result=result,
        output_dir=args.output_dir,
    )
    print(
        {
            "run_id": result["run_id"],
            "output_dir": str(args.output_dir),
            "report_paths": report_paths,
            "step19_implemented": False,
        }
    )
    return 0


def load_raw_datasets(raw_dir: Path) -> dict[str, pd.DataFrame | None]:
    datasets: dict[str, pd.DataFrame | None] = {}
    for dataset_name, filename in RAW_FILENAMES.items():
        path = raw_dir / filename
        datasets[dataset_name] = _read_tabular(path) if path.exists() else None
    return datasets


def _append_manual_source(
    raw_datasets: dict[str, pd.DataFrame | None],
    *,
    dataset_name: str,
    input_path: Path,
    source_category: str,
) -> None:
    manual_df = _read_tabular(input_path)
    manual_df = manual_df.copy()
    manual_df["source_category"] = source_category
    if "source" not in manual_df.columns:
        manual_df["source"] = source_category
    else:
        manual_df["source"] = manual_df["source"].where(
            manual_df["source"].astype(str).str.strip() != "",
            source_category,
        )
    if "confidence_raw" not in manual_df.columns:
        manual_df["confidence_raw"] = "medium"
    existing = raw_datasets.get(dataset_name)
    raw_datasets[dataset_name] = (
        manual_df
        if not isinstance(existing, pd.DataFrame)
        else pd.concat([existing, manual_df], ignore_index=True, sort=False)
    )


def _read_tabular(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, keep_default_na=False)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, keep_default_na=False)
    raise ValueError(f"Unsupported input file format: {path}")


def _manual_category_from_path(path: Path) -> str:
    return "manual_xlsx" if path.suffix.lower() in {".xlsx", ".xls"} else "manual_csv"


def parse_ticker_list(value: str) -> list[str]:
    tickers = []
    for part in (value or "").split(","):
        ticker = part.strip().upper()
        if ticker and ticker not in tickers:
            tickers.append(ticker)
    return tickers


def infer_tickers(raw_datasets: dict[str, pd.DataFrame | None]) -> list[str]:
    tickers = []
    universe = raw_datasets.get("universe")
    candidates: list[pd.DataFrame | None] = [universe, *raw_datasets.values()]
    for df in candidates:
        if not isinstance(df, pd.DataFrame) or "ticker" not in df.columns:
            continue
        for value in df["ticker"]:
            ticker = str(value).strip().upper()
            if ticker and ticker not in tickers:
                tickers.append(ticker)
    return tickers


if __name__ == "__main__":
    raise SystemExit(main())
