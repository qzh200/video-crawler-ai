from __future__ import annotations

from datetime import UTC, datetime
from types import MethodType, SimpleNamespace
from uuid import UUID

import pytest

from video_crawler.bootstrap import ApplicationContainer
from video_crawler.infrastructure.database.repositories.profile_verifications import (
    ClaimedProfileVerification,
)
from video_crawler.worker.profile_verification import ProfileVerificationRunner

VERIFICATION_ID = UUID("01900000-0000-7000-8000-000000000021")
PROFILE_ID = UUID("01900000-0000-7000-8000-000000000022")
NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
EXECUTION = ClaimedProfileVerification(
    verification_id=VERIFICATION_ID,
    profile_id=PROFILE_ID,
    platform="example",
    profile_directory="example-main",
    worker_id="worker-1",
)


class FakeRepository:
    def __init__(self, execution: ClaimedProfileVerification | None = EXECUTION) -> None:
        self.execution = execution
        self.events: list[tuple[object, ...]] = []

    async def load_execution(
        self, verification_id: UUID
    ) -> ClaimedProfileVerification | None:
        self.events.append(("load", verification_id))
        return self.execution

    async def mark_succeeded(
        self,
        verification_id: UUID,
        *,
        is_valid: bool,
        now: datetime,
    ) -> bool:
        self.events.append(("succeeded", verification_id, is_valid, now))
        return True

    async def mark_failed(
        self,
        verification_id: UUID,
        error_code: str,
        error_message: str,
        now: datetime,
    ) -> bool:
        self.events.append(("failed", verification_id, error_code, error_message, now))
        return True


def _container(repository: FakeRepository, verifier: object) -> ApplicationContainer:
    container = object.__new__(ApplicationContainer)
    container.profile_verifications = repository  # type: ignore[assignment]
    container._verify_profile_execution = MethodType(verifier, container)  # type: ignore[attr-defined,arg-type]
    return container


@pytest.mark.asyncio
@pytest.mark.parametrize("is_valid", [True, False])
async def test_execute_verification_persists_adapter_result(is_valid: bool) -> None:
    repository = FakeRepository()

    async def verify(
        container: ApplicationContainer,
        execution: ClaimedProfileVerification,
    ) -> bool:
        del container
        assert execution == EXECUTION
        return is_valid

    await _container(repository, verify).execute_profile_verification(VERIFICATION_ID)

    assert repository.events[0] == ("load", VERIFICATION_ID)
    assert repository.events[1][0:3] == ("succeeded", VERIFICATION_ID, is_valid)


@pytest.mark.asyncio
async def test_execute_verification_sanitizes_unexpected_failure() -> None:
    repository = FakeRepository()

    async def fail(
        container: ApplicationContainer,
        execution: ClaimedProfileVerification,
    ) -> bool:
        del container, execution
        raise RuntimeError("sensitive browser detail")

    with pytest.raises(RuntimeError, match="sensitive browser detail"):
        await _container(repository, fail).execute_profile_verification(VERIFICATION_ID)

    assert repository.events[1][0:4] == (
        "failed",
        VERIFICATION_ID,
        "PROFILE_VERIFICATION_FAILED",
        "Profile verification failed",
    )


def test_production_supervisor_prioritizes_profile_verification_runner() -> None:
    container = object.__new__(ApplicationContainer)
    container.settings = SimpleNamespace(
        worker_id="worker-1",
        worker_poll_interval_seconds=2.0,
        worker_heartbeat_interval_seconds=5.0,
        worker_stale_after_seconds=30.0,
        task_terminate_grace_seconds=5,
        task_kill_timeout_seconds=10,
        default_page_timeout_seconds=60,
    )
    container.worker_states = SimpleNamespace()
    container.leases = SimpleNamespace()
    container.profile_verifications = SimpleNamespace()

    supervisor = container.create_supervisor()

    assert isinstance(supervisor._auxiliary_runner, ProfileVerificationRunner)
    assert supervisor._auxiliary_runner._timeout_seconds == 135

