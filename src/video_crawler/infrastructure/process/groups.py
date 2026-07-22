from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID


class _PosixProcessApi(Protocol):
    WNOHANG: int

    def killpg(self, process_group_id: int, requested_signal: int) -> None: ...

    def waitpid(self, pid: int, options: int) -> tuple[int, int]: ...


_POSIX = cast(_PosixProcessApi, os)


@dataclass(frozen=True, slots=True)
class SupervisedProcess:
    """A task subprocess and the isolated process group that owns its descendants."""

    process: subprocess.Popen[bytes]
    process_group_id: int

    @property
    def pid(self) -> int:
        return self.process.pid

    def poll(self) -> int | None:
        return self.process.poll()

    def wait(self, timeout: float | None = None) -> int:
        return self.process.wait(timeout=timeout)


def spawn_task_process(run_id: UUID) -> SupervisedProcess:
    """Start one crawl run as an isolated process-group leader."""

    process = subprocess.Popen(  # noqa: S603 - fixed interpreter and module entrypoint
        [
            sys.executable,
            "-m",
            "video_crawler.worker.task_entrypoint",
            str(run_id),
        ],
        shell=False,
        start_new_session=True,
    )
    return SupervisedProcess(process=process, process_group_id=process.pid)


def terminate_process_group(
    process_group_id: int,
    grace_seconds: float,
    kill_timeout_seconds: float,
) -> str:
    """Terminate a complete POSIX process group, escalating to SIGKILL if needed."""

    if os.name != "posix":
        raise NotImplementedError("process-group termination requires a POSIX platform")
    if process_group_id <= 0:
        raise ValueError("process group id must be positive")
    if grace_seconds < 0 or kill_timeout_seconds <= 0:
        raise ValueError("termination timeouts are invalid")

    if not _send_group_signal(process_group_id, signal.SIGTERM):
        return signal.SIGTERM.name
    if _wait_for_group_exit(process_group_id, grace_seconds):
        return signal.SIGTERM.name

    sigkill = int(getattr(signal, "SIGKILL", 9))
    if not _send_group_signal(process_group_id, sigkill):
        return "SIGKILL"
    if _wait_for_group_exit(process_group_id, kill_timeout_seconds):
        return "SIGKILL"
    raise TimeoutError(f"process group {process_group_id} did not exit after SIGKILL")


def _send_group_signal(process_group_id: int, requested_signal: int) -> bool:
    try:
        _POSIX.killpg(process_group_id, requested_signal)
    except ProcessLookupError:
        return False
    return True


def _wait_for_group_exit(process_group_id: int, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while True:
        _reap_group_leader(process_group_id)
        try:
            _POSIX.killpg(process_group_id, 0)
        except ProcessLookupError:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))


def _reap_group_leader(process_group_id: int) -> None:
    try:
        _POSIX.waitpid(process_group_id, _POSIX.WNOHANG)
    except ChildProcessError:
        pass
