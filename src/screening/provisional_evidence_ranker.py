"""Neutral provisional evidence-priority ranking.

The score produced here is only a workload-prioritization score for official
evidence collection. It is not an investment, valuation, buy, sell, or target
price score.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingestion.evidence_pack_policy import assign_evidence_stage
from src.ingestion.legacy_structured_finance_importer import FORBIDDEN_BIAS_FIELDS


RANKING_COLUMNS = [
    "rank",
    "ticker",
    "exchange",
    "company_name",
    "sector_raw",
    "industry_raw",
    "evidence_priority_score",
    "liquidity_score",
    "data_completeness_score",
    "finance_sanity_score",
    "source_coverage_score",
    "staleness_penalty",
    "missing_data_penalty",
    "confidence_level",
    "source_count",
    "provisional_only",
    "manual_review_required",
    "reason",
    "evidence_stage",
]

MARKET_CROSSCHECK_COLUMNS = [
    "ticker",
    "legacy_last_close",
    "public_repo_last_close",
    "legacy_avg_volume_60d",
    "public_repo_avg_volume_60d",
    "price_crosscheck_status",
    "volume_crosscheck_status",
    "manual_review_required",
    "reason",
]


def run_provisional_evidence_ranking(input_dir: Path | str, output_dir: Path | str) -> dict[str, Any]:
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    finance = _read_csv(input_path / "provisional_finance_latest_wide.csv")
    market = _read_csv(input_path / "provisional_market_liquidity.csv")
    quality = _read_csv(input_path / "provisional_data_quality_flags.csv")
    crosscheck = _read_csv(input_path / "source_crosscheck_matrix.csv")

    ranking = build_provisional_evidence_ranking(finance, market, quality, crosscheck)
    ranking.to_csv(output_path / "provisional_ranked_shortlist.csv", index=False)
    pd.DataFrame(columns=MARKET_CROSSCHECK_COLUMNS).to_csv(output_path / "market_price_crosscheck.csv", index=False)

    summary = {
        "ranking_rows": int(len(ranking)),
        "stage_distribution": _value_counts(ranking, "evidence_stage"),
        "confidence_distribution": _value_counts(ranking, "confidence_level"),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    (output_path / "provisional_ranking_run_summary.md").write_text(_summary_markdown(summary), encoding="utf-8")
    return summary


def build_provisional_evidence_ranking(
    finance: pd.DataFrame,
    market: pd.DataFrame,
    quality: pd.DataFrame,
    crosscheck: pd.DataFrame,
) -> pd.DataFrame:
    finance = _strip_forbidden(finance)
    market = _strip_forbidden(market)
    quality = _strip_forbidden(quality)
    crosscheck = _strip_forbidden(crosscheck)

    tickers = _all_tickers(finance, market, quality)
    if not tickers:
        return pd.DataFrame(columns=RANKING_COLUMNS)

    finance_by_ticker = _index_by_ticker(finance)
    market_by_ticker = _index_by_ticker(market)
    quality_by_ticker = _index_by_ticker(quality)
    crosscheck_by_ticker = _crosscheck_counts(crosscheck)
    max_volume_log = _max_volume_log(market)

    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        fin = finance_by_ticker.get(ticker, {})
        mkt = market_by_ticker.get(ticker, {})
        qual = quality_by_ticker.get(ticker, {})
        identity = _identity(ticker, fin, mkt)
        completeness = _finance_completeness(fin, qual)
        liquidity = _liquidity_score(mkt, max_volume_log)
        sanity = _finance_sanity_score(fin)
        source_count = max(_to_int(fin.get("source_count")), crosscheck_by_ticker.get(ticker, 0), 1 if completeness > 0 else 0)
        source_coverage = min(source_count, 3) / 3 * 100
        stale_penalty = 10.0 if _as_bool(mkt.get("stale_price_flag")) else 0.0
        missing_penalty = _missing_data_penalty(fin, mkt, qual)
        score = _clamp(
            (0.30 * liquidity)
            + (0.35 * completeness)
            + (0.20 * sanity)
            + (0.15 * source_coverage)
            - stale_penalty
            - missing_penalty,
            0,
            100,
        )
        confidence = "PROVISIONAL_MEDIUM" if source_count >= 2 and completeness >= 75 else "PROVISIONAL_LOW"
        manual_review = source_count < 2 or missing_penalty > 0 or stale_penalty > 0 or _requires_review_from_quality(qual)
        rows.append(
            {
                **identity,
                "evidence_priority_score": round(score, 4),
                "liquidity_score": round(liquidity, 4),
                "data_completeness_score": round(completeness, 4),
                "finance_sanity_score": round(sanity, 4),
                "source_coverage_score": round(source_coverage, 4),
                "staleness_penalty": round(stale_penalty, 4),
                "missing_data_penalty": round(missing_penalty, 4),
                "confidence_level": confidence,
                "source_count": source_count,
                "provisional_only": True,
                "manual_review_required": manual_review,
                "reason": _reason(source_count, fin, mkt, qual),
            }
        )

    ranking = pd.DataFrame(rows)
    ranking = ranking.sort_values(["evidence_priority_score", "ticker"], ascending=[False, True]).reset_index(drop=True)
    ranking.insert(0, "rank", ranking.index + 1)
    ranking["evidence_stage"] = ranking.apply(lambda row: assign_evidence_stage({"rank": row["rank"]}), axis=1)
    return ranking[RANKING_COLUMNS]


def _all_tickers(*frames: pd.DataFrame) -> list[str]:
    tickers: set[str] = set()
    for frame in frames:
        if isinstance(frame, pd.DataFrame) and "ticker" in frame.columns:
            tickers.update(str(value).strip().upper() for value in frame["ticker"] if str(value).strip())
    return sorted(tickers)


def _index_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if not isinstance(frame, pd.DataFrame) or frame.empty or "ticker" not in frame.columns:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for _, row in frame.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        if ticker:
            out[ticker] = row.to_dict()
    return out


def _crosscheck_counts(frame: pd.DataFrame) -> dict[str, int]:
    if not isinstance(frame, pd.DataFrame) or frame.empty or "ticker" not in frame.columns:
        return {}
    out: dict[str, int] = {}
    for ticker, group in frame.groupby(frame["ticker"].astype(str).str.upper()):
        out[ticker] = max([_to_int(value) for value in group.get("source_count", [])] or [0])
    return out


def _identity(ticker: str, finance: dict[str, Any], market: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "exchange": _first(finance.get("exchange"), market.get("exchange")),
        "company_name": _first(finance.get("company_name"), market.get("company_name")),
        "sector_raw": _first(finance.get("sector_raw"), market.get("sector_raw")),
        "industry_raw": _first(finance.get("industry_raw"), market.get("industry_raw")),
    }


def _finance_completeness(finance: dict[str, Any], quality: dict[str, Any]) -> float:
    value = _to_float(finance.get("finance_completeness_score"))
    if value is not None:
        return _clamp(value * 100 if value <= 1 else value, 0, 100)
    field_count = _to_int(quality.get("finance_field_count"))
    return _clamp(field_count / 8 * 100, 0, 100)


def _liquidity_score(market: dict[str, Any], max_volume_log: float) -> float:
    volume = _to_float(market.get("avg_volume_60d"))
    if volume is None:
        volume = _to_float(market.get("avg_volume_20d"))
    if volume is None:
        volume = _to_float(market.get("avg_volume_10d"))
    if volume is None or volume <= 0 or max_volume_log <= 0:
        return 0.0
    return _clamp(math.log1p(volume) / max_volume_log * 100, 0, 100)


def _finance_sanity_score(finance: dict[str, Any]) -> float:
    score = 0.0
    assets = _to_float(finance.get("total_assets"))
    liabilities = _to_float(finance.get("total_liabilities"))
    equity = _to_float(finance.get("equity"))
    if assets is not None and assets > 0:
        score += 20
    if liabilities is not None:
        score += 10
    if equity is not None:
        score += 20
    if assets is not None and liabilities is not None and assets >= liabilities:
        score += 10
    if _to_float(finance.get("revenue")) is not None:
        score += 20
    if _to_float(finance.get("net_income")) is not None:
        score += 10
    if _to_float(finance.get("cfo")) is not None:
        score += 5
    if _to_float(finance.get("capex")) is not None:
        score += 5
    return _clamp(score, 0, 100)


def _missing_data_penalty(finance: dict[str, Any], market: dict[str, Any], quality: dict[str, Any]) -> float:
    missing_fields = [item for item in str(finance.get("missing_fields") or quality.get("missing_required_fields") or "").split(";") if item]
    penalty = min(len(missing_fields), 8) / 8 * 20
    if _as_bool(market.get("missing_price_flag")) or _to_float(market.get("last_close")) is None:
        penalty += 8
    if (
        _to_float(market.get("avg_volume_60d")) is None
        and _to_float(market.get("avg_volume_20d")) is None
        and _to_float(market.get("avg_volume_10d")) is None
    ):
        penalty += 7
    if _requires_review_from_quality(quality):
        penalty += 5
    return _clamp(penalty, 0, 40)


def _requires_review_from_quality(quality: dict[str, Any]) -> bool:
    status = str(quality.get("export_status", "")).strip().upper()
    return bool(status and status != "OK_FOR_PROVISIONAL_SCREEN")


def _reason(source_count: int, finance: dict[str, Any], market: dict[str, Any], quality: dict[str, Any]) -> str:
    reasons = ["Provisional evidence-priority only; not an investment score."]
    if source_count < 2:
        reasons.append("ONE_SOURCE_ONLY.")
    if finance.get("missing_fields") or quality.get("missing_required_fields"):
        reasons.append("Missing finance fields preserved.")
    if _as_bool(market.get("stale_price_flag")):
        reasons.append("Legacy price date is stale or unavailable.")
    status = str(quality.get("export_status", "")).strip()
    if status:
        reasons.append(f"legacy_export_status={status}.")
    return " ".join(reasons)


def _max_volume_log(market: pd.DataFrame) -> float:
    if not isinstance(market, pd.DataFrame) or market.empty:
        return 0.0
    volume_columns = [column for column in ["avg_volume_60d", "avg_volume_20d", "avg_volume_10d"] if column in market.columns]
    if not volume_columns:
        return 0.0
    volumes = pd.concat([pd.to_numeric(market[column], errors="coerce") for column in volume_columns]).dropna()
    volumes = volumes[volumes > 0]
    if volumes.empty:
        return 0.0
    return float(math.log1p(volumes.max()))


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, keep_default_na=False)


def _strip_forbidden(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        return pd.DataFrame()
    forbidden = [column for column in frame.columns if str(column).strip().lower() in FORBIDDEN_BIAS_FIELDS]
    return frame.drop(columns=forbidden, errors="ignore").copy()


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _to_int(value: Any) -> int:
    number = _to_float(value)
    return int(number) if number is not None else 0


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _first(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _value_counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if not isinstance(frame, pd.DataFrame) or frame.empty or column not in frame.columns:
        return {}
    counts = Counter(frame[column].astype(str))
    return dict(sorted((key, int(value)) for key, value in counts.items()))


def _summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Provisional Evidence Ranking 01",
        "",
        f"- ranking_rows: {summary['ranking_rows']}",
        "",
        "## Evidence Stage Distribution",
    ]
    for stage, count in summary["stage_distribution"].items():
        lines.append(f"- {stage}: {count}")
    lines.append("")
    lines.append("## Confidence Distribution")
    for confidence, count in summary["confidence_distribution"].items():
        lines.append(f"- {confidence}: {count}")
    lines.extend(
        [
            "",
            "## Safety",
            "- evidence_priority_score is a neutral workload-prioritization score only.",
            "- No buy/sell recommendation, target price, fair value, margin of safety, or investment score is produced.",
            "- Missing values were not inferred or zero-filled.",
            "- Legacy structured finance remains provisional_structured, not official verified BCTC.",
            "",
            f"_Generated at {summary['generated_at']}._",
        ]
    )
    return "\n".join(lines) + "\n"
