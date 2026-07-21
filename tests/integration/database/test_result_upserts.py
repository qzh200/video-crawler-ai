from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from video_crawler.domain.comments import CommentBatch, NormalizedComment
from video_crawler.domain.metrics import MetricResult, MetricStatus, MetricValue
from video_crawler.domain.timed_text import (
    NormalizedTimedText,
    TimedTextBatch,
    TimedTextStreamDescriptor,
    TimedTextType,
)
from video_crawler.infrastructure.database.models import (
    AuthProfile,
    Comment,
    CrawlJob,
    CrawlRun,
    MetricSnapshot,
    Platform,
    TimedTextItem,
    Video,
)
from video_crawler.infrastructure.database.repositories.content import ContentRepository
from video_crawler.infrastructure.database.repositories.results import ResultRepository
from video_crawler.infrastructure.database.session import DatabaseSessionFactory

pytestmark = pytest.mark.integration


async def _seed_video(database: DatabaseSessionFactory) -> tuple[int, UUID]:
    now = datetime.now(UTC)
    profile_id = uuid4()
    job_id = uuid4()
    run_id = uuid4()
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
        video = Video(
            platform_id=platform.id,
            platform_video_id="video-1",
            canonical_url="https://example.test/video-1",
            platform_ids={},
            first_discovered_at=now.replace(tzinfo=None),
            created_at=now.replace(tzinfo=None),
            updated_at=now.replace(tzinfo=None),
        )
        session.add(video)
        await session.flush()
        session.add(
            CrawlJob(
                id=job_id,
                root_job_id=job_id,
                auth_profile_id=profile_id,
                platform_id=platform.id,
                video_id=video.id,
                source_url=video.canonical_url,
                job_type="video",
                status="running",
                effective_strategy={},
                created_at=now.replace(tzinfo=None),
                updated_at=now.replace(tzinfo=None),
            )
        )
        session.add(
            CrawlRun(
                id=run_id,
                job_id=job_id,
                video_id=video.id,
                attempt_no=1,
                worker_id="test",
                status="running",
                created_at=now.replace(tzinfo=None),
            )
        )
        return int(video.id), run_id


async def test_result_writes_are_idempotent_and_snapshots_are_distinct(
    database: DatabaseSessionFactory,
) -> None:
    video_id, run_id = await _seed_video(database)
    now = datetime.now(UTC)
    comments = CommentBatch(
        items=(
            NormalizedComment("root", None, None, None, "root", "hello", 1, 1, now, "visible"),
            NormalizedComment(
                "reply", "root", "root", None, "reply", "world", 0, 0, now, "visible"
            ),
        ),
        cursor=None,
        has_more=False,
    )
    results = ResultRepository(database)
    assert await results.upsert_comments(video_id, comments, now=now) == 2
    assert await results.upsert_comments(video_id, comments, now=now) == 2

    content = ContentRepository(database)
    await content.upsert_video_unit(
        video_id=video_id, platform_unit_id="unit-1", unit_index=0, now=now
    )
    timed = TimedTextBatch(
        stream=TimedTextStreamDescriptor("unit-1", TimedTextType.SUBTITLE, "zh", "zh-CN", "json"),
        items=(NormalizedTimedText(None, 0, 1000, "hello", None, None),),
    )
    assert await results.upsert_timed_text_batch(video_id, timed, now=now) == 1
    assert await results.upsert_timed_text_batch(video_id, timed, now=now) == 1

    metric = MetricResult({"standard.views": MetricValue(10, MetricStatus.AVAILABLE)})
    await results.create_metric_snapshot(video_id, run_id, metric, captured_at=now)
    await results.create_metric_snapshot(video_id, run_id, metric, captured_at=now)
    async with database() as session:
        assert await session.scalar(select(func.count()).select_from(Comment)) == 2
        assert await session.scalar(select(func.count()).select_from(TimedTextItem)) == 1
        assert await session.scalar(select(func.count()).select_from(MetricSnapshot)) == 2
