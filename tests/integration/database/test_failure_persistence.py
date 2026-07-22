from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from video_crawler.domain.errors import DiscoveryEmptyError
from video_crawler.infrastructure.database.models import (
    AuthProfile,
    CrawlJob,
    CrawlModuleRun,
    CrawlRun,
    Platform,
)
from video_crawler.infrastructure.database.repositories.jobs import (
    SqlAlchemyModuleStateStore,
    SqlAlchemyWorkerStateStore,
)
from video_crawler.infrastructure.database.session import DatabaseSessionFactory

pytestmark = pytest.mark.integration


async def _insert_running_job(database: DatabaseSessionFactory) -> tuple[UUID, UUID]:
    now = datetime.now(UTC).replace(tzinfo=None)
    profile_id = uuid4()
    job_id = uuid4()
    run_id = uuid4()
    async with database.transaction() as session:
        platform = Platform(
            platform_key=f"failure-{uuid4().hex[:12]}",
            display_name="Failure fixture",
            adapter_version="1",
            created_at=now,
        )
        session.add(platform)
        await session.flush()
        session.add(
            AuthProfile(
                id=profile_id,
                platform_id=platform.id,
                profile_name="failure-profile",
                profile_directory=f"failure-{uuid4().hex[:8]}",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            CrawlJob(
                id=job_id,
                root_job_id=job_id,
                platform_id=platform.id,
                auth_profile_id=profile_id,
                source_url="https://example.test/list",
                job_type="list",
                status="running",
                effective_strategy={},
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            CrawlRun(
                id=run_id,
                job_id=job_id,
                attempt_no=1,
                worker_id="failure-worker",
                status="running",
                started_at=now,
                created_at=now,
            )
        )
    return job_id, run_id


@pytest.mark.asyncio
async def test_coded_module_failure_is_exposed_on_the_finished_run(
    database: DatabaseSessionFactory,
) -> None:
    job_id, run_id = await _insert_running_job(database)
    states = SqlAlchemyModuleStateStore(database, run_id)
    await states.mark_running("discovery")
    await states.mark_failed(
        "discovery",
        DiscoveryEmptyError(
            {
                "captured_responses": 0,
                "captured_candidates": 0,
                "dom_candidates": 0,
                "http_candidates": 0,
            }
        ),
    )

    worker_states = SqlAlchemyWorkerStateStore(database)
    await worker_states.mark_finished(job_id, run_id, "failed", datetime.now(UTC))

    async with database() as session:
        module = await session.scalar(
            select(CrawlModuleRun).where(CrawlModuleRun.crawl_run_id == run_id)
        )
        run = await session.get(CrawlRun, run_id)
        job = await session.get(CrawlJob, job_id)
    assert module is not None
    assert module.error_code == "DISCOVERY_EMPTY"
    assert module.error_message == "list discovery returned no valid targets"
    assert module.result_summary == {
        "captured_responses": 0,
        "captured_candidates": 0,
        "dom_candidates": 0,
        "http_candidates": 0,
    }
    assert run is not None and run.error_code == "DISCOVERY_EMPTY"
    assert run.error_message == "list discovery returned no valid targets"
    assert run.result_summary == {
        "module": "discovery",
        "details": module.result_summary,
    }
    assert job is not None and job.status == "failed"
