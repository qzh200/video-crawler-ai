from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from video_crawler.infrastructure.database.models import AuthProfile, CrawlJob, Platform
from video_crawler.infrastructure.database.repositories.jobs import JobRepository
from video_crawler.infrastructure.database.session import DatabaseSessionFactory

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_claim_next_pauses_jobs_for_inactive_profiles(
    database: DatabaseSessionFactory,
) -> None:
    now = datetime.now(UTC)
    active_profile_id = UUID(int=101)
    expired_profile_id = UUID(int=102)
    active_job_id = UUID(int=201)
    expired_job_id = UUID(int=202)
    async with database.transaction() as session:
        platform = Platform(
            platform_key=f"test-{uuid4().hex[:12]}",
            display_name="Test",
            adapter_version="1",
            created_at=now.replace(tzinfo=None),
        )
        session.add(platform)
        await session.flush()
        session.add_all(
            [
                AuthProfile(
                    id=active_profile_id,
                    platform_id=platform.id,
                    profile_name="active",
                    profile_directory=f"active-{uuid4().hex[:8]}",
                    status="active",
                    created_at=now.replace(tzinfo=None),
                    updated_at=now.replace(tzinfo=None),
                ),
                AuthProfile(
                    id=expired_profile_id,
                    platform_id=platform.id,
                    profile_name="expired",
                    profile_directory=f"expired-{uuid4().hex[:8]}",
                    status="expired",
                    created_at=now.replace(tzinfo=None),
                    updated_at=now.replace(tzinfo=None),
                ),
            ]
        )
        await session.flush()
        for job_id, profile_id in (
            (active_job_id, active_profile_id),
            (expired_job_id, expired_profile_id),
        ):
            session.add(
                CrawlJob(
                    id=job_id,
                    root_job_id=job_id,
                    platform_id=platform.id,
                    auth_profile_id=profile_id,
                    source_url="https://example.test/video",
                    job_type="video",
                    status="pending",
                    effective_strategy={},
                    created_at=now.replace(tzinfo=None),
                    updated_at=now.replace(tzinfo=None),
                )
            )

    repository = JobRepository(database)
    first = await repository.claim_next("worker", now)
    second = await repository.claim_next("worker", now)

    assert first is not None and first.id == active_job_id
    assert second is None

    async with database.transaction() as session:
        profile = await session.get(AuthProfile, expired_profile_id)
        assert profile is not None
        profile.status = "active"
    resumed = await repository.claim_next("worker", now)
    assert resumed is not None and resumed.id == expired_job_id


async def test_claim_next_skips_locked_jobs(database: DatabaseSessionFactory) -> None:
    now = datetime.now(UTC)
    profile_id = uuid4()
    job_ids = [uuid4(), uuid4()]
    async with database.transaction() as session:
        platform = Platform(
            platform_key=f"test-{uuid4().hex[:12]}",
            display_name="Test",
            adapter_version="1",
            created_at=now.replace(tzinfo=None),
        )
        session.add(platform)
        await session.flush()
        session.add(
            AuthProfile(
                id=profile_id,
                platform_id=platform.id,
                profile_name="test",
                profile_directory=f"test-{uuid4().hex[:8]}",
                status="active",
                created_at=now.replace(tzinfo=None),
                updated_at=now.replace(tzinfo=None),
            )
        )
        await session.flush()
        for job_id in job_ids:
            session.add(
                CrawlJob(
                    id=job_id,
                    parent_job_id=None,
                    root_job_id=job_id,
                    platform_id=platform.id,
                    auth_profile_id=profile_id,
                    source_url="https://example.test/video",
                    job_type="video",
                    status="pending",
                    effective_strategy={},
                    created_at=now.replace(tzinfo=None),
                    updated_at=now.replace(tzinfo=None),
                )
            )

    repository = JobRepository(database)
    async with database() as session_a, database() as session_b:
        async with session_a.begin(), session_b.begin():
            claimed = await asyncio.gather(
                repository.claim_next("worker-a", now, session=session_a),
                repository.claim_next("worker-b", now, session=session_b),
            )
    assert {job.id for job in claimed if job is not None} == set(job_ids)

    async with database() as session:
        statuses = dict(
            (
                await session.execute(
                    select(CrawlJob.id, CrawlJob.status).where(CrawlJob.id.in_(job_ids))
                )
            ).all()
        )
    assert statuses == {job_id: "running" for job_id in job_ids}
