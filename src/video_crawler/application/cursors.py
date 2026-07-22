from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


class InvalidCursorError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CommentCursor:
    published_at: datetime | None
    id: int


@dataclass(frozen=True, slots=True)
class TimedTextCursor:
    start_ms: int
    id: int


@dataclass(frozen=True, slots=True)
class MetricCursor:
    captured_at: datetime
    id: int


def _encode_base64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_base64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def _format_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("cursor datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise InvalidCursorError("invalid cursor datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise InvalidCursorError("invalid cursor datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidCursorError("invalid cursor datetime")
    return parsed.astimezone(UTC)


class CursorCodec:
    def __init__(self, secret: bytes) -> None:
        if not secret:
            raise ValueError("cursor secret must not be empty")
        self._secret = secret

    def encode_comment(self, cursor: CommentCursor) -> str:
        published_at = (
            _format_datetime(cursor.published_at) if cursor.published_at is not None else None
        )
        return self._encode({"kind": "comment", "published_at": published_at, "id": cursor.id})

    def decode_comment(self, value: str) -> CommentCursor:
        payload = self._decode(value, "comment")
        published_value = payload.get("published_at")
        published_at = None if published_value is None else _parse_datetime(published_value)
        return CommentCursor(published_at=published_at, id=self._positive_id(payload))

    def encode_timed_text(self, cursor: TimedTextCursor) -> str:
        return self._encode({"kind": "timed_text", "start_ms": cursor.start_ms, "id": cursor.id})

    def decode_timed_text(self, value: str) -> TimedTextCursor:
        payload = self._decode(value, "timed_text")
        start_ms = payload.get("start_ms")
        if not isinstance(start_ms, int) or isinstance(start_ms, bool) or start_ms < 0:
            raise InvalidCursorError("invalid cursor start_ms")
        return TimedTextCursor(start_ms=start_ms, id=self._positive_id(payload))

    def encode_metric(self, cursor: MetricCursor) -> str:
        return self._encode(
            {
                "kind": "metric",
                "captured_at": _format_datetime(cursor.captured_at),
                "id": cursor.id,
            }
        )

    def decode_metric(self, value: str) -> MetricCursor:
        payload = self._decode(value, "metric")
        return MetricCursor(
            captured_at=_parse_datetime(payload.get("captured_at")),
            id=self._positive_id(payload),
        )

    def _encode(self, payload: dict[str, object]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.digest(self._secret, raw, hashlib.sha256)
        return f"{_encode_base64(raw)}.{_encode_base64(signature)}"

    def _decode(self, value: str, expected_kind: str) -> dict[str, Any]:
        try:
            payload_part, signature_part = value.split(".", maxsplit=1)
            raw = _decode_base64(payload_part)
            supplied_signature = _decode_base64(signature_part)
        except (ValueError, UnicodeError) as error:
            raise InvalidCursorError("invalid cursor encoding") from error
        expected_signature = hmac.digest(self._secret, raw, hashlib.sha256)
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise InvalidCursorError("invalid cursor signature")
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeError) as error:
            raise InvalidCursorError("invalid cursor payload") from error
        if not isinstance(payload, dict):
            raise InvalidCursorError("invalid cursor payload")
        if payload.get("kind") != expected_kind:
            raise InvalidCursorError("invalid cursor kind")
        return payload

    @staticmethod
    def _positive_id(payload: dict[str, Any]) -> int:
        value = payload.get("id")
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise InvalidCursorError("invalid cursor id")
        return value
