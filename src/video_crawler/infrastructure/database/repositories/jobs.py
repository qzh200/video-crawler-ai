from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from video_crawler.application.jobs import (
    IdempotencyConflictError,
    IdempotencyReservation,
    JobCreateResult,
    JobRecord,
)
from video_crawler.infrastructure.database.models import (
    AuthProfile,
    CrawlJob,
    CrawlModuleRun,
    CrawlRun,
    IdempotencyKey,
    Platform,
)
from video_crawler.infrastructure.database.session import DatabaseSessionFactory
from video_crawler.worker.supervisor import ClaimedWork


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


def _public_error(error: Exception) -> tuple[str, str, dict[str, object] | None]:
    code = getattr(error, "code", type(error).__name__)
    message = getattr(error, "public_message", "module execution failed")
    raw_details = getattr(error, "details", None)
    details = dict(raw_details) if isinstance(raw_details, Mapping) else None
    return str(code), str(message), details


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
        candidate_ids = tuple(
            (
                await session.scalars(
                    select(CrawlJob.id)
                    .where(
                        CrawlJob.status == "pending",
                        (CrawlJob.next_retry_at.is_(None) | (CrawlJob.next_retry_at <= now)),
                    )
                    .order_by(CrawlJob.id.asc())
                    .limit(100)
                )
            ).all()
        )
        for candidate_id in candidate_ids:
            query = (
                select(CrawlJob)
                .where(
                    CrawlJob.id == candidate_id,
                    CrawlJob.status == "pending",
                    (CrawlJob.next_retry_at.is_(None) | (CrawlJob.next_retry_at <= now)),
                )
                .with_for_update(skip_locked=True)
            )
            job = (await session.execute(query)).scalar_one_or_none()
            if job is None:
                continue
            profile_status = await session.scalar(
                select(AuthProfile.status).where(AuthProfile.id == job.auth_profile_id)
            )
            if profile_status != "active":
                continue
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
        return None


def _db_time(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _api_time(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SqlAlchemyJobStore:
    """Persist API-facing logical jobs and idempotency reservations."""

    def __init__(self, sessions: DatabaseSessionFactory) -> None:
        self.sessions = sessions

    async def create(
        self,
        record: JobRecord,
        reservation: IdempotencyReservation | None,
    ) -> JobCreateResult:
        async with self.sessions.transaction() as session:
            if reservation is not None:
                existing = (
                    await session.execute(
                        select(IdempotencyKey)
                        .where(IdempotencyKey.idempotency_key == reservation.key)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if existing is not None and existing.expires_at > _db_time(reservation.created_at):
                    if existing.request_hash != reservation.request_hash:
                        raise IdempotencyConflictError
                    replay = await self._get_record(session, existing.job_id)
                    if replay is None:
                        raise RuntimeError("idempotency reservation references a missing job")
                    return JobCreateResult(record=replay, created=False)
                if existing is not None:
                    await session.delete(existing)

            platform_id = (
                await session.execute(
                    select(AuthProfile.platform_id).where(AuthProfile.id == record.auth_profile_id)
                )
            ).scalar_one()
            configured_retries = record.effective_strategy.get("max_retries", 3)
            max_retries = (
                configured_retries
                if isinstance(configured_retries, int) and not isinstance(configured_retries, bool)
                else 3
            )
            row = CrawlJob(
                id=record.id,
                parent_job_id=record.parent_job_id,
                root_job_id=record.root_job_id,
                platform_id=platform_id,
                auth_profile_id=record.auth_profile_id,
                source_url=record.source_url,
                job_type="root",
                status=record.status,
                strategy_version=record.strategy_version,
                effective_strategy=dict(record.effective_strategy),
                cancel_requested=record.cancel_requested,
                cancel_requested_at=_db_time(record.cancel_requested_at)
                if record.cancel_requested_at
                else None,
                cancelled_at=_db_time(record.cancelled_at) if record.cancelled_at else None,
                max_attempts=max_retries + 1,
                created_at=_db_time(record.created_at),
                updated_at=_db_time(record.updated_at),
            )
            session.add(row)
            await session.flush()
            if reservation is not None:
                session.add(
                    IdempotencyKey(
                        idempotency_key=reservation.key,
                        request_hash=reservation.request_hash,
                        job_id=record.id,
                        created_at=_db_time(reservation.created_at),
                        expires_at=_db_time(reservation.expires_at),
                    )
                )
            return JobCreateResult(record=record, created=True)

    async def get(self, job_id: UUID) -> JobRecord | None:
        async with self.sessions() as session:
            return await self._get_record(session, job_id)

    async def save(
        self,
        record: JobRecord,
        *,
        reset_incomplete_modules: bool = False,
    ) -> JobRecord:
        async with self.sessions.transaction() as session:
            await session.execute(
                update(CrawlJob)
                .where(CrawlJob.id == record.id)
                .values(
                    status=record.status,
                    effective_strategy=dict(record.effective_strategy),
                    cancel_requested=record.cancel_requested,
                    cancel_requested_at=_db_time(record.cancel_requested_at)
                    if record.cancel_requested_at
                    else None,
                    cancelled_at=_db_time(record.cancelled_at) if record.cancelled_at else None,
                    updated_at=_db_time(record.updated_at),
                    locked_by=None if record.status == "pending" else CrawlJob.locked_by,
                    locked_at=None if record.status == "pending" else CrawlJob.locked_at,
                )
            )
            if reset_incomplete_modules:
                latest_run_id = (
                    await session.execute(
                        select(CrawlRun.id)
                        .where(CrawlRun.job_id == record.id)
                        .order_by(CrawlRun.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if latest_run_id is not None:
                    await session.execute(
                        update(CrawlModuleRun)
                        .where(
                            CrawlModuleRun.crawl_run_id == latest_run_id,
                            CrawlModuleRun.status != "success",
                        )
                        .values(status="pending", started_at=None, finished_at=None)
                    )
        return record

    async def _get_record(self, session: AsyncSession, job_id: UUID) -> JobRecord | None:
        job = await session.get(CrawlJob, job_id)
        if job is None:
            return None
        latest_run = (
            await session.execute(
                select(CrawlRun)
                .where(CrawlRun.job_id == job.id)
                .order_by(CrawlRun.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        module_states: dict[str, str] = {}
        if latest_run is not None:
            rows = (
                await session.execute(
                    select(CrawlModuleRun.module_key, CrawlModuleRun.status).where(
                        CrawlModuleRun.crawl_run_id == latest_run.id
                    )
                )
            ).all()
            module_states = {module_key: status for module_key, status in rows}
        error: dict[str, object] | None = None
        if latest_run is not None and latest_run.error_code is not None:
            error = {
                "code": latest_run.error_code,
                "message": latest_run.error_message or "crawl run failed",
            }
        return JobRecord(
            id=job.id,
            auth_profile_id=job.auth_profile_id,
            source_url=job.source_url,
            status=job.status,
            strategy_version=job.strategy_version,
            effective_strategy=dict(job.effective_strategy),
            root_job_id=job.root_job_id,
            parent_job_id=job.parent_job_id,
            created_at=_api_time(job.created_at) or datetime.now(UTC),
            updated_at=_api_time(job.updated_at) or datetime.now(UTC),
            cancel_requested=job.cancel_requested,
            cancel_requested_at=_api_time(job.cancel_requested_at),
            cancelled_at=_api_time(job.cancelled_at),
            module_states=module_states,
            started_at=_api_time(latest_run.started_at) if latest_run else None,
            finished_at=_api_time(latest_run.finished_at) if latest_run else None,
            error=error,
        )


@dataclass(frozen=True, slots=True)
class RunExecutionRecord:
    run_id: UUID
    job_id: UUID
    root_job_id: UUID
    auth_profile_id: UUID
    source_url: str
    effective_strategy: dict[str, Any]
    platform_id: int
    platform_key: str
    profile_directory: str
    video_id: int | None


class SqlAlchemyWorkerStateStore:
    """Persist Worker supervision and task-process state transitions."""

    _TERMINAL = frozenset({"success", "partial", "failed", "cancelled"})

    def __init__(self, sessions: DatabaseSessionFactory) -> None:
        self.sessions = sessions
        self._claims = JobRepository(sessions)

    async def claim_next(self, worker_id: str, now: datetime) -> ClaimedWork | None:
        claimed = await self._claims.claim_next(worker_id, _db_time(now))
        if claimed is None:
            return None
        return ClaimedWork(
            job_id=claimed.id,
            auth_profile_id=claimed.auth_profile_id,
            attempt_no=claimed.attempt_count,
        )

    async def create_run(self, work: ClaimedWork, worker_id: str, now: datetime) -> UUID:
        run_id = uuid4()
        current = _db_time(now)
        async with self.sessions.transaction() as session:
            video_id = await session.scalar(
                select(CrawlJob.video_id).where(CrawlJob.id == work.job_id)
            )
            session.add(
                CrawlRun(
                    id=run_id,
                    job_id=work.job_id,
                    video_id=video_id,
                    attempt_no=work.attempt_no,
                    worker_id=worker_id,
                    status="running",
                    started_at=current,
                    heartbeat_at=current,
                    created_at=current,
                )
            )
        return run_id

    async def record_process(
        self,
        job_id: UUID,
        run_id: UUID,
        pid: int,
        process_group_id: int,
        now: datetime,
    ) -> None:
        del job_id
        await self._update_run(
            run_id,
            process_pid=pid,
            process_group_id=process_group_id,
            heartbeat_at=_db_time(now),
        )

    async def is_cancel_requested(self, job_id: UUID) -> bool:
        async with self.sessions() as session:
            value = await session.scalar(
                select(CrawlJob.cancel_requested).where(CrawlJob.id == job_id)
            )
        return bool(value)

    async def heartbeat(self, job_id: UUID, run_id: UUID, now: datetime) -> None:
        current = _db_time(now)
        async with self.sessions.transaction() as session:
            await session.execute(
                update(CrawlJob).where(CrawlJob.id == job_id).values(heartbeat_at=current)
            )
            await session.execute(
                update(CrawlRun).where(CrawlRun.id == run_id).values(heartbeat_at=current)
            )

    async def mark_cancelling(self, job_id: UUID, run_id: UUID, now: datetime) -> None:
        current = _db_time(now)
        async with self.sessions.transaction() as session:
            await session.execute(
                update(CrawlJob)
                .where(CrawlJob.id == job_id)
                .values(status="cancelling", updated_at=current)
            )
            await session.execute(
                update(CrawlRun).where(CrawlRun.id == run_id).values(heartbeat_at=current)
            )

    async def mark_cancelled(
        self,
        job_id: UUID,
        run_id: UUID,
        termination_signal: str,
        now: datetime,
    ) -> None:
        current = _db_time(now)
        async with self.sessions.transaction() as session:
            await session.execute(
                update(CrawlRun)
                .where(CrawlRun.id == run_id)
                .values(
                    status="cancelled",
                    termination_signal=termination_signal,
                    terminated_at=current,
                    finished_at=current,
                )
            )
            await session.execute(
                update(CrawlJob)
                .where(CrawlJob.id == job_id)
                .values(
                    status="cancelled",
                    cancelled_at=current,
                    updated_at=current,
                    locked_by=None,
                    locked_at=None,
                )
            )

    async def mark_finished(
        self,
        job_id: UUID,
        run_id: UUID,
        status: str,
        now: datetime,
    ) -> None:
        current = _db_time(now)
        async with self.sessions.transaction() as session:
            run = await session.get(CrawlRun, run_id, with_for_update=True)
            if run is None:
                raise RuntimeError("crawl run was not found")
            final_status = run.status if run.status in self._TERMINAL else status
            run.status = final_status
            run.finished_at = current
            if final_status in {"failed", "partial"} and run.error_code is None:
                failed_module = (
                    await session.execute(
                        select(CrawlModuleRun)
                        .where(
                            CrawlModuleRun.crawl_run_id == run_id,
                            CrawlModuleRun.status == "failed",
                        )
                        .order_by(
                            CrawlModuleRun.finished_at.desc(),
                            CrawlModuleRun.id.desc(),
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if failed_module is not None:
                    run.error_code = failed_module.error_code
                    run.error_message = failed_module.error_message
                    run.result_summary = {
                        "module": failed_module.module_key,
                        "details": failed_module.result_summary or {},
                    }
            await session.execute(
                update(CrawlJob)
                .where(CrawlJob.id == job_id)
                .values(
                    status=final_status,
                    updated_at=current,
                    locked_by=None,
                    locked_at=None,
                    heartbeat_at=None,
                )
            )

    async def load_execution(self, run_id: UUID) -> RunExecutionRecord:
        async with self.sessions() as session:
            row = (
                await session.execute(
                    select(CrawlRun, CrawlJob, AuthProfile, Platform)
                    .join(CrawlJob, CrawlRun.job_id == CrawlJob.id)
                    .join(AuthProfile, CrawlJob.auth_profile_id == AuthProfile.id)
                    .join(Platform, CrawlJob.platform_id == Platform.id)
                    .where(CrawlRun.id == run_id)
                )
            ).one_or_none()
        if row is None:
            raise RuntimeError("crawl run was not found")
        run, job, profile, platform = row
        return RunExecutionRecord(
            run_id=run.id,
            job_id=job.id,
            root_job_id=job.root_job_id,
            auth_profile_id=profile.id,
            source_url=job.source_url,
            effective_strategy=dict(job.effective_strategy),
            platform_id=platform.id,
            platform_key=platform.platform_key,
            profile_directory=profile.profile_directory,
            video_id=job.video_id,
        )

    async def bind_video(
        self,
        job_id: UUID,
        run_id: UUID,
        video_id: int,
        now: datetime,
    ) -> None:
        current = _db_time(now)
        async with self.sessions.transaction() as session:
            await session.execute(
                update(CrawlJob)
                .where(CrawlJob.id == job_id)
                .values(video_id=video_id, job_type="video", updated_at=current)
            )
            await session.execute(
                update(CrawlRun).where(CrawlRun.id == run_id).values(video_id=video_id)
            )

    async def create_child_job(
        self,
        execution: RunExecutionRecord,
        video_id: int,
        source_url: str,
        now: datetime,
    ) -> UUID:
        child_id = uuid4()
        current = _db_time(now)
        async with self.sessions.transaction() as session:
            session.add(
                CrawlJob(
                    id=child_id,
                    parent_job_id=execution.job_id,
                    root_job_id=execution.root_job_id,
                    platform_id=execution.platform_id,
                    auth_profile_id=execution.auth_profile_id,
                    video_id=video_id,
                    source_url=source_url,
                    job_type="video",
                    status="pending",
                    strategy_version=1,
                    effective_strategy=dict(execution.effective_strategy),
                    max_attempts=int(execution.effective_strategy.get("max_retries", 3)) + 1,
                    created_at=current,
                    updated_at=current,
                )
            )
        return child_id

    async def _update_run(self, run_id: UUID, **values: object) -> None:
        async with self.sessions.transaction() as session:
            await session.execute(update(CrawlRun).where(CrawlRun.id == run_id).values(**values))


class SqlAlchemyModuleStateStore:
    def __init__(self, sessions: DatabaseSessionFactory, run_id: UUID) -> None:
        self.sessions = sessions
        self.run_id = run_id

    async def mark_running(self, module_key: str) -> None:
        await self._mark(module_key, "running", started_at=datetime.now(UTC))

    async def mark_success(self, module_key: str) -> None:
        await self._mark(module_key, "success", finished_at=datetime.now(UTC))

    async def mark_failed(self, module_key: str, error: Exception) -> None:
        error_code, error_message, result_summary = _public_error(error)
        await self._mark(
            module_key,
            "failed",
            finished_at=datetime.now(UTC),
            error_code=error_code,
            error_message=error_message,
            result_summary=result_summary,
        )

    async def mark_cancelled(self, module_key: str, error: BaseException) -> None:
        del error
        await self._mark(module_key, "cancelled", finished_at=datetime.now(UTC))

    async def mark_skipped(self, module_key: str) -> None:
        await self._mark(module_key, "skipped", finished_at=datetime.now(UTC))

    async def _mark(self, module_key: str, status: str, **values: object) -> None:
        normalized = {
            key: _db_time(value) if isinstance(value, datetime) else value
            for key, value in values.items()
        }
        statement = insert(CrawlModuleRun).values(
            crawl_run_id=self.run_id,
            module_key=module_key,
            status=status,
            **normalized,
        )
        statement = statement.on_duplicate_key_update(
            status=statement.inserted.status,
            **{key: getattr(statement.inserted, key) for key in normalized},
        )
        async with self.sessions.transaction() as session:
            await session.execute(statement)
