from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


class DatabaseHealthProbe(Protocol):
    async def ping(self) -> None: ...

    async def migration_revision(self) -> str | None: ...


class ObjectStorageHealthProbe(Protocol):
    async def ping(self) -> None: ...

    async def bucket_exists(self, bucket: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    status: str
    current_revision: str | None = None
    expected_revision: str | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    ready: bool
    components: Mapping[str, ComponentHealth]


class HealthService:
    def __init__(
        self,
        *,
        database: DatabaseHealthProbe,
        object_storage: ObjectStorageHealthProbe,
        expected_migration_revision: str,
        bucket: str,
    ) -> None:
        self._database = database
        self._object_storage = object_storage
        self._expected_migration_revision = expected_migration_revision
        self._bucket = bucket

    async def check_readiness(self) -> ReadinessReport:
        components: dict[str, ComponentHealth] = {}
        await self._check_database(components)
        await self._check_object_storage(components)
        ready = all(component.status == "up" for component in components.values())
        return ReadinessReport(ready=ready, components=components)

    async def _check_database(self, components: dict[str, ComponentHealth]) -> None:
        try:
            await self._database.ping()
        except Exception:
            components["mysql"] = ComponentHealth(status="unavailable")
            components["migration"] = ComponentHealth(status="not_checked")
            return

        components["mysql"] = ComponentHealth(status="up")
        try:
            current_revision = await self._database.migration_revision()
        except Exception:
            components["migration"] = ComponentHealth(status="unavailable")
            return

        status = "up" if current_revision == self._expected_migration_revision else "mismatch"
        components["migration"] = ComponentHealth(
            status=status,
            current_revision=current_revision,
            expected_revision=self._expected_migration_revision,
        )

    async def _check_object_storage(self, components: dict[str, ComponentHealth]) -> None:
        try:
            await self._object_storage.ping()
        except Exception:
            components["minio"] = ComponentHealth(status="unavailable")
            components["bucket"] = ComponentHealth(status="not_checked")
            return

        components["minio"] = ComponentHealth(status="up")
        try:
            bucket_exists = await self._object_storage.bucket_exists(self._bucket)
        except Exception:
            components["bucket"] = ComponentHealth(status="unavailable", name=self._bucket)
            return

        components["bucket"] = ComponentHealth(
            status="up" if bucket_exists else "missing",
            name=self._bucket,
        )
