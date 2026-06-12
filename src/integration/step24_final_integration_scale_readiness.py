"""STEP24 final integration and scale-readiness gate.

The checker validates process contracts across the provisional pipeline. It does
not run the full universe, change previous outputs, or promote any ticker.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


STEP_ID = "STEP24-FINAL-INTEGRATION-CONTRACT-SCALE-READINESS"
MODE = "final_integration_scale_readiness_only"
SAFETY_NOTICE = (
    "This is a process-readiness report for a provisional screening system. "
    "It provides operational checks only and contains no trading guidance."
)

INTEGRATION_STATUSES = {
    "INTEGRATION_READY_FOR_PRIMARY_ONLY_SCALE",
    "INTEGRATION_READY_WITH_WARNINGS",
    "PARTIAL_INTEGRATION_ONLY",
    "BLOCKED_MISSING_ARTIFACTS",
    "BLOCKED_FORBIDDEN_OUTPUT",
    "BLOCKED_CONFIDENCE_LABEL_VIOLATION",
}

FULL_UNIVERSE_READINESS_VALUES = {
    "READY_FOR_FULL_UNIVERSE_PRIMARY_ONLY_RUN",
    "READY_FOR_FULL_UNIVERSE_WITH_WARNINGS",
    "NOT_READY_FOR_FULL_UNIVERSE",
}

FINAL_DECISIONS = {
    "PASS_FINAL_INTEGRATION_READY_FOR_PRIMARY_ONLY_SCALE",
    "PASS_FINAL_INTEGRATION_WITH_WARNINGS",
    "BLOCKED_FINAL_INTEGRATION",
}

BLOCKED_PREVIOUS_DECISION_PREFIXES = ("BLOCKED", "NO_GO")

FORBIDDEN_TERMS = [
    "buy",
    "sell",
    "hold",
    "buy now",
    "sell now",
    "target price",
    "fair value",
    "intrinsic value",
    "margin of safety",
    "expected return",
    "entry price",
    "exit price",
    "stoploss",
    "take profit",
    "recommended portfolio",
    "strategy beats market",
    "guaranteed alpha",
]

ARTIFACT_COLUMNS = ["artifact_name", "path", "exists", "status", "final_decision", "integration_note"]
SCHEMA_COLUMNS = ["artifact_name", "path", "required_columns", "missing_columns", "status"]
SOURCE_COLUMNS = [
    "artifact_name",
    "market_source_confidence",
    "finance_source_confidence",
    "crosscheck_status",
    "verification_status",
    "status",
    "note",
]
FORBIDDEN_COLUMNS = ["scanned_path", "forbidden_terms_found", "status"]
MANUAL_COLUMNS = ["contract_name", "path", "exists", "row_count", "missing_columns", "status", "note"]


class Step24SafeRunBlocked(RuntimeError):
    """Raised when a requested Step24 run violates scope controls."""


@dataclass
class Step24Result:
    artifact_checklist: pd.DataFrame
    schema_contract_check: pd.DataFrame
    source_confidence_check: pd.DataFrame
    forbidden_terms_check: pd.DataFrame
    manual_review_contract_check: pd.DataFrame
    run_manifest: dict[str, Any]
    summary: dict[str, Any]


def load_step24_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("STEP24 config must be a mapping.")
    return data


def run_step24_final_integration_scale_readiness(
    *,
    config_path: str | Path,
    output_dir: str | Path | None = None,
    allow_partial: bool | None = None,
    request_full_universe: bool = False,
    request_scale_1743: bool = False,
    command_used: str = "",
    core_output_paths: list[str | Path] | None = None,
) -> Step24Result:
    config = load_step24_config(config_path)
    validate_step24_config(config)
    limits = config.get("limits") or {}
    if request_full_universe and not _as_bool(limits.get("full_universe_allowed", False)):
        raise Step24SafeRunBlocked("Full-universe execution is blocked by STEP24 config.")
    if request_scale_1743 and not _as_bool(limits.get("scale_1743_allowed", False)):
        raise Step24SafeRunBlocked("1743-scale execution is blocked by STEP24 config.")

    output = Path(output_dir or ((config.get("exports") or {}).get("output_dir") or "data/reports/step24_final_integration_scale_readiness"))
    output.mkdir(parents=True, exist_ok=True)
    run_policy = dict(config.get("run") or {})
    if allow_partial is not None:
        run_policy["allow_partial"] = bool(allow_partial)
    allow_partial_effective = _as_bool(run_policy.get("allow_partial", True))

    core_paths = [Path(path) for path in (core_output_paths or config.get("core_output_watchlist", []))]
    before_hashes = _hashes(core_paths)
    artifact_checklist, summaries, missing_artifacts = build_artifact_checklist(config)
    if missing_artifacts and not allow_partial_effective:
        raise Step24SafeRunBlocked("STEP24 missing artifacts while allow_partial=false: " + ",".join(missing_artifacts))
    schema_check = build_schema_contract_check(config)
    source_check = build_source_confidence_check(config, summaries)
    manual_check = build_manual_review_contract_check(config)
    forbidden_check = build_forbidden_terms_check(config)
    forbidden_hits = _forbidden_hits_from_check(forbidden_check)
    core_modified = before_hashes != _hashes(core_paths)
    summary = build_summary(
        config=config,
        artifact_checklist=artifact_checklist,
        schema_check=schema_check,
        source_check=source_check,
        manual_check=manual_check,
        forbidden_hits=forbidden_hits,
        core_outputs_modified=core_modified,
    )
    manifest = build_run_manifest(
        config=config,
        config_path=Path(config_path),
        output_dir=output,
        allow_partial=allow_partial_effective,
        command_used=command_used,
        core_outputs_modified=core_modified,
        missing_artifacts=missing_artifacts,
    )
    write_step24_outputs(
        output_dir=output,
        artifact_checklist=artifact_checklist,
        schema_check=schema_check,
        source_check=source_check,
        forbidden_check=forbidden_check,
        manual_check=manual_check,
        summary=summary,
        manifest=manifest,
    )
    output_hits = scan_forbidden_terms(output)
    if output_hits:
        summary = build_summary(
            config=config,
            artifact_checklist=artifact_checklist,
            schema_check=schema_check,
            source_check=source_check,
            manual_check=manual_check,
            forbidden_hits=sorted(set(forbidden_hits + output_hits)),
            core_outputs_modified=core_modified,
        )
        write_step24_outputs(
            output_dir=output,
            artifact_checklist=artifact_checklist,
            schema_check=schema_check,
            source_check=source_check,
            forbidden_check=forbidden_check,
            manual_check=manual_check,
            summary=summary,
            manifest=manifest,
        )
    return Step24Result(
        artifact_checklist=artifact_checklist,
        schema_contract_check=schema_check,
        source_confidence_check=source_check,
        forbidden_terms_check=forbidden_check,
        manual_review_contract_check=manual_check,
        run_manifest=manifest,
        summary=summary,
    )


def validate_step24_config(config: dict[str, Any]) -> None:
    if config.get("step_id") != STEP_ID:
        raise ValueError(f"STEP24 config step_id must be {STEP_ID}.")
    safety = config.get("safety") if isinstance(config.get("safety"), dict) else {}
    required = [
        "no_recommendation",
        "no_buy_sell_hold",
        "no_target_price",
        "no_fair_value",
        "no_intrinsic_value",
        "no_margin_of_safety",
        "no_expected_return",
        "no_entry_exit_price",
        "no_portfolio_recommendation",
        "no_strategy_claim",
        "no_pdf_ocr",
        "no_official_bctc_scrape",
        "no_zero_fill",
        "no_core_output_mutation",
        "no_stage_promotion_to_investment_ready",
    ]
    missing = [key for key in required if safety.get(key) is not True]
    if missing:
        raise ValueError(f"STEP24 safety flags must be true: {','.join(missing)}")


def build_artifact_checklist(config: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    summaries: dict[str, dict[str, Any]] = {}
    missing_artifacts: list[str] = []
    for name, spec in (config.get("required_artifacts") or {}).items():
        path = _first_existing_path(spec)
        exists = path is not None
        final_decision = ""
        note = "artifact_available"
        if not exists:
            status = "MISSING_REQUIRED_ARTIFACT"
            note = "PARTIAL_INTEGRATION_ONLY"
            missing_artifacts.append(str(name))
        else:
            summary = _read_json(path) if str(path).lower().endswith(".json") else {}
            if summary:
                summaries[str(name)] = summary
            final_decision = str(summary.get("final_decision", ""))
            if final_decision.upper().startswith(BLOCKED_PREVIOUS_DECISION_PREFIXES):
                status = "PREVIOUS_STEP_BLOCKED"
                note = "previous decision blocks readiness"
            else:
                status = "AVAILABLE"
        rows.append(
            {
                "artifact_name": name,
                "path": str(path) if path else _spec_text(spec),
                "exists": bool(exists),
                "status": status,
                "final_decision": final_decision,
                "integration_note": note,
            }
        )
    return pd.DataFrame(rows, columns=ARTIFACT_COLUMNS), summaries, missing_artifacts


def build_schema_contract_check(config: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for name, contract in (config.get("schema_contracts") or {}).items():
        path = _first_existing_path((contract or {}).get("path"))
        required = [str(column) for column in ((contract or {}).get("required_columns") or [])]
        if path is None:
            missing = required
            status = "MISSING_REQUIRED_ARTIFACT"
        else:
            frame = _read_csv(path)
            missing = [column for column in required if column not in frame.columns]
            status = "PASS" if not missing else "SCHEMA_MISSING_COLUMNS"
        rows.append(
            {
                "artifact_name": name,
                "path": str(path) if path else _spec_text((contract or {}).get("path")),
                "required_columns": _json_list(required),
                "missing_columns": _json_list(missing),
                "status": status,
            }
        )
    return pd.DataFrame(rows, columns=SCHEMA_COLUMNS)


def build_source_confidence_check(config: dict[str, Any], summaries: dict[str, dict[str, Any]]) -> pd.DataFrame:
    expected = config.get("source_confidence") or {}
    rows: list[dict[str, Any]] = []
    for name, summary in summaries.items():
        observed = _observed_confidence(summary)
        status, note = _source_status(observed, expected)
        rows.append(
            {
                "artifact_name": name,
                "market_source_confidence": observed.get("market_source_confidence", "UNKNOWN"),
                "finance_source_confidence": observed.get("finance_source_confidence", "UNKNOWN"),
                "crosscheck_status": observed.get("crosscheck_status", "UNKNOWN"),
                "verification_status": observed.get("verification_status", "UNKNOWN"),
                "status": status,
                "note": note,
            }
        )
    if not rows:
        rows.append(
            {
                "artifact_name": "NO_SUMMARIES_AVAILABLE",
                "market_source_confidence": "UNKNOWN",
                "finance_source_confidence": "UNKNOWN",
                "crosscheck_status": "UNKNOWN",
                "verification_status": "UNKNOWN",
                "status": "MISSING_REQUIRED_ARTIFACT",
                "note": "No summary artifacts were available.",
            }
        )
    return pd.DataFrame(rows, columns=SOURCE_COLUMNS)


def build_forbidden_terms_check(config: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for raw_dir in config.get("forbidden_scan_dirs") or []:
        path = Path(str(raw_dir))
        if not path.exists():
            rows.append({"scanned_path": str(path), "forbidden_terms_found": "[]", "status": "MISSING_SCAN_DIR"})
            continue
        hits = scan_forbidden_terms(path)
        rows.append(
            {
                "scanned_path": str(path),
                "forbidden_terms_found": _json_list(hits),
                "status": "PASS" if not hits else "FORBIDDEN_TERMS_FOUND",
            }
        )
    return pd.DataFrame(rows, columns=FORBIDDEN_COLUMNS)


def build_manual_review_contract_check(config: dict[str, Any]) -> pd.DataFrame:
    manual_spec = (config.get("required_artifacts") or {}).get("step05a_manual_queue")
    path = _first_existing_path(manual_spec)
    required = ["ticker", "missing_fields", "verification_status"]
    if path is None:
        return pd.DataFrame(
            [
                {
                    "contract_name": "manual_bctc_review_queue",
                    "path": _spec_text(manual_spec),
                    "exists": False,
                    "row_count": 0,
                    "missing_columns": _json_list(required),
                    "status": "MISSING_REQUIRED_ARTIFACT",
                    "note": "Manual review queue artifact is missing.",
                }
            ],
            columns=MANUAL_COLUMNS,
        )
    frame = _read_csv(path)
    missing = [column for column in required if column not in frame.columns]
    row_count = int(len(frame))
    status = "PASS" if not missing and row_count > 0 else "MANUAL_REVIEW_CONTRACT_INCOMPLETE"
    note = "manual_review_queue_available" if status == "PASS" else "manual_review_queue_needs_attention"
    return pd.DataFrame(
        [
            {
                "contract_name": "manual_bctc_review_queue",
                "path": str(path),
                "exists": True,
                "row_count": row_count,
                "missing_columns": _json_list(missing),
                "status": status,
                "note": note,
            }
        ],
        columns=MANUAL_COLUMNS,
    )


def build_summary(
    *,
    config: dict[str, Any],
    artifact_checklist: pd.DataFrame,
    schema_check: pd.DataFrame,
    source_check: pd.DataFrame,
    manual_check: pd.DataFrame,
    forbidden_hits: list[str],
    core_outputs_modified: bool,
) -> dict[str, Any]:
    confidence = config.get("source_confidence") or {}
    missing_artifact_count = int(artifact_checklist["status"].eq("MISSING_REQUIRED_ARTIFACT").sum()) if not artifact_checklist.empty else 0
    previous_blocked_count = int(artifact_checklist["status"].eq("PREVIOUS_STEP_BLOCKED").sum()) if not artifact_checklist.empty else 0
    schema_passed = bool(not schema_check.empty and schema_check["status"].eq("PASS").all())
    source_passed = bool(not source_check.empty and source_check["status"].eq("PASS").all())
    manual_passed = bool(not manual_check.empty and manual_check["status"].eq("PASS").all())
    if forbidden_hits:
        integration_status = "BLOCKED_FORBIDDEN_OUTPUT"
        readiness = "NOT_READY_FOR_FULL_UNIVERSE"
        final_decision = "BLOCKED_FINAL_INTEGRATION"
    elif missing_artifact_count or previous_blocked_count or core_outputs_modified:
        integration_status = "BLOCKED_MISSING_ARTIFACTS" if missing_artifact_count else "PARTIAL_INTEGRATION_ONLY"
        readiness = "NOT_READY_FOR_FULL_UNIVERSE"
        final_decision = "BLOCKED_FINAL_INTEGRATION" if missing_artifact_count or core_outputs_modified else "PASS_FINAL_INTEGRATION_WITH_WARNINGS"
    elif not source_passed:
        integration_status = "BLOCKED_CONFIDENCE_LABEL_VIOLATION"
        readiness = "NOT_READY_FOR_FULL_UNIVERSE"
        final_decision = "BLOCKED_FINAL_INTEGRATION"
    elif not schema_passed or not manual_passed:
        integration_status = "PARTIAL_INTEGRATION_ONLY"
        readiness = "NOT_READY_FOR_FULL_UNIVERSE"
        final_decision = "PASS_FINAL_INTEGRATION_WITH_WARNINGS"
    else:
        warning_decisions = artifact_checklist["final_decision"].astype(str).str.contains("WARNING|CONDITIONAL|MANUAL_REVIEW", case=False, regex=True).any()
        if warning_decisions:
            integration_status = "INTEGRATION_READY_WITH_WARNINGS"
            readiness = "READY_FOR_FULL_UNIVERSE_WITH_WARNINGS"
            final_decision = "PASS_FINAL_INTEGRATION_WITH_WARNINGS"
        else:
            integration_status = "INTEGRATION_READY_FOR_PRIMARY_ONLY_SCALE"
            readiness = "READY_FOR_FULL_UNIVERSE_PRIMARY_ONLY_RUN"
            final_decision = "PASS_FINAL_INTEGRATION_READY_FOR_PRIMARY_ONLY_SCALE"
    if integration_status not in INTEGRATION_STATUSES:
        raise ValueError(f"Invalid integration status: {integration_status}")
    if readiness not in FULL_UNIVERSE_READINESS_VALUES:
        raise ValueError(f"Invalid full-universe readiness: {readiness}")
    if final_decision not in FINAL_DECISIONS:
        raise ValueError(f"Invalid STEP24 final decision: {final_decision}")
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "mode": MODE,
        "required_artifact_count": int(len(artifact_checklist)),
        "missing_artifact_count": missing_artifact_count,
        "schema_check_passed": bool(schema_passed),
        "source_confidence_check_passed": bool(source_passed),
        "manual_review_contract_passed": bool(manual_passed),
        "forbidden_terms_found": forbidden_hits,
        "integration_status": integration_status,
        "full_universe_readiness": readiness,
        "market_source_confidence": confidence.get("market_source_confidence", "PROVISIONAL_PRIMARY_ONLY"),
        "finance_source_confidence_default": confidence.get("finance_source_confidence_default", "PROVISIONAL_LOW"),
        "crosscheck_status": confidence.get("crosscheck_status", "NOT_AVAILABLE"),
        "verification_status": confidence.get("verification_status", "NEEDS_MANUAL_BCTC_REVIEW"),
        "previous_blocked_decision_count": previous_blocked_count,
        "core_outputs_modified": bool(core_outputs_modified),
        "final_decision": final_decision,
    }


def build_run_manifest(
    *,
    config: dict[str, Any],
    config_path: Path,
    output_dir: Path,
    allow_partial: bool,
    command_used: str,
    core_outputs_modified: bool,
    missing_artifacts: list[str],
) -> dict[str, Any]:
    limits = config.get("limits") or {}
    return {
        "step_id": STEP_ID,
        "created_at": _now(),
        "commit_hash": _git_commit_hash(),
        "command_used": command_used,
        "config_path": str(config_path),
        "output_dir": str(output_dir),
        "allow_partial": bool(allow_partial),
        "full_universe_allowed": _as_bool(limits.get("full_universe_allowed", False)),
        "scale_1743_allowed": _as_bool(limits.get("scale_1743_allowed", False)),
        "network_usage_if_known": "none",
        "core_outputs_modified": bool(core_outputs_modified),
        "previous_step_outputs_mutated": bool(core_outputs_modified),
        "missing_artifacts": missing_artifacts,
    }


def write_step24_outputs(
    *,
    output_dir: Path,
    artifact_checklist: pd.DataFrame,
    schema_check: pd.DataFrame,
    source_check: pd.DataFrame,
    forbidden_check: pd.DataFrame,
    manual_check: pd.DataFrame,
    summary: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_checklist.to_csv(output_dir / "artifact_checklist.csv", index=False)
    schema_check.to_csv(output_dir / "schema_contract_check.csv", index=False)
    source_check.to_csv(output_dir / "source_confidence_check.csv", index=False)
    forbidden_check.to_csv(output_dir / "forbidden_terms_check.csv", index=False)
    manual_check.to_csv(output_dir / "manual_review_contract_check.csv", index=False)
    _write_json(output_dir / "final_integration_summary.json", summary)
    _write_json(output_dir / "run_manifest.json", manifest)
    (output_dir / "scale_readiness_report.md").write_text(
        build_scale_readiness_report(
            artifact_checklist=artifact_checklist,
            schema_check=schema_check,
            source_check=source_check,
            forbidden_check=forbidden_check,
            manual_check=manual_check,
            summary=summary,
        ),
        encoding="utf-8",
    )


def build_scale_readiness_report(
    *,
    artifact_checklist: pd.DataFrame,
    schema_check: pd.DataFrame,
    source_check: pd.DataFrame,
    forbidden_check: pd.DataFrame,
    manual_check: pd.DataFrame,
    summary: dict[str, Any],
) -> str:
    lines = [
        "# Step24 Final Integration & Scale Readiness Report",
        "",
        "## Safety Notice",
        SAFETY_NOTICE,
        "",
        "## Integration Summary",
        f"- integration_status: {summary.get('integration_status', '')}",
        f"- full_universe_readiness: {summary.get('full_universe_readiness', '')}",
        f"- final_decision: {summary.get('final_decision', '')}",
        "",
        "## Required Artifact Checklist",
        _markdown_table(artifact_checklist, ["artifact_name", "exists", "status", "final_decision"]),
        "",
        "## Schema Contract Check",
        _markdown_table(schema_check, ["artifact_name", "status", "missing_columns"]),
        "",
        "## Source Confidence Check",
        _markdown_table(source_check, ["artifact_name", "market_source_confidence", "finance_source_confidence", "crosscheck_status", "verification_status", "status"]),
        "",
        "## Manual Review Contract Check",
        _markdown_table(manual_check, ["contract_name", "exists", "row_count", "status"]),
        "",
        "## Forbidden Output Check",
        _markdown_table(forbidden_check, ["scanned_path", "status", "forbidden_terms_found"]),
        "",
        "## Evidence Debt Summary",
        "- Market confidence remains PROVISIONAL_PRIMARY_ONLY.",
        "- Finance confidence remains PROVISIONAL_LOW.",
        "- Crosscheck status remains NOT_AVAILABLE.",
        "- Verification status remains NEEDS_MANUAL_BCTC_REVIEW.",
        "",
        "## Full-Universe Primary-Only Readiness",
        f"- process_readiness: {summary.get('full_universe_readiness', '')}",
        "- This only describes pipeline operation readiness.",
        "",
        "## Remaining Risks",
        "- Independent source-family confirmation is still unavailable.",
        "- Official BCTC manual review remains required.",
        "- Current outputs remain provisional.",
        "",
        "## Next Step",
        "- Run a separately authorized primary-only scale command only after reviewing this gate.",
    ]
    return "\n".join(lines) + "\n"


def scan_forbidden_terms(output_dir: Path) -> list[str]:
    hits: list[str] = []
    if not output_dir.exists():
        return hits
    for path in sorted(output_dir.glob("*")):
        if path.suffix.lower() not in {".csv", ".json", ".md", ".txt"}:
            continue
        text = _scan_text(path)
        for line_no, line in enumerate(text.splitlines(), start=1):
            lower = line.lower()
            for term in FORBIDDEN_TERMS:
                if _term_in_text(term, lower):
                    hits.append(f"{path.name}:{line_no}:{term}")
    return hits


def _observed_confidence(summary: dict[str, Any]) -> dict[str, str]:
    market = summary.get("market_source_confidence")
    finance = summary.get("finance_source_confidence_default") or summary.get("finance_source_confidence")
    crosscheck = summary.get("crosscheck_status")
    verification = summary.get("verification_status")
    market_dist = summary.get("market_source_confidence_distribution")
    finance_dist = summary.get("finance_source_confidence_distribution")
    if _is_missing(market) and isinstance(market_dist, dict) and len(market_dist) == 1:
        market = next(iter(market_dist))
    if _is_missing(finance) and isinstance(finance_dist, dict) and len(finance_dist) == 1:
        finance = next(iter(finance_dist))
    return {
        "market_source_confidence": str(market or "UNKNOWN"),
        "finance_source_confidence": str(finance or "UNKNOWN"),
        "crosscheck_status": str(crosscheck or "UNKNOWN"),
        "verification_status": str(verification or "UNKNOWN"),
    }


def _source_status(observed: dict[str, str], expected: dict[str, Any]) -> tuple[str, str]:
    failures = []
    if observed.get("market_source_confidence") not in {expected.get("market_source_confidence"), "UNKNOWN"}:
        failures.append("market confidence label changed")
    if observed.get("finance_source_confidence") not in {expected.get("finance_source_confidence_default"), "UNKNOWN"}:
        failures.append("finance confidence label changed")
    if observed.get("crosscheck_status") not in {expected.get("crosscheck_status"), "UNKNOWN"}:
        failures.append("crosscheck status changed")
    if observed.get("verification_status") not in {expected.get("verification_status"), "UNKNOWN"}:
        failures.append("verification status changed")
    if failures:
        return "CONFIDENCE_LABEL_VIOLATION", "; ".join(failures)
    return "PASS", "provisional confidence labels preserved"


def _forbidden_hits_from_check(frame: pd.DataFrame) -> list[str]:
    hits: list[str] = []
    if frame.empty or "forbidden_terms_found" not in frame.columns:
        return hits
    for _, row in frame.iterrows():
        hits.extend(_parse_json_list(row.get("forbidden_terms_found", "")))
    return sorted(set(hits))


def _first_existing_path(spec: Any) -> Path | None:
    candidates = spec if isinstance(spec, list) else [spec]
    for candidate in candidates:
        path = Path(str(candidate))
        if path.exists():
            return path
    return None


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _read_csv(path: str | Path) -> pd.DataFrame:
    target = Path(path)
    if not target.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(target, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _json_list(values: list[Any]) -> str:
    return json.dumps([str(value) for value in values if not _is_missing(value)], ensure_ascii=False)


def _parse_json_list(value: Any) -> list[str]:
    if _is_missing(value):
        return []
    text = str(value).strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [str(item) for item in parsed if not _is_missing(item)]
        return []
    return [field.strip() for field in text.replace(";", ",").split(",") if field.strip()]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _is_missing(value: Any) -> bool:
    return value is None or str(value).strip() == "" or str(value).strip().lower() in {"nan", "none", "null", "na"}


def _term_in_text(term: str, lower_text: str) -> bool:
    if " " in term or "-" in term:
        return term in lower_text
    return re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", lower_text) is not None


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    if frame.empty:
        return "INSUFFICIENT_DATA"
    available = [column for column in columns if column in frame.columns]
    if not available:
        return "INSUFFICIENT_DATA"
    lines = ["| " + " | ".join(available) + " |", "| " + " | ".join(["---"] * len(available)) + " |"]
    for _, row in frame.reindex(columns=available).iterrows():
        values = [_clean_markdown_cell(row.get(column, "UNKNOWN")) for column in available]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def _clean_markdown_cell(value: Any) -> str:
    text = str(value)
    text = text.replace("|", "/").replace("\n", " ").strip()
    return text if text else "UNKNOWN"


def _spec_text(spec: Any) -> str:
    if isinstance(spec, list):
        return "|".join(str(item) for item in spec)
    return str(spec)


def _hashes(paths: list[Path]) -> dict[str, str]:
    return {str(path): _hash_file(path) for path in paths if path.exists()}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit_hash() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:  # noqa: BLE001
        return ""
    return completed.stdout.strip()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _scan_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() != ".json":
        return text
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(data, dict):
        data = dict(data)
        data.pop("forbidden_terms_found", None)
    return json.dumps(data, ensure_ascii=False, indent=2)
