from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from video_crawler.application.result_queries import (
    CommentRecord,
    MetricSnapshotRecord,
    TimedTextRecord,
)


class MetricValueResponse(BaseModel):
    value: int | None
    status: str


class MetricSnapshotResponse(BaseModel):
    snapshot_id: int
    captured_at: datetime
    metrics: dict[str, MetricValueResponse]

    @classmethod
    def from_record(cls, record: MetricSnapshotRecord) -> MetricSnapshotResponse:
        return cls(
            snapshot_id=record.snapshot_id,
            captured_at=record.captured_at,
            metrics={
                key: MetricValueResponse(value=value.value, status=value.status)
                for key, value in record.metrics.items()
            },
        )


class MetricPageResponse(BaseModel):
    items: list[MetricSnapshotResponse]
    next_cursor: str | None


class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_comment_id: str
    root_comment_id: int | None
    parent_comment_id: int | None
    depth: int
    author_platform_id: str | None
    author_name: str | None
    content: str
    like_count: int | None
    reply_count: int | None
    published_at: datetime | None
    status: str
    extra: dict[str, Any]

    @classmethod
    def from_record(cls, record: CommentRecord) -> CommentResponse:
        return cls.model_validate(record)


class CommentPageResponse(BaseModel):
    items: list[CommentResponse]
    next_cursor: str | None


class TimedTextResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stream_id: int
    content_type: str
    language_code: str | None
    start_ms: int
    end_ms: int | None
    text: str
    published_at: datetime | None
    sender_ref: str | None
    attributes: dict[str, Any]

    @classmethod
    def from_record(cls, record: TimedTextRecord) -> TimedTextResponse:
        return cls.model_validate(record)


class TimedTextPageResponse(BaseModel):
    items: list[TimedTextResponse]
    next_cursor: str | None
