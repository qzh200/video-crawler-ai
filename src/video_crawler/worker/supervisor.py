from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from video_crawler.infrastructure.process.groups import spawn_task_process, terminate_process_group


@dataclass(frozen=True, slots=True)
class ClaimedWork:
    job_id: UUID
    auth_profile_id: UUID
    attempt_no: int


class WorkerStateStore(Protocol):
    async def claim_next(self, worker_id: str, now: datetime) -> ClaimedWork | None: ...

    async def create_run(
        self,
        work: ClaimedWork,
        worker_id: str,
        now: datetime,
    ) -> UUID: ...

    async def record_process(
        self,
        job_id: UUID,
        run_id: UUID,
        pid: int,
        process_group_id: int,
        now: datetime,
    ) -> None: ...

    async def is_cancel_requested(self, job_id: UUID) -> bool: ...

    async def heartbeat(self, job_id: UUID, run_id: UUID, now: datetime) -> None: ...

    async def mark_cancelling(self, job_id: UUID, run_id: UUID, now: datetime) -> None: ...

    async def mark_cancelled(
        self,
        job_id: UUID,
        run_id: UUID,
        termination_signal: str,
        now: datetime,
    ) -> None: ...

    async def mark_finished(
        self,
        job_id: UUID,
        run_id: UUID,
        status: str,
        now: datetime,
    ) -> None: ...


class ProfileLeaseGateway(Protocol):
    async def acquire(
        self,
        auth_profile_id: UUID,
        worker_id: str,
        crawl_run_id: UUID,
        now: datetime,
        *,
        process_pid: int | None = None,
    ) -> bool: ...

    async def heartbeat(
        self,
        auth_profile_id: UUID,
        crawl_run_id: UUID,
        now: datetime,
        *,
        process_pid: int | None = None,
    ) -> bool: ...

    async def release(self, auth_profile_id: UUID, crawl_run_id: UUID) -> bool: ...


class ProcessHandle(Protocol):
    @property
    def pid(self) -> int: ...

    @property
    def process_group_id(self) -> int: ...

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...


ProcessFactory = Callable[[UUID], ProcessHandle]
TerminateGroup = Callable[[int, float, float], str]
Clock = Callable[[], datetime]
Sleep = Callable[[float], Awaitable[None]]


def _default_process_factory(run_id: UUID) -> ProcessHandle:
    return spawn_task_process(run_id)


class WorkerSupervisor:
    """Claim and supervise at most one isolated crawl task process at a time."""

    def __init__(
        self,
        *,
        worker_id: str,
        states: WorkerStateStore,
        leases: ProfileLeaseGateway,
        process_factory: ProcessFactory = _default_process_factory,
        terminate_group: TerminateGroup = terminate_process_group,
        clock: Clock | None = None,
        sleep: Sleep = asyncio.sleep,
        poll_interval_seconds: float,
        heartbeat_interval_seconds: float,
        terminate_grace_seconds: float,
        kill_timeout_seconds: float,
    ) -> None:
        if poll_interval_seconds <= 0 or heartbeat_interval_seconds <= 0:
            raise ValueError("worker intervals must be positive")
        if terminate_grace_seconds < 0 or kill_timeout_seconds <= 0:
            raise ValueError("worker termination timeouts are invalid")
        self._worker_id = worker_id
        self._states = states
        self._leases = leases
        self._process_factory = process_factory
        self._terminate_group = terminate_group
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleep = sleep
        self._poll_interval_seconds = poll_interval_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._terminate_grace_seconds = terminate_grace_seconds
        self._kill_timeout_seconds = kill_timeout_seconds

    async def run_forever(self) -> None:
        while True:
            handled = await self.run_once()
            if not handled:
                await self._sleep(self._poll_interval_seconds)

    async def run_once(self) -> bool:
        now = self._clock()
        work = await self._states.claim_next(self._worker_id, now)
        if work is None:
            return False
        run_id = await self._states.create_run(work, self._worker_id, now)
        lease_acquired = await self._leases.acquire(
            work.auth_profile_id,
            self._worker_id,
            run_id,
            now,
        )
        if not lease_acquired:
            await self._states.mark_finished(work.job_id, run_id, "failed", self._clock())
            return True

        try:
            process = self._process_factory(run_id)
            await self._states.record_process(
                work.job_id,
                run_id,
                process.pid,
                process.process_group_id,
                self._clock(),
            )
            await self._supervise_process(work, run_id, process)
        finally:
            await self._leases.release(work.auth_profile_id, run_id)
        return True

    async def _supervise_process(
        self,
        work: ClaimedWork,
        run_id: UUID,
        process: ProcessHandle,
    ) -> None:
        next_heartbeat = self._clock()
        while True:
            returncode = process.poll()
            if returncode is not None:
                status = "success" if returncode == 0 else "failed"
                await self._states.mark_finished(work.job_id, run_id, status, self._clock())
                return

            if await self._states.is_cancel_requested(work.job_id):
                await self._states.mark_cancelling(work.job_id, run_id, self._clock())
                termination_signal = self._terminate_group(
                    process.process_group_id,
                    self._terminate_grace_seconds,
                    self._kill_timeout_seconds,
                )
                process.wait(timeout=self._kill_timeout_seconds)
                await self._states.mark_cancelled(
                    work.job_id,
                    run_id,
                    termination_signal,
                    self._clock(),
                )
                return

            now = self._clock()
            if now >= next_heartbeat:
                await self._states.heartbeat(work.job_id, run_id, now)
                await self._leases.heartbeat(
                    work.auth_profile_id,
                    run_id,
                    now,
                    process_pid=process.pid,
                )
                next_heartbeat = now + timedelta(seconds=self._heartbeat_interval_seconds)
            await self._sleep(self._poll_interval_seconds)


def build_default_supervisor(
    *,
    worker_id: str,
    states: WorkerStateStore,
    leases: ProfileLeaseGateway,
    poll_interval_seconds: float,
    heartbeat_interval_seconds: float,
    terminate_grace_seconds: float,
    kill_timeout_seconds: float,
) -> WorkerSupervisor:
    return WorkerSupervisor(
        worker_id=worker_id,
        states=states,
        leases=leases,
        poll_interval_seconds=poll_interval_seconds,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        terminate_grace_seconds=terminate_grace_seconds,
        kill_timeout_seconds=kill_timeout_seconds,
    )
