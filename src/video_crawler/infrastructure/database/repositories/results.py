from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.mysql import insert

from video_crawler.application.result_queries import (
    CommentRecord,
    MetricSnapshotRecord,
    MetricValueRecord,
    TimedTextRecord,
)
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

    async def list_metric_snapshots(
        self,
        video_id: int,
        *,
        after: tuple[datetime, int] | None,
        limit: int,
    ) -> list[MetricSnapshotRecord]:
        async with self.sessions() as session:
            statement = select(MetricSnapshot).where(MetricSnapshot.video_id == video_id)
            if after is not None:
                captured_at = _db_time(after[0])
                statement = statement.where(
                    or_(
                        MetricSnapshot.captured_at < captured_at,
                        and_(
                            MetricSnapshot.captured_at == captured_at,
                            MetricSnapshot.id < after[1],
                        ),
                    )
                )
            snapshots = (
                (
                    await session.execute(
                        statement.order_by(
                            MetricSnapshot.captured_at.desc(),
                            MetricSnapshot.id.desc(),
                        ).limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            snapshot_ids = [snapshot.id for snapshot in snapshots]
            values_by_snapshot: dict[int, dict[str, MetricValueRecord]] = {
                snapshot_id: {} for snapshot_id in snapshot_ids
            }
            if snapshot_ids:
                values = (
                    await session.execute(
                        select(MetricValue).where(MetricValue.snapshot_id.in_(snapshot_ids))
                    )
                ).scalars()
                for value in values:
                    values_by_snapshot[value.snapshot_id][value.metric_key] = MetricValueRecord(
                        value=value.metric_value,
                        status=value.status,
                    )
        return [
            MetricSnapshotRecord(
                snapshot_id=snapshot.id,
                captured_at=snapshot.captured_at.replace(tzinfo=UTC),
                metrics=values_by_snapshot[snapshot.id],
            )
            for snapshot in snapshots
        ]

    async def latest_metric_snapshot(self, video_id: int) -> MetricSnapshotRecord | None:
        rows = await self.list_metric_snapshots(video_id, after=None, limit=1)
        return rows[0] if rows else None

    async def list_comments(
        self,
        video_id: int,
        *,
        after: tuple[datetime | None, int] | None,
        limit: int,
        root_only: bool,
        root_comment_id: int | None,
        order: Literal["asc", "desc"],
    ) -> list[CommentRecord]:
        epoch = datetime(1970, 1, 1)
        published = func.coalesce(Comment.published_at, epoch)
        statement = select(Comment).where(Comment.video_id == video_id)
        if root_only:
            statement = statement.where(Comment.parent_comment_id.is_(None))
        if root_comment_id is not None:
            statement = statement.where(Comment.root_comment_id == root_comment_id)
        if after is not None:
            cursor_time = _db_time(after[0]) if after[0] is not None else epoch
            if order == "asc":
                statement = statement.where(
                    or_(
                        published > cursor_time,
                        and_(published == cursor_time, Comment.id > after[1]),
                    )
                )
            else:
                statement = statement.where(
                    or_(
                        published < cursor_time,
                        and_(published == cursor_time, Comment.id < after[1]),
                    )
                )
        ordering = (
            (published.asc(), Comment.id.asc())
            if order == "asc"
            else (published.desc(), Comment.id.desc())
        )
        async with self.sessions() as session:
            rows = (
                (await session.execute(statement.order_by(*ordering).limit(limit))).scalars().all()
            )
        return [
            CommentRecord(
                id=row.id,
                platform_comment_id=row.platform_comment_id,
                root_comment_id=row.root_comment_id,
                parent_comment_id=row.parent_comment_id,
                depth=row.depth,
                author_platform_id=row.author_platform_id,
                author_name=row.author_name,
                content=row.content,
                like_count=row.like_count,
                reply_count=row.reply_count,
                published_at=row.published_at.replace(tzinfo=UTC) if row.published_at else None,
                status=row.status,
                extra=dict(row.extra),
            )
            for row in rows
        ]

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
    ) -> list[TimedTextRecord]:
        statement = (
            select(TimedTextItem, TimedTextStream)
            .join(TimedTextStream, TimedTextItem.stream_id == TimedTextStream.id)
            .where(TimedTextStream.video_unit_id == unit_id)
        )
        if content_type is not None:
            statement = statement.where(TimedTextStream.content_type == content_type)
        if language_code is not None:
            statement = statement.where(
                TimedTextStream.language_code_normalized == language_code.strip().lower()
            )
        if start_ms is not None:
            statement = statement.where(TimedTextItem.start_ms >= start_ms)
        if end_ms is not None:
            statement = statement.where(TimedTextItem.start_ms <= end_ms)
        if after is not None:
            statement = statement.where(
                or_(
                    TimedTextItem.start_ms > after[0],
                    and_(
                        TimedTextItem.start_ms == after[0],
                        TimedTextItem.id > after[1],
                    ),
                )
            )
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    statement.order_by(TimedTextItem.start_ms.asc(), TimedTextItem.id.asc()).limit(
                        limit
                    )
                )
            ).all()
        return [
            TimedTextRecord(
                id=item.id,
                stream_id=item.stream_id,
                content_type=stream.content_type,
                language_code=stream.language_code,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                text=item.text,
                published_at=item.published_at.replace(tzinfo=UTC) if item.published_at else None,
                sender_ref=item.sender_ref,
                attributes=dict(item.attributes),
            )
            for item, stream in rows
        ]
