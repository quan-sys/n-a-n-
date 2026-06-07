"""Redact credential-like tokens before saving public text snapshots."""

from __future__ import annotations

import re


TEXT_SNAPSHOT_SUFFIXES = {".csv", ".htm", ".html", ".js", ".json", ".txt", ".xml"}
TEXT_CONTENT_TYPE_MARKERS = ("csv", "html", "javascript", "json", "text/", "xml")

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"AIza[0-9A-Za-z_-]{30,45}"), "[REDACTED_GOOGLE_API_KEY]"),
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "[REDACTED_OPENAI_KEY]"),
    (re.compile(r"gh[opsru]_[A-Za-z0-9_]{20,}"), "[REDACTED_GITHUB_TOKEN]"),
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----",
            re.MULTILINE,
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (
        re.compile(
            r"(?i)([?&;\s\"'](?:api_?key|access_token|auth_token|secret|token)=)([^&#\s\"']{12,})"
        ),
        r"\1[REDACTED_SECRET]",
    ),
)


def redact_text_secrets(text: str) -> str:
    """Return text with credential-shaped values replaced by stable markers."""

    redacted = text
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_snapshot_bytes(
    body: bytes,
    *,
    content_type: str = "",
    file_suffix: str = "",
) -> bytes:
    """Redact text-like snapshot bytes without modifying binary documents."""

    if not body or not is_text_snapshot(content_type=content_type, file_suffix=file_suffix):
        return body
    text = body.decode("utf-8", errors="replace")
    redacted = redact_text_secrets(text)
    if redacted == text:
        return body
    return redacted.encode("utf-8")


def is_text_snapshot(*, content_type: str = "", file_suffix: str = "") -> bool:
    lower_content_type = str(content_type or "").lower()
    lower_suffix = str(file_suffix or "").lower()
    if lower_suffix and not lower_suffix.startswith("."):
        lower_suffix = f".{lower_suffix}"
    return lower_suffix in TEXT_SNAPSHOT_SUFFIXES or any(
        marker in lower_content_type for marker in TEXT_CONTENT_TYPE_MARKERS
    )
