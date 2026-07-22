from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from video_crawler.domain.targets import DiscoveredTarget
from video_crawler.infrastructure.database.models import TargetDiscovery, Video, VideoUnit
from video_crawler.infrastructure.database.session import DatabaseSessionFactory


def _db_time(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


class ContentRepository:
    def __init__(self, sessions: DatabaseSessionFactory) -> None:
        self.sessions = sessions

    async def upsert_video(
        self,
        *,
        platform_id: int,
        target: DiscoveredTarget,
        now: datetime,
    ) -> int:
        async with self.sessions.transaction() as session:
            return await self._upsert_video(session, platform_id, target, now)

    async def _upsert_video(
        self, session: AsyncSession, platform_id: int, target: DiscoveredTarget, now: datetime
    ) -> int:
        values: dict[str, Any] = {
            "platform_id": platform_id,
            "platform_video_id": target.platform_video_id,
            "canonical_url": target.canonical_url,
            "platform_ids": dict(target.platform_ids),
            "first_discovered_at": _db_time(now),
            "created_at": _db_time(now),
            "updated_at": _db_time(now),
        }
        stmt = insert(Video).values(values)
        stmt = stmt.on_duplicate_key_update(
            canonical_url=stmt.inserted.canonical_url,
            platform_ids=stmt.inserted.platform_ids,
            updated_at=stmt.inserted.updated_at,
        )
        await session.execute(stmt)
        return int(
            (
                await session.execute(
                    select(Video.id).where(
                        Video.platform_id == platform_id,
                        Video.platform_video_id == target.platform_video_id,
                    )
                )
            ).scalar_one()
        )

    async def record_discovery(
        self,
        *,
        crawl_run_id: Any,
        video_id: int,
        source_url: str,
        position: int | None,
        now: datetime,
    ) -> None:
        async with self.sessions.transaction() as session:
            stmt = insert(TargetDiscovery).values(
                crawl_run_id=crawl_run_id,
                video_id=video_id,
                source_url=source_url,
                position=position,
                discovered_at=_db_time(now),
            )
            stmt = stmt.on_duplicate_key_update(
                source_url=stmt.inserted.source_url,
                position=stmt.inserted.position,
            )
            await session.execute(stmt)

    async def upsert_video_unit(
        self,
        *,
        video_id: int,
        platform_unit_id: str,
        unit_index: int,
        now: datetime,
        duration_ms: int | None = None,
        platform_ids: dict[str, str | int] | None = None,
    ) -> int:
        async with self.sessions.transaction() as session:
            values = {
                "video_id": video_id,
                "platform_unit_id": platform_unit_id,
                "unit_index": unit_index,
                "duration_ms": duration_ms,
                "platform_ids": platform_ids or {},
                "created_at": _db_time(now),
                "updated_at": _db_time(now),
            }
            stmt = insert(VideoUnit).values(values)
            stmt = stmt.on_duplicate_key_update(
                duration_ms=stmt.inserted.duration_ms,
                platform_ids=stmt.inserted.platform_ids,
                updated_at=stmt.inserted.updated_at,
            )
            await session.execute(stmt)
            return int(
                (
                    await session.execute(
                        select(VideoUnit.id).where(
                            VideoUnit.video_id == video_id,
                            VideoUnit.platform_unit_id == platform_unit_id,
                        )
                    )
                ).scalar_one()
            )

    async def ensure_video_unit(
        self,
        *,
        video_id: int,
        platform_unit_id: str,
        now: datetime,
    ) -> int:
        """Return an existing unit or create the next generic unit index."""

        async with self.sessions.transaction() as session:
            existing = (
                await session.execute(
                    select(VideoUnit.id).where(
                        VideoUnit.video_id == video_id,
                        VideoUnit.platform_unit_id == platform_unit_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return int(existing)
            maximum = await session.scalar(
                select(func.max(VideoUnit.unit_index)).where(VideoUnit.video_id == video_id)
            )
            unit_index = int(maximum) + 1 if maximum is not None else 0
            current = _db_time(now)
            unit = VideoUnit(
                video_id=video_id,
                platform_unit_id=platform_unit_id,
                unit_index=unit_index,
                duration_ms=None,
                platform_ids={},
                created_at=current,
                updated_at=current,
            )
            session.add(unit)
            await session.flush()
            return int(unit.id)
