from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from video_crawler.application.auth_profiles import ProfileLeaseService
from video_crawler.application.raw_artifacts import CleanupSummary, RawArtifactService
from video_crawler.infrastructure.database.models import CrawlJob, CrawlRun
from video_crawler.infrastructure.database.session import DatabaseSessionFactory


@dataclass(frozen=True, slots=True)
class MaintenanceSummary:
    raw_artifacts: CleanupSummary
    stale_requeued: int
    stale_failed: int
    stale_cancelled: int
    leases_released: int


class MaintenanceService:
    """Run bounded Worker maintenance without starting crawl processes."""

    def __init__(
        self,
        *,
        sessions: DatabaseSessionFactory,
        raw_artifacts: RawArtifactService,
        profile_leases: ProfileLeaseService,
        stale_after: timedelta,
    ) -> None:
        self._sessions = sessions
        self._raw_artifacts = raw_artifacts
        self._profile_leases = profile_leases
        self._stale_after = stale_after

    async def run_once(self, now: datetime) -> MaintenanceSummary:
        artifacts = await self._raw_artifacts.cleanup_expired(
            now,
            temporary_stale_before=now - self._stale_after,
        )
        requeued, failed, cancelled = await self._recover_stale_jobs(now)
        leases_released = await self._profile_leases.reap_expired(now)
        return MaintenanceSummary(
            raw_artifacts=artifacts,
            stale_requeued=requeued,
            stale_failed=failed,
            stale_cancelled=cancelled,
            leases_released=leases_released,
        )

    async def _recover_stale_jobs(self, now: datetime) -> tuple[int, int, int]:
        current = _db_time(now)
        cutoff = current - self._stale_after
        requeued = failed = cancelled = 0
        async with self._sessions.transaction() as session:
            jobs = (
                await session.execute(
                    select(CrawlJob)
                    .where(
                        CrawlJob.status == "running",
                        CrawlJob.heartbeat_at.is_not(None),
                        CrawlJob.heartbeat_at <= cutoff,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
            for job in jobs:
                run = (
                    await session.execute(
                        select(CrawlRun)
                        .where(CrawlRun.job_id == job.id, CrawlRun.status == "running")
                        .order_by(CrawlRun.created_at.desc())
                        .limit(1)
                        .with_for_update()
                    )
                ).scalar_one_or_none()

                if job.cancel_requested:
                    job.status = "cancelled"
                    job.cancelled_at = current
                    run_status = "cancelled"
                    cancelled += 1
                elif job.attempt_count < job.max_attempts:
                    job.status = "pending"
                    job.next_retry_at = None
                    run_status = "failed"
                    requeued += 1
                else:
                    job.status = "failed"
                    run_status = "failed"
                    failed += 1

                job.locked_by = None
                job.locked_at = None
                job.heartbeat_at = None
                job.updated_at = current
                if run is not None:
                    run.status = run_status
                    run.finished_at = current
                    run.error_code = "WORKER_STALE"
                    run.error_message = "worker heartbeat expired"
        return requeued, failed, cancelled


def _db_time(value: datetime) -> datetime:
    normalized = value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value
    return normalized.replace(microsecond=(normalized.microsecond // 1000) * 1000)
