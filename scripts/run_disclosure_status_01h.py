from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ingestion.disclosure_status_list_ingestion import (  # noqa: E402
    build_01h_decision_report_markdown,
    build_comparison_vs_01g,
    build_custom_01h_decision,
    build_disclosure_01h_summary_markdown,
    load_disclosure_status_sources,
    run_disclosure_status_01h,
)
from src.ingestion.multi_source_evidence import (  # noqa: E402
    load_multi_source_registry,
    load_source_priority_config,
    run_multi_source_evidence,
    save_multi_source_evidence_reports,
)


REPRESENTATIVE_20 = [
    "VCB",
    "BID",
    "CTG",
    "MBB",
    "ACB",
    "HPG",
    "HSG",
    "VHM",
    "KDH",
    "NLG",
    "SSI",
    "VND",
    "GAS",
    "PVS",
    "FPT",
    "MWG",
    "VGC",
    "GMD",
    "VHC",
    "TCM",
]

RAW_CONTEXT_FILENAMES = {
    "universe": "universe_raw.csv",
    "company_profile": "company_profile_raw.csv",
    "market_price": "market_price_raw.csv",
    "financial_statement_summary": "financial_statement_summary_raw.csv",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="REAL-DATA-01H official disclosure status-list ingestion."
    )
    parser.add_argument("--representative-tickers", default=",".join(REPRESENTATIVE_20))
    parser.add_argument("--sources", default="hose,hnx,ssc,cafef,vietstock,vnstock")
    parser.add_argument("--output-dir", default="data/reports/disclosure_status_01h")
    parser.add_argument("--raw-snapshot-dir", default="data/raw/source_snapshots/01h")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--request-sleep-seconds", type=float, default=0)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--source-config", default="config/disclosure_status_sources.yaml")
    parser.add_argument("--source-registry", default="config/multi_source_registry.yaml")
    parser.add_argument("--source-priority", default="config/source_priority.yaml")
    parser.add_argument("--previous-01g-dir", default="data/reports/multi_source_probe_01g")
    parser.add_argument("--year", type=int, default=0)
    parser.add_argument("--page-size", type=int, default=500)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    representative_tickers = parse_csv_arg(args.representative_tickers) or REPRESENTATIVE_20
    sources = parse_csv_arg(args.sources)

    ingestion_reports = run_disclosure_status_01h(
        representative_tickers=representative_tickers,
        sources=sources,
        output_dir=output_dir,
        raw_snapshot_dir=args.raw_snapshot_dir,
        source_config=load_disclosure_status_sources(args.source_config),
        request_sleep_seconds=args.request_sleep_seconds,
        year=args.year or None,
        page_size=args.page_size,
        allow_partial=args.allow_partial,
    )

    raw_context = load_raw_context(Path(args.raw_dir))
    raw_context["disclosure_status"] = ingestion_reports["disclosure_candidate_rows"]

    evidence_result = run_multi_source_evidence(
        raw_datasets=raw_context,
        requested_tickers=representative_tickers,
        source_registry=load_multi_source_registry(args.source_registry),
        priority_config=load_source_priority_config(args.source_priority),
        run_id="disclosure_status_01h",
    )
    evidence_result["field_level_evidence"] = enrich_disclosure_evidence_status(
        field_level_evidence=evidence_result["field_level_evidence"],
        disclosure_raw=ingestion_reports["disclosure_candidate_rows"],
    )
    save_multi_source_evidence_reports(result=evidence_result, output_dir=output_dir)

    custom_decision = build_custom_01h_decision(
        representative_tickers=representative_tickers,
        status_by_ticker=ingestion_reports["disclosure_status_by_ticker"],
        positive_control=ingestion_reports["disclosure_positive_control_tickers"],
        positive_control_status_value=ingestion_reports["positive_control_status"],
        evidence_decisions=evidence_result["decisions"],
        unresolved_required_fields=evidence_result["unresolved_required_fields"],
    )

    command = " ".join([Path(sys.executable).name, *sys.argv])
    (output_dir / "disclosure_01h_run_summary.md").write_text(
        build_disclosure_01h_summary_markdown(
            command=command,
            reports=ingestion_reports,
            evidence_decisions=evidence_result["decisions"],
            custom_decision=custom_decision,
        ),
        encoding="utf-8",
    )
    (output_dir / "datasource_decision_report.md").write_text(
        build_01h_decision_report_markdown(custom_decision),
        encoding="utf-8",
    )
    (output_dir / "comparison_vs_01g.md").write_text(
        build_comparison_vs_01g(
            previous_dir=args.previous_01g_dir,
            current_dir=output_dir,
            status_by_ticker=ingestion_reports["disclosure_status_by_ticker"],
            positive_control=ingestion_reports["disclosure_positive_control_tickers"],
            probe_matrix=ingestion_reports["disclosure_source_probe_matrix"],
            unresolved_required_fields=evidence_result["unresolved_required_fields"],
            custom_decision=custom_decision,
        ),
        encoding="utf-8",
    )

    print(
        {
            "output_dir": str(output_dir),
            "positive_control_tickers": int(
                len(ingestion_reports["disclosure_positive_control_tickers"])
            ),
            "disclosure_status_rows": int(len(ingestion_reports["disclosure_status_by_ticker"])),
            "disclosure_candidate_rows": int(len(ingestion_reports["disclosure_candidate_rows"])),
            "unresolved_required_fields": int(len(evidence_result["unresolved_required_fields"])),
            "disclosure_ready_for_l0": custom_decision["disclosure_ready_for_l0"],
            "finance_disclosure_ready_for_step18": custom_decision[
                "finance_disclosure_ready_for_step18"
            ],
            "step19_implemented": False,
        }
    )
    return 0


def enrich_disclosure_evidence_status(
    *,
    field_level_evidence: pd.DataFrame,
    disclosure_raw: pd.DataFrame,
) -> pd.DataFrame:
    if not isinstance(field_level_evidence, pd.DataFrame) or field_level_evidence.empty:
        return field_level_evidence
    if not isinstance(disclosure_raw, pd.DataFrame) or disclosure_raw.empty:
        return field_level_evidence
    output = field_level_evidence.copy()
    mapping = {}
    for _, row in disclosure_raw.iterrows():
        record_key = (
            f"ticker={clean_text(row.get('ticker')).upper()}"
            f"|event_date={clean_text(row.get('event_date'))}"
            f"|event_type={clean_text(row.get('event_type'))}"
        )
        source_name = clean_text(row.get("source_name")) or clean_text(row.get("source"))
        source_url = clean_text(row.get("source_url"))
        evidence_status = clean_text(row.get("evidence_status"))
        if evidence_status:
            mapping[(record_key, source_name, source_url)] = evidence_status

    statuses = []
    for _, row in output.iterrows():
        if row.get("dataset_name") != "disclosure_status":
            statuses.append(row.get("evidence_status", "EVIDENCE_AVAILABLE"))
            continue
        key = (
            clean_text(row.get("record_key")),
            clean_text(row.get("source_name")),
            clean_text(row.get("source_url")),
        )
        statuses.append(mapping.get(key, row.get("evidence_status", "EVIDENCE_AVAILABLE")))
    output["evidence_status"] = statuses
    return output


def load_raw_context(raw_dir: Path) -> dict[str, pd.DataFrame | None]:
    datasets: dict[str, pd.DataFrame | None] = {}
    for dataset_name, filename in RAW_CONTEXT_FILENAMES.items():
        path = raw_dir / filename
        datasets[dataset_name] = pd.read_csv(path, keep_default_na=False) if path.exists() else None
    return datasets


def parse_csv_arg(value: str) -> list[str]:
    result = []
    for part in (value or "").split(","):
        item = part.strip()
        if item and item not in result:
            result.append(item)
    return result


def clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


if __name__ == "__main__":
    raise SystemExit(main())
