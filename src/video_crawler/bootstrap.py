from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

import structlog
from fastapi import FastAPI
from sqlalchemy import select, text, update

from video_crawler.adapters.base import AdapterContext, VideoSiteAdapter
from video_crawler.adapters.bilibili import BilibiliAdapter
from video_crawler.adapters.registry import AdapterRegistry
from video_crawler.api.schemas.auth_profiles import (
    AuthProfileCreateRequest,
    AuthProfileResponse,
)
from video_crawler.application.auth_profiles import ProfileLeaseService
from video_crawler.application.cursors import CursorCodec
from video_crawler.application.health import HealthService
from video_crawler.application.jobs import JobService
from video_crawler.application.pipeline import (
    CrawlJobContext,
    CrawlPipeline,
    PipelineResult,
)
from video_crawler.application.rate_limit import RateLimiter
from video_crawler.application.raw_artifacts import RawArtifactRef, RawArtifactService
from video_crawler.application.result_queries import ResultQueryService
from video_crawler.core.config import Settings, get_settings
from video_crawler.domain.artifacts import RawObjectStore
from video_crawler.domain.comments import CommentBatch
from video_crawler.domain.errors import CancellationRequestedError
from video_crawler.domain.metrics import MetricResult
from video_crawler.domain.strategy import CrawlStrategy
from video_crawler.domain.targets import DiscoveredTarget, TargetKind
from video_crawler.domain.timed_text import TimedTextBatch
from video_crawler.infrastructure.browser.crawl4ai_gateway import Crawl4AIBrowserGateway
from video_crawler.infrastructure.database.models import AuthProfile, Platform
from video_crawler.infrastructure.database.repositories.artifacts import (
    SqlAlchemyRawArtifactRepository,
)
from video_crawler.infrastructure.database.repositories.content import ContentRepository
from video_crawler.infrastructure.database.repositories.jobs import (
    RunExecutionRecord,
    SqlAlchemyJobStore,
    SqlAlchemyModuleStateStore,
    SqlAlchemyWorkerStateStore,
)
from video_crawler.infrastructure.database.repositories.results import ResultRepository
from video_crawler.infrastructure.database.session import DatabaseSessionFactory
from video_crawler.infrastructure.http.client import HttpxGateway, RetryPolicy
from video_crawler.infrastructure.storage.minio import MinioRawArtifactStore
from video_crawler.worker.supervisor import WorkerSupervisor, build_default_supervisor


@dataclass(frozen=True, slots=True)
class _AuthContext:
    profile_id: str
    platform: str
    profile_directory: str


class _CancellationToken:
    def __init__(self) -> None:
        self.cancelled = False

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise CancellationRequestedError("crawl cancellation was requested")


class _ScopedRawArtifactGateway:
    def __init__(
        self,
        service: RawArtifactService,
        *,
        platform: str,
        run_id: UUID,
        video_key: str,
        database_video_id: int | None,
    ) -> None:
        self._service = service
        self._platform = platform
        self._run_id = run_id
        self._video_key = video_key
        self._database_video_id = database_video_id
        self._sequence = 0

    async def store(
        self,
        content: bytes,
        *,
        artifact_type: str,
        content_type: str,
        compression: str | None = None,
        metadata: Mapping[str, str | int | float | bool | None] | None = None,
    ) -> RawArtifactRef:
        del metadata
        self._sequence += 1
        return await self._service.store(
            content,
            platform=self._platform,
            captured_at=datetime.now(UTC),
            video_id=self._video_key,
            database_video_id=self._database_video_id,
            run_id=self._run_id,
            artifact_name=f"{artifact_type}-{self._sequence:04d}.raw",
            artifact_type=artifact_type,
            content_type=content_type,
            compression=compression,
        )


class _RejectingRawArtifactGateway:
    async def store(self, content: bytes, **kwargs: object) -> RawArtifactRef:
        del content, kwargs
        raise RuntimeError("auth verification cannot persist crawl artifacts")


class _PipelineResults:
    def __init__(
        self,
        results: ResultRepository,
        content: ContentRepository,
    ) -> None:
        self._results = results
        self._content = content

    async def create_metric_snapshot(
        self,
        video_id: int,
        crawl_run_id: UUID,
        result: MetricResult,
    ) -> int:
        raw_id = _first_artifact_id(result.raw_artifacts)
        return await self._results.create_metric_snapshot(
            video_id,
            crawl_run_id,
            result,
            raw_artifact_id=raw_id,
        )

    async def upsert_comments(self, video_id: int, batch: CommentBatch) -> int:
        return await self._results.upsert_comments(video_id, batch)

    async def upsert_timed_text_batch(self, video_id: int, batch: TimedTextBatch) -> int:
        await self._content.ensure_video_unit(
            video_id=video_id,
            platform_unit_id=batch.stream.platform_unit_id,
            now=datetime.now(UTC),
        )
        return await self._results.upsert_timed_text_batch(video_id, batch)


class _DiscoveryRepository:
    def __init__(
        self,
        content: ContentRepository,
        states: SqlAlchemyWorkerStateStore,
        execution: RunExecutionRecord,
    ) -> None:
        self._content = content
        self._states = states
        self._execution = execution

    async def record_discovered_target(
        self,
        crawl_run_id: UUID,
        target: DiscoveredTarget,
    ) -> None:
        now = datetime.now(UTC)
        video_id = await self._content.upsert_video(
            platform_id=self._execution.platform_id,
            target=target,
            now=now,
        )
        await self._content.record_discovery(
            crawl_run_id=crawl_run_id,
            video_id=video_id,
            source_url=target.canonical_url,
            position=target.position,
            now=now,
        )
        await self._states.create_child_job(
            self._execution,
            video_id,
            target.canonical_url,
            now,
        )


class _DatabaseHealthProbe:
    def __init__(self, sessions: DatabaseSessionFactory) -> None:
        self._sessions = sessions

    async def ping(self) -> None:
        async with self._sessions() as session:
            await session.execute(text("SELECT 1"))

    async def migration_revision(self) -> str | None:
        async with self._sessions() as session:
            return cast(
                str | None,
                await session.scalar(text("SELECT version_num FROM alembic_version LIMIT 1")),
            )


class _ObjectStorageHealthProbe:
    def __init__(self, storage: MinioRawArtifactStore) -> None:
        self._client = cast(_HealthObjectClient, storage.client)

    async def ping(self) -> None:
        await asyncio.to_thread(self._client.list_buckets)

    async def bucket_exists(self, bucket: str) -> bool:
        return bool(await asyncio.to_thread(self._client.bucket_exists, bucket))


class _HealthObjectClient(Protocol):
    def list_buckets(self) -> object: ...

    def bucket_exists(self, bucket: str) -> bool: ...


class _AuthProfileOperations:
    def __init__(self, container: ApplicationContainer) -> None:
        self._container = container

    async def create(self, request: AuthProfileCreateRequest) -> AuthProfileResponse:
        self._container.adapter_registry.get(request.platform)
        now = datetime.now(UTC).replace(tzinfo=None)
        profile_id = uuid4()
        async with self._container.sessions.transaction() as session:
            platform = (
                await session.execute(
                    select(Platform).where(Platform.platform_key == request.platform)
                )
            ).scalar_one_or_none()
            if platform is None:
                platform = Platform(
                    platform_key=request.platform,
                    display_name=request.platform,
                    adapter_version="1",
                    created_at=now,
                )
                session.add(platform)
                await session.flush()
            session.add(
                AuthProfile(
                    id=profile_id,
                    platform_id=platform.id,
                    profile_name=request.profile_name,
                    profile_directory=request.profile_directory,
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
        record = await self.get(profile_id)
        if record is None:
            raise RuntimeError("created auth Profile could not be loaded")
        return record

    async def list(self) -> tuple[AuthProfileResponse, ...]:
        async with self._container.sessions() as session:
            rows = (
                await session.execute(
                    select(AuthProfile, Platform)
                    .join(Platform, AuthProfile.platform_id == Platform.id)
                    .order_by(AuthProfile.created_at.asc())
                )
            ).all()
        return tuple(
            _profile_response(profile, platform.platform_key) for profile, platform in rows
        )

    async def get(self, profile_id: UUID) -> AuthProfileResponse | None:
        async with self._container.sessions() as session:
            row = (
                await session.execute(
                    select(AuthProfile, Platform)
                    .join(Platform, AuthProfile.platform_id == Platform.id)
                    .where(AuthProfile.id == profile_id)
                )
            ).one_or_none()
        if row is None:
            return None
        return _profile_response(row[0], row[1].platform_key)

    async def verify(self, profile_id: UUID) -> AuthProfileResponse | None:
        profile = await self.get(profile_id)
        if profile is None:
            return None
        valid = await self._container.verify_profile(profile)
        now = datetime.now(UTC).replace(tzinfo=None)
        async with self._container.sessions.transaction() as session:
            await session.execute(
                update(AuthProfile)
                .where(AuthProfile.id == profile_id)
                .values(
                    status="active" if valid else "expired",
                    last_verified_at=now,
                    updated_at=now,
                )
            )
        return await self.get(profile_id)

    async def enable(self, profile_id: UUID) -> AuthProfileResponse | None:
        return await self._set_status(profile_id, "active")

    async def disable(self, profile_id: UUID) -> AuthProfileResponse | None:
        return await self._set_status(profile_id, "disabled")

    async def _set_status(
        self,
        profile_id: UUID,
        status: str,
    ) -> AuthProfileResponse | None:
        if await self.get(profile_id) is None:
            return None
        async with self._container.sessions.transaction() as session:
            await session.execute(
                update(AuthProfile)
                .where(AuthProfile.id == profile_id)
                .values(status=status, updated_at=datetime.now(UTC).replace(tzinfo=None))
            )
        return await self.get(profile_id)


class ApplicationContainer:
    """Composition root for API, Worker, task process, database, and object storage."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        sessions: DatabaseSessionFactory | None = None,
        object_store: RawObjectStore | None = None,
        adapter_registry: AdapterRegistry[VideoSiteAdapter] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._owns_sessions = sessions is None
        self.sessions = sessions or DatabaseSessionFactory(self.settings)
        self.adapter_registry = adapter_registry or AdapterRegistry([BilibiliAdapter()])
        if object_store is None:
            object_store = MinioRawArtifactStore(
                endpoint=self.settings.minio_endpoint,
                access_key=self.settings.minio_access_key,
                secret_key=self.settings.minio_secret_key.get_secret_value(),
                secure=self.settings.minio_secure,
            )
        self.object_store = object_store
        self.raw_artifacts = RawArtifactService(
            object_store,
            SqlAlchemyRawArtifactRepository(self.sessions),
            bucket=self.settings.minio_bucket,
            retention_days=self.settings.raw_artifact_retention_days,
        )
        self.job_store = SqlAlchemyJobStore(self.sessions)
        self.worker_states = SqlAlchemyWorkerStateStore(self.sessions)
        self.content = ContentRepository(self.sessions)
        self.results = ResultRepository(self.sessions)
        self.job_service = JobService(
            store=self.job_store,
            default_strategy=CrawlStrategy.from_defaults(self.settings),
            idempotency_ttl=timedelta(hours=self.settings.idempotency_ttl_hours),
        )
        cursor_secret = self.settings.api_key.get_secret_value().encode()
        self.result_query_service = ResultQueryService(
            store=self.results,
            cursor_codec=CursorCodec(cursor_secret),
        )
        self.profile_service = _AuthProfileOperations(self)
        self.leases = ProfileLeaseService(
            self.sessions,
            lease_ttl=timedelta(seconds=self.settings.worker_stale_after_seconds),
        )
        self.health_service = self._build_health_service()

    def create_api_app(self) -> FastAPI:
        from video_crawler.main import create_app

        return create_app(
            job_service=self.job_service,
            profile_service=self.profile_service,
            result_query_service=self.result_query_service,
            health_service=self.health_service,
        )

    def configure_api_app(self, application: FastAPI) -> None:
        application.state.job_service = self.job_service
        application.state.profile_service = self.profile_service
        application.state.result_query_service = self.result_query_service
        application.state.health_service = self.health_service

    def create_supervisor(self) -> WorkerSupervisor:
        return build_default_supervisor(
            worker_id=self.settings.worker_id,
            states=self.worker_states,
            leases=self.leases,
            poll_interval_seconds=self.settings.worker_poll_interval_seconds,
            heartbeat_interval_seconds=self.settings.worker_heartbeat_interval_seconds,
            terminate_grace_seconds=self.settings.task_terminate_grace_seconds,
            kill_timeout_seconds=self.settings.task_kill_timeout_seconds,
        )

    async def run_worker_once(self, *, worker_id: str | None = None) -> bool:
        selected_worker = worker_id or self.settings.worker_id
        now = datetime.now(UTC)
        work = await self.worker_states.claim_next(selected_worker, now)
        if work is None:
            return False
        run_id = await self.worker_states.create_run(work, selected_worker, now)
        acquired = await self.leases.acquire(
            work.auth_profile_id,
            selected_worker,
            run_id,
            now,
        )
        if not acquired:
            await self.worker_states.mark_finished(work.job_id, run_id, "failed", now)
            return True
        try:
            try:
                result = await self.execute_run(run_id)
            except Exception:
                await self.worker_states.mark_finished(
                    work.job_id,
                    run_id,
                    "failed",
                    datetime.now(UTC),
                )
                raise
            await self.worker_states.mark_finished(
                work.job_id,
                run_id,
                result.status.value,
                datetime.now(UTC),
            )
        finally:
            await self.leases.release(work.auth_profile_id, run_id)
        return True

    async def execute_run(self, run_id: UUID) -> PipelineResult:
        execution = await self.worker_states.load_execution(run_id)
        adapter = self.adapter_registry.resolve(execution.source_url)
        if adapter.platform_key != execution.platform_key:
            raise ValueError("job Profile platform does not match the selected Adapter")
        strategy = CrawlStrategy().merge(execution.effective_strategy)
        browser = Crawl4AIBrowserGateway(
            profile_root=self.settings.browser_profile_root,
            profile_directory=execution.profile_directory,
        )
        rate_limiter = RateLimiter()
        logger = structlog.get_logger().bind(job_id=str(execution.job_id), run_id=str(run_id))
        http = HttpxGateway(
            retry_policy=RetryPolicy(max_retries=strategy.max_retries),
            rate_limiter=rate_limiter,
            strategy=strategy,
            logger=logger,
        )
        cancellation = _CancellationToken()
        raw_gateway = _ScopedRawArtifactGateway(
            self.raw_artifacts,
            platform=adapter.platform_key,
            run_id=run_id,
            video_key=str(execution.video_id or execution.job_id),
            database_video_id=execution.video_id,
        )
        context = AdapterContext(
            browser=browser,
            http=http,
            network_capture=browser,
            raw_artifacts=raw_gateway,
            rate_limiter=rate_limiter,
            cancellation=cancellation,
            logger=logger,
            auth_profile=_AuthContext(
                profile_id=str(execution.auth_profile_id),
                platform=execution.platform_key,
                profile_directory=execution.profile_directory,
            ),
        )
        try:
            target = await adapter.resolve_target(context, execution.source_url)
            video_id = execution.video_id
            if target.kind is TargetKind.SINGLE_VIDEO:
                if target.platform_video_id is None:
                    raise ValueError("single-video target did not contain a platform video id")
                discovered = DiscoveredTarget(
                    platform=target.platform,
                    platform_video_id=target.platform_video_id,
                    canonical_url=target.canonical_url,
                    position=None,
                    platform_ids=target.platform_ids,
                )
                video_id = await self.content.upsert_video(
                    platform_id=execution.platform_id,
                    target=discovered,
                    now=datetime.now(UTC),
                )
                await self.worker_states.bind_video(
                    execution.job_id,
                    run_id,
                    video_id,
                    datetime.now(UTC),
                )
                raw_gateway._video_key = target.platform_video_id
                raw_gateway._database_video_id = video_id

            module_states = SqlAlchemyModuleStateStore(self.sessions, run_id)
            pipeline = CrawlPipeline(
                result_repository=_PipelineResults(self.results, self.content),
                module_states=module_states,
                discovery_repository=_DiscoveryRepository(
                    self.content,
                    self.worker_states,
                    execution,
                ),
            )
            result = await pipeline.execute(
                CrawlJobContext(
                    adapter=adapter,
                    adapter_context=context,
                    target=target,
                    strategy=strategy,
                    crawl_run_id=run_id,
                    video_id=video_id,
                )
            )
            await self.worker_states.mark_finished(
                execution.job_id,
                run_id,
                result.status.value,
                datetime.now(UTC),
            )
            return result
        finally:
            await browser.close()
            await http.aclose()

    async def verify_profile(self, profile: AuthProfileResponse) -> bool:
        adapter = self.adapter_registry.get(profile.platform)
        browser = Crawl4AIBrowserGateway(
            profile_root=self.settings.browser_profile_root,
            profile_directory=profile.profile_directory,
        )
        http = HttpxGateway()
        logger = structlog.get_logger().bind(profile_id=str(profile.profile_id))
        context = AdapterContext(
            browser=browser,
            http=http,
            network_capture=browser,
            raw_artifacts=_RejectingRawArtifactGateway(),
            rate_limiter=RateLimiter(),
            cancellation=_CancellationToken(),
            logger=logger,
            auth_profile=_AuthContext(
                profile_id=str(profile.profile_id),
                platform=profile.platform,
                profile_directory=profile.profile_directory,
            ),
        )
        try:
            result = await adapter.verify_auth(context)
            return result.is_valid
        finally:
            await browser.close()
            await http.aclose()

    async def aclose(self) -> None:
        if self._owns_sessions:
            await self.sessions.dispose()

    def _build_health_service(self) -> HealthService | None:
        if not isinstance(self.object_store, MinioRawArtifactStore):
            return None
        return HealthService(
            database=_DatabaseHealthProbe(self.sessions),
            object_storage=_ObjectStorageHealthProbe(self.object_store),
            expected_migration_revision="0001_initial_schema",
            bucket=self.settings.minio_bucket,
        )


def _first_artifact_id(artifacts: tuple[object, ...]) -> int | None:
    if not artifacts:
        return None
    value = getattr(artifacts[0], "id", None)
    return value if isinstance(value, int) else None


def _profile_response(profile: AuthProfile, platform_key: str) -> AuthProfileResponse:
    return AuthProfileResponse(
        profile_id=profile.id,
        platform=platform_key,
        profile_name=profile.profile_name,
        profile_directory=profile.profile_directory,
        status=cast(Any, profile.status),
        last_verified_at=profile.last_verified_at.replace(tzinfo=UTC)
        if profile.last_verified_at
        else None,
        created_at=profile.created_at.replace(tzinfo=UTC),
        updated_at=profile.updated_at.replace(tzinfo=UTC),
    )
