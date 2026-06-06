from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ingestion.finance_candidate_normalizer import (  # noqa: E402
    FINANCE_01I_CANDIDATE_COLUMNS,
    build_finance_field_coverage_by_source,
)
from src.ingestion.finance_numeric_reconciliation import reconcile_numeric_candidates  # noqa: E402
from src.ingestion.finance_web_source_probe import run_finance_source_probes  # noqa: E402
from src.ingestion.multi_source_evidence import (  # noqa: E402
    load_multi_source_registry,
    load_source_priority_config,
    run_multi_source_evidence,
    save_multi_source_evidence_reports,
)
from src.ingestion.source_adapter_diagnostics import finance_candidates_to_wide  # noqa: E402


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
    "universe": "data/raw/universe_raw.csv",
    "company_profile": "data/raw/company_profile_raw.csv",
    "market_price": "data/raw/market_price_raw.csv",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="REAL-DATA-01I finance web sources and field reconciliation.")
    parser.add_argument("--tickers", default=",".join(REPRESENTATIVE_20))
    parser.add_argument("--sources", default="vnstock,cafef,vietstock,company_ir,annual_report_pdf,exchange_filing")
    parser.add_argument("--periods", default="2026-Q1,2025-Q4,2025")
    parser.add_argument("--output-dir", default="data/reports/finance_web_sources_01i")
    parser.add_argument("--raw-snapshot-dir", default="data/raw/source_snapshots/01i")
    parser.add_argument("--request-sleep-seconds", type=float, default=3.2)
    parser.add_argument("--vnstock-max-workers", type=int, default=1)
    parser.add_argument("--source-probe-max-workers", type=int, default=4)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--previous-01g-dir", default="data/reports/multi_source_probe_01g")
    parser.add_argument("--disclosure-01h-dir", default="data/reports/disclosure_status_01h")
    parser.add_argument("--source-registry", default="config/multi_source_registry.yaml")
    parser.add_argument("--source-priority", default="config/source_priority.yaml")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tickers = parse_csv(args.tickers) or REPRESENTATIVE_20
    sources = parse_csv(args.sources)
    periods = parse_csv(args.periods)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    Path(args.raw_snapshot_dir).mkdir(parents=True, exist_ok=True)

    result = run_finance_source_probes(
        tickers=tickers,
        sources=sources,
        periods=periods,
        output_snapshot_dir=args.raw_snapshot_dir,
        request_sleep_seconds=args.request_sleep_seconds,
        vnstock_max_workers=args.vnstock_max_workers,
        source_probe_max_workers=args.source_probe_max_workers,
    )

    raw_candidates = result["finance_raw_candidate_rows"]
    normalized_candidates = raw_candidates.copy()
    coverage = build_finance_field_coverage_by_source(normalized_candidates)
    numeric_conflicts = reconcile_numeric_candidates(normalized_candidates)

    write_csv(result["finance_source_probe_matrix"], output_dir / "finance_source_probe_matrix.csv")
    write_csv(result["finance_adapter_diagnostics"], output_dir / "finance_adapter_diagnostics.csv")
    write_csv(result["finance_schema_diagnostics"], output_dir / "finance_schema_diagnostics.csv")
    write_csv(raw_candidates, output_dir / "finance_raw_candidate_rows.csv")
    write_csv(normalized_candidates, output_dir / "finance_normalized_candidate_rows.csv")
    write_csv(coverage, output_dir / "finance_field_coverage_by_source.csv")
    write_csv(numeric_conflicts, output_dir / "finance_numeric_conflict_report.csv")
    if not result["source_snapshot_metadata"].empty:
        write_csv(result["source_snapshot_metadata"], output_dir / "source_snapshot_metadata.csv")

    raw_context = load_raw_context()
    raw_context["financial_statement_summary"] = finance_candidates_to_wide(_legacy_candidate_columns(normalized_candidates))
    disclosure_raw = load_disclosure_01h(Path(args.disclosure_01h_dir))
    if disclosure_raw is not None:
        raw_context["disclosure_status"] = disclosure_raw

    evidence_result = run_multi_source_evidence(
        raw_datasets=raw_context,
        requested_tickers=tickers,
        source_registry=load_multi_source_registry(args.source_registry),
        priority_config=load_source_priority_config(args.source_priority),
        run_id="finance_web_sources_01i",
    )
    save_multi_source_evidence_reports(result=evidence_result, output_dir=output_dir)

    comparison_01g = build_comparison_vs_01g(Path(args.previous_01g_dir), normalized_candidates, evidence_result)
    (output_dir / "comparison_vs_01g.md").write_text(comparison_01g, encoding="utf-8")
    combined = build_combined_readiness(Path(args.disclosure_01h_dir), normalized_candidates, evidence_result, numeric_conflicts)
    (output_dir / "comparison_vs_01h_combined_readiness.md").write_text(combined["markdown"], encoding="utf-8")
    (output_dir / "finance_01i_run_summary.md").write_text(
        build_run_summary(
            command=" ".join([Path(sys.executable).name, *sys.argv]),
            tickers=tickers,
            periods=periods,
            sources=sources,
            probes=result["finance_source_probe_matrix"],
            diagnostics=result["finance_adapter_diagnostics"],
            candidates=normalized_candidates,
            coverage=coverage,
            conflicts=numeric_conflicts,
            combined=combined,
            vnstock_max_workers=args.vnstock_max_workers,
            source_probe_max_workers=args.source_probe_max_workers,
        ),
        encoding="utf-8",
    )
    (output_dir / "datasource_decision_report.md").write_text(build_decision_report(combined), encoding="utf-8")

    print(
        {
            "output_dir": str(output_dir),
            "raw_snapshot_dir": str(args.raw_snapshot_dir),
            "candidate_rows": int(len(normalized_candidates)),
            "net_profit_rows": int((normalized_candidates.get("field_name", pd.Series(dtype=str)) == "net_profit").sum()),
            "operating_cash_flow_rows": int((normalized_candidates.get("field_name", pd.Series(dtype=str)) == "operating_cash_flow").sum()),
            "finance_ready_for_l0": combined["finance_ready_for_l0"],
            "finance_disclosure_ready_for_step18": combined["finance_disclosure_ready_for_step18"],
            "step19_implemented": False,
        }
    )
    return 0


def load_raw_context() -> dict[str, pd.DataFrame]:
    output: dict[str, pd.DataFrame] = {}
    for dataset_name, filename in RAW_CONTEXT_FILENAMES.items():
        path = Path(filename)
        output[dataset_name] = pd.read_csv(path) if path.exists() else pd.DataFrame()
    return output


def load_disclosure_01h(path: Path) -> pd.DataFrame | None:
    candidates = path / "disclosure_candidate_rows.csv"
    if not candidates.exists():
        return None
    df = pd.read_csv(candidates)
    if df.empty:
        return df
    df = df.copy()
    df["source"] = df.get("source_name", "disclosure_status_01h")
    return df


def build_comparison_vs_01g(previous_dir: Path, candidates: pd.DataFrame, evidence_result: dict[str, Any]) -> str:
    previous_candidates = read_csv(previous_dir / "finance_raw_candidate_rows.csv")
    previous_unresolved = read_csv(previous_dir / "unresolved_required_fields.csv")
    current_unresolved = evidence_result["unresolved_required_fields"]
    previous_net_profit = _field_count(previous_candidates, "net_profit")
    current_net_profit = _field_count(candidates, "net_profit")
    previous_cfo = _field_count(previous_candidates, "operating_cash_flow")
    current_cfo = _field_count(candidates, "operating_cash_flow")
    return "\n".join(
        [
            "# Comparison vs 01G",
            "",
            f"- 01G finance candidate rows: {len(previous_candidates)}",
            f"- 01I finance candidate rows: {len(candidates)}",
            f"- 01G net_profit rows: {previous_net_profit}",
            f"- 01I net_profit rows: {current_net_profit}",
            f"- 01G operating_cash_flow rows: {previous_cfo}",
            f"- 01I operating_cash_flow rows: {current_cfo}",
            f"- 01G unresolved required fields: {len(previous_unresolved)}",
            f"- 01I unresolved required fields: {len(current_unresolved)}",
            "",
            "Missing fields remain unresolved; no financial values were fabricated.",
        ]
    )


def build_combined_readiness(
    disclosure_01h_dir: Path,
    candidates: pd.DataFrame,
    evidence_result: dict[str, Any],
    conflicts: pd.DataFrame,
) -> dict[str, Any]:
    unresolved = evidence_result["unresolved_required_fields"]
    finance_unresolved = unresolved[unresolved["dataset_name"] == "financial_statement_summary"] if not unresolved.empty else unresolved
    has_required = all(_field_count(candidates, field) > 0 for field in ["revenue", "net_profit", "total_assets", "total_liabilities", "equity"])
    finance_ready = "Partial" if has_required and not candidates.empty else "False"
    if not finance_unresolved.empty or not conflicts.empty:
        finance_ready = "Partial" if not candidates.empty else "False"
    disclosure_ready = parse_disclosure_ready(disclosure_01h_dir / "datasource_decision_report.md")
    combined_ready = "False"
    markdown = "\n".join(
        [
            "# Combined readiness with 01H disclosure",
            "",
            f"- finance_ready_for_l0: {finance_ready}",
            f"- disclosure_ready_for_l0 from 01H: {disclosure_ready}",
            f"- finance_disclosure_ready_for_step18: {combined_ready}",
            f"- unresolved finance required fields: {len(finance_unresolved)}",
            f"- finance conflicts: {len(conflicts)}",
            "",
            "Step 18 may consume partial evidence for diagnostics only; future Step 19 is blocked until finance/disclosure evidence is source-backed and reconciled.",
        ]
    )
    return {
        "finance_ready_for_l0": finance_ready,
        "disclosure_ready_for_l0": disclosure_ready,
        "finance_disclosure_ready_for_step18": combined_ready,
        "should_run_REAL_DATA_02": "No",
        "should_implement_Step19_now": "No",
        "markdown": markdown,
    }


def build_run_summary(
    *,
    command: str,
    tickers: list[str],
    periods: list[str],
    sources: list[str],
    probes: pd.DataFrame,
    diagnostics: pd.DataFrame,
    candidates: pd.DataFrame,
    coverage: pd.DataFrame,
    conflicts: pd.DataFrame,
    combined: dict[str, Any],
    vnstock_max_workers: int,
    source_probe_max_workers: int,
) -> str:
    accessible = sorted(probes.loc[probes["is_accessible"].astype(bool), "source_category"].dropna().astype(str).unique()) if not probes.empty else []
    parsed = sorted(diagnostics.loc[diagnostics["status"] == "ROWS_PARSED", "source_category"].dropna().astype(str).unique()) if not diagnostics.empty else []
    failed = diagnostics[diagnostics["status"] != "ROWS_PARSED"] if not diagnostics.empty else pd.DataFrame()
    by_source = candidates.groupby("source_category").size().to_dict() if not candidates.empty else {}
    normalized_by_source = by_source
    fields = coverage.groupby("source_category")["field_name"].apply(lambda values: "|".join(sorted(set(values)))).to_dict() if not coverage.empty else {}
    return "\n".join(
        [
            "# REAL-DATA-01I finance web sources run summary",
            "",
            f"- command: `{command}`",
            f"- tickers requested: {len(tickers)}",
            f"- tickers: {','.join(tickers)}",
            f"- periods requested: {','.join(periods)}",
            f"- sources attempted: {','.join(sources)}",
            f"- vnstock_max_workers: {vnstock_max_workers}",
            f"- source_probe_max_workers: {source_probe_max_workers}",
            f"- sources accessible: {','.join(accessible)}",
            f"- sources parsed: {','.join(parsed)}",
            f"- failed/partial diagnostic rows: {len(failed)}",
            f"- candidate rows by source: {by_source}",
            f"- normalized rows by source: {normalized_by_source}",
            f"- fields covered by source: {fields}",
            f"- net_profit rows: {_field_count(candidates, 'net_profit')}",
            f"- operating_cash_flow rows: {_field_count(candidates, 'operating_cash_flow')}",
            f"- conflicts: {len(conflicts)}",
            f"- finance_ready_for_l0: {combined['finance_ready_for_l0']}",
            f"- disclosure_ready_for_l0 from 01H: {combined['disclosure_ready_for_l0']}",
            f"- finance_disclosure_ready_for_step18: {combined['finance_disclosure_ready_for_step18']}",
            "",
            "No Step 19 logic, buy/sell logic, or target price logic was implemented.",
        ]
    )


def build_decision_report(combined: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Datasource decision report",
            "",
            f"- finance_ready_for_l0: {combined['finance_ready_for_l0']}",
            f"- disclosure_ready_for_l0_from_01h: {combined['disclosure_ready_for_l0']}",
            f"- finance_disclosure_ready_for_step18: {combined['finance_disclosure_ready_for_step18']}",
            f"- should_run_REAL_DATA_02: {combined['should_run_REAL_DATA_02']}",
            f"- should_implement_Step19_now: {combined['should_implement_Step19_now']}",
            "",
            "Decision: do not scale yet. Use source-backed manual CSV/XLSX or official PDF/IR evidence for unresolved representative tickers before REAL-DATA-02.",
        ]
    )


def parse_disclosure_ready(path: Path) -> str:
    if not path.exists():
        return "False"
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if "disclosure_ready_for_l0" in line:
            return line.split(":", 1)[-1].strip().strip("- ").strip() or "Partial"
    return "Partial"


def _legacy_candidate_columns(df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "ticker",
        "period",
        "period_type",
        "field_name",
        "value",
        "unit",
        "currency",
        "source_category",
        "source_name",
        "source_url",
        "fetch_time",
        "confidence_raw",
        "raw_label",
        "raw_value",
        "notes",
    ]
    output = df.copy()
    for column in columns:
        if column not in output.columns:
            output[column] = ""
    return output[columns]


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _field_count(df: pd.DataFrame, field_name: str) -> int:
    if not isinstance(df, pd.DataFrame) or df.empty or "field_name" not in df.columns:
        return 0
    return int((df["field_name"].astype(str) == field_name).sum())


if __name__ == "__main__":
    raise SystemExit(main())
