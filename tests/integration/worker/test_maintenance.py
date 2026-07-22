from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from video_crawler.application.auth_profiles import ProfileLeaseService
from video_crawler.application.raw_artifacts import RawArtifactService
from video_crawler.domain.artifacts import ObjectInfo, RawObjectStore
from video_crawler.infrastructure.database.models import (
    AuthProfile,
    AuthProfileLease,
    CrawlJob,
    CrawlRun,
    MetricSnapshot,
    Platform,
    RawArtifact,
    Video,
)
from video_crawler.infrastructure.database.repositories.artifacts import (
    SqlAlchemyRawArtifactRepository,
)
from video_crawler.infrastructure.database.session import DatabaseSessionFactory
from video_crawler.worker.maintenance import MaintenanceService

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class _Object:
    object_name: str
    last_modified: datetime | None


class _CleanupObjectStore:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], datetime | None] = {}
        self.remove_failures: set[tuple[str, str]] = set()

    async def remove(self, bucket: str, object_key: str) -> None:
        identity = (bucket, object_key)
        if identity in self.remove_failures:
            raise RuntimeError("synthetic delete failure")
        self.objects.pop(identity, None)

    async def list(self, bucket: str, prefix: str) -> tuple[ObjectInfo, ...]:
        return cast(
            tuple[ObjectInfo, ...],
            tuple(
                _Object(key, modified)
                for (object_bucket, key), modified in self.objects.items()
                if object_bucket == bucket and key.startswith(prefix)
            ),
        )


async def _seed_artifacts(
    database: DatabaseSessionFactory,
    storage: _CleanupObjectStore,
    now: datetime,
) -> tuple[int, dict[str, int], dict[str, str]]:
    current = now.replace(tzinfo=None)
    profile_id = uuid4()
    job_id = uuid4()
    run_id = uuid4()
    async with database.transaction() as session:
        platform = Platform(
            platform_key=f"maintenance-{uuid4().hex[:12]}",
            display_name="Maintenance test",
            adapter_version="1",
            created_at=current,
        )
        session.add(platform)
        await session.flush()
        session.add(
            AuthProfile(
                id=profile_id,
                platform_id=platform.id,
                profile_name="maintenance",
                profile_directory=f"maintenance-{uuid4().hex[:8]}",
                status="active",
                created_at=current,
                updated_at=current,
            )
        )
        await session.flush()
        video = Video(
            platform_id=platform.id,
            platform_video_id="maintenance-video",
            canonical_url="https://example.test/maintenance-video",
            platform_ids={},
            first_discovered_at=current,
            created_at=current,
            updated_at=current,
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
                status="success",
                effective_strategy={},
                created_at=current,
                updated_at=current,
            )
        )
        await session.flush()
        session.add(
            CrawlRun(
                id=run_id,
                job_id=job_id,
                video_id=video.id,
                attempt_no=1,
                worker_id="maintenance-worker",
                status="success",
                started_at=current,
                finished_at=current,
                created_at=current,
            )
        )
        await session.flush()

        artifacts: dict[str, RawArtifact] = {}
        namespace = uuid4().hex
        object_keys = {
            name: f"fixture/{namespace}/{name}.json"
            for name in ("expired", "delete-failed", "permanent")
        }
        for name, expires_at in (
            ("expired", current - timedelta(seconds=1)),
            ("delete-failed", current - timedelta(seconds=1)),
            ("permanent", None),
        ):
            artifact = RawArtifact(
                crawl_run_id=run_id,
                video_id=video.id,
                artifact_type="fixture",
                bucket="crawler-raw",
                object_key=object_keys[name],
                content_type="application/json",
                compression="identity",
                etag=name,
                sha256="0" * 64,
                size_bytes=2,
                storage_status="available",
                captured_at=current - timedelta(days=31),
                expires_at=expires_at,
                created_at=current - timedelta(days=31),
                updated_at=current - timedelta(days=31),
            )
            session.add(artifact)
            artifacts[name] = artifact
        await session.flush()
        session.add(
            MetricSnapshot(
                video_id=video.id,
                crawl_run_id=run_id,
                captured_at=current,
                snapshot_hash="1" * 64,
                raw_artifact_id=artifacts["expired"].id,
                created_at=current,
            )
        )

    for name in artifacts:
        storage.objects[("crawler-raw", object_keys[name])] = now - timedelta(days=31)
    object_keys["temporary"] = f".tmp/{namespace}/stale"
    storage.objects[("crawler-raw", object_keys["temporary"])] = now - timedelta(hours=1)
    object_keys["temporary-active"] = f".tmp/{namespace}/active"
    storage.objects[("crawler-raw", object_keys["temporary-active"])] = now - timedelta(seconds=10)
    storage.remove_failures.add(("crawler-raw", object_keys["delete-failed"]))
    return (
        int(video.id),
        {name: int(row.id) for name, row in artifacts.items()},
        object_keys,
    )


async def test_run_once_cleans_objects_without_deleting_structured_data(
    database: DatabaseSessionFactory,
) -> None:
    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    storage = _CleanupObjectStore()
    video_id, artifact_ids, object_keys = await _seed_artifacts(database, storage, now)
    raw_artifacts = RawArtifactService(
        cast(RawObjectStore, storage),
        SqlAlchemyRawArtifactRepository(database),
        retention_days=30,
    )
    service = MaintenanceService(
        sessions=database,
        raw_artifacts=raw_artifacts,
        profile_leases=ProfileLeaseService(database, lease_ttl=timedelta(seconds=30)),
        stale_after=timedelta(seconds=30),
    )

    summary = await service.run_once(now)

    assert summary.raw_artifacts.expired == 1
    assert summary.raw_artifacts.delete_failed == 1
    assert summary.raw_artifacts.temporary_deleted == 1
    async with database() as session:
        rows = (
            await session.execute(
                select(RawArtifact).where(RawArtifact.id.in_(artifact_ids.values()))
            )
        ).scalars()
        statuses = {row.id: row.storage_status for row in rows}
        snapshot_count = await session.scalar(
            select(func.count())
            .select_from(MetricSnapshot)
            .where(MetricSnapshot.video_id == video_id)
        )
    assert statuses == {
        artifact_ids["expired"]: "expired",
        artifact_ids["delete-failed"]: "delete_failed",
        artifact_ids["permanent"]: "available",
    }
    assert snapshot_count == 1
    assert ("crawler-raw", object_keys["expired"]) not in storage.objects
    assert ("crawler-raw", object_keys["permanent"]) in storage.objects
    assert ("crawler-raw", object_keys["temporary"]) not in storage.objects
    assert ("crawler-raw", object_keys["temporary-active"]) in storage.objects


async def test_retention_zero_skips_expiry_but_still_removes_temporary_objects(
    database: DatabaseSessionFactory,
) -> None:
    now = datetime(2026, 7, 22, 12, 30, tzinfo=UTC)
    storage = _CleanupObjectStore()
    _, artifact_ids, object_keys = await _seed_artifacts(database, storage, now)
    service = MaintenanceService(
        sessions=database,
        raw_artifacts=RawArtifactService(
            cast(RawObjectStore, storage),
            SqlAlchemyRawArtifactRepository(database),
            retention_days=0,
        ),
        profile_leases=ProfileLeaseService(database, lease_ttl=timedelta(seconds=30)),
        stale_after=timedelta(seconds=30),
    )

    summary = await service.run_once(now)

    assert summary.raw_artifacts.expired == 0
    assert summary.raw_artifacts.delete_failed == 0
    assert summary.raw_artifacts.temporary_deleted == 1
    async with database() as session:
        statuses = dict(
            (
                await session.execute(
                    select(RawArtifact.id, RawArtifact.storage_status).where(
                        RawArtifact.id.in_(artifact_ids.values())
                    )
                )
            ).all()
        )
    assert set(statuses.values()) == {"available"}
    assert ("crawler-raw", object_keys["expired"]) in storage.objects
    assert ("crawler-raw", object_keys["delete-failed"]) in storage.objects
    assert ("crawler-raw", object_keys["temporary"]) not in storage.objects


async def _seed_running_jobs(
    database: DatabaseSessionFactory,
    now: datetime,
) -> tuple[dict[str, UUID], dict[str, UUID]]:
    current = now.replace(tzinfo=None)
    stale_heartbeat = current - timedelta(seconds=31)
    fresh_heartbeat = current - timedelta(seconds=29)
    job_ids = {name: uuid4() for name in ("requeued", "failed", "cancelled", "fresh")}
    run_ids = {name: uuid4() for name in job_ids}
    profile_ids = {name: uuid4() for name in job_ids}
    async with database.transaction() as session:
        platform = Platform(
            platform_key=f"recovery-{uuid4().hex[:12]}",
            display_name="Recovery test",
            adapter_version="1",
            created_at=current,
        )
        session.add(platform)
        await session.flush()
        for name in job_ids:
            heartbeat = fresh_heartbeat if name == "fresh" else stale_heartbeat
            session.add(
                AuthProfile(
                    id=profile_ids[name],
                    platform_id=platform.id,
                    profile_name=name,
                    profile_directory=f"recovery-{name}-{uuid4().hex[:6]}",
                    status="active",
                    created_at=current,
                    updated_at=current,
                )
            )
            await session.flush()
            session.add(
                CrawlJob(
                    id=job_ids[name],
                    root_job_id=job_ids[name],
                    platform_id=platform.id,
                    auth_profile_id=profile_ids[name],
                    source_url=f"https://example.test/{name}",
                    job_type="video",
                    status="running",
                    effective_strategy={},
                    cancel_requested=name == "cancelled",
                    cancel_requested_at=stale_heartbeat if name == "cancelled" else None,
                    attempt_count=3 if name == "failed" else 1,
                    max_attempts=3,
                    locked_by="lost-worker",
                    locked_at=heartbeat,
                    heartbeat_at=heartbeat,
                    created_at=current,
                    updated_at=current,
                )
            )
            await session.flush()
            session.add(
                CrawlRun(
                    id=run_ids[name],
                    job_id=job_ids[name],
                    attempt_no=3 if name == "failed" else 1,
                    worker_id="lost-worker",
                    status="running",
                    started_at=heartbeat,
                    heartbeat_at=heartbeat,
                    created_at=heartbeat,
                )
            )
            await session.flush()
            session.add(
                AuthProfileLease(
                    auth_profile_id=profile_ids[name],
                    worker_id="lost-worker",
                    crawl_run_id=run_ids[name],
                    acquired_at=heartbeat,
                    heartbeat_at=heartbeat,
                    expires_at=(
                        current + timedelta(seconds=1)
                        if name == "fresh"
                        else current - timedelta(seconds=1)
                    ),
                )
            )
    return job_ids, run_ids


async def test_run_once_recovers_stale_jobs_and_releases_only_expired_leases(
    database: DatabaseSessionFactory,
) -> None:
    now = datetime(2026, 7, 22, 13, 0, tzinfo=UTC)
    job_ids, run_ids = await _seed_running_jobs(database, now)
    storage = _CleanupObjectStore()
    service = MaintenanceService(
        sessions=database,
        raw_artifacts=RawArtifactService(
            cast(RawObjectStore, storage),
            SqlAlchemyRawArtifactRepository(database),
            retention_days=0,
        ),
        profile_leases=ProfileLeaseService(database, lease_ttl=timedelta(seconds=30)),
        stale_after=timedelta(seconds=30),
    )

    summary = await service.run_once(now)

    assert summary.stale_requeued == 1
    assert summary.stale_failed == 1
    assert summary.stale_cancelled == 1
    assert summary.leases_released == 3
    async with database() as session:
        jobs = (
            await session.execute(select(CrawlJob).where(CrawlJob.id.in_(job_ids.values())))
        ).scalars()
        runs = (
            await session.execute(select(CrawlRun).where(CrawlRun.id.in_(run_ids.values())))
        ).scalars()
        leases = (await session.execute(select(AuthProfileLease))).scalars().all()

    jobs_by_id = {row.id: row for row in jobs}
    runs_by_id = {row.id: row for row in runs}
    assert {name: jobs_by_id[job_id].status for name, job_id in job_ids.items()} == {
        "requeued": "pending",
        "failed": "failed",
        "cancelled": "cancelled",
        "fresh": "running",
    }
    for name in ("requeued", "failed", "cancelled"):
        assert jobs_by_id[job_ids[name]].locked_by is None
        assert jobs_by_id[job_ids[name]].heartbeat_at is None
        assert runs_by_id[run_ids[name]].finished_at == now.replace(tzinfo=None)
        assert runs_by_id[run_ids[name]].error_code == "WORKER_STALE"
    assert runs_by_id[run_ids["requeued"]].status == "failed"
    assert runs_by_id[run_ids["failed"]].status == "failed"
    assert runs_by_id[run_ids["cancelled"]].status == "cancelled"
    assert runs_by_id[run_ids["fresh"]].status == "running"
    assert jobs_by_id[job_ids["cancelled"]].cancelled_at == now.replace(tzinfo=None)
    assert [lease.crawl_run_id for lease in leases] == [run_ids["fresh"]]
