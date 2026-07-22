from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from video_crawler.domain.artifacts import (
    PendingArtifact,
    RawArtifactRepository,
    RawObjectStore,
    build_object_key,
)


@dataclass(frozen=True, slots=True)
class RawArtifactRef:
    id: int
    bucket: str
    object_key: str
    etag: str
    sha256: str
    size_bytes: int
    content_type: str
    compression: str


@dataclass(frozen=True, slots=True)
class CleanupSummary:
    expired: int
    delete_failed: int
    temporary_deleted: int


class RawArtifactService:
    def __init__(
        self,
        storage: RawObjectStore,
        repository: RawArtifactRepository,
        *,
        bucket: str = "crawler-raw",
        retention_days: int = 30,
    ) -> None:
        if retention_days < 0:
            raise ValueError("retention_days must be nonnegative")
        self.storage = storage
        self.repository = repository
        self.bucket = bucket
        self.retention_days = retention_days

    async def store(
        self,
        content: bytes,
        *,
        platform: str,
        captured_at: datetime,
        video_id: str | int,
        run_id: UUID,
        artifact_name: str,
        content_type: str,
        compression: str | None = None,
        artifact_type: str | None = None,
        database_video_id: int | None = None,
    ) -> RawArtifactRef:
        captured = (
            captured_at.astimezone(UTC) if captured_at.tzinfo else captured_at.replace(tzinfo=UTC)
        )
        db_time = captured.replace(tzinfo=None)
        digest = hashlib.sha256(content).hexdigest()
        compression_value = compression or "identity"
        final_key = build_object_key(platform, captured, video_id, run_id, artifact_name)
        expires_at = db_time + timedelta(days=self.retention_days) if self.retention_days else None
        artifact_id = await self.repository.create_pending(
            PendingArtifact(
                crawl_run_id=run_id,
                video_id=database_video_id,
                artifact_type=artifact_type or artifact_name,
                bucket=self.bucket,
                object_key=final_key,
                content_type=content_type,
                compression=compression_value,
                sha256=digest,
                size_bytes=len(content),
                captured_at=db_time,
                expires_at=expires_at,
            )
        )
        temp_key = f".tmp/{run_id}/{artifact_id}"

        try:
            stat = await self.storage.put(
                self.bucket,
                temp_key,
                content,
                content_type=content_type,
                compression=compression_value,
                sha256=digest,
            )
            if stat.size != len(content) or _metadata_digest(stat.metadata) != digest:
                raise ValueError("uploaded artifact failed size or SHA-256 verification")
            final_stat = await self.storage.copy(self.bucket, temp_key, final_key)
            await self.storage.remove(self.bucket, temp_key)
            if final_stat.size != len(content) or _metadata_digest(final_stat.metadata) != digest:
                raise ValueError("promoted artifact failed size or SHA-256 verification")
        except Exception:
            await self.repository.mark_upload_failed(artifact_id, db_time)
            raise

        await self.repository.mark_available(artifact_id, final_stat.etag, db_time)
        return RawArtifactRef(
            id=artifact_id,
            bucket=self.bucket,
            object_key=final_key,
            etag=final_stat.etag,
            sha256=digest,
            size_bytes=len(content),
            content_type=content_type,
            compression=compression_value,
        )

    async def cleanup_expired(
        self,
        now: datetime,
        *,
        temporary_stale_before: datetime | None = None,
    ) -> CleanupSummary:
        current = now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo else now
        temporary_cutoff_value = temporary_stale_before or now
        temporary_cutoff = (
            temporary_cutoff_value.astimezone(UTC).replace(tzinfo=None)
            if temporary_cutoff_value.tzinfo
            else temporary_cutoff_value
        )
        rows = () if self.retention_days == 0 else await self.repository.list_expired(current)
        expired = 0
        delete_failed = 0
        for row in rows:
            try:
                await self.storage.remove(row.bucket, row.object_key)
            except Exception:
                delete_failed += 1
                status = "delete_failed"
            else:
                expired += 1
                status = "expired"
            await self.repository.mark_deleted(row.id, status=status, now=current)

        temporary_deleted = 0
        for item in await self.storage.list(self.bucket, ".tmp/"):
            if item.last_modified is None:
                continue
            modified = (
                item.last_modified.astimezone(UTC)
                if item.last_modified.tzinfo
                else item.last_modified.replace(tzinfo=UTC)
            )
            if modified.replace(tzinfo=None) <= temporary_cutoff:
                try:
                    await self.storage.remove(self.bucket, item.object_name)
                except Exception:
                    removed = False
                else:
                    removed = True
                if removed:
                    temporary_deleted += 1
        return CleanupSummary(expired, delete_failed, temporary_deleted)


def _metadata_digest(metadata: Mapping[str, str]) -> str:
    return metadata.get("X-Amz-Meta-Sha256", metadata.get("x-amz-meta-sha256", ""))
