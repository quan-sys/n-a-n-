"""REAL-DATA-01: ingest first real/manual tickers and dry-run to Step 18."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ingestion.contracts import (  # noqa: E402
    PROHIBITED_RECOMMENDATION_FIELDS,
    load_ingestion_contracts,
    validate_dataset_columns,
)
from src.ingestion.manifest import (  # noqa: E402
    create_ingestion_manifest_record,
    save_ingestion_manifest,
)
from src.ingestion.pipeline_dry_run import run_pipeline_dry_run  # noqa: E402
from src.ingestion.real_source_adapters import (  # noqa: E402
    build_source_adapter_status,
    create_manual_templates,
    empty_source_adapter_status,
)
from src.ingestion.source_rate_limit import (  # noqa: E402
    SourceRequestTracker,
    empty_source_request_summary,
    external_error_text,
)


RUN_TYPE = "REAL-DATA-01"
STATUS_REAL_INGESTED = "REAL_DATA_INGESTED"
STATUS_MANUAL_IMPORTED = "MANUAL_DATA_IMPORTED"
STATUS_PARTIAL_REAL = "PARTIAL_REAL_DATA_INGESTED"
STATUS_REAL_UNAVAILABLE = "REAL_SOURCE_UNAVAILABLE"
STATUS_REAL_DATA_NOT_AVAILABLE = "REAL_DATA_NOT_AVAILABLE"
STATUS_DRY_RUN_COMPLETED = "PIPELINE_DRY_RUN_COMPLETED_TO_STEP18"
STATUS_DRY_RUN_PARTIAL = "PIPELINE_DRY_RUN_PARTIAL"
STATUS_INSUFFICIENT_STEP18 = "INSUFFICIENT_DATA_FOR_STEP18"
STATUS_MANUAL_REVIEW = "MANUAL_REVIEW_REQUIRED"
STATUS_FAILED = "FAILED"

DATASETS = [
    "universe",
    "company_profile",
    "market_price",
    "financial_statement_summary",
    "disclosure_status",
]

RAW_FILENAMES = {
    "universe": "universe_raw.csv",
    "company_profile": "company_profile_raw.csv",
    "market_price": "market_price_raw.csv",
    "financial_statement_summary": "financial_statement_summary_raw.csv",
    "disclosure_status": "disclosure_status_raw.csv",
}

RAW_COLUMNS = {
    "universe": [
        "ticker",
        "exchange",
        "company_name",
        "listing_status",
        "data_source",
        "last_updated",
        "source",
        "source_url",
        "fetch_time",
        "confidence_raw",
        "notes",
    ],
    "company_profile": [
        "ticker",
        "company_name",
        "exchange",
        "industry_raw",
        "business_description",
        "source",
        "source_url",
        "last_updated",
        "fetch_time",
        "confidence_raw",
        "notes",
    ],
    "market_price": [
        "ticker",
        "date",
        "close",
        "volume",
        "trading_value",
        "source",
        "source_url",
        "fetch_time",
        "confidence_raw",
        "notes",
    ],
    "financial_statement_summary": [
        "ticker",
        "period",
        "period_type",
        "revenue",
        "gross_profit",
        "operating_profit",
        "net_profit",
        "total_assets",
        "total_liabilities",
        "equity",
        "cash",
        "short_term_debt",
        "long_term_debt",
        "operating_cash_flow",
        "inventory",
        "source",
        "source_url",
        "fetch_time",
        "confidence_raw",
        "notes",
    ],
    "disclosure_status": [
        "ticker",
        "event_date",
        "event_type",
        "severity",
        "title",
        "description",
        "source",
        "source_url",
        "fetch_time",
        "confidence_raw",
        "notes",
    ],
}

TICKER_STATUS_COLUMNS = [
    "ticker",
    "universe_status",
    "profile_status",
    "market_price_status",
    "financial_statement_status",
    "disclosure_status",
    "clean_data_status",
    "data_quality_status",
    "l0_trash_status",
    "l0_basic_status",
    "classification_status",
    "archetype_status",
    "driver_status",
    "indicator_status",
    "sector_cycle_status",
    "manual_review_required",
    "warning_flags",
    "notes",
]

FAILED_TICKER_COLUMNS = ["ticker", "dataset_name", "status", "reason", "notes"]

FINANCIAL_FIELD_ALIASES = {
    "revenue": ["sales", "revenue"],
    "gross_profit": ["gross_profit"],
    "operating_profit": ["operating_profit", "operating_income"],
    "net_profit": ["post_tax_profit", "net_profit", "net_profit_after_tax"],
    "total_assets": ["total_assets"],
    "total_liabilities": ["liabilities", "total_liabilities"],
    "equity": ["owners_equity", "equity"],
    "cash": ["cash_and_cash_equivalents", "cash"],
    "short_term_debt": ["short_term_borrowings", "short_term_debt"],
    "long_term_debt": ["long_term_borrowings", "long_term_debt"],
    "operating_cash_flow": ["net_cash_inflows_outflows_from_operating_activities"],
    "inventory": ["inventories_net", "inventories"],
}


def main() -> int:
    args = parse_args()
    result = run_real_data_01(args)
    print(json.dumps(result["console_summary"], ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--mode", choices=["real", "manual_csv", "manual_xlsx"], default="real")
    parser.add_argument(
        "--ticker-selection",
        choices=["first_from_universe", "representative", "manual_list"],
        default="first_from_universe",
    )
    parser.add_argument(
        "--representative-config",
        default="config/real_data_first_20_representative_tickers.yaml",
    )
    parser.add_argument("--ticker-list", help="Comma-separated tickers for --ticker-selection manual_list.")
    parser.add_argument("--input-tickers", help="CSV/TXT file with manual ticker list.")
    parser.add_argument("--input-universe")
    parser.add_argument("--input-profile")
    parser.add_argument("--input-market")
    parser.add_argument("--input-financials")
    parser.add_argument("--input-disclosure")
    parser.add_argument("--output-dir", default="data/reports/real_data_first_20")
    parser.add_argument("--raw-output-dir", default="data/raw")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--dry-source-unavailable", action="store_true")
    parser.add_argument(
        "--request-pause-seconds",
        "--request-sleep-seconds",
        dest="request_pause_seconds",
        type=float,
        default=3.2,
        help="Pause between real-source calls to avoid guest API rate limits.",
    )
    parser.add_argument(
        "--real-source-max-requests",
        type=int,
        default=18,
        help="Maximum real-source calls for this audit run; exhausted budget is reported as unavailable data.",
    )
    parser.add_argument("--market-lookback-days", type=int, default=90)
    parser.add_argument("--market-max-retries", type=int, default=1)
    parser.add_argument(
        "--financial-template-output",
        default="data/templates/financial_statement_summary_template.csv",
    )
    parser.add_argument(
        "--disclosure-template-output",
        default="data/templates/disclosure_status_template.csv",
    )
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    return parser.parse_args()


def run_real_data_01(args: argparse.Namespace) -> dict[str, Any]:
    started_at = utc_now()
    run_id = f"real_data_first_20_{safe_token(started_at)}"
    output_dir = Path(args.output_dir)
    raw_output_dir = Path(args.raw_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_output_dir.mkdir(parents=True, exist_ok=True)
    template_paths = create_manual_templates(
        financial_template_path=args.financial_template_output,
        disclosure_template_path=args.disclosure_template_output,
    )

    if args.dry_source_unavailable:
        return write_failure_reports(
            output_dir=output_dir,
            raw_output_dir=raw_output_dir,
            run_id=run_id,
            started_at=started_at,
            mode=args.mode,
            status=STATUS_REAL_UNAVAILABLE,
            reason="dry-source-unavailable flag set; no real source call attempted",
            requested_limit=args.limit,
            template_paths=template_paths,
        )

    if args.mode == "real":
        raw_datasets, fetch_status = fetch_real_vnstock_data(
            limit=args.limit,
            started_at=started_at,
            start_date=args.start_date,
            end_date=args.end_date,
            request_pause_seconds=args.request_pause_seconds,
            real_source_max_requests=args.real_source_max_requests,
            ticker_selection=args.ticker_selection,
            representative_config=args.representative_config,
            ticker_list=args.ticker_list,
            input_tickers=args.input_tickers,
            input_financials=args.input_financials,
            input_disclosure=args.input_disclosure,
            market_lookback_days=args.market_lookback_days,
            market_max_retries=args.market_max_retries,
        )
        if fetch_status["overall_status"] in {
            STATUS_REAL_UNAVAILABLE,
            STATUS_REAL_DATA_NOT_AVAILABLE,
        }:
            return write_failure_reports(
                output_dir=output_dir,
                raw_output_dir=raw_output_dir,
                run_id=run_id,
                started_at=started_at,
                mode=args.mode,
                status=fetch_status["overall_status"],
                reason="; ".join(fetch_status["errors"] or fetch_status["warnings"]),
                requested_limit=args.limit,
                template_paths=template_paths,
                source_request_summary=fetch_status.get("source_request_summary"),
                source_adapter_status=fetch_status.get("source_adapter_status"),
            )
    else:
        raw_datasets, fetch_status = load_manual_data(args, started_at)
        if fetch_status["overall_status"] == STATUS_FAILED:
            return write_failure_reports(
                output_dir=output_dir,
                raw_output_dir=raw_output_dir,
                run_id=run_id,
                started_at=started_at,
                mode=args.mode,
                status=STATUS_FAILED,
                reason="; ".join(fetch_status["errors"]),
                failed_rows=fetch_status["failed_tickers"],
                requested_limit=args.limit,
                template_paths=template_paths,
            )

    save_raw_files(raw_datasets, raw_output_dir)
    save_manifests(
        raw_datasets=raw_datasets,
        fetch_status=fetch_status,
        output_dir=output_dir / "ingestion_manifests",
        run_id=run_id,
        mode=args.mode,
        started_at=started_at,
    )

    dry_run = run_pipeline_dry_run(
        raw_datasets=raw_datasets,
        reports_dir=output_dir,
        run_size="mini",
        run_id=run_id,
        reference_date=started_at[:10],
        write_reports=True,
    )
    reports = write_real_data_reports(
        output_dir=output_dir,
        raw_datasets=raw_datasets,
        fetch_status=fetch_status,
        dry_run=dry_run,
        run_id=run_id,
        started_at=started_at,
        mode=args.mode,
        requested_limit=args.limit,
        ticker_selection=args.ticker_selection,
        template_paths=template_paths,
    )
    return {
        "console_summary": {
            "run_id": run_id,
            "status": reports["run_status"],
            "mode": args.mode,
            "requested": args.limit,
            "ingested_ticker_count": len(fetch_status["tickers"]),
            "tickers": fetch_status["tickers"],
            "output_dir": str(output_dir),
            "raw_output_dir": str(raw_output_dir),
            "step19_implemented": False,
        },
        "reports": reports,
    }


def fetch_real_vnstock_data(
    *,
    limit: int,
    started_at: str,
    start_date: str | None,
    end_date: str | None,
    request_pause_seconds: float,
    real_source_max_requests: int,
    ticker_selection: str,
    representative_config: str,
    ticker_list: str | None,
    input_tickers: str | None,
    input_financials: str | None,
    input_disclosure: str | None,
    market_lookback_days: int,
    market_max_retries: int,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    status = new_fetch_status("real")
    request_tracker = SourceRequestTracker(real_source_max_requests)
    try:
        from vnstock import Company, Finance, Listing, Quote
    except BaseException as exc:  # noqa: BLE001
        if isinstance(exc, KeyboardInterrupt):
            raise
        error_text = external_error_text(exc)
        request_tracker.record_dependency_error(
            source_name="vnstock", dataset_name="all", error_text=error_text
        )
        status["overall_status"] = STATUS_REAL_UNAVAILABLE
        status["errors"].append(f"vnstock import failed: {error_text}")
        status["source_request_summary"] = request_tracker.to_frame()
        status["source_adapter_status"] = build_source_adapter_status(
            vnstock_available=False
        )
        return empty_raw_datasets(), status

    listing_df, listing_error = request_tracker.request(
        source_name="vnstock:kbs",
        dataset_name="universe",
        action=lambda: Listing(source="kbs").symbols_by_exchange(),
        pause_seconds=request_pause_seconds,
    )
    if listing_error:
        status["overall_status"] = STATUS_REAL_UNAVAILABLE
        status["errors"].append(f"vnstock Listing(source='kbs') failed: {listing_error}")
        status["source_request_summary"] = request_tracker.to_frame()
        status["source_adapter_status"] = build_source_adapter_status(
            vnstock_available=True
        )
        return empty_raw_datasets(), status

    universe_source, ticker_warnings = select_listing_universe(
        listing_df,
        limit=limit,
        fetch_time=started_at,
        ticker_selection=ticker_selection,
        representative_config=representative_config,
        ticker_list=ticker_list,
        input_tickers=input_tickers,
    )
    status["warnings"].extend(ticker_warnings)
    if universe_source.empty:
        status["overall_status"] = STATUS_REAL_DATA_NOT_AVAILABLE
        status["errors"].append("real universe source returned no valid stock tickers")
        status["source_request_summary"] = request_tracker.to_frame()
        status["source_adapter_status"] = build_source_adapter_status(
            vnstock_available=True
        )
        return empty_raw_datasets(), status

    tickers = universe_source["ticker"].tolist()
    status["tickers"] = tickers
    status["dataset_status"]["universe"] = STATUS_REAL_INGESTED

    market_rows, market_failed = fetch_market_prices(
        Quote=Quote,
        tickers=tickers,
        started_at=started_at,
        start_date=start_date,
        end_date=end_date,
        request_pause_seconds=request_pause_seconds,
        request_tracker=request_tracker,
        market_lookback_days=market_lookback_days,
        market_max_retries=market_max_retries,
    )
    profile_rows, profile_failed = fetch_company_profiles(
        Company=Company,
        universe_df=universe_source,
        started_at=started_at,
        request_pause_seconds=request_pause_seconds,
        request_tracker=request_tracker,
    )
    financial_rows, financial_failed = fetch_financial_summaries(
        Finance=Finance,
        tickers=tickers,
        started_at=started_at,
        request_pause_seconds=request_pause_seconds,
        request_tracker=request_tracker,
    )
    financial_rows_from_manual = False
    manual_financial_df, manual_financial_failed = load_real_mode_manual_fallback(
        path=input_financials,
        dataset_name="financial_statement_summary",
        tickers=tickers,
        mode="manual_csv" if input_financials else "manual_csv",
    )
    if not financial_rows and input_financials and not manual_financial_df.empty:
        financial_rows = manual_financial_df.to_dict("records")
        financial_failed = manual_financial_failed
        status["dataset_status"]["financial_statement_summary"] = STATUS_MANUAL_IMPORTED
        financial_rows_from_manual = True
    elif not financial_rows:
        financial_failed = [
            failed_row(
                ticker,
                "financial_statement_summary",
                "FINANCIAL_STATEMENT_DATA_UNAVAILABLE",
                "real source unavailable or budget exhausted; use data/templates/financial_statement_summary_template.csv or --input-financials",
            )
            for ticker in tickers
        ]

    disclosure_rows, disclosure_failed = fetch_disclosures(
        Company=Company,
        tickers=tickers,
        started_at=started_at,
        request_pause_seconds=request_pause_seconds,
        request_tracker=request_tracker,
    )
    disclosure_rows_from_manual = False
    manual_disclosure_df, manual_disclosure_failed = load_real_mode_manual_fallback(
        path=input_disclosure,
        dataset_name="disclosure_status",
        tickers=tickers,
        mode="manual_csv" if input_disclosure else "manual_csv",
    )
    if not disclosure_rows and input_disclosure and not manual_disclosure_df.empty:
        disclosure_rows = manual_disclosure_df.to_dict("records")
        disclosure_failed = manual_disclosure_failed
        status["dataset_status"]["disclosure_status"] = STATUS_MANUAL_IMPORTED
        disclosure_rows_from_manual = True
    elif not disclosure_rows:
        disclosure_failed = [
            failed_row(
                ticker,
                "disclosure_status",
                "DISCLOSURE_DATA_UNAVAILABLE",
                "real source unavailable or budget exhausted; no disclosure is unknown, not clean; use data/templates/disclosure_status_template.csv or --input-disclosure",
            )
            for ticker in tickers
        ]

    if request_tracker.remaining is not None and request_tracker.remaining <= 0:
        status["warnings"].append(
            "REAL_SOURCE_REQUEST_BUDGET_EXHAUSTED: remaining datasets are partial/unavailable to avoid rate limit"
        )

    raw_datasets = {
        "universe": universe_source,
        "company_profile": pd.DataFrame(profile_rows, columns=RAW_COLUMNS["company_profile"]),
        "market_price": pd.DataFrame(market_rows, columns=RAW_COLUMNS["market_price"]),
        "financial_statement_summary": pd.DataFrame(
            financial_rows, columns=RAW_COLUMNS["financial_statement_summary"]
        ),
        "disclosure_status": pd.DataFrame(disclosure_rows, columns=RAW_COLUMNS["disclosure_status"]),
    }

    failed = profile_failed + market_failed + financial_failed + disclosure_failed
    status["failed_tickers"] = failed
    for dataset_name in DATASETS:
        if dataset_name == "universe":
            continue
        if status["dataset_status"].get(dataset_name) == STATUS_MANUAL_IMPORTED:
            continue
        row_count = int(len(raw_datasets[dataset_name]))
        failed_count = sum(1 for row in failed if row["dataset_name"] == dataset_name)
        if row_count > 0 and failed_count == 0:
            status["dataset_status"][dataset_name] = STATUS_REAL_INGESTED
        elif row_count > 0:
            status["dataset_status"][dataset_name] = STATUS_PARTIAL_REAL
        else:
            status["dataset_status"][dataset_name] = STATUS_REAL_DATA_NOT_AVAILABLE

    status["warnings"].extend(
        f"{row['ticker']}:{row['dataset_name']}:{row['reason']}" for row in failed
    )
    status["overall_status"] = (
        STATUS_REAL_INGESTED
        if all(value == STATUS_REAL_INGESTED for value in status["dataset_status"].values())
        else STATUS_PARTIAL_REAL
    )
    status["source_request_summary"] = request_tracker.to_frame()
    status["source_adapter_status"] = build_source_adapter_status(
        vnstock_available=True,
        financial_real_rows=0 if financial_rows_from_manual else len(financial_rows),
        disclosure_real_rows=0 if disclosure_rows_from_manual else len(disclosure_rows),
    )
    return raw_datasets, status


def select_listing_universe(
    df: pd.DataFrame,
    *,
    limit: int,
    fetch_time: str,
    ticker_selection: str,
    representative_config: str,
    ticker_list: str | None,
    input_tickers: str | None,
) -> tuple[pd.DataFrame, list[str]]:
    universe = normalize_listing_universe(df, None, fetch_time)
    warnings: list[str] = []
    if ticker_selection == "first_from_universe":
        return universe.head(limit).copy(), warnings

    if ticker_selection == "representative":
        config = load_representative_ticker_config(representative_config)
        desired_tickers = config["tickers"]
        if "engineering" not in config.get("purpose", ""):
            warnings.append("REPRESENTATIVE_CONFIG_PURPOSE_NOT_ENGINEERING_ONLY")
    else:
        desired_tickers = parse_manual_ticker_list(ticker_list, input_tickers)

    selected = select_universe_rows_by_ticker(universe, desired_tickers, limit)
    selected_tickers = set(selected["ticker"]) if "ticker" in selected.columns else set()
    missing = [ticker for ticker in desired_tickers[:limit] if ticker not in selected_tickers]
    if missing:
        warnings.append(
            "REQUESTED_TICKERS_NOT_IN_REAL_UNIVERSE:" + ",".join(missing)
        )
    return selected, warnings


def normalize_listing_universe(df: pd.DataFrame, limit: int | None, fetch_time: str) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame(columns=RAW_COLUMNS["universe"])
    source = df.copy()
    source["symbol"] = source["symbol"].map(clean_ticker)
    if "exchange" not in source.columns:
        source["exchange"] = ""
    if "type" in source.columns:
        source = source[source["type"].astype(str).str.lower() == "stock"]
    source = source[source["exchange"].isin(["HOSE", "HNX", "UPCOM"])]
    source = source[source["symbol"].map(bool)].drop_duplicates("symbol")
    if limit is not None:
        source = source.head(limit)
    rows = []
    for _, row in source.iterrows():
        rows.append(
            {
                "ticker": row["symbol"],
                "exchange": row.get("exchange", ""),
                "company_name": clean_text(row.get("organ_name")),
                "listing_status": "LISTED",
                "data_source": "vnstock:kbs:symbols_by_exchange",
                "last_updated": fetch_time[:10],
                "source": "vnstock:kbs",
                "source_url": "https://vnstocks.com/",
                "fetch_time": fetch_time,
                "confidence_raw": "medium",
                "notes": "real universe row from vnstock Listing.symbols_by_exchange",
            }
        )
    return pd.DataFrame(rows, columns=RAW_COLUMNS["universe"])


def load_representative_ticker_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file) or {}
    tickers = [clean_ticker(ticker) for ticker in config.get("tickers", [])]
    tickers = [ticker for ticker in tickers if ticker]
    return {
        "purpose": str(config.get("purpose", "")),
        "notes": str(config.get("notes", "")),
        "tickers": dedupe(tickers),
    }


def parse_manual_ticker_list(ticker_list: str | None, input_tickers: str | None) -> list[str]:
    tickers: list[str] = []
    if ticker_list:
        tickers.extend(ticker_list.split(","))
    if input_tickers:
        path = Path(input_tickers)
        if path.suffix.lower() == ".csv":
            df = pd.read_csv(path)
            column = "ticker" if "ticker" in df.columns else df.columns[0]
            tickers.extend(df[column].tolist())
        else:
            tickers.extend(path.read_text(encoding="utf-8").replace("\n", ",").split(","))
    return dedupe([clean_ticker(ticker) for ticker in tickers if clean_ticker(ticker)])


def select_universe_rows_by_ticker(
    universe: pd.DataFrame, desired_tickers: list[str], limit: int
) -> pd.DataFrame:
    if universe.empty or "ticker" not in universe.columns:
        return pd.DataFrame(columns=RAW_COLUMNS["universe"])
    by_ticker = {
        clean_ticker(row["ticker"]): row
        for _, row in universe.iterrows()
        if clean_ticker(row.get("ticker"))
    }
    rows = [
        by_ticker[ticker].to_dict()
        for ticker in desired_tickers
        if ticker in by_ticker
    ][:limit]
    return pd.DataFrame(rows, columns=RAW_COLUMNS["universe"])


def fetch_company_profiles(
    *,
    Company: Any,
    universe_df: pd.DataFrame,
    started_at: str,
    request_pause_seconds: float,
    request_tracker: SourceRequestTracker,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for _, universe_row in universe_df.iterrows():
        ticker = universe_row["ticker"]
        detail = {}
        notes = ["company profile initialized from real universe source"]
        overview, overview_error = request_tracker.request(
            source_name="vnstock:kbs",
            dataset_name="company_profile",
            action=lambda ticker=ticker: Company(source="KBS", symbol=ticker).overview(),
            pause_seconds=request_pause_seconds,
        )
        if isinstance(overview, pd.DataFrame) and not overview.empty:
            detail.update(overview.iloc[0].to_dict())
        elif overview_error:
            notes.append(f"KBS overview unavailable: {overview_error}")

        overview_vci, overview_vci_error = request_tracker.request(
            source_name="vnstock:vci",
            dataset_name="company_profile",
            action=lambda ticker=ticker: Company(source="VCI", symbol=ticker).overview(),
            pause_seconds=request_pause_seconds,
        )
        if isinstance(overview_vci, pd.DataFrame) and not overview_vci.empty:
            detail.update({f"vci_{k}": v for k, v in overview_vci.iloc[0].to_dict().items()})
        elif overview_vci_error:
            notes.append(f"VCI overview unavailable: {overview_vci_error}")

        business_description = clean_text(
            first_present_mapping(
                detail,
                [
                    "business_model",
                    "business_description",
                    "company_profile",
                    "company_description",
                    "description",
                    "summary",
                    "vci_business_model",
                    "vci_business_description",
                    "vci_company_profile",
                    "vci_company_description",
                    "vci_description",
                    "vci_summary",
                ],
            )
        )
        industry_raw = clean_text(
            first_present_mapping(
                detail,
                [
                    "industry_raw",
                    "industry",
                    "industry_name",
                    "icb_name",
                    "sector",
                    "tag",
                    "company_type",
                    "vci_industry_raw",
                    "vci_industry",
                    "vci_industry_name",
                    "vci_icb_name",
                    "vci_sector",
                    "vci_tag",
                ],
            )
        )
        if not business_description or not industry_raw:
            warning_flags = []
            if not industry_raw:
                warning_flags.append("MISSING_INDUSTRY_RAW")
            if not business_description:
                warning_flags.append("MISSING_BUSINESS_DESCRIPTION")
            failed.append(
                failed_row(
                    ticker,
                    "company_profile",
                    "PARTIAL_PROFILE_DATA",
                    "|".join(warning_flags) + ": source did not provide required profile fields",
                )
            )
        rows.append(
            {
                "ticker": ticker,
                "company_name": clean_text(detail.get("organ_name") or detail.get("vci_organ_name") or universe_row["company_name"]),
                "exchange": clean_text(detail.get("exchange") or universe_row["exchange"]),
                "industry_raw": industry_raw,
                "business_description": business_description,
                "source": "vnstock:kbs/vci",
                "source_url": "https://vnstocks.com/",
                "last_updated": clean_text(detail.get("as_of_date") or started_at[:10]),
                "fetch_time": started_at,
                "confidence_raw": "medium" if business_description and industry_raw else "low",
                "notes": "; ".join(notes + (warning_flags if not business_description or not industry_raw else [])),
            }
        )
    return rows, failed


def fetch_market_prices(
    *,
    Quote: Any,
    tickers: list[str],
    started_at: str,
    start_date: str | None,
    end_date: str | None,
    request_pause_seconds: float,
    request_tracker: SourceRequestTracker,
    market_lookback_days: int,
    market_max_retries: int,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    end = end_date or started_at[:10]
    start = start_date or (pd.Timestamp(end) - pd.Timedelta(days=market_lookback_days)).strftime("%Y-%m-%d")
    for ticker in tickers:
        history = pd.DataFrame()
        history_error = ""
        for attempt in range(max(0, market_max_retries) + 1):
            history, history_error = request_tracker.request(
                source_name="vnstock:vci",
                dataset_name="market_price",
                action=lambda ticker=ticker: Quote(source="VCI", symbol=ticker).history(
                    start=start, end=end, interval="1D"
                ),
                pause_seconds=request_pause_seconds,
            )
            if isinstance(history, pd.DataFrame) and not history.empty:
                break
            if history_error == "REAL_SOURCE_REQUEST_BUDGET_EXHAUSTED":
                break
            history_error = history_error or "REAL_MARKET_PRICE_EMPTY"
        if history_error:
            failed.append(
                failed_row(
                    ticker,
                    "market_price",
                    "REAL_MARKET_PRICE_UNAVAILABLE",
                    f"{history_error}; attempts={attempt + 1}",
                )
            )
            continue
        if not isinstance(history, pd.DataFrame) or history.empty:
            failed.append(failed_row(ticker, "market_price", "REAL_MARKET_PRICE_EMPTY", "no rows returned"))
            continue
        for _, row in history.iterrows():
            close = to_number(row.get("close"))
            volume = to_number(row.get("volume"))
            trading_value = close * volume if close is not None and volume is not None else pd.NA
            rows.append(
                {
                    "ticker": ticker,
                    "date": date_text(row.get("time")),
                    "close": close,
                    "volume": volume,
                    "trading_value": trading_value,
                    "source": "vnstock:vci:quote_history",
                    "source_url": "https://vnstocks.com/",
                    "fetch_time": started_at,
                    "confidence_raw": "medium",
                    "notes": "real market row from vnstock Quote.history; trading_value derived from fetched close*volume",
                }
            )
    return rows, failed


def fetch_financial_summaries(
    *,
    Finance: Any,
    tickers: list[str],
    started_at: str,
    request_pause_seconds: float,
    request_tracker: SourceRequestTracker,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for ticker in tickers:
        statements: dict[str, pd.DataFrame] = {}
        statement_errors: list[str] = []
        for key, method_name in [
            ("income", "income_statement"),
            ("balance", "balance_sheet"),
            ("cash", "cash_flow"),
        ]:
            df, finance_error = request_tracker.request(
                source_name="vnstock:vci",
                dataset_name="financial_statement_summary",
                action=lambda ticker=ticker, method_name=method_name: getattr(
                    Finance(source="VCI", symbol=ticker, period="quarter", get_all=False),
                    method_name,
                )(),
                pause_seconds=request_pause_seconds,
            )
            if finance_error:
                statements[key] = pd.DataFrame()
                statement_errors.append(f"{method_name}:{finance_error}")
            else:
                statements[key] = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
        latest_period = latest_financial_period(statements.values())
        if not latest_period:
            failed.append(
                failed_row(
                    ticker,
                    "financial_statement_summary",
                    "FINANCIAL_STATEMENT_DATA_UNAVAILABLE",
                    "; ".join(statement_errors) or "no financial statement rows returned",
                )
            )
            continue
        record = {
            "ticker": ticker,
            "period": latest_period,
            "period_type": "quarter",
            "source": "vnstock:vci:finance",
            "source_url": "https://vnstocks.com/",
            "fetch_time": started_at,
            "confidence_raw": "medium",
            "notes": "real financial statement summary from vnstock Finance; missing mapped fields left blank",
        }
        for field, aliases in FINANCIAL_FIELD_ALIASES.items():
            record[field] = lookup_financial_value(statements, aliases, latest_period)
        missing = [field for field in FINANCIAL_FIELD_ALIASES if is_missing(record.get(field))]
        if missing:
            failed.append(
                failed_row(
                    ticker,
                    "financial_statement_summary",
                    "PARTIAL_FINANCIAL_FIELDS",
                    "missing mapped fields: " + ",".join(missing),
                )
            )
        rows.append(record)
    return rows, failed


def fetch_disclosures(
    *,
    Company: Any,
    tickers: list[str],
    started_at: str,
    request_pause_seconds: float,
    request_tracker: SourceRequestTracker,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for ticker in tickers:
        events, events_error = request_tracker.request(
            source_name="vnstock:kbs",
            dataset_name="disclosure_status",
            action=lambda ticker=ticker: Company(source="KBS", symbol=ticker).events(),
            pause_seconds=request_pause_seconds,
        )
        if events_error:
            events = pd.DataFrame()
            failed.append(
                failed_row(
                    ticker,
                    "disclosure_status",
                    "DISCLOSURE_DATA_UNAVAILABLE",
                    f"{events_error}; absence is unknown, not clean",
                )
            )
            continue
        if not isinstance(events, pd.DataFrame) or events.empty:
            failed.append(
                failed_row(
                    ticker,
                    "disclosure_status",
                    "DISCLOSURE_DATA_UNAVAILABLE",
                    "no disclosure/event rows returned; absence is unknown, not clean",
                )
            )
            continue
        for _, row in events.iterrows():
            rows.append(
                {
                    "ticker": ticker,
                    "event_date": date_text(first_present(row, ["date", "event_date", "exer_date", "public_date"])),
                    "event_type": "OTHER",
                    "severity": "UNKNOWN",
                    "title": clean_text(first_present(row, ["title", "event_title", "event_name", "content"])),
                    "description": clean_text(first_present(row, ["description", "content", "event_desc"])),
                    "source": "vnstock:kbs:company_events",
                    "source_url": "https://vnstocks.com/",
                    "fetch_time": started_at,
                    "confidence_raw": "low",
                    "notes": "real company event row from vnstock; event type/severity require manual review",
                }
            )
    return rows, failed


def load_manual_data(args: argparse.Namespace, started_at: str) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    status = new_fetch_status(args.mode)
    contracts = load_ingestion_contracts()
    input_paths = {
        "universe": args.input_universe,
        "company_profile": args.input_profile,
        "market_price": args.input_market,
        "financial_statement_summary": args.input_financials,
        "disclosure_status": args.input_disclosure,
    }
    raw_datasets = empty_raw_datasets()
    if not input_paths["universe"]:
        status["overall_status"] = STATUS_FAILED
        status["errors"].append("manual mode requires --input-universe")
        return raw_datasets, status

    file_loader = pd.read_csv if args.mode == "manual_csv" else pd.read_excel
    try:
        universe_df = file_loader(input_paths["universe"])
    except Exception as exc:  # noqa: BLE001
        status["overall_status"] = STATUS_FAILED
        status["errors"].append(f"failed to read universe file: {exc}")
        return raw_datasets, status
    validation = validate_dataset_columns(universe_df, "universe", contracts)
    if not validation["is_valid"]:
        status["overall_status"] = STATUS_FAILED
        reason = "universe validation failed: " + ",".join(validation["missing_required_columns"])
        status["errors"].append(reason)
        status["failed_tickers"].append(
            failed_row("", "universe", STATUS_FAILED, reason)
        )
        return raw_datasets, status

    universe_df = ensure_columns(universe_df.head(args.limit).copy(), RAW_COLUMNS["universe"])
    tickers = [clean_ticker(value) for value in universe_df["ticker"] if clean_ticker(value)]
    status["tickers"] = tickers
    raw_datasets["universe"] = universe_df
    status["dataset_status"]["universe"] = STATUS_MANUAL_IMPORTED

    for dataset_name, path in input_paths.items():
        if dataset_name == "universe":
            continue
        if not path:
            status["dataset_status"][dataset_name] = STATUS_REAL_DATA_NOT_AVAILABLE
            status["failed_tickers"].extend(
                failed_row(ticker, dataset_name, "MANUAL_FILE_NOT_PROVIDED", "input file not provided")
                for ticker in tickers
            )
            continue
        df = file_loader(path)
        validation = validate_dataset_columns(df, dataset_name, contracts)
        if not validation["is_valid"]:
            status["dataset_status"][dataset_name] = STATUS_FAILED
            reason = f"{dataset_name} validation failed: {validation['missing_required_columns']}"
            status["errors"].append(reason)
            status["failed_tickers"].extend(
                failed_row(ticker, dataset_name, STATUS_FAILED, reason)
                for ticker in tickers
            )
            continue
        if "ticker" in df.columns:
            df = df[df["ticker"].map(clean_ticker).isin(set(tickers))]
        raw_datasets[dataset_name] = ensure_columns(df.copy(), RAW_COLUMNS[dataset_name])
        status["dataset_status"][dataset_name] = STATUS_MANUAL_IMPORTED
    status["overall_status"] = (
        STATUS_MANUAL_IMPORTED if not status["errors"] else STATUS_DRY_RUN_PARTIAL
    )
    return raw_datasets, status


def load_real_mode_manual_fallback(
    *,
    path: str | None,
    dataset_name: str,
    tickers: list[str],
    mode: str,
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    if not path:
        return pd.DataFrame(columns=RAW_COLUMNS[dataset_name]), []
    try:
        contracts = load_ingestion_contracts()
        loader = pd.read_excel if Path(path).suffix.lower() in {".xlsx", ".xls"} else pd.read_csv
        df = loader(path)
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(columns=RAW_COLUMNS[dataset_name]), [
            failed_row(ticker, dataset_name, STATUS_FAILED, f"manual fallback read failed: {exc}")
            for ticker in tickers
        ]
    validation = validate_dataset_columns(df, dataset_name, contracts)
    if not validation["is_valid"]:
        reason = f"manual fallback validation failed: {validation['missing_required_columns']}"
        return pd.DataFrame(columns=RAW_COLUMNS[dataset_name]), [
            failed_row(ticker, dataset_name, STATUS_FAILED, reason)
            for ticker in tickers
        ]
    if "ticker" in df.columns:
        df = df[df["ticker"].map(clean_ticker).isin(set(tickers))]
    return ensure_columns(df.copy(), RAW_COLUMNS[dataset_name]), []


def write_failure_reports(
    *,
    output_dir: Path,
    raw_output_dir: Path,
    run_id: str,
    started_at: str,
    mode: str,
    status: str,
    reason: str,
    failed_rows: list[dict[str, str]] | None = None,
    requested_limit: int = 0,
    template_paths: dict[str, str] | None = None,
    source_request_summary: pd.DataFrame | None = None,
    source_adapter_status: pd.DataFrame | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    failed_df = pd.DataFrame(failed_rows or [], columns=FAILED_TICKER_COLUMNS)
    errors_df = pd.DataFrame(
        [{"stage": "ingestion", "dataset_name": "", "ticker": "", "error_code": status, "message": reason, "notes": ""}]
    )
    coverage_df = pd.DataFrame(
        [
            {
                "dataset_name": dataset,
                "row_count": 0,
                "ticker_count": 0,
                "min_date": "",
                "max_date": "",
                "missing_required_field_count": 0,
                "stale_data_count": 0,
                "data_conflict_count": 0,
                "low_confidence_count": 0,
                "failed_ticker_count": 0,
                "coverage_status": status,
                "notes": reason,
            }
            for dataset in DATASETS
        ]
    )
    stage_df = pd.DataFrame(
        [{"stage": "ingestion", "status": status, "input_count": 0, "output_count": 0, "warnings": reason, "errors": reason, "notes": "pipeline did not run"}]
    )
    ticker_df = pd.DataFrame(columns=TICKER_STATUS_COLUMNS)
    manual_df = pd.DataFrame(columns=["ticker", "module", "issue", "severity", "status", "evidence", "confidence", "notes"])
    missing_df = pd.DataFrame(
        [{"dataset_name": dataset, "issue": status, "ticker": "", "notes": reason} for dataset in DATASETS]
    )

    coverage_df.to_csv(output_dir / "data_coverage_report.csv", index=False)
    stage_df.to_csv(output_dir / "pipeline_stage_status.csv", index=False)
    ticker_df.to_csv(output_dir / "ticker_level_status.csv", index=False)
    missing_df.to_csv(output_dir / "missing_data_report.csv", index=False)
    manual_df.to_csv(output_dir / "manual_review_queue.csv", index=False)
    failed_df.to_csv(output_dir / "failed_tickers.csv", index=False)
    errors_df.to_csv(output_dir / "pipeline_errors.csv", index=False)
    (source_request_summary if isinstance(source_request_summary, pd.DataFrame) else empty_source_request_summary()).to_csv(
        output_dir / "source_request_summary.csv", index=False
    )
    (source_adapter_status if isinstance(source_adapter_status, pd.DataFrame) else build_source_adapter_status()).to_csv(
        output_dir / "source_adapter_status.csv", index=False
    )
    run_summary = render_run_summary(
        run_id=run_id,
        started_at=started_at,
        finished_at=utc_now(),
        mode=mode,
        run_status=status,
        dry_run_status=STATUS_FAILED,
        tickers=[],
        requested_limit=requested_limit,
        raw_datasets=empty_raw_datasets(),
        dataset_status={dataset: status for dataset in DATASETS},
        stages=[],
        errors=[reason],
        step19_implemented=False,
        next_action="fix real/manual data source availability first",
        ticker_selection="",
        template_paths=template_paths or {},
    )
    (output_dir / "run_summary.md").write_text(run_summary, encoding="utf-8")
    return {
        "console_summary": {
            "run_id": run_id,
            "status": status,
            "mode": mode,
            "reason": reason,
            "output_dir": str(output_dir),
            "raw_output_dir": str(raw_output_dir),
            "step19_implemented": False,
        },
        "reports": {"run_status": status, "output_dir": str(output_dir)},
    }


def write_real_data_reports(
    *,
    output_dir: Path,
    raw_datasets: dict[str, pd.DataFrame],
    fetch_status: dict[str, Any],
    dry_run: dict[str, Any],
    run_id: str,
    started_at: str,
    mode: str,
    requested_limit: int,
    ticker_selection: str,
    template_paths: dict[str, str],
) -> dict[str, Any]:
    summary = dry_run["summary"]
    dry_status = (
        STATUS_DRY_RUN_COMPLETED
        if summary["error_count"] == 0 and not has_insufficient_step18(dry_run)
        else STATUS_DRY_RUN_PARTIAL
    )
    run_status = (
        STATUS_PARTIAL_REAL
        if fetch_status["overall_status"] == STATUS_PARTIAL_REAL or dry_status == STATUS_DRY_RUN_PARTIAL
        else fetch_status["overall_status"]
    )
    if has_insufficient_step18(dry_run):
        run_status = STATUS_INSUFFICIENT_STEP18

    stage_df = pd.DataFrame(dry_run["module_status_records"])
    stage_df = serialize_json_columns(stage_df, ["warnings", "errors"])
    stage_df.to_csv(output_dir / "pipeline_stage_status.csv", index=False)

    failed_df = pd.DataFrame(fetch_status["failed_tickers"], columns=FAILED_TICKER_COLUMNS)
    failed_df.to_csv(output_dir / "failed_tickers.csv", index=False)

    source_request_df = fetch_status.get("source_request_summary", empty_source_request_summary())
    if not isinstance(source_request_df, pd.DataFrame):
        source_request_df = empty_source_request_summary()
    source_request_df.to_csv(output_dir / "source_request_summary.csv", index=False)

    source_adapter_df = fetch_status.get("source_adapter_status", empty_source_adapter_status())
    if not isinstance(source_adapter_df, pd.DataFrame) or source_adapter_df.empty:
        source_adapter_df = build_source_adapter_status(
            financial_real_rows=len(raw_datasets.get("financial_statement_summary", pd.DataFrame())),
            disclosure_real_rows=len(raw_datasets.get("disclosure_status", pd.DataFrame())),
        )
    source_adapter_df.to_csv(output_dir / "source_adapter_status.csv", index=False)

    ticker_df = build_ticker_level_status(
        tickers=fetch_status["tickers"],
        fetch_status=fetch_status,
        dry_run=dry_run,
    )
    ticker_df.to_csv(output_dir / "ticker_level_status.csv", index=False)

    coverage_df = dry_run["coverage_report"].copy()
    failed_counts = failed_df.groupby("dataset_name").size().to_dict() if not failed_df.empty else {}
    coverage_df["failed_ticker_count"] = coverage_df["dataset_name"].map(lambda value: int(failed_counts.get(value, 0)))
    coverage_cols = [
        "dataset_name",
        "row_count",
        "ticker_count",
        "min_date",
        "max_date",
        "missing_required_field_count",
        "stale_data_count",
        "data_conflict_count",
        "low_confidence_count",
        "failed_ticker_count",
        "coverage_status",
        "notes",
    ]
    coverage_df[coverage_cols].to_csv(output_dir / "data_coverage_report.csv", index=False)

    missing_df = build_missing_data_report(coverage_df, failed_df, dry_run["manual_review_queue"])
    missing_df.to_csv(output_dir / "missing_data_report.csv", index=False)

    manual_df = dry_run["manual_review_queue"]
    if manual_df.empty:
        manual_df = pd.DataFrame(columns=["ticker", "module", "issue", "severity", "status", "evidence", "confidence", "notes"])
    manual_df.to_csv(output_dir / "manual_review_queue.csv", index=False)

    errors_df = dry_run["errors"]
    if errors_df.empty:
        errors_df = pd.DataFrame(columns=["stage", "dataset_name", "ticker", "error_code", "message", "notes"])
    errors_df.to_csv(output_dir / "pipeline_errors.csv", index=False)

    run_summary = render_run_summary(
        run_id=run_id,
        started_at=started_at,
        finished_at=utc_now(),
        mode=mode,
        run_status=run_status,
        dry_run_status=dry_status,
        tickers=fetch_status["tickers"],
        requested_limit=requested_limit,
        raw_datasets=raw_datasets,
        dataset_status=fetch_status["dataset_status"],
        stages=dry_run["module_status_records"],
        errors=fetch_status["errors"] + dry_run["errors"].get("message", pd.Series(dtype=str)).astype(str).tolist(),
        step19_implemented=False,
        next_action=(
            "REAL-DATA-02 - scale to 100-200 real tickers"
            if run_status in {STATUS_REAL_INGESTED, STATUS_MANUAL_IMPORTED}
            else "fix real/manual data source availability first"
        ),
        ticker_selection=ticker_selection,
        template_paths=template_paths,
    )
    (output_dir / "run_summary.md").write_text(run_summary, encoding="utf-8")
    return {
        "run_status": run_status,
        "dry_run_status": dry_status,
        "output_dir": str(output_dir),
        "row_counts": {dataset: int(len(df)) for dataset, df in raw_datasets.items()},
    }


def build_ticker_level_status(
    *,
    tickers: list[str],
    fetch_status: dict[str, Any],
    dry_run: dict[str, Any],
) -> pd.DataFrame:
    rows = []
    failed_by_ticker_dataset = {
        (row["ticker"], row["dataset_name"]): row for row in fetch_status["failed_tickers"]
    }
    sector_status = sector_cycle_status_by_micro_sector(dry_run["sector_cycle"])
    for ticker in tickers:
        universe_row = first_ticker_row(dry_run["universe"], ticker)
        l0_row = first_ticker_row(dry_run["l0_trash"], ticker)
        basic_row = first_ticker_row(dry_run["l0_basic"], ticker)
        class_row = first_ticker_row(dry_run["classification"], ticker)
        template_row = first_ticker_row(dry_run["archetype_templates"], ticker)
        driver_row = first_ticker_row(dry_run["driver_registry"], ticker)
        indicator_row = first_ticker_row(dry_run["indicator_registry"], ticker)
        rows.append(
            {
                "ticker": ticker,
                "universe_status": value_from(universe_row, "universe_status")
                or fetch_status["dataset_status"].get("universe", ""),
                "profile_status": ticker_dataset_status(ticker, "company_profile", fetch_status, failed_by_ticker_dataset),
                "market_price_status": ticker_dataset_status(ticker, "market_price", fetch_status, failed_by_ticker_dataset),
                "financial_statement_status": ticker_dataset_status(ticker, "financial_statement_summary", fetch_status, failed_by_ticker_dataset),
                "disclosure_status": ticker_dataset_status(ticker, "disclosure_status", fetch_status, failed_by_ticker_dataset),
                "clean_data_status": "AVAILABLE" if not universe_row.empty else "MISSING_DATA",
                "data_quality_status": value_from(universe_row, "data_sanity_status"),
                "l0_trash_status": value_from(l0_row, "l0_status"),
                "l0_basic_status": value_from(basic_row, "l0_basic_status"),
                "classification_status": value_from(class_row, "classification_status"),
                "archetype_status": value_from(template_row, "archetype_template_status"),
                "driver_status": value_from(driver_row, "driver_resolution_status"),
                "indicator_status": value_from(indicator_row, "indicator_resolution_status"),
                "sector_cycle_status": sector_status.get(value_from(class_row, "primary_micro_sector"), ""),
                "manual_review_required": any(
                    truthy(value_from(row, "manual_review_required"))
                    for row in [universe_row, l0_row, basic_row, class_row, template_row, driver_row, indicator_row]
                ),
                "warning_flags": ";".join(
                    dedupe(
                        value_list(value_from(universe_row, "universe_warnings"))
                        + value_list(value_from(l0_row, "l0_warning_flags"))
                        + value_list(value_from(basic_row, "warning_flags"))
                        + value_list(value_from(class_row, "warning_flags"))
                        + value_list(value_from(driver_row, "warning_flags"))
                        + value_list(value_from(indicator_row, "warning_flags"))
                    )
                ),
                "notes": "real/manual dry run through Step 18; no Step 19",
            }
        )
    return pd.DataFrame(rows, columns=TICKER_STATUS_COLUMNS)


def build_missing_data_report(
    coverage_df: pd.DataFrame, failed_df: pd.DataFrame, manual_df: pd.DataFrame
) -> pd.DataFrame:
    rows = []
    for _, row in coverage_df.iterrows():
        if row.get("coverage_status") != "VALID_DATA" or int(row.get("failed_ticker_count", 0)):
            rows.append(
                {
                    "dataset_name": row.get("dataset_name", ""),
                    "ticker": "",
                    "issue": row.get("coverage_status", ""),
                    "notes": row.get("notes", ""),
                }
            )
    for _, row in failed_df.iterrows():
        rows.append(
            {
                "dataset_name": row.get("dataset_name", ""),
                "ticker": row.get("ticker", ""),
                "issue": row.get("status", ""),
                "notes": row.get("reason", ""),
            }
        )
    if not manual_df.empty:
        for _, row in manual_df.iterrows():
            rows.append(
                {
                    "dataset_name": row.get("module", ""),
                    "ticker": row.get("ticker", ""),
                    "issue": row.get("issue", ""),
                    "notes": row.get("notes", ""),
                }
            )
    return pd.DataFrame(rows)


def render_run_summary(
    *,
    run_id: str,
    started_at: str,
    finished_at: str,
    mode: str,
    run_status: str,
    dry_run_status: str,
    tickers: list[str],
    requested_limit: int,
    raw_datasets: dict[str, pd.DataFrame],
    dataset_status: dict[str, str],
    stages: list[dict[str, Any]],
    errors: list[str],
    step19_implemented: bool,
    next_action: str,
    ticker_selection: str,
    template_paths: dict[str, str],
) -> str:
    row_counts = {dataset: int(len(df)) for dataset, df in raw_datasets.items()}
    succeeded = [dataset for dataset, status in dataset_status.items() if status in {STATUS_REAL_INGESTED, STATUS_MANUAL_IMPORTED}]
    failed = [dataset for dataset, status in dataset_status.items() if status not in {STATUS_REAL_INGESTED, STATUS_MANUAL_IMPORTED}]
    lines = [
        "# REAL-DATA-01 Run Summary",
        "",
        f"- run_id: {run_id}",
        f"- run_type: {RUN_TYPE}",
        f"- mode: {mode}",
        f"- ticker_selection: {ticker_selection}",
        f"- data_type: {'real source data' if mode == 'real' else 'manual imported data'}",
        f"- run_status: {run_status}",
        f"- dry_run_status: {dry_run_status}",
        f"- started_at: {started_at}",
        f"- finished_at: {finished_at}",
        f"- tickers_requested: {requested_limit}",
        f"- tickers_ingested: {len(tickers)}",
        f"- ticker_list: {', '.join(tickers)}",
        f"- datasets_attempted: {', '.join(DATASETS)}",
        f"- datasets_succeeded: {', '.join(succeeded)}",
        f"- datasets_failed_or_partial: {', '.join(failed)}",
        f"- row_counts_by_dataset: {json.dumps(row_counts, ensure_ascii=False, sort_keys=True)}",
        f"- dataset_status: {json.dumps(dataset_status, ensure_ascii=False, sort_keys=True)}",
        f"- output_contains_mock_sample: False",
        f"- step19_implemented: {step19_implemented}",
        f"- manual_template_paths: {json.dumps(template_paths, ensure_ascii=False, sort_keys=True)}",
        f"- next_recommended_action: {next_action}",
        "",
        "## Pipeline Stages Through Step 18",
    ]
    for stage in stages:
        lines.append(
            f"- {stage.get('stage')}: {stage.get('status')} "
            f"(input={stage.get('input_count')}, output={stage.get('output_count')})"
        )
    lines.extend(["", "## Errors"])
    if errors:
        lines.extend(f"- {error}" for error in errors if error)
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def save_raw_files(raw_datasets: dict[str, pd.DataFrame], output_dir: Path) -> None:
    for dataset_name, df in raw_datasets.items():
        ensure_columns(df, RAW_COLUMNS[dataset_name]).to_csv(
            output_dir / RAW_FILENAMES[dataset_name], index=False
        )


def save_manifests(
    *,
    raw_datasets: dict[str, pd.DataFrame],
    fetch_status: dict[str, Any],
    output_dir: Path,
    run_id: str,
    mode: str,
    started_at: str,
) -> None:
    for dataset_name, df in raw_datasets.items():
        dataset_failed = [
            row for row in fetch_status["failed_tickers"] if row["dataset_name"] == dataset_name
        ]
        record = create_ingestion_manifest_record(
            run_id=run_id,
            dataset_name=dataset_name,
            mode=mode,
            output_path=str(Path("data/raw") / RAW_FILENAMES[dataset_name]),
            started_at=started_at,
            finished_at=utc_now(),
            row_count=int(len(df)),
            ticker_count=ticker_count(df),
            success_count=int(len(df)),
            failed_count=len(dataset_failed),
            warnings=[row["reason"] for row in dataset_failed],
            errors=fetch_status["errors"] if dataset_name == "universe" else [],
            data_quality_status=fetch_status["dataset_status"].get(dataset_name, ""),
            notes=f"{RUN_TYPE} ingestion manifest",
        )
        save_ingestion_manifest(record, output_dir=output_dir)


def new_fetch_status(mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "overall_status": "",
        "tickers": [],
        "dataset_status": {dataset: "" for dataset in DATASETS},
        "failed_tickers": [],
        "warnings": [],
        "errors": [],
        "source_request_summary": empty_source_request_summary(),
        "source_adapter_status": empty_source_adapter_status(),
    }


def empty_raw_datasets() -> dict[str, pd.DataFrame]:
    return {
        dataset: pd.DataFrame(columns=RAW_COLUMNS[dataset])
        for dataset in DATASETS
    }


def ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    output = df.copy()
    for column in columns:
        if column not in output.columns:
            output[column] = pd.NA
    return output[columns].copy()


def latest_financial_period(dfs: Any) -> str:
    candidates: list[str] = []
    for df in dfs:
        if isinstance(df, pd.DataFrame):
            candidates.extend(
                str(column)
                for column in df.columns
                if isinstance(column, str) and "-Q" in column
            )
    return candidates[0] if candidates else ""


def lookup_financial_value(
    statements: dict[str, pd.DataFrame], aliases: list[str], period: str
) -> Any:
    for df in statements.values():
        if not isinstance(df, pd.DataFrame) or df.empty or "item_id" not in df.columns or period not in df.columns:
            continue
        for alias in aliases:
            matches = df[df["item_id"].astype(str) == alias]
            if not matches.empty:
                value = matches.iloc[0][period]
                if not is_missing(value):
                    return value
    return pd.NA


def ticker_dataset_status(
    ticker: str,
    dataset_name: str,
    fetch_status: dict[str, Any],
    failed_by_ticker_dataset: dict[tuple[str, str], dict[str, str]],
) -> str:
    failed = failed_by_ticker_dataset.get((ticker, dataset_name))
    if failed:
        return failed["status"]
    return fetch_status["dataset_status"].get(dataset_name, "")


def sector_cycle_status_by_micro_sector(df: pd.DataFrame) -> dict[str, str]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return {}
    return {
        str(row.get("micro_sector", "")): str(row.get("cycle_status", ""))
        for _, row in df.iterrows()
    }


def first_ticker_row(df: pd.DataFrame, ticker: str) -> pd.Series:
    if not isinstance(df, pd.DataFrame) or df.empty or "ticker" not in df.columns:
        return pd.Series(dtype=object)
    matches = df[df["ticker"].map(clean_ticker) == ticker]
    if matches.empty:
        return pd.Series(dtype=object)
    return matches.iloc[0]


def value_from(row: pd.Series, column: str) -> Any:
    if not isinstance(row, pd.Series) or column not in row.index:
        return ""
    return row[column]


def serialize_json_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    output = df.copy()
    for column in columns:
        if column in output.columns:
            output[column] = output[column].map(
                lambda value: json.dumps(value, ensure_ascii=False)
                if isinstance(value, (list, dict))
                else value
            )
    return output


def has_insufficient_step18(dry_run: dict[str, Any]) -> bool:
    sector_df = dry_run.get("sector_cycle", pd.DataFrame())
    if isinstance(sector_df, pd.DataFrame) and "cycle_status" in sector_df.columns:
        return bool((sector_df["cycle_status"] == "INSUFFICIENT_DATA_FOR_SECTOR_CYCLE").any())
    return True


def no_prohibited_columns(df: pd.DataFrame) -> bool:
    normalized = {str(column).strip().lower() for column in df.columns}
    return PROHIBITED_RECOMMENDATION_FIELDS.isdisjoint(normalized)


def failed_row(ticker: str, dataset_name: str, status: str, reason: str) -> dict[str, str]:
    return {
        "ticker": clean_ticker(ticker),
        "dataset_name": dataset_name,
        "status": status,
        "reason": str(reason),
        "notes": "recorded by REAL-DATA-01; no fabricated data",
    }


def first_present(row: pd.Series, columns: list[str]) -> Any:
    for column in columns:
        if column in row.index and not is_missing(row[column]):
            return row[column]
    return ""


def first_present_mapping(mapping: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in mapping and not is_missing(mapping[key]):
            return mapping[key]
    return ""


def ticker_count(df: pd.DataFrame) -> int:
    if "ticker" not in df.columns:
        return 0
    return len({clean_ticker(value) for value in df["ticker"] if clean_ticker(value)})


def date_text(value: Any) -> str:
    if is_missing(value):
        return ""
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return str(value).strip()
    return timestamp.strftime("%Y-%m-%d")


def to_number(value: Any) -> float | None:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return None
    return float(numeric)


def clean_ticker(value: Any) -> str:
    if is_missing(value):
        return ""
    return str(value).strip().upper()


def clean_text(value: Any) -> str:
    if is_missing(value):
        return ""
    return str(value).strip()


def value_list(value: Any) -> list[str]:
    if is_missing(value):
        return []
    if isinstance(value, list):
        return [str(item) for item in value if not is_missing(item)]
    if isinstance(value, tuple) or isinstance(value, set):
        return [str(item) for item in value if not is_missing(item)]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped == "[]":
            return []
        return [part.strip() for part in stripped.replace("|", ";").split(";") if part.strip()]
    return [str(value)]


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if is_missing(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def is_missing(value: Any) -> bool:
    if isinstance(value, list) or isinstance(value, tuple) or isinstance(value, set):
        return len(value) == 0
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        return False
    return isinstance(value, str) and not value.strip()


def dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(values))


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def safe_token(value: Any) -> str:
    return "".join(
        character if character.isalnum() else "_"
        for character in str(value)
    ).strip("_")


if __name__ == "__main__":
    raise SystemExit(main())
