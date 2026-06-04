"""REAL-DATA-01: ingest first real/manual tickers and dry-run to Step 18."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

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
        )

    if args.mode == "real":
        raw_datasets, fetch_status = fetch_real_vnstock_data(
            limit=args.limit,
            started_at=started_at,
            start_date=args.start_date,
            end_date=args.end_date,
            request_pause_seconds=args.request_pause_seconds,
            real_source_max_requests=args.real_source_max_requests,
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
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    status = new_fetch_status("real")
    request_budget = {"remaining": int(real_source_max_requests)}
    try:
        from vnstock import Company, Finance, Listing, Quote
    except BaseException as exc:  # noqa: BLE001
        if isinstance(exc, KeyboardInterrupt):
            raise
        status["overall_status"] = STATUS_REAL_UNAVAILABLE
        status["errors"].append(f"vnstock import failed: {external_error_text(exc)}")
        return empty_raw_datasets(), status

    listing_df, listing_error = call_real_source(
        lambda: Listing(source="kbs").symbols_by_exchange(),
        request_pause_seconds,
        request_budget,
    )
    if listing_error:
        status["overall_status"] = STATUS_REAL_UNAVAILABLE
        status["errors"].append(f"vnstock Listing(source='kbs') failed: {listing_error}")
        return empty_raw_datasets(), status

    universe_source = normalize_listing_universe(listing_df, limit, started_at)
    if universe_source.empty:
        status["overall_status"] = STATUS_REAL_DATA_NOT_AVAILABLE
        status["errors"].append("real universe source returned no valid stock tickers")
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
        request_budget=request_budget,
    )
    profile_rows, profile_failed = fetch_company_profiles(
        Company=Company,
        universe_df=universe_source,
        started_at=started_at,
        request_pause_seconds=request_pause_seconds,
        request_budget=request_budget,
    )
    financial_rows, financial_failed = fetch_financial_summaries(
        Finance=Finance,
        tickers=tickers,
        started_at=started_at,
        request_pause_seconds=request_pause_seconds,
        request_budget=request_budget,
    )
    disclosure_rows, disclosure_failed = fetch_disclosures(
        Company=Company,
        tickers=tickers,
        started_at=started_at,
        request_pause_seconds=request_pause_seconds,
        request_budget=request_budget,
    )
    if request_budget["remaining"] <= 0:
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
    return raw_datasets, status


def normalize_listing_universe(df: pd.DataFrame, limit: int, fetch_time: str) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame(columns=RAW_COLUMNS["universe"])
    source = df.copy()
    source["symbol"] = source["symbol"].map(clean_ticker)
    if "exchange" not in source.columns:
        source["exchange"] = ""
    if "type" in source.columns:
        source = source[source["type"].astype(str).str.lower() == "stock"]
    source = source[source["exchange"].isin(["HOSE", "HNX", "UPCOM"])]
    source = source[source["symbol"].map(bool)].drop_duplicates("symbol").head(limit)
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


def fetch_company_profiles(
    *,
    Company: Any,
    universe_df: pd.DataFrame,
    started_at: str,
    request_pause_seconds: float,
    request_budget: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for _, universe_row in universe_df.iterrows():
        ticker = universe_row["ticker"]
        detail = {}
        notes = ["company profile initialized from real universe source"]
        overview, overview_error = call_real_source(
            lambda: Company(source="KBS", symbol=ticker).overview(),
            request_pause_seconds,
            request_budget,
        )
        if isinstance(overview, pd.DataFrame) and not overview.empty:
            detail.update(overview.iloc[0].to_dict())
        elif overview_error:
            notes.append(f"KBS overview unavailable: {overview_error}")

        overview_vci, overview_vci_error = call_real_source(
            lambda: Company(source="VCI", symbol=ticker).overview(),
            request_pause_seconds,
            request_budget,
        )
        if isinstance(overview_vci, pd.DataFrame) and not overview_vci.empty:
            detail.update({f"vci_{k}": v for k, v in overview_vci.iloc[0].to_dict().items()})
        elif overview_vci_error:
            notes.append(f"VCI overview unavailable: {overview_vci_error}")

        business_description = clean_text(detail.get("business_model"))
        industry_raw = clean_text(
            detail.get("vci_industry_name")
            or detail.get("vci_icb_name")
            or detail.get("vci_sector")
            or detail.get("vci_tag")
            or detail.get("company_type")
        )
        if not business_description or not industry_raw:
            failed.append(
                failed_row(
                    ticker,
                    "company_profile",
                    "PARTIAL_PROFILE_DATA",
                    "industry_raw or business_description unavailable from real source",
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
                "notes": "; ".join(notes),
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
    request_budget: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    end = end_date or started_at[:10]
    start = start_date or (pd.Timestamp(end) - pd.Timedelta(days=45)).strftime("%Y-%m-%d")
    for ticker in tickers:
        history, history_error = call_real_source(
            lambda ticker=ticker: Quote(source="VCI", symbol=ticker).history(
                start=start, end=end, interval="1D"
            ),
            request_pause_seconds,
            request_budget,
        )
        if history_error:
            failed.append(failed_row(ticker, "market_price", "REAL_MARKET_PRICE_UNAVAILABLE", history_error))
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
    request_budget: dict[str, int],
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
            df, finance_error = call_real_source(
                lambda ticker=ticker, method_name=method_name: getattr(
                    Finance(source="VCI", symbol=ticker, period="quarter", get_all=False),
                    method_name,
                )(),
                request_pause_seconds,
                request_budget,
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
                    "REAL_FINANCIAL_STATEMENT_UNAVAILABLE",
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
    request_budget: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for ticker in tickers:
        events, events_error = call_real_source(
            lambda ticker=ticker: Company(source="KBS", symbol=ticker).events(),
            request_pause_seconds,
            request_budget,
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


def call_real_source(
    action: Any,
    pause_seconds: float,
    request_budget: dict[str, int],
) -> tuple[Any, str]:
    if request_budget["remaining"] <= 0:
        return None, "REAL_SOURCE_REQUEST_BUDGET_EXHAUSTED"
    request_budget["remaining"] -= 1
    try:
        return action(), ""
    except BaseException as exc:  # noqa: BLE001 - third-party API may call sys.exit.
        if isinstance(exc, KeyboardInterrupt):
            raise
        return None, external_error_text(exc)
    finally:
        pause_real_source(pause_seconds)


def pause_real_source(seconds: float) -> None:
    if seconds and seconds > 0:
        time.sleep(float(seconds))


def external_error_text(exc: BaseException) -> str:
    message = str(exc).strip()
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def new_fetch_status(mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "overall_status": "",
        "tickers": [],
        "dataset_status": {dataset: "" for dataset in DATASETS},
        "failed_tickers": [],
        "warnings": [],
        "errors": [],
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
