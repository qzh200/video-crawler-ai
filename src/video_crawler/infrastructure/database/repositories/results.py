from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.mysql import insert

from video_crawler.domain.comments import CommentBatch
from video_crawler.domain.metrics import MetricResult
from video_crawler.domain.timed_text import (
    TimedTextBatch,
    build_timed_text_dedup_key,
)
from video_crawler.infrastructure.database.models import (
    Comment,
    MetricSnapshot,
    MetricValue,
    TimedTextItem,
    TimedTextStream,
    VideoUnit,
)
from video_crawler.infrastructure.database.session import DatabaseSessionFactory


def _db_time(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


class ResultRepository:
    def __init__(self, sessions: DatabaseSessionFactory) -> None:
        self.sessions = sessions

    async def upsert_comments(
        self,
        video_id: int,
        batch: CommentBatch,
        *,
        now: datetime | None = None,
    ) -> int:
        observed_at = _db_time(now or datetime.now(UTC))
        async with self.sessions.transaction() as session:
            for item in batch.items:
                values = {
                    "video_id": video_id,
                    "platform_comment_id": item.platform_comment_id,
                    "root_platform_comment_id": item.root_platform_comment_id,
                    "parent_platform_comment_id": item.parent_platform_comment_id,
                    "depth": 0 if item.parent_platform_comment_id is None else 1,
                    "author_platform_id": item.author_platform_id,
                    "author_name": item.author_name,
                    "content": item.content,
                    "like_count": item.like_count,
                    "reply_count": item.reply_count,
                    "published_at": _db_time(item.published_at) if item.published_at else None,
                    "first_seen_at": observed_at,
                    "last_seen_at": observed_at,
                    "status": item.status,
                    "extra": dict(item.attributes),
                    "created_at": observed_at,
                    "updated_at": observed_at,
                }
                stmt = insert(Comment).values(values)
                stmt = stmt.on_duplicate_key_update(
                    root_platform_comment_id=stmt.inserted.root_platform_comment_id,
                    parent_platform_comment_id=stmt.inserted.parent_platform_comment_id,
                    author_platform_id=stmt.inserted.author_platform_id,
                    author_name=stmt.inserted.author_name,
                    content=stmt.inserted.content,
                    like_count=stmt.inserted.like_count,
                    reply_count=stmt.inserted.reply_count,
                    published_at=stmt.inserted.published_at,
                    last_seen_at=stmt.inserted.last_seen_at,
                    status=stmt.inserted.status,
                    extra=stmt.inserted.extra,
                    updated_at=stmt.inserted.updated_at,
                )
                await session.execute(stmt)

            ids = (
                await session.execute(
                    select(Comment.id, Comment.platform_comment_id).where(
                        Comment.video_id == video_id
                    )
                )
            ).all()
            by_platform = {platform_id: row_id for row_id, platform_id in ids}
            for item in batch.items:
                row_id = by_platform[item.platform_comment_id]
                root_id = (
                    by_platform.get(item.root_platform_comment_id)
                    if item.root_platform_comment_id
                    and item.root_platform_comment_id != item.platform_comment_id
                    else None
                )
                parent_id = by_platform.get(item.parent_platform_comment_id)
                await session.execute(
                    update(Comment)
                    .where(Comment.id == row_id)
                    .values(
                        root_comment_id=root_id,
                        parent_comment_id=parent_id,
                    )
                )
        return len(batch.items)

    async def upsert_timed_text_batch(
        self,
        video_id: int,
        batch: TimedTextBatch,
        *,
        now: datetime | None = None,
    ) -> int:
        observed_at = _db_time(now or datetime.now(UTC))
        async with self.sessions.transaction() as session:
            unit_id = (
                await session.execute(
                    select(VideoUnit.id).where(
                        VideoUnit.video_id == video_id,
                        VideoUnit.platform_unit_id == batch.stream.platform_unit_id,
                    )
                )
            ).scalar_one_or_none()
            if unit_id is None:
                raise ValueError("video unit must exist before timed text is stored")
            language = (batch.stream.language_code or "").strip().lower()
            stream_values = {
                "video_unit_id": unit_id,
                "content_type": batch.stream.content_type.value,
                "stream_key": batch.stream.stream_key,
                "language_code": batch.stream.language_code,
                "language_code_normalized": language,
                "source_type": batch.stream.source_type,
                "captured_at": observed_at,
                "attributes": dict(batch.stream.attributes),
                "created_at": observed_at,
                "updated_at": observed_at,
            }
            stream_stmt = insert(TimedTextStream).values(stream_values)
            stream_stmt = stream_stmt.on_duplicate_key_update(
                language_code=stream_stmt.inserted.language_code,
                source_type=stream_stmt.inserted.source_type,
                captured_at=stream_stmt.inserted.captured_at,
                attributes=stream_stmt.inserted.attributes,
                updated_at=stream_stmt.inserted.updated_at,
            )
            await session.execute(stream_stmt)
            stream_id = (
                await session.execute(
                    select(TimedTextStream.id).where(
                        TimedTextStream.video_unit_id == unit_id,
                        TimedTextStream.content_type == batch.stream.content_type.value,
                        TimedTextStream.stream_key == batch.stream.stream_key,
                        TimedTextStream.language_code_normalized == language,
                    )
                )
            ).scalar_one()
            for item in batch.items:
                values = {
                    "stream_id": stream_id,
                    "platform_item_id": item.platform_item_id,
                    "dedup_key": build_timed_text_dedup_key(item, batch.stream.content_type),
                    "start_ms": item.start_ms,
                    "end_ms": item.end_ms,
                    "text": item.text,
                    "published_at": _db_time(item.published_at) if item.published_at else None,
                    "sender_ref": item.sender_ref,
                    "attributes": dict(item.attributes),
                    "first_seen_at": observed_at,
                    "last_seen_at": observed_at,
                    "created_at": observed_at,
                    "updated_at": observed_at,
                }
                stmt = insert(TimedTextItem).values(values)
                stmt = stmt.on_duplicate_key_update(
                    platform_item_id=stmt.inserted.platform_item_id,
                    end_ms=stmt.inserted.end_ms,
                    text=stmt.inserted.text,
                    published_at=stmt.inserted.published_at,
                    sender_ref=stmt.inserted.sender_ref,
                    attributes=stmt.inserted.attributes,
                    last_seen_at=stmt.inserted.last_seen_at,
                    updated_at=stmt.inserted.updated_at,
                )
                await session.execute(stmt)
        return len(batch.items)

    async def create_metric_snapshot(
        self,
        video_id: int,
        crawl_run_id: UUID,
        result: MetricResult,
        *,
        captured_at: datetime | None = None,
        raw_artifact_id: int | None = None,
    ) -> int:
        captured = _db_time(captured_at or datetime.now(UTC))
        payload = {
            key: {
                "value": metric.value,
                "status": metric.status.value,
                "source_path": metric.source_path,
                "extra": dict(metric.extra),
            }
            for key, metric in sorted(result.values.items())
        }
        snapshot_hash = sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        async with self.sessions.transaction() as session:
            snapshot = MetricSnapshot(
                video_id=video_id,
                crawl_run_id=crawl_run_id,
                captured_at=captured,
                snapshot_hash=snapshot_hash,
                raw_artifact_id=raw_artifact_id,
                created_at=captured,
            )
            session.add(snapshot)
            await session.flush()
            for key, metric in result.values.items():
                session.add(
                    MetricValue(
                        snapshot_id=snapshot.id,
                        metric_key=key,
                        metric_value=metric.value,
                        status=metric.status.value,
                        source_path=metric.source_path,
                        extra=dict(metric.extra),
                    )
                )
            return int(snapshot.id)
