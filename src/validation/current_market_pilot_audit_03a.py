"""Pilot audit for PROVISIONAL-CURRENT-MARKET-03 outputs.

This module is intentionally read-only over the 03 outputs. It does not fetch
market data, parse official documents, or repair generated files.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


CHECK_COLUMNS = ["check_id", "area", "status", "severity", "expected", "actual", "message"]
TICKER_COLUMNS = [
    "ticker",
    "attempt_status",
    "has_snapshot",
    "last_price_date",
    "last_close",
    "avg_volume_20d",
    "avg_volume_60d",
    "trading_days_60d",
    "missing_market_flag",
    "stale_price_flag",
    "gate_eligibility_status",
    "gate_reason_codes",
    "evidence_stage_after_gate",
    "sector",
    "firm_type",
    "pilot_audit_status",
    "pilot_audit_notes",
]
MISMATCH_COLUMNS = [
    "ticker",
    "area",
    "field",
    "source_value",
    "recomputed_or_comparison_value",
    "status",
    "message",
]

VALID_STATUSES = {"PASS", "WARN", "FAIL", "SKIP"}
VALID_SEVERITIES = {"INFO", "LOW", "MEDIUM", "HIGH", "BLOCKER"}
STAGE2_PLUS = {"stage_2_evidence_candidates", "stage_3_final_watchlist", "stage_4_deep_dive_shortlist"}

REQUIRED_FILES = {
    "current_market_snapshot": "current_market_snapshot.csv",
    "current_market_refresh_attempt_log": "current_market_refresh_attempt_log.csv",
    "stage2_eligibility_gate": "stage2_eligibility_gate.csv",
    "current_market_balanced_ranked_shortlist": "current_market_balanced_ranked_shortlist.csv",
}
OPTIONAL_INPUT_FILES = {
    "current_market_refresh_summary": "current_market_refresh_summary.md",
    "stage2_eligibility_summary": "stage2_eligibility_summary.md",
    "current_market_balanced_ranking_summary": "current_market_balanced_ranking_summary.md",
}
EVIDENCE_REQUIRED_FILES = {
    "evidence_collection_queue": "evidence_collection_queue.csv",
    "evidence_run_summary": "run_summary.md",
}

SCHEMAS = {
    "current_market_snapshot": [
        "ticker",
        "fetch_status",
        "last_close",
        "last_price_date",
        "avg_volume_20d",
        "avg_volume_60d",
        "trading_days_60d",
        "missing_market_flag",
        "stale_price_flag",
    ],
    "current_market_refresh_attempt_log": ["ticker", "fetch_status", "created_at"],
    "stage2_eligibility_gate": [
        "ticker",
        "original_stage",
        "new_stage",
        "eligibility_status",
        "demotion_reason",
        "finance_crosscheck_status",
        "finance_confidence",
    ],
    "current_market_balanced_ranked_shortlist": ["ticker", "evidence_stage", "sector_bucket", "firm_type"],
    "evidence_collection_queue": ["ticker", "stage", "document_priority"],
}


@dataclass
class AuditResult:
    checks: pd.DataFrame
    ticker_level: pd.DataFrame
    mismatches: pd.DataFrame
    overall_status: str
    go_no_go: str


def load_audit_policy(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def run_pilot_audit(
    *,
    input_dir: Path | str,
    evidence_dir: Path | str,
    output_dir: Path | str,
    policy_path: Path | str,
    raw_dir: Path | str,
    strict: bool = False,
) -> AuditResult:
    input_path = Path(input_dir)
    evidence_path = Path(evidence_dir)
    raw_path = Path(raw_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    policy = load_audit_policy(policy_path)

    checks: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    frames: dict[str, pd.DataFrame] = {}
    texts: dict[str, str] = {}

    _load_inputs(input_path, evidence_path, frames, texts, checks)
    _schema_checks(frames, checks)
    _attempt_log_checks(frames.get("current_market_refresh_attempt_log", pd.DataFrame()), checks, policy)
    _snapshot_checks(frames, checks, mismatches, policy)
    _raw_recompute_checks(frames, raw_path, checks, mismatches, policy)
    _stage_gate_checks(frames, checks, mismatches)
    _balanced_ranking_checks(frames, checks, policy)
    _evidence_queue_checks(frames, checks, mismatches)
    _safety_checks(input_path, evidence_path, frames, checks, policy)

    ticker_level = build_ticker_level(frames, mismatches)
    check_frame = pd.DataFrame(checks, columns=CHECK_COLUMNS)
    mismatch_frame = pd.DataFrame(mismatches, columns=MISMATCH_COLUMNS)
    if mismatch_frame.empty:
        mismatch_frame = pd.DataFrame(columns=MISMATCH_COLUMNS)
    overall_status = _overall_status(check_frame, strict=strict)
    go_no_go = _go_no_go(check_frame, strict=strict)

    check_frame.to_csv(output_path / "pilot_audit_checks.csv", index=False)
    ticker_level.to_csv(output_path / "pilot_audit_ticker_level.csv", index=False)
    mismatch_frame.to_csv(output_path / "pilot_audit_mismatch_cases.csv", index=False)
    (output_path / "pilot_audit_summary.md").write_text(
        build_summary(
            input_dir=input_path,
            evidence_dir=evidence_path,
            checks=check_frame,
            ticker_level=ticker_level,
            mismatches=mismatch_frame,
            overall_status=overall_status,
        ),
        encoding="utf-8",
    )
    (output_path / "pilot_audit_go_no_go.md").write_text(
        build_go_no_go(go_no_go=go_no_go, checks=check_frame),
        encoding="utf-8",
    )

    return AuditResult(check_frame, ticker_level, mismatch_frame, overall_status, go_no_go)


def build_ticker_level(frames: dict[str, pd.DataFrame], mismatches: list[dict[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    attempts = frames.get("current_market_refresh_attempt_log", pd.DataFrame())
    snapshot = _index_by_ticker(frames.get("current_market_snapshot", pd.DataFrame()))
    gate = _index_by_ticker(frames.get("stage2_eligibility_gate", pd.DataFrame()))
    ranking = _index_by_ticker(frames.get("current_market_balanced_ranked_shortlist", pd.DataFrame()))
    mismatch_frame = pd.DataFrame(mismatches)
    mismatch_tickers = set(mismatch_frame["ticker"].astype(str).str.upper()) if not mismatch_frame.empty and "ticker" in mismatch_frame.columns else set()
    rows = []
    if attempts.empty or "ticker" not in attempts.columns:
        return pd.DataFrame(columns=TICKER_COLUMNS)
    for _, attempt in attempts.iterrows():
        ticker = str(attempt.get("ticker", "")).upper()
        snap = snapshot.get(ticker, {})
        gate_row = gate.get(ticker, {})
        rank = ranking.get(ticker, {})
        notes = []
        status = "PASS"
        if ticker in mismatch_tickers:
            status = "WARN"
            notes.append("mismatch_or_warning_recorded")
        if not snap:
            status = "FAIL"
            notes.append("missing_snapshot")
        if gate_row.get("eligibility_status") != "STAGE2_ELIGIBLE":
            notes.append(str(gate_row.get("eligibility_status") or "gate_status_missing"))
        rows.append(
            {
                "ticker": ticker,
                "attempt_status": attempt.get("fetch_status", ""),
                "has_snapshot": bool(snap),
                "last_price_date": snap.get("last_price_date", ""),
                "last_close": snap.get("last_close", ""),
                "avg_volume_20d": snap.get("avg_volume_20d", ""),
                "avg_volume_60d": snap.get("avg_volume_60d", ""),
                "trading_days_60d": snap.get("trading_days_60d", ""),
                "missing_market_flag": snap.get("missing_market_flag", ""),
                "stale_price_flag": snap.get("stale_price_flag", ""),
                "gate_eligibility_status": gate_row.get("eligibility_status", ""),
                "gate_reason_codes": gate_row.get("demotion_reason", ""),
                "evidence_stage_after_gate": rank.get("evidence_stage", ""),
                "sector": rank.get("sector_bucket", rank.get("sector_raw", "")),
                "firm_type": rank.get("firm_type", ""),
                "pilot_audit_status": status,
                "pilot_audit_notes": ";".join(notes),
            }
        )
    return pd.DataFrame(rows, columns=TICKER_COLUMNS)


def build_summary(
    *,
    input_dir: Path,
    evidence_dir: Path,
    checks: pd.DataFrame,
    ticker_level: pd.DataFrame,
    mismatches: pd.DataFrame,
    overall_status: str,
) -> str:
    counts = checks["status"].value_counts().to_dict() if not checks.empty else {}
    blocker_count = int(checks["severity"].eq("BLOCKER").sum()) if not checks.empty else 0
    gate_counts = ticker_level["gate_eligibility_status"].value_counts().to_dict() if not ticker_level.empty else {}
    key_findings = _key_findings(checks, mismatches)
    return "\n".join(
        [
            "# PROVISIONAL-CURRENT-MARKET-03A Pilot Audit Summary",
            "",
            f"- generated_at: {datetime.now(UTC).replace(microsecond=0).isoformat()}",
            f"- input_report_dir: {input_dir}",
            f"- evidence_report_dir: {evidence_dir}",
            f"- pilot_ticker_count: {len(ticker_level)}",
            f"- pass_count: {int(counts.get('PASS', 0))}",
            f"- warn_count: {int(counts.get('WARN', 0))}",
            f"- fail_count: {int(counts.get('FAIL', 0))}",
            f"- blocker_count: {blocker_count}",
            f"- overall_status: {overall_status}",
            "",
            "## Key Findings",
            *key_findings,
            "",
            "## Stage/Gate Consistency",
            f"- gate_status_counts: {gate_counts}",
            "- The 20-ticker pilot is intentionally not a top-500 or full-universe refresh.",
            "- Large BLOCKED_MISSING_MARKET counts outside the 20 fetched tickers mean not refreshed in pilot, not a market-data conclusion.",
            "",
            "## Evidence Queue Consistency",
            "- Evidence queue rows are checked against the gate; blocked tickers in stage_2+ are treated as BLOCKER failures.",
            "",
            "## Safety Checks",
            "- Audit does not fetch new tickers or mutate 03 outputs.",
            "- Safety keyword scan ignores explicit negative-policy lines such as no_target_price: true.",
            "- No official BCTC/PDF/OCR/Step19/REAL-DATA-02 checks are executed.",
            "",
            "## Blockers Before Next Step",
            *_blocker_lines(checks),
        ]
    ) + "\n"


def build_go_no_go(*, go_no_go: str, checks: pd.DataFrame) -> str:
    severe = checks[(checks["status"].eq("FAIL")) | (checks["severity"].eq("BLOCKER"))] if not checks.empty else pd.DataFrame()
    warnings = checks[checks["status"].eq("WARN")] if not checks.empty else pd.DataFrame()
    next_step = "PROVISIONAL-CURRENT-MARKET-03B - Market Cross-Check on Same 20 Tickers"
    lines = [
        f"# {go_no_go}",
        "",
        f"- decision: {go_no_go}",
        f"- next_allowed_step: {next_step if go_no_go in {'GO', 'CONDITIONAL_GO'} else 'Resolve audit blockers before continuing.'}",
        "",
        "## Decision Rules Applied",
        "- GO: no FAIL, no BLOCKER, warnings are absent or fully explained.",
        "- CONDITIONAL_GO: no BLOCKER but WARN items need tracking.",
        "- NO_GO: any HIGH/BLOCKER fail or critical invariant break.",
        "",
        "## Failures / Blockers",
    ]
    if severe.empty:
        lines.append("- none")
    else:
        for _, row in severe.iterrows():
            lines.append(f"- {row.get('check_id')}: {row.get('message')}")
    lines.append("")
    lines.append("## Warnings")
    if warnings.empty:
        lines.append("- none")
    else:
        for _, row in warnings.iterrows():
            lines.append(f"- {row.get('check_id')}: {row.get('message')}")
    lines.extend(
        [
            "",
            "## Safety",
            "- Do not scale to top 500 from this audit.",
            "- Do not run Step19, REAL-DATA-02, official PDF fetch, OCR, valuation, target price, or buy/sell logic.",
        ]
    )
    return "\n".join(lines) + "\n"


def _load_inputs(input_dir: Path, evidence_dir: Path, frames: dict[str, pd.DataFrame], texts: dict[str, str], checks: list[dict[str, Any]]) -> None:
    for key, filename in REQUIRED_FILES.items():
        path = input_dir / filename
        if path.exists():
            frames[key] = _read_csv(path)
            _check(checks, f"FILE_{key}", "file_existence", "PASS", "INFO", filename, "exists", "Required file exists.")
        else:
            frames[key] = pd.DataFrame()
            _check(checks, f"FILE_{key}", "file_existence", "FAIL", "HIGH", filename, "missing", "Required file is missing.")
    for key, filename in OPTIONAL_INPUT_FILES.items():
        path = input_dir / filename
        if path.exists():
            texts[key] = path.read_text(encoding="utf-8")
            _check(checks, f"FILE_{key}", "file_existence", "PASS", "INFO", filename, "exists", "Optional summary file exists.")
        else:
            _check(checks, f"FILE_{key}", "file_existence", "WARN", "LOW", filename, "missing", "Optional summary file is missing.")
    for key, filename in EVIDENCE_REQUIRED_FILES.items():
        path = evidence_dir / filename
        if path.exists():
            if filename.endswith(".csv"):
                frames[key] = _read_csv(path)
            else:
                texts[key] = path.read_text(encoding="utf-8")
            _check(checks, f"FILE_{key}", "file_existence", "PASS", "INFO", filename, "exists", "Evidence file exists.")
        else:
            frames[key] = pd.DataFrame()
            _check(checks, f"FILE_{key}", "file_existence", "FAIL", "HIGH", filename, "missing", "Evidence file is missing.")


def _schema_checks(frames: dict[str, pd.DataFrame], checks: list[dict[str, Any]]) -> None:
    for key, columns in SCHEMAS.items():
        frame = frames.get(key, pd.DataFrame())
        if frame.empty and key in REQUIRED_FILES:
            _check(checks, f"SCHEMA_{key}", "schema", "SKIP", "LOW", ",".join(columns), "empty_or_missing", "Schema skipped because file is missing or empty.")
            continue
        missing = [column for column in columns if column not in frame.columns]
        _check(
            checks,
            f"SCHEMA_{key}",
            "schema",
            "FAIL" if missing else "PASS",
            "HIGH" if missing else "INFO",
            ",".join(columns),
            ",".join(missing) if missing else "all_present",
            "Missing required columns." if missing else "Required columns present.",
        )


def _attempt_log_checks(attempts: pd.DataFrame, checks: list[dict[str, Any]], policy: dict[str, Any]) -> None:
    if attempts.empty:
        _check(checks, "ATTEMPT_LOG_NONEMPTY", "attempt_log", "FAIL", "HIGH", "non_empty", "empty", "Attempt log is empty.")
        return
    ticker_count = attempts["ticker"].astype(str).str.upper().nunique() if "ticker" in attempts.columns else 0
    expected = int(((policy.get("input_expectations") or {}).get("expected_pilot_ticker_count")) or ticker_count)
    status_counts = attempts.get("fetch_status", pd.Series(dtype=str)).astype(str).value_counts().to_dict()
    duplicate_count = int(attempts["ticker"].astype(str).str.upper().duplicated().sum()) if "ticker" in attempts.columns else 0
    timestamps = pd.to_datetime(attempts.get("created_at", pd.Series(dtype=str)), errors="coerce")
    invalid_ts = int(timestamps.isna().sum())
    _check(checks, "ATTEMPT_LOG_TICKER_COUNT", "attempt_log", "PASS", "INFO", f"pilot around {expected}", ticker_count, f"Attempt log status counts: {status_counts}")
    _check(checks, "ATTEMPT_LOG_DUPLICATES", "attempt_log", "FAIL" if duplicate_count else "PASS", "HIGH" if duplicate_count else "INFO", "0 duplicates", duplicate_count, "Duplicate ticker attempts found." if duplicate_count else "No duplicate ticker attempts.")
    _check(checks, "ATTEMPT_LOG_TIMESTAMPS", "attempt_log", "FAIL" if invalid_ts else "PASS", "MEDIUM" if invalid_ts else "INFO", "all parseable", invalid_ts, "Attempt timestamps are parseable." if not invalid_ts else "Some attempt timestamps are not parseable.")


def _snapshot_checks(frames: dict[str, pd.DataFrame], checks: list[dict[str, Any]], mismatches: list[dict[str, Any]], policy: dict[str, Any]) -> None:
    attempts = frames.get("current_market_refresh_attempt_log", pd.DataFrame())
    snapshot = frames.get("current_market_snapshot", pd.DataFrame())
    if attempts.empty or "ticker" not in attempts.columns or "fetch_status" not in attempts.columns or "ticker" not in snapshot.columns:
        _check(checks, "SNAPSHOT_CHECKS_READY", "snapshot", "SKIP", "LOW", "attempts and snapshot ticker columns", "missing", "Snapshot checks skipped due to missing inputs.")
        return
    snapshot_by_ticker = _index_by_ticker(snapshot)
    fetch_ok = attempts[attempts["fetch_status"].astype(str).eq("FETCH_OK")]
    missing_snapshot = []
    bad_rows = []
    bad_dates = []
    stale_rows = []
    for _, row in fetch_ok.iterrows():
        ticker = str(row.get("ticker", "")).upper()
        snap = snapshot_by_ticker.get(ticker)
        if not snap:
            missing_snapshot.append(ticker)
            mismatches.append(_mismatch(ticker, "snapshot", "snapshot_row", "FETCH_OK", "missing", "FAIL", "FETCH_OK ticker has no snapshot row."))
            continue
        if _is_missing(snap.get("last_close")) or _is_missing(snap.get("last_price_date")) or _as_bool(snap.get("missing_market_flag")):
            bad_rows.append(ticker)
            mismatches.append(_mismatch(ticker, "snapshot", "market_presence", "expected present", "missing", "FAIL", "FETCH_OK snapshot has missing market values."))
        if not _is_missing(snap.get("last_price_date")) and pd.to_datetime(pd.Series([snap.get("last_price_date")]), errors="coerce").isna().iloc[0]:
            bad_dates.append(ticker)
            mismatches.append(_mismatch(ticker, "snapshot", "last_price_date", "parseable date", snap.get("last_price_date"), "FAIL", "FETCH_OK snapshot has an unparseable last_price_date."))
        if _as_bool(snap.get("stale_price_flag")):
            stale_rows.append(ticker)
            mismatches.append(_mismatch(ticker, "snapshot", "stale_price_flag", "False", snap.get("stale_price_flag"), "FAIL", "FETCH_OK snapshot is stale."))
    _check(checks, "SNAPSHOT_FETCH_OK_ROWS", "snapshot", "FAIL" if missing_snapshot else "PASS", "HIGH" if missing_snapshot else "INFO", "all FETCH_OK have snapshot", len(missing_snapshot), "All FETCH_OK tickers have snapshot rows." if not missing_snapshot else f"Missing snapshot for: {','.join(missing_snapshot)}")
    _check(checks, "SNAPSHOT_MARKET_FIELDS", "snapshot", "FAIL" if bad_rows else "PASS", "HIGH" if bad_rows else "INFO", "last_close/date present and missing_market_flag false", len(bad_rows), "Snapshot market fields are present." if not bad_rows else f"Bad market fields for: {','.join(bad_rows)}")
    _check(checks, "SNAPSHOT_PRICE_DATE_PARSEABLE", "snapshot", "FAIL" if bad_dates else "PASS", "HIGH" if bad_dates else "INFO", "last_price_date parseable", len(bad_dates), "Snapshot price dates are parseable." if not bad_dates else f"Unparseable last_price_date for: {','.join(bad_dates)}")
    _check(checks, "SNAPSHOT_STALE_FLAGS", "snapshot", "FAIL" if stale_rows else "PASS", "HIGH" if stale_rows else "INFO", "stale_price_flag false for fresh pilot", len(stale_rows), "No FETCH_OK snapshot is stale." if not stale_rows else f"Stale FETCH_OK tickers: {','.join(stale_rows)}")


def _raw_recompute_checks(frames: dict[str, pd.DataFrame], raw_dir: Path, checks: list[dict[str, Any]], mismatches: list[dict[str, Any]], policy: dict[str, Any]) -> None:
    attempts = frames.get("current_market_refresh_attempt_log", pd.DataFrame())
    snapshot = frames.get("current_market_snapshot", pd.DataFrame())
    if attempts.empty or "ticker" not in attempts.columns or "fetch_status" not in attempts.columns or "ticker" not in snapshot.columns:
        _check(checks, "RAW_RECOMPUTE_READY", "raw_recompute", "SKIP", "LOW", "attempts and snapshot ticker columns", "missing", "Raw recompute skipped due to missing inputs.")
        return
    raw_policy = policy.get("raw_recompute", {})
    snapshot_by_ticker = _index_by_ticker(snapshot)
    fetch_ok = attempts[attempts["fetch_status"].astype(str).eq("FETCH_OK")]
    missing_raw = []
    mismatch_count = 0
    for _, row in fetch_ok.iterrows():
        ticker = str(row.get("ticker", "")).upper()
        history_path = raw_dir / f"{ticker}_history.csv"
        if not history_path.exists():
            missing_raw.append(ticker)
            mismatches.append(_mismatch(ticker, "raw_recompute", "raw_history", "exists", "missing", raw_policy.get("missing_raw_history_status", "WARN"), "Raw history not found; no online fetch attempted."))
            continue
        recomputed = recompute_snapshot_from_history(history_path)
        snap = snapshot_by_ticker.get(ticker, {})
        mismatch_count += _compare_recomputed(ticker, snap, recomputed, mismatches, raw_policy)
    if missing_raw:
        _check(checks, "RAW_HISTORY_PRESENT", "raw_recompute", "WARN", "LOW", "raw history for FETCH_OK", len(missing_raw), f"Raw history missing for {len(missing_raw)} tickers; no fetch attempted.")
    else:
        _check(checks, "RAW_HISTORY_PRESENT", "raw_recompute", "PASS", "INFO", "raw history for FETCH_OK", "all_present", "Raw history exists for all FETCH_OK tickers.")
    _check(checks, "RAW_RECOMPUTE_MATCH", "raw_recompute", "FAIL" if mismatch_count else "PASS", "HIGH" if mismatch_count else "INFO", "snapshot equals raw recompute", mismatch_count, "Raw recompute matches snapshot." if not mismatch_count else "Raw recompute mismatches found.")


def recompute_snapshot_from_history(history_path: Path | str) -> dict[str, Any]:
    frame = pd.read_csv(history_path, keep_default_na=False)
    date_col = _first_column(frame, ["date", "time"])
    close_col = _first_column(frame, ["close", "adjusted_close", "adj_close"])
    volume_col = _first_column(frame, ["volume", "vol"])
    if not date_col or not close_col:
        return {}
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(frame[date_col], errors="coerce"),
            "close": pd.to_numeric(frame[close_col], errors="coerce"),
            "volume": pd.to_numeric(frame[volume_col], errors="coerce") if volume_col else pd.Series(dtype=float),
        }
    ).dropna(subset=["date", "close"]).sort_values("date")
    if out.empty:
        return {}
    volumes = pd.to_numeric(out["volume"], errors="coerce").dropna()
    return {
        "last_price_date": out.iloc[-1]["date"].date().isoformat(),
        "last_close": float(out.iloc[-1]["close"]),
        "avg_volume_20d": round(float(volumes.tail(20).mean()), 4) if not volumes.empty else "",
        "avg_volume_60d": round(float(volumes.tail(60).mean()), 4) if not volumes.empty else "",
        "trading_days_60d": int(min(len(volumes), 60)),
    }


def _stage_gate_checks(frames: dict[str, pd.DataFrame], checks: list[dict[str, Any]], mismatches: list[dict[str, Any]]) -> None:
    gate = frames.get("stage2_eligibility_gate", pd.DataFrame())
    ranking = frames.get("current_market_balanced_ranked_shortlist", pd.DataFrame())
    attempts = frames.get("current_market_refresh_attempt_log", pd.DataFrame())
    if gate.empty or ranking.empty:
        _check(checks, "GATE_READY", "stage_gate", "SKIP", "LOW", "gate and ranking", "missing", "Gate checks skipped due to missing inputs.")
        return
    gate_by_ticker = _index_by_ticker(gate)
    rank_by_ticker = _index_by_ticker(ranking)
    fetch_ok = set(attempts[attempts["fetch_status"].astype(str).eq("FETCH_OK")]["ticker"].astype(str).str.upper()) if not attempts.empty and "fetch_status" in attempts.columns else set()
    missing_gate = sorted(ticker for ticker in fetch_ok if ticker not in gate_by_ticker)
    blocked_stage2 = []
    unknown_pass = []
    source_confidence_bad = []
    for ticker, row in gate_by_ticker.items():
        status = str(row.get("eligibility_status", ""))
        new_stage = str(row.get("new_stage", ""))
        if status != "STAGE2_ELIGIBLE" and new_stage in STAGE2_PLUS:
            blocked_stage2.append(ticker)
            mismatches.append(_mismatch(ticker, "stage_gate", "new_stage", status, new_stage, "FAIL", "Blocked ticker remains in stage_2+."))
        if status == "BLOCKED_UNKNOWN_EXCHANGE" and new_stage in STAGE2_PLUS:
            unknown_pass.append(ticker)
        if str(row.get("finance_crosscheck_status", "")) == "ONE_SOURCE_ONLY" and str(row.get("finance_confidence", "")) != "PROVISIONAL_LOW":
            source_confidence_bad.append(ticker)
    rank_stage_bad = []
    for ticker, row in rank_by_ticker.items():
        gate_status = str(gate_by_ticker.get(ticker, {}).get("eligibility_status", ""))
        if gate_status != "STAGE2_ELIGIBLE" and str(row.get("evidence_stage", "")) in STAGE2_PLUS:
            rank_stage_bad.append(ticker)
            mismatches.append(_mismatch(ticker, "balanced_ranking", "evidence_stage", gate_status, row.get("evidence_stage"), "FAIL", "Ranking after gate promotes blocked ticker to stage_2+."))
    _check(checks, "GATE_ROWS_MATCH_RANKING", "stage_gate", "FAIL" if len(gate) != len(ranking) else "PASS", "HIGH" if len(gate) != len(ranking) else "INFO", len(ranking), len(gate), "Gate row count matches ranking." if len(gate) == len(ranking) else "Gate row count differs from ranking.")
    _check(checks, "GATE_FETCH_OK_ROWS", "stage_gate", "FAIL" if missing_gate else "PASS", "HIGH" if missing_gate else "INFO", "FETCH_OK tickers in gate", len(missing_gate), "All FETCH_OK tickers have gate rows." if not missing_gate else f"Missing gate rows: {','.join(missing_gate)}")
    _check(checks, "GATE_BLOCKED_NOT_STAGE2_PLUS", "stage_gate", "FAIL" if blocked_stage2 else "PASS", "BLOCKER" if blocked_stage2 else "INFO", "blocked tickers demoted below stage_2", len(blocked_stage2), "Blocked tickers are not in stage_2+." if not blocked_stage2 else f"Blocked tickers still stage_2+: {','.join(blocked_stage2)}")
    _check(checks, "GATE_UNKNOWN_EXCHANGE_BLOCKED", "stage_gate", "FAIL" if unknown_pass else "PASS", "HIGH" if unknown_pass else "INFO", "UNKNOWN_EXCHANGE not stage_2+", len(unknown_pass), "Unknown exchange rows are not silently passed.")
    _check(checks, "GATE_ONE_SOURCE_LOW_CONFIDENCE", "stage_gate", "FAIL" if source_confidence_bad else "PASS", "HIGH" if source_confidence_bad else "INFO", "ONE_SOURCE_ONLY -> PROVISIONAL_LOW", len(source_confidence_bad), "ONE_SOURCE_ONLY finance remains PROVISIONAL_LOW.")
    _check(checks, "RANKING_GATE_CONSISTENCY", "balanced_ranking", "FAIL" if rank_stage_bad else "PASS", "BLOCKER" if rank_stage_bad else "INFO", "blocked tickers not stage_2+ in ranking", len(rank_stage_bad), "Ranking after gate respects eligibility gate." if not rank_stage_bad else f"Ranking promotes blocked tickers: {','.join(rank_stage_bad)}")


def _balanced_ranking_checks(frames: dict[str, pd.DataFrame], checks: list[dict[str, Any]], policy: dict[str, Any]) -> None:
    ranking = frames.get("current_market_balanced_ranked_shortlist", pd.DataFrame())
    if ranking.empty:
        _check(checks, "BALANCED_RANKING_NONEMPTY", "balanced_ranking", "FAIL", "HIGH", "non_empty", "empty", "Balanced ranking is empty.")
        return
    stage_counts = ranking["evidence_stage"].value_counts().to_dict() if "evidence_stage" in ranking.columns else {}
    _check(checks, "BALANCED_RANKING_STAGE_COUNTS", "balanced_ranking", "PASS", "INFO", "stage counts available", stage_counts, "Stage distribution after gate is available.")
    sector_ok, sector_message = _check_caps(ranking)
    _check(checks, "BALANCED_RANKING_TOP_CAPS", "balanced_ranking", "FAIL" if not sector_ok else "PASS", "HIGH" if not sector_ok else "INFO", "top caps respected", sector_message, "Top cap check completed.")


def _evidence_queue_checks(frames: dict[str, pd.DataFrame], checks: list[dict[str, Any]], mismatches: list[dict[str, Any]]) -> None:
    queue = frames.get("evidence_collection_queue", pd.DataFrame())
    gate = frames.get("stage2_eligibility_gate", pd.DataFrame())
    ranking = frames.get("current_market_balanced_ranked_shortlist", pd.DataFrame())
    if queue.empty:
        _check(checks, "EVIDENCE_QUEUE_NONEMPTY", "evidence_queue", "WARN", "LOW", "queue present", "empty", "Evidence queue is empty.")
        return
    gate_by_ticker = _index_by_ticker(gate)
    rank_by_ticker = _index_by_ticker(ranking)
    blocked = []
    non_stage = []
    for ticker in queue["ticker"].astype(str).str.upper().unique():
        gate_status = str(gate_by_ticker.get(ticker, {}).get("eligibility_status", ""))
        rank_stage = str(rank_by_ticker.get(ticker, {}).get("evidence_stage", ""))
        if gate_status != "STAGE2_ELIGIBLE":
            blocked.append(ticker)
            mismatches.append(_mismatch(ticker, "evidence_queue", "eligibility_status", "STAGE2_ELIGIBLE", gate_status, "FAIL", "Evidence queue contains ticker blocked by gate."))
        if rank_stage not in STAGE2_PLUS:
            non_stage.append(ticker)
    _check(checks, "EVIDENCE_QUEUE_GATE_ELIGIBLE", "evidence_queue", "FAIL" if blocked else "PASS", "BLOCKER" if blocked else "INFO", "queue tickers STAGE2_ELIGIBLE", len(blocked), "Evidence queue only contains gate-eligible tickers." if not blocked else f"Blocked queue tickers: {','.join(blocked)}")
    _check(checks, "EVIDENCE_QUEUE_STAGE2_PLUS", "evidence_queue", "FAIL" if non_stage else "PASS", "HIGH" if non_stage else "INFO", "queue tickers stage_2+", len(non_stage), "Evidence queue only contains stage_2+ tickers." if not non_stage else f"Queue tickers not stage_2+: {','.join(non_stage)}")


def _safety_checks(input_dir: Path, evidence_dir: Path, frames: dict[str, pd.DataFrame], checks: list[dict[str, Any]], policy: dict[str, Any]) -> None:
    forbidden = {str(item).lower() for item in (policy.get("safety_keywords", {}) or {}).get("forbidden_columns", [])}
    allowed_context = [str(item).lower() for item in (policy.get("safety_keywords", {}) or {}).get("allowed_negative_context", [])]
    column_hits = []
    text_hits = []
    for frame_name, frame in frames.items():
        if frame.empty:
            continue
        for column in frame.columns:
            normalized = str(column).strip().lower()
            if normalized in forbidden:
                column_hits.append(f"{frame_name}.{column}")
    for root in [input_dir, evidence_dir]:
        if not root.exists():
            continue
        for path in root.glob("*"):
            if path.suffix.lower() not in {".md", ".csv"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line_no, line in enumerate(text.splitlines(), start=1):
                lower = line.lower()
                if any(keyword in lower for keyword in forbidden):
                    if any(marker in lower for marker in allowed_context):
                        continue
                    if "evidence workload stage" in lower or "not investment" in lower:
                        continue
                    text_hits.append(f"{path.name}:{line_no}:{line[:80]}")
    hits = column_hits + text_hits
    _check(checks, "SAFETY_FORBIDDEN_OUTPUTS", "safety", "FAIL" if hits else "PASS", "BLOCKER" if hits else "INFO", "no recommendation/valuation fields", "; ".join(hits[:10]) if hits else "none", "No dangerous recommendation/valuation outputs found." if not hits else "Dangerous safety keywords found outside allowed negative context.")


def _compare_recomputed(ticker: str, snap: dict[str, Any], recomputed: dict[str, Any], mismatches: list[dict[str, Any]], policy: dict[str, Any]) -> int:
    if not recomputed:
        mismatches.append(_mismatch(ticker, "raw_recompute", "history_parse", "parseable", "empty", "FAIL", "Raw history could not be recomputed."))
        return 1
    mismatch_count = 0
    for field in ["last_price_date", "trading_days_60d"]:
        if str(snap.get(field, "")) != str(recomputed.get(field, "")):
            mismatch_count += 1
            mismatches.append(_mismatch(ticker, "raw_recompute", field, snap.get(field, ""), recomputed.get(field, ""), policy.get(f"{field}_mismatch_status", "FAIL"), f"{field} mismatch between snapshot and raw history."))
    close_tol = float(policy.get("last_close_tolerance", 1e-6) or 1e-6)
    if _abs_diff(snap.get("last_close"), recomputed.get("last_close")) > close_tol:
        mismatch_count += 1
        mismatches.append(_mismatch(ticker, "raw_recompute", "last_close", snap.get("last_close", ""), recomputed.get("last_close", ""), policy.get("last_close_mismatch_status", "FAIL"), "last_close mismatch between snapshot and raw history."))
    for field in ["avg_volume_20d", "avg_volume_60d"]:
        if not _within_volume_tolerance(snap.get(field), recomputed.get(field), policy):
            mismatch_count += 1
            mismatches.append(_mismatch(ticker, "raw_recompute", field, snap.get(field, ""), recomputed.get(field, ""), policy.get("avg_volume_mismatch_status", "WARN"), f"{field} mismatch between snapshot and raw history."))
    return mismatch_count


def _check_caps(ranking: pd.DataFrame) -> tuple[bool, str]:
    checks = [
        (10, "sector_bucket", 2),
        (10, "firm_type", 3),
        (50, "sector_bucket", 8),
        (50, "firm_type", 12),
        (200, "sector_bucket", 30),
        (200, "firm_type", 50),
    ]
    failures = []
    for n, column, cap in checks:
        if column not in ranking.columns:
            continue
        counts = ranking.head(n)[column].astype(str).value_counts()
        if not counts.empty and int(counts.max()) > cap and not (column == "firm_type" and counts.index[0] == "non_financial"):
            failures.append(f"top{n}.{column}.max={int(counts.max())}>cap{cap}")
    return not failures, ";".join(failures) if failures else "caps_ok"


def _overall_status(checks: pd.DataFrame, *, strict: bool) -> str:
    if checks.empty:
        return "FAIL"
    if ((checks["status"].eq("FAIL")) & (checks["severity"].isin(["HIGH", "BLOCKER"]))).any():
        return "FAIL"
    if checks["status"].eq("FAIL").any():
        return "FAIL"
    if strict and checks["status"].eq("WARN").any():
        return "FAIL"
    if checks["status"].eq("WARN").any():
        return "WARN"
    return "PASS"


def _go_no_go(checks: pd.DataFrame, *, strict: bool) -> str:
    if checks.empty:
        return "NO_GO"
    if ((checks["status"].eq("FAIL")) & (checks["severity"].isin(["HIGH", "BLOCKER"]))).any():
        return "NO_GO"
    if checks["status"].eq("FAIL").any():
        return "NO_GO"
    if strict and checks["status"].eq("WARN").any():
        return "NO_GO"
    if checks["status"].eq("WARN").any():
        return "CONDITIONAL_GO"
    return "GO"


def _key_findings(checks: pd.DataFrame, mismatches: pd.DataFrame) -> list[str]:
    if checks.empty:
        return ["- Audit could not run checks."]
    lines = []
    counts = checks["status"].value_counts().to_dict()
    lines.append(f"- check_status_counts: {counts}")
    lines.append(f"- mismatch_cases: {len(mismatches)}")
    failed = checks[checks["status"].eq("FAIL")]
    if failed.empty:
        lines.append("- No failing audit checks.")
    else:
        for _, row in failed.head(10).iterrows():
            lines.append(f"- FAIL {row.get('check_id')}: {row.get('message')}")
    return lines


def _blocker_lines(checks: pd.DataFrame) -> list[str]:
    blockers = checks[(checks["severity"].eq("BLOCKER")) | ((checks["status"].eq("FAIL")) & (checks["severity"].eq("HIGH")))]
    if blockers.empty:
        return ["- none"]
    return [f"- {row.get('check_id')}: {row.get('message')}" for _, row in blockers.iterrows()]


def _check(checks: list[dict[str, Any]], check_id: str, area: str, status: str, severity: str, expected: Any, actual: Any, message: str) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid audit status: {status}")
    if severity not in VALID_SEVERITIES:
        raise ValueError(f"Invalid audit severity: {severity}")
    checks.append(
        {
            "check_id": check_id,
            "area": area,
            "status": status,
            "severity": severity,
            "expected": expected,
            "actual": actual,
            "message": message,
        }
    )


def _mismatch(ticker: str, area: str, field: str, source_value: Any, recomputed_value: Any, status: str, message: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "area": area,
        "field": field,
        "source_value": source_value,
        "recomputed_or_comparison_value": recomputed_value,
        "status": status,
        "message": message,
    }


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _index_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if not isinstance(frame, pd.DataFrame) or frame.empty or "ticker" not in frame.columns:
        return {}
    out = {}
    for _, row in frame.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        if ticker:
            out[ticker] = row.to_dict()
    return out


def _first_column(frame: pd.DataFrame, candidates: list[str]) -> str:
    lowered = {str(column).lower(): str(column) for column in frame.columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return ""


def _within_volume_tolerance(left: Any, right: Any, policy: dict[str, Any]) -> bool:
    left_num = _to_float(left)
    right_num = _to_float(right)
    if left_num is None and right_num is None:
        return True
    if left_num is None or right_num is None:
        return False
    abs_tol = float(policy.get("avg_volume_abs_tolerance", 1) or 1)
    rel_tol = float(policy.get("avg_volume_rel_tolerance_pct", 0.01) or 0.01) / 100
    tolerance = max(abs_tol, max(abs(left_num), abs(right_num), 1.0) * rel_tol)
    return abs(left_num - right_num) <= tolerance


def _abs_diff(left: Any, right: Any) -> float:
    left_num = _to_float(left)
    right_num = _to_float(right)
    if left_num is None or right_num is None:
        return float("inf")
    return abs(left_num - right_num)


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _is_missing(value: Any) -> bool:
    return value is None or str(value).strip() == ""
