"""Vietstock category-first public document discovery for 01IF PATCH3-PATCH3."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import pandas as pd

from src.ingestion.official_finance_link_extractor import normalize_text
from src.ingestion.source_snapshot import fetch_public_snapshot, probe_status_from_snapshot


VIETSTOCK_DOCUMENT_CATEGORY_COLUMNS_01IF_PATCH3_PATCH3 = [
    "ticker",
    "source_name",
    "source_category",
    "source_url",
    "document_category_raw",
    "document_category_normalized",
    "document_title",
    "published_at",
    "report_year",
    "period",
    "period_type",
    "file_type",
    "candidate_url",
    "final_url",
    "confidence_raw",
    "manual_review_required",
    "review_reason",
]

TARGET_VIETSTOCK_CATEGORIES = {"financial_statement", "annual_report"}


@dataclass(frozen=True)
class DocumentCandidate:
    ticker: str
    source_name: str
    source_category: str
    source_url: str
    document_category_raw: str
    document_category_normalized: str
    document_title: str
    published_at: str
    report_year: str
    period: str
    period_type: str
    file_type: str
    candidate_url: str
    final_url: str
    confidence_raw: str
    manual_review_required: bool
    review_reason: str

    def as_row(self) -> dict[str, Any]:
        return self.__dict__.copy()


def discover_vietstock_documents_for_ticker(
    ticker: str,
    years: list[int],
    *,
    snapshot_dir: str | Path = "data/raw/vietstock_document_discovery/01if_patch3_patch3",
    timeout_seconds: int = 20,
) -> list[DocumentCandidate]:
    """Fetch and parse the public Vietstock shareholder-document page.

    The fetch uses normal public HTTP only. If Vietstock blocks or requires JS,
    the result is a manual-review candidate instead of any bypass attempt.
    """

    clean_ticker = str(ticker or "").strip().upper()
    source_url = f"https://finance.vietstock.vn/{clean_ticker}/tai-tai-lieu.htm"
    result = fetch_public_snapshot(
        url=source_url,
        snapshot_dir=snapshot_dir,
        source_name="vietstock_finance_documents",
        source_category="vietstock_public_document_page",
        parser_used="vietstock_document_discovery_01if_patch3_patch3",
        timeout_seconds=timeout_seconds,
    )
    status = probe_status_from_snapshot(result)
    if status != "SOURCE_AVAILABLE":
        return [
            DocumentCandidate(
                ticker=clean_ticker,
                source_name="vietstock_finance_documents",
                source_category="vietstock_public_document_page",
                source_url=source_url,
                document_category_raw="",
                document_category_normalized="other",
                document_title="",
                published_at="",
                report_year="",
                period="",
                period_type="",
                file_type="html",
                candidate_url="",
                final_url="",
                confidence_raw="low",
                manual_review_required=True,
                review_reason="MANUAL_REVIEW_BLOCKED_OR_JS" if "BLOCKED" in status else status,
            )
        ]
    candidates = parse_vietstock_document_candidates_from_html(
        ticker=clean_ticker,
        html=result.text,
        years=years,
        source_url=source_url,
    )
    if not candidates:
        return [
            DocumentCandidate(
                ticker=clean_ticker,
                source_name="vietstock_finance_documents",
                source_category="vietstock_public_document_page",
                source_url=source_url,
                document_category_raw="",
                document_category_normalized="other",
                document_title="",
                published_at="",
                report_year="",
                period="",
                period_type="",
                file_type="html",
                candidate_url="",
                final_url="",
                confidence_raw="low",
                manual_review_required=True,
                review_reason="MANUAL_REVIEW_NO_DIRECT_FILE_LINK",
            )
        ]
    return candidates


def parse_vietstock_document_candidates_from_html(
    *,
    ticker: str,
    html: str,
    years: list[int],
    source_url: str = "",
) -> list[DocumentCandidate]:
    parser = _VietstockDocumentHtmlParser(base_url=source_url)
    parser.feed(str(html or ""))
    rows = []
    clean_ticker = str(ticker or "").strip().upper()
    wanted_years = {str(year) for year in years}
    for link in parser.links:
        title = link.get("title", "")
        href = link.get("href", "")
        category_raw = link.get("category", "")
        normalized_category = normalize_vietstock_category(category_raw)
        report_year = _infer_year(" ".join([title, href]))
        if wanted_years and report_year and report_year not in wanted_years:
            continue
        file_type = _file_type_from_url(href)
        review_reason = ""
        manual_review = False
        confidence = "medium"
        if normalized_category not in TARGET_VIETSTOCK_CATEGORIES:
            review_reason = "REJECTED_NON_TARGET_VIETSTOCK_CATEGORY"
            manual_review = True
            confidence = "low"
        elif not href:
            review_reason = "MANUAL_REVIEW_NO_DIRECT_FILE_LINK"
            manual_review = True
            confidence = "low"
        rows.append(
            DocumentCandidate(
                ticker=clean_ticker,
                source_name="vietstock_finance_documents",
                source_category="vietstock_public_document_page",
                source_url=source_url,
                document_category_raw=category_raw,
                document_category_normalized=normalized_category,
                document_title=title,
                published_at=_infer_date(" ".join([title, link.get("context", "")])),
                report_year=report_year,
                period=_infer_period(" ".join([title, href])),
                period_type=_period_type(_infer_period(" ".join([title, href]))),
                file_type=file_type,
                candidate_url=href,
                final_url=href,
                confidence_raw=confidence,
                manual_review_required=manual_review,
                review_reason=review_reason,
            )
        )
    return rows


def candidates_to_frame(candidates: list[DocumentCandidate]) -> pd.DataFrame:
    return pd.DataFrame([candidate.as_row() for candidate in candidates], columns=VIETSTOCK_DOCUMENT_CATEGORY_COLUMNS_01IF_PATCH3_PATCH3)


def normalize_vietstock_category(value: Any) -> str:
    normalized = normalize_text(value)
    if "bao cao tai chinh" in normalized or "bctc" in normalized or "financial statement" in normalized:
        return "financial_statement"
    if "bao cao thuong nien" in normalized or "bctn" in normalized or "annual report" in normalized:
        return "annual_report"
    return "other"


class _VietstockDocumentHtmlParser(HTMLParser):
    def __init__(self, *, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.current_category = ""
        self._active_link: dict[str, Any] | None = None
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.lower(): value or "" for key, value in attrs}
        category = attr.get("data-category") or attr.get("data-document-category") or attr.get("category")
        if category:
            self.current_category = category
        class_text = " ".join([attr.get("class", ""), attr.get("id", "")])
        if tag.lower() in {"li", "tr", "div", "section"} and category:
            self.current_category = category
        if tag.lower() == "a":
            href = attr.get("href", "").strip()
            self._active_link = {
                "href": urljoin(self.base_url, href) if href else "",
                "title": attr.get("title", "").strip(),
                "category": category or self.current_category,
                "context": class_text,
                "text": [],
            }

    def handle_data(self, data: str) -> None:
        text = " ".join(str(data or "").split())
        if not text:
            return
        normalized = normalize_text(text)
        if normalize_vietstock_category(text) in TARGET_VIETSTOCK_CATEGORIES:
            self.current_category = text
        elif any(token in normalized for token in ["nghi quyet", "esop", "dieu le", "tai lieu", "bao cao quan tri", "khac"]):
            self.current_category = text
        if self._active_link is not None:
            self._active_link["text"].append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._active_link is None:
            return
        title = self._active_link.get("title") or " ".join(self._active_link.get("text", []))
        href = self._active_link.get("href", "")
        context = " ".join([self._active_link.get("context", ""), title, href])
        if _looks_like_document_link(href, title):
            self.links.append(
                {
                    "href": href,
                    "title": title,
                    "category": self._active_link.get("category", "") or _category_from_context(context),
                    "context": context,
                }
            )
        self._active_link = None


def _looks_like_document_link(href: str, title: str) -> bool:
    normalized = normalize_text(f"{href} {title}")
    return bool(
        href
        and (
            _file_type_from_url(href) in {"pdf", "xlsx", "xls"}
            or any(token in normalized for token in ["bctc", "bctn", "bao cao tai chinh", "bao cao thuong nien", "financial statement", "annual report"])
        )
    )


def _category_from_context(value: str) -> str:
    normalized = normalize_text(value)
    if "bao cao tai chinh" in normalized or "bctc" in normalized:
        return "Bao cao tai chinh"
    if "bao cao thuong nien" in normalized or "bctn" in normalized or "annual report" in normalized:
        return "Bao cao thuong nien"
    return ""


def _file_type_from_url(value: str) -> str:
    path = urlparse(str(value or "")).path.lower()
    if "." not in path:
        return "html"
    suffix = path.rsplit(".", 1)[-1]
    return suffix if re.fullmatch(r"[a-z0-9]{2,5}", suffix) else "html"


def _infer_year(value: str) -> str:
    match = re.search(r"\b(20\d{2})\b", str(value or ""))
    return match.group(1) if match else ""


def _infer_date(value: str) -> str:
    match = re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]20\d{2})\b", str(value or ""))
    return match.group(1) if match else ""


def _infer_period(value: str) -> str:
    text = normalize_text(value)
    year = _infer_year(value)
    quarter = ""
    for index in range(1, 5):
        if f"quy {index}" in text or f"q{index}" in text or f"quarter {index}" in text:
            quarter = f"Q{index}"
            break
    if year and quarter:
        return f"{year}-{quarter}"
    return year


def _period_type(period: str) -> str:
    return "quarter" if "-Q" in str(period or "").upper() else "annual" if period else ""
