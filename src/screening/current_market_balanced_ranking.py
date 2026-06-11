"""Rebuild balanced evidence ranking after the current market eligibility gate."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingestion.evidence_pack_policy import assign_evidence_stage
from src.screening.sector_balanced_evidence_ranker import create_balanced_ranking
from src.screening.stage2_eligibility_gate import STAGE1, STAGE2_PLUS


def build_current_market_balanced_ranking(
    ranking: pd.DataFrame,
    gate: pd.DataFrame,
    market_crosscheck: pd.DataFrame,
    finance_crosscheck: pd.DataFrame,
    balance_policy: dict[str, Any],
) -> pd.DataFrame:
    ranking = ranking.copy()
    gate_by_ticker = _index_by_ticker(gate)
    ranking["_gate_status"] = ranking["ticker"].astype(str).str.upper().map(lambda ticker: gate_by_ticker.get(ticker, {}).get("eligibility_status", "BLOCKED_MISSING_MARKET"))
    ranking["_gate_new_stage"] = ranking["ticker"].astype(str).str.upper().map(lambda ticker: gate_by_ticker.get(ticker, {}).get("new_stage", STAGE1))
    eligible = ranking[ranking["_gate_status"].eq("STAGE2_ELIGIBLE")].drop(columns=["_gate_status", "_gate_new_stage"], errors="ignore")
    ineligible = ranking[~ranking["ticker"].isin(eligible["ticker"])].copy()

    balanced_eligible = create_balanced_ranking(eligible, market_crosscheck, finance_crosscheck, balance_policy) if not eligible.empty else pd.DataFrame()
    if not balanced_eligible.empty:
        balanced_eligible["stage"] = balanced_eligible["balanced_rank"].apply(lambda rank: assign_evidence_stage({"rank": rank}))
        balanced_eligible["evidence_stage"] = balanced_eligible["stage"]
    ineligible_rows = _ineligible_rows(ineligible, gate_by_ticker, start_rank=len(balanced_eligible) + 1)
    combined = pd.concat([balanced_eligible, ineligible_rows], ignore_index=True, sort=False)
    if combined.empty:
        return combined
    combined["current_market_rank"] = range(1, len(combined) + 1)
    combined["balanced_rank"] = combined["current_market_rank"]
    combined["stage"] = combined.apply(lambda row: row.get("stage") or row.get("evidence_stage") or STAGE1, axis=1)
    combined["evidence_stage"] = combined["stage"]
    return combined


def build_current_market_balanced_summary(
    before_ranking: pd.DataFrame,
    gate: pd.DataFrame,
    after_ranking: pd.DataFrame,
    previous_queue_rows: int = 0,
    new_queue_rows: int = 0,
) -> str:
    before_stage = Counter(before_ranking.get("evidence_stage", pd.Series(dtype=str)).astype(str)) if not before_ranking.empty else {}
    after_stage = Counter(after_ranking.get("evidence_stage", pd.Series(dtype=str)).astype(str)) if not after_ranking.empty else {}
    status_counts = Counter(gate.get("eligibility_status", pd.Series(dtype=str)).astype(str)) if not gate.empty else {}
    lines = [
        "# Current Market Balanced Ranking 03",
        "",
        f"- generated_at: {datetime.now(UTC).replace(microsecond=0).isoformat()}",
        "",
        "## Stage Distribution Before Gate",
        *[f"- {stage}: {count}" for stage, count in sorted(before_stage.items())],
        "",
        "## Stage Distribution After Gate",
        *[f"- {stage}: {count}" for stage, count in sorted(after_stage.items())],
        "",
        "## Gate Counts",
        f"- number_demoted_by_missing_market: {int(status_counts.get('BLOCKED_MISSING_MARKET', 0))}",
        f"- number_demoted_by_stale_market: {int(status_counts.get('BLOCKED_STALE_MARKET', 0))}",
        f"- number_demoted_by_insufficient_trading_days: {int(status_counts.get('BLOCKED_INSUFFICIENT_TRADING_DAYS', 0))}",
        f"- number_demoted_by_missing_finance: {int(status_counts.get('BLOCKED_MISSING_MIN_FINANCE', 0))}",
        f"- number_eligible_for_stage_2_plus: {int(status_counts.get('STAGE2_ELIGIBLE', 0))}",
        "",
        "## Sector Distribution",
        f"- top_10: {_format_counter(after_ranking.head(10).get('sector_bucket', pd.Series(dtype=str)))}",
        f"- top_50: {_format_counter(after_ranking.head(50).get('sector_bucket', pd.Series(dtype=str)))}",
        f"- top_200: {_format_counter(after_ranking.head(200).get('sector_bucket', pd.Series(dtype=str)))}",
        "",
        "## Firm Type Distribution",
        f"- top_10: {_format_counter(after_ranking.head(10).get('firm_type', pd.Series(dtype=str)))}",
        f"- top_50: {_format_counter(after_ranking.head(50).get('firm_type', pd.Series(dtype=str)))}",
        f"- top_200: {_format_counter(after_ranking.head(200).get('firm_type', pd.Series(dtype=str)))}",
        "",
        "## Evidence Queue Rows",
        f"- before: {previous_queue_rows}",
        f"- after: {new_queue_rows}",
        "",
        "## Safety",
        "- Current market gate only affects evidence workload stage.",
        "- No recommendations, valuation, target price, Step19, REAL-DATA-02, official PDF fetch, or OCR was run.",
    ]
    return "\n".join(lines) + "\n"


def _ineligible_rows(ineligible: pd.DataFrame, gate_by_ticker: dict[str, dict[str, Any]], start_rank: int) -> pd.DataFrame:
    rows = []
    if ineligible.empty:
        return pd.DataFrame()
    for offset, (_, row) in enumerate(ineligible.iterrows()):
        ticker = str(row.get("ticker", "")).upper()
        gate = gate_by_ticker.get(ticker, {})
        original_stage = str(gate.get("original_stage") or row.get("evidence_stage") or "")
        new_stage = str(gate.get("new_stage") or (STAGE1 if original_stage in STAGE2_PLUS else original_stage or STAGE1))
        rows.append(
            {
                "balanced_rank": start_rank + offset,
                "raw_rank": row.get("raw_rank", row.get("rank", "")),
                "ticker": ticker,
                "exchange": row.get("exchange", ""),
                "sector_raw": row.get("sector_raw", ""),
                "sector_bucket": row.get("sector_bucket", ""),
                "firm_type": row.get("firm_type", ""),
                "raw_evidence_priority_score": row.get("raw_evidence_priority_score", row.get("evidence_priority_score", "")),
                "balanced_evidence_priority_score": row.get("balanced_evidence_priority_score", row.get("evidence_priority_score", "")),
                "liquidity_score": row.get("liquidity_score", ""),
                "data_completeness_score": row.get("data_completeness_score", ""),
                "finance_sanity_score": row.get("finance_sanity_score", ""),
                "source_coverage_score": row.get("source_coverage_score", ""),
                "market_crosscheck_status": row.get("market_crosscheck_status", ""),
                "finance_crosscheck_status": row.get("finance_crosscheck_status", "ONE_SOURCE_ONLY"),
                "balance_action": "DEMOTED_STAGE2_GATE" if original_stage in STAGE2_PLUS else row.get("balance_action", "KEPT"),
                "stage": new_stage,
                "evidence_stage": new_stage,
                "manual_review_required": True,
                "reason": f"Current market gate status={gate.get('eligibility_status', 'BLOCKED_MISSING_MARKET')}; original_stage={original_stage}; new_stage={new_stage}.",
                "eligibility_status": gate.get("eligibility_status", "BLOCKED_MISSING_MARKET"),
                "demotion_reason": gate.get("demotion_reason", gate.get("eligibility_status", "")),
            }
        )
    return pd.DataFrame(rows)


def _index_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if not isinstance(frame, pd.DataFrame) or frame.empty or "ticker" not in frame.columns:
        return {}
    out = {}
    for _, row in frame.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        if ticker:
            out[ticker] = row.to_dict()
    return out


def _format_counter(series: pd.Series) -> str:
    if series is None or series.empty:
        return "none"
    counts = Counter(series.astype(str))
    return "; ".join(f"{key}={value}" for key, value in counts.most_common()) or "none"
