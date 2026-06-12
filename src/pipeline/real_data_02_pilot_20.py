"""Controlled REAL-DATA-02 pilot readiness check for the same 20 tickers.

This module reads existing local market and provisional structured finance
outputs only. It does not fetch official PDFs, OCR documents, run Step19, or
produce investment recommendations/valuation fields.
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


DECISION_VALUES = {"PASS_FOR_STEP19_SHADOW_20", "CONDITIONAL_GO_FOR_STEP19_SHADOW_20", "NO_GO"}
MARKET_CONFIDENCE_VALUES = {"PROVISIONAL_PRIMARY", "PROVISIONAL_LOW", "PROVISIONAL_LOW_PLUS", "MANUAL_REVIEW", "MISSING"}
FINANCE_CONFIDENCE_VALUES = {"PROVISIONAL_LOW", "ONE_SOURCE_ONLY", "MISSING"}

SOURCE_LOG_COLUMNS = [
    "ticker",
    "data_category",
    "source_name",
    "source_family",
    "source_status",
    "rows_returned",
    "fields_returned",
    "missing_fields",
    "stale_flag",
    "error_message",
    "confidence_label",
]
FIELD_COVERAGE_COLUMNS = [
    "ticker",
    "data_category",
    "required_fields",
    "available_fields",
    "missing_fields",
    "coverage_ratio",
    "confidence_label",
]
FAILURE_COLUMNS = ["ticker", "data_category", "failure_type", "severity", "message"]
SCHEMA_COLUMNS = ["output_name", "required_columns", "missing_columns", "status", "severity", "message"]
READINESS_COLUMNS = [
    "ticker",
    "market_data_confidence",
    "finance_data_confidence",
    "metadata_confidence",
    "readiness_status",
    "critical_failures",
    "warnings",
    "missing_fields",
]


@dataclass
class RealData02PilotResult:
    tickers: pd.DataFrame
    source_log: pd.DataFrame
    field_coverage: pd.DataFrame
    failures: pd.DataFrame
    schema_check: pd.DataFrame
    readiness: pd.DataFrame
    decision: dict[str, Any]


def load_pilot_policy(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def run_real_data_02_pilot_20(
    *,
    input_replay_dir: str | Path,
    current_market_dir: str | Path,
    output_dir: str | Path,
    policy_path: str | Path,
    finance_long_path: str | Path,
    finance_wide_path: str | Path,
    finance_quality_path: str | Path,
    ranking_path: str | Path | None = None,
    allow_partial: bool = True,
) -> RealData02PilotResult:
    input_replay = Path(input_replay_dir)
    current_market = Path(current_market_dir)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    policy = load_pilot_policy(policy_path)
    ticker_source, ticker_list, ticker_errors = derive_pilot_tickers(input_replay, current_market)
    ticker_frame = pd.DataFrame(
        [{"ticker": ticker, "input_order": index, "input_source": ticker_source} for index, ticker in enumerate(ticker_list, start=1)],
        columns=["ticker", "input_order", "input_source"],
    )

    snapshot = _read_csv(current_market / "current_market_snapshot.csv")
    finance_long = _read_csv(finance_long_path)
    finance_wide = _read_csv(finance_wide_path)
    finance_quality = _read_csv(finance_quality_path)
    ranking = _read_csv(ranking_path) if ranking_path else _read_csv(input_replay / "replay_current_market_balanced_ranked_shortlist.csv")

    source_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    failure_rows: list[dict[str, Any]] = []
    schema_rows = _schema_checks(snapshot, finance_long, finance_wide, ranking, policy)

    for error in ticker_errors:
        failure_rows.append(_failure("", "pilot_input", "INVALID_TICKER_SET", "CRITICAL", error))

    market_snapshot = _build_market_snapshot(ticker_list, snapshot, policy, source_rows, coverage_rows, failure_rows)
    finance_snapshot = _build_finance_snapshot(ticker_list, finance_wide, finance_quality, policy, source_rows, coverage_rows, failure_rows)
    _log_structured_finance_sources(ticker_list, finance_long, policy, source_rows)
    _log_metadata_sources(ticker_list, ranking, policy, source_rows, coverage_rows, failure_rows)

    readiness = _build_readiness(ticker_list, market_snapshot, finance_snapshot, ranking, failure_rows, policy)
    source_log = pd.DataFrame(source_rows, columns=SOURCE_LOG_COLUMNS)
    field_coverage = pd.DataFrame(coverage_rows, columns=FIELD_COVERAGE_COLUMNS)
    failures = pd.DataFrame(failure_rows, columns=FAILURE_COLUMNS)
    schema_check = pd.DataFrame(schema_rows, columns=SCHEMA_COLUMNS)
    decision = _build_decision(
        ticker_list=ticker_list,
        ticker_errors=ticker_errors,
        source_log=source_log,
        failures=failures,
        schema_check=schema_check,
        readiness=readiness,
        allow_partial=allow_partial,
    )

    _write_outputs(
        output=output,
        ticker_frame=ticker_frame,
        source_log=source_log,
        field_coverage=field_coverage,
        failures=failures,
        schema_check=schema_check,
        readiness=readiness,
        decision=decision,
        market_snapshot=market_snapshot,
        finance_snapshot=finance_snapshot,
    )
    safety_hits = _forbidden_term_hits(output, policy)
    if safety_hits:
        failures = pd.concat(
            [
                failures,
                pd.DataFrame(
                    [_failure("", "safety", "FORBIDDEN_OUTPUT_TERM", "CRITICAL", "; ".join(safety_hits[:20]))],
                    columns=FAILURE_COLUMNS,
                ),
            ],
            ignore_index=True,
        )
        decision = _build_decision(
            ticker_list=ticker_list,
            ticker_errors=ticker_errors,
            source_log=source_log,
            failures=failures,
            schema_check=schema_check,
            readiness=readiness,
            allow_partial=allow_partial,
            forbidden_terms=safety_hits,
        )
        failures.to_csv(output / "real_data_02_pilot_failures.csv", index=False)
        _write_decision_and_summary(output, decision, failures, readiness)

    return RealData02PilotResult(ticker_frame, source_log, field_coverage, failures, schema_check, readiness, decision)


def derive_pilot_tickers(input_replay_dir: Path, current_market_dir: Path) -> tuple[str, list[str], list[str]]:
    candidates: list[tuple[str, list[str]]] = []
    manifest_path = input_replay_dir / "replay_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            candidates.append((str(manifest_path), [str(item).strip().upper() for item in manifest.get("pilot_tickers", [])]))
        except json.JSONDecodeError:
            candidates.append((str(manifest_path), []))
    ranking_path = input_replay_dir / "replay_current_market_balanced_ranked_shortlist.csv"
    if ranking_path.exists():
        ranking = _read_csv(ranking_path)
        candidates.append((str(ranking_path), _tickers_from_frame(ranking)))
    snapshot_path = current_market_dir / "current_market_snapshot.csv"
    if snapshot_path.exists():
        snapshot = _read_csv(snapshot_path)
        candidates.append((str(snapshot_path), _tickers_from_frame(snapshot)))
    for source, tickers in candidates:
        cleaned = [ticker for ticker in tickers if ticker]
        if cleaned:
            return source, cleaned, _ticker_set_errors(cleaned)
    return "not_found", [], ["Pilot ticker set could not be derived from 03C/03 outputs."]


def _ticker_set_errors(tickers: list[str]) -> list[str]:
    errors = []
    duplicates = sorted([ticker for ticker, count in Counter(tickers).items() if count > 1])
    if len(tickers) != 20:
        errors.append(f"Expected exactly 20 pilot tickers, got {len(tickers)}.")
    if duplicates:
        errors.append(f"Duplicate pilot tickers: {','.join(duplicates)}.")
    if len(set(tickers)) != len(tickers):
        errors.append("Pilot ticker set is not unique.")
    return errors


def _schema_checks(snapshot: pd.DataFrame, finance_long: pd.DataFrame, finance_wide: pd.DataFrame, ranking: pd.DataFrame, policy: dict[str, Any]) -> list[dict[str, Any]]:
    market_required = list(policy.get("market_minimum_fields") or [])
    finance_required = list(policy.get("finance_minimum_fields") or [])
    finance_wide_required = ["ticker", "source_name", "source_confidence", "source_layer"]
    metadata_required = ["ticker", "exchange", "sector_raw", "sector_bucket", "firm_type"]
    return [
        _schema_row("market_snapshot", market_required, snapshot),
        _schema_row("finance_long", finance_required, finance_long, critical=False),
        _schema_row("finance_snapshot_wide", finance_wide_required, finance_wide, critical=False),
        _schema_row("company_profile_or_metadata", metadata_required, ranking, critical=False),
    ]


def _schema_row(output_name: str, required: list[str], frame: pd.DataFrame, critical: bool = True) -> dict[str, Any]:
    missing = [column for column in required if column not in frame.columns]
    return {
        "output_name": output_name,
        "required_columns": ";".join(required),
        "missing_columns": ";".join(missing),
        "status": "FAIL" if missing else "PASS",
        "severity": "CRITICAL" if missing and critical else "WARN" if missing else "INFO",
        "message": "Required schema present." if not missing else "Required schema columns are missing.",
    }


def _build_market_snapshot(
    tickers: list[str],
    snapshot: pd.DataFrame,
    policy: dict[str, Any],
    source_rows: list[dict[str, Any]],
    coverage_rows: list[dict[str, Any]],
    failure_rows: list[dict[str, Any]],
) -> pd.DataFrame:
    required = list(policy.get("market_minimum_fields") or [])
    frame = _filter_tickers(snapshot, tickers)
    rows = []
    by_ticker = _index_by_ticker(frame)
    for ticker in tickers:
        row = by_ticker.get(ticker, {})
        missing_fields = [field for field in required if field not in row or _is_missing(row.get(field))]
        missing_market = _as_bool(row.get("missing_market_flag", True)) or _is_missing(row.get("last_close")) or _is_missing(row.get("last_price_date"))
        stale = _as_bool(row.get("stale_price_flag", False))
        if not row:
            status = "MISSING"
            confidence = "MISSING"
            failure_rows.append(_failure(ticker, "market_price", "MARKET_ROW_MISSING", "CRITICAL", "Primary market snapshot row missing."))
        elif missing_market:
            status = "MISSING_MARKET"
            confidence = "MISSING"
            failure_rows.append(_failure(ticker, "market_price", "MARKET_VALUE_MISSING", "CRITICAL", "Primary market values missing; no zero-fill applied."))
        elif stale:
            status = "STALE"
            confidence = "MANUAL_REVIEW"
            failure_rows.append(_failure(ticker, "market_price", "MARKET_STALE", "CRITICAL", "Primary market row is stale."))
        else:
            status = "OK"
            confidence = "PROVISIONAL_PRIMARY"
        output_row = {field: row.get(field, "") for field in required}
        output_row.update(
            {
                "market_source": row.get("market_source", "current_market_03_snapshot"),
                "market_data_confidence": confidence,
                "source_layer": "provisional_current_market",
            }
        )
        rows.append(output_row)
        source_rows.append(
            _source_row(
                ticker=ticker,
                data_category="market_price",
                source_name=row.get("market_source", "current_market_03_snapshot") if row else "current_market_03_snapshot",
                source_family="vnstock_quote_vci_history",
                source_status=status,
                rows_returned=1 if row else 0,
                fields_returned=_present_fields(row, required),
                missing_fields=missing_fields,
                stale_flag=stale,
                error_message="" if status == "OK" else status,
                confidence_label=confidence,
            )
        )
        coverage_rows.append(_coverage_row(ticker, "market_price", required, row, confidence))
    return pd.DataFrame(rows)


def _build_finance_snapshot(
    tickers: list[str],
    finance_wide: pd.DataFrame,
    finance_quality: pd.DataFrame,
    policy: dict[str, Any],
    source_rows: list[dict[str, Any]],
    coverage_rows: list[dict[str, Any]],
    failure_rows: list[dict[str, Any]],
) -> pd.DataFrame:
    required = list(policy.get("finance_snapshot_fields") or [])
    frame = _filter_tickers(finance_wide, tickers)
    quality_by_ticker = _index_by_ticker(finance_quality)
    rows = []
    by_ticker = _index_by_ticker(frame)
    for ticker in tickers:
        row = by_ticker.get(ticker, {})
        quality = quality_by_ticker.get(ticker, {})
        missing_fields = [field for field in required if field not in row or _is_missing(row.get(field))]
        present_count = len(required) - len(missing_fields)
        source_count = _to_int(row.get("source_count", 0))
        if not row or source_count == 0:
            status = "MISSING"
            confidence = "MISSING"
            failure_rows.append(_failure(ticker, "structured_finance", "FINANCE_ROW_MISSING", "WARN", "Structured finance row/source missing; no values inferred."))
        elif missing_fields:
            status = "PARTIAL"
            confidence = "PROVISIONAL_LOW"
            failure_rows.append(_failure(ticker, "structured_finance", "FINANCE_FIELD_MISSING", "WARN", f"Missing provisional finance fields: {','.join(missing_fields)}."))
        else:
            status = "OK"
            confidence = "ONE_SOURCE_ONLY"
        output_row = {
            "ticker": ticker,
            "period": row.get("period", ""),
            "period_type": row.get("period_type", ""),
            "fiscal_year": row.get("fiscal_year", ""),
            **{field: row.get(field, "") for field in required},
            "source_name": row.get("source_name", "legacy_structured_finance"),
            "source_layer": "provisional_structured",
            "finance_data_confidence": confidence,
            "finance_quality_status": quality.get("export_status", ""),
            "missing_fields": ";".join(missing_fields),
        }
        rows.append(output_row)
        source_rows.append(
            _source_row(
                ticker=ticker,
                data_category="structured_finance",
                source_name=row.get("source_name", "legacy_structured_finance") if row else "legacy_structured_finance",
                source_family="legacy_structured_cache",
                source_status=status,
                rows_returned=1 if row else 0,
                fields_returned=present_count,
                missing_fields=missing_fields,
                stale_flag=False,
                error_message="" if status == "OK" else "missing_or_partial_provisional_finance",
                confidence_label=confidence,
            )
        )
        coverage_rows.append(_coverage_row(ticker, "structured_finance", required, row, confidence))
    return pd.DataFrame(rows)


def _log_structured_finance_sources(tickers: list[str], finance_long: pd.DataFrame, policy: dict[str, Any], source_rows: list[dict[str, Any]]) -> None:
    if finance_long.empty or "ticker" not in finance_long.columns:
        return
    required = list(policy.get("finance_minimum_fields") or [])
    frame = _filter_tickers(finance_long, tickers)
    for ticker, group in frame.groupby(frame["ticker"].astype(str).str.upper()):
        missing = [field for field in required if field not in group.columns]
        source_rows.append(
            _source_row(
                ticker=ticker,
                data_category="structured_finance_long_rows",
                source_name=_first_non_missing(group.get("source_name", pd.Series(dtype=str)), "legacy_structured_finance"),
                source_family="legacy_structured_cache",
                source_status="OK" if not missing and len(group) else "PARTIAL",
                rows_returned=len(group),
                fields_returned=";".join(sorted(set(group.get("field_name", pd.Series(dtype=str)).astype(str)))) if "field_name" in group.columns else "",
                missing_fields=missing,
                stale_flag=False,
                error_message="" if not missing else "finance_long_schema_partial",
                confidence_label="ONE_SOURCE_ONLY",
            )
        )


def _log_metadata_sources(
    tickers: list[str],
    ranking: pd.DataFrame,
    policy: dict[str, Any],
    source_rows: list[dict[str, Any]],
    coverage_rows: list[dict[str, Any]],
    failure_rows: list[dict[str, Any]],
) -> None:
    required = ["ticker", "exchange", "sector_raw", "sector_bucket", "firm_type"]
    frame = _filter_tickers(ranking, tickers)
    by_ticker = _index_by_ticker(frame)
    for ticker in tickers:
        row = by_ticker.get(ticker, {})
        missing = [field for field in required if field not in row or _is_missing(row.get(field))]
        status = "OK" if row and not missing else "NOT_AVAILABLE_IN_THIS_PILOT" if not row else "PARTIAL"
        confidence = "PROVISIONAL_LOW" if status in {"OK", "PARTIAL"} else "MISSING"
        if status != "OK":
            failure_rows.append(_failure(ticker, "company_profile_or_metadata", status, "WARN", "Company metadata/profile is missing or partial in this pilot."))
        source_rows.append(
            _source_row(
                ticker=ticker,
                data_category="company_profile_or_metadata",
                source_name="current_market_balanced_ranking_03c_replay",
                source_family="provisional_ranking_metadata",
                source_status=status,
                rows_returned=1 if row else 0,
                fields_returned=_present_fields(row, required),
                missing_fields=missing,
                stale_flag=False,
                error_message="" if status == "OK" else status,
                confidence_label=confidence,
            )
        )
        coverage_rows.append(_coverage_row(ticker, "company_profile_or_metadata", required, row, confidence))


def _build_readiness(
    tickers: list[str],
    market_snapshot: pd.DataFrame,
    finance_snapshot: pd.DataFrame,
    ranking: pd.DataFrame,
    failure_rows: list[dict[str, Any]],
    policy: dict[str, Any],
) -> pd.DataFrame:
    market_by_ticker = _index_by_ticker(market_snapshot)
    finance_by_ticker = _index_by_ticker(finance_snapshot)
    failures_by_ticker: dict[str, list[dict[str, Any]]] = {ticker: [] for ticker in tickers}
    for failure in failure_rows:
        ticker = str(failure.get("ticker", "")).upper()
        if ticker in failures_by_ticker:
            failures_by_ticker[ticker].append(failure)
    rows = []
    for ticker in tickers:
        failures = failures_by_ticker.get(ticker, [])
        critical = [item for item in failures if item.get("severity") == "CRITICAL"]
        warns = [item for item in failures if item.get("severity") == "WARN"]
        market_confidence = market_by_ticker.get(ticker, {}).get("market_data_confidence", "MISSING")
        finance_confidence = finance_by_ticker.get(ticker, {}).get("finance_data_confidence", "MISSING")
        metadata_confidence = "MISSING" if any(item.get("data_category") == "company_profile_or_metadata" and item.get("failure_type") == "NOT_AVAILABLE_IN_THIS_PILOT" for item in failures) else "PROVISIONAL_LOW"
        readiness_status = "NO_GO" if critical else "CONDITIONAL_READY" if warns or finance_confidence != "ONE_SOURCE_ONLY" else "READY_FOR_SHADOW"
        rows.append(
            {
                "ticker": ticker,
                "market_data_confidence": _validated_confidence(market_confidence, MARKET_CONFIDENCE_VALUES, "MISSING"),
                "finance_data_confidence": _validated_confidence(finance_confidence, FINANCE_CONFIDENCE_VALUES, "MISSING"),
                "metadata_confidence": metadata_confidence,
                "readiness_status": readiness_status,
                "critical_failures": ";".join(item["failure_type"] for item in critical),
                "warnings": ";".join(item["failure_type"] for item in warns),
                "missing_fields": finance_by_ticker.get(ticker, {}).get("missing_fields", ""),
            }
        )
    return pd.DataFrame(rows, columns=READINESS_COLUMNS)


def _build_decision(
    *,
    ticker_list: list[str],
    ticker_errors: list[str],
    source_log: pd.DataFrame,
    failures: pd.DataFrame,
    schema_check: pd.DataFrame,
    readiness: pd.DataFrame,
    allow_partial: bool,
    forbidden_terms: list[str] | None = None,
) -> dict[str, Any]:
    forbidden_terms = forbidden_terms or []
    critical_fail_count = int(failures["severity"].eq("CRITICAL").sum()) if not failures.empty else 0
    critical_fail_count += int(schema_check["severity"].eq("CRITICAL").sum()) if not schema_check.empty else 0
    warn_count = int(failures["severity"].eq("WARN").sum()) if not failures.empty else 0
    warn_count += int(schema_check["severity"].eq("WARN").sum()) if not schema_check.empty else 0
    if ticker_errors:
        critical_fail_count += len(ticker_errors)
    if forbidden_terms and (failures.empty or not failures["failure_type"].eq("FORBIDDEN_OUTPUT_TERM").any()):
        critical_fail_count += 1
    source_failure_count = int(source_log["source_status"].isin(["ERROR", "MISSING", "MISSING_MARKET", "STALE"]).sum()) if not source_log.empty else 0
    missing_market_count = _source_status_count(source_log, "market_price", {"MISSING", "MISSING_MARKET"})
    stale_market_count = _source_status_count(source_log, "market_price", {"STALE"})
    finance_missing_count = _source_status_count(source_log, "structured_finance", {"MISSING"})
    finance_one_source_only_count = _finance_source_present_count(source_log)
    if critical_fail_count or len(set(ticker_list)) != len(ticker_list) or len(ticker_list) != 20:
        final_decision = "NO_GO"
    elif warn_count or finance_missing_count or not allow_partial:
        final_decision = "CONDITIONAL_GO_FOR_STEP19_SHADOW_20"
    else:
        final_decision = "PASS_FOR_STEP19_SHADOW_20"
    if final_decision not in DECISION_VALUES:
        raise ValueError(f"Invalid REAL-DATA-02 pilot decision: {final_decision}")
    failed_tickers = sorted(set(failures[failures["severity"].eq("CRITICAL")]["ticker"].astype(str).str.upper())) if not failures.empty else []
    failed_tickers = [ticker for ticker in failed_tickers if ticker]
    return {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "task": "REAL-DATA-02-PILOT-20",
        "pilot_ticker_count": len(ticker_list),
        "final_decision": final_decision,
        "critical_fail_count": critical_fail_count,
        "warn_count": warn_count,
        "source_failure_count": source_failure_count,
        "tickers_succeeded": len(ticker_list) - len(failed_tickers),
        "tickers_failed": len(failed_tickers),
        "failed_tickers": failed_tickers,
        "missing_market_count": missing_market_count,
        "stale_market_count": stale_market_count,
        "finance_one_source_only_count": finance_one_source_only_count,
        "finance_missing_count": finance_missing_count,
        "forbidden_terms_found": forbidden_terms,
        "allowed_next_step": "STEP19-SHADOW-20" if final_decision in {"PASS_FOR_STEP19_SHADOW_20", "CONDITIONAL_GO_FOR_STEP19_SHADOW_20"} else "Fix REAL-DATA-02-PILOT-20 issues before Step19 shadow",
        "not_authorized": [
            "top500_refresh",
            "full_universe_live_fetch",
            "official_pdf_fetch",
            "OCR",
            "valuation",
            "target_price",
            "buy_sell_hold_recommendation",
        ],
    }


def _write_outputs(
    *,
    output: Path,
    ticker_frame: pd.DataFrame,
    source_log: pd.DataFrame,
    field_coverage: pd.DataFrame,
    failures: pd.DataFrame,
    schema_check: pd.DataFrame,
    readiness: pd.DataFrame,
    decision: dict[str, Any],
    market_snapshot: pd.DataFrame,
    finance_snapshot: pd.DataFrame,
) -> None:
    ticker_frame.to_csv(output / "pilot_input_tickers.csv", index=False)
    source_log.to_csv(output / "real_data_02_pilot_source_log.csv", index=False)
    field_coverage.to_csv(output / "real_data_02_pilot_field_coverage.csv", index=False)
    failures.to_csv(output / "real_data_02_pilot_failures.csv", index=False)
    schema_check.to_csv(output / "real_data_02_pilot_schema_check.csv", index=False)
    readiness.to_csv(output / "real_data_02_pilot_readiness.csv", index=False)
    market_snapshot.to_csv(output / "real_data_02_pilot_market_snapshot.csv", index=False)
    finance_snapshot.to_csv(output / "real_data_02_pilot_finance_snapshot.csv", index=False)
    _write_decision_and_summary(output, decision, failures, readiness)


def _write_decision_and_summary(output: Path, decision: dict[str, Any], failures: pd.DataFrame, readiness: pd.DataFrame) -> None:
    (output / "real_data_02_pilot_decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "run_summary.md").write_text(build_run_summary(decision, failures, readiness), encoding="utf-8")


def build_run_summary(decision: dict[str, Any], failures: pd.DataFrame, readiness: pd.DataFrame) -> str:
    warnings = failures[failures["severity"].eq("WARN")] if not failures.empty else pd.DataFrame()
    critical = failures[failures["severity"].eq("CRITICAL")] if not failures.empty else pd.DataFrame()
    return "\n".join(
        [
            "# REAL-DATA-02-PILOT-20 Summary",
            "",
            f"- generated_at: {decision.get('generated_at', '')}",
            f"- pilot_ticker_count: {decision.get('pilot_ticker_count', 0)}",
            f"- final_decision: {decision.get('final_decision', '')}",
            f"- critical_fail_count: {decision.get('critical_fail_count', 0)}",
            f"- warn_count: {decision.get('warn_count', 0)}",
            f"- source_failure_count: {decision.get('source_failure_count', 0)}",
            f"- tickers_succeeded: {decision.get('tickers_succeeded', 0)}",
            f"- tickers_failed: {decision.get('tickers_failed', 0)}",
            f"- missing_market_count: {decision.get('missing_market_count', 0)}",
            f"- stale_market_count: {decision.get('stale_market_count', 0)}",
            f"- finance_one_source_only_count: {decision.get('finance_one_source_only_count', 0)}",
            f"- finance_missing_count: {decision.get('finance_missing_count', 0)}",
            f"- forbidden_terms_found: {len(decision.get('forbidden_terms_found', []))}",
            "",
            "## What passed",
            f"- Market rows passing readiness: {int(readiness['market_data_confidence'].eq('PROVISIONAL_PRIMARY').sum()) if not readiness.empty else 0}",
            f"- Pilot tickers retained in readiness table: {len(readiness)}",
            "- Structured finance remained provisional and was not upgraded to official verification.",
            "",
            "## Warnings",
            *_issue_lines(warnings),
            "",
            "## Failures",
            *_issue_lines(critical),
            "",
            "## Safety Boundary",
            "- This pilot only permits Step19-SHADOW-20 if final_decision is PASS or CONDITIONAL_GO.",
            "- This does not permit top-500 refresh, full-universe live fetch, official PDF fetch, OCR, valuation, target price, or recommendations.",
            "",
            "## Next Step",
            "- If PASS or CONDITIONAL_GO: STEP19-SHADOW-20.",
            "- If NO_GO: fix listed issues before Step19 shadow.",
        ]
    ) + "\n"


def _issue_lines(frame: pd.DataFrame) -> list[str]:
    if frame.empty:
        return ["- none"]
    return [f"- {row.get('ticker', '')} {row.get('data_category', '')}: {row.get('failure_type', '')} - {row.get('message', '')}" for _, row in frame.head(30).iterrows()]


def _forbidden_term_hits(output: Path, policy: dict[str, Any]) -> list[str]:
    safety = policy.get("safety", {}) or {}
    terms = [str(term).lower() for term in safety.get("forbidden_terms", [])]
    allowed = [str(item).lower() for item in safety.get("allowed_context", [])]
    hits = []
    for path in sorted(output.glob("*")):
        if path.suffix.lower() not in {".csv", ".json", ".md", ".txt"}:
            continue
        text = _scan_text(path)
        for line_no, line in enumerate(text.splitlines(), start=1):
            lower = line.lower()
            if any(marker in lower for marker in allowed):
                continue
            for term in terms:
                if term and term in lower:
                    hits.append(f"{path.name}:{line_no}:{term}")
    return hits


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
        data.pop("not_authorized", None)
    return json.dumps(data, ensure_ascii=False, indent=2)


def _source_row(
    *,
    ticker: str,
    data_category: str,
    source_name: str,
    source_family: str,
    source_status: str,
    rows_returned: int,
    fields_returned: Any,
    missing_fields: list[str],
    stale_flag: bool,
    error_message: str,
    confidence_label: str,
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "data_category": data_category,
        "source_name": source_name,
        "source_family": source_family,
        "source_status": source_status,
        "rows_returned": rows_returned,
        "fields_returned": _stringify(fields_returned),
        "missing_fields": ";".join(missing_fields),
        "stale_flag": stale_flag,
        "error_message": error_message,
        "confidence_label": confidence_label,
    }


def _coverage_row(ticker: str, category: str, required: list[str], row: dict[str, Any], confidence: str) -> dict[str, Any]:
    missing = [field for field in required if field not in row or _is_missing(row.get(field))]
    available = [field for field in required if field not in missing]
    return {
        "ticker": ticker,
        "data_category": category,
        "required_fields": ";".join(required),
        "available_fields": ";".join(available),
        "missing_fields": ";".join(missing),
        "coverage_ratio": round(len(available) / len(required), 4) if required else 1.0,
        "confidence_label": confidence,
    }


def _failure(ticker: str, data_category: str, failure_type: str, severity: str, message: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "data_category": data_category,
        "failure_type": failure_type,
        "severity": severity,
        "message": message,
    }


def _filter_tickers(frame: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame()
    ticker_set = set(tickers)
    out = frame.copy()
    out["_ticker_upper"] = out["ticker"].astype(str).str.strip().str.upper()
    out = out[out["_ticker_upper"].isin(ticker_set)].copy()
    order = {ticker: index for index, ticker in enumerate(tickers)}
    out["_order"] = out["_ticker_upper"].map(order)
    out = out.sort_values("_order").drop(columns=["_ticker_upper", "_order"], errors="ignore")
    return out.reset_index(drop=True)


def _tickers_from_frame(frame: pd.DataFrame) -> list[str]:
    if frame.empty or "ticker" not in frame.columns:
        return []
    return [ticker for ticker in frame["ticker"].astype(str).str.strip().str.upper().tolist() if ticker]


def _index_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty or "ticker" not in frame.columns:
        return {}
    out = {}
    for _, row in frame.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        if ticker and ticker not in out:
            out[ticker] = row.to_dict()
    return out


def _read_csv(path: str | Path) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame()
    target = Path(path)
    if not target.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(target, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _present_fields(row: dict[str, Any], fields: list[str]) -> int:
    return len([field for field in fields if field in row and not _is_missing(row.get(field))])


def _first_non_missing(series: pd.Series, fallback: str) -> str:
    if not isinstance(series, pd.Series) or series.empty:
        return fallback
    for value in series.astype(str):
        if value.strip():
            return value
    return fallback


def _source_status_count(source_log: pd.DataFrame, category: str, statuses: set[str]) -> int:
    if source_log.empty:
        return 0
    return int((source_log["data_category"].eq(category) & source_log["source_status"].isin(statuses)).sum())


def _finance_source_present_count(source_log: pd.DataFrame) -> int:
    if source_log.empty:
        return 0
    rows = source_log[source_log["data_category"].eq("structured_finance")].copy()
    if rows.empty:
        return 0
    returned = pd.to_numeric(rows["rows_returned"], errors="coerce").fillna(0)
    return int((returned > 0).sum())


def _validated_confidence(value: Any, allowed: set[str], fallback: str) -> str:
    text = str(value)
    return text if text in allowed else fallback


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _is_missing(value: Any) -> bool:
    return value is None or str(value).strip() == "" or str(value).strip().lower() in {"nan", "none", "null"}


def _to_int(value: Any) -> int:
    try:
        if _is_missing(value):
            return 0
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _stringify(value: Any) -> str:
    if isinstance(value, list):
        return ";".join(str(item) for item in value)
    return str(value)
