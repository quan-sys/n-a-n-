"""Public-source fetch snapshots for auditable ingestion runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.ingestion.secret_redaction import redact_snapshot_bytes

try:
    import requests
except ImportError:  # pragma: no cover - urllib fallback is used only if requests is absent.
    requests = None


SNAPSHOT_METADATA_COLUMNS = [
    "source_name",
    "source_category",
    "source_url",
    "fetched_at",
    "http_status",
    "content_type",
    "content_hash",
    "snapshot_path",
    "parser_used",
    "parse_status",
    "notes",
]


@dataclass(frozen=True)
class SnapshotFetchResult:
    """Fetched public URL body plus snapshot metadata."""

    url: str
    status_code: int | None
    content_type: str
    body: bytes
    text: str
    error: str
    fetched_at: str
    content_hash: str
    snapshot_path: str


def fetch_public_snapshot(
    *,
    url: str,
    snapshot_dir: str | Path,
    source_name: str,
    source_category: str,
    parser_used: str,
    timeout_seconds: int = 25,
    max_fetch_bytes: int = 1_200_000,
    max_snapshot_bytes: int = 350_000,
    headers: dict[str, str] | None = None,
) -> SnapshotFetchResult:
    """Fetch a public URL with normal TLS verification and save a small snapshot.

    This helper never disables certificate verification and never retries through
    bypass channels. SSL failures are reported for downstream diagnostics.
    """

    resolved_headers = {"User-Agent": "Mozilla/5.0 compatible; VietnameseStockPipeline/01H"}
    for key, value in (headers or {}).items():
        resolved_headers[str(key)] = str(value)

    fetched_at = utc_now_iso()
    status_code: int | None = None
    content_type = ""
    body = b""
    error = ""

    if requests is not None:
        try:
            response = requests.get(
                url,
                headers=resolved_headers,
                timeout=timeout_seconds,
                verify=True,
            )
            status_code = int(response.status_code)
            content_type = str(response.headers.get("content-type", ""))
            body = bytes(response.content[:max_fetch_bytes])
        except requests.exceptions.SSLError as exc:  # type: ignore[union-attr]
            error = f"SSLError:{exc}"
        except requests.exceptions.Timeout as exc:  # type: ignore[union-attr]
            error = f"Timeout:{exc}"
        except requests.exceptions.RequestException as exc:  # type: ignore[union-attr]
            error = f"RequestException:{exc}"
    else:  # pragma: no cover
        try:
            request = Request(url, headers=resolved_headers)
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - public URL from config.
                status_code = getattr(response, "status", None)
                content_type = response.headers.get("content-type", "")
                body = response.read(max_fetch_bytes)
        except HTTPError as exc:
            status_code = exc.code
            content_type = ""
            body = exc.read(max_fetch_bytes)
            error = f"HTTPError:{exc.code}"
        except URLError as exc:
            error = f"URLError:{exc.reason}"
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}:{exc}"

    digest = sha256(body).hexdigest() if body else ""
    encoding = _encoding_from_content_type(content_type)
    text = body.decode(encoding, errors="replace") if body else ""
    snapshot_path = _write_snapshot(
        body=body,
        url=url,
        snapshot_dir=Path(snapshot_dir),
        source_name=source_name,
        source_category=source_category,
        content_type=content_type,
        content_hash=digest,
        max_snapshot_bytes=max_snapshot_bytes,
    )
    return SnapshotFetchResult(
        url=url,
        status_code=status_code,
        content_type=content_type,
        body=body,
        text=text,
        error=error,
        fetched_at=fetched_at,
        content_hash=digest,
        snapshot_path=snapshot_path,
    )


def snapshot_metadata_row(
    *,
    result: SnapshotFetchResult,
    source_name: str,
    source_category: str,
    parser_used: str,
    parse_status: str,
    notes: str,
) -> dict[str, Any]:
    """Build a stable snapshot metadata row."""

    return {
        "source_name": source_name,
        "source_category": source_category,
        "source_url": result.url,
        "fetched_at": result.fetched_at,
        "http_status": result.status_code or "",
        "content_type": result.content_type,
        "content_hash": result.content_hash,
        "snapshot_path": result.snapshot_path,
        "parser_used": parser_used,
        "parse_status": parse_status,
        "notes": notes,
    }


def probe_status_from_snapshot(result: SnapshotFetchResult) -> str:
    """Convert a fetch result into the 01H source status vocabulary."""

    lower_error = result.error.lower()
    lower_body = result.text.lower()
    if "ssl" in lower_error:
        return "SOURCE_SSL_FAILED"
    if result.status_code == 429:
        return "SOURCE_RATE_LIMITED"
    if result.status_code in {401, 403}:
        return "SOURCE_BLOCKED_OR_JS_REQUIRED"
    if result.error:
        return "SOURCE_UNAVAILABLE"
    if result.status_code is None or result.status_code >= 500:
        return "SOURCE_UNAVAILABLE"
    if result.status_code >= 400:
        return "SOURCE_UNAVAILABLE"
    if not result.body:
        return "SOURCE_EMPTY_RESPONSE"
    blocked_markers = ["captcha", "access denied", "forbidden"]
    login_markers = ["login", "dang nhap", "sign in"]
    js_markers = ["__next", "window.", "document.", "javascript", "app-root"]
    schema_markers = ["\"success\"", "\"data\"", "<table", "cong bo thong tin", "canh bao"]
    if any(marker in lower_body for marker in blocked_markers + login_markers):
        return "SOURCE_BLOCKED_OR_JS_REQUIRED"
    if sum(marker in lower_body for marker in js_markers) >= 2 and not any(
        marker in lower_body for marker in schema_markers
    ):
        return "SOURCE_BLOCKED_OR_JS_REQUIRED"
    if not any(marker in lower_body for marker in schema_markers):
        return "SOURCE_SCHEMA_UNKNOWN"
    return "SOURCE_AVAILABLE"


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _write_snapshot(
    *,
    body: bytes,
    url: str,
    snapshot_dir: Path,
    source_name: str,
    source_category: str,
    content_type: str,
    content_hash: str,
    max_snapshot_bytes: int,
) -> str:
    if not body:
        return ""
    if len(body) > max_snapshot_bytes:
        return ""
    if "pdf" in content_type.lower():
        return ""
    suffix = ".json" if "json" in content_type.lower() else ".html"
    safe_source = _safe_token(f"{source_category}_{source_name}")
    safe_hash = (content_hash or sha256(url.encode("utf-8")).hexdigest())[:16]
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_dir / f"{safe_source}_{safe_hash}{suffix}"
    body_to_write = redact_snapshot_bytes(body, content_type=content_type, file_suffix=suffix)
    path.write_bytes(body_to_write)
    return str(path)


def _encoding_from_content_type(content_type: str) -> str:
    lower = content_type.lower()
    marker = "charset="
    if marker in lower:
        return lower.split(marker, 1)[1].split(";", 1)[0].strip() or "utf-8"
    return "utf-8"


def _safe_token(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value.lower()).strip("_")
