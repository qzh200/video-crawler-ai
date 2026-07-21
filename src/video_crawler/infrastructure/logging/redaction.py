from __future__ import annotations

import re
from collections.abc import Mapping, MutableMapping
from typing import Any

REDACTED = "<redacted>"

_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "cookie",
        "client_secret",
        "minio_secret_key",
        "mysql_password",
        "passwd",
        "password",
        "secret",
        "set_cookie",
        "token",
        "x_api_key",
    }
)
_SENSITIVE_SUFFIXES = ("_api_key", "_password", "_secret", "_token")
_HEADER_RE = re.compile(r"(?im)\b(set-cookie|cookie|authorization|x-api-key)\s*:\s*[^\r\n]*")
_QUERY_RE = re.compile(
    r"(?i)([?&](?:"
    r"access_token|api_key|apikey|authorization|client_secret|cookie|key|password|"
    r"refresh_token|secret|session|sign|signature|token|w_rid|x-api-key"
    r")=)[^&#\s'\"]*"
)


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES)


def redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: REDACTED if _is_sensitive_key(key) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, str):
        return _QUERY_RE.sub(r"\1" + REDACTED, _HEADER_RE.sub(r"\1: " + REDACTED, value))
    if hasattr(value, "get_secret_value"):
        return REDACTED
    return value


def redact_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Return a recursively redacted copy of a structured log event."""

    return {
        key: REDACTED if _is_sensitive_key(key) else redact_value(value)
        for key, value in event.items()
    }


def redact_processor(
    logger: Any,
    method_name: str,
    event_dict: MutableMapping[str, Any],
) -> Mapping[str, Any]:
    del logger, method_name
    return redact_event(event_dict)
