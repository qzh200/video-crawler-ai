from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from video_crawler.domain.artifacts import RawArtifactRef
from video_crawler.domain.errors import DomainValidationError


@dataclass(frozen=True, slots=True)
class NormalizedComment:
    platform_comment_id: str
    root_platform_comment_id: str | None
    parent_platform_comment_id: str | None
    author_platform_id: str | None
    author_name: str | None
    content: str
    like_count: int | None
    reply_count: int | None
    published_at: datetime | None
    status: str
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.like_count is not None and self.like_count < 0:
            raise DomainValidationError("like_count must be nonnegative")
        if self.reply_count is not None and self.reply_count < 0:
            raise DomainValidationError("reply_count must be nonnegative")
        if self.published_at is not None:
            if self.published_at.tzinfo is None or self.published_at.utcoffset() is None:
                raise DomainValidationError("published_at must be timezone-aware")
            object.__setattr__(self, "published_at", self.published_at.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class CommentBatch:
    items: tuple[NormalizedComment, ...]
    cursor: str | None
    has_more: bool
    raw_artifacts: tuple[RawArtifactRef, ...] = ()
