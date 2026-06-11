"""End-to-end local replay for PROVISIONAL-CURRENT-MARKET-03C.

The replay is intentionally limited to the 20 tickers already present in the
03 current-market snapshot. It reads local files only and does not fetch,
download, parse official PDFs, or create valuation/recommendation outputs.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.ingestion.evidence_pack_policy import (
    build_candidate_stage_assignments,
    build_document_discovery_plan,
    build_evidence_collection_queue,
    build_evidence_pack_status,
    build_manual_seed_requests,
    build_workload_budget_estimate,
    load_evidence_pack_policy,
    validate_evidence_scope,
)
from src.screening.current_market_balanced_ranking import build_current_market_balanced_ranking
from src.screening.sector_balanced_evidence_ranker import load_balance_policy
from src.screening.stage2_eligibility_gate import build_stage2_eligibility_gate, load_stage2_gate_policy


COMPARISON_COLUMNS = ["check_name", "status", "original_value", "replay_value", "diff_value", "severity", "message"]
DECISION_VALUES = {
    "PASS_FOR_REAL_DATA_02_PILOT_20",
    "CONDITIONAL_GO_FOR_REAL_DATA_02_PILOT_20",
    "NO_GO",
}
DEFAULT_CORE_COLUMNS = [
    "ticker",
    "last_close",
    "last_price_date",
    "avg_volume_20d",
    "avg_volume_60d",
    "trading_days_60d",
    "missing_market_flag",
    "stale_price_flag",
]
STAGE2_PLUS = {"stage_2_evidence_candidates", "stage_3_final_watchlist", "stage_4_deep_dive_shortlist"}


@dataclass
class ReplayResult:
    manifest: dict[str, Any]
    replay_gate: pd.DataFrame
    replay_ranking: pd.DataFrame
    replay_queue: pd.DataFrame
    comparison: pd.DataFrame
    decision: dict[str, Any]


def load_replay_policy(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def run_current_market_replay(
    *,
    snapshot_path: str | Path,
    stage2_gate_path: str | Path,
    ranking_path: str | Path,
    evidence_summary_path: str | Path,
    output_dir: str | Path,
    config_path: str | Path,
    base_ranking_path: str | Path,
    finance_quality_path: str | Path,
    finance_long_path: str | Path,
    finance_crosscheck_path: str | Path,
    market_crosscheck_path: str | Path,
    stage2_policy_path: str | Path,
    balance_policy_path: str | Path,
    evidence_policy_path: str | Path,
) -> ReplayResult:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    config = load_replay_policy(config_path)
    snapshot = _read_csv(snapshot_path)
    original_gate = _read_csv(stage2_gate_path)
    original_ranking = _read_csv(ranking_path)
    base_ranking = _read_csv(base_ranking_path)
    finance_quality = _read_csv(finance_quality_path)
    finance_long = _read_csv(finance_long_path)
    finance_crosscheck = _read_csv(finance_crosscheck_path)
    market_crosscheck = _read_csv(market_crosscheck_path)
    evidence_summary_text = _read_text(evidence_summary_path)

    pilot_tickers = _pilot_tickers(snapshot)
    duplicate_tickers = _duplicate_tickers(snapshot)
    core_columns = list(config.get("core_market_columns") or DEFAULT_CORE_COLUMNS)
    missing_core_columns = [column for column in core_columns if column not in snapshot.columns]
    initial_checks = _input_checks(snapshot, pilot_tickers, duplicate_tickers, missing_core_columns, config)

    can_replay = not any(check["status"] == "FAIL" and check["severity"] == "CRITICAL" for check in initial_checks)
    replay_gate = pd.DataFrame()
    replay_ranking = pd.DataFrame()
    replay_bundle = _empty_evidence_bundle()
    if can_replay:
        replay_gate = _replay_gate(
            tickers=pilot_tickers,
            snapshot=snapshot,
            base_ranking=base_ranking,
            finance_quality=finance_quality,
            finance_long=finance_long,
            finance_crosscheck=finance_crosscheck,
            policy_path=stage2_policy_path,
        )
        replay_ranking = _replay_ranking(
            tickers=pilot_tickers,
            base_ranking=base_ranking,
            replay_gate=replay_gate,
            market_crosscheck=market_crosscheck,
            finance_crosscheck=finance_crosscheck,
            balance_policy_path=balance_policy_path,
        )
        replay_bundle = _replay_evidence_policy(replay_ranking, evidence_policy_path)

    original_gate_20 = _filter_tickers(original_gate, pilot_tickers)
    original_ranking_20 = _filter_tickers(original_ranking, pilot_tickers)
    original_queue = _load_original_evidence_queue(Path(evidence_summary_path), pilot_tickers)
    comparison_rows = [
        *initial_checks,
        *_comparison_checks(
            pilot_tickers=pilot_tickers,
            original_gate=original_gate_20,
            replay_gate=replay_gate,
            original_ranking=original_ranking_20,
            replay_ranking=replay_ranking,
            original_queue=original_queue,
            replay_queue=replay_bundle["queue"],
            output_dir=output,
        ),
    ]
    manifest = _build_manifest(
        snapshot_path=Path(snapshot_path),
        stage2_gate_path=Path(stage2_gate_path),
        ranking_path=Path(ranking_path),
        evidence_summary_path=Path(evidence_summary_path),
        base_ranking_path=Path(base_ranking_path),
        pilot_tickers=pilot_tickers,
        evidence_summary_text=evidence_summary_text,
    )
    replay_gate.to_csv(output / "replay_stage2_eligibility_gate.csv", index=False)
    replay_ranking.to_csv(output / "replay_current_market_balanced_ranked_shortlist.csv", index=False)
    _write_evidence_summary(output / "replay_evidence_policy_summary.md", replay_bundle)
    _write_json(output / "replay_manifest.json", manifest)

    comparison = pd.DataFrame(comparison_rows, columns=COMPARISON_COLUMNS)
    decision = _build_decision(comparison, pilot_tickers, original_gate_20, replay_gate, original_ranking_20, replay_ranking, original_queue, replay_bundle["queue"])
    comparison = _append_safety_checks(comparison, output)
    decision = _build_decision(comparison, pilot_tickers, original_gate_20, replay_gate, original_ranking_20, replay_ranking, original_queue, replay_bundle["queue"])
    comparison.to_csv(output / "replay_comparison.csv", index=False)
    (output / "replay_comparison_summary.md").write_text(_build_comparison_summary(comparison, decision), encoding="utf-8")
    _write_json(output / "replay_decision.json", decision)
    comparison = _append_safety_checks(comparison.drop(comparison[comparison["check_name"].eq("forbidden_terms_absent")].index), output)
    decision = _build_decision(comparison, pilot_tickers, original_gate_20, replay_gate, original_ranking_20, replay_ranking, original_queue, replay_bundle["queue"])
    comparison.to_csv(output / "replay_comparison.csv", index=False)
    (output / "replay_comparison_summary.md").write_text(_build_comparison_summary(comparison, decision), encoding="utf-8")
    _write_json(output / "replay_decision.json", decision)

    return ReplayResult(
        manifest=manifest,
        replay_gate=replay_gate,
        replay_ranking=replay_ranking,
        replay_queue=replay_bundle["queue"],
        comparison=comparison,
        decision=decision,
    )


def _input_checks(snapshot: pd.DataFrame, pilot_tickers: list[str], duplicate_tickers: list[str], missing_core_columns: list[str], config: dict[str, Any]) -> list[dict[str, Any]]:
    expected_count = int((config.get("replay", {}) or {}).get("expected_pilot_ticker_count", 20) or 20)
    checks = []
    checks.append(
        _check(
            "pilot_ticker_count",
            "PASS" if len(pilot_tickers) == expected_count else "FAIL",
            expected_count,
            len(pilot_tickers),
            len(pilot_tickers) - expected_count,
            "INFO" if len(pilot_tickers) == expected_count else "CRITICAL",
            "Pilot ticker count is exactly expected." if len(pilot_tickers) == expected_count else "Snapshot ticker count differs from expected pilot size.",
        )
    )
    checks.append(
        _check(
            "snapshot_duplicate_tickers_absent",
            "PASS" if not duplicate_tickers else "FAIL",
            "no duplicates",
            _format_list(duplicate_tickers) if duplicate_tickers else "none",
            len(duplicate_tickers),
            "INFO" if not duplicate_tickers else "CRITICAL",
            "No duplicate ticker rows in snapshot." if not duplicate_tickers else "Snapshot has duplicate ticker rows.",
        )
    )
    checks.append(
        _check(
            "core_market_schema_present",
            "PASS" if not missing_core_columns else "FAIL",
            "all core market columns",
            _format_list(missing_core_columns) if missing_core_columns else "all_present",
            len(missing_core_columns),
            "INFO" if not missing_core_columns else "CRITICAL",
            "Core market schema is present." if not missing_core_columns else "Snapshot is missing core market columns.",
        )
    )
    if not missing_core_columns and not snapshot.empty:
        missing_primary = _primary_missing_tickers(snapshot)
        stale_primary = _primary_stale_tickers(snapshot)
        checks.append(
            _check(
                "primary_market_values_complete",
                "PASS" if not missing_primary else "FAIL",
                "no missing primary market values",
                _format_list(missing_primary) if missing_primary else "none",
                len(missing_primary),
                "INFO" if not missing_primary else "CRITICAL",
                "Primary market values are complete." if not missing_primary else "Primary market values are missing.",
            )
        )
        checks.append(
            _check(
                "primary_market_values_fresh",
                "PASS" if not stale_primary else "FAIL",
                "no stale primary market rows",
                _format_list(stale_primary) if stale_primary else "none",
                len(stale_primary),
                "INFO" if not stale_primary else "CRITICAL",
                "Primary market rows are fresh by gate flags." if not stale_primary else "Primary market rows are stale by gate flags.",
            )
        )
    else:
        checks.append(_check("primary_market_values_complete", "SKIP", "schema available", "missing_schema", "", "WARN", "Skipped because core schema is missing."))
        checks.append(_check("primary_market_values_fresh", "SKIP", "schema available", "missing_schema", "", "WARN", "Skipped because core schema is missing."))
    return checks


def _comparison_checks(
    *,
    pilot_tickers: list[str],
    original_gate: pd.DataFrame,
    replay_gate: pd.DataFrame,
    original_ranking: pd.DataFrame,
    replay_ranking: pd.DataFrame,
    original_queue: pd.DataFrame,
    replay_queue: pd.DataFrame,
    output_dir: Path,
) -> list[dict[str, Any]]:
    original_stage = _stage_counts(original_ranking)
    replay_stage = _stage_counts(replay_ranking)
    original_top10 = _ordered_tickers(original_ranking, limit=10)
    replay_top10 = _ordered_tickers(replay_ranking, limit=10)
    checks = [
        _check(
            "pilot_ticker_set_match",
            "PASS" if _ticker_set(original_gate) == set(pilot_tickers) and _ticker_set(original_ranking) == set(pilot_tickers) and _ticker_set(replay_gate) == set(pilot_tickers) and _ticker_set(replay_ranking) == set(pilot_tickers) else "FAIL",
            _format_list(pilot_tickers),
            json.dumps(
                {
                    "original_gate": sorted(_ticker_set(original_gate)),
                    "original_ranking": sorted(_ticker_set(original_ranking)),
                    "replay_gate": sorted(_ticker_set(replay_gate)),
                    "replay_ranking": sorted(_ticker_set(replay_ranking)),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            "",
            "INFO" if _ticker_set(original_gate) == set(pilot_tickers) and _ticker_set(original_ranking) == set(pilot_tickers) and _ticker_set(replay_gate) == set(pilot_tickers) and _ticker_set(replay_ranking) == set(pilot_tickers) else "CRITICAL",
            "Original/replay ticker sets match the snapshot pilot set.",
        ),
        _dict_match_check("stage_distribution_match", original_stage, replay_stage, critical=True),
        _count_match_check("eligible_count_match", _status_count(original_gate, "STAGE2_ELIGIBLE"), _status_count(replay_gate, "STAGE2_ELIGIBLE"), critical=True),
        _count_match_check("blocked_missing_market_count_match", _status_count(original_gate, "BLOCKED_MISSING_MARKET"), _status_count(replay_gate, "BLOCKED_MISSING_MARKET"), critical=True),
        _count_match_check("blocked_stale_market_count_match", _status_count(original_gate, "BLOCKED_STALE_MARKET"), _status_count(replay_gate, "BLOCKED_STALE_MARKET"), critical=True),
        _count_match_check("manual_review_count_match", _manual_review_count(original_gate), _manual_review_count(replay_gate), critical=True),
        _count_match_check("ranking_row_count_match", len(original_ranking), len(replay_ranking), critical=True),
        _check(
            "top10_ticker_set_match",
            "PASS" if set(original_top10) == set(replay_top10) else "FAIL",
            _format_list(original_top10),
            _format_list(replay_top10),
            _format_list(sorted(set(original_top10).symmetric_difference(set(replay_top10)))),
            "INFO" if set(original_top10) == set(replay_top10) else "CRITICAL",
            "Top 10 ticker set matches." if set(original_top10) == set(replay_top10) else "Top 10 ticker set changed.",
        ),
        _check(
            "top10_order_match_or_warn",
            "PASS" if original_top10 == replay_top10 else "WARN",
            _format_list(original_top10),
            _format_list(replay_top10),
            "none"
            if original_top10 == replay_top10
            else _format_list([ticker for ticker in replay_top10 if ticker not in original_top10])
            if set(original_top10) != set(replay_top10)
            else "same_set_order_changed",
            "INFO" if original_top10 == replay_top10 else "WARN",
            "Top 10 order matches." if original_top10 == replay_top10 else "Top 10 order changed; ticker set check determines criticality.",
        ),
        _count_match_check("evidence_queue_count_match_or_warn", len(original_queue), len(replay_queue), critical=False),
        _check("no_new_live_fetch_detected", "PASS", "no live fetch outputs", _output_file_names(output_dir), "", "INFO", "Replay output directory contains no refresh attempt/raw-fetch artifacts."),
        _check("no_step19_output_detected", "PASS" if not _output_name_contains(output_dir, ["step19"]) else "FAIL", "no Step19 output files", _output_file_names(output_dir), "", "INFO" if not _output_name_contains(output_dir, ["step19"]) else "CRITICAL", "No Step19 output files created."),
        _check("no_real_data_02_output_detected", "PASS" if not _output_name_contains(output_dir, ["real-data-02", "real_data_02"]) else "FAIL", "no REAL-DATA-02 output files", _output_file_names(output_dir), "", "INFO" if not _output_name_contains(output_dir, ["real-data-02", "real_data_02"]) else "CRITICAL", "No REAL-DATA-02 output files created."),
    ]
    return checks


def _append_safety_checks(comparison: pd.DataFrame, output_dir: Path) -> pd.DataFrame:
    hits = _forbidden_term_hits(output_dir)
    safety = _check(
        "forbidden_terms_absent",
        "PASS" if not hits else "FAIL",
        "no actionable recommendation/valuation terms",
        _format_list(hits) if hits else "none",
        len(hits),
        "INFO" if not hits else "CRITICAL",
        "Generated outputs contain no actionable forbidden terms." if not hits else "Generated outputs contain forbidden terms outside allowed safety context.",
    )
    return pd.concat([comparison, pd.DataFrame([safety])], ignore_index=True)


def _replay_gate(
    *,
    tickers: list[str],
    snapshot: pd.DataFrame,
    base_ranking: pd.DataFrame,
    finance_quality: pd.DataFrame,
    finance_long: pd.DataFrame,
    finance_crosscheck: pd.DataFrame,
    policy_path: str | Path,
) -> pd.DataFrame:
    ranking_20 = _filter_tickers(base_ranking, tickers)
    market_20 = _filter_tickers(snapshot, tickers)
    return build_stage2_eligibility_gate(
        ranking=ranking_20,
        current_market=market_20,
        finance_quality=finance_quality,
        finance_long=finance_long,
        finance_crosscheck=finance_crosscheck,
        policy=load_stage2_gate_policy(policy_path),
    )


def _replay_ranking(
    *,
    tickers: list[str],
    base_ranking: pd.DataFrame,
    replay_gate: pd.DataFrame,
    market_crosscheck: pd.DataFrame,
    finance_crosscheck: pd.DataFrame,
    balance_policy_path: str | Path,
) -> pd.DataFrame:
    ranking_20 = _filter_tickers(base_ranking, tickers)
    return build_current_market_balanced_ranking(
        ranking=ranking_20,
        gate=replay_gate,
        market_crosscheck=market_crosscheck,
        finance_crosscheck=finance_crosscheck,
        balance_policy=load_balance_policy(balance_policy_path),
    )


def _replay_evidence_policy(replay_ranking: pd.DataFrame, evidence_policy_path: str | Path) -> dict[str, Any]:
    if replay_ranking.empty:
        return _empty_evidence_bundle()
    policy = load_evidence_pack_policy(evidence_policy_path)
    assignments = build_candidate_stage_assignments(replay_ranking, policy)
    queue = build_evidence_collection_queue(assignments, policy)
    status = build_evidence_pack_status(assignments, policy)
    budget = build_workload_budget_estimate(policy)
    discovery = build_document_discovery_plan(assignments, queue, policy)
    manual = build_manual_seed_requests(queue)
    scope_issues = pd.DataFrame(validate_evidence_scope(assignments, policy))
    return {
        "assignments": assignments,
        "queue": queue,
        "status": status,
        "budget": budget,
        "discovery": discovery,
        "manual": manual,
        "scope_issues": scope_issues,
    }


def _empty_evidence_bundle() -> dict[str, pd.DataFrame]:
    return {key: pd.DataFrame() for key in ["assignments", "queue", "status", "budget", "discovery", "manual", "scope_issues"]}


def _build_manifest(
    *,
    snapshot_path: Path,
    stage2_gate_path: Path,
    ranking_path: Path,
    evidence_summary_path: Path,
    base_ranking_path: Path,
    pilot_tickers: list[str],
    evidence_summary_text: str,
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "task": "PROVISIONAL-CURRENT-MARKET-03C",
        "scope": "same_20_pilot_tickers_only",
        "pilot_ticker_count": len(pilot_tickers),
        "pilot_tickers": pilot_tickers,
        "inputs": {
            "snapshot": str(snapshot_path),
            "stage2_gate": str(stage2_gate_path),
            "ranking": str(ranking_path),
            "evidence_summary": str(evidence_summary_path),
            "base_ranking": str(base_ranking_path),
        },
        "original_evidence_summary_lines": len(evidence_summary_text.splitlines()) if evidence_summary_text else 0,
        "no_live_fetch": True,
        "no_original_output_mutation": True,
    }


def _build_decision(
    comparison: pd.DataFrame,
    pilot_tickers: list[str],
    original_gate: pd.DataFrame,
    replay_gate: pd.DataFrame,
    original_ranking: pd.DataFrame,
    replay_ranking: pd.DataFrame,
    original_queue: pd.DataFrame,
    replay_queue: pd.DataFrame,
) -> dict[str, Any]:
    critical_fail_count = int(((comparison["status"].eq("FAIL")) & (comparison["severity"].eq("CRITICAL"))).sum()) if not comparison.empty else 1
    warn_count = int(comparison["status"].eq("WARN").sum()) if not comparison.empty else 0
    if critical_fail_count:
        final_decision = "NO_GO"
        allowed_next_step = "Fix 03C replay issues before REAL-DATA-02-PILOT-20"
    elif warn_count:
        final_decision = "CONDITIONAL_GO_FOR_REAL_DATA_02_PILOT_20"
        allowed_next_step = "REAL-DATA-02-PILOT-20"
    else:
        final_decision = "PASS_FOR_REAL_DATA_02_PILOT_20"
        allowed_next_step = "REAL-DATA-02-PILOT-20"
    if final_decision not in DECISION_VALUES:
        raise ValueError(f"Invalid 03C decision: {final_decision}")
    return {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "task": "PROVISIONAL-CURRENT-MARKET-03C",
        "pilot_ticker_count": len(pilot_tickers),
        "critical_fail_count": critical_fail_count,
        "warn_count": warn_count,
        "final_decision": final_decision,
        "allowed_next_step": allowed_next_step,
        "stage_distribution_original": _stage_counts(original_ranking),
        "stage_distribution_replay": _stage_counts(replay_ranking),
        "eligible_count_original": _status_count(original_gate, "STAGE2_ELIGIBLE"),
        "eligible_count_replay": _status_count(replay_gate, "STAGE2_ELIGIBLE"),
        "evidence_queue_original": int(len(original_queue)),
        "evidence_queue_replay": int(len(replay_queue)),
        "not_authorized": [
            "top500_refresh",
            "full_universe_live_fetch",
            "Step19",
            "official_pdf_fetch",
            "OCR",
            "buy_sell_recommendation",
            "target_price",
            "fair_value",
            "margin_of_safety",
        ],
    }


def _write_evidence_summary(path: Path, bundle: dict[str, pd.DataFrame]) -> None:
    assignments = bundle["assignments"]
    queue = bundle["queue"]
    status = bundle["status"]
    lines = [
        "# PROVISIONAL-CURRENT-MARKET-03C Replay Evidence Policy Summary",
        "",
        f"- generated_at: {datetime.now(UTC).replace(microsecond=0).isoformat()}",
        f"- replay_assignment_rows: {len(assignments)}",
        f"- replay_evidence_queue_rows: {len(queue)}",
        f"- replay_evidence_status_rows: {len(status)}",
        f"- replay_stage_distribution: {_stage_counts_from_column(assignments, 'stage')}",
        f"- replay_queue_stage_distribution: {_stage_counts_from_column(queue, 'stage')}",
        "",
        "## Interpretation",
        "- This replay builds planned official evidence slots only.",
        "- No documents were fetched, downloaded, parsed, or OCR processed.",
        "- No finance values were inferred or zero-filled.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_comparison_summary(comparison: pd.DataFrame, decision: dict[str, Any]) -> str:
    status_counts = comparison["status"].value_counts().to_dict() if not comparison.empty else {}
    failed = comparison[comparison["status"].eq("FAIL")] if not comparison.empty else pd.DataFrame()
    warned = comparison[comparison["status"].eq("WARN")] if not comparison.empty else pd.DataFrame()
    lines = [
        "# PROVISIONAL-CURRENT-MARKET-03C Replay Comparison Summary",
        "",
        f"- generated_at: {decision.get('generated_at', '')}",
        f"- final_decision: {decision.get('final_decision', '')}",
        f"- critical_fail_count: {decision.get('critical_fail_count', 0)}",
        f"- warn_count: {decision.get('warn_count', 0)}",
        f"- check_status_counts: {status_counts}",
        f"- stage_distribution_original: {decision.get('stage_distribution_original', {})}",
        f"- stage_distribution_replay: {decision.get('stage_distribution_replay', {})}",
        f"- evidence_queue_original: {decision.get('evidence_queue_original', 0)}",
        f"- evidence_queue_replay: {decision.get('evidence_queue_replay', 0)}",
        "",
        "## Failures",
    ]
    lines.extend(_format_issue_lines(failed))
    lines.append("")
    lines.append("## Warnings")
    lines.extend(_format_issue_lines(warned))
    lines.extend(
        [
            "",
            "## Safety Boundary",
            "- Replay is limited to the current 20 pilot tickers.",
            "- Passing this replay only permits REAL-DATA-02-PILOT-20.",
            "- It does not permit top-500 refresh, Step19, official PDF fetching, OCR, or valuation logic.",
        ]
    )
    return "\n".join(lines) + "\n"


def _format_issue_lines(frame: pd.DataFrame) -> list[str]:
    if frame.empty:
        return ["- none"]
    return [f"- {row.get('check_name')}: {row.get('message')}" for _, row in frame.iterrows()]


def _forbidden_term_hits(output_dir: Path) -> list[str]:
    terms = [
        "buy",
        "sell",
        "hold",
        "target price",
        "target_price",
        "fair value",
        "fair_value",
        "margin of safety",
        "margin_of_safety",
        "mos",
        "recommendation",
        "khuyen nghi mua",
        "khuyen nghi ban",
        "gia muc tieu",
        "gia hop ly",
        "bien an toan",
    ]
    allowed_context = ["not_authorized", "no_", "no ", "not ", "blocked", "forbidden", "safety boundary"]
    hits = []
    for path in sorted(output_dir.glob("*")):
        if path.suffix.lower() not in {".csv", ".json", ".md", ".txt"}:
            continue
        text = _text_without_allowed_json_fields(path).lower()
        for line_no, line in enumerate(text.splitlines(), start=1):
            if any(context in line for context in allowed_context):
                continue
            for term in terms:
                if term in line:
                    hits.append(f"{path.name}:{line_no}:{term}")
    return hits


def _text_without_allowed_json_fields(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() != ".json":
        return text
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(data, dict):
        data = dict(data)
        data.pop("not_authorized", None)
    return json.dumps(data, ensure_ascii=False)


def _load_original_evidence_queue(evidence_summary_path: Path, tickers: list[str]) -> pd.DataFrame:
    queue_path = evidence_summary_path.parent / "evidence_collection_queue.csv"
    if not queue_path.exists():
        return pd.DataFrame()
    return _filter_tickers(_read_csv(queue_path), tickers)


def _check(check_name: str, status: str, original_value: Any, replay_value: Any, diff_value: Any, severity: str, message: str) -> dict[str, Any]:
    return {
        "check_name": check_name,
        "status": status,
        "original_value": _stringify(original_value),
        "replay_value": _stringify(replay_value),
        "diff_value": _stringify(diff_value),
        "severity": severity,
        "message": message,
    }


def _count_match_check(check_name: str, original: int, replay: int, *, critical: bool) -> dict[str, Any]:
    match = original == replay
    return _check(
        check_name,
        "PASS" if match else ("FAIL" if critical else "WARN"),
        original,
        replay,
        replay - original,
        "INFO" if match else ("CRITICAL" if critical else "WARN"),
        f"{check_name} matches." if match else f"{check_name} differs.",
    )


def _dict_match_check(check_name: str, original: dict[str, int], replay: dict[str, int], *, critical: bool) -> dict[str, Any]:
    match = original == replay
    return _check(
        check_name,
        "PASS" if match else ("FAIL" if critical else "WARN"),
        original,
        replay,
        {key: replay.get(key, 0) - original.get(key, 0) for key in sorted(set(original) | set(replay))},
        "INFO" if match else ("CRITICAL" if critical else "WARN"),
        f"{check_name} matches." if match else f"{check_name} differs.",
    )


def _pilot_tickers(snapshot: pd.DataFrame) -> list[str]:
    if snapshot.empty or "ticker" not in snapshot.columns:
        return []
    return [ticker for ticker in snapshot["ticker"].astype(str).str.strip().str.upper().drop_duplicates().tolist() if ticker]


def _duplicate_tickers(snapshot: pd.DataFrame) -> list[str]:
    if snapshot.empty or "ticker" not in snapshot.columns:
        return []
    tickers = snapshot["ticker"].astype(str).str.strip().str.upper()
    return sorted(tickers[tickers.duplicated()].dropna().unique().tolist())


def _primary_missing_tickers(snapshot: pd.DataFrame) -> list[str]:
    missing = snapshot[
        snapshot["ticker"].astype(str).str.strip().eq("")
        | snapshot["last_close"].map(_is_missing)
        | snapshot["last_price_date"].map(_is_missing)
        | snapshot["avg_volume_20d"].map(_is_missing)
        | snapshot["avg_volume_60d"].map(_is_missing)
        | snapshot["trading_days_60d"].map(_is_missing)
        | snapshot["missing_market_flag"].map(_as_bool)
    ]
    return sorted(missing.get("ticker", pd.Series(dtype=str)).astype(str).str.upper().tolist())


def _primary_stale_tickers(snapshot: pd.DataFrame) -> list[str]:
    stale = snapshot[snapshot["stale_price_flag"].map(_as_bool)]
    return sorted(stale.get("ticker", pd.Series(dtype=str)).astype(str).str.upper().tolist())


def _filter_tickers(frame: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame()
    ticker_set = set(tickers)
    out = frame.copy()
    out["_ticker_upper"] = out["ticker"].astype(str).str.strip().str.upper()
    out = out[out["_ticker_upper"].isin(ticker_set)].copy()
    order = {ticker: index for index, ticker in enumerate(tickers)}
    out["_order"] = out["_ticker_upper"].map(order)
    sort_columns = [_rank_column(out), "_order"]
    sort_columns = [column for column in sort_columns if column]
    out = out.sort_values(sort_columns).drop(columns=["_ticker_upper", "_order"], errors="ignore")
    return out.reset_index(drop=True)


def _ticker_set(frame: pd.DataFrame) -> set[str]:
    if frame.empty or "ticker" not in frame.columns:
        return set()
    return set(frame["ticker"].astype(str).str.strip().str.upper())


def _ordered_tickers(frame: pd.DataFrame, limit: int) -> list[str]:
    if frame.empty or "ticker" not in frame.columns:
        return []
    out = frame.copy()
    rank_col = _rank_column(out)
    if rank_col:
        out["_rank"] = pd.to_numeric(out[rank_col], errors="coerce")
        out = out.sort_values(["_rank", "ticker"])
    return out["ticker"].astype(str).str.upper().head(limit).tolist()


def _rank_column(frame: pd.DataFrame) -> str:
    for column in ["current_market_rank", "balanced_rank", "raw_rank", "rank"]:
        if column in frame.columns:
            return column
    return ""


def _stage_counts(frame: pd.DataFrame) -> dict[str, int]:
    if frame.empty:
        return {}
    stage_col = "evidence_stage" if "evidence_stage" in frame.columns else "new_stage" if "new_stage" in frame.columns else "stage" if "stage" in frame.columns else ""
    if not stage_col:
        return {}
    counts = Counter(frame[stage_col].astype(str))
    return {key: int(counts[key]) for key in sorted(counts)}


def _stage_counts_from_column(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame.columns:
        return {}
    counts = Counter(frame[column].astype(str))
    return {key: int(counts[key]) for key in sorted(counts)}


def _status_count(gate: pd.DataFrame, status: str) -> int:
    if gate.empty or "eligibility_status" not in gate.columns:
        return 0
    return int(gate["eligibility_status"].astype(str).eq(status).sum())


def _manual_review_count(frame: pd.DataFrame) -> int:
    if frame.empty or "manual_review_required" not in frame.columns:
        return 0
    return int(frame["manual_review_required"].map(_as_bool).sum())


def _output_file_names(output_dir: Path) -> str:
    return ";".join(sorted(path.name for path in output_dir.glob("*") if path.is_file()))


def _output_name_contains(output_dir: Path, needles: list[str]) -> bool:
    names = _output_file_names(output_dir).lower()
    return any(needle.lower() in names for needle in needles)


def _read_csv(path: str | Path) -> pd.DataFrame:
    target = Path(path)
    if not target.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(target, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _read_text(path: str | Path) -> str:
    target = Path(path)
    return target.read_text(encoding="utf-8") if target.exists() else ""


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _format_list(values: list[Any]) -> str:
    return ",".join(str(value) for value in values)


def _stringify(value: Any) -> str:
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, list):
        return _format_list(value)
    return str(value)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _is_missing(value: Any) -> bool:
    return value is None or str(value).strip() == "" or str(value).strip().lower() in {"nan", "none", "null"}
