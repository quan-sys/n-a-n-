"""Depth-1 official finance document discovery for REAL-DATA-01I-E."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import pandas as pd

from src.ingestion.official_finance_link_extractor import (
    infer_candidate_document_type,
    normalize_text,
    score_official_document_candidate,
)


DEPTH1_DOCUMENT_CANDIDATE_COLUMNS = [
    "ticker",
    "source_html_url",
    "source_html_local_path",
    "official_domain",
    "depth1_url",
    "depth1_domain",
    "anchor_text",
    "file_extension",
    "document_type_guess",
    "period_guess",
    "score",
    "download_attempted",
    "download_status",
    "local_path",
    "file_hash",
    "manual_review_required",
    "reason",
    "notes",
]

DEPTH1_FINANCE_TERMS = [
    "bctc",
    "bao cao tai chinh",
    "financial statement",
    "financial statements",
    "financial report",
    "annual report",
    "bao cao thuong nien",
    "bctn",
    "audited",
    "kiem toan",
    "hop nhat",
    "consolidated",
    "rieng",
    "standalone",
    "quy",
    "quarter",
    "q1",
    "q2",
    "q3",
    "q4",
    "2026",
    "2025",
]


def find_depth1_document_candidates(
    *,
    ticker: str,
    source_html_url: str,
    source_html_local_path: str | Path,
    official_domain: str,
    target_years: list[str] | None = None,
    target_periods: list[str] | None = None,
    min_score: int = 50,
) -> pd.DataFrame:
    """Extract same official-domain depth-1 document links from one saved HTML page."""

    html_path = Path(source_html_local_path)
    if not html_path.exists():
        return pd.DataFrame(columns=DEPTH1_DOCUMENT_CANDIDATE_COLUMNS)
    html = html_path.read_text(encoding="utf-8", errors="replace")
    return find_depth1_document_candidates_from_html(
        ticker=ticker,
        source_html_url=source_html_url,
        source_html_local_path=str(source_html_local_path),
        html=html,
        official_domain=official_domain,
        target_years=target_years,
        target_periods=target_periods,
        min_score=min_score,
    )


def find_depth1_document_candidates_from_html(
    *,
    ticker: str,
    source_html_url: str,
    source_html_local_path: str,
    html: str,
    official_domain: str,
    target_years: list[str] | None = None,
    target_periods: list[str] | None = None,
    min_score: int = 50,
) -> pd.DataFrame:
    parser = _Depth1LinkParser()
    parser.feed(html)
    rows = []
    seen: set[str] = set()
    for raw in parser.links:
        href = _clean_text(raw.get("href"))
        if not href:
            continue
        depth1_url = urljoin(source_html_url, href)
        parsed = urlparse(depth1_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        depth1_domain = _normalize_domain(parsed.netloc)
        if not _domain_matches(depth1_domain, _normalize_domain(official_domain)):
            continue
        anchor_text = _clean_text(raw.get("text"))
        if not _has_strong_document_pattern(depth1_url, anchor_text):
            continue
        if depth1_url in seen:
            continue
        seen.add(depth1_url)
        score_result = score_official_document_candidate(
            candidate_url=depth1_url,
            anchor_text=anchor_text,
            official_domain=official_domain,
            source_download_status="HTML_SNAPSHOT_SAVED",
            target_years=target_years,
            target_periods=target_periods,
        )
        if int(score_result["score"]) < min_score:
            continue
        extension = _file_extension_from_url(depth1_url)
        rows.append(
            {
                "ticker": _clean_text(ticker).upper(),
                "source_html_url": source_html_url,
                "source_html_local_path": source_html_local_path,
                "official_domain": _normalize_domain(official_domain),
                "depth1_url": depth1_url,
                "depth1_domain": depth1_domain,
                "anchor_text": anchor_text,
                "file_extension": extension,
                "document_type_guess": infer_candidate_document_type(f"{depth1_url} {anchor_text}"),
                "period_guess": score_result["period_guess"],
                "score": score_result["score"],
                "download_attempted": False,
                "download_status": "",
                "local_path": "",
                "file_hash": "",
                "manual_review_required": score_result["manual_review_required"],
                "reason": score_result["reason"],
                "notes": "01IE_DEPTH1_CANDIDATE_NOT_FINANCE_EVIDENCE_YET",
            }
        )
    if not rows:
        return pd.DataFrame(columns=DEPTH1_DOCUMENT_CANDIDATE_COLUMNS)
    frame = pd.DataFrame(rows, columns=DEPTH1_DOCUMENT_CANDIDATE_COLUMNS)
    return frame.sort_values(["score", "depth1_url"], ascending=[False, True]).reset_index(drop=True)


def _has_strong_document_pattern(url: str, anchor_text: str) -> bool:
    normalized = normalize_text(f"{url} {anchor_text}")
    extension = _file_extension_from_url(url)
    if extension in {"pdf", "xlsx", "xls"}:
        return any(normalize_text(term) in normalized for term in DEPTH1_FINANCE_TERMS)
    return any(normalize_text(term) in normalized for term in DEPTH1_FINANCE_TERMS)


def _file_extension_from_url(value: str) -> str:
    path = urlparse(value).path.lower()
    if "." not in path:
        return "html"
    extension = path.rsplit(".", 1)[-1]
    return extension if extension in {"pdf", "xlsx", "xls", "html"} else "html"


class _Depth1LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self._current_anchor: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.lower(): value or "" for key, value in attrs}
        if tag == "a" and attr.get("href"):
            self._current_anchor = {"href": attr["href"], "text": []}
            for key in ["title", "aria-label", "download"]:
                if attr.get(key):
                    self._current_anchor["text"].append(attr[key])

    def handle_data(self, data: str) -> None:
        if self._current_anchor is not None:
            self._current_anchor["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_anchor is not None:
            self.links.append(
                {
                    "href": self._current_anchor["href"],
                    "text": " ".join(self._current_anchor["text"]),
                }
            )
            self._current_anchor = None


def _domain_matches(domain: str, official_domain: str) -> bool:
    domain = _normalize_domain(domain)
    official_domain = _normalize_domain(official_domain)
    return bool(domain and official_domain and (domain == official_domain or domain.endswith("." + official_domain)))


def _normalize_domain(value: Any) -> str:
    text = _clean_text(value).lower()
    if "://" in text:
        text = urlparse(text).netloc
    return text.split(":", 1)[0].removeprefix("www.")


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()
