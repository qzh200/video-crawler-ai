from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEYS = (
    "cookie",
    "set-cookie",
    "authorization",
    "auth",
    "api_key",
    "apikey",
    "x-api-key",
    "password",
    "passwd",
    "token",
    "access_token",
)

_SENSITIVE_KEY_RE = re.compile("|".join(re.escape(k) for k in SENSITIVE_KEYS), re.IGNORECASE)


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return redact_event(value)
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    if isinstance(value, str):
        # redact header-like patterns: "Cookie: ..." or "Authorization: Bearer ..."
        value = re.sub(r"(?i)(set-cookie|cookie)\s*:\s*[^;\n\r]+", r"\1: <redacted>", value)
        value = re.sub(r"(?i)authorization\s*:\s*[^;\n\r]+", "authorization: <redacted>", value)

        # redact query params like ?token=... or &api_key=...
        qp_pattern = r"(?i)([?&](?:api_key|apikey|x-api-key|token|access_token)=)[^&\s']+"
        value = re.sub(qp_pattern, r"\1<redacted>", value)

        # redact obvious long secrets
        if len(value) > 50 and re.search(r"[A-Za-z0-9_\-]{20,}", value):
            return "<redacted>"
        return value
    return value


def redact_event(event: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-copy of `event` with sensitive fields redacted.

    Keys that match known sensitive names are replaced with "<redacted>".
    Strings are sanitized for header patterns and query parameters.
    Works recursively for nested dicts and lists.
    """
    out: dict[str, Any] = {}
    for k, v in event.items():
        if _SENSITIVE_KEY_RE.search(k):
            out[k] = "<redacted>"
            continue
        if isinstance(v, dict):
            out[k] = redact_event(v)
            continue
        if isinstance(v, list):
            out[k] = [_redact_value(i) for i in v]
            continue
        out[k] = _redact_value(v)
    return out
