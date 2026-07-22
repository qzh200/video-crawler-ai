from __future__ import annotations

from fastapi.testclient import TestClient

from video_crawler.application.health import HealthService
from video_crawler.main import create_app


class FakeDatabaseProbe:
    def __init__(
        self,
        *,
        available: bool = True,
        revision: str | None = "0001",
    ) -> None:
        self.available = available
        self.revision = revision
        self.revision_checks = 0

    async def ping(self) -> None:
        if not self.available:
            raise ConnectionError("database credentials must not be returned")

    async def migration_revision(self) -> str | None:
        self.revision_checks += 1
        return self.revision


class FakeObjectStorageProbe:
    def __init__(self, *, available: bool = True, bucket_exists: bool = True) -> None:
        self.available = available
        self._bucket_exists = bucket_exists
        self.bucket_checks = 0

    async def ping(self) -> None:
        if not self.available:
            raise ConnectionError("object storage credentials must not be returned")

    async def bucket_exists(self, bucket: str) -> bool:
        assert bucket == "crawler-raw"
        self.bucket_checks += 1
        return self._bucket_exists


def _client(
    database: FakeDatabaseProbe | None = None,
    storage: FakeObjectStorageProbe | None = None,
) -> TestClient:
    service = HealthService(
        database=database or FakeDatabaseProbe(),
        object_storage=storage or FakeObjectStorageProbe(),
        expected_migration_revision="0001",
        bucket="crawler-raw",
    )
    return TestClient(create_app(health_service=service))


def test_liveness_is_public_and_remains_up_without_dependency_checks() -> None:
    database = FakeDatabaseProbe(available=False)
    storage = FakeObjectStorageProbe(available=False)

    response = _client(database, storage).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
    assert database.revision_checks == 0
    assert storage.bucket_checks == 0


def test_readiness_reports_all_healthy_components() -> None:
    response = _client().get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "components": {
            "mysql": {"status": "up"},
            "migration": {
                "status": "up",
                "current_revision": "0001",
                "expected_revision": "0001",
            },
            "minio": {"status": "up"},
            "bucket": {"status": "up", "name": "crawler-raw"},
        },
    }


def test_readiness_degrades_when_mysql_is_unavailable() -> None:
    database = FakeDatabaseProbe(available=False)

    response = _client(database=database).get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["components"]["mysql"] == {"status": "unavailable"}
    assert response.json()["components"]["migration"] == {"status": "not_checked"}
    assert database.revision_checks == 0
    assert "credentials" not in response.text


def test_readiness_degrades_when_migration_revision_mismatches() -> None:
    response = _client(database=FakeDatabaseProbe(revision="0000")).get("/health/ready")

    assert response.status_code == 503
    assert response.json()["components"]["migration"] == {
        "status": "mismatch",
        "current_revision": "0000",
        "expected_revision": "0001",
    }


def test_readiness_degrades_when_minio_is_unavailable() -> None:
    storage = FakeObjectStorageProbe(available=False)

    response = _client(storage=storage).get("/health/ready")

    assert response.status_code == 503
    assert response.json()["components"]["minio"] == {"status": "unavailable"}
    assert response.json()["components"]["bucket"] == {"status": "not_checked"}
    assert storage.bucket_checks == 0
    assert "credentials" not in response.text


def test_readiness_degrades_when_bucket_is_missing() -> None:
    response = _client(storage=FakeObjectStorageProbe(bucket_exists=False)).get("/health/ready")

    assert response.status_code == 503
    assert response.json()["components"]["bucket"] == {
        "status": "missing",
        "name": "crawler-raw",
    }
