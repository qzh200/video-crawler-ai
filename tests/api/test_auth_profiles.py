from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from video_crawler.api.dependencies.auth import require_api_key
from video_crawler.api.schemas.auth_profiles import (
    AuthProfileCreateRequest,
    AuthProfileResponse,
)
from video_crawler.main import create_app

PROFILE_ID = UUID("01900000-0000-7000-8000-000000000010")
NOW = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)


class UnusedJobService:
    pass


class RecordingProfileService:
    def __init__(self) -> None:
        self.profile: AuthProfileResponse | None = None
        self.calls: list[str] = []

    async def create(self, request: AuthProfileCreateRequest) -> AuthProfileResponse:
        self.calls.append("create")
        self.profile = AuthProfileResponse(
            profile_id=PROFILE_ID,
            platform=request.platform,
            profile_name=request.profile_name,
            profile_directory=request.profile_directory,
            status="active",
            last_verified_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        return self.profile

    async def list(self) -> tuple[AuthProfileResponse, ...]:
        self.calls.append("list")
        return (self.profile,) if self.profile is not None else ()

    async def get(self, profile_id: UUID) -> AuthProfileResponse | None:
        self.calls.append("get")
        return self.profile if profile_id == PROFILE_ID else None

    async def verify(self, profile_id: UUID) -> AuthProfileResponse | None:
        self.calls.append("verify")
        if self.profile is None or profile_id != PROFILE_ID:
            return None
        self.profile = self.profile.model_copy(
            update={"status": "active", "last_verified_at": NOW, "updated_at": NOW}
        )
        return self.profile

    async def enable(self, profile_id: UUID) -> AuthProfileResponse | None:
        self.calls.append("enable")
        if self.profile is None or profile_id != PROFILE_ID:
            return None
        self.profile = self.profile.model_copy(update={"status": "active"})
        return self.profile

    async def disable(self, profile_id: UUID) -> AuthProfileResponse | None:
        self.calls.append("disable")
        if self.profile is None or profile_id != PROFILE_ID:
            return None
        self.profile = self.profile.model_copy(update={"status": "disabled"})
        return self.profile


def _client() -> tuple[TestClient, RecordingProfileService]:
    profiles = RecordingProfileService()
    app = create_app(job_service=UnusedJobService(), profile_service=profiles)
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app), profiles


def test_create_rejects_unsafe_profile_directory_with_structured_error() -> None:
    client, profiles = _client()

    response = client.post(
        "/api/v1/auth-profiles",
        json={
            "platform": "example",
            "profile_name": "main",
            "profile_directory": "../escape",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert profiles.calls == []


def test_profile_endpoints_never_return_browser_state() -> None:
    client, profiles = _client()
    created = client.post(
        "/api/v1/auth-profiles",
        json={
            "platform": "example",
            "profile_name": "main",
            "profile_directory": "example-main",
        },
    )

    assert created.status_code == 201
    assert "cookie" not in created.text.lower()
    profile_id = created.json()["profile_id"]
    assert client.get("/api/v1/auth-profiles").status_code == 200
    assert client.get(f"/api/v1/auth-profiles/{profile_id}").status_code == 200
    assert client.post(f"/api/v1/auth-profiles/{profile_id}/verify").status_code == 200
    disabled = client.post(f"/api/v1/auth-profiles/{profile_id}/disable")
    assert disabled.json()["status"] == "disabled"
    enabled = client.post(f"/api/v1/auth-profiles/{profile_id}/enable")
    assert enabled.json()["status"] == "active"
    assert profiles.calls == ["create", "list", "get", "verify", "disable", "enable"]


def test_missing_profile_returns_structured_not_found() -> None:
    client, _ = _client()

    response = client.get("/api/v1/auth-profiles/01900000-0000-7000-8000-000000000099")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROFILE_NOT_FOUND"
