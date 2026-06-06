from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ingestion.official_finance_document_downloader import download_seed_documents  # noqa: E402
from src.ingestion.official_finance_document_index import (  # noqa: E402
    build_01ib_decision_report_markdown,
    build_01ib_run_summary_markdown,
    build_document_seed_status_by_ticker,
)
from src.ingestion.official_finance_document_seed import (  # noqa: E402
    load_document_seed_csv,
    load_document_seed_schema,
    validate_document_seed_rows,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="REAL-DATA-01I-B official finance document seed infrastructure.")
    parser.add_argument("--seed-file", default="data/seeds/official_finance_document_seed.example.csv")
    parser.add_argument("--output-dir", default="data/reports/official_finance_documents_01ib")
    parser.add_argument("--raw-output-dir", default="data/raw/official_finance_documents/01ib")
    parser.add_argument("--request-sleep-seconds", type=float, default=2.0)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--max-documents", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=int, default=25)
    parser.add_argument("--allowed-domains-file", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--schema-file", default="config/official_finance_document_schema.yaml")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_output_dir = Path(args.raw_output_dir)
    if not args.dry_run:
        raw_output_dir.mkdir(parents=True, exist_ok=True)

    seed_df = load_document_seed_csv(args.seed_file)
    validation_result = validate_document_seed_rows(
        seed_df,
        schema=load_document_seed_schema(args.schema_file),
    )
    validation = validation_result["validation"]
    valid_seed_rows = validation_result["valid_seed_rows"]
    invalid_seed_rows = validation_result["invalid_seed_rows"]
    duplicate_seed_rows = validation_result["duplicate_seed_rows"]

    validation.to_csv(output_dir / "seed_validation_report.csv", index=False)
    invalid_seed_rows.to_csv(output_dir / "invalid_seed_rows.csv", index=False)
    duplicate_seed_rows.to_csv(output_dir / "duplicate_seed_rows.csv", index=False)

    if valid_seed_rows.empty and not args.allow_partial:
        raise SystemExit("No valid seed rows. Pass --allow-partial to write validation reports only.")

    download_result = download_seed_documents(
        valid_seed_rows,
        raw_output_dir=raw_output_dir,
        request_sleep_seconds=args.request_sleep_seconds,
        timeout_seconds=args.timeout_seconds,
        max_documents=args.max_documents or None,
        allowed_domains=load_allowed_domains(args.allowed_domains_file),
        dry_run=args.dry_run,
    )
    document_index = download_result["finance_document_index"]
    manual_review_queue = download_result["manual_review_queue"]
    status_by_ticker = build_document_seed_status_by_ticker(document_index)
    document_index.to_csv(output_dir / "finance_document_index.csv", index=False)
    manual_review_queue.to_csv(output_dir / "manual_review_queue.csv", index=False)
    status_by_ticker.to_csv(output_dir / "document_seed_status_by_ticker.csv", index=False)

    command = " ".join([Path(sys.executable).name, *sys.argv])
    run_label = "01ic" if "01ic" in str(output_dir).lower() else "01ib"
    (output_dir / f"official_finance_document_{run_label}_run_summary.md").write_text(
        build_01ib_run_summary_markdown(
            command=command,
            seed_rows_loaded=len(seed_df),
            validation=validation,
            document_index=document_index,
            manual_review_queue=manual_review_queue,
            dry_run=args.dry_run,
            run_label=run_label,
        ),
        encoding="utf-8",
    )
    (output_dir / "datasource_decision_report.md").write_text(
        build_01ib_decision_report_markdown(
            validation=validation,
            document_index=document_index,
        ),
        encoding="utf-8",
    )

    print(
        {
            "output_dir": str(output_dir),
            "raw_output_dir": str(raw_output_dir),
            "seed_rows_loaded": int(len(seed_df)),
            "valid_seed_rows": int(len(valid_seed_rows)),
            "invalid_seed_rows": int(len(invalid_seed_rows)),
            "documents_attempted": 0 if args.dry_run else int(len(document_index)),
            "manual_review_rows": int(len(manual_review_queue)),
            "dry_run": bool(args.dry_run),
            "finance_parse_ready": False,
            "step19_implemented": False,
        }
    )
    return 0


def load_allowed_domains(path_value: str) -> set[str] | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.exists():
        raise FileNotFoundError(f"Allowed domains file not found: {path}")
    domains = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip().lower()
        if value and not value.startswith("#"):
            domains.add(value.removeprefix("www."))
    return domains


if __name__ == "__main__":
    raise SystemExit(main())
