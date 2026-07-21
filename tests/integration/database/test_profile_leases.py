from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from video_crawler.application.auth_profiles import ProfileLeaseService
from video_crawler.infrastructure.database.models import (
    AuthProfile,
    CrawlJob,
    CrawlRun,
    Platform,
)
from video_crawler.infrastructure.database.session import DatabaseSessionFactory

pytestmark = pytest.mark.integration


async def _seed_profile_and_runs(
    database: DatabaseSessionFactory,
    now: datetime,
) -> tuple[UUID, UUID, UUID]:
    profile_id = uuid4()
    first_job_id = uuid4()
    second_job_id = uuid4()
    first_run_id = uuid4()
    second_run_id = uuid4()
    async with database.transaction() as session:
        platform = Platform(
            platform_key=f"lease-test-{profile_id}",
            display_name="Lease Test",
            adapter_version="1",
            enabled=True,
            created_at=now,
        )
        session.add(platform)
        await session.flush()
        session.add(
            AuthProfile(
                id=profile_id,
                platform_id=platform.id,
                profile_name="main",
                profile_directory=f"profile-{profile_id}",
                status="active",
                last_verified_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        for job_id in (first_job_id, second_job_id):
            session.add(
                CrawlJob(
                    id=job_id,
                    root_job_id=job_id,
                    auth_profile_id=profile_id,
                    source_url="https://example.test/video",
                    job_type="single_video",
                    status="running",
                    effective_strategy={},
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.flush()
        session.add_all(
            [
                CrawlRun(
                    id=first_run_id,
                    job_id=first_job_id,
                    attempt_no=1,
                    worker_id="worker-1",
                    status="running",
                    created_at=now,
                ),
                CrawlRun(
                    id=second_run_id,
                    job_id=second_job_id,
                    attempt_no=1,
                    worker_id="worker-2",
                    status="running",
                    created_at=now,
                ),
            ]
        )
    return profile_id, first_run_id, second_run_id


async def test_concurrent_profile_lease_acquisitions_have_one_winner(
    database: DatabaseSessionFactory,
) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    profile_id, first_run_id, second_run_id = await _seed_profile_and_runs(database, now)
    leases = ProfileLeaseService(database, lease_ttl=timedelta(seconds=30))

    results = await asyncio.gather(
        leases.acquire(profile_id, "worker-1", first_run_id, now),
        leases.acquire(profile_id, "worker-2", second_run_id, now),
    )

    assert results.count(True) == 1
    assert results.count(False) == 1
    released = await asyncio.gather(
        leases.release(profile_id, first_run_id),
        leases.release(profile_id, second_run_id),
    )
    assert released.count(True) == 1


async def test_profile_lease_is_exclusive_and_reacquirable_after_reap(
    database: DatabaseSessionFactory,
) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    profile_id, first_run_id, second_run_id = await _seed_profile_and_runs(database, now)
    leases = ProfileLeaseService(database, lease_ttl=timedelta(seconds=30))

    first = await leases.acquire(profile_id, "worker-1", first_run_id, now, process_pid=101)
    second = await leases.acquire(profile_id, "worker-2", second_run_id, now, process_pid=202)

    assert first is True
    assert second is False
    assert await leases.reap_expired(now + timedelta(seconds=29)) == 0
    assert await leases.reap_expired(now + timedelta(seconds=30)) == 1
    assert (
        await leases.acquire(
            profile_id,
            "worker-2",
            second_run_id,
            now + timedelta(seconds=30),
            process_pid=202,
        )
        is True
    )


async def test_heartbeat_and_release_require_the_owning_run(
    database: DatabaseSessionFactory,
) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    profile_id, first_run_id, second_run_id = await _seed_profile_and_runs(database, now)
    leases = ProfileLeaseService(database, lease_ttl=timedelta(seconds=30))
    assert await leases.acquire(profile_id, "worker-1", first_run_id, now)

    assert await leases.heartbeat(profile_id, second_run_id, now + timedelta(seconds=10)) is False
    assert await leases.release(profile_id, second_run_id) is False
    assert await leases.heartbeat(profile_id, first_run_id, now + timedelta(seconds=10)) is True
    assert await leases.reap_expired(now + timedelta(seconds=39)) == 0
    assert await leases.release(profile_id, first_run_id) is True
    assert await leases.acquire(profile_id, "worker-2", second_run_id, now) is True
