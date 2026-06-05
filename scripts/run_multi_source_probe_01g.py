from __future__ import annotations

import argparse
import sys
from pathlib import Path

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
from src.ingestion.source_adapter_contracts import (  # noqa: E402
    empty_adapter_diagnostics,
    empty_disclosure_candidates,
    empty_finance_candidates,
    empty_probe_frame,
    empty_schema_diagnostics,
)
from src.ingestion.source_adapter_diagnostics import (  # noqa: E402
    build_comparison_vs_01f,
    build_disclosure_coverage_by_source,
    build_finance_field_coverage_by_source,
    disclosure_candidates_to_raw,
    finance_candidates_to_wide,
    instantiate_adapters,
    load_source_adapter_registry,
    source_probe_summary_markdown,
    validate_source_adapter_registry,
)
from src.ingestion.source_probe import load_source_probe_targets, safe_http_get  # noqa: E402


RAW_CONTEXT_FILENAMES = {
    "universe": "universe_raw.csv",
    "company_profile": "company_profile_raw.csv",
    "market_price": "market_price_raw.csv",
}

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="REAL-DATA-01G automated multi-source finance/disclosure probe."
    )
    parser.add_argument("--tickers", default=",".join(REPRESENTATIVE_20))
    parser.add_argument(
        "--datasets",
        default="financial_statement_summary,disclosure_status",
    )
    parser.add_argument(
        "--sources",
        default="vnstock,cafef,vietstock,hose,hnx,ssc",
    )
    parser.add_argument("--output-dir", default="data/reports/multi_source_probe_01g")
    parser.add_argument("--raw-output-dir", default="data/raw")
    parser.add_argument("--request-sleep-seconds", type=float, default=0)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--probe-targets", default="config/source_probe_targets.yaml")
    parser.add_argument("--adapter-registry", default="config/source_adapter_registry.yaml")
    parser.add_argument("--source-registry", default="config/multi_source_registry.yaml")
    parser.add_argument("--source-priority", default="config/source_priority.yaml")
    parser.add_argument("--previous-01f-dir", default="data/reports/multi_source_evidence_01f")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tickers = parse_csv_arg(args.tickers) or REPRESENTATIVE_20
    datasets = parse_csv_arg(args.datasets)
    sources = parse_csv_arg(args.sources)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    probe_targets = load_source_probe_targets(args.probe_targets)
    adapter_registry = load_source_adapter_registry(args.adapter_registry)
    registry_validation = validate_source_adapter_registry(adapter_registry)
    if not registry_validation["is_valid"]:
        raise SystemExit("; ".join(registry_validation["errors"]))

    adapters = instantiate_adapters(
        adapter_registry=adapter_registry,
        probe_targets=probe_targets,
        source_names=sources,
        http_get=safe_http_get,
        request_sleep_seconds=args.request_sleep_seconds,
    )
    if not adapters and not args.allow_partial:
        raise SystemExit("No adapters selected.")

    probe_frames = []
    adapter_diag_frames = []
    schema_diag_frames = []
    finance_frames = []
    disclosure_frames = []

    for adapter in adapters:
        probe_df = adapter.probe(datasets=datasets)
        probe_frames.append(probe_df)

        if "financial_statement_summary" in datasets:
            if should_fetch(probe_df, "financial_statement_summary"):
                finance_df, diag_df, schema_df = adapter.fetch_finance(tickers)
            else:
                finance_df, diag_df, schema_df = skipped_fetch_frames(
                    adapter,
                    dataset_name="financial_statement_summary",
                    action="fetch_finance",
                    notes="fetch skipped because probe did not show safe accessibility",
                )
            finance_frames.append(finance_df)
            adapter_diag_frames.append(diag_df)
            schema_diag_frames.append(schema_df)

        if "disclosure_status" in datasets:
            if should_fetch(probe_df, "disclosure_status"):
                disclosure_df, diag_df, schema_df = adapter.fetch_disclosure(tickers)
            else:
                disclosure_df, diag_df, schema_df = skipped_fetch_frames(
                    adapter,
                    dataset_name="disclosure_status",
                    action="fetch_disclosure",
                    notes="fetch skipped because probe did not show safe accessibility",
                )
            disclosure_frames.append(disclosure_df)
            adapter_diag_frames.append(diag_df)
            schema_diag_frames.append(schema_df)

    probe_matrix = concat_or_empty(probe_frames, empty_probe_frame())
    adapter_diagnostics = concat_or_empty(adapter_diag_frames, empty_adapter_diagnostics())
    schema_diagnostics = concat_or_empty(schema_diag_frames, empty_schema_diagnostics())
    finance_candidates = concat_or_empty(finance_frames, empty_finance_candidates())
    disclosure_candidates = concat_or_empty(disclosure_frames, empty_disclosure_candidates())

    finance_candidates.to_csv(output_dir / "finance_raw_candidate_rows.csv", index=False)
    disclosure_candidates.to_csv(output_dir / "disclosure_raw_candidate_rows.csv", index=False)
    probe_matrix.to_csv(output_dir / "source_probe_matrix.csv", index=False)
    adapter_diagnostics.to_csv(output_dir / "source_adapter_diagnostics.csv", index=False)
    schema_diagnostics.to_csv(output_dir / "source_schema_diagnostics.csv", index=False)

    finance_coverage = build_finance_field_coverage_by_source(finance_candidates)
    disclosure_coverage = build_disclosure_coverage_by_source(disclosure_candidates)
    finance_coverage.to_csv(output_dir / "finance_field_coverage_by_source.csv", index=False)
    disclosure_coverage.to_csv(output_dir / "disclosure_coverage_by_source.csv", index=False)

    raw_context = load_raw_context(Path(args.raw_output_dir))
    raw_context["financial_statement_summary"] = finance_candidates_to_wide(finance_candidates)
    raw_context["disclosure_status"] = disclosure_candidates_to_raw(disclosure_candidates)

    evidence_result = run_multi_source_evidence(
        raw_datasets=raw_context,
        requested_tickers=tickers,
        source_registry=load_multi_source_registry(args.source_registry),
        priority_config=load_source_priority_config(args.source_priority),
        run_id="multi_source_probe_01g",
    )
    save_multi_source_evidence_reports(result=evidence_result, output_dir=output_dir)

    comparison = build_comparison_vs_01f(
        previous_dir=args.previous_01f_dir,
        current_dir=output_dir,
        current_decisions=evidence_result["decisions"],
    )
    (output_dir / "comparison_vs_01f.md").write_text(comparison, encoding="utf-8")

    command = " ".join([Path(sys.executable).name, *sys.argv])
    (output_dir / "source_probe_summary.md").write_text(
        source_probe_summary_markdown(
            command=command,
            probe_matrix=probe_matrix,
            adapter_diagnostics=adapter_diagnostics,
            finance_candidates=finance_candidates,
            disclosure_candidates=disclosure_candidates,
            decisions=evidence_result["decisions"],
        ),
        encoding="utf-8",
    )

    print(
        {
            "output_dir": str(output_dir),
            "finance_candidate_rows": int(len(finance_candidates)),
            "disclosure_candidate_rows": int(len(disclosure_candidates)),
            "unresolved_required_fields": int(len(evidence_result["unresolved_required_fields"])),
            "step19_implemented": False,
        }
    )
    return 0


def should_fetch(probe_df: pd.DataFrame, dataset_name: str) -> bool:
    if not isinstance(probe_df, pd.DataFrame) or probe_df.empty:
        return False
    rows = probe_df[probe_df["dataset_name"].astype(str) == dataset_name]
    if rows.empty:
        return False
    statuses = set(rows["probe_status"].astype(str))
    return bool(statuses.intersection({"SOURCE_AVAILABLE", "SOURCE_SCHEMA_UNKNOWN"}))


def skipped_fetch_frames(adapter: object, *, dataset_name: str, action: str, notes: str):
    diagnostic = pd.DataFrame(
        [
            {
                "source_name": getattr(adapter, "source_name", ""),
                "source_category": getattr(adapter, "source_category", ""),
                "dataset_name": dataset_name,
                "ticker": "",
                "action": action,
                "status": "FETCH_SKIPPED",
                "row_count": 0,
                "http_status_or_error": "",
                "source_url": "",
                "notes": notes,
            }
        ]
    )
    schema = pd.DataFrame(
        [
            {
                "source_name": getattr(adapter, "source_name", ""),
                "source_category": getattr(adapter, "source_category", ""),
                "dataset_name": dataset_name,
                "ticker": "",
                "source_url": "",
                "schema_status": "FETCH_SKIPPED",
                "detected_fields": "",
                "unsupported_fields": "",
                "raw_labels": "",
                "notes": notes,
            }
        ]
    )
    candidate = (
        empty_finance_candidates()
        if dataset_name == "financial_statement_summary"
        else empty_disclosure_candidates()
    )
    return candidate, diagnostic, schema


def concat_or_empty(frames: list[pd.DataFrame], empty: pd.DataFrame) -> pd.DataFrame:
    usable = [frame for frame in frames if isinstance(frame, pd.DataFrame) and not frame.empty]
    if not usable:
        return empty.copy()
    return pd.concat(usable, ignore_index=True, sort=False)


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


if __name__ == "__main__":
    raise SystemExit(main())
