from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any

from video_crawler.domain.artifacts import RawArtifactRef
from video_crawler.domain.errors import DomainValidationError


class TimedTextType(StrEnum):
    DANMAKU = "danmaku"
    SUBTITLE = "subtitle"


@dataclass(frozen=True, slots=True)
class TimedTextStreamDescriptor:
    platform_unit_id: str
    content_type: TimedTextType
    stream_key: str
    language_code: str | None
    source_type: str
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NormalizedTimedText:
    platform_item_id: str | None
    start_ms: int
    end_ms: int | None
    text: str
    published_at: datetime | None
    sender_ref: str | None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.start_ms < 0:
            raise DomainValidationError("start_ms must be nonnegative")
        if self.end_ms is not None and self.end_ms < self.start_ms:
            raise DomainValidationError("end_ms must be greater than or equal to start_ms")
        if self.published_at is not None:
            if self.published_at.tzinfo is None or self.published_at.utcoffset() is None:
                raise DomainValidationError("published_at must be timezone-aware")
            object.__setattr__(self, "published_at", self.published_at.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class TimedTextBatch:
    stream: TimedTextStreamDescriptor
    items: tuple[NormalizedTimedText, ...]
    raw_artifacts: tuple[RawArtifactRef, ...] = ()


def build_timed_text_dedup_key(
    item: NormalizedTimedText,
    content_type: TimedTextType,
) -> str:
    if item.platform_item_id is not None:
        payload = item.platform_item_id
    elif content_type is TimedTextType.SUBTITLE:
        end_ms = "" if item.end_ms is None else str(item.end_ms)
        payload = f"{item.start_ms}|{end_ms}|{item.text}"
    elif content_type is TimedTextType.DANMAKU:
        published_at = "" if item.published_at is None else item.published_at.isoformat()
        sender_ref = "" if item.sender_ref is None else item.sender_ref
        payload = f"{item.start_ms}|{published_at}|{sender_ref}|{item.text}"
    else:
        raise DomainValidationError(f"unsupported timed text type: {content_type!r}")
    return sha256(payload.encode("utf-8")).hexdigest()
