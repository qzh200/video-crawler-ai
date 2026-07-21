from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from testcontainers.minio import MinioContainer

from video_crawler.application.raw_artifacts import RawArtifactService
from video_crawler.infrastructure.database.models import (
    AuthProfile,
    CrawlJob,
    CrawlRun,
    Platform,
    RawArtifact,
    Video,
)
from video_crawler.infrastructure.database.repositories.artifacts import (
    SqlAlchemyRawArtifactRepository,
)
from video_crawler.infrastructure.database.session import DatabaseSessionFactory
from video_crawler.infrastructure.storage.minio import MinioRawArtifactStore

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def minio_client() -> Iterator[object]:
    with MinioContainer("minio/minio:RELEASE.2025-04-22T22-12-26Z") as minio:
        client = minio.get_client()
        client.make_bucket("crawler-raw")
        yield client


async def _seed_run(database: DatabaseSessionFactory) -> tuple[int, UUID]:
    now = datetime.now(UTC).replace(tzinfo=None)
    profile_id = uuid4()
    job_id = uuid4()
    run_id = uuid4()
    async with database.transaction() as session:
        platform = Platform(
            platform_key=f"storage-{uuid4().hex[:12]}",
            display_name="Storage test",
            adapter_version="1",
            created_at=now,
        )
        session.add(platform)
        await session.flush()
        session.add(
            AuthProfile(
                id=profile_id,
                platform_id=platform.id,
                profile_name="storage",
                profile_directory=f"storage-{uuid4().hex[:8]}",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        video = Video(
            platform_id=platform.id,
            platform_video_id="storage-video",
            canonical_url="https://example.test/storage-video",
            platform_ids={},
            first_discovered_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(video)
        await session.flush()
        session.add(
            CrawlJob(
                id=job_id,
                root_job_id=job_id,
                platform_id=platform.id,
                auth_profile_id=profile_id,
                video_id=video.id,
                source_url=video.canonical_url,
                job_type="video",
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
                video_id=video.id,
                attempt_no=1,
                worker_id="test",
                status="running",
                created_at=now,
            )
        )
        return int(video.id), run_id


async def test_verified_upload_and_interrupted_promotion_cleanup(
    database: DatabaseSessionFactory,
    minio_client: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_id, run_id = await _seed_run(database)
    storage = MinioRawArtifactStore(minio_client)  # type: ignore[arg-type]
    repository = SqlAlchemyRawArtifactRepository(database)
    service = RawArtifactService(storage, repository, retention_days=30)
    captured_at = datetime.now(UTC)

    stored = await service.store(
        b'{"views":10}',
        platform="test-platform",
        captured_at=captured_at,
        video_id="storage-video",
        database_video_id=video_id,
        run_id=run_id,
        artifact_name="metrics.json",
        artifact_type="metrics_response",
        content_type="application/json",
    )
    assert minio_client.stat_object(stored.bucket, stored.object_key).size == stored.size_bytes  # type: ignore[attr-defined]

    async def fail_copy(bucket: str, source_key: str, destination_key: str) -> object:
        del bucket, source_key, destination_key
        raise RuntimeError("promotion interrupted")

    monkeypatch.setattr(storage, "copy", fail_copy)
    with pytest.raises(RuntimeError, match="promotion interrupted"):
        await service.store(
            b"interrupted",
            platform="test-platform",
            captured_at=captured_at,
            video_id="storage-video",
            database_video_id=video_id,
            run_id=run_id,
            artifact_name="comments.json",
            content_type="application/json",
        )

    async with database() as session:
        rows = (await session.execute(select(RawArtifact))).scalars().all()
    assert {row.storage_status for row in rows} == {"available", "upload_failed"}
    failed = next(row for row in rows if row.storage_status == "upload_failed")
    temporary = tuple(minio_client.list_objects("crawler-raw", prefix=".tmp/", recursive=True))  # type: ignore[attr-defined]
    assert [item.object_name for item in temporary] == [f".tmp/{run_id}/{failed.id}"]

    summary = await service.cleanup_expired(captured_at + timedelta(days=31))
    assert summary.expired == 1
    assert summary.temporary_deleted == 1
    assert tuple(minio_client.list_objects("crawler-raw", recursive=True)) == ()  # type: ignore[attr-defined]
