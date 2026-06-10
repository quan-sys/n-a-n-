from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ingestion.evidence_pack_policy import (  # noqa: E402
    DOCUMENT_DISCOVERY_PLAN_COLUMNS,
    EVIDENCE_COLLECTION_QUEUE_COLUMNS,
    EVIDENCE_PACK_STATUS_COLUMNS,
    EVIDENCE_WORKLOAD_BUDGET_COLUMNS,
    MANUAL_SEED_REQUEST_COLUMNS,
    SCOPE_VALIDATION_COLUMNS,
    build_candidate_stage_assignments,
    build_document_discovery_plan,
    build_evidence_collection_queue,
    build_evidence_pack_status,
    build_manual_seed_requests,
    build_workload_budget_estimate,
    estimate_document_workload,
    forbidden_policy_output_columns,
    load_evidence_pack_policy,
    required_documents_for_stage,
    stage_order,
    validate_evidence_scope,
)


DEFAULT_DOCUMENT_INDEX = "data/reports/official_finance_documents_01ie/finance_document_index.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="REAL-DATA-EVIDENCE-PACK-01 staged official evidence policy.")
    parser.add_argument("--input", default="", help="Optional ranked watchlist/universe CSV.")
    parser.add_argument("--output-dir", default="data/reports/evidence_pack_policy_01")
    parser.add_argument("--policy", default="config/evidence_pack_policy.yaml")
    parser.add_argument("--document-index", default=DEFAULT_DOCUMENT_INDEX)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    policy = load_evidence_pack_policy(args.policy)
    input_frame, input_status = _read_optional_csv(args.input)
    document_index, document_index_status = _read_optional_csv(args.document_index)

    assignments = build_candidate_stage_assignments(input_frame, policy)
    queue = build_evidence_collection_queue(assignments, policy)
    discovery_plan = build_document_discovery_plan(assignments, queue, policy)
    manual_seed_requests = build_manual_seed_requests(queue)
    evidence_status = build_evidence_pack_status(assignments, policy, document_index=document_index)
    budget = build_workload_budget_estimate(policy)
    validation = pd.DataFrame(validate_evidence_scope(assignments, policy), columns=SCOPE_VALIDATION_COLUMNS)
    real_assignments = assignments[~assignments["template_only"].astype(bool)].copy() if "template_only" in assignments.columns else assignments
    workload = estimate_document_workload(real_assignments, policy)

    assignments.to_csv(output_dir / "candidate_stage_assignments.csv", index=False)
    queue.to_csv(output_dir / "evidence_collection_queue.csv", index=False)
    discovery_plan.to_csv(output_dir / "document_discovery_plan.csv", index=False)
    manual_seed_requests.to_csv(output_dir / "manual_seed_requests.csv", index=False)
    evidence_status.to_csv(output_dir / "evidence_pack_status.csv", index=False)
    budget.to_csv(output_dir / "evidence_workload_budget_estimate.csv", index=False)
    validation.to_csv(output_dir / "scope_validation_issues.csv", index=False)
    (output_dir / "data_readiness_gate.md").write_text(
        build_data_readiness_gate(),
        encoding="utf-8",
    )
    (output_dir / "run_summary.md").write_text(
        build_run_summary(
            args=args,
            policy=policy,
            assignments=assignments,
            queue=queue,
            evidence_status=evidence_status,
            budget=budget,
            validation=validation,
            workload=workload,
            input_status=input_status,
            document_index_status=document_index_status,
        ),
        encoding="utf-8",
    )

    print(
        {
            "output_dir": str(output_dir),
            "input_status": input_status,
            "stage_assignment_rows": int(len(assignments)),
            "evidence_queue_rows": int(len(queue)),
            "manual_seed_request_rows": int(len(manual_seed_requests)),
            "scope_validation_issues": int(len(validation)),
            "real_data_02_blocked": "Yes",
            "step19_blocked": "Yes",
        }
    )
    return 0


def build_data_readiness_gate() -> str:
    return "\n".join(
        [
            "# Data readiness gate",
            "",
            "- REAL-DATA-02 remains blocked unless Stage 2/3 has minimum evidence or an explicitly accepted provisional policy.",
            "- Step19 / L4 Company Engine remains blocked.",
            "- Official evidence pack is not the same as parsed financial data.",
            "- A ticker can be evidence-file-ready but not finance-parse-ready.",
            "- Downloaded PDF/BCTN/BCTC files must not be treated as parsed finance evidence until values are extracted with source/file/page/table/row evidence.",
            "- No buy/sell recommendation or target price logic is created by this policy.",
        ]
    )


def build_run_summary(
    *,
    args: argparse.Namespace,
    policy: dict[str, Any],
    assignments: pd.DataFrame,
    queue: pd.DataFrame,
    evidence_status: pd.DataFrame,
    budget: pd.DataFrame,
    validation: pd.DataFrame,
    workload: dict[str, Any],
    input_status: str,
    document_index_status: str,
) -> str:
    template_mode = bool(assignments["template_only"].astype(bool).all()) if not assignments.empty else True
    forbidden_columns = forbidden_policy_output_columns()
    return "\n".join(
        [
            "# REAL-DATA-EVIDENCE-PACK-01 run summary",
            "",
            "## Command",
            f"`{_command_string()}`",
            "",
            "## Input status",
            f"- ranked_input_status: {input_status}",
            f"- document_index_status: {document_index_status}",
            f"- template_only: {template_mode}",
            "- MISSING_RANKING_INPUT: " + ("Yes" if template_mode else "No"),
            "- No real investment ranking was inferred." if template_mode else "- Ranking was used only to assign evidence workload stage, not an investment recommendation.",
            "",
            "## Stage policy",
            *_format_stage_policy(policy),
            "",
            "## Required evidence per stage",
            *_format_required_documents(policy),
            "",
            "## Outputs",
            "- candidate_stage_assignments.csv",
            "- evidence_collection_queue.csv",
            "- document_discovery_plan.csv",
            "- manual_seed_requests.csv",
            "- evidence_pack_status.csv",
            "- evidence_workload_budget_estimate.csv",
            "- data_readiness_gate.md",
            "- run_summary.md",
            "",
            "## Workload",
            f"- assignment_estimated_files_min: {workload.get('total_estimated_files_min', 0)}",
            f"- assignment_estimated_files_max: {workload.get('total_estimated_files_max', 0)}",
            f"- evidence_collection_queue_rows: {len(queue)}",
            *_format_budget_highlights(budget),
            "",
            "## Why staged collection matters",
            "- Collecting 10-15 official files for 20-50 names would mean roughly 200-750 files before parsing even starts.",
            "- Stage 3 caps final-watchlist evidence at 2-3 files per ticker, keeping the initial official evidence pack to 40-150 files for a 20-50 name watchlist.",
            "- Deep 5-8 file packs are reserved for 5-10 names, and 10-15 file history is reserved for 1-3 names.",
            "",
            "## Evidence status counts",
            *_format_value_counts(evidence_status, "evidence_pack_status"),
            "",
            "## Scope validation",
            "- validation_issues: " + str(len(validation)),
            *_format_validation(validation),
            "",
            "## Safety",
            f"- forbidden_buy_sell_target_columns: {forbidden_columns if forbidden_columns else 'none'}",
            "- REAL-DATA-02 remains blocked.",
            "- Step19 remains blocked.",
            "- This run did not fetch PDFs, OCR, infer values, zero-fill values, or create target price/buy/sell logic.",
            "",
            f"_Generated at {datetime.now(UTC).replace(microsecond=0).isoformat()}._",
        ]
    )


def _format_stage_policy(policy: dict[str, Any]) -> list[str]:
    lines = []
    for stage in stage_order(policy):
        spec = policy["stages"][stage]
        lines.append(
            "- "
            f"{stage}: target_max_tickers={spec.get('target_max_tickers')}, "
            f"official_files_per_ticker={spec.get('official_files_per_ticker_min')}-{spec.get('official_files_per_ticker_max')}"
        )
    return lines


def _format_required_documents(policy: dict[str, Any]) -> list[str]:
    lines = []
    for stage in stage_order(policy):
        documents = required_documents_for_stage(stage, policy)
        labels = ", ".join(doc["document_priority"] for doc in documents) if documents else "none"
        lines.append(f"- {stage}: {labels}")
    return lines


def _format_budget_highlights(budget: pd.DataFrame) -> list[str]:
    lines = []
    if not isinstance(budget, pd.DataFrame) or budget.empty:
        return ["- workload_budget: unavailable"]
    for stage in ["stage_3_final_watchlist", "stage_4_deep_dive_shortlist", "stage_5_full_historical_research"]:
        row = budget[budget["stage"].eq(stage)]
        if row.empty:
            continue
        item = row.iloc[0]
        lines.append(
            "- "
            f"{stage}: estimated_files={item['estimated_files_min']}-{item['estimated_files_max']}, "
            f"manual_hours={item['manual_hours_min']}-{item['manual_hours_max']}"
        )
    return lines


def _format_value_counts(frame: pd.DataFrame, column: str) -> list[str]:
    if not isinstance(frame, pd.DataFrame) or frame.empty or column not in frame.columns:
        return ["- none"]
    return [f"- {key}: {value}" for key, value in frame[column].value_counts(dropna=False).items()]


def _format_validation(validation: pd.DataFrame) -> list[str]:
    if not isinstance(validation, pd.DataFrame) or validation.empty:
        return ["- none"]
    lines = []
    for _, row in validation.head(20).iterrows():
        lines.append(f"- {row.get('issue_code')}: {row.get('stage')} {row.get('ticker')} {row.get('message')}")
    return lines


def _read_optional_csv(path_value: str) -> tuple[pd.DataFrame, str]:
    if not path_value:
        return pd.DataFrame(), "MISSING_RANKING_INPUT"
    path = Path(path_value)
    if not path.exists():
        return pd.DataFrame(), f"MISSING_FILE:{path_value}"
    try:
        return pd.read_csv(path, keep_default_na=False), f"LOADED:{path_value}"
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(), f"READ_FAILED:{type(exc).__name__}:{exc}"


def _command_string() -> str:
    return " ".join([Path(sys.executable).name, *sys.argv])


if __name__ == "__main__":
    raise SystemExit(main())
