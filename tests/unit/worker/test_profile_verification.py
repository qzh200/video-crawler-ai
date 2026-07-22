from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from video_crawler.infrastructure.database.repositories.profile_verifications import (
    ClaimedProfileVerification,
)
from video_crawler.worker.profile_verification import ProfileVerificationRunner

VERIFICATION_ID = UUID("01900000-0000-7000-8000-000000000021")
PROFILE_ID = UUID("01900000-0000-7000-8000-000000000022")
NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


class FakeVerificationStore:
    def __init__(self) -> None:
        self.claimed = False
        self.events: list[tuple[object, ...]] = []

    async def claim_next(
        self,
        worker_id: str,
        now: datetime,
        *,
        stale_before: datetime,
    ) -> ClaimedProfileVerification | None:
        self.events.append(("claim", worker_id, now, stale_before))
        if self.claimed:
            return None
        self.claimed = True
        return ClaimedProfileVerification(
            verification_id=VERIFICATION_ID,
            profile_id=PROFILE_ID,
            platform="example",
            profile_directory="example-main",
            worker_id=worker_id,
        )

    async def record_process(
        self,
        verification_id: UUID,
        pid: int,
        process_group_id: int,
        now: datetime,
    ) -> bool:
        self.events.append(("record_process", verification_id, pid, process_group_id, now))
        return True

    async def heartbeat(self, verification_id: UUID, now: datetime) -> bool:
        self.events.append(("heartbeat", verification_id, now))
        return True

    async def mark_failed(
        self,
        verification_id: UUID,
        error_code: str,
        error_message: str,
        now: datetime,
    ) -> bool:
        self.events.append(
            ("mark_failed", verification_id, error_code, error_message, now)
        )
        return True


class FakeProcess:
    pid = 4321
    process_group_id = 4321

    def __init__(self, poll_results: list[int | None]) -> None:
        self._poll_results = iter(poll_results)
        self.returncode: int | None = None
        self.wait_calls: list[float | None] = []

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        result = next(self._poll_results)
        if result is not None:
            self.returncode = result
        return result

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        if self.returncode is None:
            self.returncode = -15
        return self.returncode


def _runner(
    store: FakeVerificationStore,
    process: FakeProcess,
    *,
    clock: object = None,
    terminate: object = None,
) -> ProfileVerificationRunner:
    async def no_wait(_: float) -> None:
        return None

    return ProfileVerificationRunner(
        worker_id="worker-1",
        states=store,
        process_factory=lambda verification_id: process,
        terminate_group=terminate or (lambda *_: "SIGTERM"),  # type: ignore[arg-type]
        clock=clock or (lambda: NOW),  # type: ignore[arg-type]
        sleep=no_wait,
        poll_interval_seconds=0.01,
        heartbeat_interval_seconds=5.0,
        stale_after_seconds=30.0,
        timeout_seconds=120.0,
        terminate_grace_seconds=2.0,
        kill_timeout_seconds=3.0,
    )


@pytest.mark.asyncio
async def test_runner_records_process_and_heartbeats_until_success() -> None:
    store = FakeVerificationStore()
    process = FakeProcess([None, 0])

    assert await _runner(store, process).run_once() is True

    assert ("record_process", VERIFICATION_ID, 4321, 4321, NOW) in store.events
    assert ("heartbeat", VERIFICATION_ID, NOW) in store.events
    assert not any(event[0] == "mark_failed" for event in store.events)


@pytest.mark.asyncio
async def test_runner_records_sanitized_child_failure() -> None:
    store = FakeVerificationStore()
    process = FakeProcess([1])

    assert await _runner(store, process).run_once() is True

    assert (
        "mark_failed",
        VERIFICATION_ID,
        "PROFILE_VERIFICATION_PROCESS_FAILED",
        "Profile verification process failed",
        NOW,
    ) in store.events


@pytest.mark.asyncio
async def test_runner_terminates_timed_out_process_group() -> None:
    store = FakeVerificationStore()
    process = FakeProcess([None])
    times = iter([NOW, NOW, NOW + timedelta(seconds=121), NOW + timedelta(seconds=121)])
    terminations: list[tuple[int, float, float]] = []

    def terminate(process_group_id: int, grace: float, kill_timeout: float) -> str:
        terminations.append((process_group_id, grace, kill_timeout))
        process.returncode = -15
        return "SIGTERM"

    assert await _runner(
        store,
        process,
        clock=lambda: next(times),
        terminate=terminate,
    ).run_once()

    assert terminations == [(4321, 2.0, 3.0)]
    assert process.wait_calls == [3.0]
    assert any(
        event[0:4]
        == (
            "mark_failed",
            VERIFICATION_ID,
            "PROFILE_VERIFICATION_TIMEOUT",
            "Profile verification timed out",
        )
        for event in store.events
    )

