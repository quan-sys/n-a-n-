"""HTTPS-first official finance document link extraction for REAL-DATA-01I-D."""

from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import pandas as pd


LINK_CANDIDATE_COLUMNS = [
    "ticker",
    "source_page_url",
    "source_snapshot_path",
    "official_domain",
    "candidate_url",
    "candidate_scheme",
    "candidate_domain",
    "candidate_is_https",
    "anchor_text",
    "file_extension",
    "candidate_document_type",
    "period_guess",
    "score",
    "score_band",
    "manual_review_required",
    "reason",
    "notes",
]

FINANCE_KEYWORDS = [
    "bao cao tai chinh",
    "bctc",
    "financial statement",
    "financial statements",
    "financial report",
    "financial reports",
    "audited",
    "kiem toan",
    "hop nhat",
    "consolidated",
]

ANNUAL_KEYWORDS = [
    "annual report",
    "bao cao thuong nien",
    "thuong nien",
]

PERIOD_KEYWORDS = ["quarter", "quy", "q1", "q2", "q3", "q4", "2026", "2025"]

DISCOVERY_HINTS = [
    "nha dau tu",
    "investor",
    "co dong",
    "shareholder",
    "quan he",
    "download",
    "tai ve",
    "document",
]

GENERIC_NEWS_HINTS = ["tin tuc", "news", "bai viet", "post", "article"]
BLOCK_HINTS = ["captcha", "access denied", "forbidden", "enable javascript", "app-root", "__next", "login"]
ERROR_HINTS = ["404", "not found", "error", "page not found", "khong tim thay"]
NON_DOCUMENT_EXTENSIONS = {
    "css",
    "js",
    "png",
    "jpg",
    "jpeg",
    "gif",
    "svg",
    "ico",
    "webp",
    "woff",
    "woff2",
    "ttf",
    "eot",
    "mp4",
}


def extract_link_candidates_from_snapshot(
    *,
    ticker: str,
    source_page_url: str,
    source_snapshot_path: str | Path,
    official_domain: str,
    source_download_status: str = "HTML_SNAPSHOT_SAVED",
    target_years: list[str] | None = None,
    target_periods: list[str] | None = None,
    min_high_confidence_score: int = 80,
    min_reviewable_score: int = 50,
) -> pd.DataFrame:
    """Extract and score public http/https candidates from a local HTML snapshot."""

    snapshot_path = Path(source_snapshot_path)
    if not snapshot_path.exists():
        return pd.DataFrame(columns=LINK_CANDIDATE_COLUMNS)
    html = snapshot_path.read_text(encoding="utf-8", errors="replace")
    parser = _LinkParser()
    parser.feed(html)
    rows = []
    seen = set()
    page_hints = _page_hints(html)
    for raw_link in parser.links:
        href = _clean_text(raw_link.get("href"))
        if not href:
            continue
        candidate_url = urljoin(source_page_url, href)
        parsed = urlparse(candidate_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        extension = file_extension_from_url(candidate_url)
        if extension in NON_DOCUMENT_EXTENSIONS:
            continue
        anchor_text = _clean_text(raw_link.get("text"))
        if not _looks_like_document_candidate(candidate_url, anchor_text, extension):
            continue
        key = candidate_url
        if key in seen:
            continue
        seen.add(key)
        score_result = score_official_document_candidate(
            candidate_url=candidate_url,
            anchor_text=anchor_text,
            official_domain=official_domain,
            source_download_status=source_download_status,
            page_hints=page_hints,
            target_years=target_years,
            target_periods=target_periods,
            min_high_confidence_score=min_high_confidence_score,
            min_reviewable_score=min_reviewable_score,
        )
        rows.append(
            {
                "ticker": _clean_ticker(ticker),
                "source_page_url": source_page_url,
                "source_snapshot_path": str(source_snapshot_path),
                "official_domain": _normalize_domain(official_domain),
                "candidate_url": candidate_url,
                "candidate_scheme": parsed.scheme,
                "candidate_domain": _normalize_domain(parsed.netloc),
                "candidate_is_https": parsed.scheme == "https",
                "anchor_text": anchor_text,
                "file_extension": extension,
                "candidate_document_type": score_result["candidate_document_type"],
                "period_guess": score_result["period_guess"],
                "score": score_result["score"],
                "score_band": score_result["score_band"],
                "manual_review_required": score_result["manual_review_required"],
                "reason": score_result["reason"],
                "notes": score_result["notes"],
            }
        )
    return pd.DataFrame(rows, columns=LINK_CANDIDATE_COLUMNS)


def score_official_document_candidate(
    *,
    candidate_url: str,
    anchor_text: str,
    official_domain: str,
    source_download_status: str = "HTML_SNAPSHOT_SAVED",
    page_hints: dict[str, bool] | None = None,
    final_url: str | None = None,
    target_years: list[str] | None = None,
    target_periods: list[str] | None = None,
    min_high_confidence_score: int = 80,
    min_reviewable_score: int = 50,
) -> dict[str, Any]:
    """Score a document candidate without treating it as finance evidence."""

    target_years = [str(item) for item in (target_years or ["2026", "2025"])]
    target_periods = [str(item).upper() for item in (target_periods or ["2026-Q1", "2025-Q4", "2025"])]
    effective_url = final_url or candidate_url
    parsed_candidate = urlparse(candidate_url)
    parsed_final = urlparse(effective_url)
    candidate_domain = _normalize_domain(parsed_candidate.netloc)
    final_domain = _normalize_domain(parsed_final.netloc)
    official = _normalize_domain(official_domain)
    combined = f"{candidate_url} {effective_url} {anchor_text}"
    normalized = normalize_text(combined)
    extension = file_extension_from_url(effective_url) or file_extension_from_url(candidate_url)
    page_hints = page_hints or {}
    score = 0
    reasons: list[str] = []
    manual_review = False

    if _domain_matches(final_domain or candidate_domain, official):
        score += 25
        reasons.append("OFFICIAL_DOMAIN_MATCH")
    else:
        score -= 40
        manual_review = True
        reasons.append("DOMAIN_MISMATCH")

    if parsed_final.scheme == "https" or (not final_url and parsed_candidate.scheme == "https"):
        score += 15
        reasons.append("HTTPS_LINK")
    if parsed_candidate.scheme == "http":
        score -= 20
        if parsed_final.scheme == "https" and _domain_matches(final_domain, official):
            manual_review = True
            reasons.append("HTTP_REDIRECTED_TO_HTTPS_REVIEW")
        else:
            manual_review = True
            reasons.append("HTTP_NOT_REDIRECTED_TO_HTTPS")

    finance_hit = _has_any(normalized, FINANCE_KEYWORDS)
    annual_hit = _has_any(normalized, ANNUAL_KEYWORDS)
    target_period_hit = _has_target_period(normalized, target_years, target_periods)
    if finance_hit:
        score += 25
        reasons.append("FINANCE_KEYWORD")
    if annual_hit:
        score += 20
        reasons.append("ANNUAL_REPORT_KEYWORD")
    if target_period_hit:
        score += 10
        reasons.append("TARGET_PERIOD_HINT")
    if extension in {"pdf", "xlsx", "xls"}:
        score += 15
        reasons.append("DOCUMENT_FILE_EXTENSION")
    if source_download_status == "HTML_SNAPSHOT_SAVED":
        score += 5
        reasons.append("SOURCE_HTML_SNAPSHOT_SAVED")

    if _has_error_url(effective_url) or page_hints.get("error_page", False):
        score -= 50
        manual_review = True
        reasons.append("ERROR_OR_404_PAGE")
    if _has_any(normalized, GENERIC_NEWS_HINTS) and not (finance_hit or annual_hit):
        score -= 20
        manual_review = True
        reasons.append("GENERIC_NEWS_PAGE")
    old_year_only = _is_old_year_only(normalized, target_years)
    if old_year_only:
        score -= 35
        manual_review = True
        reasons.append("OLD_YEAR_ONLY")
    if source_download_status == "SOURCE_BLOCKED_OR_JS_REQUIRED" or page_hints.get("blocked_or_js", False):
        score -= 50
        manual_review = True
        reasons.append("JS_OR_BLOCKED")
    if not (finance_hit or annual_hit or extension in {"pdf", "xlsx", "xls"}):
        score -= 20
        manual_review = True
        reasons.append("NO_FINANCE_KEYWORDS")

    score = 0 if old_year_only else max(0, min(100, int(score)))
    if score >= min_high_confidence_score:
        band = "HIGH_CONFIDENCE_CANDIDATE"
    elif score >= min_reviewable_score:
        band = "REVIEWABLE_CANDIDATE"
        manual_review = True
    elif score > 0:
        band = "LOW_CONFIDENCE_CANDIDATE"
        manual_review = True
    else:
        band = "REJECTED_CANDIDATE"
        manual_review = True
    return {
        "score": score,
        "score_band": band,
        "manual_review_required": manual_review,
        "reason": ";".join(_dedupe(reasons)),
        "candidate_document_type": infer_candidate_document_type(combined),
        "period_guess": infer_period_guess(combined, target_years, target_periods),
        "notes": "01ID_CANDIDATE_NOT_FINANCE_EVIDENCE_YET; HTTPS alone is not finance evidence",
    }


def infer_candidate_document_type(value: str) -> str:
    normalized = normalize_text(value)
    if _has_any(normalized, ANNUAL_KEYWORDS):
        return "annual_report"
    if _has_any(normalized, FINANCE_KEYWORDS):
        return "financial_statement"
    return "filing_page"


def infer_period_guess(value: str, target_years: list[str] | None = None, target_periods: list[str] | None = None) -> str:
    normalized = normalize_text(value).upper()
    target_years = [str(item) for item in (target_years or ["2026", "2025"])]
    target_periods = [str(item).upper() for item in (target_periods or ["2026-Q1", "2025-Q4", "2025"])]
    compact = normalized.replace("_", "-").replace("/", "-")
    for period in target_periods:
        year = period[:4]
        quarter = period[-2:] if "-Q" in period else ""
        if quarter and year in compact and quarter in compact:
            return period
    for year in target_years:
        if year in compact:
            return year
    return "DISCOVERY_REVIEW"


def file_extension_from_url(value: str) -> str:
    path = urlparse(value).path.lower()
    if "." not in path:
        return "html"
    ext = path.rsplit(".", 1)[-1]
    return ext if re.fullmatch(r"[a-z0-9]{2,5}", ext) else "html"


def normalize_text(value: Any) -> str:
    text = _clean_text(value).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _looks_like_document_candidate(url: str, anchor_text: str, extension: str) -> bool:
    normalized = normalize_text(f"{url} {anchor_text}")
    if extension in {"pdf", "xlsx", "xls"}:
        return True
    return _has_any(normalized, [*FINANCE_KEYWORDS, *ANNUAL_KEYWORDS, *PERIOD_KEYWORDS, *DISCOVERY_HINTS])


def _page_hints(html: str) -> dict[str, bool]:
    normalized = normalize_text(html[:200_000])
    return {
        "blocked_or_js": _has_any(normalized, BLOCK_HINTS),
        "error_page": _has_any(normalized, ERROR_HINTS),
    }


def _has_any(normalized_text: str, keywords: list[str]) -> bool:
    return any(normalize_text(keyword) in normalized_text for keyword in keywords)


def _has_target_period(normalized_text: str, target_years: list[str], target_periods: list[str]) -> bool:
    upper = normalized_text.upper()
    return any(year in upper for year in target_years) or any(period.upper() in upper for period in target_periods)


def _is_old_year_only(normalized_text: str, target_years: list[str]) -> bool:
    years = re.findall(r"\b20\d{2}\b", normalized_text)
    return bool(years) and not any(year in target_years for year in years)


def _has_error_url(value: str) -> bool:
    normalized = normalize_text(value)
    return _has_any(normalized, ERROR_HINTS)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self._current_anchor: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.lower(): value or "" for key, value in attrs}
        if tag == "a" and attr.get("href"):
            self._current_anchor = {"href": attr["href"], "text": []}
            title = attr.get("title") or attr.get("aria-label") or attr.get("download") or ""
            if title:
                self._current_anchor["text"].append(title)
        elif tag == "link" and attr.get("href"):
            text = attr.get("title") or attr.get("rel") or "metadata link"
            self.links.append({"href": attr["href"], "text": text})
        elif tag == "meta":
            content = attr.get("content", "")
            if content.startswith(("http://", "https://")):
                text = attr.get("property") or attr.get("name") or "metadata link"
                self.links.append({"href": content, "text": text})

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


def _clean_ticker(value: Any) -> str:
    return _clean_text(value).upper()


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
