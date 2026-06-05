"""Safe source probing utilities for REAL-DATA-01G."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

from src.ingestion.source_adapter_contracts import SOURCE_PROBE_COLUMNS

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None


DEFAULT_TARGETS_PATH = Path("config/source_probe_targets.yaml")
BLOCKED_MARKERS = ["captcha", "cloudflare", "access denied", "forbidden"]
LOGIN_MARKERS = ["login", "dang nhap", "sign in"]
JS_MARKERS = ["__next", "window.", "document.", "javascript", "app-root"]
SCHEMA_MARKERS = ["<table", "bao cao tai chinh", "cong bo thong tin", "financial"]


@dataclass
class HttpProbeResponse:
    url: str
    status_code: int | None
    body: str
    error: str = ""


def load_source_probe_targets(path: str | Path = DEFAULT_TARGETS_PATH) -> dict[str, Any]:
    """Load source probe target config."""

    if yaml is None:
        raise ImportError("PyYAML is required to load source probe targets.")
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise ValueError("source probe targets must contain a YAML mapping.")
    return data


def safe_http_get(
    url: str,
    *,
    timeout_seconds: int = 20,
    user_agent: str = "Mozilla/5.0 compatible; VietnameseStockPipeline/01G",
    max_bytes: int = 300000,
) -> HttpProbeResponse:
    """Fetch a public URL without bypassing blocks or JS requirements."""

    request = Request(url, headers={"User-Agent": user_agent})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - public probe URL from config.
            status_code = getattr(response, "status", None)
            raw = response.read(max_bytes)
            encoding = response.headers.get_content_charset() or "utf-8"
            body = raw.decode(encoding, errors="replace")
            return HttpProbeResponse(url=url, status_code=status_code, body=body)
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read(max_bytes).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return HttpProbeResponse(
            url=url,
            status_code=exc.code,
            body=body,
            error=f"HTTPError:{exc.code}",
        )
    except URLError as exc:
        return HttpProbeResponse(
            url=url,
            status_code=None,
            body="",
            error=f"URLError:{exc.reason}",
        )
    except Exception as exc:  # noqa: BLE001 - source probes must not crash batch.
        return HttpProbeResponse(
            url=url,
            status_code=None,
            body="",
            error=f"{type(exc).__name__}:{exc}",
        )


def probe_public_url(
    *,
    source_name: str,
    source_category: str,
    dataset_name: str,
    sample_url: str,
    supported_fields: list[str] | None = None,
    unsupported_fields: list[str] | None = None,
    http_get: Any = safe_http_get,
    request_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Probe one source URL and return a normalized probe-result row."""

    defaults = request_defaults or {}
    response = http_get(
        sample_url,
        timeout_seconds=int(defaults.get("timeout_seconds", 20)),
        user_agent=str(defaults.get("user_agent", "Mozilla/5.0")),
        max_bytes=int(defaults.get("max_probe_bytes", 300000)),
    )
    text = (response.body or "").lower()
    status = response.status_code
    requires_login = any(marker in text for marker in LOGIN_MARKERS)
    blocked = (
        bool(status in {401, 403})
        or any(marker in text for marker in BLOCKED_MARKERS)
    )
    rate_limited = bool(status == 429)
    requires_js = _requires_js(text)
    schema_detected = any(marker in text for marker in SCHEMA_MARKERS)

    if rate_limited:
        probe_status = "SOURCE_RATE_LIMITED"
    elif blocked or requires_login:
        probe_status = "SOURCE_BLOCKED_OR_JS_REQUIRED"
    elif response.error or status is None or (status and status >= 500):
        probe_status = "SOURCE_UNAVAILABLE"
    elif status and status >= 400:
        probe_status = "SOURCE_UNAVAILABLE"
    elif not response.body.strip():
        probe_status = "SOURCE_EMPTY_RESPONSE"
    elif requires_js and not schema_detected:
        probe_status = "SOURCE_BLOCKED_OR_JS_REQUIRED"
    elif not schema_detected:
        probe_status = "SOURCE_SCHEMA_UNKNOWN"
    else:
        probe_status = "SOURCE_AVAILABLE"

    return {
        "source_name": source_name,
        "source_category": source_category,
        "dataset_name": dataset_name,
        "probe_status": probe_status,
        "http_status_or_error": response.error or str(status or ""),
        "is_accessible": probe_status in {"SOURCE_AVAILABLE", "SOURCE_SCHEMA_UNKNOWN"},
        "requires_js": bool(requires_js),
        "requires_login": bool(requires_login),
        "blocked_or_captcha": bool(blocked),
        "schema_detected": bool(schema_detected),
        "supported_fields": "|".join(supported_fields or []),
        "unsupported_fields": "|".join(unsupported_fields or []),
        "sample_url": sample_url,
        "notes": _probe_notes(probe_status, response.error),
    }


def build_probe_matrix(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Build probe matrix with stable columns."""

    return pd.DataFrame(rows, columns=SOURCE_PROBE_COLUMNS)


def _requires_js(text: str) -> bool:
    if not text:
        return False
    marker_count = sum(marker in text for marker in JS_MARKERS)
    has_visible_schema = any(marker in text for marker in SCHEMA_MARKERS)
    return marker_count >= 2 and not has_visible_schema


def _probe_notes(status: str, error: str) -> str:
    if status == "SOURCE_AVAILABLE":
        return "public URL accessible and schema markers detected"
    if status == "SOURCE_SCHEMA_UNKNOWN":
        return "public URL accessible but expected schema markers were not detected"
    if status == "SOURCE_BLOCKED_OR_JS_REQUIRED":
        return "source appears blocked, login-gated, captcha-gated, or JS-required"
    if status == "SOURCE_EMPTY_RESPONSE":
        return "source returned an empty response"
    if status == "SOURCE_RATE_LIMITED":
        return "source returned a rate-limit response"
    return error or "source unavailable"
