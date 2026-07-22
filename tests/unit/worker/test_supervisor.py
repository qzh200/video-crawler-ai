from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from video_crawler.worker.supervisor import ClaimedWork, WorkerSupervisor

JOB_ID = UUID("01900000-0000-7000-8000-000000000001")
RUN_ID = UUID("01900000-0000-7000-8000-000000000002")
PROFILE_ID = UUID("01900000-0000-7000-8000-000000000003")
NOW = datetime(2026, 7, 22, 9, 30, tzinfo=UTC)


class FakeStateStore:
    def __init__(self, *, cancel_requested: bool) -> None:
        self.cancel_requested = cancel_requested
        self.claimed = False
        self.events: list[tuple[object, ...]] = []

    async def claim_next(self, worker_id: str, now: datetime) -> ClaimedWork | None:
        self.events.append(("claim", worker_id, now))
        if self.claimed:
            return None
        self.claimed = True
        return ClaimedWork(
            job_id=JOB_ID,
            auth_profile_id=PROFILE_ID,
            attempt_no=1,
        )

    async def create_run(
        self,
        work: ClaimedWork,
        worker_id: str,
        now: datetime,
    ) -> UUID:
        self.events.append(("create_run", work.job_id, worker_id, now))
        return RUN_ID

    async def record_process(
        self,
        job_id: UUID,
        run_id: UUID,
        pid: int,
        process_group_id: int,
        now: datetime,
    ) -> None:
        self.events.append(("record_process", job_id, run_id, pid, process_group_id, now))

    async def is_cancel_requested(self, job_id: UUID) -> bool:
        self.events.append(("is_cancel_requested", job_id))
        return self.cancel_requested

    async def heartbeat(self, job_id: UUID, run_id: UUID, now: datetime) -> None:
        self.events.append(("heartbeat", job_id, run_id, now))

    async def mark_cancelling(self, job_id: UUID, run_id: UUID, now: datetime) -> None:
        self.events.append(("mark_cancelling", job_id, run_id, now))

    async def mark_cancelled(
        self,
        job_id: UUID,
        run_id: UUID,
        termination_signal: str,
        now: datetime,
    ) -> None:
        self.events.append(("mark_cancelled", job_id, run_id, termination_signal, now))

    async def mark_finished(
        self,
        job_id: UUID,
        run_id: UUID,
        status: str,
        now: datetime,
    ) -> None:
        self.events.append(("mark_finished", job_id, run_id, status, now))


class FakeLeaseService:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []

    async def acquire(
        self,
        auth_profile_id: UUID,
        worker_id: str,
        crawl_run_id: UUID,
        now: datetime,
        *,
        process_pid: int | None = None,
    ) -> bool:
        self.events.append(("acquire", auth_profile_id, worker_id, crawl_run_id, now, process_pid))
        return True

    async def heartbeat(
        self,
        auth_profile_id: UUID,
        crawl_run_id: UUID,
        now: datetime,
        *,
        process_pid: int | None = None,
    ) -> bool:
        self.events.append(("heartbeat", auth_profile_id, crawl_run_id, now, process_pid))
        return True

    async def release(self, auth_profile_id: UUID, crawl_run_id: UUID) -> bool:
        self.events.append(("release", auth_profile_id, crawl_run_id))
        return True


class FakeProcess:
    def __init__(self, poll_results: list[int | None]) -> None:
        self.pid = 4321
        self.process_group_id = 4321
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


@pytest.mark.asyncio
async def test_cancel_request_terminates_group_marks_cancelled_and_releases_lease() -> None:
    states = FakeStateStore(cancel_requested=True)
    leases = FakeLeaseService()
    process = FakeProcess([None])
    termination_calls: list[tuple[int, float, float]] = []

    def terminate(process_group_id: int, grace: float, kill_timeout: float) -> str:
        termination_calls.append((process_group_id, grace, kill_timeout))
        process.returncode = -15
        return "SIGTERM"

    supervisor = WorkerSupervisor(
        worker_id="worker-1",
        states=states,
        leases=leases,
        process_factory=lambda run_id: process,
        terminate_group=terminate,
        clock=lambda: NOW,
        poll_interval_seconds=0.01,
        heartbeat_interval_seconds=5.0,
        terminate_grace_seconds=1.5,
        kill_timeout_seconds=2.5,
    )

    assert await supervisor.run_once() is True

    assert termination_calls == [(4321, 1.5, 2.5)]
    assert ("mark_cancelling", JOB_ID, RUN_ID, NOW) in states.events
    assert ("mark_cancelled", JOB_ID, RUN_ID, "SIGTERM", NOW) in states.events
    assert leases.events[-1] == ("release", PROFILE_ID, RUN_ID)


@pytest.mark.asyncio
async def test_running_process_heartbeats_run_and_profile_lease() -> None:
    states = FakeStateStore(cancel_requested=False)
    leases = FakeLeaseService()
    process = FakeProcess([None, 0])

    async def no_wait(_: float) -> None:
        return None

    supervisor = WorkerSupervisor(
        worker_id="worker-1",
        states=states,
        leases=leases,
        process_factory=lambda run_id: process,
        terminate_group=lambda *_: "SIGTERM",
        clock=lambda: NOW,
        sleep=no_wait,
        poll_interval_seconds=5.0,
        heartbeat_interval_seconds=5.0,
        terminate_grace_seconds=1.0,
        kill_timeout_seconds=1.0,
    )

    assert await supervisor.run_once() is True

    assert ("heartbeat", JOB_ID, RUN_ID, NOW) in states.events
    assert ("heartbeat", PROFILE_ID, RUN_ID, NOW, 4321) in leases.events
    assert ("mark_finished", JOB_ID, RUN_ID, "success", NOW) in states.events
    assert leases.events[-1] == ("release", PROFILE_ID, RUN_ID)
