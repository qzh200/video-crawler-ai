from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update

from video_crawler.domain.artifacts import ExpiredArtifact, PendingArtifact
from video_crawler.infrastructure.database.models import RawArtifact
from video_crawler.infrastructure.database.session import DatabaseSessionFactory


class SqlAlchemyRawArtifactRepository:
    def __init__(self, sessions: DatabaseSessionFactory) -> None:
        self.sessions = sessions

    async def create_pending(self, artifact: PendingArtifact) -> int:
        async with self.sessions.transaction() as session:
            row = RawArtifact(
                crawl_run_id=artifact.crawl_run_id,
                video_id=artifact.video_id,
                artifact_type=artifact.artifact_type,
                bucket=artifact.bucket,
                object_key=artifact.object_key,
                content_type=artifact.content_type,
                compression=artifact.compression,
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
                storage_status="uploading",
                captured_at=artifact.captured_at,
                expires_at=artifact.expires_at,
                created_at=artifact.captured_at,
                updated_at=artifact.captured_at,
            )
            session.add(row)
            await session.flush()
            return int(row.id)

    async def mark_available(self, artifact_id: int, etag: str, now: datetime) -> None:
        await self._update(artifact_id, now, storage_status="available", etag=etag)

    async def mark_upload_failed(self, artifact_id: int, now: datetime) -> None:
        await self._update(artifact_id, now, storage_status="upload_failed")

    async def list_expired(self, now: datetime) -> tuple[ExpiredArtifact, ...]:
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(RawArtifact.id, RawArtifact.bucket, RawArtifact.object_key).where(
                        RawArtifact.storage_status == "available",
                        RawArtifact.expires_at.is_not(None),
                        RawArtifact.expires_at <= now,
                    )
                )
            ).all()
        return tuple(ExpiredArtifact(row_id, bucket, key) for row_id, bucket, key in rows)

    async def mark_deleted(self, artifact_id: int, *, status: str, now: datetime) -> None:
        values: dict[str, object] = {"storage_status": status, "updated_at": now}
        if status == "expired":
            values["deleted_at"] = now
        await self._update(artifact_id, now, **values)

    async def _update(self, artifact_id: int, now: datetime, **values: object) -> None:
        values.setdefault("updated_at", now)
        async with self.sessions.transaction() as session:
            await session.execute(
                update(RawArtifact).where(RawArtifact.id == artifact_id).values(**values)
            )
