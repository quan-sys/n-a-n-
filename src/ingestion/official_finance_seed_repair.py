"""REAL-DATA-01I-D official finance seed repair reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd

from src.ingestion.official_finance_document_seed import SEED_COLUMNS, load_document_seed_csv
from src.ingestion.official_finance_link_extractor import (
    LINK_CANDIDATE_COLUMNS,
    extract_link_candidates_from_snapshot,
    infer_candidate_document_type,
    infer_period_guess,
    normalize_text,
)


BAD_SEED_URL_REPORT_COLUMNS = [
    "ticker",
    "seed_url",
    "seed_scheme",
    "final_url",
    "final_scheme",
    "http_status",
    "download_status",
    "bad_seed_reason",
    "manual_review_required",
    "notes",
]

DISCOVERY_STATUS_COLUMNS = [
    "ticker",
    "initial_seed_rows",
    "html_snapshots",
    "blocked_or_failed",
    "high_confidence_candidates",
    "reviewable_candidates",
    "low_confidence_candidates",
    "rejected_candidates",
    "https_candidates",
    "http_candidates",
    "best_candidate_score",
    "best_candidate_url",
    "discovery_status",
    "notes",
]

REPAIR_MANUAL_REVIEW_COLUMNS = [
    "ticker",
    "period",
    "document_type",
    "source_url",
    "candidate_url",
    "issue",
    "manual_review_required",
    "priority",
    "notes",
]


def run_official_finance_seed_repair_01id(
    *,
    seed_file: str | Path,
    index_file: str | Path,
    raw_snapshot_dir: str | Path,
    output_dir: str | Path,
    min_reviewable_score: int = 50,
    min_high_confidence_score: int = 80,
    target_years: list[str] | None = None,
    target_periods: list[str] | None = None,
    https_first: bool = True,
    previous_candidates_file: str | Path | None = None,
) -> dict[str, pd.DataFrame]:
    seed_df = load_document_seed_csv(seed_file)
    index_df = pd.read_csv(index_file, keep_default_na=False)
    target_years = target_years or ["2026", "2025"]
    target_periods = target_periods or ["2026-Q1", "2025-Q4", "2025"]

    candidates = build_link_candidates(
        index_df=index_df,
        raw_snapshot_dir=raw_snapshot_dir,
        target_years=target_years,
        target_periods=target_periods,
        min_reviewable_score=min_reviewable_score,
        min_high_confidence_score=min_high_confidence_score,
    )
    bad_seed = build_bad_seed_url_report(index_df=index_df, target_years=target_years)
    refined = build_refined_seed_candidates(
        seed_df=seed_df,
        candidates=candidates,
        min_reviewable_score=min_reviewable_score,
        patch_label=_patch_label(output_dir),
    )
    status_by_ticker = build_document_discovery_status_by_ticker(
        seed_df=seed_df,
        index_df=index_df,
        candidates=candidates,
    )
    manual_review = build_manual_review_queue(
        seed_df=seed_df,
        candidates=candidates,
        bad_seed=bad_seed,
        status_by_ticker=status_by_ticker,
    )

    resolved_output_dir = Path(output_dir)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    patch_label = _patch_label(resolved_output_dir)
    refined_filename = "refined_seed_candidates_01id_patch1.csv" if patch_label == "01id_patch1" else "refined_seed_candidates_01id.csv"
    previous_candidates = _load_previous_candidates(previous_candidates_file)
    candidates.to_csv(resolved_output_dir / "official_document_link_candidates.csv", index=False)
    refined.to_csv(resolved_output_dir / refined_filename, index=False)
    bad_seed.to_csv(resolved_output_dir / "bad_seed_url_report.csv", index=False)
    manual_review.to_csv(resolved_output_dir / "manual_review_queue.csv", index=False)
    status_by_ticker.to_csv(resolved_output_dir / "document_discovery_status_by_ticker.csv", index=False)
    (resolved_output_dir / "official_finance_document_01id_run_summary.md").write_text(
        build_01id_run_summary_markdown(
            seed_df=seed_df,
            index_df=index_df,
            candidates=candidates,
            bad_seed=bad_seed,
            manual_review=manual_review,
            status_by_ticker=status_by_ticker,
            https_first=https_first,
        ),
        encoding="utf-8",
    )
    (resolved_output_dir / "datasource_decision_report.md").write_text(
        build_01id_decision_report_markdown(candidates=candidates),
        encoding="utf-8",
    )
    (resolved_output_dir / "candidate_scoring_calibration_report.md").write_text(
        build_candidate_scoring_calibration_report(
            before_candidates=previous_candidates,
            after_candidates=candidates,
        ),
        encoding="utf-8",
    )

    return {
        "official_document_link_candidates": candidates,
        refined_filename.removesuffix(".csv"): refined,
        "refined_seed_candidates_01id": refined,
        "bad_seed_url_report": bad_seed,
        "manual_review_queue": manual_review,
        "document_discovery_status_by_ticker": status_by_ticker,
    }


def build_link_candidates(
    *,
    index_df: pd.DataFrame,
    raw_snapshot_dir: str | Path,
    target_years: list[str],
    target_periods: list[str],
    min_reviewable_score: int,
    min_high_confidence_score: int,
) -> pd.DataFrame:
    frames = []
    for _, row in index_df.iterrows():
        local_path = _clean_text(row.get("local_path"))
        if not local_path:
            continue
        path = Path(local_path)
        if not path.is_absolute():
            path = Path(local_path)
        if not path.exists():
            path = Path(raw_snapshot_dir) / Path(local_path).name
        if not path.exists():
            continue
        if _clean_text(row.get("detected_file_type")) != "html":
            continue
        frame = extract_link_candidates_from_snapshot(
            ticker=row.get("ticker", ""),
            source_page_url=_clean_text(row.get("final_url")) or _clean_text(row.get("source_url")),
            source_snapshot_path=path,
            official_domain=row.get("official_domain", ""),
            source_download_status=row.get("download_status", ""),
            target_years=target_years,
            target_periods=target_periods,
            min_high_confidence_score=min_high_confidence_score,
            min_reviewable_score=min_reviewable_score,
        )
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=LINK_CANDIDATE_COLUMNS)
    return pd.concat(frames, ignore_index=True)[LINK_CANDIDATE_COLUMNS]


def build_refined_seed_candidates(
    *,
    seed_df: pd.DataFrame,
    candidates: pd.DataFrame,
    min_reviewable_score: int = 50,
    patch_label: str = "01id",
) -> pd.DataFrame:
    if not isinstance(candidates, pd.DataFrame) or candidates.empty:
        return pd.DataFrame(columns=SEED_COLUMNS)
    seed_by_ticker = {
        str(row.get("ticker", "")).upper(): row
        for _, row in seed_df.iterrows()
    }
    rows = []
    selected = candidates[
        candidates["score_band"].isin(["HIGH_CONFIDENCE_CANDIDATE", "REVIEWABLE_CANDIDATE"])
        & (candidates["candidate_is_https"].astype(bool))
        & (~candidates["reason"].astype(str).str.contains("DOMAIN_MISMATCH|ERROR_OR_404_PAGE|OLD_YEAR_ONLY|JS_OR_BLOCKED", regex=True))
        & (candidates["score"].astype(int) >= min_reviewable_score)
    ].copy()
    selected = selected.sort_values(["ticker", "score", "candidate_url"], ascending=[True, False, True])
    for _, candidate in selected.iterrows():
        seed_row = seed_by_ticker.get(str(candidate["ticker"]).upper())
        if seed_row is None:
            continue
        extension = _expected_file_type(candidate.get("file_extension"))
        combined_text = f"{candidate.get('candidate_url', '')} {candidate.get('anchor_text', '')} {candidate.get('reason', '')}"
        document_type = infer_candidate_document_type(combined_text)
        consolidated_status = _infer_consolidated_status(combined_text, seed_row.get("consolidated_status", "unknown"))
        notes = (
            "01ID_PATCH1_CANDIDATE_NOT_FINANCE_EVIDENCE_YET; HTTPS and official domain checked, finance numbers not parsed"
            if patch_label == "01id_patch1"
            else "01ID_CANDIDATE_NOT_FINANCE_EVIDENCE_YET; HTTPS and official domain checked, finance numbers not parsed"
        )
        if consolidated_status == "standalone":
            notes = f"{notes}; standalone/rieng candidate requires manual review"
        rows.append(
            {
                "ticker": candidate["ticker"],
                "exchange": seed_row.get("exchange", "UNKNOWN"),
                "company_name": seed_row.get("company_name", ""),
                "period": candidate.get("period_guess") or infer_period_guess(combined_text),
                "document_type": document_type,
                "source_type": seed_row.get("source_type", "company_ir"),
                "source_name": f"{seed_row.get('source_name', '')} {patch_label.upper()} candidate".strip(),
                "source_url": candidate["candidate_url"],
                "official_domain": candidate["official_domain"],
                "expected_file_type": extension,
                "consolidated_status": consolidated_status,
                "language": seed_row.get("language", "unknown"),
                "confidence_seed": "medium" if candidate["score_band"] == "HIGH_CONFIDENCE_CANDIDATE" else "low",
                "notes": notes,
            }
        )
    return pd.DataFrame(rows, columns=SEED_COLUMNS).drop_duplicates(subset=["ticker", "period", "document_type", "source_url"])


def build_bad_seed_url_report(*, index_df: pd.DataFrame, target_years: list[str]) -> pd.DataFrame:
    rows = []
    for _, row in index_df.iterrows():
        reasons = bad_seed_reasons(row.to_dict(), target_years=target_years)
        if not reasons:
            continue
        seed_url = _clean_text(row.get("source_url"))
        final_url = _clean_text(row.get("final_url"))
        rows.append(
            {
                "ticker": row.get("ticker", ""),
                "seed_url": seed_url,
                "seed_scheme": urlparse(seed_url).scheme,
                "final_url": final_url,
                "final_scheme": urlparse(final_url).scheme,
                "http_status": row.get("http_status", ""),
                "download_status": row.get("download_status", ""),
                "bad_seed_reason": ";".join(reasons),
                "manual_review_required": True,
                "notes": "bad seed URL does not prove clean finance evidence",
            }
        )
    return pd.DataFrame(rows, columns=BAD_SEED_URL_REPORT_COLUMNS)


def bad_seed_reasons(row: dict[str, Any], *, target_years: list[str]) -> list[str]:
    reasons = []
    seed_url = _clean_text(row.get("source_url"))
    final_url = _clean_text(row.get("final_url"))
    seed_scheme = urlparse(seed_url).scheme
    final_scheme = urlparse(final_url).scheme
    status = _clean_text(row.get("download_status"))
    http_status = _clean_text(row.get("http_status"))
    combined = normalize_text(f"{seed_url} {final_url} {row.get('notes', '')}")
    if seed_scheme == "http" and final_scheme != "https":
        reasons.append("HTTP_NOT_REDIRECTED_TO_HTTPS")
    if http_status == "404":
        reasons.append("HTTP_404")
    if http_status == "403":
        reasons.append("HTTP_403")
    if http_status.startswith("5"):
        reasons.append("HTTP_500")
    if status == "SOURCE_BLOCKED_OR_JS_REQUIRED":
        reasons.append("JS_OR_BLOCKED")
    if status in {"SOURCE_UNAVAILABLE", "SOURCE_CONTENT_TYPE_UNSUPPORTED", "DOWNLOAD_FAILED"} and http_status not in {"403", "404"} and not http_status.startswith("5"):
        reasons.append("SOURCE_UNAVAILABLE")
    if _url_has_error(final_url) and http_status == "200":
        reasons.append("ERROR_PAGE_200")
    if not _domain_matches(_domain(final_url or seed_url), _clean_text(row.get("official_domain"))):
        reasons.append("DOMAIN_MISMATCH")
    if "tin tuc" in combined or "news" in combined or "bai viet" in combined:
        if not any(keyword in combined for keyword in ["bao cao tai chinh", "bctc", "financial", "annual report", "bao cao thuong nien"]):
            reasons.append("GENERIC_NEWS_PAGE")
    years = [value for value in __import__("re").findall(r"\b20\d{2}\b", combined)]
    if years and not any(year in target_years for year in years):
        reasons.append("OLD_YEAR_REDIRECT")
    if status == "HTML_SNAPSHOT_SAVED" and not any(keyword in combined for keyword in ["bao cao", "bctc", "financial", "annual", "report", "nha dau tu", "investor", "co dong"]):
        reasons.append("NO_FINANCE_KEYWORDS")
    return _dedupe(reasons)


def build_document_discovery_status_by_ticker(
    *,
    seed_df: pd.DataFrame,
    index_df: pd.DataFrame,
    candidates: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    all_tickers = sorted({str(ticker).upper() for ticker in seed_df["ticker"]})
    for ticker in all_tickers:
        seed_rows = seed_df[seed_df["ticker"].astype(str).str.upper() == ticker]
        index_rows = index_df[index_df["ticker"].astype(str).str.upper() == ticker]
        candidate_rows = candidates[candidates["ticker"].astype(str).str.upper() == ticker] if not candidates.empty else pd.DataFrame(columns=LINK_CANDIDATE_COLUMNS)
        status_counts = candidate_rows["score_band"].value_counts().to_dict() if not candidate_rows.empty else {}
        high = int(status_counts.get("HIGH_CONFIDENCE_CANDIDATE", 0))
        reviewable = int(status_counts.get("REVIEWABLE_CANDIDATE", 0))
        low = int(status_counts.get("LOW_CONFIDENCE_CANDIDATE", 0))
        rejected = int(status_counts.get("REJECTED_CANDIDATE", 0))
        https = int(candidate_rows["candidate_is_https"].astype(bool).sum()) if not candidate_rows.empty else 0
        http = int(len(candidate_rows) - https)
        best_score = int(candidate_rows["score"].max()) if not candidate_rows.empty else 0
        best_url = ""
        if not candidate_rows.empty:
            best_url = str(candidate_rows.sort_values(["score", "candidate_url"], ascending=[False, True]).iloc[0]["candidate_url"])
        if high:
            discovery_status = "HAS_HIGH_CONFIDENCE_DOCUMENT_CANDIDATE"
        elif reviewable:
            discovery_status = "HAS_REVIEWABLE_CANDIDATE"
        elif low:
            discovery_status = "ONLY_LOW_CONFIDENCE_CANDIDATES"
        elif int(index_rows["download_status"].isin(["SOURCE_BLOCKED_OR_JS_REQUIRED", "SOURCE_UNAVAILABLE"]).sum()) == len(index_rows):
            discovery_status = "BLOCKED_OR_FAILED"
        elif candidate_rows.empty:
            discovery_status = "NO_CANDIDATES"
        else:
            discovery_status = "NEEDS_MANUAL_SEARCH"
        rows.append(
            {
                "ticker": ticker,
                "initial_seed_rows": int(len(seed_rows)),
                "html_snapshots": int((index_rows["download_status"] == "HTML_SNAPSHOT_SAVED").sum()),
                "blocked_or_failed": int(index_rows["download_status"].isin(["SOURCE_BLOCKED_OR_JS_REQUIRED", "SOURCE_UNAVAILABLE"]).sum()),
                "high_confidence_candidates": high,
                "reviewable_candidates": reviewable,
                "low_confidence_candidates": low,
                "rejected_candidates": rejected,
                "https_candidates": https,
                "http_candidates": http,
                "best_candidate_score": best_score,
                "best_candidate_url": best_url,
                "discovery_status": discovery_status,
                "notes": "document candidates only; finance numbers not parsed",
            }
        )
    return pd.DataFrame(rows, columns=DISCOVERY_STATUS_COLUMNS)


def build_manual_review_queue(
    *,
    seed_df: pd.DataFrame,
    candidates: pd.DataFrame,
    bad_seed: pd.DataFrame,
    status_by_ticker: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    for _, row in bad_seed.iterrows():
        rows.append(_review_row(row.get("ticker"), "", "", row.get("seed_url"), "", row.get("bad_seed_reason"), "high", row.get("notes")))
    if not candidates.empty:
        review_candidates = candidates[candidates["manual_review_required"].astype(bool)]
        for _, row in review_candidates.iterrows():
            rows.append(_review_row(row.get("ticker"), row.get("period_guess"), row.get("candidate_document_type"), row.get("source_page_url"), row.get("candidate_url"), row.get("reason"), "medium", row.get("notes")))
    for _, row in status_by_ticker.iterrows():
        if row["discovery_status"] in {"NO_CANDIDATES", "BLOCKED_OR_FAILED", "NEEDS_MANUAL_SEARCH"}:
            rows.append(_review_row(row.get("ticker"), "DISCOVERY", "", "", row.get("best_candidate_url"), row.get("discovery_status"), "high", row.get("notes")))
    return pd.DataFrame(rows, columns=REPAIR_MANUAL_REVIEW_COLUMNS).drop_duplicates()


def build_01id_run_summary_markdown(
    *,
    seed_df: pd.DataFrame,
    index_df: pd.DataFrame,
    candidates: pd.DataFrame,
    bad_seed: pd.DataFrame,
    manual_review: pd.DataFrame,
    status_by_ticker: pd.DataFrame,
    https_first: bool,
) -> str:
    bands = _counts(candidates, "score_band")
    statuses = _counts(index_df, "download_status")
    bad_reasons = _split_counts(bad_seed, "bad_seed_reason")
    return "\n".join(
        [
            "# REAL-DATA-01I-D official seed repair run",
            "",
            f"- seed rows: {len(seed_df)}",
            f"- unique tickers: {seed_df['ticker'].nunique()}",
            f"- html snapshots: {statuses.get('HTML_SNAPSHOT_SAVED', 0)}",
            f"- blocked/js: {statuses.get('SOURCE_BLOCKED_OR_JS_REQUIRED', 0)}",
            f"- failed: {statuses.get('SOURCE_UNAVAILABLE', 0)}",
            f"- candidates extracted: {len(candidates)}",
            f"- https candidates: {int(candidates['candidate_is_https'].astype(bool).sum()) if not candidates.empty else 0}",
            f"- http candidates: {int((~candidates['candidate_is_https'].astype(bool)).sum()) if not candidates.empty else 0}",
            f"- high confidence candidates: {bands.get('HIGH_CONFIDENCE_CANDIDATE', 0)}",
            f"- reviewable candidates: {bands.get('REVIEWABLE_CANDIDATE', 0)}",
            f"- low confidence candidates: {bands.get('LOW_CONFIDENCE_CANDIDATE', 0)}",
            f"- rejected candidates: {bands.get('REJECTED_CANDIDATE', 0)}",
            f"- bad seed rows: {len(bad_seed)}",
            f"- manual review rows: {len(manual_review)}",
            f"- https_first_policy_ready: {bool(https_first)}",
            "",
            "## Top bad seed reasons",
            _format_counts(bad_reasons),
            "",
            "No finance values were parsed. HTTPS links remain document candidates only.",
        ]
    )


def build_01id_decision_report_markdown(*, candidates: pd.DataFrame) -> str:
    good = 0 if candidates.empty else int(candidates["score_band"].isin(["HIGH_CONFIDENCE_CANDIDATE", "REVIEWABLE_CANDIDATE"]).sum())
    candidate_ready = "Partial" if good else "False"
    return "\n".join(
        [
            "# Datasource decision report",
            "",
            "- official_document_seed_ready: Partial",
            "- official_document_download_ready: Partial",
            f"- official_link_candidate_ready: {candidate_ready}",
            "- https_first_policy_ready: True",
            "- finance_parse_ready: False",
            "- finance_ready_for_l0: unchanged",
            "- should_run_REAL_DATA_02: No",
            "- should_implement_Step19_now: No",
            "",
            "01I-D repairs official document discovery only. HTTPS, official domain, and snapshots do not confirm finance values.",
        ]
    )


def build_candidate_scoring_calibration_report(
    *,
    before_candidates: pd.DataFrame,
    after_candidates: pd.DataFrame,
) -> str:
    before_counts = _counts(before_candidates, "score_band")
    after_counts = _counts(after_candidates, "score_band")
    before_good = _good_candidate_rows(before_candidates)
    after_good = _good_candidate_rows(after_candidates)
    promoted = _promoted_candidates(before_candidates, after_candidates)
    tickers_good = sorted(after_good["ticker"].astype(str).str.upper().unique().tolist()) if not after_good.empty else []
    lines = [
        "# Candidate scoring calibration report",
        "",
        "## Before vs after",
        f"- candidates extracted: {len(before_candidates)} -> {len(after_candidates)}",
        f"- high confidence candidates: {before_counts.get('HIGH_CONFIDENCE_CANDIDATE', 0)} -> {after_counts.get('HIGH_CONFIDENCE_CANDIDATE', 0)}",
        f"- reviewable candidates: {before_counts.get('REVIEWABLE_CANDIDATE', 0)} -> {after_counts.get('REVIEWABLE_CANDIDATE', 0)}",
        f"- low confidence candidates: {before_counts.get('LOW_CONFIDENCE_CANDIDATE', 0)} -> {after_counts.get('LOW_CONFIDENCE_CANDIDATE', 0)}",
        f"- rejected candidates: {before_counts.get('REJECTED_CANDIDATE', 0)} -> {after_counts.get('REJECTED_CANDIDATE', 0)}",
        f"- tickers with high/reviewable candidates: {len(tickers_good)} ({', '.join(tickers_good) if tickers_good else 'none'})",
        "",
        "## Promoted candidates",
    ]
    if promoted.empty:
        lines.append("- none")
    else:
        for _, row in promoted.sort_values(["ticker", "new_score", "candidate_url"], ascending=[True, False, True]).iterrows():
            lines.extend(
                [
                    f"- ticker: {row['ticker']}",
                    f"  old score: {row['old_score']}",
                    f"  new score: {row['new_score']}",
                    f"  score band: {row['new_score_band']}",
                    f"  candidate_url: {row['candidate_url']}",
                    f"  reason codes: {row['reason']}",
                    f"  manual_review_required: {row['manual_review_required']}",
                ]
            )
    lines.extend(
        [
            "",
            "No finance values were parsed. Calibrated candidates remain discovery evidence only.",
        ]
    )
    return "\n".join(lines)


def _review_row(ticker: Any, period: Any, document_type: Any, source_url: Any, candidate_url: Any, issue: Any, priority: str, notes: Any) -> dict[str, Any]:
    return {
        "ticker": _clean_text(ticker).upper(),
        "period": _clean_text(period),
        "document_type": _clean_text(document_type),
        "source_url": _clean_text(source_url),
        "candidate_url": _clean_text(candidate_url),
        "issue": _clean_text(issue),
        "manual_review_required": True,
        "priority": priority,
        "notes": _clean_text(notes),
    }


def _expected_file_type(extension: Any) -> str:
    ext = _clean_text(extension).lower()
    return ext if ext in {"pdf", "xlsx", "xls", "html"} else "unknown"


def _infer_consolidated_status(value: str, fallback: Any) -> str:
    normalized = normalize_text(value)
    if "hop nhat" in normalized or "consolidated" in normalized:
        return "consolidated"
    if "rieng" in normalized or "standalone" in normalized or "cong ty me" in normalized or "cty me" in normalized:
        return "standalone"
    fallback_text = _clean_text(fallback).lower()
    return fallback_text if fallback_text in {"consolidated", "standalone", "unknown"} else "unknown"


def _patch_label(output_dir: str | Path) -> str:
    text = str(output_dir).replace("\\", "/").lower()
    return "01id_patch1" if "01id_patch1" in text else "01id"


def _load_previous_candidates(previous_candidates_file: str | Path | None) -> pd.DataFrame:
    candidates_path = Path(previous_candidates_file) if previous_candidates_file else Path("data/reports/official_finance_documents_01id/official_document_link_candidates.csv")
    if not candidates_path.exists():
        return pd.DataFrame(columns=LINK_CANDIDATE_COLUMNS)
    return pd.read_csv(candidates_path, keep_default_na=False)


def _good_candidate_rows(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame) or df.empty or "score_band" not in df.columns:
        return pd.DataFrame(columns=df.columns if isinstance(df, pd.DataFrame) else LINK_CANDIDATE_COLUMNS)
    return df[df["score_band"].isin(["HIGH_CONFIDENCE_CANDIDATE", "REVIEWABLE_CANDIDATE"])].copy()


def _promoted_candidates(before_candidates: pd.DataFrame, after_candidates: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "ticker",
        "candidate_url",
        "old_score",
        "new_score",
        "old_score_band",
        "new_score_band",
        "reason",
        "manual_review_required",
    ]
    if not isinstance(after_candidates, pd.DataFrame) or after_candidates.empty:
        return pd.DataFrame(columns=columns)
    before_lookup = {}
    if isinstance(before_candidates, pd.DataFrame) and not before_candidates.empty:
        for _, row in before_candidates.iterrows():
            key = (_clean_text(row.get("ticker")).upper(), _clean_text(row.get("candidate_url")))
            before_lookup[key] = row
    rows = []
    for _, row in after_candidates.iterrows():
        new_band = _clean_text(row.get("score_band"))
        if new_band not in {"HIGH_CONFIDENCE_CANDIDATE", "REVIEWABLE_CANDIDATE"}:
            continue
        key = (_clean_text(row.get("ticker")).upper(), _clean_text(row.get("candidate_url")))
        old = before_lookup.get(key)
        old_band = _clean_text(old.get("score_band")) if old is not None else ""
        old_score = _clean_text(old.get("score")) if old is not None else ""
        if old_band in {"HIGH_CONFIDENCE_CANDIDATE", "REVIEWABLE_CANDIDATE"}:
            continue
        rows.append(
            {
                "ticker": key[0],
                "candidate_url": key[1],
                "old_score": old_score,
                "new_score": row.get("score", ""),
                "old_score_band": old_band,
                "new_score_band": new_band,
                "reason": row.get("reason", ""),
                "manual_review_required": row.get("manual_review_required", ""),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _url_has_error(value: str) -> bool:
    normalized = normalize_text(value)
    return any(token in normalized for token in ["404", "error", "not found", "khong tim thay"])


def _domain(value: str) -> str:
    return urlparse(value).netloc.lower().split(":", 1)[0].removeprefix("www.")


def _domain_matches(domain: str, official_domain: str) -> bool:
    domain = _domain(domain if "://" in domain else f"https://{domain}")
    official_domain = _domain(official_domain if "://" in official_domain else f"https://{official_domain}")
    return bool(domain and official_domain and (domain == official_domain or domain.endswith("." + official_domain)))


def _counts(df: pd.DataFrame, column: str) -> dict[str, int]:
    if not isinstance(df, pd.DataFrame) or df.empty or column not in df.columns:
        return {}
    return {str(key): int(value) for key, value in df[column].value_counts().items()}


def _split_counts(df: pd.DataFrame, column: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not isinstance(df, pd.DataFrame) or df.empty or column not in df.columns:
        return counts
    for value in df[column].astype(str):
        for part in value.split(";"):
            part = part.strip()
            if part:
                counts[part] = counts.get(part, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "- none"
    return "\n".join(f"- {key}: {value}" for key, value in counts.items())


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
