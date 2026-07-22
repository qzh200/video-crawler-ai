from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from testcontainers.minio import MinioContainer

from video_crawler.adapters.base import AdapterContext
from video_crawler.adapters.registry import AdapterRegistry
from video_crawler.api.dependencies.auth import require_api_key
from video_crawler.bootstrap import ApplicationContainer
from video_crawler.core.config import Settings
from video_crawler.domain.comments import CommentBatch, NormalizedComment
from video_crawler.domain.metrics import MetricResult, MetricStatus, MetricValue
from video_crawler.domain.strategy import CrawlStrategy
from video_crawler.domain.targets import (
    DiscoveredTarget,
    ResolvedTarget,
    TargetKind,
    VideoTarget,
)
from video_crawler.domain.timed_text import (
    NormalizedTimedText,
    TimedTextBatch,
    TimedTextStreamDescriptor,
    TimedTextType,
)
from video_crawler.infrastructure.database.models import (
    Platform,
    RawArtifact,
    Video,
    VideoUnit,
)
from video_crawler.infrastructure.database.session import DatabaseSessionFactory
from video_crawler.infrastructure.storage.minio import MinioRawArtifactStore
from video_crawler.main import create_production_app
from video_crawler.worker.supervisor import WorkerSupervisor
from video_crawler.worker.task_entrypoint import run_task

pytestmark = pytest.mark.integration

PLATFORM_KEY = "fake-e2e"
SOURCE_URL = "https://fake.example/video/fixture-1"
PLATFORM_VIDEO_ID = "fixture-video-1"
PLATFORM_UNIT_ID = "fixture-unit-1"
NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def e2e_minio_client() -> Iterator[object]:
    with MinioContainer("minio/minio:RELEASE.2025-04-22T22-12-26Z") as minio:
        client = minio.get_client()
        client.make_bucket("crawler-raw")
        yield client


class FakeAdapter:
    platform_key = PLATFORM_KEY

    def match(self, url: str) -> bool:
        return url.startswith("https://fake.example/")

    async def verify_auth(self, context: AdapterContext) -> object:
        del context
        return SimpleNamespace(is_valid=True, reason=None, extra={})

    async def resolve_target(self, context: AdapterContext, url: str) -> ResolvedTarget:
        del context, url
        return ResolvedTarget(
            platform=PLATFORM_KEY,
            kind=TargetKind.SINGLE_VIDEO,
            canonical_url=SOURCE_URL,
            platform_video_id=PLATFORM_VIDEO_ID,
            platform_ids={"fixture_id": 1},
        )

    async def discover_targets(
        self,
        context: AdapterContext,
        target: ResolvedTarget,
        strategy: CrawlStrategy,
    ) -> AsyncIterator[DiscoveredTarget]:
        del context, target, strategy
        if False:
            yield DiscoveredTarget(PLATFORM_KEY, "unused", SOURCE_URL, None)

    async def fetch_metrics(
        self,
        context: AdapterContext,
        target: VideoTarget,
    ) -> MetricResult:
        artifact = await context.raw_artifacts.store(
            b'{"standard.views":321}',
            artifact_type="metrics",
            content_type="application/json",
            metadata={"platform_video_id": target.platform_video_id},
        )
        return MetricResult(
            values={
                "standard.views": MetricValue(
                    value=321,
                    status=MetricStatus.AVAILABLE,
                    source_path="fixture.standard.views",
                )
            },
            raw_artifacts=(artifact,),
        )

    async def fetch_comments(
        self,
        context: AdapterContext,
        target: VideoTarget,
        strategy: CrawlStrategy,
    ) -> AsyncIterator[CommentBatch]:
        del context, target, strategy
        yield CommentBatch(
            items=(
                NormalizedComment(
                    platform_comment_id="fixture-comment-1",
                    root_platform_comment_id=None,
                    parent_platform_comment_id=None,
                    author_platform_id="fixture-author-1",
                    author_name="Fixture Author",
                    content="Synthetic comment",
                    like_count=7,
                    reply_count=0,
                    published_at=NOW,
                    status="available",
                ),
            ),
            cursor=None,
            has_more=False,
        )

    async def fetch_timed_text(
        self,
        context: AdapterContext,
        target: VideoTarget,
        strategy: CrawlStrategy,
    ) -> AsyncIterator[TimedTextBatch]:
        del context, target, strategy
        yield TimedTextBatch(
            stream=TimedTextStreamDescriptor(
                platform_unit_id=PLATFORM_UNIT_ID,
                content_type=TimedTextType.SUBTITLE,
                stream_key="fixture-subtitle",
                language_code="en",
                source_type="json",
            ),
            items=(
                NormalizedTimedText(
                    platform_item_id="fixture-cue-1",
                    start_ms=1000,
                    end_ms=2500,
                    text="Synthetic subtitle",
                    published_at=None,
                    sender_ref=None,
                ),
            ),
        )


async def _seed_platform(database: DatabaseSessionFactory) -> None:
    now = NOW.replace(tzinfo=None)
    async with database.transaction() as session:
        platform = Platform(
            platform_key=PLATFORM_KEY,
            display_name="Fake E2E",
            adapter_version="1",
            created_at=now,
        )
        session.add(platform)


def _settings(profile_root: Path) -> Settings:
    return Settings(
        api_key_enabled=False,
        api_key="test-api-key",
        mysql_password="test-password",  # noqa: S106 - synthetic integration secret
        minio_secret_key="test-secret",  # noqa: S106 - synthetic integration secret
        browser_profile_root=profile_root,
        default_video_delay_min_seconds=0.5,
        default_video_delay_max_seconds=0.5,
        default_comment_page_delay_min_seconds=0.5,
        default_comment_page_delay_max_seconds=0.5,
    )


async def test_api_worker_and_storage_are_wired_end_to_end(
    database: DatabaseSessionFactory,
    e2e_minio_client: object,
    tmp_path: Path,
) -> None:
    await _seed_platform(database)
    container = ApplicationContainer(
        settings=_settings(tmp_path),
        sessions=database,
        object_store=MinioRawArtifactStore(e2e_minio_client),  # type: ignore[arg-type]
        adapter_registry=AdapterRegistry([FakeAdapter()]),
    )
    app = container.create_api_app()
    app.dependency_overrides[require_api_key] = lambda: None
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            profile = await client.post(
                "/api/v1/auth-profiles",
                json={
                    "platform": PLATFORM_KEY,
                    "profile_name": "fixture-profile",
                    "profile_directory": "fixture-profile",
                },
            )
            assert profile.status_code == 201
            profile_id = profile.json()["profile_id"]
            verification = await client.post(f"/api/v1/auth-profiles/{profile_id}/verify")
            assert verification.status_code == 202
            verification_id = UUID(verification.json()["verification_id"])
            now = datetime.now(UTC)
            claimed = await container.profile_verifications.claim_next(
                "integration-worker",
                now,
                stale_before=now - timedelta(seconds=30),
            )
            assert claimed is not None
            assert claimed.verification_id == verification_id
            await container.execute_profile_verification(verification_id)
            verified = await client.get(
                f"/api/v1/auth-profiles/{profile_id}/verifications/{verification_id}"
            )
            assert verified.status_code == 200
            assert verified.json()["status"] == "succeeded"
            assert verified.json()["profile_status"] == "active"
            created = await client.post(
                "/api/v1/crawl-jobs",
                json={
                    "source_url": SOURCE_URL,
                    "auth_profile_id": profile_id,
                    "strategy": {
                        "video_delay_min_seconds": 0.5,
                        "video_delay_max_seconds": 0.5,
                        "comment_page_delay_min_seconds": 0.5,
                        "comment_page_delay_max_seconds": 0.5,
                    },
                },
            )
            assert created.status_code == 202
            job_id = created.json()["job_id"]

            assert await container.run_worker_once(worker_id="integration-worker")

            job = await client.get(f"/api/v1/crawl-jobs/{job_id}")
            assert job.status_code == 200
            assert job.json()["status"] == "success"
            assert job.json()["module_states"] == {
                "metrics": "success",
                "comments": "success",
                "timed_text": "success",
            }

            async with database() as session:
                video_id = int(
                    (
                        await session.execute(
                            select(Video.id).where(Video.platform_video_id == PLATFORM_VIDEO_ID)
                        )
                    ).scalar_one()
                )
                unit_id = int(
                    (
                        await session.execute(
                            select(VideoUnit.id).where(
                                VideoUnit.video_id == video_id,
                                VideoUnit.platform_unit_id == PLATFORM_UNIT_ID,
                            )
                        )
                    ).scalar_one()
                )
                artifact = (
                    await session.execute(
                        select(RawArtifact).where(RawArtifact.storage_status == "available")
                    )
                ).scalar_one()

            metrics = await client.get(f"/api/v1/videos/{video_id}/metrics/latest")
            comments = await client.get(f"/api/v1/videos/{video_id}/comments")
            timed_text = await client.get(f"/api/v1/video-units/{unit_id}/timed-text")

            assert metrics.status_code == 200
            assert metrics.json()["metrics"]["standard.views"] == {
                "value": 321,
                "status": "available",
            }
            assert comments.status_code == 200
            assert [item["content"] for item in comments.json()["items"]] == ["Synthetic comment"]
            assert timed_text.status_code == 200
            assert [item["text"] for item in timed_text.json()["items"]] == ["Synthetic subtitle"]
            stat = e2e_minio_client.stat_object(artifact.bucket, artifact.object_key)  # type: ignore[attr-defined]
            assert stat.size == artifact.size_bytes
    finally:
        await container.aclose()


async def test_production_lifespan_and_worker_factory_use_the_same_container(
    database: DatabaseSessionFactory,
    e2e_minio_client: object,
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(
        settings=_settings(tmp_path),
        sessions=database,
        object_store=MinioRawArtifactStore(e2e_minio_client),  # type: ignore[arg-type]
        adapter_registry=AdapterRegistry([FakeAdapter()]),
    )
    app = create_production_app(container_factory=lambda: container)

    async with app.router.lifespan_context(app):
        assert app.state.job_service is container.job_service
        assert app.state.result_query_service is container.result_query_service
        assert isinstance(container.create_supervisor(), WorkerSupervisor)


class FakeTaskContainer:
    def __init__(self) -> None:
        self.executed: list[UUID] = []
        self.closed = False

    async def execute_run(self, run_id: UUID) -> object:
        self.executed.append(run_id)
        return SimpleNamespace(status=SimpleNamespace(value="success"))

    async def aclose(self) -> None:
        self.closed = True


async def test_task_entrypoint_executes_one_run_and_closes_dependencies() -> None:
    run_id = uuid4()
    container = FakeTaskContainer()

    exit_code = await run_task(run_id, container_factory=lambda: container)

    assert exit_code == 0
    assert container.executed == [run_id]
    assert container.closed
