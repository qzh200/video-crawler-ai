from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from video_crawler.infrastructure.database.models import CrawlJob
from video_crawler.infrastructure.database.session import DatabaseSessionFactory


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: UUID
    root_job_id: UUID
    parent_job_id: UUID | None
    auth_profile_id: UUID
    source_url: str
    job_type: str
    effective_strategy: dict[str, Any]
    attempt_count: int


class JobRepository:
    def __init__(self, sessions: DatabaseSessionFactory) -> None:
        self.sessions = sessions

    async def claim_next(
        self,
        worker_id: str,
        now: datetime,
        *,
        session: AsyncSession | None = None,
    ) -> ClaimedJob | None:
        if session is not None:
            return await self._claim(session, worker_id, now)
        async with self.sessions.transaction() as session:
            return await self._claim(session, worker_id, now)

    async def _claim(
        self, session: AsyncSession, worker_id: str, now: datetime
    ) -> ClaimedJob | None:
        query = (
            select(CrawlJob)
            .where(
                CrawlJob.status == "pending",
                (CrawlJob.next_retry_at.is_(None) | (CrawlJob.next_retry_at <= now)),
            )
            # Ordering by the primary key avoids InnoDB next-key locks on the
            # non-unique claim index when multiple workers claim simultaneously.
            .order_by(CrawlJob.id.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        job = (await session.execute(query)).scalar_one_or_none()
        if job is None:
            return None
        job.status = "running"
        job.locked_by = worker_id
        job.locked_at = now
        job.heartbeat_at = now
        job.attempt_count += 1
        return ClaimedJob(
            id=job.id,
            root_job_id=job.root_job_id,
            parent_job_id=job.parent_job_id,
            auth_profile_id=job.auth_profile_id,
            source_url=job.source_url,
            job_type=job.job_type,
            effective_strategy=dict(job.effective_strategy),
            attempt_count=job.attempt_count,
        )
