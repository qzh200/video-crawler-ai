from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from video_crawler.api.dependencies.auth import require_api_key
from video_crawler.application.jobs import (
    IdempotencyConflictError,
    IdempotencyReservation,
    JobCreateResult,
    JobRecord,
    JobService,
)
from video_crawler.domain.strategy import CrawlStrategy
from video_crawler.main import create_app

PROFILE_ID = UUID("01900000-0000-7000-8000-000000000001")
FIRST_JOB_ID = UUID("01900000-0000-7000-8000-000000000002")
SECOND_JOB_ID = UUID("01900000-0000-7000-8000-000000000003")
THIRD_JOB_ID = UUID("01900000-0000-7000-8000-000000000004")
NOW = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)


class InMemoryJobStore:
    def __init__(self) -> None:
        self.jobs: dict[UUID, JobRecord] = {}
        self.idempotency: dict[str, tuple[str, UUID, datetime]] = {}
        self.resume_reset_jobs: list[UUID] = []

    async def create(
        self,
        record: JobRecord,
        reservation: IdempotencyReservation | None,
    ) -> JobCreateResult:
        if reservation is not None:
            existing = self.idempotency.get(reservation.key)
            if existing is not None and existing[2] > reservation.created_at:
                request_hash, job_id, _ = existing
                if request_hash != reservation.request_hash:
                    raise IdempotencyConflictError
                return JobCreateResult(record=self.jobs[job_id], created=False)
        self.jobs[record.id] = record
        if reservation is not None:
            self.idempotency[reservation.key] = (
                reservation.request_hash,
                record.id,
                reservation.expires_at,
            )
        return JobCreateResult(record=record, created=True)

    async def get(self, job_id: UUID) -> JobRecord | None:
        return self.jobs.get(job_id)

    async def save(
        self,
        record: JobRecord,
        *,
        reset_incomplete_modules: bool = False,
    ) -> JobRecord:
        self.jobs[record.id] = record
        if reset_incomplete_modules:
            self.resume_reset_jobs.append(record.id)
        return record


class UnusedProfileService:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"profile service method should not be called: {name}")


class InMemoryProfileStates:
    def __init__(self, states: dict[UUID, str] | None = None) -> None:
        self.states = states if states is not None else {PROFILE_ID: "active"}

    async def get_status(self, profile_id: UUID) -> str | None:
        return self.states.get(profile_id)


def _client(
    store: InMemoryJobStore | None = None,
    profile_states: InMemoryProfileStates | None = None,
) -> tuple[TestClient, InMemoryJobStore]:
    job_store = store or InMemoryJobStore()
    states = profile_states or InMemoryProfileStates()
    ids = iter((FIRST_JOB_ID, SECOND_JOB_ID, THIRD_JOB_ID))
    service = JobService(
        store=job_store,
        profile_states=states,
        default_strategy=CrawlStrategy(),
        idempotency_ttl=timedelta(hours=24),
        clock=lambda: NOW,
        id_factory=lambda: next(ids),
    )
    app = create_app(job_service=service, profile_service=UnusedProfileService())
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app), job_store


def _valid_request() -> dict[str, object]:
    return {
        "source_url": "https://example.test/videos/1",
        "auth_profile_id": str(PROFILE_ID),
        "video_limit": 100,
        "strategy": {"max_retries": 3},
    }


@pytest.mark.parametrize(
    ("states", "expected_status", "expected_code"),
    [
        ({}, 404, "PROFILE_NOT_FOUND"),
        ({PROFILE_ID: "expired"}, 409, "PROFILE_NOT_ACTIVE"),
        ({PROFILE_ID: "disabled"}, 409, "PROFILE_NOT_ACTIVE"),
    ],
)
def test_create_requires_an_active_profile(
    states: dict[UUID, str],
    expected_status: int,
    expected_code: str,
) -> None:
    client, store = _client(profile_states=InMemoryProfileStates(states))

    response = client.post(
        "/api/v1/crawl-jobs",
        json=_valid_request(),
        headers={"Idempotency-Key": "inactive-profile"},
    )

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert store.jobs == {}
    assert store.idempotency == {}


def test_create_rejects_video_limit_above_500_with_structured_error() -> None:
    client, _ = _client()
    payload = _valid_request()
    payload["video_limit"] = 501

    response = client.post("/api/v1/crawl-jobs", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_create_rejects_invalid_delay_order_with_structured_error() -> None:
    client, _ = _client()
    payload = _valid_request()
    payload["strategy"] = {
        "video_delay_min_seconds": 4.0,
        "video_delay_max_seconds": 2.0,
    }

    response = client.post("/api/v1/crawl-jobs", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_pending_job_cannot_be_resumed() -> None:
    client, _ = _client()
    created = client.post("/api/v1/crawl-jobs", json=_valid_request())

    response = client.post(f"/api/v1/crawl-jobs/{created.json()['job_id']}/resume", json={})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JOB_NOT_RESUMABLE"


def test_create_get_cancel_and_resume_keep_one_logical_job() -> None:
    client, store = _client()
    created = client.post("/api/v1/crawl-jobs", json=_valid_request())
    job_id = UUID(created.json()["job_id"])

    assert created.status_code == 202
    assert created.json()["status"] == "pending"
    assert created.json()["effective_strategy"]["video_limit"] == 100
    fetched = client.get(f"/api/v1/crawl-jobs/{job_id}")
    assert fetched.status_code == 200
    assert fetched.json()["source_url"] == "https://example.test/videos/1"
    assert {
        "progress",
        "module_states",
        "started_at",
        "finished_at",
        "error",
    } <= fetched.json().keys()

    cancelled = client.post(f"/api/v1/crawl-jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    resumed = client.post(
        f"/api/v1/crawl-jobs/{job_id}/resume",
        json={"strategy": {"max_retries": 2, "request_timeout_seconds": 60}},
    )
    assert resumed.status_code == 200
    assert UUID(resumed.json()["job_id"]) == job_id
    assert resumed.json()["status"] == "pending"
    assert resumed.json()["effective_strategy"]["max_retries"] == 2
    assert resumed.json()["effective_strategy"]["request_timeout_seconds"] == 60
    assert store.resume_reset_jobs == [job_id]


def test_idempotency_key_replays_same_request_and_rejects_different_request() -> None:
    client, _ = _client()
    headers = {"Idempotency-Key": "job-request-1"}

    first = client.post("/api/v1/crawl-jobs", json=_valid_request(), headers=headers)
    replay = client.post("/api/v1/crawl-jobs", json=_valid_request(), headers=headers)
    changed_payload = _valid_request()
    changed_payload["video_limit"] = 20
    conflict = client.post(
        "/api/v1/crawl-jobs",
        json=changed_payload,
        headers=headers,
    )

    assert first.status_code == 202
    assert replay.status_code == 200
    assert replay.json()["job_id"] == first.json()["job_id"]
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_terminal_job_cannot_be_cancelled() -> None:
    client, store = _client()
    created = client.post("/api/v1/crawl-jobs", json=_valid_request())
    job_id = UUID(created.json()["job_id"])
    store.jobs[job_id] = replace(store.jobs[job_id], status="success")

    response = client.post(f"/api/v1/crawl-jobs/{job_id}/cancel")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JOB_NOT_CANCELLABLE"
