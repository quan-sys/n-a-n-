"""Download verified official finance document candidates for REAL-DATA-01I-E."""

from __future__ import annotations

from pathlib import Path
from time import sleep
from typing import Any, Callable
from urllib.parse import urlparse

import pandas as pd

from src.ingestion.official_finance_document_downloader import (
    DocumentFetchResponse,
    download_one_seed_document,
)
from src.ingestion.official_finance_document_seed import SEED_COLUMNS, load_document_seed_csv
from src.ingestion.official_finance_document_verifier import (
    FINANCE_DOCUMENT_INDEX_COLUMNS_01IE,
    MANUAL_REVIEW_COLUMNS_01IE,
    build_01ie_decision_report_markdown,
    build_01ie_index_row,
    build_01ie_run_summary_markdown,
    build_document_download_status_by_ticker,
    manual_review_row_from_01ie_index,
)
from src.ingestion.official_finance_html_document_finder import (
    DEPTH1_DOCUMENT_CANDIDATE_COLUMNS,
    find_depth1_document_candidates,
)
from src.ingestion.official_finance_link_extractor import infer_candidate_document_type, infer_period_guess, normalize_text


TARGET_PERIOD_PRIORITY = {
    "2026-Q1": 0,
    "2025-Q4": 1,
    "2025": 2,
    "2025-Q3": 3,
    "2025-Q2": 4,
}

SUCCESS_DOCUMENT_STATUSES = {"DOWNLOADED", "DEPTH1_DOCUMENT_DOWNLOADED"}


def run_official_finance_candidate_download_01ie(
    *,
    refined_seed_file: str | Path,
    candidate_file: str | Path,
    output_dir: str | Path,
    raw_output_dir: str | Path,
    request_sleep_seconds: float = 0,
    timeout_seconds: int = 30,
    max_documents: int | None = None,
    max_depth1_documents_per_page: int = 3,
    tickers: list[str] | None = None,
    prefer_direct_documents: bool = True,
    skip_html_depth1: bool = False,
    dry_run: bool = False,
    allow_partial: bool = False,
    http_get: Callable[..., DocumentFetchResponse] | None = None,
    command: str = "",
) -> dict[str, pd.DataFrame]:
    refined_seed = load_document_seed_csv(refined_seed_file)
    candidate_df = pd.read_csv(candidate_file, keep_default_na=False)
    prepared = prepare_refined_candidates(
        refined_seed=refined_seed,
        candidate_df=candidate_df,
        tickers=tickers,
        prefer_direct_documents=prefer_direct_documents,
    )
    if prepared.empty and not allow_partial:
        raise ValueError("No refined official document candidates to process.")
    selected = prepared.head(max_documents) if max_documents else prepared
    result = download_refined_document_candidates(
        selected,
        raw_output_dir=raw_output_dir,
        request_sleep_seconds=request_sleep_seconds,
        timeout_seconds=timeout_seconds,
        max_depth1_documents_per_page=max_depth1_documents_per_page,
        skip_html_depth1=skip_html_depth1,
        dry_run=dry_run,
        http_get=http_get,
    )
    document_index = result["finance_document_index"]
    depth1_candidates = result["depth1_document_candidates"]
    manual_review = build_01ie_manual_review_queue(
        document_index=document_index,
        depth1_candidates=depth1_candidates,
        html_pages_without_depth1=result["html_pages_without_depth1"],
        ambiguous_depth1_pages=result["ambiguous_depth1_pages"],
    )
    status_by_ticker = build_document_download_status_by_ticker(
        refined_candidates=prepared,
        document_index=document_index,
        depth1_candidates=depth1_candidates,
    )

    resolved_output_dir = Path(output_dir)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    if not dry_run:
        Path(raw_output_dir).mkdir(parents=True, exist_ok=True)
    document_index.to_csv(resolved_output_dir / "finance_document_index.csv", index=False)
    status_by_ticker.to_csv(resolved_output_dir / "document_download_status_by_ticker.csv", index=False)
    depth1_candidates.to_csv(resolved_output_dir / "depth1_document_candidates.csv", index=False)
    manual_review.to_csv(resolved_output_dir / "manual_review_queue.csv", index=False)
    (resolved_output_dir / "official_finance_document_01ie_run_summary.md").write_text(
        build_01ie_run_summary_markdown(
            command=command,
            refined_seed_rows_loaded=len(refined_seed),
            unique_tickers=int(refined_seed["ticker"].nunique()),
            document_index=document_index,
            depth1_candidates=depth1_candidates,
            manual_review_queue=manual_review,
            status_by_ticker=status_by_ticker,
        ),
        encoding="utf-8",
    )
    (resolved_output_dir / "datasource_decision_report.md").write_text(
        build_01ie_decision_report_markdown(document_index=document_index),
        encoding="utf-8",
    )
    return {
        "prepared_refined_candidates": prepared,
        "selected_refined_candidates": selected,
        "finance_document_index": document_index,
        "document_download_status_by_ticker": status_by_ticker,
        "depth1_document_candidates": depth1_candidates,
        "manual_review_queue": manual_review,
    }


def prepare_refined_candidates(
    *,
    refined_seed: pd.DataFrame,
    candidate_df: pd.DataFrame,
    tickers: list[str] | None = None,
    prefer_direct_documents: bool = True,
) -> pd.DataFrame:
    frame = refined_seed.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    if tickers:
        wanted = {ticker.strip().upper() for ticker in tickers if ticker.strip()}
        frame = frame[frame["ticker"].isin(wanted)].copy()
    score_frame = _candidate_score_frame(candidate_df)
    frame = frame.merge(
        score_frame,
        how="left",
        left_on=["ticker", "source_url"],
        right_on=["ticker", "candidate_url"],
    )
    frame["candidate_score"] = pd.to_numeric(frame["candidate_score"], errors="coerce").fillna(0).astype(int)
    frame["candidate_score_band"] = frame["candidate_score_band"].fillna("")
    frame["anchor_text"] = frame["anchor_text"].fillna("")
    frame["candidate_reason"] = frame["candidate_reason"].fillna("")
    frame["candidate_manual_review_required"] = frame["candidate_manual_review_required"].fillna(True)
    frame["is_direct_document"] = frame.apply(lambda row: _is_direct_document(row.get("source_url"), row.get("expected_file_type")), axis=1)
    frame["is_https"] = frame["source_url"].astype(str).str.lower().str.startswith("https://")
    frame["domain_matches"] = frame.apply(lambda row: _domain_matches(_domain(row.get("source_url")), row.get("official_domain")), axis=1)
    frame["period_priority"] = frame["period"].astype(str).map(TARGET_PERIOD_PRIORITY).fillna(9).astype(int)
    frame["direct_priority"] = frame["is_direct_document"].map(lambda value: 0 if value else 1).astype(int)
    if not prefer_direct_documents:
        frame["direct_priority"] = 0
    frame["consolidated_priority"] = frame["consolidated_status"].astype(str).str.lower().map(
        {"consolidated": 0, "unknown": 1, "standalone": 2}
    ).fillna(2).astype(int)
    frame["domain_priority"] = frame["domain_matches"].map(lambda value: 0 if value else 1).astype(int)
    frame["https_priority"] = frame["is_https"].map(lambda value: 0 if value else 1).astype(int)
    frame = frame.sort_values(
        [
            "direct_priority",
            "consolidated_priority",
            "period_priority",
            "domain_priority",
            "https_priority",
            "candidate_score",
            "ticker",
            "source_url",
        ],
        ascending=[True, True, True, True, True, False, True, True],
    ).reset_index(drop=True)
    return frame


def download_refined_document_candidates(
    refined_candidates: pd.DataFrame,
    *,
    raw_output_dir: str | Path,
    request_sleep_seconds: float = 0,
    timeout_seconds: int = 30,
    max_depth1_documents_per_page: int = 3,
    skip_html_depth1: bool = False,
    dry_run: bool = False,
    http_get: Callable[..., DocumentFetchResponse] | None = None,
) -> dict[str, pd.DataFrame]:
    index_rows: list[dict[str, Any]] = []
    depth1_frames: list[pd.DataFrame] = []
    html_pages_without_depth1: list[dict[str, Any]] = []
    ambiguous_depth1_pages: list[dict[str, Any]] = []
    for _, candidate in refined_candidates.iterrows():
        seed_row = _seed_row_from_candidate(candidate)
        candidate_origin = "REFINED_SEED_DIRECT" if _is_direct_document(seed_row["source_url"], seed_row["expected_file_type"]) else "HTML_SNAPSHOT_ONLY"
        if dry_run:
            row = _dry_run_index_row(seed_row, candidate_origin, candidate.get("candidate_score"), candidate.get("candidate_score_band"))
        else:
            downloaded = download_one_seed_document(
                seed_row,
                raw_output_dir=raw_output_dir,
                timeout_seconds=timeout_seconds,
                http_get=http_get,
                dry_run=False,
            )
            row = build_01ie_index_row(
                seed_row=seed_row,
                downloaded_row=downloaded,
                candidate_origin=candidate_origin,
                candidate_score=candidate.get("candidate_score", ""),
                candidate_score_band=candidate.get("candidate_score_band", ""),
            )
        index_rows.append(row)
        if request_sleep_seconds and not dry_run:
            sleep(float(request_sleep_seconds))
        if (
            not dry_run
            and candidate_origin == "HTML_SNAPSHOT_ONLY"
            and row["download_status"] == "HTML_SNAPSHOT_SAVED"
            and not skip_html_depth1
        ):
            depth_frame = find_depth1_document_candidates(
                ticker=row["ticker"],
                source_html_url=row["final_url"] or row["source_url"],
                source_html_local_path=row["local_path"],
                official_domain=row["official_domain"],
            )
            if depth_frame.empty:
                html_pages_without_depth1.append(row)
            else:
                if len(depth_frame) > max_depth1_documents_per_page:
                    ambiguous_depth1_pages.append(row)
                attempted_depth = _attempt_depth1_downloads(
                    depth_frame=depth_frame,
                    source_seed_row=seed_row,
                    raw_output_dir=raw_output_dir,
                    max_depth1_documents_per_page=max_depth1_documents_per_page,
                    timeout_seconds=timeout_seconds,
                    request_sleep_seconds=request_sleep_seconds,
                    http_get=http_get,
                )
                depth1_frames.append(attempted_depth["depth1_document_candidates"])
                index_rows.extend(attempted_depth["index_rows"])
    document_index = pd.DataFrame(index_rows, columns=FINANCE_DOCUMENT_INDEX_COLUMNS_01IE)
    depth1_candidates = (
        pd.concat(depth1_frames, ignore_index=True)[DEPTH1_DOCUMENT_CANDIDATE_COLUMNS]
        if depth1_frames
        else pd.DataFrame(columns=DEPTH1_DOCUMENT_CANDIDATE_COLUMNS)
    )
    return {
        "finance_document_index": document_index,
        "depth1_document_candidates": depth1_candidates,
        "html_pages_without_depth1": pd.DataFrame(html_pages_without_depth1, columns=FINANCE_DOCUMENT_INDEX_COLUMNS_01IE),
        "ambiguous_depth1_pages": pd.DataFrame(ambiguous_depth1_pages, columns=FINANCE_DOCUMENT_INDEX_COLUMNS_01IE),
    }


def build_01ie_manual_review_queue(
    *,
    document_index: pd.DataFrame,
    depth1_candidates: pd.DataFrame,
    html_pages_without_depth1: pd.DataFrame,
    ambiguous_depth1_pages: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    if not document_index.empty:
        for _, row in document_index[document_index["manual_review_required"].astype(bool)].iterrows():
            rows.append(manual_review_row_from_01ie_index(row))
    for _, row in html_pages_without_depth1.iterrows():
        review = manual_review_row_from_01ie_index(row, priority="medium")
        review["issue"] = "HTML_PAGE_WITH_NO_DEPTH1_DOCUMENT"
        rows.append(review)
    for _, row in ambiguous_depth1_pages.iterrows():
        review = manual_review_row_from_01ie_index(row, priority="medium")
        review["issue"] = "TOO_MANY_AMBIGUOUS_DEPTH1_CANDIDATES"
        rows.append(review)
    if not depth1_candidates.empty:
        not_attempted = depth1_candidates[~depth1_candidates["download_attempted"].astype(bool)]
        for _, row in not_attempted.iterrows():
            rows.append(
                {
                    "ticker": row.get("ticker", ""),
                    "period": row.get("period_guess", ""),
                    "document_type": row.get("document_type_guess", ""),
                    "source_url": row.get("depth1_url", ""),
                    "issue": "DEPTH1_CANDIDATE_NOT_DOWNLOADED",
                    "manual_review_required": True,
                    "priority": "low",
                    "notes": row.get("notes", ""),
                }
            )
    if not rows:
        return pd.DataFrame(columns=MANUAL_REVIEW_COLUMNS_01IE)
    return pd.DataFrame(rows, columns=MANUAL_REVIEW_COLUMNS_01IE).drop_duplicates()


def _attempt_depth1_downloads(
    *,
    depth_frame: pd.DataFrame,
    source_seed_row: dict[str, Any],
    raw_output_dir: str | Path,
    max_depth1_documents_per_page: int,
    timeout_seconds: int,
    request_sleep_seconds: float,
    http_get: Callable[..., DocumentFetchResponse] | None,
) -> dict[str, Any]:
    index_rows = []
    rows = []
    for position, (_, depth_row) in enumerate(depth_frame.iterrows()):
        mutable_depth_row = depth_row.to_dict()
        if position >= max_depth1_documents_per_page:
            rows.append(mutable_depth_row)
            continue
        seed_row = _seed_row_from_depth1(source_seed_row, depth_row.to_dict())
        downloaded = download_one_seed_document(
            seed_row,
            raw_output_dir=raw_output_dir,
            timeout_seconds=timeout_seconds,
            http_get=http_get,
            dry_run=False,
        )
        if downloaded["download_status"] == "DOWNLOADED":
            downloaded["download_status"] = "DEPTH1_DOCUMENT_DOWNLOADED"
        index_row = build_01ie_index_row(
            seed_row=seed_row,
            downloaded_row=downloaded,
            candidate_origin="DEPTH1_FROM_HTML",
            candidate_score=depth_row.get("score", ""),
            candidate_score_band="DEPTH1_REVIEWABLE_CANDIDATE",
        )
        index_rows.append(index_row)
        mutable_depth_row["download_attempted"] = True
        mutable_depth_row["download_status"] = index_row["download_status"]
        mutable_depth_row["local_path"] = index_row["local_path"]
        mutable_depth_row["file_hash"] = index_row["file_hash"]
        mutable_depth_row["manual_review_required"] = index_row["manual_review_required"]
        rows.append(mutable_depth_row)
        if request_sleep_seconds:
            sleep(float(request_sleep_seconds))
    return {
        "index_rows": index_rows,
        "depth1_document_candidates": pd.DataFrame(rows, columns=DEPTH1_DOCUMENT_CANDIDATE_COLUMNS),
    }


def _candidate_score_frame(candidate_df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(candidate_df, pd.DataFrame) or candidate_df.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "candidate_url",
                "candidate_score",
                "candidate_score_band",
                "candidate_manual_review_required",
                "candidate_reason",
                "anchor_text",
            ]
        )
    frame = candidate_df.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    return frame.rename(
        columns={
            "score": "candidate_score",
            "score_band": "candidate_score_band",
            "manual_review_required": "candidate_manual_review_required",
            "reason": "candidate_reason",
        }
    )[
        [
            "ticker",
            "candidate_url",
            "candidate_score",
            "candidate_score_band",
            "candidate_manual_review_required",
            "candidate_reason",
            "anchor_text",
        ]
    ].drop_duplicates(subset=["ticker", "candidate_url"], keep="first")


def _dry_run_index_row(seed_row: dict[str, Any], candidate_origin: str, candidate_score: Any, candidate_score_band: Any) -> dict[str, Any]:
    downloaded = {
        "ticker": seed_row.get("ticker", ""),
        "exchange": seed_row.get("exchange", ""),
        "company_name": seed_row.get("company_name", ""),
        "period": seed_row.get("period", ""),
        "document_type": seed_row.get("document_type", ""),
        "source_type": seed_row.get("source_type", ""),
        "source_name": seed_row.get("source_name", ""),
        "source_url": seed_row.get("source_url", ""),
        "official_domain": seed_row.get("official_domain", ""),
        "final_url": "",
        "http_status": "",
        "content_type": "",
        "detected_file_type": seed_row.get("expected_file_type", "unknown"),
        "local_path": "",
        "file_hash": "",
        "downloaded_at": "",
        "download_status": "MANUAL_REVIEW",
        "document_confidence": "low",
        "manual_review_required": True,
        "review_reason": "DRY_RUN_VALIDATED_NO_DOWNLOAD",
        "notes": "dry-run validation only; no document downloaded",
    }
    return build_01ie_index_row(
        seed_row=seed_row,
        downloaded_row=downloaded,
        candidate_origin=candidate_origin,
        candidate_score=candidate_score,
        candidate_score_band=candidate_score_band,
    )


def _seed_row_from_candidate(candidate: pd.Series | dict[str, Any]) -> dict[str, Any]:
    row = {column: _clean_text(candidate.get(column, "")) for column in SEED_COLUMNS}
    row["ticker"] = row["ticker"].upper()
    row["expected_file_type"] = _expected_file_type(row["source_url"], row["expected_file_type"])
    return row


def _seed_row_from_depth1(source_seed_row: dict[str, Any], depth_row: dict[str, Any]) -> dict[str, Any]:
    depth_url = _clean_text(depth_row.get("depth1_url"))
    combined = f"{depth_url} {depth_row.get('anchor_text', '')}"
    return {
        "ticker": _clean_text(source_seed_row.get("ticker")).upper(),
        "exchange": source_seed_row.get("exchange", ""),
        "company_name": source_seed_row.get("company_name", ""),
        "period": depth_row.get("period_guess") or infer_period_guess(combined),
        "document_type": depth_row.get("document_type_guess") or infer_candidate_document_type(combined),
        "source_type": source_seed_row.get("source_type", "company_ir"),
        "source_name": f"{source_seed_row.get('source_name', '')} depth1 candidate".strip(),
        "source_url": depth_url,
        "official_domain": source_seed_row.get("official_domain", ""),
        "expected_file_type": _expected_file_type(depth_url, depth_row.get("file_extension")),
        "consolidated_status": _infer_consolidated_status(combined, source_seed_row.get("consolidated_status", "unknown")),
        "language": source_seed_row.get("language", "unknown"),
        "confidence_seed": "low",
        "notes": "01IE_DEPTH1_DOCUMENT_CANDIDATE_NOT_FINANCE_EVIDENCE_YET",
    }


def _expected_file_type(source_url: Any, expected: Any) -> str:
    expected_text = _clean_text(expected).lower()
    if expected_text in {"pdf", "xlsx", "xls", "html"}:
        return expected_text
    path = urlparse(_clean_text(source_url)).path.lower()
    for ext in ["pdf", "xlsx", "xls"]:
        if path.endswith("." + ext):
            return ext
    return "html"


def _is_direct_document(source_url: Any, expected_file_type: Any) -> bool:
    expected = _expected_file_type(source_url, expected_file_type)
    return expected in {"pdf", "xlsx", "xls"}


def _infer_consolidated_status(value: str, fallback: Any) -> str:
    normalized = normalize_text(value)
    if "hop nhat" in normalized or "consolidated" in normalized:
        return "consolidated"
    if "rieng" in normalized or "standalone" in normalized or "cong ty me" in normalized or "cty me" in normalized:
        return "standalone"
    fallback_text = _clean_text(fallback).lower()
    return fallback_text if fallback_text in {"consolidated", "standalone", "unknown"} else "unknown"


def _domain(value: Any) -> str:
    return urlparse(_clean_text(value)).netloc.lower().split(":", 1)[0].removeprefix("www.")


def _domain_matches(domain: str, official_domain: Any) -> bool:
    official = _clean_text(official_domain).lower()
    if "://" in official:
        official = urlparse(official).netloc
    official = official.split(":", 1)[0].removeprefix("www.")
    return bool(domain and official and (domain == official or domain.endswith("." + official)))


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()
