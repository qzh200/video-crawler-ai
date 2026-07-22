from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from video_crawler.infrastructure.database.repositories.profile_verifications import (
    ClaimedProfileVerification,
)
from video_crawler.infrastructure.process.groups import (
    spawn_profile_verification_process,
    terminate_process_group,
)
from video_crawler.worker.supervisor import ProcessHandle


class ProfileVerificationStateStore(Protocol):
    async def claim_next(
        self,
        worker_id: str,
        now: datetime,
        *,
        stale_before: datetime,
    ) -> ClaimedProfileVerification | None: ...

    async def record_process(
        self,
        verification_id: UUID,
        pid: int,
        process_group_id: int,
        now: datetime,
    ) -> bool: ...

    async def heartbeat(self, verification_id: UUID, now: datetime) -> bool: ...

    async def mark_failed(
        self,
        verification_id: UUID,
        error_code: str,
        error_message: str,
        now: datetime,
    ) -> bool: ...


ProcessFactory = Callable[[UUID], ProcessHandle]
TerminateGroup = Callable[[int, float, float], str]
Clock = Callable[[], datetime]
Sleep = Callable[[float], Awaitable[None]]


class ProfileVerificationRunner:
    """Claim and supervise one isolated Profile verification process."""

    def __init__(
        self,
        *,
        worker_id: str,
        states: ProfileVerificationStateStore,
        process_factory: ProcessFactory = spawn_profile_verification_process,
        terminate_group: TerminateGroup = terminate_process_group,
        clock: Clock | None = None,
        sleep: Sleep = asyncio.sleep,
        poll_interval_seconds: float,
        heartbeat_interval_seconds: float,
        stale_after_seconds: float,
        timeout_seconds: float,
        terminate_grace_seconds: float,
        kill_timeout_seconds: float,
    ) -> None:
        if (
            min(
                poll_interval_seconds,
                heartbeat_interval_seconds,
                stale_after_seconds,
                timeout_seconds,
                kill_timeout_seconds,
            )
            <= 0
        ):
            raise ValueError("Profile verification intervals must be positive")
        if terminate_grace_seconds < 0:
            raise ValueError("Profile verification grace period cannot be negative")
        self._worker_id = worker_id
        self._states = states
        self._process_factory = process_factory
        self._terminate_group = terminate_group
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleep = sleep
        self._poll_interval_seconds = poll_interval_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._stale_after_seconds = stale_after_seconds
        self._timeout_seconds = timeout_seconds
        self._terminate_grace_seconds = terminate_grace_seconds
        self._kill_timeout_seconds = kill_timeout_seconds

    async def run_once(self) -> bool:
        started_at = self._clock()
        claimed = await self._states.claim_next(
            self._worker_id,
            started_at,
            stale_before=started_at - timedelta(seconds=self._stale_after_seconds),
        )
        if claimed is None:
            return False
        process = self._process_factory(claimed.verification_id)
        await self._states.record_process(
            claimed.verification_id,
            process.pid,
            process.process_group_id,
            self._clock(),
        )
        await self._supervise(claimed.verification_id, process, started_at)
        return True

    async def _supervise(
        self,
        verification_id: UUID,
        process: ProcessHandle,
        started_at: datetime,
    ) -> None:
        deadline = started_at + timedelta(seconds=self._timeout_seconds)
        next_heartbeat = started_at
        while True:
            returncode = process.poll()
            if returncode is not None:
                if returncode != 0:
                    await self._states.mark_failed(
                        verification_id,
                        "PROFILE_VERIFICATION_PROCESS_FAILED",
                        "Profile verification process failed",
                        self._clock(),
                    )
                return

            now = self._clock()
            if now >= deadline:
                self._terminate_group(
                    process.process_group_id,
                    self._terminate_grace_seconds,
                    self._kill_timeout_seconds,
                )
                process.wait(timeout=self._kill_timeout_seconds)
                await self._states.mark_failed(
                    verification_id,
                    "PROFILE_VERIFICATION_TIMEOUT",
                    "Profile verification timed out",
                    self._clock(),
                )
                return
            if now >= next_heartbeat:
                await self._states.heartbeat(verification_id, now)
                next_heartbeat = now + timedelta(seconds=self._heartbeat_interval_seconds)
            await self._sleep(self._poll_interval_seconds)
