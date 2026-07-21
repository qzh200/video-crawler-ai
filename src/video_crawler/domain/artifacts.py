from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Protocol
from uuid import UUID


class RawArtifactRef(Protocol):
    """Opaque reference returned by the raw-artifact gateway."""


class ObjectStat(Protocol):
    size: int
    etag: str
    metadata: Mapping[str, str]


class ObjectInfo(Protocol):
    object_name: str
    last_modified: datetime | None


class RawObjectStore(Protocol):
    async def put(
        self,
        bucket: str,
        object_key: str,
        content: bytes,
        *,
        content_type: str,
        compression: str,
        sha256: str,
    ) -> ObjectStat: ...

    async def copy(self, bucket: str, source_key: str, destination_key: str) -> ObjectStat: ...

    async def remove(self, bucket: str, object_key: str) -> None: ...

    async def list(self, bucket: str, prefix: str) -> tuple[ObjectInfo, ...]: ...


@dataclass(frozen=True, slots=True)
class PendingArtifact:
    crawl_run_id: UUID
    video_id: int | None
    artifact_type: str
    bucket: str
    object_key: str
    content_type: str
    compression: str
    sha256: str
    size_bytes: int
    captured_at: datetime
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class ExpiredArtifact:
    id: int
    bucket: str
    object_key: str


class RawArtifactRepository(Protocol):
    async def create_pending(self, artifact: PendingArtifact) -> int: ...

    async def mark_available(self, artifact_id: int, etag: str, now: datetime) -> None: ...

    async def mark_upload_failed(self, artifact_id: int, now: datetime) -> None: ...

    async def list_expired(self, now: datetime) -> tuple[ExpiredArtifact, ...]: ...

    async def mark_deleted(self, artifact_id: int, *, status: str, now: datetime) -> None: ...


def _safe_segment(value: str, label: str) -> str:
    normalized = value.strip()
    if (
        not normalized
        or normalized in {".", ".."}
        or any(char in normalized for char in "/\\?#")
        or any(ord(char) < 32 for char in normalized)
    ):
        raise ValueError(f"unsafe {label}")
    return normalized


def build_object_key(
    platform: str,
    captured_at: datetime,
    video_id: str | int,
    run_id: UUID | str,
    artifact_name: str,
) -> str:
    """Build a deterministic, secret-free object key."""

    timestamp = (
        captured_at.astimezone(UTC) if captured_at.tzinfo else captured_at.replace(tzinfo=UTC)
    )
    return str(
        PurePosixPath(
            _safe_segment(platform.lower(), "platform"),
            f"{timestamp.year:04d}",
            f"{timestamp.month:02d}",
            f"{timestamp.day:02d}",
            _safe_segment(str(video_id), "video id"),
            _safe_segment(str(run_id), "run id"),
            _safe_segment(artifact_name, "artifact name"),
        )
    )
