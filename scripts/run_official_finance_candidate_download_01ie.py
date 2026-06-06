from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ingestion.official_finance_candidate_downloader import run_official_finance_candidate_download_01ie  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="REAL-DATA-01I-E official finance candidate download.")
    parser.add_argument("--refined-seed-file", default="data/reports/official_finance_documents_01id_patch1/refined_seed_candidates_01id_patch1.csv")
    parser.add_argument("--candidate-file", default="data/reports/official_finance_documents_01id_patch1/official_document_link_candidates.csv")
    parser.add_argument("--output-dir", default="data/reports/official_finance_documents_01ie")
    parser.add_argument("--raw-output-dir", default="data/raw/official_finance_documents/01ie")
    parser.add_argument("--request-sleep-seconds", type=float, default=2.5)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--max-documents", type=int, default=60)
    parser.add_argument("--max-depth1-documents-per-page", type=int, default=3)
    parser.add_argument("--tickers", default="")
    parser.add_argument("--prefer-direct-documents", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--skip-html-depth1", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command = " ".join([Path(sys.executable).name, *sys.argv])
    result = run_official_finance_candidate_download_01ie(
        refined_seed_file=args.refined_seed_file,
        candidate_file=args.candidate_file,
        output_dir=args.output_dir,
        raw_output_dir=args.raw_output_dir,
        request_sleep_seconds=args.request_sleep_seconds,
        timeout_seconds=args.timeout_seconds,
        max_documents=args.max_documents or None,
        max_depth1_documents_per_page=args.max_depth1_documents_per_page,
        tickers=parse_tickers(args.tickers),
        prefer_direct_documents=args.prefer_direct_documents,
        skip_html_depth1=args.skip_html_depth1,
        dry_run=args.dry_run,
        allow_partial=args.allow_partial,
        command=command,
    )
    index = result["finance_document_index"]
    depth1 = result["depth1_document_candidates"]
    manual = result["manual_review_queue"]
    print(
        {
            "output_dir": args.output_dir,
            "raw_output_dir": args.raw_output_dir,
            "refined_seed_rows_loaded": int(len(result["prepared_refined_candidates"])),
            "selected_refined_rows": int(len(result["selected_refined_candidates"])),
            "documents_attempted": int(len(index)),
            "pdf_downloaded": int((index["detected_file_type"].eq("pdf") & index["download_status"].isin(["DOWNLOADED", "DEPTH1_DOCUMENT_DOWNLOADED"])).sum()) if not index.empty else 0,
            "xlsx_xls_downloaded": int((index["detected_file_type"].isin(["xlsx", "xls"]) & index["download_status"].isin(["DOWNLOADED", "DEPTH1_DOCUMENT_DOWNLOADED"])).sum()) if not index.empty else 0,
            "html_snapshots_saved": int(index["download_status"].eq("HTML_SNAPSHOT_SAVED").sum()) if not index.empty else 0,
            "depth1_candidates_found": int(len(depth1)),
            "manual_review_rows": int(len(manual)),
            "dry_run": bool(args.dry_run),
            "finance_parse_ready": False,
            "step19_implemented": False,
        }
    )
    return 0


def parse_tickers(value: str) -> list[str] | None:
    tickers = [item.strip().upper() for item in str(value or "").split(",") if item.strip()]
    return tickers or None


if __name__ == "__main__":
    raise SystemExit(main())
