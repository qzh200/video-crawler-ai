from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from video_crawler.application.cursors import (
    CommentCursor,
    CursorCodec,
    MetricCursor,
    TimedTextCursor,
)


@dataclass(frozen=True, slots=True)
class MetricValueRecord:
    value: int | None
    status: str


@dataclass(frozen=True, slots=True)
class MetricSnapshotRecord:
    snapshot_id: int
    captured_at: datetime
    metrics: Mapping[str, MetricValueRecord]


@dataclass(frozen=True, slots=True)
class CommentRecord:
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
    extra: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TimedTextRecord:
    id: int
    stream_id: int
    content_type: str
    language_code: str | None
    start_ms: int
    end_ms: int | None
    text: str
    published_at: datetime | None
    sender_ref: str | None
    attributes: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ResultPage[T]:
    items: tuple[T, ...]
    next_cursor: str | None


class ResultQueryStore(Protocol):
    async def list_metric_snapshots(
        self,
        video_id: int,
        *,
        after: tuple[datetime, int] | None,
        limit: int,
    ) -> list[MetricSnapshotRecord]: ...

    async def latest_metric_snapshot(self, video_id: int) -> MetricSnapshotRecord | None: ...

    async def list_comments(
        self,
        video_id: int,
        *,
        after: tuple[datetime | None, int] | None,
        limit: int,
        root_only: bool,
        root_comment_id: int | None,
        order: Literal["asc", "desc"],
    ) -> list[CommentRecord]: ...

    async def list_timed_text(
        self,
        unit_id: int,
        *,
        after: tuple[int, int] | None,
        limit: int,
        content_type: Literal["danmaku", "subtitle"] | None,
        language_code: str | None,
        start_ms: int | None,
        end_ms: int | None,
    ) -> list[TimedTextRecord]: ...


class ResultQueryService:
    def __init__(self, *, store: ResultQueryStore, cursor_codec: CursorCodec) -> None:
        self._store = store
        self._cursor_codec = cursor_codec

    async def list_metrics(
        self, video_id: int, *, cursor: str | None, page_size: int
    ) -> ResultPage[MetricSnapshotRecord]:
        decoded = self._cursor_codec.decode_metric(cursor) if cursor is not None else None
        after = (decoded.captured_at, decoded.id) if decoded is not None else None
        rows = await self._store.list_metric_snapshots(video_id, after=after, limit=page_size + 1)
        items = rows[:page_size]
        next_cursor = None
        if len(rows) > page_size and items:
            last = items[-1]
            next_cursor = self._cursor_codec.encode_metric(
                MetricCursor(captured_at=last.captured_at, id=last.snapshot_id)
            )
        return ResultPage(items=tuple(items), next_cursor=next_cursor)

    async def latest_metric(self, video_id: int) -> MetricSnapshotRecord | None:
        return await self._store.latest_metric_snapshot(video_id)

    async def list_comments(
        self,
        video_id: int,
        *,
        cursor: str | None,
        page_size: int,
        root_only: bool,
        root_comment_id: int | None,
        order: Literal["asc", "desc"],
    ) -> ResultPage[CommentRecord]:
        decoded = self._cursor_codec.decode_comment(cursor) if cursor is not None else None
        after = (decoded.published_at, decoded.id) if decoded is not None else None
        rows = await self._store.list_comments(
            video_id,
            after=after,
            limit=page_size + 1,
            root_only=root_only,
            root_comment_id=root_comment_id,
            order=order,
        )
        items = rows[:page_size]
        next_cursor = None
        if len(rows) > page_size and items:
            last = items[-1]
            next_cursor = self._cursor_codec.encode_comment(
                CommentCursor(published_at=last.published_at, id=last.id)
            )
        return ResultPage(items=tuple(items), next_cursor=next_cursor)

    async def list_timed_text(
        self,
        unit_id: int,
        *,
        cursor: str | None,
        page_size: int,
        content_type: Literal["danmaku", "subtitle"] | None,
        language_code: str | None,
        start_ms: int | None,
        end_ms: int | None,
    ) -> ResultPage[TimedTextRecord]:
        decoded = self._cursor_codec.decode_timed_text(cursor) if cursor is not None else None
        after = (decoded.start_ms, decoded.id) if decoded is not None else None
        rows = await self._store.list_timed_text(
            unit_id,
            after=after,
            limit=page_size + 1,
            content_type=content_type,
            language_code=language_code,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        items = rows[:page_size]
        next_cursor = None
        if len(rows) > page_size and items:
            last = items[-1]
            next_cursor = self._cursor_codec.encode_timed_text(
                TimedTextCursor(start_ms=last.start_ms, id=last.id)
            )
        return ResultPage(items=tuple(items), next_cursor=next_cursor)
